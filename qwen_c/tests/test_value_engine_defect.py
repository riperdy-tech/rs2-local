"""Review 2026-11-03: a crash in the checks after the reply rules pass is an engine defect, never "reply_invalid" model output."""
import pytest

from qwen_c.value import checks
from qwen_c.tests import test_value_checks as OP


def test_a_crash_past_the_reply_rules_is_an_engine_defect():
    b, bar, ids = OP.ctx_of()
    broken = {k: v for k, v in bar.items() if k != "median"}
    with pytest.raises(AssertionError, match="engine defect in checks"):
        checks.check(OP.clean(), ids, b, broken, OP.R, OP.ENDS)


def test_malformed_model_content_is_still_reply_invalid():
    b, bar, ids = OP.ctx_of()
    assert checks.check({"base": "not a dict"}, ids, b, bar, OP.R, OP.ENDS)["status"] == "reply_invalid"
