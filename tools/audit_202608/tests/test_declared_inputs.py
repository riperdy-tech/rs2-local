import json
import pytest
from tools.audit_202608.consensus_valuation import (
    extract_scorecard,
    select_medoid_scorecard,
    extract_desk_snapshot_metrics,
    resolve_anchor_coe,
)
from depth_pipeline import band_verdict


def test_extract_scorecard_whitelists_declared_inputs():
    report = """
# INSTITUTIONAL UNDERWRITING MEMORANDUM

```json:underwriting
{
  "base_iv": 150.0,
  "bull_iv": 200.0,
  "bear_iv": 100.0,
  "base_probability": 0.5,
  "bull_probability": 0.3,
  "bear_probability": 0.2,
  "base_cf_used": 10.5,
  "base_cf_basis": "latest_fy",
  "conviction_score": 12.0,
  "business_quality_moat": 4.5,
  "kelly_fraction_pct": 15.0,
  "asymmetric_payoff_skew": 2.0,
  "reentry_tranches": {"tranche_1_starter": 120.0, "tranche_2_core": 100.0},
  "thesis_invalidation_trigger": "Operating margin drops below 15%",
  "coe_used": 0.088,
  "coe_source": "anchor_adjusted",
  "coe_adjustment_reason": "Low cyclicality in aerospace backlog warrants -50bp loading adjustment",
  "valuation_frame": "equity",
  "terminal_method": "dual_reconciled",
  "terminal_multiple_or_g": 0.025,
  "fade_years": 7,
  "stage1_growth_path": [0.15, 0.12, 0.10, 0.08, 0.06],
  "guidance_deviation_reason": "Management guided 18% in Y1, trimmed to 15% on conservative supply chain assumptions",
  "cycle_evidence": [
    {"indicator": "backlog_coverage_years", "value": 4.2, "date": "2026-06-30", "source": "10-Q"}
  ],
  "verdict_label": "undervalued"
}
```
"""
    price = 120.0
    card = extract_scorecard(report, price)

    assert card["base_iv"] == 150.0
    assert card["coe_used"] == 0.088
    assert card["coe_source"] == "anchor_adjusted"
    assert "aerospace backlog" in card["coe_adjustment_reason"]
    assert card["valuation_frame"] == "equity"
    assert card["terminal_method"] == "dual_reconciled"
    assert card["terminal_multiple_or_g"] == 0.025
    assert card["fade_years"] == 7
    assert card["stage1_growth_path"] == [0.15, 0.12, 0.10, 0.08, 0.06]
    assert "conservative supply chain" in card["guidance_deviation_reason"]
    assert len(card["cycle_evidence"]) == 1
    assert card["cycle_evidence"][0]["indicator"] == "backlog_coverage_years"
    assert card["verdict_label"] == "undervalued"


def test_extract_scorecard_narrative_verdict_label_fallback():
    report = """
Summary of analysis:
Base IV: $125.00
Bull IV: $160.00
Bear IV: $90.00
VERDICT: OVERVALUED
"""
    price = 140.0
    card = extract_scorecard(report, price)
    assert card["verdict_label"] == "overvalued"


def test_extract_desk_snapshot_metrics():
    # 1. No desk calls
    empty_calls = []
    res0 = extract_desk_snapshot_metrics(empty_calls, base_iv=100.0, coe_used=0.09)
    assert res0["desk_calls"] == 0
    assert res0["desk_iv_match"] is False
    assert res0["desk_reverse_neutral_cagr"] is None

    # 2. Single DCF within 1% match
    calls = [
        {
            "tool": "run_financial_model",
            "params": {"price": 100.0, "coe_anchor": 0.087858},
            "result": {
                "dcf_model": {
                    "per_share_iv": 125.0,
                    "per_share_iv_gordon": 125.0,
                    "per_share_iv_exit": 130.0,
                },
                "reverse_dcf": {
                    "neutral_reference_structure": {
                        "implied_10y_cagr_pct": 14.5
                    }
                }
            }
        }
    ]
    # base_iv is 125.5 (0.4% diff -> match)
    res1 = extract_desk_snapshot_metrics(calls, base_iv=125.5, coe_used=0.09)
    assert res1["desk_calls"] == 1
    assert res1["desk_iv_match"] is True
    assert res1["desk_reverse_neutral_cagr"] == 14.5
    assert res1["coe_minus_anchor"] == pytest.approx(0.09 - 0.087858, abs=1e-5)

    # base_iv is 135.0 (> 1% diff -> no match)
    res2 = extract_desk_snapshot_metrics(calls, base_iv=135.0, coe_used=0.09)
    assert res2["desk_iv_match"] is False

    # 3. Blend result match
    blend_calls = [
        {
            "tool": "run_financial_model",
            "params": {"mode": "blend"},
            "result": {
                "mode": "blend",
                "blended_per_share_iv": 142.50,
                "per_share_iv": 142.50
            }
        }
    ]
    res3 = extract_desk_snapshot_metrics(blend_calls, base_iv=142.0)
    assert res3["desk_calls"] == 1
    assert res3["desk_iv_match"] is True


def test_select_medoid_and_band_verdict_carries_declared_inputs():
    price = 100.0
    runs = [
        {
            "sample": 1, "iv": 110.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 110.0, "bull_iv": 150.0, "bear_iv": 80.0,
                "conviction_score": 10.0, "business_quality_moat": 4.0,
                "kelly_fraction_pct": 10.0, "asymmetric_payoff_skew": 2.0,
                "reentry_tranches": {"tranche_1_starter": 95.0, "tranche_2_core": 80.0},
                "coe_used": 0.09,
                "coe_source": "anchor",
                "valuation_frame": "equity",
                "terminal_method": "gordon",
                "terminal_multiple_or_g": 0.025,
                "fade_years": 5,
                "stage1_growth_path": [0.1, 0.09, 0.08, 0.07, 0.06],
                "guidance_deviation_reason": None,
                "cycle_evidence": [{"indicator": "pricing", "value": 1.05}],
                "verdict_label": "undervalued",
                "desk_calls": 2,
                "desk_iv_match": True,
                "desk_reverse_neutral_cagr": 11.2,
                "coe_minus_anchor": 0.002
            }
        }
    ]
    medoid, summary = select_medoid_scorecard(runs, price)
    assert summary["coe_used"] == 0.09
    assert summary["coe_source"] == "anchor"
    assert summary["valuation_frame"] == "equity"
    assert summary["terminal_method"] == "gordon"
    assert summary["fade_years"] == 5
    assert summary["verdict_label"] == "undervalued"
    assert summary["desk_calls"] == 2
    assert summary["desk_iv_match"] is True
    assert summary["desk_reverse_neutral_cagr"] == 11.2
    assert summary["coe_minus_anchor"] == 0.002

    doc = {
        "ticker": "TEST",
        "price": price,
        "runs": runs,
        "scorecard": summary,
        "median_iv": 110.0,
        "spread_pct": 0.0,
        "converged": True,
    }
    verdict = band_verdict(doc)
    assert verdict["coe_used"] == 0.09
    assert verdict["coe_source"] == "anchor"
    assert verdict["valuation_frame"] == "equity"
    assert verdict["terminal_method"] == "gordon"
    assert verdict["fade_years"] == 5
    assert verdict["verdict_label"] == "undervalued"
    assert verdict["desk_calls"] == 2
    assert verdict["desk_iv_match"] is True
    assert verdict["desk_reverse_neutral_cagr"] == 11.2
    assert verdict["coe_minus_anchor"] == 0.002
