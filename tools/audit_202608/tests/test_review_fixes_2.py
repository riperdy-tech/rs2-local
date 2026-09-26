"""tools/audit_202608/tests/test_review_fixes_2.py

Tests for Phase 4 Review Fixes 2 (brief_full_thinking_2.md):
- B1: Whole-sample retry snapshot read & first_attempt_failure tracking
- B2: continue_report think level propagation, report_continued record & REPORT_CONTINUED flag
- C2: Budget-exhausted memorandum sets failure = "report_not_delivered" on undeliverable report
- C3: Exception in whole-sample retry caught as lost sample (samples_lost)
"""
import json
import os
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
RS2 = HERE.parent.parent
sys.path.insert(0, str(RS2))
sys.path.insert(0, str(HERE))

import analyst_tools as at
import consensus_valuation as cv
import depth_pipeline as dp

DESK_OK = {
    "scenario_dcfs": [
        {"name": n, "dcf": {"per_share_iv": iv, "per_share_iv_gordon": iv, "terminal_method": "Gordon growth @ 3.8%"}}
        for n, iv in (("Base", 409.92), ("Bull", 460.0), ("Bear", 299.0))
    ],
    "reverse_dcf": {"implied_growth_next_5y_pct": 3.0},
    "kelly_sizing": {"quarter_kelly_pct": 20.98, "recommendation": "ALLOCATE"},
    "markdown_report": "### FINANCIAL MODELING DESK REPORT",
}
CONTRACT = {
    "base_iv": 409.92, "bull_iv": 460.0, "bear_iv": 299.0, "base_probability": 0.5,
    "conviction_score": 9, "business_quality_moat": 3, "kelly_fraction_pct": 5.0,
    "asymmetric_payoff_skew": 1.5, "verdict_label": "hold", "position_basis": "none",
}
MEMO = (
    "SECTION 0. EXECUTIVE VERDICT\n" + "memo line\n" * 700
    + "SECTION 12\n```json:underwriting\n" + json.dumps(CONTRACT) + "\n```\n"
)
DESK_CALL = [{"function": {"name": "run_financial_model", "arguments": {"price": 400.0}}}]


def _resp(content="", done="stop", prompt=28581, tool_calls=None):
    m = {"content": content, "thinking": "t"}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {
        "message": m,
        "done_reason": done,
        "prompt_eval_count": prompt,
        "eval_count": 10,
        "eval_duration": 1_000_000_000,
    }


class _R:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_b1_retry_snapshot_and_first_attempt_failure(monkeypatch, tmp_path):
    # Test B1: first attempt ends window_exhausted_twice; retry makes one desk call and
    # writes deliverable report whose base IV matches desk ->
    # desk_calls >= 1, no desk_not_used flag, basis True, failed_reason None,
    # first_attempt_failure "window_exhausted_twice", window_retry_used True, sample_retried True.
    queue = [
        _resp("", "length"),                                  # attempt 1 turn 1: window length
        _resp("", "length"),                                  # attempt 1 turn 2 (window retry): length -> window_exhausted_twice
        _resp("", tool_calls=DESK_CALL, prompt=28600),       # attempt 2 (whole-sample retry) turn 1: desk call
        _resp(MEMO, prompt=31000),                            # attempt 2 turn 2: deliverable memo
    ]
    bodies = []

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return _R(queue.pop(0))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", lambda name, args, **kw: DESK_OK)

    pack = tmp_path / "_sim_pack.md"
    pack.write_text("SIM PACK\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["consensus_valuation.py", "ZZSIM", "--tools", "--samples", "1", "--pack-file", str(pack),
         "--out-dir", str(tmp_path / "cons"), "--price", "400", "--no-research", "--think", "high"]
    )
    cv.main()

    d = sorted((tmp_path / "cons").glob("ZZSIM_*"))[-1]
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert len(doc["runs"]) == 1
    r = doc["runs"][0]

    assert r["desk_calls"] >= 1
    assert "desk_not_used" not in (r.get("flags") or [])
    assert r["desk_iv_match"] is True
    assert r["basis"] is True
    assert r["failed_reason"] is None
    assert r["first_attempt_failure"] == "window_exhausted_twice"
    assert r["window_retry_used"] is True
    assert r["sample_retried"] is True

    # Confirm the snapshot read was from sample1_research_retry
    retry_snap_path = d / "sample1_research_retry" / "_research_snapshot.json"
    assert retry_snap_path.exists()
    snap_data = json.loads(retry_snap_path.read_text(encoding="utf-8"))
    assert any(c.get("tool") == "run_financial_model" for c in snap_data.get("calls", []))


