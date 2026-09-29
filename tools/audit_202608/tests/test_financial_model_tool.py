import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from financial_model_tool import (
    unbundled_dcf,
    reverse_dcf_expectations_gap,
    continuous_multi_outcome_kelly,
    calculate_payoff_skew,
    blend,
    execute_financial_model,
    format_model_results_markdown,
    _neutral_reference_dcf,
)

def test_unbundled_dcf_basic():
    # 5-year growth at 10%, terminal multiple 15x on Year 5 FCF, $10.0B base FCF, 10% WACC, 1B shares, $5B net debt
    res = unbundled_dcf(
        base_cf=10.0,
        growth_rates=[0.10, 0.10, 0.10, 0.10, 0.10],
        wacc=0.10,
        terminal_g=0.025,
        terminal_exit_multiple=15.0,
        net_debt=5.0,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
    )
    assert res["per_share_iv"] > 0
    assert res["dcf_pv"] > 0
    assert res["terminal_value_pv"] > 0
    assert res["enterprise_value"] > 0
    assert res["equity_value"] == pytest.approx(res["enterprise_value"] - 5.0, 0.01)

def test_unbundled_dcf_with_annuity():
    # Transactional DCF + separate unbundled services annuity stream ($2.0B annual annuity, 8% cap rate)
    res = unbundled_dcf(
        base_cf=10.0,
        growth_rates=[0.10, 0.10, 0.10, 0.10, 0.10],
        wacc=0.10,
        terminal_g=0.025,
        terminal_exit_multiple=15.0,
        annuity_flow=2.0,
        annuity_cap_rate=0.08,
        net_debt=0.0,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
    )
    # Annuity PV = 2.0 / 0.08 = 25.0
    assert res["annuity_pv"] == pytest.approx(25.0, 0.01)
    assert res["enterprise_value"] == pytest.approx(res["dcf_pv"] + res["terminal_value_pv"] + 25.0, 0.01)

def test_reverse_dcf_expectations_gap():
    # Market price $100, 1B shares = $100B mcap. Base FCF $5B. WACC 9%, terminal_g 2.5%.
    # Demonstrated 5y CAGR = 8.0%.
    res = reverse_dcf_expectations_gap(
        current_price=100.0,
        shares_diluted=1.0,
        base_cf=5.0,
        wacc=0.09,
        terminal_g=0.025,
        demonstrated_cagr_5y=8.0,
    )
    assert "implied_growth_next_5y_pct" in res
    assert "expectations_gap_pts" in res
    assert isinstance(res["implied_growth_next_5y_pct"], float)

def test_continuous_multi_outcome_kelly_negative_edge():
    # Base $1100 (35%), Bull $1450 (20%), Bear $550 (45%) at price $951 (from GEV case)
    outcomes = [
        {"name": "Base", "iv": 1100.0, "prob": 0.35},
        {"name": "Bull", "iv": 1450.0, "prob": 0.20},
        {"name": "Bear", "iv": 550.0, "prob": 0.45},
    ]
    res = continuous_multi_outcome_kelly(price=951.0, outcomes=outcomes)
    # Expected IV = 1100*0.35 + 1450*0.20 + 550*0.45 = 922.50
    # Expected return = (922.50 - 951) / 951 = -2.997% (negative)
    assert res["expected_return_pct"] < 0
    assert res["quarter_kelly_pct"] == 0.0
    assert res["full_kelly_pct"] == 0.0
    assert res["recommendation"] == "NO_ALLOCATION"

def test_continuous_multi_outcome_kelly_positive_edge():
    # Price $100, Base $130 (50%), Bull $170 (30%), Bear $70 (20%)
    outcomes = [
        {"name": "Base", "iv": 130.0, "prob": 0.50},
        {"name": "Bull", "iv": 170.0, "prob": 0.30},
        {"name": "Bear", "iv": 70.0, "prob": 0.20},
    ]
    res = continuous_multi_outcome_kelly(price=100.0, outcomes=outcomes)
    assert res["expected_return_pct"] > 0
    assert res["full_kelly_pct"] > 0
    assert res["quarter_kelly_pct"] > 0
    assert res["quarter_kelly_pct"] <= res["full_kelly_pct"]

def test_calculate_payoff_skew():
    skew = calculate_payoff_skew(base_iv=1100.0, bull_iv=1450.0, bear_iv=550.0, price=951.0)
    # (1450 - 951) / (951 - 550) = 499 / 401 = 1.244x
    assert round(skew, 2) == 1.24

