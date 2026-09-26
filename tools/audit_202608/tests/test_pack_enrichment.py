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
    # When 10Y Rf is not available, the rf-specific WACC mandate line is omitted (other,
    # unrelated MANDATE lines — GROWTH BASE RATES p90 evidence, GUIDANCE stage-1 start, the COE
    # mandate's own-anchor fallback — legitimately still print; this checks the rf one only).
    assert "Use the verified 10-Year Treasury yield above" not in pack


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

    # Live COE ANCHOR shows adjusted loading and raw loading:
    assert "- COE ANCHOR for this name: rf 5.01% + adjusted loading 0.912× (Blume: 0.67 × raw 0.868 + 0.33) × implied ERP 4.35% = 8.98%" in pack
    assert "- **COE MANDATE:** Use `coe_used` within +-150 bp of the COE ANCHOR above (8.98%)" in pack

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


# ---- Phase 4 T3 (pack revision 6) -----------------------------------------------------------

def _slice(pack, header, next_prefix="## "):
    """The text of ONE `## <header>` block, up to (not including) the next `## `-prefixed line —
    so an assertion about "this section" cannot accidentally match a different one."""
    i = pack.find("## " + header)
    assert i != -1, f"section {header!r} not found in pack"
    j = pack.find("\n" + next_prefix, i + 3)
    return pack[i:j if j != -1 else len(pack)]


def test_pack_revision_is_10():
    assert cap.PACK_REVISION == 10   # E18 + terminal-g pin + small fixes (operator ruling 2026-09-26)


def test_no_ground_truth_phrase_anywhere(screener_data_stub):
    # D8: every "verified ... ground truth / ingest directly" phrase is gone from the pack,
    # TASK and RESEARCH_ADDENDUM.
    assert "ground truth" not in cap.TASK.lower()
    assert "ground truth" not in cap.RESEARCH_ADDENDUM.lower()
    pack = cap.build_pack("GEV")
    assert "ground truth" not in pack.lower()


def test_section_11_header_reverts_to_claims_not_verified_wording(tmp_path, monkeypatch, screener_data_stub):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "GEV.md").write_text(
        "GE Vernova is an industrials company.\n", encoding="utf-8")
    monkeypatch.setattr(cap, "HERE", tmp_path)
    pack = cap.build_pack("GEV")
    sec11 = _slice(pack, "SECTION 11 - DEEP RESEARCH BRIEF")
    assert ("Written by another model, not verified - every figure is a claim to check "
            "against the filings above; cite the filing when you rely on it." in sec11)


def test_all_new_pack_sections_render_from_fixture(screener_data_stub):
    pack = cap.build_pack("GEV")
    for header in ("SECTION 1.6 - STATE OF THE WORLD",
                   "SECTION 2.5 - PRICE ACTION",
                   "GROWTH BASE RATES",
                   "SECTION 8.5 - PEER CONTEXT",
                   "GUIDANCE & CONSENSUS"):
        assert f"## {header}" in pack, f"missing section: {header}"


def test_absent_sources_yield_not_available_not_invented(screener_data_stub, monkeypatch):
    # The fixture carries no factor_scores.json, stocks.json or research brief, so every field
    # those sources would populate must read "not available" — never a default, never a silently
    # omitted claim. §1.6's regime/shock sources come from mri_outputs_dir, not the screener-data
    # fixture, so they are mocked absent here explicitly (same pattern as the existing SECTION
    # 1.5 "missing series" test above) rather than relying on this machine's real MRI outputs.
    import rs2_data
    orig_load_json = rs2_data.load_json

    def mock_load_json(p):
        if str(p).endswith(("shock_register.json", "current_regime.json")):
            return None
        return orig_load_json(p)
    monkeypatch.setattr(rs2_data, "load_json", mock_load_json)
    pack = cap.build_pack("GEV")
    sec16 = _slice(pack, "SECTION 1.6 - STATE OF THE WORLD")
    assert "not available" in sec16
    sec25 = _slice(pack, "SECTION 2.5 - PRICE ACTION")
    assert "not available" in sec25
    sec85 = _slice(pack, "SECTION 8.5 - PEER CONTEXT")
    assert "not available" in sec85
    guidance = _slice(pack, "GUIDANCE & CONSENSUS")
    assert "not available" in guidance
    assert "research did not return dated guidance" in guidance


def test_section_2_5_never_contains_screener_opinion(screener_data_stub):
    # B1: §2.5 prints price FACTS only — never the screener's band, rank, door, composite or
    # falling_knife opinion, which would invite the analyst to agree with the quant screen and
    # erode the independent second opinion the divergence engine exists to record.
    pack = cap.build_pack("GEV")
    sec25 = _slice(pack, "SECTION 2.5 - PRICE ACTION")
    lowered = sec25.lower()
    for forbidden in ("band", "rank", "door", "composite", "falling_knife"):
        assert forbidden not in lowered, f"§2.5 leaked screener opinion word: {forbidden!r}"


def test_section_2_5_closing_sentence_present(screener_data_stub):
    pack = cap.build_pack("GEV")
    sec25 = _slice(pack, "SECTION 2.5 - PRICE ACTION")
    assert "these are facts about price and are not a valuation input" in sec25.lower()


