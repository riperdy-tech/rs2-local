"""tests for Item 4: scenario order, desk-backed scenarios and market-engagement flags."""
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

from consensus_valuation import check_sample_harness_rules, extract_scorecard, select_medoid_scorecard
import depth_pipeline as dp


def test_scenario_order_violation_and_edges():
    # In order: bear < base < bull -> plausible, no flag
    sc = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 50.0}
    imp, reasons, flags = check_sample_harness_rules(sc, price=100.0)
    assert not imp
    assert "scenario_order_violation" not in flags

    # Edge: bear == base == bull -> in order, plausible, no flag
    sc_equal = {"base_iv": 100.0, "bull_iv": 100.0, "bear_iv": 100.0}
    imp, reasons, flags = check_sample_harness_rules(sc_equal, price=100.0)
    assert not imp
    assert "scenario_order_violation" not in flags

    # Out of order: bear > base
    sc_bear_high = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 120.0}
    imp, reasons, flags = check_sample_harness_rules(sc_bear_high, price=100.0)
    assert imp
    assert "scenario_order_violation" in flags
    assert "scenarios out of order (bear <= base <= bull required)" in reasons

    # Out of order: base > bull
    sc_bull_low = {"base_iv": 100.0, "bull_iv": 80.0, "bear_iv": 50.0}
    imp, reasons, flags = check_sample_harness_rules(sc_bull_low, price=100.0)
    assert imp
    assert "scenario_order_violation" in flags
    assert "scenarios out of order (bear <= base <= bull required)" in reasons

    # Missing one: bear is None -> check does not fire
    sc_partial = {"base_iv": 100.0, "bull_iv": 80.0, "bear_iv": None}
    imp, reasons, flags = check_sample_harness_rules(sc_partial, price=100.0)
    assert not imp
    assert "scenario_order_violation" not in flags


def test_scenario_not_desk_backed_flags():
    # Desk output has 50.0 and 150.0
    desk_info = {"desk_per_share_ivs": [50.0, 100.0, 150.0]}
    sc = {"base_iv": 100.0, "bull_iv": 150.5, "bear_iv": 49.8}  # within 1% of 150 and 50
    imp, reasons, flags = check_sample_harness_rules(sc, price=100.0, desk_info=desk_info)
    assert not imp  # flags only
    assert "scenario_not_desk_backed:bull" not in flags
    assert "scenario_not_desk_backed:bear" not in flags

    # Bull off desk by > 1%
    sc_bull_off = {"base_iv": 100.0, "bull_iv": 160.0, "bear_iv": 50.0}
    imp, reasons, flags = check_sample_harness_rules(sc_bull_off, price=100.0, desk_info=desk_info)
    assert not imp
    assert "scenario_not_desk_backed:bull" in flags
    assert "scenario_not_desk_backed:bear" not in flags

    # Bear off desk by > 1%
    sc_bear_off = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 40.0}
    imp, reasons, flags = check_sample_harness_rules(sc_bear_off, price=100.0, desk_info=desk_info)
    assert not imp
    assert "scenario_not_desk_backed:bull" not in flags
    assert "scenario_not_desk_backed:bear" in flags


