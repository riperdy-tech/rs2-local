import json
import pytest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at


def test_compact_tool_note_search_web():
    args = {"query": "AMD MI350 capex 2026"}
    res = {
        "query": "AMD MI350 capex 2026",
        "results": [
            {"title": "AMD Roadmap", "url": "https://amd.com/news", "snippet": "Capex guidance updated for next year"},
            {"title": "Analyst Note", "url": "https://analyst.com/amd", "snippet": "Hyperscaler demand is strong"},
        ]
    }
    note = at.compact_tool_note("search_web", args, res, 1)
    assert '[call 1] search: "AMD MI350 capex 2026" -> ' in note
    assert "AMD Roadmap | https://amd.com/news | Capex guidance updated for next year" in note
    assert "Analyst Note | https://analyst.com/amd | Hyperscaler demand is strong" in note
    assert "(repeat of an earlier search)" not in note


def test_compact_tool_note_search_web_dedup():
    args = {"query": "AMD MI350 capex 2026"}
    res = {
        "query": "AMD MI350 capex 2026",
        "cache_hit": True,
        "deduplicated_from": "AMD capex 2026",
        "results": [
            {"title": "AMD Roadmap", "url": "https://amd.com/news", "snippet": "Capex guidance updated"}
        ]
    }
    note = at.compact_tool_note("search_web", args, res, 2)
    assert '[call 2] search: "AMD MI350 capex 2026" -> ' in note
    assert "(repeat of an earlier search)" in note


def test_compact_tool_note_search_web_error():
    args = {"query": "bad query"}
    res = {"error": "search failed: connection refused"}
    note = at.compact_tool_note("search_web", args, res, 3)
    assert note == '[call 3] search: "bad query" -> search failed: connection refused'


def test_compact_tool_note_fetch_page():
    args = {"url": "https://sec.gov/edgar/amd10k"}
    long_text = "Detailed 10-K disclosures... " * 100
    res = {"url": args["url"], "text": long_text}
    note = at.compact_tool_note("fetch_page", args, res, 4)
    assert note.startswith("[call 4] page: https://sec.gov/edgar/amd10k -> ")
    # Text clamped to at most 1500 chars
    body = note[len("[call 4] page: https://sec.gov/edgar/amd10k -> "):]
    assert len(body) <= 1500


def test_compact_tool_note_fetch_page_error():
    args = {"url": "https://spam.com/junk"}
    res = {"error": "low-trust source refused"}
    note = at.compact_tool_note("fetch_page", args, res, 5)
    assert note == "[call 5] page: https://spam.com/junk -> low-trust source refused"


def test_compact_tool_note_run_financial_model():
    args = {"mode": "dcf", "price": 100.0}
    res = {
        "price": 100.0,
        "scenario_dcfs": [
            {"name": "Bear", "dcf": {"per_share_iv": 60.0}},
            {"name": "Base", "dcf": {"per_share_iv": 110.0}},
            {"name": "Bull", "dcf": {"per_share_iv": 170.0}},
        ],
        "blend": {"blended_per_share_iv": 112.5},
        "reverse_dcf": {
            "implied_stage1_growth_pct": 14.5,
            "neutral_reference_structure": {"implied_10y_cagr_pct": 11.2}
        },
        "kelly_sizing": {"quarter_kelly_pct": 4.5, "recommendation": "ALLOCATE"},
        "markdown_report": "### DO NOT INCLUDE THIS HUGE TABLE IN COMPACT NOTE ###"
    }
    note = at.compact_tool_note("run_financial_model", args, res, 6)
    assert note.startswith("[call 6] model: ")
    assert "DO NOT INCLUDE" not in note
    payload_str = note[len("[call 6] model: "):]
    assert len(payload_str) <= 1200
    parsed = json.loads(payload_str)
    assert parsed["scenarios"]["Base"] == 110.0
    assert parsed["blend_iv"] == 112.5
    assert parsed["reverse_dcf"]["implied_stage1_growth_pct"] == 14.5
    assert parsed["reverse_dcf"]["neutral_10y_cagr_pct"] == 11.2
    assert parsed["kelly"]["quarter_kelly_pct"] == 4.5