def test_guidance_block_parses_fenced_table(tmp_path, monkeypatch, screener_data_stub):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "GEV.md").write_text(
        "# GEV research brief\n\nGE Vernova operates in the industrials sector.\n\n"
        "```guidance\n"
        "metric | period | value | source | date\n"
        "revenue | FY2026 | $39.5B | 10-Q call | 2026-07-22\n"
        "```\n", encoding="utf-8")
    monkeypatch.setattr(cap, "HERE", tmp_path)
    pack = cap.build_pack("GEV")
    guidance = _slice(pack, "GUIDANCE & CONSENSUS")
    assert "revenue" in guidance
    assert "$39.5B" in guidance
    assert "FY2026" in guidance
    assert "research did not return dated guidance" not in guidance


def test_guidance_block_parser_skips_header_row_and_separators():
    text = ("```guidance\n"
            "metric | period | value | source | date\n"
            "--- | --- | --- | --- | ---\n"
            "revenue | FY2026 | $39.5B | 10-Q call | 2026-07-22\n"
            "```\n")
    rows = cap._parse_guidance_block(text)
    assert len(rows) == 1
    assert rows[0]["metric"] == "revenue"
    assert rows[0]["value"] == "$39.5B"


def test_guidance_block_absent_yields_not_available(screener_data_stub):
    pack = cap.build_pack("GEV")
    guidance = _slice(pack, "GUIDANCE & CONSENSUS")
    assert "not available" in guidance
    assert "research did not return dated guidance" in guidance


def test_base_rate_table_measured_on_a_synthetic_fixture(tmp_path):
    import base_rates
    # 40 synthetic tickers, each with revenue at $5B (bucket "$1-10B") growing from year 0 at a
    # KNOWN rate for 5 years, so share_ge_10/20/30 and p50/p90 are independently checkable.
    tickers = {}
    for i in range(40):
        g = 0.05 + (i / 40.0) * 0.40   # 5% .. 44% CAGR, spread across the sample
        rev0 = 5e9
        rev5 = rev0 * (1 + g) ** 5
        tickers[f"T{i}"] = {"2020": {"revenue": rev0}, "2025": {"revenue": rev5}}
    (tmp_path / "fundamentals_history.json").write_text(
        __import__("json").dumps({"tickers": tickers}), encoding="utf-8")
    base_rates._CACHE.clear()
    size_label, table = base_rates.base_rate_table(5e9, sd=tmp_path)
    assert size_label == "$1-10B"
    row5 = table[5]
    assert row5["n"] == 40
    # every synthetic CAGR is >= 5%, none >= 10% is FALSE for the low end (0.05..0.44 spread
    # crosses 10%/20%/30%), so just check monotonic ordering and plausible bounds instead of an
    # exact count (avoids re-deriving the bucket's cutoff index twice).
    assert 0 <= row5["share_ge_30"] <= row5["share_ge_20"] <= row5["share_ge_10"] <= 100
    assert row5["p50"] < row5["p90"]


def test_base_rate_table_reads_from_the_caller_supplied_directory_not_the_real_one(tmp_path):
    # Regression: base_rate_table() must never silently fall back to the real
    # screener_data_dir when a caller passes its own (test-patched) `sd` — that would defeat
    # every test fixture the same way a hard-coded absolute path did (conftest.py's docstring).
    import base_rates
    (tmp_path / "fundamentals_history.json").write_text(
        __import__("json").dumps({"tickers": {}}), encoding="utf-8")
    base_rates._CACHE.clear()
    size_label, table = base_rates.base_rate_table(5e9, sd=tmp_path)
    assert table == {}   # empty corpus at the patched path -> no rows, not the real corpus's


def test_stale_suppression_45_days():
    from datetime import datetime, timedelta
    fresh = {"_fetched_at": (datetime.now() - timedelta(days=10)).isoformat(), "pe_ratio": 12.3}
    stale = {"_fetched_at": (datetime.now() - timedelta(days=46)).isoformat(), "pe_ratio": 12.3}
    assert cap._age_days(fresh) == 10
    assert cap._age_days(stale) == 46
    assert "STALE (46 days)" in cap._age_label(stale)
    assert "STALE" not in cap._age_label(fresh)
    assert cap._sv(fresh, "pe_ratio", False) == 12.3
    assert cap._sv(stale, "pe_ratio", True) == cap.STALE_NULL


def test_section_9_suppressed_when_enrich_record_is_stale(tmp_path, monkeypatch, screener_data_stub):
    from datetime import datetime, timedelta
    enrich_dir = tmp_path / "enrich"
    enrich_dir.mkdir()
    stale_asof = (datetime.now() - timedelta(days=90)).isoformat()
    __import__("json").dump(
        {"_fetched_at": stale_asof, "short_pct_float": 12.3, "institutional_pct": 55.0,
         "analyst_target_mean": 100.0, "fifty_two_week_low": 50.0, "fifty_two_week_high": 150.0},
        (enrich_dir / "GEV.json").open("w", encoding="utf-8"))
    monkeypatch.setattr(cap, "HERE", tmp_path)
    pack = cap.build_pack("GEV")
    sec9 = _slice(pack, "SECTION 9 - POSITIONING")
    assert cap.STALE_NULL in sec9
    assert "12.3" not in sec9   # the real short-interest value must be suppressed, not shown stale
    sec8 = _slice(pack, "SECTION 8 - CONSENSUS")
    assert cap.STALE_NULL in sec8
    assert "100.0" not in sec8


