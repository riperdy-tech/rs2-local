"""tests/test_years35_cap.py — Pack Revision 13 (F5: Base years 3-5 desk cap).

Tests cover:
- Desk tests 1-16 (financial_model_tool.py)
- Plumbing tests 17-19 (analyst_tools.py, consensus_valuation.py)
- Harness tests 20-22 (consensus_valuation.py)
"""
import copy
import json
import math
import re
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at
import consensus_valuation as cv
import financial_model_tool as fmt
from financial_model_tool import unbundled_dcf, execute_financial_model, format_model_results_markdown


# =============================================================================
# Desk Tests 1-16
# =============================================================================
# S3 A+B (brief §3.2, §3.3): price moves from params into context; cash_flow_life and its reason
# are required. None of these tests' context carries owner_earnings_default_b/coe_anchor/
# terminal_g_default/consensus_implied_value/levels/shares_default_b (adding one would trip a
# reason check the years35_cap mechanism under test has nothing to do with, forbidden by the
# order), so base_cf_reason (R2, which fires whenever owner_earnings_default_b is unavailable) and
# the price-direction reasons (R13/R14, belt-and-suspenders since price is in context) are given
# directly as call arguments instead.
_CFL = {"cash_flow_life": "perpetual", "cash_flow_life_reason": "test"}
_NEUTRAL_REASONS = {
    "base_cf_reason": "test", "bull_below_price_reason": "test", "bear_above_price_reason": "test",
}


def _three(base):
    """Revision 16: a call that sends scenarios needs exactly one Base, one Bull and one Bear. The cases
    below that test a single Base use this to complete the set: the Bull and Bear are the Base's own inputs
    at 1.2x and 0.5x the cash flow (the value is linear in it, so Bear <= Base <= Bull) and are not under
    test. Probabilities 0.5 / 0.25 / 0.25."""
    return [dict(base, prob=0.5),
            dict(base, name="Bull", prob=0.25, base_cf=base["base_cf"] * 1.2),
            dict(base, name="Bear", prob=0.25, base_cf=base["base_cf"] * 0.5)]


def test_01_base_capped_and_kelly_uses_applied():
    """1. Base [0.10,0.08,0.06,0.05,0.045], cap 0.04, no reason:
    - Base applied years 3-5 are [0.04,0.04,0.04], and the IV equals unbundled_dcf on [0.10,0.08,0.04,0.04,0.04];
    - Bull and Bear are identical to a call without context;
    - years35_cap holds the requested and applied values;
    - Kelly uses the applied Base.
    """
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": [
            {"name": "Base", "prob": 0.5, "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "wacc": 0.08},
            {"name": "Bull", "prob": 0.3, "base_cf": 10.0, "growth_rates": [0.12, 0.10, 0.08, 0.07, 0.06], "wacc": 0.08},
            {"name": "Bear", "prob": 0.2, "base_cf": 10.0, "growth_rates": [0.02, 0.00, -0.02, -0.03, -0.03], "wacc": 0.09},
        ],
    }
    res_no_ctx = execute_financial_model(copy.deepcopy(params), context={"price": 100.0})
    res_capped = execute_financial_model(copy.deepcopy(params), context={"price": 100.0, "years35_cap": 0.04})

    expected_base_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.10, 0.08, 0.04, 0.04, 0.04],
        wacc=0.08,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=5,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    expected_base_iv = expected_base_dcf["per_share_iv"]

    scs_capped = {s["name"]: s for s in res_capped["scenario_dcfs"]}
    scs_no_ctx = {s["name"]: s for s in res_no_ctx["scenario_dcfs"]}

    assert scs_capped["Base"]["dcf"]["per_share_iv"] == expected_base_iv
    assert scs_capped["Bull"]["dcf"]["per_share_iv"] == scs_no_ctx["Bull"]["dcf"]["per_share_iv"]
    assert scs_capped["Bear"]["dcf"]["per_share_iv"] == scs_no_ctx["Bear"]["dcf"]["per_share_iv"]

    yc = res_capped.get("years35_cap")
    assert yc is not None
    assert yc["cap"] == 0.04
    assert yc["reason"] is None
    assert len(yc["dcfs"]) == 1

    d0 = yc["dcfs"][0]
    assert d0["name"] == "Base"
    assert d0["requested_years35"] == [0.06, 0.05, 0.045]
    assert d0["applied_years35"] == [0.04, 0.04, 0.04]
    assert d0["requested_per_share_iv"] == scs_no_ctx["Base"]["dcf"]["per_share_iv"]
    assert d0["applied_per_share_iv"] == expected_base_iv
    assert d0["applied_fade_years"] == 5

    # Kelly uses the applied Base
    expected_outcomes = [
        {"name": "Base", "iv": expected_base_iv, "prob": 0.5},
        {"name": "Bull", "iv": scs_no_ctx["Bull"]["dcf"]["per_share_iv"], "prob": 0.3},
        {"name": "Bear", "iv": scs_no_ctx["Bear"]["dcf"]["per_share_iv"], "prob": 0.2},
    ]
    expected_kelly = fmt.continuous_multi_outcome_kelly(price=100.0, outcomes=expected_outcomes)
    assert res_capped["kelly_sizing"]["expected_iv"] == expected_kelly["expected_iv"]
    assert res_capped["kelly_sizing"]["quarter_kelly_pct"] == expected_kelly["quarter_kelly_pct"]
    assert res_capped["kelly_sizing"]["expected_iv"] != res_no_ctx["kelly_sizing"]["expected_iv"]


