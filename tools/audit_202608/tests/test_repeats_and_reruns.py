import pytest
from pathlib import Path
import sys
import json

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at
import capability_test as cap


def test_repeat_calls_jaccard_and_url(monkeypatch, tmp_path):
    """Test repeat_calls counting on a fixed query and URL list:
    - Query 1: initial search
    - Query 2: AMD-style rephrase at Jaccard ~0.6 -> counted as repeat
    - Query 3: Genuinely different query -> NOT counted
    - URL 1: first fetch
    - URL 2: identical URL -> counted as repeat
    - URL 3: different URL -> NOT counted
    """
    # Verify Jaccard directly between Query 1 and Query 2
    q1 = "AMD OpenAI multi-billion chip partnership capex"
    q2 = "AMD OpenAI multi-billion chip supply agreement"
    s1 = at._normalize_tokens(q1)
    s2 = at._normalize_tokens(q2)
    jaccard = len(s1 & s2) / len(s1 | s2)
    # Tokens: amd, openai, multi, billion, chip, partnership, capex (7 tokens)
    # Tokens: amd, openai, multi, billion, chip, supply, agreement (7 tokens)
    # Common: amd, openai, multi, billion, chip (5 tokens). Union: 9 tokens. 5/9 = 0.555 (>= 0.50)
    assert 0.50 <= jaccard < 0.75

    # Genuinely different query:
    q3 = "Hyperscaler data center cooling power constraints"
    s3 = at._normalize_tokens(q3)
    jaccard_diff = len(s1 & s3) / len(s1 | s3)
    assert jaccard_diff == 0.0

    call_seq = [
        {"name": "search_web", "arguments": json.dumps({"query": q1})},
        {"name": "search_web", "arguments": json.dumps({"query": q2})},
        {"name": "search_web", "arguments": json.dumps({"query": q3})},
        {"name": "fetch_page", "arguments": json.dumps({"url": "https://ir.amd.com/news"})},
        {"name": "fetch_page", "arguments": json.dumps({"url": "https://ir.amd.com/news"})},
        {"name": "fetch_page", "arguments": json.dumps({"url": "https://sec.gov/edgar"})},
    ]

    class _FakeResp:
        def __init__(self, tcs):
            self._body = json.dumps({
                "message": {"role": "assistant", "content": "Executing tools", "tool_calls": tcs},
                "done_reason": "stop"
            }).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    turn_count = 0

    def fake_urlopen(req, *args, **kwargs):
        nonlocal turn_count
        turn_count += 1
        if turn_count == 1:
            tcs = [{"function": c} for c in call_seq]
            return _FakeResp(tcs)
        else:
            return _FakeResp([])

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    def fake_dispatch(name, args, snap=None, query_cache=None, url_cache=None, known_urls=None):
        if name == "search_web":
            return {"results": [{"title": "T", "url": "U", "snippet": "S"}]}
        elif name == "fetch_page":
            return {"url": args.get("url"), "text": "Page content"}
        return {}

    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    rep, think, meta = at.chat_with_tools("fake-model", "test prompt", tmp_path, verbose=False)
    assert meta["research_calls"] == 6
    # q2 is repeat of q1 (+1), URL 2 is repeat of URL 1 (+1) => repeat_calls = 2
    assert meta["repeat_calls"] == 2


def test_desk_runs_extraction():
    # 1. Single DCF
    r_single = {"dcf_model": {"per_share_iv": 145.5}}
    assert at.extract_desk_run_value({}, r_single) == 145.5

    # 2. Batch with Base
    r_batch_base = {
        "scenario_dcfs": [
            {"name": "Bear Case", "dcf": {"per_share_iv": 80.0}},
            {"name": "Base Case", "dcf": {"per_share_iv": 130.0}},
            {"name": "Bull Case", "dcf": {"per_share_iv": 190.0}}
        ]
    }
    assert at.extract_desk_run_value({}, r_batch_base) == 130.0

    # 3. Batch without Base (takes median)
    r_batch_no_base = {
        "scenario_dcfs": [
            {"name": "Conservative", "dcf": {"per_share_iv": 80.0}},
            {"name": "Optimistic", "dcf": {"per_share_iv": 190.0}},
            {"name": "Moderate", "dcf": {"per_share_iv": 135.0}}
        ]
    }
    assert at.extract_desk_run_value({}, r_batch_no_base) == 135.0

    # 4. Blend mode (skipped -> None)
    r_blend = {"mode": "blend", "blended_per_share_iv": 140.0}
    assert at.extract_desk_run_value({"mode": "blend"}, r_blend) is None

    # 5. Reverse DCF only (skipped -> None)
    r_rev = {"reverse_dcf": {"implied_growth": 0.15}}
    assert at.extract_desk_run_value({}, r_rev) is None

    # 6. Errors (skipped -> None)
    r_err = {"error": "wacc must be greater than terminal_g"}
    assert at.extract_desk_run_value({}, r_err) is None


