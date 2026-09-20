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