def test_compact_tool_note_budget_quota_messages():
    quota_res = {
        "status": "search_quota_met",
        "message": "Web search budget completed (25 calls). Do not search again."
    }
    note_quota = at.compact_tool_note("search_web", {"query": "q"}, quota_res, 26)
    assert json.loads(note_quota)["status"] == "search_quota_met"

    exhausted_res = {"error": "financial model call budget exhausted (5); use computed results"}
    note_exhausted = at.compact_tool_note("run_financial_model", {}, exhausted_res, 31)
    assert "budget exhausted" in json.loads(note_exhausted)["error"]


def test_compact_history_shrink_order():
    # Build a conversation with:
    # 1. Search call (oldest)
    # 2. Page call (second oldest)
    # 3. Model call (third)
    # 4. Search call (fourth)
    # 5. Assistant turn with new tool call (boundary)
    # 6. Latest tool call (must stay full)
    msgs = [
        {"role": "user", "content": "Analyze AMD"},
        {"role": "assistant", "content": "Round 1", "tool_calls": [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}]},
        {"role": "tool", "content": "full search 1 results " * 50},
        {"role": "tool", "content": "full page 1 text " * 100},
        {"role": "tool", "content": "full model output " * 50},
        {"role": "tool", "content": "full search 2 results " * 50},
        {"role": "assistant", "content": "Round 2", "tool_calls": [{"id": "5"}]},
        {"role": "tool", "content": "latest round tool result that MUST stay full"}
    ]
    meta = [
        None,
        None,
        {"name": "search_web", "args": {"query": "AMD 1"}, "result": {"results": [{"title": "T1", "url": "U1", "snippet": "S1" * 30}]}, "call_index": 1},
        {"name": "fetch_page", "args": {"url": "https://amd1.com"}, "result": {"text": "Page text 1 " * 40}, "call_index": 2},
        {"name": "run_financial_model", "args": {}, "result": {"dcf_model": {"per_share_iv": 150.0}}, "call_index": 3},
        {"name": "search_web", "args": {"query": "AMD 2"}, "result": {"results": [{"title": "T2", "url": "U2", "snippet": "S2" * 30}]}, "call_index": 4},
        None,
        {"name": "search_web", "args": {"query": "AMD 3"}, "result": {"results": [{"title": "T3", "url": "U3", "snippet": "S3"}]}, "call_index": 5}
    ]

    # Without budget restriction
    res_large = at._compact_history(msgs, meta, budget_chars=36000)
    assert res_large[7]["content"] == "latest round tool result that MUST stay full"
    assert '[call 1] search: "AMD 1" -> ' in res_large[2]["content"]
    assert '[call 2] page: https://amd1.com -> ' in res_large[3]["content"]
    assert '[call 3] model: ' in res_large[4]["content"]
    assert '[call 4] search: "AMD 2" -> ' in res_large[5]["content"]

    # Now restrict budget so the oldest notes must shrink to header-only
    # Set budget small enough so call 1 and call 2 shrink, but call 4 does not, and model is never shrunk
    total_before = sum(len(res_large[i]["content"]) for i in (2, 3, 4, 5))
    shrunk_call1 = '[call 1] search: "AMD 1" (results shown earlier)'
    budget_tight = total_before - len(res_large[2]["content"]) + len(shrunk_call1) + 10

    res_shrunk = at._compact_history(msgs, meta, budget_chars=budget_tight)
    # Oldest (call 1) should be shrunk to header-only
    assert res_shrunk[2]["content"] == shrunk_call1
    # Model notes (call 3) MUST NEVER be shrunk
    assert '[call 3] model: ' in res_shrunk[4]["content"]
    assert "results shown earlier" not in res_shrunk[4]["content"]
    # Latest round tool stays full
    assert res_shrunk[7]["content"] == "latest round tool result that MUST stay full"