def test_02_reason_keeps_requested_path():
    """2. The same call with reason 'Company guides +6% through 2028 (8-K 2026-08-06)'.
    The result is identical to the no-context call except for years35_cap with reason and kept.
    """
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        "guidance_deviation_reason": "Company guides +6% through 2028 (8-K 2026-08-06)",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": [
            {"name": "Base", "prob": 0.5, "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "wacc": 0.08},
            {"name": "Bull", "prob": 0.3, "base_cf": 10.0, "growth_rates": [0.12, 0.10, 0.08, 0.07, 0.06], "wacc": 0.08},
            {"name": "Bear", "prob": 0.2, "base_cf": 10.0, "growth_rates": [0.02, 0.00, -0.02, -0.03, -0.03], "wacc": 0.09},
        ],
    }
    params_no_reason = copy.deepcopy(params)
    del params_no_reason["guidance_deviation_reason"]
    res_no_ctx = execute_financial_model(params_no_reason, context={"price": 100.0})
    res_with_reason = execute_financial_model(copy.deepcopy(params), context={"price": 100.0, "years35_cap": 0.04})

    assert res_with_reason["years35_cap"] == {
        "cap": 0.04,
        "reason": "Company guides +6% through 2028 (8-K 2026-08-06)",
        "kept": ["Base"],
    }

    # Everything else is identical
    res_comp = {k: v for k, v in res_with_reason.items() if k != "years35_cap"}
    assert res_comp == res_no_ctx


def test_03_empty_reason_variants():
    """3. A reason of 'null', 'None' or '  ' counts as empty, so the Base is capped."""
    for empty_val in ("null", "None", "  ", "none", "NULL", ""):
        params = {
            "valuation_frame": "equity",
            "rate_type": "cost_of_equity",
            "shares_diluted": 1.0,
            "terminal_g": 0.025,
            "fade_years": 5,
            "sbc_treatment": "deducted_in_cf",
            "guidance_deviation_reason": empty_val,
            **_CFL, **_NEUTRAL_REASONS,
            "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "wacc": 0.08}),
        }
        res = execute_financial_model(params, context={"price": 100.0, "years35_cap": 0.04})
        assert "years35_cap" in res
        assert res["years35_cap"]["reason"] is None
        assert "dcfs" in res["years35_cap"]
        assert len(res["years35_cap"]["dcfs"]) == 1


def test_04_identical_to_no_context_and_no_years35_cap_key():
    """4. Three calls give a result identical to the no-context call (compare the whole dict) and have no years35_cap key:
    - Base years 3-5 exactly at the cap;
    - a call with no cap in its context;
    - a call with context {'years35_cap': None}.
    The price is in every context (a call without one is refused, and refusals would compare equal to
    each other), so all three are accepted runs.
    """
    params_at_cap = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.04, 0.04, 0.04], "wacc": 0.08}),
    }
    res_at_cap = execute_financial_model(copy.deepcopy(params_at_cap), context={"price": 100.0, "years35_cap": 0.04})
    res_no_ctx = execute_financial_model(copy.deepcopy(params_at_cap), context={"price": 100.0})
    res_none_cap = execute_financial_model(copy.deepcopy(params_at_cap), context={"price": 100.0, "years35_cap": None})

    for res in (res_at_cap, res_no_ctx, res_none_cap):
        assert "error" not in res, res.get("error")
        assert len(res["scenario_dcfs"]) == 3
    assert "years35_cap" not in res_at_cap
    assert "years35_cap" not in res_no_ctx
    assert "years35_cap" not in res_none_cap
    assert res_at_cap == res_no_ctx
    assert res_none_cap == res_no_ctx


def test_05_bull_and_bear_above_cap_unchanged():
    """5. Bull above the cap and Bear above the cap are unchanged."""
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": [
            {"name": "Base", "prob": 0.5, "base_cf": 10.0, "growth_rates": [0.03, 0.03, 0.03, 0.03, 0.03], "wacc": 0.08},
            {"name": "Bull", "prob": 0.3, "base_cf": 10.0, "growth_rates": [0.10, 0.09, 0.08, 0.07, 0.06], "wacc": 0.08},
            {"name": "Bear", "prob": 0.2, "base_cf": 10.0, "growth_rates": [0.06, 0.05, 0.05, 0.05, 0.05], "wacc": 0.09},
        ],
    }
    res_no_ctx = execute_financial_model(copy.deepcopy(params), context={"price": 100.0})
    res_capped = execute_financial_model(copy.deepcopy(params), context={"price": 100.0, "years35_cap": 0.04})

    for res in (res_no_ctx, res_capped):
        assert "error" not in res, res.get("error")
        assert len(res["scenario_dcfs"]) == 3
    assert "years35_cap" not in res_capped
    assert res_capped == res_no_ctx


