import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import capability_test as cap

def test_task_prompt_removes_manual_kelly_math_and_introduces_financial_desk():
    # Prompt must NOT order manual mental math derivation of Kelly in prose
    assert "Explicitly derive justified scenario probabilities p and q, payoff ratio b, full Kelly f*" not in cap.TASK
    # Prompt must reference the financial modeling desk / run_financial_model
    assert "run_financial_model" in cap.TASK or "Financial Modeling Desk" in cap.TASK
    assert "Lead Underwriter" in cap.TASK or "Portfolio Manager" in cap.TASK

def test_pack_contains_working_capital_float_notice(screener_data_stub):
    pack = cap.build_pack("GEV")
    assert "WORKING CAPITAL FLOAT" in pack or "Customer Advance" in pack
