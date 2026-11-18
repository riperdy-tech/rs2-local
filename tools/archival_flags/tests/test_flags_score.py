"""flags_score: the B3b scorer on synthetic data (no files but a temp folder, no network, no real company or cohort)."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import flags_score as S  # noqa: E402

KST = timezone(timedelta(hours=9))
T2CLS = {"evt_x": "C1", "evt_y": "C2"}
D0 = date(2026, 1, 5)


def spy_bars(n=300, start=D0):
    """n consecutive 'sessions' from start, flat at 100 (the excess return is then the name's own return)."""
    return {(start + timedelta(days=i)).isoformat(): (100.0, 100.0) for i in range(n)}


def sess(k, start=D0):
    return (start + timedelta(days=k)).isoformat()


def claim(fact_ids, status="announced_pending", support="supported", etype="evt_x"):
    return {"event_type": etype, "support": support, "status": status, "fact_ids": fact_ids, "claim": "c", "occurred_on": None}


def analysis(*claims):
    return {"tasks": {"material_events": {"claims": list(claims)}}}


def packet(name="Testco Alpha Inc", cik=111):
    return {"cik": cik, "evidence": [{"fact_id": "S0", "text": f"symbol: TSTA\nname: {name}\nsector: x"}, {"fact_id": "F1", "text": "text"}]}


# ---- groups

@pytest.mark.parametrize("q,b,g", [(False, False, "kept"), (True, False, "q1_only"), (False, True, "b1_only"), (True, True, "both")])
def test_group_of_a_read(q, b, g):
    assert S.group_of(q, b, "read") == g


@pytest.mark.parametrize("state", ["no_read", "no_packet", "open"])
def test_group_of_a_name_without_a_read_is_its_state(state):
    assert S.group_of(True, True, state) == state


# ---- S0 citation, classification with the real Q1

def test_acting_claims_citing_s0():
    q = S.E.q1(analysis(claim(["S0"]), claim(["F1"]), claim(["S0", "F1"]), claim(["S0"], support="unsupported"),
                        claim(["S0"], etype="evt_other")), date(2026, 1, 2), T2CLS, {"S0": "s", "F1": "f"})
    got = S.acting_s0_claims(q)
    assert [c["fact_ids"] for c in got] == [["S0"], ["S0", "F1"]]
    assert q["restricted"] is True


def test_classify_slot_read_name(monkeypatch):
    monkeypatch.setattr(S.E, "b1", lambda p, t, c: [{"acts": False}])
    an = analysis(claim(["S0"]))
    row = S.classify_slot("2026-01-02T21:00:00Z", "TSTA", packet(), "read", an, T2CLS, None, lambda p, t: {"Testco Alpha Inc"})
    assert (row["group"], row["cites_s0"], row["cik"], row["later_name"], row["cohort"]) == ("q1_only", True, 111, False, "2026-01-02")
    assert row["acting_claims"][0]["class"] == "C1" and len(row["s0_claims"]) == 1
    row = S.classify_slot("2026-01-02T21:00:00Z", "TSTA", packet(), "read", analysis(claim(["F1"], support="unsupported")), T2CLS, None,
                            lambda p, t: {"Old Name"})
    assert (row["group"], row["cites_s0"], row["later_name"]) == ("kept", False, True)


def test_classify_slot_b1_no_read_no_packet_and_open(monkeypatch):
    monkeypatch.setattr(S.E, "b1", lambda p, t, c: [{"acts": True}])
    assert S.classify_slot("2026-01-02T21:00:00Z", "TSTA", packet(), "read", analysis(), T2CLS, None)["group"] == "b1_only"
    assert S.classify_slot("2026-01-02T21:00:00Z", "TSTA", packet(), "read", analysis(claim(["F1"])), T2CLS, None)["group"] == "both"
    assert S.classify_slot("2026-01-02T21:00:00Z", "TSTA", packet(), "no_read", None, T2CLS, None)["group"] == "no_read"
    assert S.classify_slot("2026-01-02T21:00:00Z", "TSTA", None, "open", None, T2CLS, None)["group"] == "no_packet"
    assert S.classify_slot("2026-01-02T21:00:00Z", "TSTA", packet(), "open", None, T2CLS, None)["group"] == "open"


def test_later_name_and_the_stub():
    assert S.later_name("Testco  Alpha INC", {"testco alpha inc"}) is False
    assert S.later_name("Newco", {"Oldco"}) is True
    with pytest.raises(NotImplementedError):
        S.names_at_T(packet(), "2026-01-02T21:00:00Z")


# ---- sessions, indexing, no carry-forward, closed horizons

def test_session_indexing_base_open_and_horizon_close():
    spy = {sess(i): (100.0, 100.0 + i) for i in range(5)}           # session 0 is D0 (T is the day before): spy close 100 + i
    bars = {sess(0): (50.0, 51.0), sess(1): (52.0, 60.0), sess(2): (53.0, 75.0)}
    ex, npx, last = S.excess_returns(bars, spy, date(2026, 1, 4), horizons=(1, 2))
    assert ex[1] == pytest.approx((60.0 / 50.0 - 1) - (101.0 / 100.0 - 1))      # base = session 0's open, h = session h's close
    assert ex[2] == pytest.approx((75.0 / 50.0 - 1) - (102.0 / 100.0 - 1))
    assert npx == {1: False, 2: False} and last == sess(2)


def test_t_itself_is_not_session_zero():
    spy = spy_bars(5)
    assert S.sessions_after(spy, D0)[0] == sess(1)
    assert S.sessions_after(spy, D0 - timedelta(days=1))[0] == sess(0)


def test_no_carry_forward_and_no_price():
    spy = spy_bars(10)
    bars = {sess(0): (50.0, 50.0), sess(1): (50.0, 55.0), sess(3): (50.0, 60.0)}     # no bar on session 2, the horizon
    ex, npx, last = S.excess_returns(bars, spy, date(2026, 1, 4), horizons=(1, 2, 3, 4))
    assert ex[2] is None and npx[2] is True and ex[4] is None and npx[4] is True
    assert ex[1] == pytest.approx(0.1) and ex[3] == pytest.approx(0.2)
    assert last == sess(3)


def test_no_base_bar_is_no_price_at_every_closed_horizon():
    ex, npx, last = S.excess_returns({sess(1): (50.0, 55.0)}, spy_bars(10), date(2026, 1, 4), horizons=(1, 2))
    assert ex == {1: None, 2: None} and npx == {1: True, 2: True} and last == sess(1)
    assert S.excess_returns({}, spy_bars(10), date(2026, 1, 4), horizons=(1,)) == ({1: None}, {1: True}, None)


def test_a_horizon_is_closed_only_if_its_session_exists():
    T = date(2026, 1, 4)
    assert S.closed_horizons(spy_bars(61), T) == [20, 60]            # sessions 0..60 exist
    assert S.closed_horizons(spy_bars(60), T) == [20]
    assert S.closed_horizons(spy_bars(251), T) == [20, 60, 120, 250]
    ex, npx, _ = S.excess_returns({sess(0): (1.0, 1.0)}, spy_bars(30), T)
    assert ex == {20: None} and npx == {20: True}                    # 60, 120, 250 are not closed: absent, not no_price


# ---- cohort-demeaning

def mk_row(ticker, cohort, group, cik, later=False):
    return {"ticker": ticker, "T": cohort + "T21:00:00Z", "cohort": cohort, "cik": cik, "state": group if group not in S.GROUPS else "read",
            "group": group, "q1_restricted": None, "b1_restricted": None, "acting_claims": [], "cites_s0": False, "s0_claims": [],
            "s0_name": None, "later_name": later}


def bars60(start, r):
    """A name's bars: session 0 open 100 and the close of session 60 at 100 * (1 + r)."""
    return {sess(0, start): (100.0, 100.0), sess(60, start): (100.0, 100.0 * (1 + r))}


def test_demeaning_by_own_cohort_over_read_and_priced_names():
    A, B = date(2026, 1, 2), date(2026, 3, 20)                       # B's sessions start 2026-03-21
    spy = spy_bars(300, start=D0)
    rows = [mk_row("TSTA", "2026-01-02", "kept", 1), mk_row("TSTB", "2026-01-02", "q1_only", 2), mk_row("TSTC", "2026-01-02", "kept", 3),
            mk_row("TSTD", "2026-03-20", "kept", 4), mk_row("TSTE", "2026-03-20", "b1_only", 5),
            mk_row("TSTF", "2026-01-02", "no_read", 6)]
    sa, sb = D0, date(2026, 3, 21)
    px = {"TSTA": bars60(sa, 0.10), "TSTB": bars60(sa, 0.20), "TSTD": bars60(sb, -0.10), "TSTE": bars60(sb, 0.00), "TSTF": bars60(sa, 0.9)}
    closed = S.add_prices(rows, px, spy)
    by = {r["ticker"]: r for r in rows}
    # A: TSTC has no bars (no_price, out of the mean); mean of TSTA and TSTB is 0.15
    assert by["TSTA"]["demeaned"]["60"] == pytest.approx(-0.05) and by["TSTB"]["demeaned"]["60"] == pytest.approx(0.05)
    assert "60" not in by["TSTC"]["demeaned"] and by["TSTC"]["no_price"] == [20, 60, 120, 250]
    # B: a different market; mean -0.05
    assert by["TSTD"]["demeaned"]["60"] == pytest.approx(-0.05) and by["TSTE"]["demeaned"]["60"] == pytest.approx(0.05)
    # a name without a read has no return and is not in the mean
    assert by["TSTF"]["excess"] == {} and by["TSTF"]["last_traded"] is None
    assert closed["2026-01-02"] == [20, 60, 120, 250] and closed["2026-03-20"] == [20, 60, 120]      # 250 not closed for B


# ---- bootstrap

def test_bootstrap_is_reproducible_at_seed_1000():
    a = {i: [float(i % 7)] for i in range(30)}
    b = {100 + i: [float(i % 5) - 1.0] for i in range(30)}
    r1, r2 = S.bootstrap(a, b), S.bootstrap(a, b)
    assert r1 == r2 and r1[0] < r1[1] and r1[2] == 0
    assert S.bootstrap(a, b, seed=1001) != r1


def test_bootstrap_draws_companies_with_all_their_appearances():
    # company X has two appearances (10 and 0): drawn together, its mean is 5 whenever it is in a draw, so the difference cannot exceed 5
    a = {"X": [10.0, 0.0], "Z": [0.0]}
    b = {"Y": [0.0]}
    lo, hi, skipped = S.bootstrap(a, b)
    assert 0 < hi <= 5.0 and lo >= 0.0 and skipped > 0               # draws without Y or without X and Z are skipped


def test_compare_clusters_by_cik_across_cohorts():
    rows = []
    for t, c, g, cik, dm in (("TSTA", "2026-05-20", "q1_only", 7, 10.0), ("TSTA", "2026-08-20", "q1_only", 7, 0.0),
                             ("TSTZ", "2026-05-20", "q1_only", 8, 0.0), ("TSTY", "2026-05-20", "kept", 9, 0.0)):
        r = mk_row(t, c, g, cik)
        r["demeaned"], r["excess"], r["no_price"] = {"60": dm}, {"60": dm}, []
        rows.append(r)
    out = S.compare(rows, 60, ("q1_only",), ("kept",))
    assert out["a"]["n"] == 3 and out["b"]["n"] == 1 and out["a"]["mean"] == pytest.approx(10 / 3) and out["diff_of_means"] == pytest.approx(10 / 3)
    assert out["a"]["median"] == 0.0
    assert out["interval90"][1] <= 5.0 and out["skipped_draws"] > 0


def test_compare_with_an_empty_group_has_no_difference_or_interval():
    r = mk_row("TSTA", "2026-05-20", "kept", 1)
    r["demeaned"], r["excess"], r["no_price"] = {"60": 0.1}, {"60": 0.1}, []
    out = S.compare([r], 60, ("q1_only",), ("kept",))
    assert out["diff_of_means"] is None and out["interval90"] == [None, None] and out["skipped_draws"] == S.DRAWS


# ---- the sentence

def cell(lo, hi, na=12, nb=90):
    return {"interval90": [lo, hi], "a": {"n": na}, "b": {"n": nb}}


def test_sentence_three_cases():
    assert S.sentence(cell(-0.3, -0.01)) == "Names restricted by Qwen's read alone did worse than kept names over 60 sessions"
    assert S.sentence(cell(0.01, 0.3)) == "Names restricted by Qwen's read alone did better than kept names over 60 sessions"
    assert S.sentence(cell(-0.1, 0.2)) == "no difference shown (12 restricted, 90 kept; survivor-conditioned pool)"
    assert S.sentence(cell(-0.3, 0.0)).startswith("no difference shown")                 # touching zero is not wholly below
    assert S.sentence(cell(None, None)).startswith("no difference shown")


# ---- R4, R5

def test_r4_and_r5():
    rows = []
    for t, g, ex, cls in (("TSTA", "q1_only", -0.3, ["C1"]), ("TSTB", "both", -0.1, ["C1", "C2"]), ("TSTC", "kept", -0.25, []),
                          ("TSTD", "kept", 0.1, []), ("TSTE", "b1_only", -0.9, [])):
        r = mk_row(t, "2026-05-20", g, hash(t))
        r["excess"] = {"60": ex, "120": ex}
        r["acting_claims"] = [{"class": c} for c in cls]
        rows.append(r)
    out = S.r4(rows, {"2026-05-20": [20, 60]})["all"]                # the longest closed horizon is 60
    assert out["restricted"] == {"n": 2, "n_below": 1, "share": 0.5} and out["kept"] == {"n": 2, "n_below": 1, "share": 0.5}
    five = [mk_row(f"TS{i}", "2026-05-20", "q1_only", i) for i in range(5)]
    for i, r in enumerate(five):
        r["excess"], r["acting_claims"] = {"60": 0.1 * i}, [{"class": "C3"}]
    got = S.r5(rows + five)
    assert got["C1"] == {"n_names": 2, "n_priced": 2, "mean": None} and got["C3"]["n_names"] == 5
    assert got["C3"]["mean"] == pytest.approx(0.2)


# ---- the score command

def read_rows():
    rows, k = [], 0
    for cohort in ("2026-01-02", "2026-03-20"):
        for g, n in (("kept", 6), ("q1_only", 3), ("b1_only", 2), ("both", 1)):
            for _ in range(n):
                k += 1
                rows.append(mk_row(f"TS{k:02d}", cohort, g, k))
    rows.append(mk_row("TSNR", "2026-01-02", "no_read", 900))
    rows.append(mk_row("TSNP", "2026-01-02", "no_packet", None))
    rows[0]["later_name"] = True
    return rows


def synthetic_px(rows):
    px = {"SPY": spy_bars(200)}
    for r in rows:
        if r["state"] == "read":
            start = max(D0, date.fromisoformat(r["cohort"]) + timedelta(days=1))
            ret = -0.2 if r["group"] == "q1_only" else 0.05
            px[r["ticker"]] = {sess(i, start): (100.0, 100.0 * (1 + ret * (i / 60))) for i in range(0, 130)}
    del px["TS12"][sess(60, D0)]                                         # this name has no bar on session 60 (the others of its cohort have)
    return px


def test_score_command_refusals_and_a_scoring(tmp_path):
    rows = read_rows()
    px = synthetic_px(rows)
    calls = []

    def fetch(tickers, start, end):
        calls.append((tickers, start, end))
        return "synthetic", px

    ok_now = datetime(2026, 11, 21, 12, 0, tzinfo=KST)
    with pytest.raises(S.Refused, match="not before"):                                   # the date
        S.cmd_score("p", "a", ok_now - timedelta(seconds=1), load=lambda names: (rows, []), fetch=fetch, out_dir=tmp_path)
    with pytest.raises(S.Refused, match="still open"):                                   # an open slot
        S.cmd_score("p", "a", ok_now, load=lambda names: (rows, ["TSXX@2026-01-02"]), fetch=fetch, out_dir=tmp_path)
    (tmp_path / "score.json").write_text("{}")
    with pytest.raises(S.Refused, match="exists"):                                       # an existing output
        S.cmd_score("p", "a", ok_now, load=lambda names: (rows, []), fetch=fetch, out_dir=tmp_path)
    (tmp_path / "score.json").unlink()
    assert calls == []                                                                   # no price was fetched for any refusal

    out = S.cmd_score("p", "a", ok_now, load=lambda names: (rows, []), fetch=fetch, out_dir=tmp_path)
    assert len(calls) == 1 and "SPY" in calls[0][0] and "TSNR" not in calls[0][0]
    saved = json.loads((tmp_path / "score.json").read_text())
    assert saved["prereg_sha256"] == "p" and saved["amendment_sha256"] == "a" and saved["price_source"] == "synthetic"
    assert saved["later_name_set"] == ["TS01@2026-01-02"] and saved["no_read"] == ["TSNR@2026-01-02"] and saved["no_packet"] == ["TSNP@2026-01-02"]
    assert saved["no_price"] == [{"ticker": "TS12", "cohort": "2026-01-02", "horizons": [60], "last_traded": sess(129, D0)}]
    primary = saved["full"]["comparisons"]["all"]["60"]["primary"]
    assert primary["a"]["n"] == 6 and primary["b"]["n"] == 12 and primary["diff_of_means"] < 0
    assert saved["sentences"]["full"].startswith("Names restricted by Qwen's read alone did worse")
    assert saved["sentences"]["without_later_name"] is not None
    assert saved["without_later_name"]["comparisons"]["all"]["60"]["primary"]["b"]["n"] == 11          # the later-name kept name is out
    assert saved["full"]["counts"]["all"]["kept"] == 12 and saved["full"]["counts"]["all"]["no_read"] == 1
    with pytest.raises(S.Refused, match="exists"):                                       # the second scoring
        S.cmd_score("p", "a", ok_now, load=lambda names: (rows, []), fetch=fetch, out_dir=tmp_path)
    assert len(calls) == 1 and out["rows"][0]["ticker"] == "TS01"


def test_classify_command_writes_groups_without_prices(tmp_path):
    rows = read_rows()
    out = S.cmd_classify(load=lambda names: (rows, []), out_dir=tmp_path)
    saved = json.loads((tmp_path / "classify.json").read_text())
    assert saved == json.loads(json.dumps(out)) and "excess" not in saved["rows"][0]
    assert saved["counts"]["2026-01-02"]["kept"] == 6 and saved["counts"]["2026-01-02"]["no_packet"] == 1
