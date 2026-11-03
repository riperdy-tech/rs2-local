"""V12 (RR_Q7 C2): a reason's stated comparison against a printed number, or a record statistic it says the input is set at, must hold
for the input. The claims are the E3 findings (DVA, HRTG, SEZL, TASK) and their consistent controls."""
from qwen_c.value import checks
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin_q3c import op_ctx

S = checks._stated_contradiction
BAR = {"min": 0.05, "p25": 0.08, "median": 0.09, "p75": 0.1028, "max": 0.12, "last": 0.119}


def test_comparison_against_a_printed_number_is_checked():
    assert S("support a long-run return on new capital below the cost of equity of 0.0784.", [0.12])
    assert S("support a long-run return on new capital below the cost of equity of 0.0784.", [0.07]) is None
    assert S("Return stays above the cost of equity of 7.84%.", [0.07])


def test_and_continues_the_subject():
    claim = "The long-run return on equity of 0.12 is above the long-run growth anchor of 0.0375 and below the cost of equity of 0.0871."
    assert S(claim, [0.12])
    assert S(claim.replace("below", "above"), [0.12]) is None


def test_another_subject_is_skipped():
    assert S("convergence toward the anchor of 0.0375, which is below the cost of equity of 0.0871.", [0.12]) is None
    assert S("The fiscal 2025 margin of 11.9% is above the median of 9%.", [0.05]) is None
    assert S("A fade of 10 years is below the limit of 15.", [0.12]) is None          # not a rate


def test_negation_and_pairs():
    assert S("Growth is not above the anchor of 0.03.", [0.04, 0.05])
    assert S("Growth is above the anchor of 0.03.", [0.02, 0.04]) is None             # one of the pair holds


def test_set_at_a_record_statistic():
    assert S("The long-run operating margin is set at the p75 statistic from the filed record.", [0.10], BAR)
    assert S("The long-run operating margin is set at the p75 statistic from the filed record.", [0.1028], BAR) is None
    assert S("The long-run operating margin is set at the p75 statistic.", [0.10]) is None    # no record for this input


def test_check_refuses_the_reason_and_marks_the_input():
    b, bar, items = op_ctx()
    out = OP.clean()
    out["base"]["terminal_ronic"] = 0.12
    rz = next(x for x in out["reasons"] if x["input"] == "base.terminal_ronic")
    i = out["reasons"].index(rz)
    rz["claim"] = rz["claim"].rstrip(".") + "; the return on new capital stays below the cost of equity of 0.0784."
    res = checks.check(out, items, "T", set(), b, bar, OP.R, OP.ENDS)
    assert any(w.startswith("V12 ") for w in res["unsupported"].get("base.terminal_ronic", []))
    assert i in res["refused_reasons"] and res["status"] == "valuation_incomplete"