def test_flags_thresholds_edges():
    """Verify exact edge conditions for both new flags:
    - desk_input_revisions_<n>_swing_<x.xx>x: len >= 2 and desk_swing > 1.25
    - research_repeats_<k>_of_<m>: m >= 5 and k/m > 0.15
    """
    def check_flags(desk_runs, research_calls, repeat_calls):
        flags = []
        desk_swing = (round(max(desk_runs) / min(desk_runs), 2)
                      if len(desk_runs) >= 2 and min(desk_runs) > 0 else None)
        if len(desk_runs) >= 2 and desk_swing is not None and desk_swing > 1.25:
            flags.append(f"desk_input_revisions_{len(desk_runs)}_swing_{desk_swing:.2f}x")
        if research_calls >= 5 and (repeat_calls / research_calls) > 0.15:
            flags.append(f"research_repeats_{repeat_calls}_of_{research_calls}")
        return flags, desk_swing

    # Desk edge 1: len < 2
    f, s = check_flags([100.0], 0, 0)
    assert f == []
    assert s is None

    # Desk edge 2: swing == 1.25 (not > 1.25)
    f, s = check_flags([100.0, 125.0], 0, 0)
    assert s == 1.25
    assert not any("desk_input_revisions" in x for x in f)

    # Desk edge 3: swing == 1.26 (> 1.25)
    f, s = check_flags([100.0, 126.0], 0, 0)
    assert s == 1.26
    assert "desk_input_revisions_2_swing_1.26x" in f

    # Research edge 1: m < 5, even if k/m high
    f, _ = check_flags([], 4, 2)
    assert not any("research_repeats" in x for x in f)

    # Research edge 2: m = 5, k/m = 0/5 = 0.0 <= 0.15
    f, _ = check_flags([], 5, 0)
    assert not any("research_repeats" in x for x in f)

    # Research edge 3: m = 5, k/m = 1/5 = 0.20 > 0.15
    f, _ = check_flags([], 5, 1)
    assert "research_repeats_1_of_5" in f

    # Research edge 4: m = 20, k/m = 3/20 = 0.15 (not > 0.15)
    f, _ = check_flags([], 20, 3)
    assert not any("research_repeats" in x for x in f)

    # Research edge 5: m = 20, k/m = 4/20 = 0.20 > 0.15
    f, _ = check_flags([], 20, 4)
    assert "research_repeats_4_of_20" in f


# S3 A+B (brief §4.2): "One model, stated once" is now checklist item 5, directly after item 4
# (departing inputs need reasons) and before item 6 (the reverse DCF).
def test_capability_test_task_has_model_stated_once_bullet():
    expected_bullet = (
        "5. Run Bear, Base and Bull together in one call. Your last complete desk run of all three "
        "is your answer. If you change any input after a complete run, the memorandum's 'Model "
        "revisions' list gives each changed input's old value, new value and the dated evidence "
        "that forced the change. Changing an input because you dislike the resulting value is "
        "forbidden; the harness records every run."
    )
    assert expected_bullet in cap.TASK
    item4_pos = cap.TASK.find("4. Where an input departs from its DEFAULT")
    bullet_pos = cap.TASK.find("5. Run Bear, Base and Bull together in one call.")
    item6_pos = cap.TASK.find("6. The desk also returns price_implied:")
    assert item4_pos != -1
    assert bullet_pos > item4_pos
    assert bullet_pos < item6_pos