def test_06_top_level_single_dcf_capped():
    """6. A top-level single DCF above the cap with no reason is capped the same way; its name is 'top-level'."""
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        "base_cf": 10.0,
        "explicit_growth": [0.10, 0.08, 0.06, 0.05, 0.045],
        "wacc": 0.08,
        **_CFL, "base_cf_reason": "test",
    }
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": 0.04})
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.10, 0.08, 0.04, 0.04, 0.04],
        wacc=0.08,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=5,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert res["dcf_model"]["per_share_iv"] == expected_dcf["per_share_iv"]
    assert res["years35_cap"]["dcfs"][0]["name"] == "top-level"
    assert res["years35_cap"]["dcfs"][0]["applied_years35"] == [0.04, 0.04, 0.04]


def test_07_scenario_named_central_capped():
    """7. A scenario named 'Central' is treated as Base and capped."""
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Central", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "wacc": 0.08}),
    }
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": 0.04})
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.10, 0.08, 0.04, 0.04, 0.04],
        wacc=0.08,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=5,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert res["scenario_dcfs"][0]["dcf"]["per_share_iv"] == expected_dcf["per_share_iv"]
    assert res["years35_cap"]["dcfs"][0]["name"] == "Central"


def test_08_four_explicit_rates_fade_years_5():
    """8. Four explicit rates with fade_years 5, where the applied year 5 (a fade year) is above the cap:
    - the result equals unbundled_dcf on five explicit rates with fade_years 4;
    - the number of discrete years is unchanged.
    """
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.03,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05], "wacc": 0.08}),
    }
    # Applied year 5: 0.05 + (0.03 - 0.05) * (1/5) = 0.046.
    # Cap 0.04 => applied is min(0.046, 0.04) = 0.04.
    # explicit_growth becomes [0.10, 0.08, 0.04, 0.04, 0.04] (from app[:2] + [min(g, cap) for g in app[2:]]).
    # fade_years becomes 5 - (5 - 4) = 4.
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": 0.04})
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.10, 0.08, 0.04, 0.04, 0.04],
        wacc=0.08,
        terminal_g=0.03,
        shares_diluted=1.0,
        fade_years=4,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert res["scenario_dcfs"][0]["dcf"]["per_share_iv"] == expected_dcf["per_share_iv"]
    # Total discrete years is unchanged: 5 explicit + 4 fade = 9 (was 4 explicit + 5 fade = 9)
    assert len(res["scenario_dcfs"][0]["dcf"]["projected_cfs"]) == len(expected_dcf["projected_cfs"]) == 9


def test_09_two_explicit_rates_fade_years_8():
    """9. Two explicit rates with fade_years 8, so years 3-5 are fade years.
    The result equals unbundled_dcf on five explicit rates (years 3-5 = min(fade value, cap)) with fade_years 5.
    """
    r1, r2 = 0.10, 0.08
    tg = 0.03
    cap = 0.04
    fade_orig = 8
    # Fade steps 1, 2, 3:
    y3 = r2 + (tg - r2) * (1 / fade_orig)
    y4 = r2 + (tg - r2) * (2 / fade_orig)
    y5 = r2 + (tg - r2) * (3 / fade_orig)
    expected_rates = [r1, r2, min(y3, cap), min(y4, cap), min(y5, cap)]
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=expected_rates,
        wacc=0.08,
        terminal_g=tg,
        shares_diluted=1.0,
        fade_years=5,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )

    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": tg,
        "fade_years": fade_orig,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [r1, r2], "wacc": 0.08}),
    }
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": cap})
    assert res["scenario_dcfs"][0]["dcf"]["per_share_iv"] == expected_dcf["per_share_iv"]
    assert res["scenario_dcfs"][0]["dcf"]["fade_years"] == 5


def test_10_two_explicit_rates_fade_years_1_terminal_above_cap():
    """10. Two explicit rates with fade_years 1 and terminal_g 0.03 above a 0.02 cap, so years 3-5 lie in the fade's end and
    the terminal. The result equals unbundled_dcf on [r1, r2, 0.02, 0.02, 0.02] with fade_years 0.
    """
    r1, r2 = 0.10, 0.08
    tg = 0.03
    cap = 0.02
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[r1, r2, 0.02, 0.02, 0.02],
        wacc=0.08,
        terminal_g=tg,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )

    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": tg,
        "fade_years": 1,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [r1, r2], "wacc": 0.08}),
    }
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": cap})
    assert res["scenario_dcfs"][0]["dcf"]["per_share_iv"] == expected_dcf["per_share_iv"]
    assert res["scenario_dcfs"][0]["dcf"]["fade_years"] == 0


