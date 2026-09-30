import pytest
from tools.audit_202608.depth_sanity import audit

def test_sanity_fails_on_broken_scorecard_monotonicity():
    verdict = {
        "ticker": "BAD", "price": 100.0, "direction": "undervalued",
        "iv_band_low": 120.0, "iv_band_high": 150.0, "n_basis": 2, "spread_pct": 10.0,
        "scorecard": {
            "median_iv": 130.0, "median_bull_iv": 110.0, "median_bear_iv": 140.0  # BROKEN!
        }
    }
    level, lines = audit("BAD", verdict)
    assert level == 2  # FAIL
    assert any("monotonicity" in l.lower() or "bull" in l.lower() for l in lines)

def test_sanity_fails_on_unconverged_undervalued_verdict():
    verdict = {
        "ticker": "DXC", "price": 11.07, "direction": "undervalued",  # ILLEGAL: spread 158%
        "iv_band_low": 17.4, "iv_band_high": 45.0, "n_basis": 2, "spread_pct": 158.6,
        "flags": ["HIGH_DISPERSION_QUARANTINE"], "scorecard": {"median_iv": 17.4}
    }
    level, lines = audit("DXC", verdict)
    assert level == 2  # FAIL
    assert any("dispersion" in l.lower() or "spread" in l.lower() for l in lines)

def test_sanity_warns_on_full_size_with_lost_sample():
    verdict = {
        "ticker": "GTE", "price": 10.0, "direction": "undervalued",
        "iv_band_low": 12.0, "iv_band_high": 13.0, "n_basis": 2, "spread_pct": 8.0,
        "size_hint": "full", "samples_run": 3  # Lost sample!
    }
    level, lines = audit("GTE", verdict)
    assert level >= 1  # WARN
    assert any("lost sample" in l.lower() or "capped at half" in l.lower() for l in lines)


# --- contract base ownership (2026-09-20) ----------------------------------------------------
# The auditor must resolve the fiduciary base the SAME way the pipeline does, or it will flag
# verdicts the pipeline correctly passed (and vice versa). It read `median_iv`, which is the
# cross-sample dispersion statistic, not the contract base.

def _gev_verdict(scorecard):
    return {
        "ticker": "GEV", "price": 951.04, "direction": "hold", "size_hint": "half",
        "iv_band_low": 831.19, "iv_band_high": 1037.88, "n_basis": 2, "spread_pct": 24.9,
        "samples_run": 3, "early_stop": False, "scorecard": scorecard,
    }


def test_sanity_reads_the_contract_base_not_the_median():
    """GEV's coherent shape: the medoid owns the base ($1,037.88 > price), so its Kelly is legal
    even though the cross-sample median ($934.54) sits below the price."""
    level, lines = audit("GEV", _gev_verdict({
        "base_iv": 1037.88, "median_iv": 934.535, "median_bull_iv": 1228.67,
        "median_bear_iv": 588.96, "median_kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0,
    }))
    assert level < 2, lines
    assert not any("fiduciary" in l.lower() for l in lines)


def test_sanity_still_fails_kelly_below_the_contract_base():
    """The same Kelly is illegal when the contract base itself is under the price."""
    level, lines = audit("GEV", _gev_verdict({
        "base_iv": 900.0, "median_iv": 934.535, "median_bull_iv": 1100.0,
        "median_bear_iv": 700.0, "median_kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0,
    }))
    assert level == 2
    assert any("fiduciary" in l.lower() for l in lines)


# --- 0.0 is a value, not an absence ------------------------------------------------------------

def test_a_contract_base_of_0_0_is_audited_as_the_base_not_replaced_by_the_band_low():
    """`contract_base(sc) or lo` read a base of 0.0 as missing and audited against the band's low
    bound ($831.19, above the price) instead: a Kelly on a base of $0 passed. Only None falls back."""
    level, lines = audit("GEV", _gev_verdict({
        "base_iv": 0.0, "median_iv": 934.535, "median_bull_iv": 0.0,
        "median_bear_iv": 0.0, "median_kelly_fraction_pct": 8.98,
    }))
    assert level == 2
    assert any("Kelly fraction" in l and "Base $0.0" in l for l in lines), lines


def test_a_scorecard_with_no_iv_still_falls_back_to_the_band_low():
    """No `base_iv` and no `median_iv` (None): the auditor audits against the band's low bound."""
    level, lines = audit("GEV", _gev_verdict({"median_kelly_fraction_pct": 8.98}))
    assert level == 2
    assert any("Kelly fraction" in l and "Base $831.19" in l for l in lines), lines


def test_a_median_kelly_of_0_0_is_the_kelly_not_a_missing_one():
    """`median_kelly_fraction_pct or kelly_fraction_pct` read a median Kelly of 0.0 as missing and
    took the medoid's 8.98 instead, flagging a base under the price that sized nothing."""
    level, lines = audit("GEV", _gev_verdict({
        "base_iv": 900.0, "median_iv": 934.535, "median_bull_iv": 1100.0,
        "median_bear_iv": 700.0, "median_kelly_fraction_pct": 0.0, "kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0,
    }))
    assert level < 2, lines
    assert not any("fiduciary" in l.lower() for l in lines)


def test_kelly_falls_back_to_the_medoid_field_only_when_the_median_is_absent():
    level, lines = audit("GEV", _gev_verdict({
        "base_iv": 900.0, "median_iv": 934.535, "median_bull_iv": 1100.0,
        "median_bear_iv": 700.0, "kelly_fraction_pct": 8.98,
        "median_quality_moat": 4.0,
    }))
    assert level == 2
    assert any("Kelly fraction 8.98%" in l for l in lines), lines
