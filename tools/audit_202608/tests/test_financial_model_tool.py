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
    execute_financial_model,
)

def test_unbundled_dcf_basic():
    # 5-year growth at 10%, terminal multiple 15x on Year 5 FCF, $10.0B base FCF, 10% WACC, 1B shares, $5B net debt
    res = unbundled_dcf(
        base_cf=10.0,
        growth_rates=[0.10, 0.10, 0.10, 0.10, 0.10],
        wacc=0.10,
        terminal_exit_multiple=15.0,
        net_debt=5.0,
        shares_diluted=1.0,
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
        "demonstrated_cagr_5y": 7.5,
    }
    out = execute_financial_model(payload)
    assert "kelly_sizing" in out
    assert "reverse_dcf" in out
    assert "payoff_skew" in out
    assert out["kelly_sizing"]["quarter_kelly_pct"] == 0.0

def test_unbundled_dcf_boundary_conditions():
    # Negative base cash flow
    res_neg = unbundled_dcf(base_cf=-2.0, growth_rates=[0.1], wacc=0.1)
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