def test_11_finite_life_years_4():
    """11. finite_life_years 4 with years 3-4 above the cap: only years 3-4 are capped, and the finite life is kept."""
    # S3 A+B (brief §3.4 V3): a top-level finite_life_years is now refused; the finite life moves
    # into cash_flow_life, which applies to every scenario (here there is only Base).
    cap = 0.04
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        "cash_flow_life": 4,
        "cash_flow_life_reason": "test",
        **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05], "wacc": 0.08}),
    }
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": cap})
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.10, 0.08, 0.04, 0.04],
        wacc=0.08,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=res["scenario_dcfs"][0]["dcf"]["fade_years"],
        finite_life_years=4,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert res["scenario_dcfs"][0]["dcf"]["per_share_iv"] == expected_dcf["per_share_iv"]
    assert res["years35_cap"]["dcfs"][0]["applied_years35"] == [0.04, 0.04]


def test_12_negative_cap():
    """12. A negative cap (-0.05) caps years 3-5 at -0.05."""
    cap = -0.05
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.02,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.05, 0.02, -0.01, -0.02, -0.03], "wacc": 0.08}),
    }
    res = execute_financial_model(params, context={"price": 100.0, "years35_cap": cap})
    expected_dcf = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.05, 0.02, -0.05, -0.05, -0.05],
        wacc=0.08,
        terminal_g=0.02,
        shares_diluted=1.0,
        fade_years=5,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert res["scenario_dcfs"][0]["dcf"]["per_share_iv"] == expected_dcf["per_share_iv"]
    assert res["years35_cap"]["dcfs"][0]["applied_years35"] == [-0.05, -0.05, -0.05]


def test_13_params_years35_cap_ignored():
    """13. params['years35_cap'] = 0.99 with no cap in the context is ignored. The same holds for a value
    that would bite (0.04 caps this Base's 6%, 5% and 4.5%): the accepted result is the one without the
    parameter, so only the context's cap counts. The price is in the context (a call without one is
    refused, and a refusal never reads the parameter)."""
    params = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "wacc": 0.08}),
    }
    res_plain = execute_financial_model(copy.deepcopy(params), context={"price": 100.0})
    assert "error" not in res_plain, res_plain.get("error")
    for param_cap in (0.99, 0.04):
        res = execute_financial_model(dict(copy.deepcopy(params), years35_cap=param_cap), context={"price": 100.0})
        assert "error" not in res, res.get("error")
        assert "years35_cap" not in res
        assert res == res_plain


def test_14_recorded_regressions():
    """14. Recorded regressions, using the minimal params from the brief:
    - with {'years35_cap': 0.009}, the MO Base is 82.74 (it was 88.84);
    - with {'years35_cap': 0.039}, the LAMR Base is 161.62 (it was 168.45);
    - Bull and Bear are unchanged: MO 96.39 and 55.61, LAMR 192.98 and 93.3.
    """
    mo_params = {
        "valuation_frame": "equity", "rate_type": "cost_of_equity",
        "shares_diluted": 1.6697, "terminal_g": 0.025, "fade_years": 5, "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": [
            {"name": "Base", "prob": 0.5, "base_cf": 6.997, "growth_rates": [0.047, 0.033, 0.03, 0.028, 0.025], "wacc": 0.0751},
            {"name": "Bull", "prob": 0.2, "base_cf": 6.997, "growth_rates": [0.047, 0.033, 0.05, 0.05, 0.045], "wacc": 0.0751},
            {"name": "Bear", "prob": 0.3, "base_cf": 6.997, "growth_rates": [0.047, 0.033, -0.02, -0.03, -0.03], "wacc": 0.0901},
        ],
    }
    # revision 17: the recorded values are the unfunded arithmetic; unlimited returns at both ends of the long run reproduce it
    unfunded = {"terminal_ronic": math.inf, "long_run": {"r_tc": math.inf}}
    res_mo = execute_financial_model(mo_params, context=dict({"price": 68.82, "years35_cap": 0.009}, **unfunded))
    scs_mo = {s["name"]: s["dcf"]["per_share_iv"] for s in res_mo["scenario_dcfs"]}
    assert scs_mo["Base"] == 82.74
    assert scs_mo["Bull"] == 96.39
    assert scs_mo["Bear"] == 55.61

    lamr_params = {
        "valuation_frame": "equity", "rate_type": "cost_of_equity",
        "shares_diluted": 0.101549684, "terminal_g": 0.0375, "fade_years": 5, "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": [
            {"name": "Base", "prob": 0.5, "base_cf": 0.694, "growth_rates": [0.07, 0.08, 0.06, 0.05, 0.045], "wacc": 0.0848},
            {"name": "Bull", "prob": 0.3, "base_cf": 0.694, "growth_rates": [0.12, 0.1, 0.085, 0.07, 0.06], "wacc": 0.0848},
            {"name": "Bear", "prob": 0.2, "base_cf": 0.694, "growth_rates": [0.01, -0.04, -0.02, 0.01, 0.025], "wacc": 0.0998},
        ],
    }
    res_lamr = execute_financial_model(lamr_params, context=dict({"price": 143.98, "years35_cap": 0.039}, **unfunded))
    scs_lamr = {s["name"]: s["dcf"]["per_share_iv"] for s in res_lamr["scenario_dcfs"]}
    assert scs_lamr["Base"] == 161.62
    assert scs_lamr["Bull"] == 192.98
    assert scs_lamr["Bear"] == 93.3