# S3 A+B (brief §3.2, §3.3): price and demonstrated_cagr_5y (= revenue_cagr_5y_pct) come from
# context now; cash_flow_life and its reason are required.
# Revision 16 (brief_rev16.md): every scenario entry carries the inputs the desk values it with (an entry
# with only a name, prob and iv is refused), so the scenarios below are computed; all three values sit below
# the $951 price, so the expected return is negative and the Kelly size is still 0.0.
def test_execute_financial_model_dispatch():
    payload = {
        "scenarios": [
            {"name": "Base", "prob": 0.35, "base_cf": 3.8, "explicit_growth": [0.05] * 5, "wacc": 0.085},
            {"name": "Bull", "prob": 0.20, "base_cf": 4.56, "explicit_growth": [0.05] * 5, "wacc": 0.085},
            {"name": "Bear", "prob": 0.45, "base_cf": 1.9, "explicit_growth": [0.05] * 5, "wacc": 0.085},
        ],
        "base_cf": 3.8,
        "shares_diluted": 0.274,
        "wacc": 0.085,
        "terminal_g": 0.025,
        "fade_years": 5,
        "sbc_treatment": "deducted_in_cf",
        "cash_flow_life": "perpetual",
        "cash_flow_life_reason": "test",
        "base_cf_reason": "test",
        "bull_below_price_reason": "test",
    }
    out = execute_financial_model(payload, context={"price": 951.0, "revenue_cagr_5y_pct": 7.5})
    assert "kelly_sizing" in out
    assert "reverse_dcf" in out
    assert "payoff_skew" in out
    assert out["kelly_sizing"]["quarter_kelly_pct"] == 0.0

def test_unbundled_dcf_boundary_conditions():
    # Negative base cash flow
    res_neg = unbundled_dcf(
        base_cf=-2.0,
        growth_rates=[0.1],
        wacc=0.1,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
    )
    assert "error" in res_neg
    assert "base_cf must be positive" in res_neg["error"]

    # WACC <= terminal growth rate
    res_wacc = unbundled_dcf(
        base_cf=5.0,
        growth_rates=[0.05],
        wacc=0.02,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
    )
    assert "error" in res_wacc
    assert "must be greater than terminal_g" in res_wacc["error"]

def test_calculate_payoff_skew_zero_downside():
    # Price equals bear_iv -> downside = 0
    skew = calculate_payoff_skew(base_iv=100.0, bull_iv=150.0, bear_iv=100.0, price=100.0)
    assert skew == 99.9  # Asymmetric cap


# S3 A+B (brief §3.2, §3.3, §3.5 R7/R8): price and demonstrated_cagr_5y come from context now;
# cash_flow_life and its reason are required; the firm frame needs interest_addback and
# wacc_reason.
def test_batch_scenario_dcf_execution():
    """Verify batch multi-scenario DCF in a single tool call."""
    payload = {
        "shares_diluted": 0.266,
        "fade_years": 0,
        "sbc_treatment": "deducted_in_cf",
        "net_debt": -9.6,  # Net cash
        "valuation_frame": "firm",
        "cash_flow_life": "perpetual",
        "cash_flow_life_reason": "test",
        "interest_addback": 0.3,
        "wacc_reason": "COE ANCHOR 9%, cost of debt 4%, tax 21%, weights 80/20",
        "base_cf_reason": "test",   # no owner_earnings_default_b in context (R2)
        "scenarios": [
            {
                "name": "Base",
                "prob": 0.50,
                "base_cf": 4.8,
                "growth_rates": [0.29, 0.22, 0.17, 0.15, 0.12],
                "wacc": 0.095,
                "terminal_g": 0.045
            },
            {
                "name": "Bull",
                "prob": 0.30,
                "base_cf": 5.0,
                "growth_rates": [0.34, 0.26, 0.21, 0.18, 0.15],
                "wacc": 0.090,
                "terminal_g": 0.050
            },
            {
                "name": "Bear",
                "prob": 0.20,
                "base_cf": 4.5,
                "growth_rates": [0.15, 0.13, 0.07, 0.06, 0.05],
                "wacc": 0.115,
                "terminal_g": 0.025
            }
        ]
    }
    out = execute_financial_model(payload, context={"price": 951.04, "revenue_cagr_5y_pct": 8.7})
    assert "scenario_dcfs" in out
    assert len(out["scenario_dcfs"]) == 3
    assert out["scenario_dcfs"][0]["dcf"]["per_share_iv"] > 0
    assert out["scenario_dcfs"][1]["dcf"]["per_share_iv"] > out["scenario_dcfs"][0]["dcf"]["per_share_iv"]
    assert out["scenario_dcfs"][2]["dcf"]["per_share_iv"] < out["scenario_dcfs"][0]["dcf"]["per_share_iv"]
    assert "kelly_sizing" in out
    assert "payoff_skew" in out
    assert "reverse_dcf" in out


# ── Phase 4 Decision D1: Three-Stage DCF, Dual Terminal, Frames, SBC, Multiple Band ──

