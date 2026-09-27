"""E17 D1 desk budget and closure tests."""
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at


class _FakeResp(io.BytesIO):
    def __init__(self, obj):
        super().__init__(json.dumps(obj).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_desk_closure_after_5_valid_runs_and_subsequent_research_results(monkeypatch, tmp_path):
    recorded_requests = []
    turn_plan = [
        [{"function": {"name": "run_financial_model", "arguments": {"price": 100.0}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"price": 101.0}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"price": 102.0}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"price": 103.0}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"price": 104.0}}}],
        [{"function": {"name": "search_web", "arguments": {"query": "amphenol news"}}}],
        [{"function": {"name": "fetch_page", "arguments": {"url": "https://example.com/a"}}}],
        [],  # memorandum
    ]
    turn_idx = [0]

    def fake_urlopen(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "11434" in url, f"unexpected request to {url}"
        body = json.loads(req.data.decode("utf-8"))
        recorded_requests.append(body)
        idx = turn_idx[0]
        turn_idx[0] += 1
        tcs = turn_plan[idx] if idx < len(turn_plan) else []
        content = "REPORT: " + "Institutional Analysis " * 500 if not tcs else ""
        return _FakeResp({"message": {"role": "assistant", "content": content, "tool_calls": tcs},
                          "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20})

    def fake_dispatch(name, args, **kw):
        if name == "run_financial_model":
            return {"dcf_model": {"per_share_iv": args.get("price", 100.0)}}
        elif name == "search_web":
            return {"query": args.get("query"), "results": [], "n_results": 0, "cache_hit": False}
        elif name == "fetch_page":
            return {"url": args.get("url"), "chars": 100, "text": "sample text", "part": 1, "parts": 1, "cache_hit": False}
        return {"error": f"unknown tool {name}"}

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, max_model_calls=5, verbose=False)

    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    assert len(snap) == 7

    # 1. desk results 1-5 carry desk_budget "1 of 5 desk runs used" ... "5 of 5 desk runs used",
    # and only the 5th carries desk_closed = DESK_CLOSED_RUNS
    for i in range(5):
        c = snap[i]
        assert c["tool"] == "run_financial_model"
        assert c.get("desk_budget") == f"{i+1} of 5 desk runs used"
        if i < 4:
            assert "desk_closed" not in c
            assert "desk" not in c
        else:
            assert c.get("desk_closed") == at.DESK_CLOSED_RUNS.format(cap=5)
            assert "desk" not in c

    # 2. both research results carry desk as their first key, and it survives in the tool message sent to the model
    for i in (5, 6):
        c = snap[i]
        assert list(c.keys())[0] == "desk"
        assert c.get("desk") == at.DESK_CLOSED_LINE

    # Check that in the requests sent to Ollama, the tool message has desk as first key
    req_turn7 = recorded_requests[6]
    tool_msg_6 = [m for m in req_turn7["messages"] if m.get("role") == "tool"][-1]
    parsed_msg_6 = json.loads(tool_msg_6["content"])
    assert list(parsed_msg_6.keys())[0] == "desk"
    assert parsed_msg_6["desk"] == at.DESK_CLOSED_LINE

    req_turn8 = recorded_requests[7]
    tool_msg_7 = [m for m in req_turn8["messages"] if m.get("role") == "tool"][-1]
    parsed_msg_7 = json.loads(tool_msg_7["content"])
    assert list(parsed_msg_7.keys())[0] == "desk"
    assert parsed_msg_7["desk"] == at.DESK_CLOSED_LINE

    # 3. the request after closure offers no run_financial_model
    tools_offered_turn6 = [t["function"]["name"] for t in recorded_requests[5].get("tools", [])]
    assert "run_financial_model" not in tools_offered_turn6


def test_seven_rejected_desk_calls_close_desk(monkeypatch, tmp_path):
    turn_plan = [
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [{"function": {"name": "run_financial_model", "arguments": {"bad": True}}}],
        [],
    ]
    turn_idx = [0]

    def fake_urlopen(req, *a, **k):
        idx = turn_idx[0]
        turn_idx[0] += 1
        tcs = turn_plan[idx] if idx < len(turn_plan) else []
        content = "REPORT: " + "Institutional Analysis " * 500 if not tcs else ""
        return _FakeResp({"message": {"role": "assistant", "content": content, "tool_calls": tcs},
                          "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20})

    def fake_dispatch(name, args, **kw):
        return {"error": "parameter invalid", "validation_error": True}

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, max_model_calls=5, verbose=False)
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    assert len(snap) == 7
    assert meta["desk_validation_errors"] == 7

    # Call 7 gives DESK_CLOSED_REJECTED with n=7
    call7 = snap[6]
    assert call7.get("desk_budget") == "0 of 5 desk runs used"
    assert call7.get("desk_closed") == at.DESK_CLOSED_REJECTED.format(n=7)


def test_max_model_calls_zero_never_carries_desk_fields(monkeypatch, tmp_path):
    turn_plan = [
        [{"function": {"name": "search_web", "arguments": {"query": "catalysts"}}}],
        [{"function": {"name": "fetch_page", "arguments": {"url": "https://example.com/news"}}}],
        [],
    ]
    turn_idx = [0]

    def fake_urlopen(req, *a, **k):
        idx = turn_idx[0]
        turn_idx[0] += 1
        tcs = turn_plan[idx] if idx < len(turn_plan) else []
        content = "REPORT: " + "Discovery brief " * 500 + "```json:catalysts\n[]\n```" if not tcs else ""
        return _FakeResp({"message": {"role": "assistant", "content": content, "tool_calls": tcs},
                          "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20})

    def fake_dispatch(name, args, **kw):
        if name == "search_web":
            return {"query": args.get("query"), "results": [], "n_results": 0}
        return {"url": args.get("url"), "chars": 50, "text": "news text", "part": 1, "parts": 1}

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, max_model_calls=0, verbose=False)
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    assert len(snap) == 2
    for c in snap:
        assert "desk_budget" not in c
        assert "desk_closed" not in c
        assert "desk" not in c