def test_15_monotone_and_continuous():
    """15. Monotone and continuous. For requested years 3-5 of cap-0.001, cap, cap+0.0001, cap+0.001 and cap+0.05:
    - the applied Base IV never falls as the request rises;
    - it is equal for every request at or above the cap.
    """
    cap = 0.04
    requests = [cap - 0.001, cap, cap + 0.0001, cap + 0.001, cap + 0.05]
    ivs = []
    for r in requests:
        params = {
            "valuation_frame": "equity",
            "rate_type": "cost_of_equity",
            "shares_diluted": 1.0,
            "terminal_g": 0.025,
            "fade_years": 5,
            "sbc_treatment": "deducted_in_cf",
            **_CFL, **_NEUTRAL_REASONS,
            "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, r, r, r], "wacc": 0.08}),
        }
        res = execute_financial_model(params, context={"price": 100.0, "years35_cap": cap})
        ivs.append(res["scenario_dcfs"][0]["dcf"]["per_share_iv"])

    # Never falls
    for i in range(len(ivs) - 1):
        assert ivs[i] <= ivs[i + 1]

    # Equal for every request at or above the cap
    # requests[1:] are cap, cap+0.0001, cap+0.001, cap+0.05
    for iv in ivs[2:]:
        assert iv == ivs[1]


def test_16_markdown_capped_and_kept():
    """16. Markdown: the capped message and the kept message both appear, with their numbers."""
    cap = 0.04
    params_capped = {
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "wacc": 0.08}),
    }
    res_capped = execute_financial_model(copy.deepcopy(params_capped), context={"price": 100.0, "years35_cap": cap})
    md_capped = format_model_results_markdown(res_capped)
    assert "**Base years 3-5 held at next-FY consensus revenue growth (+4.0%, DATA 8):**" in md_capped
    assert "no guidance_deviation_reason was given, so the desk valued Base on years 3-5 +4.0% / +4.0% / +4.0% instead of your +6.0% / +5.0% / +4.5%:" in md_capped

    params_kept = copy.deepcopy(params_capped)
    params_kept["guidance_deviation_reason"] = "Company guides +6% through 2028 (8-K 2026-08-06)"
    res_kept = execute_financial_model(params_kept, context={"price": 100.0, "years35_cap": cap})
    md_kept = format_model_results_markdown(res_kept)
    assert "**Base years 3-5 above next-FY consensus revenue growth (+4.0%, DATA 8), kept on your guidance_deviation_reason:**" in md_kept
    assert '"Company guides +6% through 2028 (8-K 2026-08-06)"' in md_kept


