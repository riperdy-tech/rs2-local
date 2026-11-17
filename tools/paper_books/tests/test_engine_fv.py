"""Paper book FV in m3o_engine (PREREG_m3o_bookV, SPEC_m3o_bookV v0.2): synthetic worlds, fixtures only. The first formation of the worlds is made
the series start (FV_START = T1); each world's snapshots (fv_<T>.json) are written by World.snapshot. Run from the repo root:
python -m pytest tools/paper_books/tests -q"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as W  # noqa: E402
from test_engine import F1, F2, F3, HIT, act, b_hit, per, r  # noqa: E402

E = W.E
T1, T2, T3 = W.T1, W.T2, W.T3
V1, V2, V3 = "2026-08-04", "2026-09-02", "2026-10-02"          # FV's fill sessions: the morning after each A0 fill (World.snapshot default)
LAST = "2026-10-16"


def rc(t, d0):
    """open of d0 to the close of the last price day"""
    return W.price(t, date.fromisoformat(LAST))[1] / W.price(t, date.fromisoformat(d0))[0] - 1.0

FILL_OPEN = E.fl.open_utc(date.fromisoformat(V1))
BOOK1, BOOK23 = list("ABCDE") + ["OPXA"], list("ABCDF") + ["OPXA"]


@pytest.fixture(autouse=True)
def fv_start(monkeypatch):
    monkeypatch.setattr(E, "FV_START", T1)


def entry(role, v):
    """A snapshot name: a number is a cheapness (equity value over a market cap of 1000), a string the reason of an unvalued name."""
    out = {"role": role, "valued": False, "reason": None, "value_base": None, "shares": None, "equity_value": None, "market_cap": None, "cheapness": None}
    if isinstance(v, str):
        out["reason"] = v
    else:
        out.update(valued=True, value_base=v, shares=1000.0, equity_value=v * 1000.0, market_cap=1000.0, cheapness=v)
    return out


def names(book=None, held=None):
    return {**{t: entry("book", v) for t, v in (book or {}).items()}, **{t: entry("fv_held", v) for t, v in (held or {}).items()}}


S1 = {"A": 3.0, "B": 2.0, "C": 1.0, "D": 4.0, "E": 5.0}                    # cut 3.0: A, D, E enter
S2 = {"A": 4.0, "B": 3.0, "C": 1.0, "D": 0.5, "F": "no_value: no_call:x"}  # cut 2.0
S3 = {"A": 4.0, "B": 3.0, "C": 1.0, "D": 0.5, "F": 2.0}                    # cut 2.0


def scenario(tmp_path, snaps=(T1, T2, T3), n=3):
    """T1 enters A, D, E; T2 (A under B1) holds A and E (E left the book), D exits, B enters; T3 holds A, B, E (no value once), F enters."""
    fs = [{"T": T1, "book": BOOK1, "fv_held": []}, {"T": T2, "book": BOOK23, "fv_held": ["E"]}, {"T": T3, "book": BOOK23, "fv_held": ["E"]}]
    w = W.World(tmp_path, fs[:n])
    w.set(T2, "A", items=b_hit(T2, 30))
    spec = {T1: names(S1), T2: names(S2, {"E": 6.0}), T3: names(S3, {"E": "no_value: no_call:y"})}
    for T in snaps:
        w.snapshot(T, spec[T])
    return w


def fv(L, T, t):
    return act(L, T, "FV", t)


# ---------------------------------------------------------------- off, and the registration

def test_no_value_dir_and_no_snapshot_leave_lines_and_marks_as_they_are(tmp_path, monkeypatch):
    w = W.standard(tmp_path)
    L0, m0 = w.run()
    L1, m1 = w.run(value=True)                                                       # value dir does not exist
    assert (L0, m0) == (L1, m1)
    w.snapshot(T1, names({"A": 1.0}))                                                  # present, but T1 is before the start
    monkeypatch.setattr(E, "FV_START", "2026-11-30")
    L2, m2 = w.run(value=True)
    assert (L0, m0) == (L2, m2)
    assert not [l for l in L0["actions"] if l["arm"] == "FV"] and "FV" not in m0["groups"]["main"]["series"]


def test_constants_equal_the_registration(monkeypatch):
    monkeypatch.undo()
    p = json.loads(E.PREREG_BOOKV.read_text(encoding="utf-8"))
    assert E.FV_START == p["series_start"][:10] == "2026-11-30"
    assert E.FV_MAX_HELD == p["rule"]["max_formations_held"] == 12
    assert E.FV_MISSED_TO_LEAVE == p["rule"]["missed_values_to_leave"] == 2
    assert "FV" not in E.SERIES and "FV" not in E.ALL_SERIES and E.ENGINE_VERSION == "m3o_engine.v4"


# ---------------------------------------------------------------- the first decision

@pytest.mark.parametrize("spec,cut,entered", [
    ({"A": 3.0, "B": 2.0, "C": 1.0, "D": "no_value: x", "E": "no_value: x"}, 2.0, ["A", "B"]),          # odd count: the middle name enters
    ({"A": 3.0, "B": 2.0, "C": 1.0, "D": "no_value: x", "E": 4.0}, 2.5, ["A", "E"]),                    # even count: the mean of the middle two
    ({"A": 3.0, "B": 0.0, "C": -0.5, "D": 4.0, "E": 2.0}, 2.0, ["A", "D", "E"]),                         # 0.0 and a negative cheapness are values
])
def test_the_cut_is_the_median_and_names_at_it_enter(tmp_path, spec, cut, entered):
    w = W.World(tmp_path, [{"T": T1, "book": BOOK1, "fv_held": []}])
    w.snapshot(T1, names(spec))
    L, marks = w.run(value=True)
    for t in "ABCDE":
        a = fv(L, T1, t)
        assert a["value"]["cut"] == cut
        if t in entered:
            assert (a["action"], a["rule"], a["reason"]) == ("enter", "V1", "cheap") and a["weight_target"] == pytest.approx(1 / len(entered))
        elif isinstance(spec[t], str):
            assert (a["action"], a["reason"]) == ("not_entered", "no_value") and a["value"]["value_reason"] == "no_value: x" and not a["value"]["valued"]
        else:
            assert (a["action"], a["reason"]) == ("not_entered", "not_cheap") and a["value"]["valued"]
    assert per(marks, "FV", 0)["gross"] == pytest.approx(sum(rc(t, V1) for t in entered) / len(entered))
    assert per(marks, "FV", 0)["n"] == len(entered)


def test_not_entered_lines_and_an_operator_excluded_name(tmp_path):
    book = list("ABCDEFGH") + ["OPXA"]
    w = W.World(tmp_path, [{"T": T1, "book": book, "fv_held": []}])
    occurred = W.date_days_before(T1, 30).strftime("%B %d, %Y")
    q_item = (f"On {occurred} the company announced a filing.", "2026-05-01T12:00:00Z")
    w.set(T1, "B", items=[q_item], claims=[W.claim(occurred_on=occurred)])                    # Q1 acts
    w.set(T1, "C", items=b_hit(T1, 30))                                                      # B1 acts
    w.set(T1, "D", items=[q_item, (HIT, W.accepted_days_before(T1, 30))], claims=[W.claim(occurred_on=occurred)])   # both
    w.set(T1, "E", finished=None)                                                            # no finished run
    w.snapshot(T1, names({"A": 5.0, "B": 5.0, "C": 5.0, "D": 5.0, "E": 5.0, "F": "no_value: x", "G": 1.0, "H": 5.0}))
    L, marks = w.run(value=True)
    assert [(t, fv(L, T1, t)["action"], fv(L, T1, t)["reason"]) for t in "ABCDEFGH"] == [
        ("A", "enter", "cheap"), ("B", "not_entered", "restricted_new_entry: Q1"),
        ("C", "not_entered", "restricted_new_entry: " + E.B1_NAME), ("D", "not_entered", "restricted_new_entry: " + E.B1_NAME + "+Q1"),
        ("E", "not_entered", "analysis_not_finished"), ("F", "not_entered", "no_value"), ("G", "not_entered", "not_cheap"), ("H", "enter", "cheap")]
    assert fv(L, T1, "B")["causes"] == ["Q1"] and fv(L, T1, "C")["causes"] == ["B1"] and fv(L, T1, "D")["causes"] == ["B1", "Q1"]
    x = fv(L, T1, "OPXA")
    assert (x["action"], x["rule"], x["reason"], x["weight_target"]) == ("operator_excluded", "E1", "operator_excluded_ticker", 0.0)
    assert "OPXA" not in per(marks, "FV", 0)["groups"]["cheap_half"]["names"]
    assert fv(L, T1, "A")["weight_target"] == pytest.approx(0.5) and fv(L, T1, "H")["weight_target"] == pytest.approx(0.5)
    assert fv(L, T1, "E")["value"]["cut"] == 5.0


def test_a_line_carries_fvs_fill_the_value_object_the_inputs_and_the_label(tmp_path):
    L, _ = scenario(tmp_path / "s").run(value=True)
    a = fv(L, T1, "A")
    assert (a["fill_session"], a["a0_fill_session"], a["arm"], a["kind"], a["label"]) == (V1, F1, "FV", "at_fill_open", "shadow_pre_3N_close")
    assert a["value"] == {"cheapness": 3.0, "cut": 3.0, "equity_value": 3000.0, "market_cap": 1000.0, "valued": True, "value_reason": None,
                          "periods_held": 0, "missed": 0}
    assert a["inputs"]["prereg_bookV"] == E.sha256_bytes(E.PREREG_BOOKV.read_bytes())
    assert a["inputs"]["fv"] == E.sha256_bytes((tmp_path / "s" / "value" / f"fv_{T1}.json").read_bytes())
    assert "prereg_bookV" not in act(L, T1, "FQ", "A")["inputs"] and act(L, T1, "F", "A")["fill_session"] == F1
    assert a["qwen_c_commit"] == "qqqqqqqabc" and a["builder_code"] == {"packet.py": "bc-A"}
    assert E.arm_label("FV", "2026-11-30") == "paper_post_3N"


# ---------------------------------------------------------------- Q1 by finished_at

@pytest.mark.parametrize("finished,claim,action,reason", [
    ("2026-08-03T20:00:00.000000Z", False, "enter", "cheap"),                                  # after the A0 fill open, before FV's: counts
    ("2026-08-03T20:00:00.000000Z", True, "not_entered", "restricted_new_entry: Q1"),
    ("2026-08-04T13:29:59.000000Z", True, "not_entered", "restricted_new_entry: Q1"),          # one second before FV's fill open
    ("2026-08-04T13:30:00.000000Z", True, "not_entered", "restricted_new_entry: Q1"),          # at the open: on or before counts
    ("2026-08-04T13:30:01.000000Z", True, "not_entered", "analysis_not_finished"),             # a second after: no Q1 result
    ("2026-08-05T15:00:00.000000Z", False, "not_entered", "analysis_not_finished"),
])
def test_a_late_q1_run_counts_only_when_it_finished_before_fvs_fill_open(tmp_path, finished, claim, action, reason):
    w = W.World(tmp_path, [{"T": T1, "book": ["A", "B", "OPXA"], "fv_held": []}])
    occurred = W.date_days_before(T1, 30).strftime("%B %d, %Y")
    w.set(T1, "B", finished=finished, **({"items": [(f"On {occurred} the company announced a filing.", "2026-05-01T12:00:00Z")],
                                          "claims": [W.claim(occurred_on=occurred)]} if claim else {}))
    w.snapshot(T1, names({"A": 1.0, "B": 2.0}))
    L, _ = w.run(value=True)
    assert (fv(L, T1, "B")["action"], fv(L, T1, "B")["reason"]) == (action, reason)


def test_a_run_that_finishes_after_fvs_fill_never_changes_a_stored_line(tmp_path):
    w = W.World(tmp_path, [{"T": T1, "book": ["A", "B", "OPXA"], "fv_held": []}, {"T": T2, "book": ["A", "B", "OPXA"], "fv_held": []}])
    w.set(T1, "B", finished=None)
    w.snapshot(T1, names({"A": 1.0, "B": 2.0}))
    w.write(value=True)
    n_fv = len([l for l in w.lines("actions") if l["arm"] == "FV"])
    assert fv(w.run(value=True)[0], T1, "B")["reason"] == "analysis_not_finished"
    w.set(T1, "B", finished="2026-09-02T15:00:00.000000Z", state="complete")                 # after FV's fill (08-04) and the next A0 fill
    again, new_marks = w.write(value=True)                                                   # no Stop: the stored FV line recomputes the same
    assert again["actions"] == 1 and new_marks is False                                      # only FQ's pending_resolution line is new
    assert len([l for l in w.lines("actions") if l["arm"] == "FV"]) == n_fv == 3


# ---------------------------------------------------------------- stay and leave

def test_stay_and_leave_over_three_decisions(tmp_path):
    L, marks = scenario(tmp_path).run(value=True)
    assert [fv(L, T1, t)["action"] for t in "ABCDE"] == ["enter", "not_entered", "not_entered", "enter", "enter"]
    a, d, e, b = (fv(L, T2, t) for t in "ADEB")
    assert (a["action"], a["reason"], a["flags"], a["causes"]) == ("hold", "still_cheap", ["restricted_held"], ["B1"])
    assert (d["action"], d["reason"]) == ("exit", "no_longer_cheap") and d["weight_target"] == 0.0 and d["weight_before"] > 0
    assert (e["action"], e["reason"], e["flags"]) == ("hold", "still_cheap", ["left_A0_book"]) and "causes" not in e
    assert (b["action"], b["reason"]) == ("enter", "cheap")
    assert fv(L, T2, "F")["reason"] == "no_value" and fv(L, T2, "F")["value"]["value_reason"] == "no_value: no_call:x"
    assert fv(L, T2, "C")["reason"] == "not_cheap" and a["value"]["cut"] == 2.0
    assert [fv(L, T2, t)["weight_target"] for t in "AEB"] == pytest.approx([1 / 3] * 3)
    e3 = fv(L, T3, "E")
    assert (e3["action"], e3["reason"], e3["flags"]) == ("hold", "held_value_missing", ["value_missing", "left_A0_book"])
    assert (e3["value"]["periods_held"], e3["value"]["missed"], e3["value"]["valued"]) == (2, 1, False)
    assert (fv(L, T3, "A")["value"]["periods_held"], fv(L, T3, "B")["value"]["periods_held"]) == (2, 1)
    assert fv(L, T3, "F")["action"] == "enter" and fv(L, T3, "D")["reason"] == "not_cheap"          # D left at T2 and is not held again
    assert E.fv_held_now(L) == ["A", "B", "E", "F"]


def pf(book, held, snap, counts=None, excluded=(), ev=None):
    """plan_fv on stub evidence: every non-excluded book name complete with no restriction."""
    ev = ev if ev is not None else {t: {"state": "complete", "q_fill": {"restricted": False}, "q_late": None, "b1_restricted": False, "info": None}
                                    for t in book if t not in excluded}
    pre = {t: 1.0 / len(held) for t in held} or {"CASH": 1.0}
    return E.plan_fv(book, set(excluded), pre, ev, snap, counts if counts is not None else {t: {"periods_held": 0, "missed": 0} for t in held}, FILL_OPEN)


def acts(dec):
    return {t: (a, rs) for t, a, _, rs, _, _ in dec}


def test_held_twelve_formations_exits_at_the_twelfth_carry_and_not_the_eleventh():
    book, held, counts, seen = ["X", "Y"], [], {}, []
    for k in range(1, 20):
        plan, dec, cut, now = pf(book, held, names({"X": 3.0, "Y": 1.0}), counts)
        seen.append(acts(dec)["X"])
        held, counts = list(plan["positions"]), {t: now[t] for t in plan["positions"]}
        if not held:
            break
    assert seen[0] == ("enter", "cheap") and all(s == ("hold", "still_cheap") for s in seen[1:12]) and seen[12] == ("exit", "held_12_formations")
    assert len(seen) == 13 and counts == {}                                                   # entered (0), carried 11 times (1..11), the 12th carry exits
    _, dec, _, now = pf(book, ["X"], names({"X": 4.0, "Y": 3.0}), {"X": {"periods_held": 11, "missed": 0}})
    assert acts(dec)["X"] == ("exit", "held_12_formations") and now["X"]["periods_held"] == 12
    _, dec, _, _ = pf(book, ["X"], names({"X": 4.0, "Y": 3.0}), {"X": {"periods_held": 10, "missed": 0}})
    assert acts(dec)["X"] == ("hold", "still_cheap")
    _, dec2, _, _ = pf(book, ["X"], names({"X": 1.0, "Y": 4.0}), {"X": {"periods_held": 11, "missed": 0}})
    assert acts(dec2)["X"] == ("exit", "no_longer_cheap")                                      # below the cut at the 12th: that reason first


def test_a_missing_value_is_held_once_exits_twice_and_a_value_in_between_resets():
    book = ["X", "Y", "Z"]
    one, c = {"X": {"periods_held": 3, "missed": 0}}, names({"X": "no_value: q", "Y": 2.0, "Z": 1.0})
    _, dec, _, now = pf(book, ["X"], c, one)
    assert acts(dec)["X"] == ("hold", "held_value_missing") and dec[0][4] == ["value_missing"] and now["X"] == {"periods_held": 4, "missed": 1}
    _, dec, _, now = pf(book, ["X"], c, {"X": {"periods_held": 4, "missed": 1}})
    assert acts(dec)["X"] == ("exit", "value_missing_twice")
    _, dec, _, now = pf(book, ["X"], names({"X": 2.0, "Y": 2.0, "Z": 1.0}), {"X": {"periods_held": 4, "missed": 1}})
    assert acts(dec)["X"] == ("hold", "still_cheap") and now["X"]["missed"] == 0
    _, dec, _, now = pf(book, ["X"], c, now)
    assert acts(dec)["X"] == ("hold", "held_value_missing") and now["X"]["missed"] == 1


def test_no_cut_nothing_enters_and_held_names_hold_with_no_cut():
    book = ["X", "Y", "Z"]
    plan, dec, cut, now = pf(book, ["H"], names({"X": "no_value: q", "Y": "no_value: q", "Z": "no_value: q"}, {"H": 7.0}))
    assert cut is None and acts(dec) == {"H": ("hold", "held_no_cut"), "X": ("not_entered", "no_value"), "Y": ("not_entered", "no_value"),
                                         "Z": ("not_entered", "no_value")}
    assert dec[0][4] == ["no_cut", "left_A0_book"] and plan["positions"] == {"H": 1.0}
    plan, dec, cut, now = pf(book, ["H"], names({"X": "no_value: q", "Y": "no_value: q", "Z": "no_value: q"}, {"H": "no_value: q"}))
    assert dec[0][3] == "held_value_missing" and dec[0][4] == ["value_missing", "no_cut", "left_A0_book"]


def test_an_operator_excluded_held_name_leaves_and_loses_its_counts():
    plan, dec, cut, now = pf(["X", "OPXA"], ["OPXA"], names({"X": 1.0}), {"OPXA": {"periods_held": 5, "missed": 0}}, excluded=("OPXA",))
    assert dec[0] == ("OPXA", "operator_excluded", "E1", "operator_excluded_ticker", [], []) and "OPXA" not in now and "OPXA" not in plan["positions"]
    assert acts(dec)["X"] == ("enter", "cheap")


def test_a_held_book_name_under_b1_is_held_with_its_causes():
    ev = {t: {"state": "complete", "q_fill": {"restricted": q}, "q_late": None, "b1_restricted": b, "info": None} for t, b, q in
          (("X", True, True), ("Y", False, False))}
    _, dec, _, _ = pf(["X", "Y"], ["X"], names({"X": 5.0, "Y": 1.0}), ev=ev)
    assert dec[0] == ("X", "hold", "V1", "still_cheap", ["restricted_held"], ["B1", "Q1"])


def test_a_held_name_missing_from_the_snapshot_is_unvalued():
    _, dec, _, now = pf(["X", "Y"], ["H"], names({"X": 1.0, "Y": 2.0}))
    assert acts(dec)["H"] == ("hold", "held_value_missing") and now["H"] == {"periods_held": 1, "missed": 1}


def test_a_null_or_missing_fv_held_reads_as_empty(tmp_path):
    for i, held in enumerate((None, [])):
        w = W.World(tmp_path / str(i), [{"T": T1, "book": BOOK1, "fv_held": held}])
        w.snapshot(T1, names(S1))
        assert fv(w.run(value=True)[0], T1, "A")["action"] == "enter"
    w = W.World(tmp_path / "m", [{"T": T1, "book": BOOK1}])                                    # no key at all
    w.snapshot(T1, names(S1))
    assert fv(w.run(value=True)[0], T1, "A")["action"] == "enter"
    w.snapshot(T1, names(S1, {"H": 1.0}))
    with pytest.raises(E.Stop, match="not in the map"):
        w.run(value=True)


# ---------------------------------------------------------------- the period

def test_two_decisions_from_fill_to_fill_the_last_marked_at_the_last_close(tmp_path):
    L, marks = scenario(tmp_path, snaps=(T1, T2)).run(value=True)
    px = rc
    p1, p2 = per(marks, "FV", 0), per(marks, "FV", 1)
    r1 = {t: r(t, V1, V2) for t in "ADE"}
    g1 = sum(r1.values()) / 3
    assert (p1["fill"], p1["exit"], p1["n"], p1["formation_T"]) == (V1, V2, 3, T1)
    assert p1["gross"] == pytest.approx(g1) and p1["turnover_one_way"] == pytest.approx(0.5) and p1["spy"] == pytest.approx(r("SPY", V1, V2))
    w1 = {t: (1 / 3) * (1 + r1[t]) / (1 + g1) for t in "ADE"}                                    # drifted weights into the second decision
    c = {t: px(t, V2) for t in "AEB"}
    assert (p2["fill"], p2["exit"]) == (V2, f"OPEN (marked {LAST})") and p2["n"] == 3
    assert p2["gross"] == pytest.approx(sum(c.values()) / 3) and p2["spy"] == pytest.approx(px("SPY", V2))
    assert p2["turnover_one_way"] == pytest.approx(0.5 * (abs(1 / 3 - w1["A"]) + abs(1 / 3 - w1["E"]) + 1 / 3 + w1["D"]))
    assert p2["net_20bp"] == pytest.approx(p2["gross"] - p2["turnover_one_way"] * 20 / 1e4) and p1["label"] == "shadow_pre_3N_close"
    g = p1["groups"]
    assert (p1["cut"], p1["n_valued"], p1["a0_fill_session"]) == (3.0, 5, F1)
    assert [x["ticker"] for x in g["cheap_half"]["names"]] == ["A", "D", "E"] and g["cheap_half"]["n"] == 3
    assert g["cheap_half"]["mean_return"] == pytest.approx(g1) and [x["ticker"] for x in g["expensive_half"]["names"]] == ["B", "C"]
    assert g["expensive_half"]["mean_return"] == pytest.approx((r("B", V1, V2) + r("C", V1, V2)) / 2)
    assert g["unvalued"] == {"n": 0, "mean_return": None, "names": []} and p1["leavers"] == []
    g2 = p2["groups"]
    assert (p2["cut"], p2["n_valued"]) == (2.0, 4) and [x["ticker"] for x in g2["cheap_half"]["names"]] == ["A", "B"]
    assert [x["ticker"] for x in g2["expensive_half"]["names"]] == ["C", "D"] and [x["ticker"] for x in g2["unvalued"]["names"]] == ["F"]
    assert g2["unvalued"]["mean_return"] == pytest.approx(px("F", V2))
    assert p2["leavers"] == [{"ticker": "D", "reason": "no_longer_cheap", "return": pytest.approx(px("D", V2))}]
    assert marks["groups"]["main"]["series"]["FV"]["summary"]["periods"] == 2


def test_nothing_held_is_cash(tmp_path):
    w = W.World(tmp_path, [{"T": T1, "book": BOOK1, "fv_held": []}])
    w.snapshot(T1, names({t: "no_value: x" for t in "ABCDE"}))
    L, marks = w.run(value=True)
    p = per(marks, "FV", 0)
    assert (p["n"], p["gross"], p["turnover_one_way"], p["cash_weight_at_fill"], p["cut"], p["n_valued"]) == (0, 0.0, 0.0, 1.0, None, 0)
    assert p["groups"]["unvalued"]["n"] == 5 and p["groups"]["cheap_half"]["mean_return"] is None and "best" not in p
    assert all(fv(L, T1, t)["reason"] == "no_value" for t in "ABCDE") and E.fv_held_now(L) == []


def test_a_formation_without_a_snapshot_is_skipped_the_period_spans_it_and_counts_do_not_advance(tmp_path):
    L, marks = scenario(tmp_path, snaps=(T1, T3)).run(value=True)
    assert not [l for l in L["actions"] if l["arm"] == "FV" and l["formation_T"] == T2]
    p = per(marks, "FV", 0)
    assert (p["fill"], p["exit"]) == (V1, V3) and len(marks["groups"]["main"]["series"]["FV"]["periods"]) == 2
    a = fv(L, T3, "A")
    assert a["action"] == "hold" and a["value"]["periods_held"] == 1 and a["weight_before"] > 0                # T1 enter, T3 the first carry
    assert fv(L, T3, "E")["flags"] == ["value_missing", "left_A0_book"] and fv(L, T3, "E")["value"]["missed"] == 1
    assert fv(L, T3, "B")["action"] == "enter"
    cmp = marks["groups"]["main"]["comparisons"]
    s = marks["groups"]["main"]["series"]
    fvcum = (1 + s["FV"]["periods"][0]["gross"]) * (1 + s["FV"]["periods"][1]["gross"]) - 1
    f_sub = (1 + s["F"]["periods"][0]["gross"]) * (1 + s["F"]["periods"][2]["gross"]) - 1                   # F over T1 and T3 only
    fq_sub = (1 + s["FQ"]["periods"][0]["gross"]) * (1 + s["FQ"]["periods"][2]["gross"]) - 1
    assert cmp["FV_minus_F_gross"] == pytest.approx(fvcum - f_sub) and cmp["FV_minus_FQ_gross"] == pytest.approx(fvcum - fq_sub)


def test_marks_hold_the_four_comparisons_and_the_note(tmp_path):
    _, marks = scenario(tmp_path).run(value=True)
    c = marks["groups"]["main"]["comparisons"]
    s = marks["groups"]["main"]["series"]
    for base, key in (("FQ", "FV_minus_FQ"), ("F", "FV_minus_F")):
        assert c[f"{key}_gross"] == pytest.approx(s["FV"]["summary"]["cumulative_gross"] - s[base]["summary"]["cumulative_gross"])
        assert c[f"{key}_net_20bp"] == pytest.approx(s["FV"]["summary"]["cumulative_net_20bp"] - s[base]["summary"]["cumulative_net_20bp"])
    assert c["FV_note"] == "FV fills after the values of record exist, later than F and FQ at each formation; the windows differ by those days"
    assert "FV" in marks["groups"]["main"]["series"] and all("FV" not in g["series"] for k, g in marks["groups"].items() if k != "main")


def test_a_retrospective_formation_never_has_an_fv_period(tmp_path):
    fs = [{"T": T1, "book": BOOK1, "fv_held": []}, {"T": T2, "book": BOOK23, "label": "retrospective", "fv_held": []}]
    w = W.World(tmp_path, fs)
    w.snapshot(T1, names(S1))
    w.snapshot(T2, names(S2))
    L, marks = w.run(value=True)
    assert {l["formation_T"] for l in L["actions"] if l["arm"] == "FV"} == {T1}
    assert "FV" not in marks["groups"][f"retrospective_{T2}"]["series"]


# ---------------------------------------------------------------- when the fill is priced; the checks on the file

def test_a_snapshot_whose_fill_is_not_priced_yet_makes_no_line_until_prices_reach_it(tmp_path, monkeypatch):
    full = list(W.SESSIONS)
    monkeypatch.setattr(W, "SESSIONS", [d for d in full if d <= date(2026, 9, 1)])               # prices end 09-01; T2's FV fill is 09-02
    w = scenario(tmp_path, snaps=(T1, T2), n=2)
    w.write(value=True)
    stored = [l for l in w.lines("actions") if l["arm"] == "FV"]
    assert {l["formation_T"] for l in stored} == {T1}
    monkeypatch.setattr(W, "SESSIONS", full)
    w.prices_for(sorted(set(W.GROWTH) | {"GONE"}))
    counts, _ = w.write(value=True)
    now = [l for l in w.lines("actions") if l["arm"] == "FV"]
    assert {l["formation_T"] for l in now} == {T1, T2} and now[:len(stored)] == stored and len(now) > len(stored)


def test_stop_when_the_fill_session_is_not_the_first_open_after_written(tmp_path):
    w = scenario(tmp_path)
    w.snapshot(T1, names(S1), fill_session=F1)                                                # written 08-04 morning: the first open is 08-04
    with pytest.raises(E.Stop, match="first open after written_utc"):
        w.run(value=True)


def test_stop_when_fill_sessions_do_not_increase(tmp_path):
    w = scenario(tmp_path)
    w.snapshot(T2, names(S2, {"E": 6.0}), written="2026-08-04T11:00:00Z")                      # fill 08-04 again
    with pytest.raises(E.Stop, match="does not come after"):
        w.run(value=True)


def test_stop_for_a_snapshot_of_another_formation(tmp_path):
    w = scenario(tmp_path)
    w.snapshot(T1, names(S1), formation_T=T2)
    with pytest.raises(E.Stop, match="formation_T"):
        w.run(value=True)


def test_stop_when_the_snapshot_lacks_a_book_name(tmp_path):
    w = scenario(tmp_path)
    w.snapshot(T1, names({k: v for k, v in S1.items() if k != "C"}))
    with pytest.raises(E.Stop, match="no book-role entry"):
        w.run(value=True)


# ---------------------------------------------------------------- append-only

def test_a_rerun_appends_nothing_and_a_new_formation_appends_only_its_own_lines(tmp_path, monkeypatch):
    full = list(W.SESSIONS)
    monkeypatch.setattr(W, "SESSIONS", [d for d in full if d <= date(2026, 9, 30)])
    w1 = scenario(tmp_path, snaps=(T1, T2), n=2)
    w1.write(value=True)
    before = [json.loads(x) for x in (w1.ledger / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert w1.write(value=True)[0] == dict.fromkeys(E.LINE_FILES, 0)
    monkeypatch.setattr(W, "SESSIONS", full)
    w2 = scenario(tmp_path, snaps=(T1, T2, T3))                                                   # one more formation and snapshot, later prices
    counts, new_marks = w2.write(value=True)
    after = [json.loads(x) for x in (w2.ledger / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert new_marks and after[:len(before)] == before
    assert {l["formation_T"] for l in after[len(before):] if l["arm"] == "FV"} == {T3}
    assert w2.write(value=True)[0] == dict.fromkeys(E.LINE_FILES, 0)


def test_a_changed_snapshot_stops_the_engine_through_the_stored_lines(tmp_path):
    w = scenario(tmp_path)
    w.write(value=True)
    w.snapshot(T1, names({**S1, "C": 6.0}))                                                    # a rewritten snapshot: C would now be cheap
    with pytest.raises(E.Stop, match="actions.jsonl"):
        w.write(value=True)


def test_fv_held_now_takes_the_latest_formation_with_fv_lines():
    L = {"actions": [{"arm": "FV", "kind": "at_fill_open", "formation_T": "2026-11-30", "ticker": "A", "action": "enter"},
                     {"arm": "FV", "kind": "at_fill_open", "formation_T": "2026-12-31", "ticker": "B", "action": "enter"},
                     {"arm": "FV", "kind": "at_fill_open", "formation_T": "2026-12-31", "ticker": "A", "action": "exit"},
                     {"arm": "FV", "kind": "at_fill_open", "formation_T": "2026-12-31", "ticker": "C", "action": "hold"},
                     {"arm": "FV", "kind": "at_fill_open", "formation_T": "2026-12-31", "ticker": "D", "action": "not_entered"},
                     {"arm": "FQ", "kind": "at_fill_open", "formation_T": "2027-01-29", "ticker": "Z", "action": "enter"}]}
    assert E.fv_held_now(L) == ["B", "C"] and E.fv_held_now({"actions": []}) == []
