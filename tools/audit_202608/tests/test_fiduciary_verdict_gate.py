import pytest
from depth_pipeline import band_verdict

# P4.4 — a minimal, checkable invalidation_rules pair, so a scorecard under test does not
# incidentally trip the new "thesis cannot be falsified" contract FAIL when the test is really
# about something else (lost-sample sizing, MoS restatement, ...).
VALID_INVALIDATION_RULES = [
    {"metric": "mom_12_1", "comparator": "<", "threshold": -20.0,
     "window": "next reported quarter", "source": "momentum_state.json"},
    {"metric": "revenue_yoy_pct", "comparator": "<", "threshold": 0.0,
     "window": "next reported quarter", "source": "fundamentals_quarterly.json"},
]

def test_non_converged_spread_blocks_undervalued_buy():
    # Like DXC: Price 11.07, IVs [17.4, 45.0], spread 158.6% -> Must NOT be "undervalued" buy!
    doc = {
        "ticker": "DXC", "price": 11.07, "samples_run": 3, "converged": False,
        "spread_pct": 158.6, "median_iv": 31.2, "tolerance_pct": 25.0,
        "runs": [
            {"sample": 1, "iv": 17.4, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 45.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 17.4, "median_quality_moat": 2.1}
    }
    v = band_verdict(doc)
    assert v["direction"] == "hold"
    assert "high dispersion" in v["reason"].lower() or "quarantine" in v["reason"].lower()
    assert "HIGH_DISPERSION_QUARANTINE" in v["flags"]


def test_p4_8_non_converged_spread_blocks_overvalued_sell_too():
    # P4.8 — symmetric dispersion. Price 200, IVs [80, 150] (spread 87.5%, past the 25% tol),
    # median 100: the MoS-floor rule alone would call this "overvalued" — model disagreement on
    # the sell side must withhold capital exactly as it does on the buy side.
    doc = {
        "ticker": "OVERDISP", "price": 200.0, "samples_run": 3, "converged": False,
        "spread_pct": 87.5, "median_iv": 100.0, "tolerance_pct": 25.0,
        "runs": [
            {"sample": 1, "iv": 80.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 150.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 100.0, "invalidation_rules": VALID_INVALIDATION_RULES}
    }
    v = band_verdict(doc)
    assert v["direction"] == "hold"
    assert "overvalued withheld" in v["reason"].lower()
    assert "HIGH_DISPERSION_QUARANTINE" in v["flags"]


def test_lost_sample_caps_size_to_half():
    # Like GTE: 1 sample lost, 2 surviving agree within 11.8% -> Must NOT be "full" size!
    doc = {
        "ticker": "GTE", "price": 10.47, "samples_run": 3, "converged": True,
        "spread_pct": 11.8, "median_iv": 13.2, "early_stop": False,
        "runs": [
            {"sample": 1, "iv": None, "plausible": False, "truncated": True},
            {"sample": 2, "iv": 12.49, "plausible": True, "truncated": False},
            {"sample": 3, "iv": 13.96, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 13.2, "invalidation_rules": VALID_INVALIDATION_RULES}
    }
    v = band_verdict(doc)
    assert v["direction"] == "undervalued"
    assert v["size_hint"] in ["half", "quarter"]
    assert v["size_hint"] != "full"

def test_asymmetric_compounder_is_flagged_but_no_longer_overrides_direction():
    # P4.8 removed the moat override as a DIRECTION change (it erased the disagreement the
    # divergence engine exists to record, and is price-anchoring at the verdict layer). High
    # quality compounder: Price 110, Base IVs [98, 100], median_iv 99, MoS exactly at the 10%
    # floor (110-99)/110 = 10.0%, price within 10% above the top of the band (110 == 1.10*100)
    # -> the direction the MoS-floor rule alone would produce is "overvalued", and it MUST STAY
    # "overvalued" — only the info flag/reason fire.
    doc = {
        "ticker": "CMPD", "price": 110.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": 99.0, "early_stop": True,
        "runs": [
            {"sample": 1, "iv": 98.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 100.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {
            "median_iv": 99.0, "median_bull_iv": 180.0, "median_bear_iv": 85.0,
            "median_quality_moat": 4.5, "asymmetric_payoff_skew": 3.5,
            "median_kelly_fraction_pct": 15.0,
            "invalidation_rules": VALID_INVALIDATION_RULES,
        }
    }
    v = band_verdict(doc)
    assert v["direction"] == "overvalued"
    assert "compounder_near_fair_value" in v["flags"]
    assert "compounder near fair value" in v["reason"].lower()


def test_compounder_flag_does_not_fire_more_than_10pct_above_the_band():
    doc = {
        "ticker": "CMPD2", "price": 130.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": 99.0, "early_stop": True,
        "runs": [
            {"sample": 1, "iv": 98.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 100.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {
            "median_iv": 99.0, "median_quality_moat": 4.5, "asymmetric_payoff_skew": 3.5,
            "median_kelly_fraction_pct": 15.0,
            "invalidation_rules": VALID_INVALIDATION_RULES,
        }
    }
    v = band_verdict(doc)
    assert v["direction"] == "overvalued"
    assert "compounder_near_fair_value" not in (v.get("flags") or [])


def test_compounder_flag_uses_is_none_not_or_zero_kelly_still_flags():
    # A real zero-Kelly reading must not silently fall through to `kelly_fraction_pct` via `or`
    # (0.0 is a value). It also must not qualify for the flag (kelly > 0 is part of the test).
    doc = {
        "ticker": "CMPD3", "price": 110.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": 99.0, "early_stop": True,
        "runs": [
            {"sample": 1, "iv": 98.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 100.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {
            "median_iv": 99.0, "median_quality_moat": 4.5, "asymmetric_payoff_skew": 3.5,
            "median_kelly_fraction_pct": 0.0, "kelly_fraction_pct": 15.0,
            "invalidation_rules": VALID_INVALIDATION_RULES,
        }
    }
    v = band_verdict(doc)
    assert v["direction"] == "overvalued"
    assert "compounder_near_fair_value" not in (v.get("flags") or [])


# ---------------------------------------------------------------------------------------------
# FIDUCIARY VERDICT GATE (the final output stage). The handoff of 2026-09-20 lists this as
# implemented in depth_pipeline.py; it was not — `fiduciary_gate.validate_fiduciary_contract`
# was only ever called from `select_medoid_scorecard` and `depth_sanity`. Consequence measured on
# GEV: the verdict published `kelly_fraction_pct: 8.98` beside `mos_vs_median_pct: -1.7`, and the
# only thing that noticed was the read-only auditor, one step AFTER the verdict was published.
# ---------------------------------------------------------------------------------------------
GEV_BAND_RUNS = [
    {"sample": 2, "iv": 1037.88, "plausible": True, "truncated": False},
    {"sample": 3, "iv": 831.19, "plausible": True, "truncated": False},
]


def _gev_doc(scorecard):
    return {
        "ticker": "GEV", "price": 951.04, "samples_run": 3, "early_stop": False,
        "converged": True, "spread_pct": 24.9, "median_iv": 934.535,
        "tolerance_pct": 25.0, "runs": GEV_BAND_RUNS, "scorecard": scorecard,
    }


def test_gate_blocks_position_when_kelly_has_no_margin_of_safety():
    """Kelly > 0 while the contract base sits below the price is not a review comment — it is
    an unallocatable proposal, because Section 12's own edge test is negative."""
    doc = _gev_doc({
        "base_iv": 900.0, "median_iv": 934.535, "median_bull_iv": 1100.0,
        "median_bear_iv": 700.0, "median_kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0, "asymmetric_payoff_skew": 0.77,
    })
    v = band_verdict(doc)
    assert v["fiduciary_verdict"] == "FAIL"
    assert v["kelly_fraction_pct"] == 0.0
    assert v["size_hint"] == "zero"
    assert v["fiduciary_violations"]


def test_gate_blocks_position_on_inverted_scenarios():
    """Bear IV above Base IV is a broken contract, not conservative underwriting."""
    doc = _gev_doc({
        "base_iv": 1037.88, "median_iv": 934.535, "median_bull_iv": 1228.67,
        "median_bear_iv": 1200.0,  # inverted: bear > base
        "median_kelly_fraction_pct": 8.98, "median_quality_moat": 4.0,
    })
    v = band_verdict(doc)
    assert v["fiduciary_verdict"] == "FAIL"
    assert v["kelly_fraction_pct"] == 0.0
    assert v["size_hint"] == "zero"


def test_gate_passes_coherent_contract_and_preserves_kelly():
    """The GEV shape as it SHOULD publish: the medoid owns the base, so its Kelly is legal."""
    doc = _gev_doc({
        "base_iv": 1037.88, "median_iv": 934.535, "median_bull_iv": 1228.67,
        "median_bear_iv": 588.96, "median_kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0, "asymmetric_payoff_skew": 0.77,
        "median_conviction_score": 12.0,
        "reentry_tranches": {"tranche_1_starter": 951.04, "tranche_2_core": 750.0},
        "invalidation_rules": VALID_INVALIDATION_RULES,
    })
    v = band_verdict(doc)
    assert v["fiduciary_verdict"] == "PASS"
    assert v["fiduciary_violations"] == []
    assert v["kelly_fraction_pct"] == 8.98        # legal: base $1,037.88 > price $951.04
    assert v["direction"] == "hold"               # price still inside the band
    # P4.9: size_hint = min(dispersion, mos, conviction, risk). Dispersion alone (spread 24.9%)
    # would allow "half", and conviction 12/15 -> "full", but MoS is (1037.88/951.04-1) = 9.1%,
    # under the 10% half-bucket floor -> mos_bucket "quarter" is the binding constraint here,
    # not the lost third sample.
    assert v["size_hint"] == "quarter"
    assert v["size_components"]["mos"]["bucket"] == "quarter"
    assert v["size_components"]["dispersion"]["bucket"] == "half"
    assert v["size_components"]["conviction"]["bucket"] == "full"
    assert v["size_components"]["risk"]["bucket"] == "full"


def test_mos_is_restated_against_the_contract_base():
    """The verdict must not publish a Kelly from one sample beside a MoS from another."""
    doc = _gev_doc({
        "base_iv": 1037.88, "median_iv": 934.535, "median_bull_iv": 1228.67,
        "median_bear_iv": 588.96, "median_kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0,
    })
    v = band_verdict(doc)
    assert v["mos_vs_base_pct"] == pytest.approx(9.1, abs=0.1)     # from $1,037.88
    assert v["mos_vs_median_pct"] == pytest.approx(-1.7, abs=0.1)  # dispersion anchor, retained
