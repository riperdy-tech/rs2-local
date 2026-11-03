"""Review 2026-11-03: a crash in the checks after the shape rules pass is an engine defect, never "invalid" model output."""
import pytest

from qwen_c.value import checks
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin_q3c import op_ctx


def test_a_crash_past_the_shape_rules_is_an_engine_defect():
    b, bar, items = op_ctx()
    broken = {k: v for k, v in bar.items() if k != "median"}
    with pytest.raises(AssertionError, match="engine defect in checks"):
        checks.check(OP.clean(), items, "T", set(), b, broken, OP.R, OP.ENDS)


def test_malformed_model_content_is_still_invalid():
    b, bar, items = op_ctx()
    assert checks.check({"base": "not a dict"}, items, "T", set(), b, bar, OP.R, OP.ENDS)["status"] == "invalid"
