"""orchestrate_depth.build_queue — the ONE queue both arms serve
(DEPTH_ORCHESTRATOR_CADENCE_20260825.md §3 run criteria, §5 priority, §4 entry dwell)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# orchestrate_depth re-wraps sys.stdout at import (utf-8 console on Windows). Under pytest that
# wraps the capture buffer, and letting the wrapper be garbage-collected would close it — same
# hazard api_llm/publish_cloud_verdicts.py guards with _STDOUT_KEEPALIVE. Keep it, restore ours.
_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
import depth_triggers  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT

V = {"date": "2026-08-01", "direction": "hold"}     # any existing verdict
FS = {"RN1": {"fct_band": "research_now"}, "RN2": {"fct_band": "research_now"},
      "WL1": {"fct_band": "watchlist"}, "WL2": {"fct_band": "watchlist"}}


def q(book, st=None, trig=None, verdicts=None, fs=None, **kw):
    return od.build_queue(sorted(book), st or {}, trig or {}, verdicts or {}, fs or FS, **kw)


def tickers(rows):
    return [t for t, _, _ in rows]


def test_priority_classes_then_band_then_alpha():
    book = ["ROT", "BASE", "RN1", "WL1", "REENT", "XREV", "OUT"]
    trig = {"RN1": [("move", "9%")], "WL1": [("8k", "8-K")], "OUT": [("filing", "10-Q")],
            "XREV": [("exit_review", "out 3d")], "REENT": [("reentry", "in 6d")],
            "ROT": [("rotation", "95d")]}
    verdicts = {t: V for t in book if t != "BASE"}
    rows = q(book, trig=trig, verdicts=verdicts)
    # class 0 events: RN before WL before rest, alphabetical inside rest
    assert tickers(rows) == ["RN1", "WL1", "OUT", "XREV", "BASE", "REENT", "ROT"]
    assert [c for _, c, _ in rows] == [0, 0, 0, 0, 1, 2, 3]


def test_verdict_with_no_trigger_is_not_due():
    assert q(["RN1"], verdicts={"RN1": V}) == []


def test_filing_pending_is_visible_but_not_actionable():
    rows = q(["RN1"], trig={"RN1": [("filing_pending", "10-Q; tables behind")]},
             verdicts={"RN1": V})
    assert rows == []
    # ...but with an actionable trigger alongside, the name runs and the why keeps both
    rows = q(["RN1"], trig={"RN1": [("filing_pending", "x"), ("move", "9%")]},
             verdicts={"RN1": V})
    assert tickers(rows) == ["RN1"] and "filing_pending" in rows[0][2]


def test_pack_revision_is_due_but_ranked_with_rotation():
    rows = q(["RN1", "WL1"], trig={"RN1": [("pack", "rev 2 -> 3")], "WL1": [("8k", "x")]},
             verdicts={"RN1": V, "WL1": V})
    assert tickers(rows) == ["WL1", "RN1"]
    assert rows[1][1] == 3


def test_failed_state_uses_retry_budget():
    st = {"RN1": {"ok": False, "retries": od.MAX_RETRIES - 1},
          "WL1": {"ok": False, "retries": od.MAX_RETRIES}}
    # RN1: one retry left -> due even with no trigger. WL1: budget spent -> not due even triggered.
    rows = q(["RN1", "WL1"], st=st, trig={"WL1": [("8k", "x")]}, verdicts={"RN1": V, "WL1": V})
    assert tickers(rows) == ["RN1"]


def test_ok_state_does_not_block_triggered_rerun():
    st = {"RN1": {"ok": True}}
    rows = q(["RN1"], st=st, trig={"RN1": [("move", "9%")]}, verdicts={"RN1": V})
    assert tickers(rows) == ["RN1"]


def test_entry_dwell_gates_baseline_only_once_history_exists():
    d = depth_triggers.ENTRY_DWELL
    dwell = {"RN1": d - 1, "WL1": d}.get
    # dormant: fewer rows than the dwell -> every never-analysed name is due
    assert tickers(q(["RN1", "WL1"], dwell_in=dwell, rows=d - 1)) == ["RN1", "WL1"]
    # live: RN1 has not dwelt long enough, WL1 has
    assert tickers(q(["RN1", "WL1"], dwell_in=dwell, rows=d)) == ["WL1"]
    # no dwell function injected -> no gate (the function stays pure)
    assert tickers(q(["RN1", "WL1"], rows=d)) == ["RN1", "WL1"]


def test_held_name_is_exempt_from_entry_dwell():
    d = depth_triggers.ENTRY_DWELL
    rows = q(["RN1"], dwell_in=lambda t: 0, held=frozenset({"RN1"}), rows=d)
    assert tickers(rows) == ["RN1"]


def test_entry_dwell_never_touches_names_with_a_verdict():
    d = depth_triggers.ENTRY_DWELL
    rows = q(["RN1"], trig={"RN1": [("8k", "x")]}, verdicts={"RN1": V},
             dwell_in=lambda t: 0, rows=d)
    assert tickers(rows) == ["RN1"]


def test_why_strings():
    rows = q(["BASE", "ROT", "RN1"], trig={"RN1": [("8k", "8-K filed 2026-09-01"),
                                                   ("move", "9%")],
                                           "ROT": [("rotation", "95d")]},
             verdicts={"ROT": V, "RN1": V})
    why = {t: w for t, _, w in rows}
    assert why["RN1"] == "8k:8-K filed 2026-09-01, move:9%"
    assert why["BASE"] == "baseline"
    assert why["ROT"] == "rotation:95d"