def test_three_stage_dcf_with_fade():
    """Verify hand-computed three-stage DCF with linear fade per D1.
    Parameters:
      base_cf = 100.0, explicit = [0.10, 0.10], fade_years = 2, terminal_g = 0.04,
      wacc = 0.10, shares = 10.0, net_debt = 0.0, frame = 'equity'.
    Hand calculation:
      Stage 1:
        Year 1 (g=0.10): CF1 = 110.0, PV1 = 100.0
        Year 2 (g=0.10): CF2 = 121.0, PV2 = 100.0
      Stage 2 (fade over 2 years from 0.10 to 0.04):
        Year 3 (i=1, g=0.07): CF3 = 121.0 * 1.07 = 129.47, PV3 = 129.47 / 1.1^3 = 97.2727
        Year 4 (i=2, g=0.04): CF4 = 129.47 * 1.04 = 134.6488, PV4 = 134.6488 / 1.1^4 = 91.9669
      Discrete DCF PV = 100.0 + 100.0 + 97.2727 + 91.9669 = 389.2396
      Stage 3 (Gordon Terminal Value at t=4):
        CF5 = 134.6488 * 1.04 = 140.034752
        TV_nominal = 140.034752 / (0.10 - 0.04) = 2333.912533
        TV_pv = 2333.912533 / 1.1^4 = 1594.093664
      Enterprise Value = 389.2396 + 1594.093664 = 1983.3333
      Equity Value = 1983.3333
      Per-share IV = 1983.3333 / 10.0 = 198.33
      Implied terminal EV/FCF multiple = TV_nominal / CF4 = 1.04 / 0.06 = 17.3333x
      Terminal share of value = 1594.093664 / 1983.3333 = 0.8037 (80.37%)
    """
    res = unbundled_dcf(
        base_cf=100.0,
        explicit_growth=[0.10, 0.10],
        fade_years=2,
        terminal_g=0.04,
        wacc=0.10,
        shares_diluted=10.0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert not res.get("error")
    assert res["dcf_pv"] == pytest.approx(389.24, 0.01)
    assert res["terminal_value_nominal"] == pytest.approx(2333.91, 0.01)
    assert res["terminal_value_pv"] == pytest.approx(1594.09, 0.01)
    assert res["enterprise_value"] == pytest.approx(1983.33, 0.02)
    assert res["per_share_iv"] == pytest.approx(198.33, 0.01)
    assert res["implied_terminal_ev_fcf_gordon"] == pytest.approx(17.33, 0.01)
    assert res["terminal_share_of_value"] == pytest.approx(0.8037, 0.001)
    assert res["growth_rates_applied"] == [0.10, 0.10, 0.07, 0.04]


def test_dual_terminal_gordon_and_exit_legs():
    """Verify both Gordon and Exit Multiple legs are calculated, discounted, and returned per D1."""
    res = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.08, 0.08, 0.08, 0.08, 0.08],
        fade_years=0,
        wacc=0.09,
        terminal_g=0.025,
        terminal_exit_multiple=18.0,
        net_debt=2.0,
        shares_diluted=1.0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
    )
    assert not res.get("error")
    assert "gordon_terminal" in res
    assert "exit_multiple_terminal" in res
    assert res["per_share_iv_gordon"] > 0
    assert res["per_share_iv_exit"] > 0
    assert res["gordon_terminal"]["terminal_value_pv"] > 0
    assert res["exit_multiple_terminal"]["terminal_value_pv"] > 0
    # Both terminal values must be discounted to t=0
    n = 5
    disc_factor = (1.0 + 0.09) ** n
    assert res["gordon_terminal"]["terminal_value_pv"] == pytest.approx(
        res["gordon_terminal"]["terminal_value_nominal"] / disc_factor, 0.01
    )
    assert res["exit_multiple_terminal"]["terminal_value_pv"] == pytest.approx(
        res["exit_multiple_terminal"]["terminal_value_nominal"] / disc_factor, 0.01
    )


def test_undiscounted_tv_regression_cat():
    """Regression test against undiscounted TV (the CAT audit defect).
    In CAT, nominal TV was added directly to discrete PV without discounting,
    producing an erroneous ~$440 (or here ~$510.69) instead of the true discounted ~$263 (or here ~$348.46).
    The tool MUST discount TV to t=0.
    """
    res = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.08, 0.08, 0.08, 0.08, 0.08],
        fade_years=0,
        wacc=0.09,
        terminal_g=0.025,
        net_debt=25.0,
        shares_diluted=0.50,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
    )
    assert not res.get("error")
    # Correct discounted values
    assert res["per_share_iv"] == pytest.approx(348.46, 0.02)
    assert res["terminal_value_pv"] == pytest.approx(150.59, 0.02)
    assert res["terminal_value_nominal"] == pytest.approx(231.70, 0.02)

    # Verify that enterprise_value used discounted TV, NOT nominal TV
    assert res["enterprise_value"] == pytest.approx(res["dcf_pv"] + res["terminal_value_pv"], 0.01)
    erroneous_ev = res["dcf_pv"] + res["terminal_value_nominal"]
    erroneous_iv = (erroneous_ev - 25.0) / 0.50
    assert erroneous_iv == pytest.approx(510.69, 0.02)
    assert res["enterprise_value"] < erroneous_ev
    assert res["per_share_iv"] < erroneous_iv


def test_valuation_frame_equity_refuses_nonzero_net_debt():
    """Valuation frame 'equity' discounts FCFE at CoE and strictly refuses nonzero net debt."""
    res_bad = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=10.0,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert "error" in res_bad
    assert "refuses nonzero net_debt" in res_bad["error"]

    # net_debt == 0.0 or None must succeed
    res_zero = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=0.0,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert not res_zero.get("error")

    res_none = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=None,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
    )
    assert not res_none.get("error")


def test_valuation_frame_firm_requires_net_debt_and_shares():
    """Valuation frame 'firm' discounts FCFF at WACC and requires net_debt and shares_diluted."""
    res_missing_debt = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=None,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
    )
    assert "error" in res_missing_debt
    assert "requires net_debt" in res_missing_debt["error"]

    res_missing_shares = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=5.0,
        shares_diluted=0.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
    )
    assert "error" in res_missing_shares
    assert "shares_diluted" in res_missing_shares["error"]


