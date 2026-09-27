import sys
import json
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at
import financial_model_tool as fmt

# S3 A+B (brief §3.3): "price" left the schema (the harness supplies it via desk_context).
def test_financial_model_tool_registered_in_tools_list():
    tool_names = [t["function"]["name"] for t in at.TOOLS]
    assert "run_financial_model" in tool_names

    # Check parameters
    fm_tool = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")
    params = fm_tool["function"]["parameters"]["properties"]
    assert "price" not in params
    assert "cash_flow_life" in params
    assert "scenarios" in params

# S3 A+B (brief §3.2, §3.3): price and demonstrated_cagr_5y (= revenue_cagr_5y_pct) come from
# desk_context now, not the call; cash_flow_life/cash_flow_life_reason are required call arguments.
def test_dispatch_financial_model_tool():
    args = {
        "scenarios": [
            {"name": "Base", "iv": 1100.0, "prob": 0.35},
            {"name": "Bull", "iv": 1450.0, "prob": 0.20},
            {"name": "Bear", "iv": 550.0, "prob": 0.45},
        ],
        "base_cf": 3.8,
        "shares_diluted": 0.274,
        "wacc": 0.085,
        "terminal_g": 0.025,
        "cash_flow_life": "perpetual",
        "cash_flow_life_reason": "test",
    }
    snap = []
    res = at.dispatch_tool("run_financial_model", args, snap=snap,
                           desk_context={"price": 951.0, "revenue_cagr_5y_pct": 7.5})
    assert "kelly_sizing" in res
    assert "reverse_dcf" in res
    assert "markdown_report" in res
    assert res["kelly_sizing"]["quarter_kelly_pct"] == 0.0
    assert len(snap) == 1
    assert snap[0]["tool"] == "run_financial_model"


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_dispatched_tool_call_snapshotted_before_execution_even_if_raised(monkeypatch, tmp_path):
    """P1.7: every dispatched call is appended and saved before execution.

    If tool dispatch raises mid-call, the call record must still be in the log on disk.
    """
    resp = {
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "search_web",
                        "arguments": {"query": "Flexsteel Q4 2026 earnings"}
                    }
                }
            ]
        },
        "done_reason": "stop",
        "eval_count": 10,
        "eval_duration": 100_000_000,
    }

    monkeypatch.setattr(at.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(resp))

    def fake_dispatch(*args, **kwargs):
        # Verify that BEFORE dispatch executes, the call is already in _research_snapshot.json on disk
        snap_file = tmp_path / "_research_snapshot.json"
        assert snap_file.exists(), "Snapshot file must exist on disk before tool executes"
        data = json.loads(snap_file.read_text(encoding="utf-8"))
        assert data["tool_calls"] == 1
        assert len(data["calls"]) == 1
        assert data["calls"][0]["tool"] == "search_web"
        assert data["calls"][0]["params"] == {"query": "Flexsteel Q4 2026 earnings"}
        raise RuntimeError("Simulated mid-call failure during tool execution")

    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    with pytest.raises(RuntimeError, match="Simulated mid-call failure"):
        at.chat_with_tools("fake-model", "test prompt", tmp_path, verbose=False)

    # After the raise, the snapshot must STILL exist on disk with the error recorded
    snap_file = tmp_path / "_research_snapshot.json"
    assert snap_file.exists()
    snapshot = json.loads(snap_file.read_text(encoding="utf-8"))
    assert snapshot["tool_calls"] == 1
    assert len(snapshot["calls"]) == 1
    assert snapshot["calls"][0]["tool"] == "search_web"
    assert "error" in snapshot["calls"][0]


def test_research_tools_returns_search_and_fetch_only():
    rtools = at.research_tools()
    assert len(rtools) == 2
    names = [t["function"]["name"] for t in rtools]
    assert names == ["search_web", "fetch_page"]
    assert "run_financial_model" not in names


def test_chat_with_tools_defaults_and_signature():
    import inspect
    sig = inspect.signature(at.chat_with_tools)
    assert sig.parameters["tools"].default is None
    assert sig.parameters["max_search_calls"].default == 25
    assert sig.parameters["max_model_calls"].default == 5


