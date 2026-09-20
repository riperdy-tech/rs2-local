import pytest
from tools.audit_202608.consensus_valuation import select_medoid_scorecard

def test_medoid_selection_preserves_sample_integrity():
    price = 100.0
    runs = [
        {
            "sample": 1, "iv": 110.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 110.0, "bull_iv": 150.0, "bear_iv": 80.0,
                "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
                "conviction_score": 11.0, "business_quality_moat": 4.0,
                "kelly_fraction_pct": 12.0, "asymmetric_payoff_skew": 2.50,
                "reentry_tranches": {"tranche_1_starter": 95.0, "tranche_2_core": 80.0},
                "thesis_invalidation_trigger": "Trigger 1"
            }
        },
        {
            "sample": 2, "iv": 115.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 115.0, "bull_iv": 160.0, "bear_iv": 85.0,
                "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
                "conviction_score": 12.0, "business_quality_moat": 4.2,
                "kelly_fraction_pct": 14.0, "asymmetric_payoff_skew": 3.00,
                "reentry_tranches": {"tranche_1_starter": 100.0, "tranche_2_core": 85.0},
                "thesis_invalidation_trigger": "Trigger 2"
            }
        },
        {
            "sample": 3, "iv": 200.0, "plausible": True, "truncated": False,  # Wild outlier
            "scorecard": {
                "base_iv": 200.0, "bull_iv": 300.0, "bear_iv": 90.0,
                "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
                "conviction_score": 14.0, "business_quality_moat": 4.5,
                "kelly_fraction_pct": 25.0, "asymmetric_payoff_skew": 20.0,
                "reentry_tranches": {"tranche_1_starter": 150.0, "tranche_2_core": 120.0},
                "thesis_invalidation_trigger": "Trigger 3"
            }
        }
    ]
    medoid, summary = select_medoid_scorecard(runs, price)

    # The medoid sample should be Sample 2 (closest to median IV 115.0 and median Moat 4.2)
    assert summary["medoid_sample"] == 2
    assert medoid["base_iv"] == 115.0
    assert medoid["bull_iv"] == 160.0
    assert medoid["bear_iv"] == 85.0
    assert medoid["thesis_invalidation_trigger"] == "Trigger 2"
    assert medoid["kelly_fraction_pct"] == 14.0
    assert medoid["reentry_tranches"]["tranche_1_starter"] == 100.0

    # The summary captures the full 3-sample dispersion
    assert summary["iv_band_low"] == 110.0
    assert summary["iv_band_high"] == 200.0
    assert summary["median_iv"] == 115.0
    assert summary["spread_pct"] == pytest.approx(81.8, 0.1)  # (200 - 110) / 110 * 100
    assert summary["converged"] is False  # 81.8% > 25.0%

def test_medoid_excludes_invalid_cards():
    price = 100.0
    runs = [
        {
            "sample": 1, "iv": 120.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 120.0, "bull_iv": 100.0, "bear_iv": 140.0,  # INVERTED! Fails validation
            }
        },
        {
            "sample": 2, "iv": 130.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 130.0, "bull_iv": 170.0, "bear_iv": 90.0,
                "conviction_score": 12.0, "business_quality_moat": 4.0,
                "kelly_fraction_pct": 10.0,
                "thesis_invalidation_trigger": "Valid Trigger"
            }
        }
    ]
    medoid, summary = select_medoid_scorecard(runs, price)
    # Sample 1 was rejected by fiduciary validator, so Sample 2 must be chosen
    assert summary["medoid_sample"] == 2
    assert medoid["base_iv"] == 130.0
    assert medoid["thesis_invalidation_trigger"] == "Valid Trigger"


def test_published_contract_base_owns_the_medoid_sample_not_the_median():
    """GEV 2026-09-20: the exported contract mixed FIELD OWNERSHIP across two samples.

    The medoid was sample 2 (base IV $1,037.88) but the summary published the three-sample MEDIAN
    ($934.54) at `median_iv` while taking bull/bear/conviction/Kelly from sample 2. Both numbers
    were then exported as if they were the same thing, and `depth_pipeline` computed MoS from the
    median while carrying sample 2's Kelly — publishing "Kelly 8.98%" beside "MoS -1.7%".

    RS2.txt line 352 defines MoS = (IV Base - Price) / IV Base, and Kelly sits in the same step,
    so ONE sample must own both. This test pins that the contract base is the medoid's own value
    and stays distinct from the dispersion statistic.
    """
    price = 951.04
    runs = [
        {"sample": 2, "iv": 1037.88, "plausible": True, "truncated": False, "scorecard": {
            "base_iv": 1037.88, "bull_iv": 1228.67, "bear_iv": 588.96,
            "conviction_score": 10.5, "business_quality_moat": 4.05,
            "kelly_fraction_pct": 8.98, "asymmetric_payoff_skew": 0.77,
            "reentry_tranches": {"tranche_1_starter": 951.04, "tranche_2_core": 750.0},
            "thesis_invalidation_trigger": "Backlog declines >$10B in any single quarter"}},
        {"sample": 3, "iv": 831.19, "plausible": True, "truncated": False, "scorecard": {
            "base_iv": 831.19, "bull_iv": 1164.51, "bear_iv": 517.29,
            "conviction_score": 7.0, "business_quality_moat": 3.5,
            "kelly_fraction_pct": 0.0, "asymmetric_payoff_skew": 0.49,
            "reentry_tranches": {"tranche_1_starter": 790.0, "tranche_2_core": 545.0},
            "thesis_invalidation_trigger": "Total backlog declines below $150B"}},
    ]
    medoid, summary = select_medoid_scorecard(runs, price)

    assert summary["medoid_sample"] == 2
    # The contract base is whichever sample owns the contract — not a cross-sample average.
    assert summary["base_iv"] == medoid["base_iv"] == 1037.88
    # The median stays published, but as a dispersion statistic, never as the contract base.
    assert summary["median_iv"] == pytest.approx(934.535)
    assert summary["base_iv"] != summary["median_iv"]