def test_missing_terminal_g_refused():
    """terminal_g is required; calls without it are refused with a structured error."""
    res = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=None,
    )
    assert "error" in res
    assert "terminal_g is required" in res["error"]


def test_rate_pairing_check():
    """Verify rate_engine.check_pairing is wired and returns structured FrameMismatch errors."""
    # Equity frame with true_wacc rate_type -> FrameMismatch
    res_eq_mismatch = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="equity",
        rate_type="true_wacc",
    )
    assert "error" in res_eq_mismatch
    assert "FrameMismatch" in res_eq_mismatch["error"]

    # Firm frame with cost_of_equity rate_type -> FrameMismatch
    res_firm_mismatch = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=2.0,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
        rate_type="cost_of_equity",
    )
    assert "error" in res_firm_mismatch
    assert "FrameMismatch" in res_firm_mismatch["error"]


def test_sbc_double_deduction_refused():
    """sbc_treatment='deducted_in_cf' may not also pass sbc_dilution (double deduction refused)."""
    res_double = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        sbc_dilution=0.05,
    )
    assert "error" in res_double
    assert "double deduction refused" in res_double["error"]

    # Valid single treatment: add_back_dilution with dilution factor
    res_valid = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="add_back_dilution",
        sbc_dilution=0.05,  # 5% share dilution
    )
    assert not res_valid.get("error")
    assert res_valid["shares_diluted"] == pytest.approx(1.05, 0.001)


def test_sector_multiple_band_inside_outside():
    """Verify reconciliation of Gordon and Exit leg implied multiples against sector_multiple_band."""
    # Gordon implied multiple: (1 + 0.04) / (0.10 - 0.04) = 17.33x
    band_inside = {"low": 15.0, "mid": 17.5, "high": 20.0, "metric": "EV/FCF"}
    res_in = unbundled_dcf(
        base_cf=100.0,
        explicit_growth=[0.10],
        wacc=0.10,
        terminal_g=0.04,
        shares_diluted=10.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        terminal_exit_multiple=18.0,
        sector_multiple_band=band_inside,
    )
    assert res_in["multiple_in_band_gordon"] is True
    assert res_in["multiple_in_band_exit"] is True

    band_outside = {"low": 10.0, "mid": 12.0, "high": 15.0, "metric": "EV/FCF"}
    res_out = unbundled_dcf(
        base_cf=100.0,
        explicit_growth=[0.10],
        wacc=0.10,
        terminal_g=0.04,
        shares_diluted=10.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        terminal_exit_multiple=18.0,
        sector_multiple_band=band_outside,
    )
    assert res_out["multiple_in_band_gordon"] is False
    assert res_out["multiple_in_band_exit"] is False


def test_reverse_dcf_missing_terminal_g_refused():
    """reverse DCF requires terminal_g; missing terminal_g returns structured error."""
    res = reverse_dcf_expectations_gap(
        current_price=100.0,
        shares_diluted=1.0,
        base_cf=5.0,
        wacc=0.09,
        terminal_g=None,
    )
    assert "error" in res
    assert "terminal_g is required" in res["error"]


def test_reverse_dcf_own_structure_recovers_known_growth():
    """Forward DCF at known growth rate must be recovered by reverse DCF own structure."""
    target_g = 0.12
    base_cf = 10.0
    wacc = 0.09
    terminal_g = 0.03
    fade_years = 4
    stage1_years = 5
    shares = 2.0

    forward = unbundled_dcf(
        base_cf=base_cf,
        explicit_growth=[target_g] * stage1_years,
        fade_years=fade_years,
        wacc=wacc,
        terminal_g=terminal_g,
        shares_diluted=shares,
        sbc_treatment="deducted_in_cf",
    )
    assert not forward.get("error")
    target_iv = forward["per_share_iv"]

    # Reverse solve
    rev = reverse_dcf_expectations_gap(
        current_price=target_iv,
        shares_diluted=shares,
        base_cf=base_cf,
        wacc=wacc,
        terminal_g=terminal_g,
        fade_years=fade_years,
        stage1_years=stage1_years,
    )
    assert not rev.get("error")
    solved_g_pct = rev["own_structure"]["solved_growth_pct"]
    assert solved_g_pct == pytest.approx(target_g * 100.0, abs=0.05)
    assert rev["implied_growth_next_5y_pct"] == pytest.approx(target_g * 100.0, abs=0.05)


def test_reverse_dcf_neutral_structure_recovers_known_growth():
    """Forward neutral reference DCF at known growth must be recovered by reverse DCF neutral structure."""
    known_initial_g = 0.15
    coe_anchor = 0.095
    terminal_g_anchor = 0.03
    base_cf = 8.0
    shares = 1.5

    iv, cf_10, expected_10y_cagr = _neutral_reference_dcf(
        base_cf=base_cf,
        g=known_initial_g,
        coe_anchor=coe_anchor,
        terminal_g_anchor=terminal_g_anchor,
        shares_diluted=shares,
    )

    rev = reverse_dcf_expectations_gap(
        current_price=iv,
        shares_diluted=shares,
        base_cf=base_cf,
        wacc=coe_anchor,
        terminal_g=terminal_g_anchor,
        coe_anchor=coe_anchor,
        terminal_g_anchor=terminal_g_anchor,
    )
    assert not rev.get("error")
    nr = rev["neutral_reference_structure"]
    assert nr["solved_initial_growth_pct"] == pytest.approx(known_initial_g * 100.0, abs=0.05)
    assert nr["implied_10y_cagr_pct"] == pytest.approx(expected_10y_cagr * 100.0, abs=0.05)