def test_synthetic_25_call_history_budget():
    """Create a synthetic 25-call history (20 search/fetch + 5 model runs), measure size."""
    msgs = [{"role": "user", "content": "Initial prompt"}]
    meta = [None]
    call_idx = 0

    # 5 rounds of 4 research calls + 1 model call = 25 calls total
    for r in range(5):
        tcs = [{"id": f"tc_{r}_{j}"} for j in range(5)]
        msgs.append({"role": "assistant", "content": f"Round {r+1}", "tool_calls": tcs})
        meta.append(None)
        # 3 searches, 1 fetch, 1 model call per round
        for s in range(3):
            call_idx += 1
            msgs.append({"role": "tool", "content": "raw verbose search result " * 80})
            meta.append({
                "name": "search_web",
                "args": {"query": f"company research topic {call_idx}"},
                "result": {
                    "results": [
                        {"title": f"Result {k}", "url": f"https://example.com/{k}", "snippet": f"Important finding snippet {k} " * 5}
                        for k in range(4)
                    ]
                },
                "call_index": call_idx
            })
        call_idx += 1
        msgs.append({"role": "tool", "content": "raw verbose page text " * 150})
        meta.append({
            "name": "fetch_page",
            "args": {"url": f"https://example.com/filing_{call_idx}"},
            "result": {"text": f"Filing textual content about capital allocation {call_idx} " * 50},
            "call_index": call_idx
        })
        call_idx += 1
        msgs.append({"role": "tool", "content": "raw model output markdown report " * 100})
        meta.append({
            "name": "run_financial_model",
            "args": {"mode": "dcf"},
            "result": {
                "scenario_dcfs": [
                    {"name": "Base", "dcf": {"per_share_iv": 100.0 + call_idx}},
                    {"name": "Bear", "dcf": {"per_share_iv": 60.0 + call_idx}},
                    {"name": "Bull", "dcf": {"per_share_iv": 150.0 + call_idx}}
                ],
                "reverse_dcf": {"implied_stage1_growth_pct": 12.0}
            },
            "call_index": call_idx
        })

    # Add a 6th round assistant turn so all 25 earlier calls are before last_asst_idx
    msgs.append({"role": "assistant", "content": "Round 6", "tool_calls": [{"id": "tc_6"}]})
    meta.append(None)
    msgs.append({"role": "tool", "content": "Round 6 tool result"})
    meta.append({"name": "search_web", "args": {"query": "final search"}, "result": {"results": []}, "call_index": 26})

    compacted = at._compact_history(msgs, meta, budget_chars=36000)
    # Measure compacted tool notes characters
    compact_chars = sum(len(m["content"]) for idx, m in enumerate(compacted) if m["role"] == "tool" and idx < len(compacted) - 1)
    print(f"Synthetic 25-call compacted size: {compact_chars} chars")
    assert compact_chars <= 36000
    assert compact_chars > 0


