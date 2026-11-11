"""Paper book FV's exits between formations (WO_TB2a, SPEC_m3o_bookV rules 6 to 8): the engine reads value/fv_exits.jsonl and applies it.
Synthetic worlds only; the scenario is test_engine_fv's (T1 enters A, D, E at V1). Run from the repo root: python -m pytest tools/paper_books/tests -q"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as W  # noqa: E402
from test_engine import act, per, r  # noqa: E402
from test_engine_fv import LAST, S2, T1, T2, T3, V1, V2, V3, F1, names, rc, scenario  # noqa: E402

E = W.E
D1 = "2026-08-18T20:00:00Z"                  # decided after the close of 08-18: effective at the 08-19 open
X1 = "2026-08-19"


@pytest.fixture(autouse=True)
def fv_start(monkeypatch):
    monkeypatch.setattr(E, "FV_START", T1)


def xr(T, t, decided=D1, reason="under_review", kind="news_event", **over):
    return {"formation_T": T, "ticker": t, "reason": reason, "warning_kind": kind, "warning_event_id": "ev-" + t, "decided_utc": decided,
            "effective_session": E.first_open_after(E.parse_utc(decided)).isoformat(), "revaluation": None, **over}


def d(s):
    return date.fromisoformat(s)


def bf(L, T, t):
    return act(L, T, "FV", t, kind="between_formations")


def strip_bf(marks):
    """marks without the period records' between_formations key"""
    out = json.loads(json.dumps(marks))
    for p in out["groups"]["main"]["series"]["FV"]["periods"]:
        p.pop("between_formations")
    return out


# ---------------------------------------------------------------- no file, an empty file

def test_no_file_and_an_empty_file_leave_lines_and_marks_as_they_are(tmp_path):
    w = scenario(tmp_path)
    L0, m0 = w.run(value=True)
    w.write_exits([])
    assert w.run(value=True) == (L0, m0)
    w.write_exits([], raw=b"\n\n")
    assert w.run(value=True) == (L0, m0)
    assert all(p["between_formations"] == [] for p in m0["groups"]["main"]["series"]["FV"]["periods"])
    assert not [l for l in L0["actions"] if l["kind"] == "between_formations"]


def test_arm_step_without_exits_is_what_it_was(tmp_path):
    w = W.World(tmp_path)
    pre, plan = {"CASH": 0.2, "A": 0.8}, {"positions": {"A": 0.5, "B": 0.5}, "slots": {}, "cash": 0.0}
    base = E.arm_step(pre, plan, w.px, d(V1), d(V2), d(LAST))
    assert E.arm_step(pre, plan, w.px, d(V1), d(V2), d(LAST), None) == base == E.arm_step(pre, plan, w.px, d(V1), d(V2), d(LAST), {})


# ---------------------------------------------------------------- an applied exit

def test_arm_step_sells_the_leaver_at_the_exit_open_and_its_value_is_cash(tmp_path):
    w = W.World(tmp_path)
    plan = {"positions": {"A": 0.5, "B": 0.5}, "slots": {}, "cash": 0.0}
    s = E.arm_step({"CASH": 1.0}, plan, w.px, d(V1), d(V2), d(LAST), {"A": d(X1)})
    ra, rb = r("A", V1, X1), r("B", V1, V2)
    g = 0.5 * ra + 0.5 * rb
    assert s["gross"] == pytest.approx(g) and s["turnover"] == pytest.approx(0.5 + 0.5 * 0.5 * (1 + ra)) and s["n"] == 2
    assert s["post"] == pytest.approx({"CASH": 0.5 * (1 + ra) / (1 + g), "B": 0.5 * (1 + rb) / (1 + g)}) and sum(s["post"].values()) == pytest.approx(1.0)
    assert s["cash_weight"] == 0.0 and s["rets"]["A"] == pytest.approx(ra)               # cash at the fill: the sale's cash is not counted in it