def test_reverse_dcf_base_rate_percentile_bands():
    """Verify classification into < p50, p50 - p90, and > p90 given base_rate_table."""
    base_rates = {
        "p50": 0.08,
        "p90": 0.16,
        "share_ge_10": 0.35,
        "share_ge_20": 0.15,
        "share_ge_30": 0.05,
    }
    coe_anchor = 0.09
    terminal_g_anchor = 0.025
    base_cf = 10.0
    shares = 1.0

    # 1. Low growth case: initial g = 0.03 -> 10y CAGR will be < 0.08 (p50)
    iv_low, _, _ = _neutral_reference_dcf(base_cf, 0.03, coe_anchor, terminal_g_anchor, shares_diluted=shares)
    rev_low = reverse_dcf_expectations_gap(
        current_price=iv_low,
        shares_diluted=shares,
        base_cf=base_cf,
        wacc=coe_anchor,
        terminal_g=terminal_g_anchor,
        coe_anchor=coe_anchor,
        terminal_g_anchor=terminal_g_anchor,
        base_rate_table=base_rates,
    )
    assert rev_low["neutral_reference_structure"]["percentile_band"] == "< p50"

    # 2. Mid growth case: initial g = 0.16 -> 10y CAGR will be between 0.08 and 0.16
    iv_mid, _, _ = _neutral_reference_dcf(base_cf, 0.16, coe_anchor, terminal_g_anchor, shares_diluted=shares)
    rev_mid = reverse_dcf_expectations_gap(
        current_price=iv_mid,
        shares_diluted=shares,
        base_cf=base_cf,
        wacc=coe_anchor,
        terminal_g=terminal_g_anchor,
        coe_anchor=coe_anchor,
        terminal_g_anchor=terminal_g_anchor,
        base_rate_table=base_rates,
    )
    assert rev_mid["neutral_reference_structure"]["percentile_band"] == "p50 - p90"

    # 3. High growth case: initial g = 0.35 -> 10y CAGR will be > 0.16 (p90)
    iv_high, _, _ = _neutral_reference_dcf(base_cf, 0.35, coe_anchor, terminal_g_anchor, shares_diluted=shares)
    rev_high = reverse_dcf_expectations_gap(
        current_price=iv_high,
        shares_diluted=shares,
        base_cf=base_cf,
        wacc=coe_anchor,
        terminal_g=terminal_g_anchor,
        coe_anchor=coe_anchor,
        terminal_g_anchor=terminal_g_anchor,
        base_rate_table=base_rates,
    )
    assert rev_high["neutral_reference_structure"]["percentile_band"] == "> p90"


def test_blend_arithmetic_exact():
    """Verify exact weighted blend of named desk valuation legs and price margin of safety."""
    legs_2 = [
        {"name": "Gordon DCF", "weight": 0.60, "iv": 150.0, "source": "desk_call_1"},
        {"name": "Exit Multiple", "weight": 0.40, "iv": 200.0, "source": "desk_call_2"},
    ]
    res_2 = blend(legs=legs_2, price=160.0)
    assert not res_2.get("error")
    assert res_2["blended_per_share_iv"] == 170.0
    assert res_2["per_share_iv"] == 170.0
    assert res_2["weights_sum"] == pytest.approx(1.0, 0.0001)
    assert res_2["mos_pct"] == pytest.approx(6.25, 0.01)
    assert len(res_2["legs"]) == 2
    assert res_2["legs"][0]["source"] == "desk_call_1"
    assert res_2["legs"][1]["source"] == "desk_call_2"

    legs_3 = [
        {"name": "Base DCF", "weight": 0.50, "per_share_iv": 100.0, "result_id": "snap_1"},
        {"name": "Bull DCF", "weight": 0.30, "per_share_iv": 120.0, "result_id": "snap_2"},
        {"name": "Bear DCF", "weight": 0.20, "per_share_iv": 80.0, "result_id": "snap_3"},
    ]
    res_3 = blend(legs=legs_3)
    assert not res_3.get("error")
    assert res_3["blended_per_share_iv"] == 102.0
    assert res_3["per_share_iv"] == 102.0
    assert res_3["legs"][0]["result_id"] == "snap_1"


def test_blend_weights_not_summing_to_one_refused():
    """Blend weights must sum to 1.0; deviations and negative weights are refused."""
    legs_under = [
        {"name": "Leg A", "weight": 0.50, "iv": 100.0},
        {"name": "Leg B", "weight": 0.40, "iv": 100.0},
    ]
    res_under = blend(legs=legs_under)
    assert "error" in res_under
    assert "must sum to 1.0" in res_under["error"]

    legs_neg = [
        {"name": "Leg A", "weight": 1.10, "iv": 100.0},
        {"name": "Leg B", "weight": -0.10, "iv": 100.0},
    ]
    res_neg = blend(legs=legs_neg)
    assert "error" in res_neg
    assert "negative weight" in res_neg["error"]


