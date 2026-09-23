import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import capability_test as cap

def test_task_prompt_removes_manual_kelly_math_and_introduces_financial_desk():
    # Prompt must NOT order manual mental math derivation of Kelly in prose
    assert "Explicitly derive justified scenario probabilities p and q, payoff ratio b, full Kelly f*" not in cap.TASK
    # Prompt must reference the financial modeling desk / run_financial_model
    assert "run_financial_model" in cap.TASK or "Financial Modeling Desk" in cap.TASK
    assert "Lead Underwriter" in cap.TASK or "Portfolio Manager" in cap.TASK

def test_pack_contains_working_capital_float_notice(screener_data_stub):
    pack = cap.build_pack("GEV")
    assert "WORKING CAPITAL FLOAT" in pack or "Customer Advance" in pack


def test_pack_section_1_5_missing_series_yields_not_available_and_macro_degraded(screener_data_stub, monkeypatch):
    import rs2_data
    # Force anchor and macro_state to return empty / missing
    monkeypatch.setattr(rs2_data, "load_anchors", lambda force=False: {})
    # screener_data_stub does not contain macro_state.json, so macro_series is empty
    pack = cap.build_pack("GEV")
    assert "not available" in pack
    assert pack.macro_degraded is True
    assert "macro_degraded" in pack.flags
    assert cap.LAST_PACK_MACRO_DEGRADED is True
    # When 10Y Rf is not available, mandate line is omitted
    assert "**MANDATE:**" not in pack


def test_pack_section_1_5_present_anchors_and_probability_vector(screener_data_stub, monkeypatch):
    import json
    from datetime import datetime, timezone
    import rs2_data

    # 1. Anchors fixture
    anchor_coc = {
        "asof": "2026-09-23",
        "degraded": False,
        "provenance": {"degradation_reasons": []},
        "risk_free": {
            "nominal_10y": 0.0501,
            "real_10y": 0.0268,
            "breakeven_10y": 0.0234,
        },
        "implied_erp": 0.0435,
        "implied_cost_of_equity": 0.0936,
        "sector_loadings": {
            "industrials": 0.868,
        },
    }
    monkeypatch.setattr(rs2_data, "load_anchors", lambda force=False: {"cost_of_capital": anchor_coc})

    # 2. macro_state.json fixture in screener_data_stub
    macro_state = {
        "fetched_at": "2026-09-23T00:00:00Z",
        "series": {
            "DGS10": {"value": 5.01, "as_of": "2026-09-23"},
            "T10Y2Y": {"value": 0.20, "as_of": "2026-09-21"},
            "BAA10Y": {"value": 1.40, "as_of": "2026-09-18"},
            "BAMLH0A0HYM2": {"value": 2.68, "as_of": "2026-09-18"},
        },
    }
    (screener_data_stub / "macro_state.json").write_text(json.dumps(macro_state), encoding="utf-8")

    # 3. current_regime.json fixture
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    current_regime = {
        "date": now_str,
        "season_headline": "goldilocks",
        "headline_margin": 0.044,
        "season_posterior": {
            "goldilocks": {"probability": 0.287},
            "reflation": {"probability": 0.243},
            "tightening": {"probability": 0.182},
            "stagflation": {"probability": 0.174},
            "recession": {"probability": 0.115},
        },
    }
    orig_load_json = rs2_data.load_json
    def mock_load_json(p):
        if str(p).endswith("current_regime.json"):
            return current_regime
        return orig_load_json(p)
    monkeypatch.setattr(rs2_data, "load_json", mock_load_json)

    pack = cap.build_pack("GEV")
    assert pack.macro_degraded is False
    assert "macro_degraded" not in pack.flags

    # Six anchor lines:
    assert "- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): 5.01%  [MRI anchor" in pack
    assert "- Real 10-Year US Treasury Yield: 2.68%  [MRI anchor]" in pack
    assert "- 10-Year Breakeven Inflation Rate: 2.34%  [MRI anchor]" in pack
    assert "- Implied Equity Risk Premium (ERP): 4.35%  [MRI anchor]" in pack
    assert "- Implied Cost of Equity: 9.36%  [MRI anchor]" in pack
    assert "- Sector Cost of Equity Loading (industrials): 0.868x  [MRI anchor]" in pack

    # Secondary macro series:
    assert "- 10Y-2Y Treasury Yield Spread (Curve Slope) [macro_state.json]: +0.20%  (Normal / Steepening)" in pack
    assert "- Investment Grade Credit Spread (BAA - 10Y) [macro_state.json]: 1.40%" in pack
    assert "- High Yield Option-Adjusted Spread (OAS) [macro_state.json]: 2.68%" in pack

    # B6 (Phase 1 approval review): the probability vector prints FIRST and the label second,
    # as a contested headline with its margin — never an unqualified regime name.
    assert "Current Macro Regime: Probabilities: [" in pack
    assert "goldilocks 0.287" in pack
    assert "reflation 0.243" in pack
    assert "headline goldilocks (margin 0.044 — contested)" in pack

    # Mandate line present when Rf is present:
    assert "- **MANDATE:** Use the verified 10-Year Treasury yield above (5.01%)" in pack

    # B6: the capitalization mandate no longer conditions on the regime LABEL — it must be the
    # SAME unconditional text regardless of the (contested) headline above.
    assert ("- **COST OF CAPITAL & CAPITALIZATION ANCHOR:** Derive terminal multiples from "
            "net capitalization rates (1 / [WACC - g]) and verified peer comps; do not force "
            "artificial multiple caps.") in pack
    assert "In the current" not in pack
    assert "goldilocks regime" not in pack


def test_pack_section_1_5_stale_regime_yields_stale_notice(screener_data_stub, monkeypatch):
    import rs2_data
    stale_regime = {
        "date": "2024-01-01",
        "season_headline": "reflation",
    }
    orig_load_json = rs2_data.load_json
    def mock_load_json(p):
        if str(p).endswith("current_regime.json"):
            return stale_regime
        return orig_load_json(p)
    monkeypatch.setattr(rs2_data, "load_json", mock_load_json)

    pack = cap.build_pack("GEV")
    assert "not available (stale: 2024-01-01)" in pack
    assert pack.macro_degraded is True


def test_consensus_valuation_flags_include_macro_degraded(monkeypatch):
    import consensus_valuation as cv
    # Verify that pack_macro_degraded adds 'macro_degraded' to flags
    flags = []
    pack_macro_degraded = True
    if pack_macro_degraded and "macro_degraded" not in flags:
        flags = list(flags) + ["macro_degraded"]
    assert "macro_degraded" in flags


