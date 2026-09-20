import pytest
from tools.audit_202608.fiduciary_gate import validate_fiduciary_contract

def test_valid_coherent_contract():
    card = {
        "base_iv": 1139.78, "bull_iv": 1570.65, "bear_iv": 636.29,
        "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
        "conviction_score": 12.0, "business_quality_moat": 4.3,
        "kelly_fraction_pct": 24.75, "asymmetric_payoff_skew": 1.97,
        "reentry_tranches": {"tranche_1_starter": 951.04, "tranche_2_core": 795.00},
        "thesis_invalidation_trigger": "Backlog declines for 2 quarters."
    }
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=951.04)
    assert is_valid is True
    assert issues == []
    assert sanitized["base_iv"] == 1139.78
    assert sanitized["asymmetric_payoff_skew"] == 1.97

def test_inverted_scenarios_rejected():
    card = {
        "base_iv": 100.0, "bull_iv": 80.0, "bear_iv": 120.0,  # INVERTED!
        "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
    }
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=100.0)
    assert is_valid is False
    assert any("monotonicity" in i.lower() or "inverted" in i.lower() for i in issues)

def test_negative_edge_clamps_kelly():
    card = {
        "base_iv": 90.0, "bull_iv": 110.0, "bear_iv": 50.0,
        "base_probability": 0.5, "bull_probability": 0.2, "bear_probability": 0.3,
        "kelly_fraction_pct": 8.0,  # Hallucinated Kelly on negative return!
    }
    # Expected IV = 0.5*90 + 0.2*110 + 0.3*50 = 45 + 22 + 15 = 82 vs price 100 -> Expected return -18%
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert any("clamped" in i.lower() for i in issues)

def test_tranche_inversion_repaired():
    card = {
        "base_iv": 120.0, "bull_iv": 160.0, "bear_iv": 80.0,
        "reentry_tranches": {"tranche_1_starter": 80.0, "tranche_2_core": 100.0}  # Inverted: starter < core
    }
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=100.0)
    assert is_valid is True
    assert sanitized["reentry_tranches"]["tranche_1_starter"] >= sanitized["reentry_tranches"]["tranche_2_core"]

def test_recalculate_payoff_skew_if_missing_or_divergent():
    card = {
        "base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
        "asymmetric_payoff_skew": 99.0  # Incorrectly stated
    }
    # Price = 90. Upside = 150 - 90 = 60. Downside = 90 - 80 = 10. Skew = 6.0x
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=90.0)
    assert is_valid is True
    assert sanitized["asymmetric_payoff_skew"] == 6.0