def test_blend_missing_or_invalid_legs():
    """Verify validation on empty legs and missing IV values."""
    assert "error" in blend([])
    assert "error" in blend([{"name": "No IV", "weight": 1.0}])


# S3 A+B (brief §3.2): price comes from context now, including in blend mode.
def test_blend_dispatch_via_execute_financial_model():
    """Verify blend mode dispatch and markdown formatting in execute_financial_model."""
    params = {
        "mode": "blend",
        "legs": [
            {"name": "Gordon DCF", "weight": 0.60, "iv": 150.0, "source": "desk_call_1"},
            {"name": "Exit Multiple", "weight": 0.40, "iv": 200.0, "source": "desk_call_2"},
        ],
    }
    res = execute_financial_model(params, context={"price": 160.0})
    assert not res.get("error")
    assert res["mode"] == "blend"
    assert res["blended_per_share_iv"] == 170.0
    assert res["per_share_iv"] == 170.0
    assert res["mos_pct"] == pytest.approx(6.25, 0.01)

    md = format_model_results_markdown(res)
    assert "Valuation Blend Summary" in md
    assert "Gordon DCF" in md
    assert "Exit Multiple" in md
    assert "$170.00" in md
    assert "+6.2%" in md


# ── Phase 4 FIX 1: Required DCF inputs & no silent defaults ──

def test_required_inputs_all_missing_returns_single_error():
    """All missing required inputs returned at once with validation_error: True."""
    res = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.05],
        wacc=0.09,
    )
    assert res.get("validation_error") is True
    assert res.get("missing") == ["terminal_g", "shares_diluted", "fade_years", "sbc_treatment"]
    assert "terminal_g is required" in res["error"]
    assert "missing required inputs: terminal_g, shares_diluted, fade_years, sbc_treatment (terminal_g is required) (no silent defaults since Phase 4)" == res["error"]


def test_each_required_input_individually_missing():
    """Each required input missing returns validation_error: True and identifies missing input."""
    base_args = {
        "base_cf": 10.0,
        "explicit_growth": [0.05],
        "wacc": 0.09,
        "terminal_g": 0.025,
        "shares_diluted": 1.0,
        "fade_years": 0,
        "sbc_treatment": "deducted_in_cf",
    }

    # Missing terminal_g
    args = dict(base_args)
    del args["terminal_g"]
    r_tg = unbundled_dcf(**args)
    assert r_tg.get("validation_error") is True
    assert r_tg.get("missing") == ["terminal_g"]
    assert "terminal_g is required" in r_tg["error"]

    # Missing shares_diluted
    args = dict(base_args)
    del args["shares_diluted"]
    r_sd = unbundled_dcf(**args)
    assert r_sd.get("validation_error") is True
    assert r_sd.get("missing") == ["shares_diluted"]

    # Missing fade_years
    args = dict(base_args)
    del args["fade_years"]
    r_fy = unbundled_dcf(**args)
    assert r_fy.get("validation_error") is True
    assert r_fy.get("missing") == ["fade_years"]

    # Missing sbc_treatment
    args = dict(base_args)
    del args["sbc_treatment"]
    r_sbc = unbundled_dcf(**args)
    assert r_sbc.get("validation_error") is True
    assert r_sbc.get("missing") == ["sbc_treatment"]


def test_sbc_dilution_mode_validation():
    """'dilution' without sbc_dilution is refused; with sbc_dilution it succeeds and dilutes shares."""
    # Refused without sbc_dilution
    res_bad = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="dilution",
    )
    assert res_bad.get("validation_error") is True
    assert "sbc_dilution" in res_bad["missing"]

    # Succeeded with sbc_dilution
    res_good = unbundled_dcf(
        base_cf=10.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="dilution",
        sbc_dilution=0.04,  # 4% dilution
    )
    assert not res_good.get("error")
    assert res_good["shares_diluted"] == pytest.approx(1.04, 0.001)


# S3 A+B (brief §3.2, task order "specific tests"): the context now carries the price and the
# call carries a life (both required), so the refusal is for shares_diluted alone; sbc_treatment
# is given so it no longer confounds the check.
def test_old_amd_call_9_params_refused():
    """Old AMD call-9 params (omitted shares_diluted) refused with validation_error."""
    params = {
        "base_cf": 6.765,
        "growth_rates": [0.20, 0.15, 0.12, 0.10, 0.08],
        "fade_years": 5,
        "wacc": 0.095,
        "terminal_g": 0.03,
        "sbc_treatment": "deducted_in_cf",
        "cash_flow_life": "perpetual",
        "cash_flow_life_reason": "test",
        # omitted shares_diluted
    }
    res = execute_financial_model(params, context={"price": 160.0})
    assert res.get("validation_error") is True
    assert any("shares_diluted" in m for m in res["missing"])
    assert not any("sbc_treatment" in m for m in res["missing"])
    assert "no silent defaults since Phase 4" in res["error"]


