import sys
import json
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at

def test_financial_model_tool_registered_in_tools_list():
    tool_names = [t["function"]["name"] for t in at.TOOLS]
    assert "run_financial_model" in tool_names
    
    # Check parameters
    fm_tool = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")
    params = fm_tool["function"]["parameters"]["properties"]
    assert "price" in params
    assert "scenarios" in params

def test_dispatch_financial_model_tool():
    args = {
        "price": 951.0,
        "scenarios": [
            {"name": "Base", "iv": 1100.0, "prob": 0.35},
            {"name": "Bull", "iv": 1450.0, "prob": 0.20},
            {"name": "Bear", "iv": 550.0, "prob": 0.45},
        ],
        "base_cf": 3.8,
        "shares_diluted": 0.274,
        "wacc": 0.085,
        "demonstrated_cagr_5y": 7.5,
    }
    snap = []
    res = at.dispatch_tool("run_financial_model", args, snap=snap)
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