def test_an_applied_exit_period_line_and_the_next_decision(tmp_path):
    w = scenario(tmp_path)
    rec = xr(T1, "D", reason="revalued_not_cheap", kind="thesis_changed", revaluation={"value_base": 1.5, "seeds": [{"x": [1, 2]}], "n": None})
    w.write_exits([rec])
    L, marks = w.run(value=True)
    ra, rd, re_ = r("A", V1, V2), r("D", V1, X1), r("E", V1, V2)
    g1 = (ra + rd + re_) / 3
    p1 = per(marks, "FV", 0)
    assert p1["gross"] == pytest.approx(g1) and p1["n"] == 3 and p1["cash_weight_at_fill"] == 0.0
    assert p1["turnover_one_way"] == pytest.approx(0.5 + 0.5 * (1 / 3) * (1 + rd))
    assert p1["between_formations"] == [{"ticker": "D", "reason": "revalued_not_cheap", "effective_session": X1, "applied": True,
                                         "return_to_exit": pytest.approx(rd), "return_after_exit": pytest.approx(r("D", X1, V2))}]
    x = bf(L, T1, "D")
    assert (x["arm"], x["kind"], x["action"], x["rule"], x["reason"], x["flags"], x["label"]) == (
        "FV", "between_formations", "exit", "V2", "revalued_not_cheap", [], "shadow_pre_3N_close")
    assert (x["fill_session"], x["a0_fill_session"], x["weight_target"], x["formation_T"]) == (X1, F1, 0.0, T1) and x["weight_before"] == 0.0
    assert x["exit"] == {"warning_kind": "thesis_changed", "warning_event_id": "ev-D", "decided_utc": D1, "effective_session": X1, "applied": True,
                         "revaluation": rec["revaluation"]}
    fv_in = act(L, T1, "FV", "D")["inputs"]
    assert x["inputs"] == {**fv_in, "fv_exit": E.sha256_bytes(json.dumps(rec, sort_keys=True).encode("utf-8"))} and "fv_exit" not in fv_in
    assert act(L, T1, "FV", "D")["action"] == "enter" and act(L, T1, "FV", "D")["kind"] == "at_fill_open"
    # the next decision: D left, so it is not held; the value S2 does not call it cheap
    d2 = act(L, T2, "FV", "D")
    assert (d2["action"], d2["reason"], d2["weight_before"]) == ("not_entered", "not_cheap", 0.0)
    wa, we = (1 / 3) * (1 + ra) / (1 + g1), (1 / 3) * (1 + re_) / (1 + g1)
    p2 = per(marks, "FV", 1)
    assert p2["turnover_one_way"] == pytest.approx(0.5 * (abs(1 / 3 - wa) + abs(1 / 3 - we) + 1 / 3))
    assert [x["ticker"] for x in p2["leavers"]] == [] and act(L, T2, "FV", "E")["value"]["periods_held"] == 1
    assert E.fv_held_now(L) == ["A", "B", "E", "F"]


def test_a_leaver_may_enter_again_when_cheap_with_counts_from_zero(tmp_path):
    w = scenario(tmp_path)
    w.snapshot(T2, names({**S2, "D": 5.0}, {"E": 6.0}))                                         # cut 3.5: D is cheap again
    w.write_exits([xr(T1, "D")])
    L, marks = w.run(value=True)
    d2 = act(L, T2, "FV", "D")
    assert (d2["action"], d2["reason"], d2["weight_before"]) == ("enter", "cheap", 0.0)
    assert (d2["value"]["periods_held"], d2["value"]["missed"]) == (0, 0)
    assert per(marks, "FV", 1)["leavers"] == []


def test_under_review_and_revalued_not_cheap_both_apply_and_the_revaluation_is_carried_untouched(tmp_path):
    w = scenario(tmp_path)
    reval = {"value_base": 1.5, "cheapness": 0.2, "nested": {"list": [1, 2.5, None], "s": "x"}}
    w.write_exits([xr(T1, "A", "2026-08-11T20:00:00Z", "revalued_not_cheap", "event_found", revaluation=reval), xr(T1, "D", reason="under_review")])
    L, marks = w.run(value=True)
    xa, xd = bf(L, T1, "A"), bf(L, T1, "D")
    assert (xa["reason"], xa["exit"]["warning_kind"], xa["exit"]["effective_session"], xa["exit"]["revaluation"]) == (
        "revalued_not_cheap", "event_found", "2026-08-12", reval)
    assert (xd["reason"], xd["exit"]["warning_kind"], xd["exit"]["revaluation"]) == ("under_review", "news_event", None)
    p1 = per(marks, "FV", 0)
    assert p1["gross"] == pytest.approx((r("A", V1, "2026-08-12") + r("D", V1, X1) + r("E", V1, V2)) / 3)
    assert [(x["ticker"], x["applied"]) for x in p1["between_formations"]] == [("A", True), ("D", True)]
    assert xa["inputs"]["fv_exit"] != xd["inputs"]["fv_exit"]