def test_bull_below_price_and_bear_above_price_edges():
    price = 100.0

    # Bull < price without reason -> flag
    sc = {"base_iv": 80.0, "bull_iv": 90.0, "bear_iv": 70.0, "bull_below_price_reason": ""}
    imp, reasons, flags = check_sample_harness_rules(sc, price=price)
    assert not imp
    assert "bull_below_price_without_reason" in flags

    # Bull < price with reason -> no flag
    sc_with_reason = {"base_iv": 80.0, "bull_iv": 90.0, "bear_iv": 70.0, "bull_below_price_reason": "Market pricing extreme growth"}
    imp, reasons, flags = check_sample_harness_rules(sc_with_reason, price=price)
    assert "bull_below_price_without_reason" not in flags

    # Edge: Bull == price -> does NOT fire
    sc_equal = {"base_iv": 80.0, "bull_iv": 100.0, "bear_iv": 70.0, "bull_below_price_reason": ""}
    imp, reasons, flags = check_sample_harness_rules(sc_equal, price=price)
    assert "bull_below_price_without_reason" not in flags

    # Bear > price without reason -> flag
    sc_bear = {"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 110.0, "bear_above_price_reason": None}
    imp, reasons, flags = check_sample_harness_rules(sc_bear, price=price)
    assert not imp
    assert "bear_above_price_without_reason" in flags

    # Bear > price with reason -> no flag
    sc_bear_with_reason = {"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 110.0, "bear_above_price_reason": "High contracted backlog floor"}
    imp, reasons, flags = check_sample_harness_rules(sc_bear_with_reason, price=price)
    assert "bear_above_price_without_reason" not in flags

    # Edge: Bear == price -> does NOT fire
    sc_bear_equal = {"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 100.0, "bear_above_price_reason": ""}
    imp, reasons, flags = check_sample_harness_rules(sc_bear_equal, price=price)
    assert "bear_above_price_without_reason" not in flags


def test_bull_below_street_low_without_reason():
    enrich = {"analyst_target_low": 300.0}

    # Bull < street low without reason -> flag
    sc = {"base_iv": 250.0, "bull_iv": 280.0, "bear_iv": 200.0, "bull_below_price_reason": ""}
    imp, reasons, flags = check_sample_harness_rules(sc, price=250.0, enrich_data=enrich)
    assert "bull_below_street_low_without_reason" in flags

    # Bull < street low with reason -> no flag
    sc_reason = {"base_iv": 250.0, "bull_iv": 280.0, "bear_iv": 200.0, "bull_below_price_reason": "Every analyst is ignoring capex digestion"}
    imp, reasons, flags = check_sample_harness_rules(sc_reason, price=250.0, enrich_data=enrich)
    assert "bull_below_street_low_without_reason" not in flags

    # Edge: Bull == street low -> does NOT fire
    sc_equal = {"base_iv": 250.0, "bull_iv": 300.0, "bear_iv": 200.0, "bull_below_price_reason": ""}
    imp, reasons, flags = check_sample_harness_rules(sc_equal, price=250.0, enrich_data=enrich)
    assert "bull_below_street_low_without_reason" not in flags


def test_catalysts_missing_flag():
    # |mom_1m| >= 0.10 and catalysts empty -> flag
    sc_empty_cats = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 50.0, "catalysts": []}
    mom_10 = {"mom_1m": 0.12, "mom_6m": 0.05}
    imp, reasons, flags = check_sample_harness_rules(sc_empty_cats, price=100.0, momentum_state=mom_10)
    assert "catalysts_missing" in flags

    # |mom_6m| >= 0.25 and catalysts None -> flag
    sc_none_cats = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 50.0, "catalysts": None}
    mom_25 = {"mom_1m": 0.02, "mom_6m": -0.30}
    imp, reasons, flags = check_sample_harness_rules(sc_none_cats, price=100.0, momentum_state=mom_25)
    assert "catalysts_missing" in flags

    # catalysts present -> no flag
    sc_has_cats = {
        "base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 50.0,
        "catalysts": [{"date": "2026-09-23", "event": "Muse launch", "direction": "bull"}]
    }
    imp, reasons, flags = check_sample_harness_rules(sc_has_cats, price=100.0, momentum_state=mom_10)
    assert "catalysts_missing" not in flags

    # Momentum unknown (None) -> skip when unknown, no flag
    mom_unknown = {"mom_1m": None, "mom_6m": None}
    imp, reasons, flags = check_sample_harness_rules(sc_empty_cats, price=100.0, momentum_state=mom_unknown)
    assert "catalysts_missing" not in flags

    # Small momentum -> no flag
    mom_small = {"mom_1m": 0.05, "mom_6m": 0.15}
    imp, reasons, flags = check_sample_harness_rules(sc_empty_cats, price=100.0, momentum_state=mom_small)
    assert "catalysts_missing" not in flags


def test_card_keys_and_medoid_and_pipeline_passthrough():
    report = """
# MEMORANDUM
```json:underwriting
{
  "base_iv": 100.0,
  "bull_iv": 150.0,
  "bear_iv": 50.0,
  "base_probability": 0.5,
  "bull_probability": 0.3,
  "bear_probability": 0.2,
  "catalysts": [{"date": "2026-09-23", "event": "Muse agent", "direction": "bull"}],
  "bull_below_price_reason": "Market overestimating TAM",
  "bear_above_price_reason": "Floor underwritten",
  "base_cf_used": 5.0,
  "base_cf_basis": "owner_earnings_default"
}
```
"""
    card = extract_scorecard(report, price=100.0)
    assert card["catalysts"] == [{"date": "2026-09-23", "event": "Muse agent", "direction": "bull"}]
    assert card["bull_below_price_reason"] == "Market overestimating TAM"
    assert card["bear_above_price_reason"] == "Floor underwritten"

    # Medoid pass-through
    runs = [{"sample": 1, "iv": 100.0, "plausible": True, "truncated": False, "scorecard": card, "flags": []}]
    med_card, summary = select_medoid_scorecard(runs, price=100.0, eff_tol=15.0)
    assert summary["catalysts"] == card["catalysts"]
    assert summary["bull_below_price_reason"] == "Market overestimating TAM"
    assert summary["bear_above_price_reason"] == "Floor underwritten"

    # depth_pipeline CONTRACT_PASSTHROUGH and verdict
    built = dp.build_contract(summary)
    assert built["catalysts"] == card["catalysts"]
    assert built["bull_below_price_reason"] == "Market overestimating TAM"
    assert built["bear_above_price_reason"] == "Floor underwritten"

    verdict = dp.band_verdict({"ticker": "TEST", "scorecard": summary, "median_iv": 100.0, "tolerance_pct": 15.0, "price": 100.0})
    assert verdict["catalysts"] == card["catalysts"]
    assert verdict["bull_below_price_reason"] == "Market overestimating TAM"
    assert verdict["bear_above_price_reason"] == "Floor underwritten"