class _CaptureFakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_three_request_paths_use_compacted_history(monkeypatch, tmp_path):
    """Verify that:
    Path 1: main loop subsequent turn
    Path 2: forced-report retry turn
    Path 3: all-budgets-exhausted final turn
    all use _compact_history (no placeholder string, compact notes present, latest round full).
    """
    captured_requests = []

    def fake_urlopen(req, *args, **kwargs):
        body = json.loads(req.data.decode("utf-8"))
        captured_requests.append(body)
        turn_num = len(captured_requests)
        if turn_num == 1:
            # Turn 1: model returns 2 tool calls
            return _CaptureFakeResponse({
                "message": {
                    "role": "assistant",
                    "content": "Searching...",
                    "tool_calls": [
                        {"function": {"name": "search_web", "arguments": json.dumps({"query": "q1"})}},
                        {"function": {"name": "fetch_page", "arguments": json.dumps({"url": "http://p1"})}}
                    ]
                },
                "done_reason": "stop",
                "eval_count": 20,
                "eval_duration": 100_000_000
            })
        elif turn_num == 2:
            # Turn 2: model returns another tool call (so round 1 tool calls must be compacted)
            return _CaptureFakeResponse({
                "message": {
                    "role": "assistant",
                    "content": "Searching round 2...",
                    "tool_calls": [
                        {"function": {"name": "run_financial_model", "arguments": json.dumps({"price": 100.0, "scenarios": [{"name": "Base", "base_cf": 10.0, "growth_rates": [0.1], "wacc": 0.09, "terminal_g": 0.02}]})}}
                    ]
                },
                "done_reason": "stop",
                "eval_count": 20,
                "eval_duration": 100_000_000
            })
        elif turn_num == 3:
            # Turn 3: stub report -> triggers forced-report retry (Path 2)
            return _CaptureFakeResponse({
                "message": {
                    "role": "assistant",
                    "content": "Short stub",
                    "tool_calls": []
                },
                "done_reason": "stop",
                "eval_count": 10,
                "eval_duration": 50_000_000
            })
        else:
            # Forced report response
            return _CaptureFakeResponse({
                "message": {
                    "role": "assistant",
                    "content": "SECTION 1: Formal institutional memorandum text ... " * 200,
                    "tool_calls": []
                },
                "done_reason": "stop",
                "eval_count": 500,
                "eval_duration": 500_000_000
            })

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    # Mock dispatch_tool to avoid network
    def fake_dispatch(name, args, snap=None, query_cache=None, url_cache=None):
        if name == "search_web":
            return {"results": [{"title": "T1", "url": "U1", "snippet": "S1"}]}
        elif name == "fetch_page":
            return {"url": args.get("url"), "text": "Page content 1"}
        elif name == "run_financial_model":
            return {"mode": "dcf", "dcf_model": {"per_share_iv": 105.0}}
        return {}

    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    rep, think, meta = at.chat_with_tools("fake-model", "test prompt", tmp_path, verbose=False)

    assert len(captured_requests) == 4
    # Request 2 (Path 1: main loop turn 2):
    req2_msgs = captured_requests[1]["messages"]
    tool_msgs_req2 = [m for m in req2_msgs if m["role"] == "tool"]
    # Both round 1 tool calls must be full since round 2 hasn't executed yet
    assert len(tool_msgs_req2) == 2

    # Request 3 (main loop turn 3, after round 2 tool execution):
    req3_msgs = captured_requests[2]["messages"]
    # Round 1 tool calls must be compacted (before last assistant turn); round 2 must be full
    assert any("[call 1] search:" in m["content"] for m in req3_msgs if m["role"] == "tool")
    assert any("[call 2] page:" in m["content"] for m in req3_msgs if m["role"] == "tool")
    for m in req3_msgs:
        assert "[Retrieved research digested" not in m.get("content", "")

    # Request 4 (Path 2: forced-report retry):
    req4_msgs = captured_requests[3]["messages"]
    assert any("[call 1] search:" in m["content"] for m in req4_msgs if m["role"] == "tool")
    for m in req4_msgs:
        assert "[Retrieved research digested" not in m.get("content", "")


def test_path3_all_budgets_exhausted_uses_compacted_history(monkeypatch, tmp_path):
    captured_requests = []

    def fake_urlopen(req, *args, **kwargs):
        body = json.loads(req.data.decode("utf-8"))
        captured_requests.append(body)
        turn_num = len(captured_requests)
        if turn_num == 1:
            # Emit 25 search calls and 5 model calls
            tcs = []
            for i in range(25):
                tcs.append({"function": {"name": "search_web", "arguments": json.dumps({"query": f"q_{i}"})}})
            for i in range(5):
                tcs.append({"function": {"name": "run_financial_model", "arguments": json.dumps({"price": 10.0})}})
            return _CaptureFakeResponse({
                "message": {"role": "assistant", "content": "Exhausting budgets", "tool_calls": tcs},
                "done_reason": "stop"
            })
        else:
            return _CaptureFakeResponse({
                "message": {"role": "assistant", "content": "FINAL REPORT " * 500, "tool_calls": []},
                "done_reason": "stop"
            })

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    def fake_dispatch(name, args, snap=None, query_cache=None, url_cache=None):
        if name == "search_web":
            return {"results": [{"title": "T", "url": "U", "snippet": "S"}]}
        return {"mode": "dcf", "dcf_model": {"per_share_iv": 50.0}}

    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    rep, think, meta = at.chat_with_tools("fake-model", "test prompt", tmp_path, verbose=False)
    assert len(captured_requests) == 2
    # Request 2 is Path 3: all-budgets-exhausted
    req2_msgs = captured_requests[1]["messages"]
    assert req2_msgs[-1]["role"] == "user"
    assert "Tool budgets are exhausted" in req2_msgs[-1]["content"]
    # Check that no placeholder string exists
    for m in req2_msgs:
        assert "[Retrieved research digested" not in m.get("content", "")