def test_chat_with_tools_honours_new_parameters(monkeypatch, tmp_path):
    """Test research-only tools, 14-call budget, 0 desk calls."""
    recorded_requests = []

    turn = 0
    def fake_urlopen(req, timeout=None):
        nonlocal turn
        body = json.loads(req.data.decode("utf-8"))
        recorded_requests.append(body)
        turn += 1
        if turn == 1:
            # Model calls search_web twice
            resp = {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "search_web", "arguments": {"query": f"AMD catalyst {i}"}}}
                        for i in range(14)
                    ]
                },
                "done_reason": "stop",
                "eval_count": 50,
                "eval_duration": 100_000_000,
            }
        else:
            # Final deliverable
            resp = {
                "message": {
                    "content": '```json:catalysts\n{"asof": "2026-09-24", "events": []}\n```',
                },
                "done_reason": "stop",
                "eval_count": 80,
                "eval_duration": 150_000_000,
            }
        return _FakeResponse(resp)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", lambda name, args, **kwargs: {"results": []})

    out_dir = tmp_path / "chat_run"
    report, thinking, meta = at.chat_with_tools(
        "test-model", "test prompt", out_dir,
        tools=at.research_tools(), max_search_calls=14, max_model_calls=0,
        verbose=False,
    )

    # First turn should have received only research tools
    first_req_tools = [t["function"]["name"] for t in recorded_requests[0]["tools"]]
    assert first_req_tools == ["search_web", "fetch_page"]
    assert "run_financial_model" not in first_req_tools

    # All 14 search calls executed, exhausting search budget (since max_search_calls=14, max_model_calls=0)
    # Next turn forces the final answer because all budgets are exhausted
    assert meta["tool_calls"] == 14
    assert "json:catalysts" in report


def test_chat_with_tools_zero_desk_calls_refuses_financial_model(monkeypatch, tmp_path):
    """When max_model_calls=0, run_financial_model is refused with budget exhausted."""
    turn = 0
    def fake_urlopen(req, timeout=None):
        nonlocal turn
        turn += 1
        if turn == 1:
            resp = {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "run_financial_model", "arguments": {"price": 100}}}
                    ]
                },
                "done_reason": "stop",
                "eval_count": 20,
                "eval_duration": 50_000_000,
            }
        else:
            resp = {
                "message": {
                    "content": "Final memorandum after desk refusal",
                },
                "done_reason": "stop",
                "eval_count": 20,
                "eval_duration": 50_000_000,
            }
        return _FakeResponse(resp)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    out_dir = tmp_path / "desk_run"

    # With max_model_calls=0, even if TOOLS has run_financial_model
    report, thinking, meta = at.chat_with_tools(
        "test-model", "test prompt", out_dir,
        tools=at.TOOLS, max_search_calls=25, max_model_calls=0,
        verbose=False,
    )
    # Snapshot should show error: financial model call budget exhausted (0)
    snap_file = out_dir / "_research_snapshot.json"
    assert snap_file.exists()
    snap = json.loads(snap_file.read_text(encoding="utf-8"))
    assert "budget exhausted (0)" in snap["calls"][0]["error"]


# S3 A+B (brief §3.3, §4.4): the required list is now cash_flow_life, cash_flow_life_reason,
# terminal_g, fade_years, sbc_treatment; shares_diluted is optional (the context default applies)
# and its description text changed.
def test_financial_model_tool_schema_and_validation_agree():
    """F4: run_financial_model schema required list matches desk validation, and a desk call
    missing each required field is refused with validation_error: True."""
    fm_tool = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")
    fn = fm_tool["function"]
    props = fn["parameters"]["properties"]
    required = fn["parameters"]["required"]

    expected_desc = (
        "Optional. The desk uses SECTION 2's count (DEFAULTS) when you leave it out. "
        "Pass it only for a different count, with shares_reason."
    )
    assert props["shares_diluted"]["description"] == expected_desc

    five_fields = ["cash_flow_life", "cash_flow_life_reason", "terminal_g", "fade_years", "sbc_treatment"]
    assert required == five_fields
    for field in five_fields:
        assert field in required

    base_params = {
        "base_cf": 10.0,
        "explicit_growth": [0.05],
        "wacc": 0.09,
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        "cash_flow_life": "perpetual",
        "cash_flow_life_reason": "test",
    }
    ctx = {"price": 100.0}
    for field in five_fields:
        p = dict(base_params)
        del p[field]
        res = fmt.execute_financial_model(p, context=ctx)
        assert res.get("validation_error") is True, f"Desk must refuse call missing {field}"
        assert any(field in m for m in res.get("missing", [])), f"{field} must be reported in missing list"

    # shares_diluted is no longer required: with no scenario/top-level count and no context
    # default, the call is refused with shares_diluted among the missing inputs (V6, §3.2).
    p = dict(base_params)
    del p["shares_diluted"]
    res = fmt.execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any("shares_diluted" in m for m in res.get("missing", []))


