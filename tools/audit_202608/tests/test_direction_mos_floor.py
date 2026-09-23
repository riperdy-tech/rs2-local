import pytest
import depth_gates
from depth_pipeline import band_verdict
import tools.audit_202608.depth_sanity as depth_sanity


def test_min_mos_for_direction_constant():
    assert hasattr(depth_gates, "MIN_MOS_FOR_DIRECTION")
    assert depth_gates.MIN_MOS_FOR_DIRECTION == 0.10


def test_direction_undervalued_requires_mos_floor():
    # Base: Price 100.0, IVs [105.0, 108.0], median 106.5
    # Price is below band low (100 < 105), but MoS is (106.5 - 100)/100 = 6.5% < 10% -> must be HOLD!
    doc_narrow = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.8, "median_iv": 106.5,
        "runs": [
            {"sample": 1, "iv": 105.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 108.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 106.5}
    }
    v_narrow = band_verdict(doc_narrow)
    assert v_narrow["direction"] == "hold"

    # Price 100.0, IVs [112.0, 115.0], median 113.5
    # Price is below band low (100 < 112) AND MoS is 13.5% >= 10% -> UNDERVALUED
    doc_sufficient = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.7, "median_iv": 113.5,
        "runs": [
            {"sample": 1, "iv": 112.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 115.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 113.5}
    }
    v_sufficient = band_verdict(doc_sufficient)
    assert v_sufficient["direction"] == "undervalued"


def test_direction_overvalued_requires_mos_floor():
    # Base: Price 100.0, IVs [93.0, 96.0], median 94.5
    # Price is above band high (100 > 96), but MoS is (100 - 94.5)/100 = 5.5% < 10% -> must be HOLD!
    doc_narrow = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 3.2, "median_iv": 94.5,
        "runs": [
            {"sample": 1, "iv": 93.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 96.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 94.5}
    }
    v_narrow = band_verdict(doc_narrow)
    assert v_narrow["direction"] == "hold"

    # Price 100.0, IVs [80.0, 85.0], median 82.5
    # Price is above band high (100 > 85) AND MoS is (100 - 82.5)/100 = 17.5% >= 10% -> OVERVALUED
    doc_sufficient = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 6.2, "median_iv": 82.5,
        "runs": [
            {"sample": 1, "iv": 80.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 85.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 82.5}
    }
    v_sufficient = band_verdict(doc_sufficient)
    assert v_sufficient["direction"] == "overvalued"


def test_report_verdict_mismatch_flag():
    # Case 1: Report claims undervalued, but MoS was only 6% -> recorded direction is hold -> mismatch flag!
    doc1 = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": 106.0,
        "runs": [
            {"sample": 1, "iv": 105.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 107.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 106.0, "verdict_label": "undervalued"}
    }
    v1 = band_verdict(doc1)
    assert v1["direction"] == "hold"
    assert v1["verdict_label"] == "undervalued"
    assert "report_verdict_mismatch" in v1["flags"]

    # Case 2: Report claims fair, recorded direction is hold -> fair ≡ hold -> NO mismatch!
    doc2 = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": 100.0,
        "runs": [
            {"sample": 1, "iv": 98.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 102.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 100.0, "verdict_label": "fair"}
    }
    v2 = band_verdict(doc2)
    assert v2["direction"] == "hold"
    assert v2["verdict_label"] == "fair"
    assert "report_verdict_mismatch" not in v2.get("flags", [])

    # Case 3: Report claims undervalued and recorded direction is undervalued -> NO mismatch!
    doc3 = {
        "ticker": "TEST", "price": 100.0, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": 120.0,
        "runs": [
            {"sample": 1, "iv": 118.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 122.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 120.0, "verdict_label": "undervalued"}
    }
    v3 = band_verdict(doc3)
    assert v3["direction"] == "undervalued"
    assert "report_verdict_mismatch" not in v3.get("flags", [])


def test_depth_sanity_direction_audit_matches_mos_floor():
    # Verdict with price 100, band 105-108, median 106.5, direction 'hold'
    # depth_sanity must NOT warn that price 100 vs 105-108 implies 'undervalued'
    verdict = {
        "ticker": "TEST", "price": 100.0, "direction": "hold",
        "iv_band_low": 105.0, "iv_band_high": 108.0, "median_iv": 106.5,
        "n_basis": 2, "spread_pct": 2.8, "size_hint": "full",
        "run_source": "orchestrator", "scorecard": {"median_iv": 106.5}
    }
    lvl, lines = depth_sanity.audit("TEST", verdict)
    contradictions = [line for line in lines if "contradicts its band" in line]
    assert len(contradictions) == 0
