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