# S3 A+B (brief §3.2, task order "specific tests"): the desk still never invents a share count.
# With no shares in the call and none in the context, the whole call is refused with
# shares_diluted among the missing inputs (V6) — there is no longer a "reverse DCF skipped" path
# for a call with no share count anywhere, since the top-level DCF itself cannot compute either.
# With shares_default_b in the context, the reverse DCF uses exactly that count.
def test_reverse_dcf_never_uses_defaulted_share_count():
    """Reverse DCF path must not run on a defaulted share count: explicit shares_diluted, or the
    context's shares_default_b, is required."""
    cfl = {"cash_flow_life": "perpetual", "cash_flow_life_reason": "test", "base_cf_reason": "test",
           "bull_below_price_reason": "test", "bear_above_price_reason": "test"}

    def three(base):
        # revision 16: a call that sends scenarios needs exactly one Base, one Bull and one Bear; the
        # Bull and Bear are the Base's inputs at 1.2x and 0.5x the cash flow and are not under test
        return [dict(base, prob=0.5), dict(base, name="Bull", prob=0.25, base_cf=base["base_cf"] * 1.2),
                dict(base, name="Bear", prob=0.25, base_cf=base["base_cf"] * 0.5)]

    payload_sc_no_shares = {
        "scenarios": three({
            "name": "Base",
            "base_cf": 5.0,
            "growth_rates": [0.10, 0.08],
            "wacc": 0.09,
            "terminal_g": 0.025,
            "fade_years": 0,
            "sbc_treatment": "deducted_in_cf",
            # shares_diluted omitted
        }),
        **cfl,
    }
    res = execute_financial_model(payload_sc_no_shares, context={"price": 100.0})
    assert res.get("validation_error") is True
    assert any("shares_diluted" in m for m in res["missing"])

    payload_sc_with_shares = {
        "scenarios": three({
            "name": "Base",
            "base_cf": 5.0,
            "growth_rates": [0.10, 0.08],
            "wacc": 0.09,
            "terminal_g": 0.025,
            "fade_years": 0,
            "sbc_treatment": "deducted_in_cf",
            "shares_diluted": 1.635,
        }),
        **cfl,
    }
    res_ok = execute_financial_model(payload_sc_with_shares, context={"price": 100.0})
    assert not res_ok.get("error")
    assert "reverse_dcf" in res_ok
    assert not res_ok["reverse_dcf"].get("skipped")
    assert res_ok["reverse_dcf"]["shares_diluted"] == 1.635

    # No shares anywhere in the call, but the context carries shares_default_b: the reverse DCF
    # uses exactly that count (never invents one, never silently substitutes another value).
    payload_rev_default = {
        "base_cf": 5.0,
        "wacc": 0.09,
        "terminal_g": 0.025,
        "fade_years": 0,
        "sbc_treatment": "deducted_in_cf",
        **cfl,
    }
    res_default = execute_financial_model(payload_rev_default, context={"price": 100.0, "shares_default_b": 2.5})
    assert not res_default.get("error")
    assert "reverse_dcf" in res_default
    assert not res_default["reverse_dcf"].get("skipped")
    assert res_default["reverse_dcf"]["shares_diluted"] == 2.5


def test_finite_life_10_years_equals_hand_computed_pv():
    # 10-year finite life equals the hand-computed PV of 10 flows (no terminal)
    base_cf = 10.0
    rates = [0.05, 0.05, 0.05, 0.05, 0.05]
    fade_years = 5
    terminal_g = 0.02
    wacc = 0.08
    shares = 1.0

    # Hand computation:
    cf = base_cf
    pv_sum = 0.0
    # Stage 1: 5 years at 5%
    for i in range(1, 6):
        cf = cf * 1.05
        pv_sum += cf / (1.08 ** i)
    # Stage 2: 5 years linear fade from 5% to 2%
    for i in range(1, 6):
        year = 5 + i
        g_t = 0.05 + (0.02 - 0.05) * (i / 5)
        cf = cf * (1.0 + g_t)
        pv_sum += cf / (1.08 ** year)

    res = unbundled_dcf(
        base_cf=base_cf,
        growth_rates=rates,
        wacc=wacc,
        terminal_g=terminal_g,
        fade_years=fade_years,
        shares_diluted=shares,
        sbc_treatment="deducted_in_cf",
        finite_life_years=10,
    )
    assert res["terminal_method"] == "finite life 10 years"
    assert res["terminal_value_pv"] == 0
    assert res["terminal_share_of_value"] == 0
    assert res["finite_life_years"] == 10
    assert len(res["projected_cfs"]) == 10
    assert res["dcf_pv"] == pytest.approx(round(pv_sum, 2), 0.01)
    assert res["per_share_iv"] == pytest.approx(round(pv_sum, 2), 0.01)


def test_finite_life_shorter_than_stage1_truncates_it():
    # Finite life shorter than stage-1 path truncates it (e.g. 3 years on 5-year path)
    res = unbundled_dcf(
        base_cf=10.0,
        growth_rates=[0.10, 0.10, 0.10, 0.10, 0.10],
        wacc=0.10,
        terminal_g=0.02,
        fade_years=0,
        shares_diluted=1.0,
        sbc_treatment="deducted_in_cf",
        finite_life_years=3,
    )
    assert len(res["projected_cfs"]) == 3
    assert len(res["pv_cfs"]) == 3
    # Year 1: 11 / 1.1 = 10; Year 2: 12.1 / 1.21 = 10; Year 3: 13.31 / 1.331 = 10 => sum = 30
    assert res["dcf_pv"] == pytest.approx(30.0, 0.01)
    assert res["per_share_iv"] == pytest.approx(30.0, 0.01)
    assert res["terminal_value_pv"] == 0