def test_16b_markdown_fade_note_survives_serialization():
    """Review fix: the record states the requested and applied fade_years as keys, so the '; fade_years N' note is
    printed when the fade changed, also from a result read back from JSON, and never when it did not."""
    params = {
        "valuation_frame": "equity", "rate_type": "cost_of_equity", "shares_diluted": 1.0,
        "terminal_g": 0.025, "fade_years": 5, "sbc_treatment": "deducted_in_cf",
        **_CFL, **_NEUTRAL_REASONS,
        "scenarios": _three({"name": "Base", "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.06, 0.05], "wacc": 0.08}),
    }
    res = execute_financial_model(copy.deepcopy(params), context={"price": 100.0, "years35_cap": 0.04})
    rec = res["years35_cap"]["dcfs"][0]
    assert type(rec) is dict
    assert (rec["requested_fade_years"], rec["applied_fade_years"]) == (5, 4)
    assert "+4.0% / +4.0% / +4.0%; fade_years 4 instead of your" in format_model_results_markdown(res)
    assert "; fade_years 4 instead of your" in format_model_results_markdown(json.loads(json.dumps(res)))

    five = copy.deepcopy(params)
    five["scenarios"][0]["growth_rates"] = [0.10, 0.08, 0.06, 0.05, 0.045]
    res5 = execute_financial_model(five, context={"price": 100.0, "years35_cap": 0.04})
    assert (res5["years35_cap"]["dcfs"][0]["requested_fade_years"], res5["years35_cap"]["dcfs"][0]["applied_fade_years"]) == (5, 5)
    assert "; fade_years" not in format_model_results_markdown(res5)


# =============================================================================
# Plumbing Tests 17-19
# =============================================================================

def test_17_plumbing_dispatch_and_chat_with_tools(monkeypatch, tmp_path):
    """17. dispatch_tool(..., desk_context=ctx) reaches execute_financial_model with context=ctx (monkeypatch).
    chat_with_tools(desk_context=ctx) passes it on for a run_financial_model call; follow the fake-model pattern in
    test_analyst_tools_integration.py.
    """
    seen_context = {}
    orig_execute = fmt.execute_financial_model

    def fake_execute(params, context=None):
        seen_context["ctx"] = context
        return orig_execute(params, context=context)

    monkeypatch.setattr(fmt, "execute_financial_model", fake_execute)

    test_ctx = {"years35_cap": 0.042}
    sample_params = {
        "price": 100.0,
        "valuation_frame": "equity",
        "rate_type": "cost_of_equity",
        "shares_diluted": 1.0,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        "scenarios": [
            {"name": "Base", "prob": 1.0, "base_cf": 10.0, "growth_rates": [0.10, 0.08, 0.04, 0.04, 0.04], "wacc": 0.08},
        ],
    }
    at.dispatch_tool("run_financial_model", sample_params, desk_context=test_ctx)
    assert seen_context["ctx"] == test_ctx

    # chat_with_tools passing it on
    resp_tool_call = {
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "run_financial_model",
                        "arguments": {"price": 100.0}
                    }
                }
            ]
        },
        "done_reason": "stop",
        "eval_count": 10,
        "eval_duration": 100_000_000,
    }
    resp_done = {
        "message": {
            "content": "SECTION 0. EXECUTIVE VERDICT\n" + ("x" * 5500),
            "tool_calls": []
        },
        "done_reason": "stop",
        "eval_count": 10,
        "eval_duration": 100_000_000,
    }

    class _FakeResponse:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode()
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    call_count = [0]
    def fake_urlopen(*a, **k):
        call_count[0] += 1
        if call_count[0] == 1:
            return _FakeResponse(resp_tool_call)
        return _FakeResponse(resp_done)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    captured_dispatch_ctx = {}

    def fake_dispatch(name, args, **kwargs):
        captured_dispatch_ctx["ctx"] = kwargs.get("desk_context")
        return {"status": "search_quota_met", "message": "done"}

    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)

    at.chat_with_tools("fake-model", "test prompt", tmp_path, verbose=False, desk_context=test_ctx)
    assert captured_dispatch_ctx["ctx"] == test_ctx


# S3 A+B (brief §3.2, §3.7 "Category G"): desk_context is now the full dict of §3.2 (price, the
# share default, the anchors, the base-rate table, the reverse-DCF inputs, and shares_warning),
# not just {"years35_cap": ...}.
def test_18_plumbing_consensus_valuation_passes_desk_context(monkeypatch, tmp_path):
    """18. consensus_valuation passes the full §3.2 desk_context at both chat_with_tools calls,
    with years35_cap set to next_fy_revenue_growth(pack) and price to the harness price. Monkeypatch
    chat_with_tools and capture the keyword argument, following the harness tests' pattern.
    """
    captured_calls = []

    def fake_chat(model, content, out_dir, **kwargs):
        captured_calls.append(kwargs.get("desk_context"))
        # First call return empty report to trigger retry, second call return deliverable memo
        if len(captured_calls) == 1:
            return "", "thinking", {"done_reason": "stop", "generated_tokens": 10, "eval_rate": 10.0, "eval_duration_s": 1.0}
        memo = (
            "SECTION 0. EXECUTIVE VERDICT\n"
            + "\n".join(f"  detail line {n} of the institutional memorandum." for n in range(400))
            + "\nSECTION 12. MACHINE CONTRACT\n"
            "```json:underwriting\n"
            '{"base_iv": 120.0, "bull_iv": 140.0, "bear_iv": 100.0, "verdict_label": "undervalued", '
            '"base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2, '
            '"conviction_score": 10, "business_quality_moat": 3, "kelly_fraction_pct": 2.0, '
            '"base_cf_used": 1.0, "base_cf_basis": "other", "stage1_growth_path": [0.1, 0.08, 0.04, 0.04, 0.04]}\n'
            "```\n"
        )
        return memo, "thinking", {"done_reason": "stop", "generated_tokens": 100, "eval_rate": 10.0, "eval_duration_s": 1.0}

    monkeypatch.setattr(at, "chat_with_tools", fake_chat)
    try:
        import analyst_tools as root_at
        monkeypatch.setattr(root_at, "chat_with_tools", fake_chat)
    except ImportError:
        pass

    sample_pack = (
        "## SECTION 8: EXPECTATIONS & CONSENSUS RECONCILIATION\n"
        "| Period | Revenue Avg | Low | High | Analysts | Growth |\n"
        "| next FY | $10.0B | $9.5B | $10.5B | 10 | +3.9% |\n"
        "- CONSENSUS-IMPLIED VALUE: $120.00\n"
        "- Shares outstanding: 1,000,000,000\n"
    )
    expected_cap = cv.next_fy_revenue_growth(sample_pack)
    assert expected_cap == pytest.approx(0.039, 1e-4)

    pack_file = tmp_path / "pack.md"
    pack_file.write_text(sample_pack, encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "TEST", "--price", "100.0", "--samples", "1",
        "--pack-file", str(pack_file), "--out-dir", str(out_dir), "--tools"
    ])

    cv.main()

    assert len(captured_calls) == 2
    expected_keys = {
        "price", "shares_default_b", "coe_anchor", "terminal_g_default", "terminal_g_anchor",
        "base_rate_table", "revenue_cagr_5y_pct", "net_debt_default_b", "interest_expense_latest_b",
        "owner_earnings_default_b", "base_window", "consensus_implied_value", "levels",
        "years35_cap", "shares_warning",
        # revision 17 (brief B 4): the through-cycle facts the desk values with
        "terminal_ronic", "long_run", "working_capital", "cash_basis_b",
        # revision 17 (brief F6): the fiscal-year base the reference grows from
        "reference_base_b",
        # revision 18 (brief 1.7, 1.5): the excess cash the desk adds at face, and the reference's status
        "excess_cash", "reference_status",
        # revision 19 (AT10 fix item 3): the bound the desk holds an excess_cash to
        "base_year_cash_and_investments_b",
    }
    for ctx in captured_calls:
        assert set(ctx.keys()) == expected_keys
        assert ctx["price"] == 100.0
        assert ctx["years35_cap"] == pytest.approx(expected_cap, 1e-4)
    # Both calls of the same run share the identical desk_context (built once per run, §3.2).
    assert captured_calls[0] == captured_calls[1]


