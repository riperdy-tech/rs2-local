import pytest
from tools.audit_202608.fiduciary_gate import validate_fiduciary_contract

# P4.4 — a minimal, checkable invalidation_rules pair (one momentum metric, one financial
# metric), reused by every fixture below that wants a fully clean (issues == []) contract.
VALID_INVALIDATION_RULES = [
    {"metric": "mom_12_1", "comparator": "<", "threshold": -20.0,
     "window": "next reported quarter", "source": "momentum_state.json"},
    {"metric": "revenue_yoy_pct", "comparator": "<", "threshold": 0.0,
     "window": "next reported quarter", "source": "fundamentals_quarterly.json"},
]

def test_valid_coherent_contract():
    card = {
        "base_iv": 1139.78, "bull_iv": 1570.65, "bear_iv": 636.29,
        "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
        "conviction_score": 12.0, "business_quality_moat": 4.3,
        "kelly_fraction_pct": 24.75, "asymmetric_payoff_skew": 1.97,
        "reentry_tranches": {"tranche_1_starter": 951.04, "tranche_2_core": 795.00},
        "thesis_invalidation_trigger": "Backlog declines for 2 quarters.",
        "invalidation_rules": VALID_INVALIDATION_RULES,
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


# ================================================================================================
# P4.4 — invalidation_rules / momentum_break_rule / momentum_flip_condition / entry_timing
# ================================================================================================

def _card(**over):
    # base_iv strictly above price (120 vs 100) so the PRE-EXISTING base-vs-price edge clamp
    # never fires on its own — these tests isolate the NEW P4.4 thesis-completeness checks.
    base = {"base_iv": 120.0, "bull_iv": 160.0, "bear_iv": 90.0, "kelly_fraction_pct": 10.0,
            "invalidation_rules": VALID_INVALIDATION_RULES}
    base.update(over)
    return base


def test_missing_invalidation_rules_clamps_kelly_and_fails_the_contract():
    # is_valid stays True (structurally coherent contract, still medoid-eligible) but Kelly is
    # force-clamped to 0.0% via the same "Clamped Kelly" mechanism the edge test uses, which
    # depth_pipeline.fiduciary_verdict_gate turns into fiduciary_verdict: FAIL downstream.
    is_valid, sanitized, issues = validate_fiduciary_contract(_card(invalidation_rules=None),
                                                              price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert any("clamped" in i.lower() and "checkable" in i.lower() for i in issues)


def test_invalidation_rules_not_a_list_fails_the_contract():
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(invalidation_rules="mom_12_1 < -20"), price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert any("not a list" in i.lower() for i in issues)
    assert sanitized["invalidation_rules"] == []


def test_malformed_rules_missing_keys_are_dropped_and_count_as_uncheckable():
    rules = [{"metric": "mom_12_1", "comparator": "<"}]   # missing threshold/window/source
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(invalidation_rules=rules), price=100.0)
    assert sanitized["invalidation_rules"] == []           # dropped: cannot be evaluated
    assert sanitized["kelly_fraction_pct"] == 0.0           # zero checkable -> FAIL
    assert any("checkable" in i.lower() for i in issues)


def test_rule_outside_vocabulary_must_be_source_unverifiable_and_is_partially_checkable():
    rules = list(VALID_INVALIDATION_RULES) + [
        {"metric": "backlog_coverage_years", "comparator": ">", "threshold": 2.0,
         "window": "next reported quarter", "source": "unverifiable"},
    ]
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(invalidation_rules=rules), price=100.0)
    assert is_valid is True
    assert sanitized["invalidation_partially_checkable"] is True
    # At least one checkable rule survives, so Kelly is NOT forced to zero for this reason alone.
    assert sanitized["kelly_fraction_pct"] == 10.0
    assert any("partially_checkable" in i for i in issues)


def test_all_rules_outside_vocabulary_fails_the_contract():
    rules = [{"metric": "backlog_coverage_years", "comparator": ">", "threshold": 2.0,
              "window": "next reported quarter", "source": "unverifiable"}]
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(invalidation_rules=rules), price=100.0)
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert sanitized["invalidation_partially_checkable"] is True
    assert any("checkable" in i.lower() for i in issues)


def test_comparator_must_be_one_of_the_four():
    rules = [{"metric": "mom_12_1", "comparator": "==", "threshold": -20.0,
              "window": "next reported quarter", "source": "momentum_state.json"}]
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(invalidation_rules=rules), price=100.0)
    assert sanitized["invalidation_rules"] == []           # bad comparator -> not checkable
    assert sanitized["kelly_fraction_pct"] == 0.0


def test_momentum_break_rule_must_use_an_scr10_metric():
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(momentum_break_rule={"metric": "pe_ratio", "comparator": "<", "threshold": 10,
                                   "window_days": 30}),
        price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert any("scr-10" in i.lower() for i in issues)


def test_momentum_flip_condition_with_an_scr10_metric_does_not_fail():
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(momentum_flip_condition={"metric": "mom_6m", "comparator": ">", "threshold": 0.0,
                                       "window_days": 30}),
        price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 10.0
    assert not any("scr-10" in i.lower() for i in issues)


def test_entry_timing_must_be_one_of_the_three_values():
    is_valid, sanitized, issues = validate_fiduciary_contract(
        _card(entry_timing="buy_the_dip"), price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert any("entry_timing" in i for i in issues)


def test_entry_timing_valid_values_do_not_fail():
    for value in ("buy_now", "wait_for_momentum", "avoid"):
        is_valid, sanitized, issues = validate_fiduciary_contract(
            _card(entry_timing=value), price=100.0)
        assert is_valid is True
        assert sanitized["kelly_fraction_pct"] == 10.0, value
        assert not any("entry_timing" in i for i in issues), value


def test_metric_vocabulary_is_imported_not_duplicated():
    # fiduciary_gate.py holds no literal metric list of its own — it imports capability_test's
    # tuples (the two modules can be loaded under different sys.modules keys depending on
    # caller, bare `capability_test` vs package-qualified `tools.audit_202608.capability_test`,
    # so this checks value equality, the thing that actually matters for "never duplicated").
    from tools.audit_202608 import capability_test as cap
    from tools.audit_202608 import fiduciary_gate as fg
    assert fg.MOMENTUM_METRICS == cap.MOMENTUM_METRICS
    assert fg.FINANCIAL_METRICS == cap.FINANCIAL_METRICS
    assert "mom_12_1, mom_6m" in cap.TASK   # TASK's own text is built from the same tuple