def test_finite_life_ignores_exit_multiple_with_note():
    # Exit multiple is ignored and result carries note: "exit multiple ignored: finite life"
    res = unbundled_dcf(
        base_cf=10.0,
        growth_rates=[0.05, 0.05, 0.05, 0.05, 0.05],
        wacc=0.08,
        terminal_g=0.02,
        terminal_exit_multiple=15.0,
        fade_years=0,
        shares_diluted=1.0,
        sbc_treatment="deducted_in_cf",
        finite_life_years=10,
    )
    assert res.get("note") == "exit multiple ignored: finite life"
    assert res["terminal_value_pv"] == 0
    assert res["terminal_method"] == "finite life 10 years"
    assert "per_share_iv_exit" not in res


def test_finite_life_validation_errors():
    # Validation errors for 0, 61, 2.5
    for bad_val in (0, 61, 2.5):
        res = unbundled_dcf(
            base_cf=10.0,
            growth_rates=[0.05, 0.05, 0.05, 0.05, 0.05],
            wacc=0.08,
            terminal_g=0.02,
            fade_years=0,
            shares_diluted=1.0,
            sbc_treatment="deducted_in_cf",
            finite_life_years=bad_val,
        )
        assert res.get("validation_error") is True
        assert "finite_life_years" in res.get("missing", [])


def test_call_without_finite_life_is_unchanged():
    # Call without finite_life_years is unchanged (compare to test_unbundled_dcf_basic values)
    res = unbundled_dcf(
        base_cf=10.0,
        growth_rates=[0.10, 0.10, 0.10, 0.10, 0.10],
        wacc=0.10,
        terminal_g=0.025,
        terminal_exit_multiple=15.0,
        net_debt=5.0,
        shares_diluted=1.0,
        fade_years=0,
        sbc_treatment="deducted_in_cf",
        valuation_frame="firm",
    )
    assert res["per_share_iv"] > 0
    assert res["terminal_value_pv"] > 0
    assert "finite_life_years" not in res
    assert "finite life" not in res["terminal_method"]


# S3 A+B (brief §3.4 V3): a scenario's own finite_life_years left the schema and is now refused;
# cash_flow_life is a single top-level call argument that reaches every scenario uniformly
# (there is no longer a way to mix a finite Base with a perpetual Bull in one call).
def test_finite_life_execute_financial_model_batch():
    # execute_financial_model passes cash_flow_life to every scenario DCF, not per scenario.
    params = {
        "shares_diluted": 1.0,
        "terminal_g": 0.02,
        "fade_years": 0,
        "sbc_treatment": "deducted_in_cf",
        "cash_flow_life": 3,
        "cash_flow_life_reason": "test",
        "base_cf_reason": "test",
        "bull_below_price_reason": "test",
        "scenarios": [
            {
                "name": "Base",
                "prob": 0.5,
                "base_cf": 10.0,
                "growth_rates": [0.05, 0.05, 0.05],
                "wacc": 0.08,
                "terminal_g": 0.02,
            },
            {
                "name": "Bull",
                "prob": 0.25,
                "base_cf": 10.0,
                "growth_rates": [0.10, 0.10, 0.10],
                "wacc": 0.08,
                "terminal_g": 0.02,
            },
            {   # revision 16: a call that sends scenarios needs Bear too (not under test here)
                "name": "Bear",
                "prob": 0.25,
                "base_cf": 10.0,
                "growth_rates": [0.0, 0.0, 0.0],
                "wacc": 0.08,
                "terminal_g": 0.02,
            }
        ]
    }
    res = execute_financial_model(params, context={"price": 100.0})
    assert not res.get("error")
    scs = res.get("scenario_dcfs") or []
    assert len(scs) == 3
    base_dcf = scs[0]["dcf"]
    assert base_dcf["finite_life_years"] == 3
    assert base_dcf["terminal_method"] == "finite life 3 years"
    assert base_dcf["terminal_value_pv"] == 0

    bull_dcf = scs[1]["dcf"]
    assert bull_dcf["finite_life_years"] == 3
    assert bull_dcf["terminal_value_pv"] == 0

    # A scenario's own finite_life_years is now refused (V3): use cash_flow_life instead.
    params_v3 = dict(params)
    params_v3["scenarios"] = [dict(params["scenarios"][0], finite_life_years=3)] + params["scenarios"][1:]
    res_v3 = execute_financial_model(params_v3, context={"price": 100.0})
    assert res_v3.get("validation_error") is True
    assert any("finite_life_years" in m for m in res_v3["missing"])

    md = format_model_results_markdown(res)
    assert "finite life 3 years" in md







def test_finite_life_accepts_whole_number_float_and_digit_string():
    kw = dict(base_cf=10.0, growth_rates=[0.05, 0.05, 0.05, 0.05, 0.05], wacc=0.08, terminal_g=0.02, fade_years=0,
              shares_diluted=1.0, sbc_treatment="deducted_in_cf")
    ref = unbundled_dcf(finite_life_years=15, **kw)["per_share_iv"]
    assert unbundled_dcf(finite_life_years=15.0, **kw)["per_share_iv"] == ref
    assert unbundled_dcf(finite_life_years="15", **kw)["per_share_iv"] == ref
    assert unbundled_dcf(finite_life_years="15.5", **kw).get("validation_error") is True