def test_19_desk_summary_and_compact_tool_note():
    """19. _desk_summary carries years35_cap, and the compact note carries years35_capped."""
    res = {
        "price": 100.0,
        "scenario_dcfs": [
            {"name": "Base", "dcf": {"per_share_iv": 82.74}},
        ],
        "years35_cap": {
            "cap": 0.04,
            "reason": None,
            "dcfs": [
                {
                    "name": "Base",
                    "requested_years35": [0.06, 0.05, 0.045],
                    "applied_years35": [0.04, 0.04, 0.04],
                    "requested_per_share_iv": 88.84,
                    "applied_per_share_iv": 82.74,
                    "applied_fade_years": 5,
                }
            ],
        },
    }
    summary = at._desk_summary({}, res)
    assert "years35_cap" in summary
    assert summary["years35_cap"] == res["years35_cap"]

    note = at.compact_tool_note("run_financial_model", {}, res, call_index=1)
    assert '"years35_capped":{"Base":[88.84,82.74]}' in note


# =============================================================================
# Harness Tests 20-22
# =============================================================================

# S3 A+B (brief §3.8 retirement): desk_contract_mismatch:* is gone (no typed values remain to
# compare the desk against), so a contract with the requested (uncapped) path no longer differs
# from one with the applied path — desk_matched_inputs and desk_years35_capped are the same either
# way, and desk_contract_flags (fixup Task 3, §7.5 replay: the field itself stays, always []) no
# longer carries any mismatch flag.
def test_20_harness_snapshot_base_capped():
    """20. A snapshot whose Base scenario is capped:
    - desk_matched_inputs.stage1_growth_path is the applied path, and fade_years is the applied fade;
    - desk_years35_capped is True, and the sample gets years35_capped_by_desk;
    - this holds whether the contract's own stage1_growth_path is the applied or the requested one.
    """
    applied_path = [0.10, 0.08, 0.04, 0.04, 0.04]
    requested_path = [0.10, 0.08, 0.06, 0.05, 0.045]
    applied_fade = 5
    applied_iv = 120.0

    call_record = {
        "tool": "run_financial_model",
        "params": {
            "scenarios": [
                {"name": "Base", "growth_rates": requested_path, "fade_years": 5, "base_cf": 10.0, "wacc": 0.08, "shares_diluted": 1.0},
            ]
        },
        "result": {
            "scenario_dcfs": [
                {
                    "name": "Base",
                    "dcf": {
                        "per_share_iv": applied_iv,
                        "years35_capped": True,
                        "explicit_growth": applied_path,
                        "fade_years": applied_fade,
                    }
                }
            ]
        }
    }

    # Contract with applied path
    scorecard_applied = {
        "base_iv": applied_iv,
        "stage1_growth_path": applied_path,
        "fade_years": applied_fade,
        "base_cf_used": 10.0,
        "coe_used": 0.08,
    }
    metrics_app = cv.extract_desk_snapshot_metrics(
        snapshot=[call_record],
        base_iv=applied_iv,
        scorecard=scorecard_applied,
    )
    assert metrics_app["desk_matched_inputs"]["stage1_growth_path"] == applied_path
    assert metrics_app["desk_matched_inputs"]["fade_years"] == applied_fade
    assert metrics_app["desk_years35_capped"] is True
    assert metrics_app["desk_contract_flags"] == []

    # Contract with requested path
    scorecard_req = {
        "base_iv": applied_iv,
        "stage1_growth_path": requested_path,
        "fade_years": applied_fade,
        "base_cf_used": 10.0,
        "coe_used": 0.08,
    }
    metrics_req = cv.extract_desk_snapshot_metrics(
        snapshot=[call_record],
        base_iv=applied_iv,
        scorecard=scorecard_req,
    )
    assert metrics_req["desk_years35_capped"] is True
    assert metrics_req["desk_matched_inputs"]["stage1_growth_path"] == applied_path
    assert metrics_req["desk_contract_flags"] == []