# ---------------------------------------------------------------- not priced yet

def test_an_exit_not_priced_yet_makes_no_line_until_prices_reach_it(tmp_path, monkeypatch):
    full = list(W.SESSIONS)
    monkeypatch.setattr(W, "SESSIONS", [x for x in full if x <= date(2026, 8, 20)])
    w = scenario(tmp_path, snaps=(T1,), n=1)
    no_file = w.run(value=True)
    w.write_exits([xr(T1, "D", "2026-08-20T20:00:00Z")])                                       # effective 08-21: after the last price day
    assert w.run(value=True) == no_file
    w.write(value=True)
    stored = [l for l in w.lines("actions") if l["arm"] == "FV"]
    assert not [l for l in stored if l["kind"] == "between_formations"]
    monkeypatch.setattr(W, "SESSIONS", full)
    w.prices_for(sorted(set(W.GROWTH) | {"GONE"}))
    w.write(value=True)
    now = [l for l in w.lines("actions") if l["arm"] == "FV"]
    assert now[:len(stored)] == stored and [(l["ticker"], l["kind"], l["exit"]["applied"]) for l in now[len(stored):]] == [("D", "between_formations", True)]


# ---------------------------------------------------------------- superseded

@pytest.mark.parametrize("decided,eff", [("2026-09-01T20:00:00Z", V2), ("2026-09-02T20:00:00Z", "2026-09-03")])     # at the next fill, after it
def test_an_exit_on_or_after_the_next_fv_fill_is_superseded_and_changes_nothing(tmp_path, decided, eff):
    w = scenario(tmp_path)
    L0, m0 = w.run(value=True)
    w.write_exits([xr(T1, "D", decided)])
    L, marks = w.run(value=True)
    x = bf(L, T1, "D")
    assert x["exit"]["effective_session"] == eff
    assert (x["flags"], x["exit"]["applied"], x["fill_session"], x["weight_target"]) == (["superseded_by_next_decision"], False, eff, 0.0)
    assert [l for l in L["actions"] if l["kind"] != "between_formations"] == L0["actions"] and len(L["actions"]) == len(L0["actions"]) + 1
    assert strip_bf(marks) == strip_bf(m0)
    b = per(marks, "FV", 0)["between_formations"]
    assert [(y["ticker"], y["applied"], y["return_after_exit"]) for y in b] == [("D", False, None)]
    assert b[0]["return_to_exit"] == pytest.approx(r("D", V1, eff))
    assert {k: v for k, v in per(marks, "FV", 0).items() if k != "between_formations"} == {k: v for k, v in per(m0, "FV", 0).items() if k != "between_formations"}
    assert per(marks, "FV", 1) == per(m0, "FV", 1) and marks["groups"]["main"]["comparisons"] == m0["groups"]["main"]["comparisons"]
    assert E.fv_held_now(L) == E.fv_held_now(L0) == ["A", "B", "E", "F"]


# ---------------------------------------------------------------- the last period, fv_held_now

def test_the_last_period_applies_and_is_marked_at_the_last_close(tmp_path):
    w = scenario(tmp_path)
    w.write_exits([xr(T3, "A", "2026-10-05T20:00:00Z")])                                       # effective 10-06
    L, marks = w.run(value=True)
    p3 = per(marks, "FV", 2)
    assert p3["exit"] == f"OPEN (marked {LAST})" and p3["n"] == 4
    assert p3["gross"] == pytest.approx((r("A", V3, "2026-10-06") + sum(rc(t, V3) for t in "BEF")) / 4)
    y = p3["between_formations"][0]
    assert y["return_to_exit"] == pytest.approx(r("A", V3, "2026-10-06")) and y["return_after_exit"] == pytest.approx(rc("A", "2026-10-06"))
    assert E.fv_held_now(L) == ["B", "E", "F"]
    assert per(marks, "FV", 0)["between_formations"] == []


def test_fv_held_now_leaves_out_an_applied_leaver_of_the_latest_formation_only():
    def line(T, t, a, kind="at_fill_open", applied=None):
        return {"arm": "FV", "kind": kind, "formation_T": T, "ticker": t, "action": a, **({"exit": {"applied": applied}} if applied is not None else {})}
    L = {"actions": [line("2026-11-30", "A", "enter"), line("2026-12-31", "A", "hold"), line("2026-12-31", "B", "hold"), line("2026-12-31", "C", "enter"),
                     line("2026-11-30", "B", "exit", "between_formations", True), line("2026-12-31", "A", "exit", "between_formations", True),
                     line("2026-12-31", "C", "exit", "between_formations", False)]}
    assert E.fv_held_now(L) == ["B", "C"]


