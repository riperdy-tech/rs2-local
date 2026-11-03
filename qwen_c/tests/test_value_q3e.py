"""CROSS_CHECK_Q3e on prompt v8: the levered reference (1) holds; the own-value text, the contract whys and the "within the record"
reading (2, 3, 5, 6) are gone with the free-text reasons (F_SPEC_valuation_menu §4); every failure of a key still reaches the repair
turn (4)."""
import re

from qwen_c.value import checks, desk, task
from qwen_c.tests import test_value_checks as OP


def test_Q3e1_levered_reference_terminal_ronic_gives_an_equity_return_of_r():
    b, bar, _ = OP.ctx_of()
    b = dict(b, delta=0.4, kd=0.06, tau=0.21)
    value, how = checks._neutral_op(b, bar, OP.R)
    assert value is not None
    ronic = float(re.search(r"terminal RONIC (\d+\.\d+)", how).group(1))
    assert abs(desk.equity_ronic(ronic, 0.4, 0.06, 0.21) - OP.R) < 1e-4
    unlevered = checks._neutral_op(dict(b, delta=0.0), bar, OP.R)[1]
    assert f"terminal RONIC {OP.R:.4f}" in unlevered


def test_Q3e4_repair_turn_shows_every_failure_of_a_key():
    b, bar, ids = OP.ctx_of()
    out = OP.clean()
    out["base"]["op_margin"]["y1"] = "last"
    out["base"]["terminal_g"] = "decline"
    errors = checks.check(out, ids, b, bar, OP.R, OP.ENDS)["errors"]
    text = task.compact_failures(errors)
    assert "- terminal_g: decline is not available" in text and len(text.splitlines()) == len(errors)