def test_b2_continuation_carries_configured_think_and_stamps_record(monkeypatch, tmp_path):
    # Test B2: report continuation carries configured think level ("medium"),
    # run record carries report_continued with {chars_rescued, done_reason, think}
    partial = "SECTION 0. EXECUTIVE VERDICT\n" + "memo line\n" * 700 + "SECTION 11. Decision journal, cut mid-sent"
    rest = "ence.\nSECTION 12\n```json:underwriting\n" + json.dumps(CONTRACT) + "\n```\n"

    queue = [
        _resp("", tool_calls=DESK_CALL),                      # turn 1: desk call
        _resp(partial, "length"),                              # turn 2: report cut at window
        _resp(rest, "stop"),                                   # turn 3: continue_report
    ]
    bodies = []

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return _R(queue.pop(0))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", lambda name, args, **kw: DESK_OK)

    pack = tmp_path / "_sim_pack.md"
    pack.write_text("SIM PACK\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["consensus_valuation.py", "ZZCONT", "--tools", "--samples", "1", "--pack-file", str(pack),
         "--out-dir", str(tmp_path / "cons"), "--price", "400", "--no-research", "--think", "medium"]
    )
    cv.main()

    # The 3rd request was the continuation call
    assert len(bodies) == 3
    cont_req = bodies[-1]
    assert cont_req.get("think") == "medium"

    d = sorted((tmp_path / "cons").glob("ZZCONT_*"))[-1]
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    r = doc["runs"][0]
    rc = r.get("report_continued")
    assert isinstance(rc, dict)
    assert rc["chars_rescued"] == len(rest)
    assert rc["done_reason"] == "stop"
    assert rc["think"] == "medium"


def test_b2_band_verdict_raises_report_continued():
    # Test B2: band_verdict raises REPORT_CONTINUED for a basis sample with report_continued truthy, and not otherwise
    doc_with = {
        "ticker": "TEST", "price": 400.0, "median_iv": 409.92,
        "runs": [
            {"sample": 1, "iv": 409.92, "plausible": True, "basis": True,
             "report_continued": {"chars_rescued": 120, "done_reason": "stop", "think": "high"}},
            {"sample": 2, "iv": 410.0, "plausible": True, "basis": True, "report_continued": None},
        ],
    }
    v_with = dp.band_verdict(doc_with)
    assert "REPORT_CONTINUED" in v_with.get("flags", [])

    doc_without = {
        "ticker": "TEST", "price": 400.0, "median_iv": 409.92,
        "runs": [
            {"sample": 1, "iv": 409.92, "plausible": True, "basis": True, "report_continued": None},
            {"sample": 2, "iv": 410.0, "plausible": True, "basis": True, "report_continued": None},
        ],
    }
    v_without = dp.band_verdict(doc_without)
    assert "REPORT_CONTINUED" not in v_without.get("flags", [])

    # If non-basis sample had report_continued, it does not trigger REPORT_CONTINUED flag
    doc_non_basis = {
        "ticker": "TEST", "price": 400.0, "median_iv": 409.92,
        "runs": [
            {"sample": 1, "iv": 409.92, "plausible": True, "basis": False,
             "report_continued": {"chars_rescued": 120, "done_reason": "stop", "think": "high"}},
        ],
    }
    v_nb = dp.band_verdict(doc_non_basis)
    assert "REPORT_CONTINUED" not in v_nb.get("flags", [])


def test_c2_budget_exhausted_memo_sets_failure_on_undeliverable_report(monkeypatch, tmp_path):
    # Test C2: in chat_with_tools, after budget-exhausted forced memorandum, if report is not deliverable,
    # failure = "report_not_delivered"
    bodies = []
    # Turn 1: tool call run_financial_model (max_model_calls=1 will be reached)
    # Turn 2: budget exhausted memorandum returns non-deliverable short stub
    queue = [
        _resp("", tool_calls=DESK_CALL),
        _resp("This is a short incomplete stub without section 12", "stop"),
    ]

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return _R(queue.pop(0))

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", lambda name, args, **kw: DESK_OK)

    report, think, meta = at.chat_with_tools(
        "m", "pack", tmp_path, max_search_calls=0, max_model_calls=1, verbose=False
    )
    assert not at.report_is_deliverable(report)
    assert meta.get("failure") == "report_not_delivered"


def test_c3_whole_sample_retry_exception_counted_as_samples_lost(monkeypatch, tmp_path):
    # Test C3: exception in whole-sample retry is a lost sample, not a crash, and samples_lost counts it
    queue = [
        _resp("", "length"),                                  # attempt 1 turn 1: window length
        _resp("", "length"),                                  # attempt 1 turn 2: length -> empty report
    ]

    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if queue:
            return _R(queue.pop(0))
        # Whole-sample retry call triggers exception
        raise RuntimeError("Simulated crash during whole-sample retry")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    pack = tmp_path / "_sim_pack.md"
    pack.write_text("SIM PACK\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["consensus_valuation.py", "ZZFAIL", "--tools", "--samples", "1", "--pack-file", str(pack),
         "--out-dir", str(tmp_path / "cons"), "--price", "400", "--no-research"]
    )
    # cv.main() should complete without raising
    cv.main()

    d = sorted((tmp_path / "cons").glob("ZZFAIL_*"))[-1]
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert doc["samples_attempted"] == 1
    assert doc["samples_run"] == 0
    assert doc["samples_lost"] == 1
    assert len(doc["runs"]) == 0