def test_21_harness_requested_iv_not_desk_backed():
    """21. A base_iv equal to the requested value from years35_cap is not desk-backed (desk_iv_match is False).
    Choose numbers so that no other desk value lies within 1%.
    """
    requested_iv = 150.0
    applied_iv = 120.0

    call_record = {
        "tool": "run_financial_model",
        "params": {
            "scenarios": [
                {"name": "Base", "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "fade_years": 5, "base_cf": 10.0, "wacc": 0.08},
            ]
        },
        "result": {
            "scenario_dcfs": [
                {
                    "name": "Base",
                    "dcf": {
                        "per_share_iv": applied_iv,
                        "years35_capped": True,
                        "explicit_growth": [0.10, 0.08, 0.04, 0.04, 0.04],
                        "fade_years": 5,
                    }
                }
            ],
            "years35_cap": {
                "cap": 0.04,
                "reason": None,
                "dcfs": [
                    {
                        "name": "Base",
                        "requested_years35": [0.06, 0.05, 0.045],
                        "applied_years35": [0.04, 0.04, 0.04],
                        "requested_per_share_iv": requested_iv,
                        "applied_per_share_iv": applied_iv,
                        "applied_fade_years": 5,
                    }
                ]
            }
        }
    }
    metrics = cv.extract_desk_snapshot_metrics(
        snapshot=[call_record],
        base_iv=requested_iv,
        scorecard={"base_iv": requested_iv},
    )
    assert metrics["desk_iv_match"] is False


# S3 A+B (brief §3.8 retirement) — STOP, reported rather than patched (per this test's own
# docstring): with desk_contract_mismatch:* gone, this sample is desk-backed (desk_iv_match is
# True: the blend leg equals base_iv exactly) and carries no flag distinguishing a blend leg that
# reuses the year35-cap's *requested* (rejected) value from one that used the applied value.
# Neither of the original two escape conditions holds. Per the docstring's own instruction this is
# not patched with a new guard; the test now pins the observed behaviour and the gap is reported
# to the reviewer.
def test_22_harness_blend_requested_leg():
    """22. A blend call whose one leg is the requested (pre-cap) value: desk_iv_match is True and
    desk_matched_inputs is the blend leg's inputs (stage1_growth_path None, since a blend leg
    carries no path) — there is no longer a signal that the leg reused a rejected value.
    """
    requested_leg_iv = 150.0
    applied_leg_iv = 120.0

    call_dcf = {
        "tool": "run_financial_model",
        "params": {
            "scenarios": [{"name": "Base", "growth_rates": [0.10, 0.08, 0.06, 0.05, 0.045], "fade_years": 5, "base_cf": 10.0, "wacc": 0.08}]
        },
        "result": {
            "scenario_dcfs": [
                {
                    "name": "Base",
                    "dcf": {
                        "per_share_iv": applied_leg_iv,
                        "years35_capped": True,
                        "explicit_growth": [0.10, 0.08, 0.04, 0.04, 0.04],
                        "fade_years": 5,
                    }
                }
            ],
            "years35_cap": {
                "cap": 0.04,
                "reason": None,
                "dcfs": [
                    {
                        "name": "Base",
                        "requested_per_share_iv": requested_leg_iv,
                        "applied_per_share_iv": applied_leg_iv,
                    }
                ]
            }
        }
    }
    # Second call is a blend using requested_leg_iv as one leg
    blend_iv = round(0.5 * requested_leg_iv + 0.5 * 100.0, 2)
    call_blend = {
        "tool": "run_financial_model",
        "params": {
            "mode": "blend",
            "legs": [
                {"name": "RequestedBase", "weight": 0.5, "iv": requested_leg_iv},
                {"name": "Other", "weight": 0.5, "iv": 100.0},
            ]
        },
        "result": {
            "mode": "blend",
            "blended_per_share_iv": blend_iv,
            "per_share_iv": blend_iv,
        }
    }

    scorecard = {
        "base_iv": blend_iv,
        "stage1_growth_path": [0.10, 0.08, 0.06, 0.05, 0.045],
        "fade_years": 5,
    }

    metrics = cv.extract_desk_snapshot_metrics(
        snapshot=[call_dcf, call_blend],
        base_iv=blend_iv,
        scorecard=scorecard,
    )
    assert metrics["desk_iv_match"] is True
    assert metrics["desk_matched_inputs"]["stage1_growth_path"] is None
    assert metrics["desk_contract_flags"] == []
