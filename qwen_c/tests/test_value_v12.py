"""V12 (RR_Q7 C2) on prompt v8: a reason can no longer state what its input is not, because code writes every number and every
comparison (F_SPEC_valuation_menu §0, §4). What replaces the regex: the memo prints the option, the resolved number, the record-neutral
number and the direction, all computed by code."""
from qwen_c.value import checks, memo
from qwen_c.tests import test_value_checks as OP


def test_v12_and_its_regex_classes_are_gone():
    for name in ("_v12", "_stated_contradiction", "_subject_is_input", "_direction_contradiction", "_direction_one", "V12_INPUTS"):
        assert not hasattr(checks, name), name


def test_the_comparison_is_code_s_own():
    b, bar, ids = OP.ctx_of()
    out = OP.depart(OP.clean(), "long_run_op_margin", ("p25", 0), "competition", ["A1.s1"])
    res = checks.check(out, ids, b, bar, OP.R, OP.ENDS)
    assert res["directions"]["long_run_op_margin"] == "down" and res["numbers"]["long_run_op_margin"] == bar["p25"]
    text = memo.render({"ticker": "T", "T": "2026-03-01", "status": res["status"], "inputs": out, "checks": res, "values": res["values"],
                        "cost_of_equity": OP.R, "base": b, "stamps": b["stamps"]})
    assert f"- **long_run_op_margin**: p25 +0 pts, {bar['p25']:.4f} (record-neutral {bar['persist']:.4f}), down; driver competition" in text
