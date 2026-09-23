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

def test_execute_financial_model_dispatch():
    payload = {
        "price": 951.0,
        "scenarios": [
            {"name": "Base", "iv": 1100.0, "prob": 0.35},
            {"name": "Bull", "iv": 1450.0, "prob": 0.20},
            {"name": "Bear", "iv": 550.0, "prob": 0.45},
        ],
        "base_cf": 3.8,
        "shares_diluted": 0.274,
        "wacc": 0.085,
        "terminal_g": 0.025,
        "demonstrated_cagr_5y": 7.5,
    }
    out = execute_financial_model(payload)
    assert "kelly_sizing" in out
    assert "reverse_dcf" in out
    assert "payoff_skew" in out
    assert out["kelly_sizing"]["quarter_kelly_pct"] == 0.0

def test_unbundled_dcf_boundary_conditions():
    # Negative base cash flow
    res_neg = unbundled_dcf(base_cf=-2.0, growth_rates=[0.1], wacc=0.1, terminal_g=0.025)
    assert "error" in res_neg

    # WACC <= terminal growth rate
    res_wacc = unbundled_dcf(base_cf=5.0, growth_rates=[0.05], wacc=0.02, terminal_g=0.025)
    assert "error" in res_wacc

def test_calculate_payoff_skew_zero_downside():
    # Price equals bear_iv -> downside = 0
    skew = calculate_payoff_skew(base_iv=100.0, bull_iv=150.0, bear_iv=100.0, price=100.0)
    assert skew == 99.9  # Asymmetric cap


def test_batch_scenario_dcf_execution():
    """Verify batch multi-scenario DCF in a single tool call."""
    payload = {
        "price": 951.04,
        "shares_diluted": 0.266,
        "net_debt": -9.6,  # Net cash
        "valuation_frame": "firm",
        "demonstrated_cagr_5y": 8.7,
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
    out = execute_financial_model(payload)
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
        valuation_frame="equity",
    )
    assert not res_zero.get("error")

    res_none = unbundled_dcf(
        base_cf=5.0,
        explicit_growth=[0.05],
        wacc=0.09,
        terminal_g=0.025,
        net_debt=None,
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
        valuation_frame="firm",
    )
    assert "error" in res_missing_shares
    assert "positive shares_diluted" in res_missing_shares["error"]


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


def test_blend_dispatch_via_execute_financial_model():
    """Verify blend mode dispatch and markdown formatting in execute_financial_model."""
    params = {
        "mode": "blend",
        "price": 160.0,
        "legs": [
            {"name": "Gordon DCF", "weight": 0.60, "iv": 150.0, "source": "desk_call_1"},
            {"name": "Exit Multiple", "weight": 0.40, "iv": 200.0, "source": "desk_call_2"},
        ],
    }
    res = execute_financial_model(params)
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




