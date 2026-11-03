"""WO_S1 tests: the U benchmark (universe.py and the marks of m3o_engine). Fixtures only; no network, no git.
Run from m3o/:  python -m pytest tests -q"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as W  # noqa: E402

E, fl = W.E, W.fl
uni = E.uni
T1, T2, T3 = W.T1, W.T2, W.T3
F1, F2, F3 = (date.fromisoformat(W.FILLS[t]) for t in (T1, T2, T3))
LAST = W.SESSIONS[-1]
OPS = ["OPXA", "OPXB", "OPXC", "OPXD"]          # synthetic operator exclusions (conftest.py writes them; the real list is data in rs2-state)
UNIVERSES = {T1: ["A", "B", "C", "D", "E", "GONE"], T2: ["A", "B", "C", "D", "F", "GONE"], T3: ["A", "B", "C", "D", "F", "H"]}


def stocks_bytes(names, as_dict=False):
    rows = [{"symbol": t, "status": "Fail"} for t in names]
    rows[0]["_meta"] = {"price_refresh_coverage": 0.9}
    return json.dumps({r["symbol"]: r for r in rows} if as_dict else rows).encode("utf-8")


def factor_bytes(eligible, vetoed=(), no_key=()):
    t = {x: {"fct_veto": None, "fct_band": "pass"} for x in eligible}
    t.update({x: {"fct_veto": "NOT_TRADABLE", "fct_band": "vetoed"} for x in vetoed})
    t.update({x: {"fct_band": "pass"} for x in no_key})
    return json.dumps({"tickers": t}).encode("utf-8")


def universe_inputs(names):
    """stocks.json rows and factor_scores of a formation whose investable universe is `names`."""
    stocks = list(names) + OPS + ["V1", "NOFLAG"]
    return stocks_bytes(stocks), factor_bytes(list(names) + OPS + ["ONLYFS"], vetoed=["V1"], no_key=["NOFLAG"])


def px_rows(names, last=LAST):
    return [(t, d.isoformat(), *W.price(t, d)) for t in names for d in W.SESSIONS if d <= last and W.price(t, d)]


def put_universe(w, ud, T, names=None, last=LAST, stamp="2026-10-17T000000Z", rows=None):
    names = UNIVERSES[T] if names is None else names
    stocks, fs = universe_inputs(names)
    rec = uni.build_record(uni.formation_line(w.forward, T), stocks, fs)
    uni.write_record(ud, rec)
    uni.write_prices(ud, rec, px_rows(rec["tickers"], last) if rows is None else rows, "fixture", 1, stamp,
                     date.fromisoformat(W.FILLS[T]) - timedelta(days=3), last)
    return rec


def world_with_universe(tmp_path, formations=(T1, T2, T3)):
    w = W.World(tmp_path)
    ud = tmp_path / "universe_prices"
    for T in formations:
        put_universe(w, ud, T)
    return w, ud


def run_u(w, ud):
    w.materialize()
    return E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader(), universe_dir=ud)


def write_u(w, ud):
    L, marks = run_u(w, ud)
    return E.write_ledger(L, marks, w.ledger)


def ret(t, F, X):
    """open-to-open return of t from the fixture prices; no bar at the fill is 0.0 (cash); no exit is the last close"""
    if W.price(t, F) is None:
        return 0.0
    return (W.price(t, X)[0] if X else W.price(t, LAST)[1]) / W.price(t, F)[0] - 1.0


def hand(universes=UNIVERSES):
    """The U periods by plain arithmetic: equal weight at the fill open, drifted, one-way turnover from drifted weights."""
    out, drifted = [], {}
    for (T, names), F, X in zip(universes.items(), (F1, F2, F3), (F2, F3, None)):
        target = {t: 1.0 / len(names) for t in names}
        rets = {t: ret(t, F, X) for t in names}
        gross = sum(target[t] * rets[t] for t in names)
        turnover = 0.5 * sum(abs(target.get(t, 0.0) - drifted.get(t, 0.0)) for t in set(target) | set(drifted))
        drifted = {t: target[t] * (1 + rets[t]) / (1 + gross) for t in names}
        out.append({"gross": gross, "turnover": turnover})
    return out


def cum(vals):
    v = 1.0
    for x in vals:
        v *= 1.0 + x
    return v - 1.0


# ---------------------------------------------------------------- the universe

def test_universe_is_read_from_a_fixture_stocks_json_with_the_flag(tmp_path):
    names = ["A", "B", "C"]
    stocks, fs = universe_inputs(names)
    rec = uni.build_record({"formation_T": T1, "fill_session": W.FILLS[T1], "output_commit": "c" * 40}, stocks, fs)
    assert rec["tickers"] == ["A", "B", "C"] and rec["n_universe"] == 3
    assert "fct_veto" in rec["field"]
    assert rec["n_stocks_rows"] == 3 + 4 + 2                       # the rows of stocks.json
    assert rec["n_eligible_in_factor_scores"] == 3 + 4 + 1         # fct_veto null; V1 is vetoed and NOFLAG has no flag
    assert rec["n_eligible_not_in_stocks_rows"] == 1               # ONLYFS has no stocks.json row
    assert "V1" not in rec["tickers"] and "NOFLAG" not in rec["tickers"] and "ONLYFS" not in rec["tickers"]
    assert rec["stocks_json_sha256"] == uni.sha256_bytes(stocks)


def test_stocks_json_may_be_a_dict_keyed_by_symbol(tmp_path):
    assert uni.stock_symbols(stocks_bytes(["A", "B"], as_dict=True)) == {"A", "B"}
    assert uni.stock_symbols(stocks_bytes(["A", "B"])) == {"A", "B"}
    with pytest.raises(uni.UniverseError):
        uni.stock_symbols(b"[]")


def test_excluded_names_are_removed_and_counted(tmp_path):
    stocks, fs = universe_inputs(["A", "B"])
    rec = uni.build_record({"formation_T": T1, "fill_session": W.FILLS[T1], "output_commit": "c" * 40}, stocks, fs)
    assert rec["excluded_operator"] == {"tickers": sorted(OPS), "count": 4}
    assert not set(OPS) & set(rec["tickers"])
    assert rec["n_universe"] == rec["n_eligible_and_in_stocks_rows"] - 4
    stocks2, fs2 = stocks_bytes(["A", "OPXA"]), factor_bytes(["A", "OPXA"])           # only one of the four present
    rec2 = uni.build_record({"formation_T": T1, "fill_session": W.FILLS[T1], "output_commit": "c" * 40}, stocks2, fs2)
    assert rec2["excluded_operator"] == {"tickers": ["OPXA"], "count": 1} and rec2["tickers"] == ["A"]


def test_record_is_written_once_and_never_overwritten(tmp_path):
    w, ud = world_with_universe(tmp_path, formations=(T1,))
    rec, sha = uni.load_record(ud, T1)
    assert rec["tickers"] == UNIVERSES[T1]
    uni.write_record(ud, rec)                                      # identical: fine
    assert uni.load_record(ud, T1)[1] == sha
    with pytest.raises(uni.UniverseError, match="never overwritten"):
        uni.write_record(ud, {**rec, "n_universe": 99})


# ---------------------------------------------------------------- the return

def test_equal_weight_drift_and_turnover_match_a_hand_calculation(tmp_path):
    w, ud = world_with_universe(tmp_path)
    _, marks = run_u(w, ud)
    periods = marks["groups"]["main"]["series"]["U"]["periods"]
    expect = hand()
    assert len(periods) == 3
    for p, e in zip(periods, expect):
        assert p["gross"] == pytest.approx(e["gross"], abs=1e-12)
        assert p["turnover_one_way"] == pytest.approx(e["turnover"], abs=1e-12)
        assert p["n"] == 6
        for c in (0, 20, 60):
            assert p[f"net_{c}bp"] == pytest.approx(e["gross"] - e["turnover"] * c / 1e4, abs=1e-12)
    assert periods[0]["turnover_one_way"] == pytest.approx(0.5)             # from cash: half the book is bought
    assert 0.0 < periods[1]["turnover_one_way"] < 0.5                        # drifted weights, E out, F in
    assert periods[0]["fill"] == F1.isoformat() and periods[0]["exit"] == F2.isoformat()
    assert periods[2]["exit"].startswith("OPEN")                            # marked at the last close
    assert periods[0]["spy"] == marks["groups"]["main"]["series"]["F"]["periods"][0]["spy"]
    sm = marks["groups"]["main"]["series"]["U"]["summary"]
    assert sm["cumulative_gross"] == pytest.approx(cum([e["gross"] for e in expect]))
    assert sm["cumulative_net_60bp"] == pytest.approx(cum([e["gross"] - e["turnover"] * 60 / 1e4 for e in expect]))
    assert sm["periods"] == 3 and sm["not_yet_validated"] is True


def test_a_missing_bar_is_held_as_cash_and_counted(tmp_path):
    w, ud = world_with_universe(tmp_path)
    _, marks = run_u(w, ud)
    p0 = marks["groups"]["main"]["series"]["U"]["periods"][0]
    assert p0["n_universe"] == 6 and p0["n_with_price_at_fill"] == 5
    assert [e["ticker"] for e in p0["no_price_series"]] == ["GONE"]
    assert p0["no_price_series"][0]["event"] == "missing_entry_bar_held_as_cash"
    priced = sum(ret(t, F1, F2) for t in "ABCDE")
    assert p0["gross"] == pytest.approx(priced / 6)                          # GONE contributes 0.0 at its 1/6 weight
    cov = marks["groups"]["main"]["U_coverage"]
    assert cov[0] == {"formation_T": T1, "n_universe": 6, "n_with_price_at_fill": 5, "U_coverage": pytest.approx(5 / 6)}
    assert cov[2]["U_coverage"] == 1.0                                       # T3 universe has bars for every name


def test_zero_is_a_value_not_a_missing_bar(tmp_path):
    w = W.World(tmp_path)
    ud = tmp_path / "universe_prices"
    for T in (T1, T2, T3):
        put_universe(w, ud, T, names=["A", "ZERO"])
    _, marks = run_u(w, ud)
    p0 = marks["groups"]["main"]["series"]["U"]["periods"][0]
    assert p0["no_price_series"] == [] and p0["n_with_price_at_fill"] == 2
    assert p0["gross"] == pytest.approx(ret("A", F1, F2) / 2)                # ZERO is flat: a 0.0 return at a real bar


# ---------------------------------------------------------------- the comparison

def test_F_minus_U(tmp_path):
    w, ud = world_with_universe(tmp_path)
    _, marks = run_u(w, ud)
    g = marks["groups"]["main"]
    f = g["series"]["F"]["periods"]
    expect = hand()
    want_gross = cum([p["gross"] for p in f]) - cum([e["gross"] for e in expect])
    want_net = cum([p["net_20bp"] for p in f]) - cum([e["gross"] - e["turnover"] * 20 / 1e4 for e in expect])
    assert g["comparisons"]["F_minus_U_gross"] == pytest.approx(want_gross, abs=1e-12)
    assert g["comparisons"]["F_minus_U_net_20bp"] == pytest.approx(want_net, abs=1e-12)
    assert g["comparisons"]["F_minus_U_gross"] == pytest.approx(
        g["series"]["F"]["summary"]["cumulative_gross"] - g["series"]["U"]["summary"]["cumulative_gross"])
    assert "FB_minus_F_gross" in g["comparisons"]                            # the existing comparisons are unchanged
    assert "U_asof_mismatch" not in g


def test_a_universe_price_file_ending_earlier_is_flagged_not_hidden(tmp_path):
    w = W.World(tmp_path)
    ud = tmp_path / "universe_prices"
    early = date(2026, 10, 9)
    for T in (T1, T2, T3):
        put_universe(w, ud, T, last=early)
    _, marks = run_u(w, ud)
    g = marks["groups"]["main"]
    assert g["U_asof_mismatch"] == {"F_asof_price_date": LAST.isoformat(), "U_asof_price_date": early.isoformat()}
    assert "F_minus_U_gross" in g["comparisons"]


# ---------------------------------------------------------------- availability

def test_no_universe_dir_leaves_the_marks_unchanged(tmp_path):
    w = W.World(tmp_path)
    w.materialize()
    _, plain = E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())
    assert "U" not in plain["groups"]["main"]["series"] and "universe_records" not in plain
    empty = tmp_path / "nothing_here"
    _, none_found = E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader(), universe_dir=empty)
    g = none_found["groups"]["main"]
    assert "U" not in g["series"] and g["U_unavailable"] == {"formation_T": T1, "reason": "no universe record"}
    assert "F_minus_U_gross" not in g["comparisons"]
    assert {k: v for k, v in g.items() if k != "U_unavailable"} == plain["groups"]["main"]


def test_a_formation_without_universe_prices_breaks_the_chain(tmp_path):
    w = W.World(tmp_path)
    ud = tmp_path / "universe_prices"
    put_universe(w, ud, T1)
    rec = uni.build_record(uni.formation_line(w.forward, T2), *universe_inputs(UNIVERSES[T2]))
    uni.write_record(ud, rec)                                                # a record but no price receipt for T2
    put_universe(w, ud, T3)
    _, marks = run_u(w, ud)
    g = marks["groups"]["main"]
    assert g["U_unavailable"] == {"formation_T": T2, "reason": "no universe price receipt"}
    assert "U" not in g["series"] and "U_coverage" not in g                  # no partial U: its drift chain is broken


def test_a_universe_record_for_another_commit_stops(tmp_path):
    w, ud = world_with_universe(tmp_path)
    p = ud / f"universe_{T1}.json"
    rec = json.loads(p.read_text())
    rec["output_commit"] = "d" * 40
    p.write_text(json.dumps(rec, indent=1, sort_keys=True))
    with pytest.raises(E.Stop, match="not the formation's"):
        run_u(w, ud)


def test_a_universe_csv_that_does_not_hash_to_its_receipt_stops(tmp_path):
    w, ud = world_with_universe(tmp_path)
    next(ud.glob(f"universe_{T1}_*.csv")).write_text("ticker,date,adj_open,adj_close\n")
    with pytest.raises(E.Stop, match="does not hash"):
        run_u(w, ud)


# ---------------------------------------------------------------- the stop rule and reruns

def test_a_rerun_appends_nothing(tmp_path):
    w, ud = world_with_universe(tmp_path)
    counts, new_marks = write_u(w, ud)
    assert new_marks is True and counts["actions"] > 0
    sizes = {p.name: p.read_bytes() for p in w.ledger.rglob("*") if p.is_file()}
    counts2, new_marks2 = write_u(w, ud)
    assert new_marks2 is False and all(v == 0 for v in counts2.values())
    assert sizes == {p.name: p.read_bytes() for p in w.ledger.rglob("*") if p.is_file()}
    stored = json.loads(next((w.ledger / "marks").glob("*.json")).read_text())
    assert "U" in stored["groups"]["main"]["series"] and set(stored["universe_records"]) == {T1, T2, T3}


def test_a_new_universe_receipt_with_the_same_prices_does_not_stop_but_changed_prices_do(tmp_path):
    w, ud = world_with_universe(tmp_path)
    write_u(w, ud)
    for T in (T1, T2, T3):                                                   # a later fetch of the same data: another receipt
        put_universe(w, ud, T, stamp="2026-10-18T000000Z")
    _, new_marks = write_u(w, ud)
    assert new_marks is False
    rows = px_rows(UNIVERSES[T1])
    rows = [(t, d, o * 1.05 if (t, d) == ("A", F2.isoformat()) else o, c) for t, d, o, c in rows]
    put_universe(w, ud, T1, stamp="2026-10-19T000000Z", rows=rows)          # the exit open of A moves: U changes for a stored asof
    with pytest.raises(E.Stop, match="marks/"):
        write_u(w, ud)


def test_a_universe_added_after_marks_were_stored_stops(tmp_path):
    w = W.World(tmp_path)
    w.materialize()
    L, marks = E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())
    E.write_ledger(L, marks, w.ledger)
    ud = tmp_path / "universe_prices"
    for T in (T1, T2, T3):
        put_universe(w, ud, T)
    with pytest.raises(E.Stop, match="marks/"):
        write_u(w, ud)


def test_u_does_not_change_the_action_lines_or_the_other_series(tmp_path):
    w, ud = world_with_universe(tmp_path)
    L_u, m_u = run_u(w, ud)
    L, m = E.run(w.forward, w.inputs, w.ledger, factor_loader=w.loader())
    assert L_u == L
    for s, x in m["groups"]["main"]["series"].items():
        assert m_u["groups"]["main"]["series"][s] == x


# ---------------------------------------------------------------- the fetch (no network: an injected downloader)

def fake_download(calls):
    def dl(chunk, start, end):
        calls.append((list(chunk), start, end))
        return [(t, d.isoformat(), *W.price(t, d)) for t in chunk for d in W.SESSIONS if start <= d <= end and W.price(t, d)], "fake"
    return dl


def test_fetch_prices_in_chunks_and_receipt(tmp_path):
    w = W.World(tmp_path)
    calls = []
    names = ["A", "B", "C", "D", "E", "GONE", "H"]
    start, end = F1 - timedelta(days=3), date(2026, 8, 14)
    rows, src, n = uni.fetch_prices(names, start, end, download=fake_download(calls), chunk=3)
    assert n == 3 and [len(c[0]) for c in calls] == [3, 3, 1] and src == "fake"
    assert all(c[1] == start and c[2] == end for c in calls)
    assert max(r[1] for r in rows) <= end.isoformat() and "GONE" not in {r[0] for r in rows}
    rec = uni.build_record(uni.formation_line(w.forward, T1), *universe_inputs(names))
    receipt = uni.write_prices(tmp_path / "out", rec, rows, src, n, "2026-10-17T00:00:00Z", start, end)
    assert receipt["tickers_without_bars"] == ["GONE"] and receipt["tickers_with_bars"] == 6 and receipt["tickers_requested"] == 7
    assert receipt["chunks"] == 3 and receipt["window"] == [start.isoformat(), end.isoformat()]
    px, loaded = uni.load_prices(tmp_path / "out", T1)
    assert loaded["sha256"] == receipt["sha256"] and px["A"][F1.isoformat()] == W.price("A", F1)
    assert uni.load_prices(tmp_path / "out", T2) == (None, None)


def test_cmd_fetch_builds_the_record_then_the_prices(tmp_path, monkeypatch):
    w = W.World(tmp_path)
    stocks, fs = universe_inputs(UNIVERSES[T1])
    monkeypatch.setattr(uni, "git_blob", lambda commit, rel: stocks if rel.endswith("stocks.json") else fs)
    calls = []
    out = tmp_path / "out"
    rec, receipt = uni.cmd_fetch(T1, w.forward, out, asof=date(2026, 8, 14), download=fake_download(calls))
    assert rec["tickers"] == UNIVERSES[T1] and rec["output_commit"] == w.commit(T1)
    assert calls[0][1] == F1 - timedelta(days=3) and calls[0][2] == date(2026, 8, 14)
    assert (out / f"universe_{T1}.json").exists() and receipt["universe_sha256"]
    with pytest.raises(uni.UniverseError, match="not in"):
        uni.cmd_fetch("2030-01-31", w.forward, out, asof=date(2026, 8, 14), download=fake_download([]))
    with pytest.raises(uni.UniverseError, match="no completed session"):
        uni.cmd_fetch(T1, w.forward, out, asof=F1 - timedelta(days=1), download=fake_download([]))
