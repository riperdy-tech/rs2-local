"""CROSS_CHECK_Q3e: the levered reference (1), normalized's own value (2), scenario whys and every failure named (3, 4), "within the
record" for an input outside it (5), exact own-value forms (6)."""
import re

from qwen_c.value import checks, desk, task
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin_q3c import op_ctx


def test_Q3e1_levered_reference_terminal_ronic_gives_an_equity_return_of_r():
    b, bar, _ = op_ctx()
    b = dict(b, delta=0.4, kd=0.06, tau=0.21)
    value, how = checks._neutral_op(b, bar, OP.R)
    assert value is not None
    ronic = float(re.search(r"terminal RONIC (\d+\.\d+)", how).group(1))
    assert abs(desk.equity_ronic(ronic, 0.4, 0.06, 0.21) - OP.R) < 1e-4
    unlevered = checks._neutral_op(dict(b, delta=0.0), bar, OP.R)[1]
    assert f"terminal RONIC {OP.R:.4f}" in unlevered


def test_Q3e2_normalized_own_value_prints_its_year_and_points():
    out = OP.clean()
    out["base"]["normalized"].update(year=4, delta_pts=0.5)
    t = checks.input_value_text(out, ("base", "normalized"))
    assert "year 4" in t and "0.5 percentage points" in t and "50 basis points" in t and "50%" not in t


def test_Q3e3_scenario_line_carries_why_and_every_check_is_named():
    b, bar, items = op_ctx()
    out = OP.clean()
    out["reasons"] = [x for x in out["reasons"] if x["input"] != "bull.op_margin"] + [
        {"input": "bull.op_margin", "claim": "The bull margin rests on a 77% share of nothing.", "fact_ids": [next(iter(items))],
         "quotes": ["zzz not printed"], "numbers": []}]
    res = checks.check(out, items, "T", set(), b, bar, OP.R, OP.ENDS)
    line = res["unsupported"]["bull.op_margin"][0]
    assert line.startswith("no supported reason for the scenario's own input (contract: quote_not_found")
    assert "number_not_listed (77%): list it if a cited item prints it" in line


def test_Q3e4_repair_turn_shows_every_failure_of_an_input():
    text = task.compact_failures({"base.long_run_roe": ["no supported reason (contract: number_not_listed (0.115))",
                                                         "V3 unsupported_premium: ROE 0.1150 outside the filed record"]})
    assert "number_not_listed" in text and "V3 unsupported_premium" in text


def test_Q3e5_within_the_record_for_an_input_outside_it_is_a_contradiction():
    bar = {"min": 0.1172, "max": 0.1343, "median": 0.1242, "last": 0.1294}
    assert checks._direction_one("A long-run ROE of 0.115 is within the filed range from 0.1172 to 0.1343.", 0.115, bar)
    assert checks._direction_one("A long-run ROE of 0.12 is within the filed range.", 0.12, bar) is None


def test_Q3e6_own_value_forms_are_exact():
    out = OP.clean()
    out["base"]["long_run_op_margin"] = 0.125
    t = checks.input_value_text(out, ("base", "long_run_op_margin")).split()
    assert "12.5%" in t and "0.125" in t and "12%" not in t and "13%" not in t and "0.1" not in t
