"""WO_Q2 (SPEC_m3q §2, §6 E1): qwen_c/value/desk.py against the D2 reference harness.

fixtures_value/d2_reference.json is written by stocks-workspace scratch/rev23/terminal_d2/gen_value_fixtures.py from reference_d2.py and the
simulator: the registered paths of rs2 1dcb3b2's test_d2_desk (vintages D&A; B, E, C and C2 on their cited state paths), RR_Q3's M1-M6
(pooled, default path) and the insurer on the financial route. The desk must reproduce the reference's value and every annual flow to
1e-9, and each case must pass or fail the registered +-3% truth bar exactly as registered.
"""
import json
import math
from pathlib import Path

import pytest

from qwen_c.value import desk

CASES = json.loads((Path(__file__).resolve().parent / "fixtures_value" / "d2_reference.json").read_text(encoding="utf-8"))
BY = {c["case"]: c for c in CASES}
TOL = 1e-9
A = BY["A_compounder|H0|vintages"]["input"]


def run(c):
    return desk.value_financial(c["input"]) if c["route"] == "financial" else desk.value_operating(c["input"])


def core(c, v):
    return v["equity_value"] if c["route"] == "financial" else v["pv_levels"] + v["pv_flows"] + v["tv_pv"]


@pytest.mark.parametrize("case", sorted(BY))
def test_parity_value_and_every_flow(case):
    c = BY[case]
    v = run(c)
    assert abs(core(c, v) / c["value"] - 1) < TOL
    flows = v["flows_all"] if c["route"] == "operating" else v["flows_all"][:5]
    assert len(flows) == len(c["flows_all"])
    for a, b in zip(flows, c["flows_all"]):
        assert abs(a - b) <= TOL * max(1.0, abs(b))


@pytest.mark.parametrize("case", sorted(BY))
def test_registered_truth_bar_passes_and_failures_exactly(case):
    # C and C2 on the default path (+7.37%, +4.53%) and M6 (R with the wedge, RR_Q3 §5) are registered failures and must stay failures
    c = BY[case]
    assert (abs(run(c)["equity_value"] / c["truth"] - 1) <= 0.03) == c["registered"]


def test_c_and_c2_default_errors_unchanged():
    err = lambda k: run(BY[k])["equity_value"] / BY[k]["truth"] - 1
    assert err("C_depleter|H0|vintages") == pytest.approx(0.0737, abs=5e-4)
    assert err("C2_depleter_levered|H0|vintages") == pytest.approx(0.0453, abs=5e-4)


def test_per_share_adds_excess_cash_and_divides():
    inp = dict(A, shares=2.0, excess_cash=0.5)
    v = desk.value_operating(inp)
    assert v["value_per_share"] == pytest.approx((v["equity_value"] + 0.5) / 2.0)


def test_zero_is_a_value_not_an_absence():
    inp = dict(A, p_ratio=0.0, rou_ratio=0.0, delta=0.0, excess_cash=0.0)
    assert desk.value_operating(inp)["equity_value"] > 0


@pytest.mark.parametrize("change,code", [
    ({"r": 0.02}, "rate_not_above_terminal_growth"),
    ({"ronic_T": 0.0}, "ronic_not_positive"),
    ({"shares": 0.0}, "shares_unavailable"),
    ({"delta": 1.0}, "input_invalid"),
    ({"F": 0}, "input_invalid"),
    ({"margin": [0.1] * 4}, "input_shape"),
])
def test_refusals_by_name(change, code):
    with pytest.raises(desk.DeskRefusal) as e:
        desk.value_operating(dict(A, **change))
    assert e.value.code == code


def test_missing_input_is_refused_never_defaulted():
    inp = dict(A)
    del inp["tau"]
    with pytest.raises(desk.DeskRefusal) as e:
        desk.value_operating(inp)
    assert e.value.code == "input_missing"


def test_state_path_extends_levels_and_drops_the_wedge():
    v = run(BY["B_newbuild|H25|vintages"])
    assert v["wedge_applied"] is False and v["levels_years"] == 30 and v["n_years"] == 30


def test_ronic_at_moves_on_the_inverse_and_handles_unlimited():
    assert desk.ronic_at(0.1, 0.2, 0.5) == pytest.approx(1 / (0.5 * 10 + 0.5 * 5))
    assert desk.ronic_at(0.1, math.inf, 1.0) == math.inf
    assert desk.ronic_at(0.1, math.inf, 0.5) == pytest.approx(0.2)


def test_shield_after_n_is_the_finite_remainder():
    inp = dict(A, amort_schedule=[1.0] * 5, amort_thereafter=12.0, tau=0.25)   # 12 left: years 6..17, N = 15
    v = desk.value_operating(inp)
    expect = sum(0.25 * 1.0 / (1 + inp["r"]) ** t for t in (16, 17))
    assert v["shield_after_n_pv"] == pytest.approx(expect)


def test_no_sustaining_charge_and_fade_convention_recorded():
    src = (Path(desk.__file__)).read_text(encoding="utf-8")
    assert "sustain" not in src.split('"""', 2)[2]
    assert desk.FADE_CONVENTION == "revenue"