# ---------------------------------------------------------------- Stop

def stop(tmp_path, records=None, raw=None, match="", snaps=(T1, T2, T3)):
    w = scenario(tmp_path, snaps=snaps)
    w.write_exits(records or [], raw=raw)
    with pytest.raises(E.Stop, match=match):
        w.run(value=True)


def line_bytes(rec):
    return (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8")


def test_stop_on_a_line_that_is_not_an_object_with_the_keys(tmp_path):
    stop(tmp_path / "a", raw=b"[1, 2]\n", match="not an object with the keys")
    stop(tmp_path / "b", raw=b"not json\n", match="not JSON")
    miss = {k: v for k, v in xr(T1, "D").items() if k != "warning_event_id"}
    stop(tmp_path / "c", raw=line_bytes(miss), match="not an object with the keys")
    no_reval = {k: v for k, v in xr(T1, "D").items() if k != "revaluation"}
    stop(tmp_path / "d", raw=line_bytes(no_reval), match="not an object with the keys")


def test_stop_on_a_reason_outside_the_two(tmp_path):
    stop(tmp_path, [xr(T1, "D", reason="no_longer_cheap")], match="neither revalued_not_cheap nor under_review")


def test_stop_when_effective_session_is_not_the_first_open_after_decided(tmp_path):
    stop(tmp_path / "a", [xr(T1, "D", effective_session="2026-08-20")], match="first open after decided_utc")
    stop(tmp_path / "b", [xr(T1, "D", "2026-08-14T20:00:00Z", effective_session="2026-08-15")], match="first open after decided_utc")   # Friday night: Monday, not Saturday
    stop(tmp_path / "c", [xr(T1, "D", "2026-08-18T20:00:00Z", decided_utc="not a time")], match="decided_utc unreadable")


def test_stop_on_two_lines_for_the_same_formation_and_ticker(tmp_path):
    stop(tmp_path, [xr(T1, "D"), xr(T1, "D", "2026-08-19T20:00:00Z", reason="revalued_not_cheap")], match="a second exit")


def test_stop_when_the_ticker_is_not_held_under_the_decision(tmp_path):
    stop(tmp_path / "a", [xr(T1, "B")], match="not held under that decision")                  # B was not entered at T1
    stop(tmp_path / "b", [xr(T1, "OPXA")], match="not held under that decision")


def test_stop_when_the_exit_was_decided_before_fv_held_the_name(tmp_path):
    stop(tmp_path / "a", [xr(T1, "D", "2026-08-03T10:00:00Z")], match="on or before the decision's fill")                 # effective 08-03, fill 08-04
    stop(tmp_path / "b", [xr(T1, "D", "2026-08-03T20:00:00Z")], match="on or before the decision's fill")                 # effective 08-04 = the fill


def test_stop_when_the_formation_is_not_an_fv_decision(tmp_path):
    stop(tmp_path / "a", [xr("2026-12-31", "D")], match="not under an FV decision")
    stop(tmp_path / "b", [xr(T2, "A", "2026-09-10T20:00:00Z")], match="not under an FV decision", snaps=(T1, T3))      # T2 has no snapshot
    w = W.World(tmp_path / "c", [{"T": T1, "book": ["A", "B", "OPXA"], "fv_held": []}])                                   # no snapshot at all
    w.write_exits([xr(T1, "A")])
    with pytest.raises(E.Stop, match="not under an FV decision"):
        w.run(value=True)


# ---------------------------------------------------------------- append-only

def test_a_rerun_appends_nothing_and_a_stored_exit_line_is_checked_against_its_recomputation(tmp_path):
    w = scenario(tmp_path)
    w.write_exits([xr(T1, "D", reason="revalued_not_cheap", revaluation={"value_base": 1.0})])
    first, _ = w.write(value=True)
    assert first["actions"] > 0 and len([l for l in w.lines("actions") if l["kind"] == "between_formations"]) == 1
    assert w.write(value=True)[0] == dict.fromkeys(E.LINE_FILES, 0)
    w.write_exits([xr(T1, "D", reason="revalued_not_cheap", revaluation={"value_base": 2.0})])        # the stored line's sha no longer matches
    with pytest.raises(E.Stop, match="actions.jsonl"):
        w.write(value=True)
