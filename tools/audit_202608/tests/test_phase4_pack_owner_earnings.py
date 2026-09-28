"""Tests for Phase 4 FIX 3: Pack default owner earnings starting cash flow and cash flow quality line."""
import json
import re
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import capability_test as cap
import rs2_data


def _sec3(pack: str) -> str:
    s = re.split(r"##\s*DATA\s*3", pack)[1]
    return re.split(r"##\s*DATA\s*4", s)[0]


def test_owner_earnings_arithmetic_on_fixture(screener_data_stub):
    """Owner earnings line arithmetic correctly computed on GEV fixture."""
    pack = cap.build_pack("GEV")
    # S3 C (brief \u00a75.6/\u00a75.3): result-first, bare numbers (the header carries $B once, \u00a75.7); the
    # "equity frame" sentence is gone (that rule now lives in the DEFAULTS block, \u00a75.2).
    expected = (
        '- [Arithmetic] OWNER EARNINGS 8.681 = TTM net income 9.529 + '
        'D&A (FY2025) 0.853 \u2212 TTM capex 1.701. '
        'Stock compensation is already expensed in net income, so it is counted once '
        '(sbc_treatment "deducted_in_cf"); working-capital swings are excluded.'
    )
    assert expected in pack


def test_owner_earnings_missing_input_lines(screener_data_stub, monkeypatch):
    """Missing input line accurately reports which inputs are missing."""
    ttm_path = cap.SD / "fundamentals_ttm.json"
    ttm_data = rs2_data.load_json(ttm_path)
    # E14: a filed fiscal-year figure or the vendor's capex now fills a missing TTM input (see
    # test_owner_earnings_fallback.py). Remove them so this test still sees the "not available" line.
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)
    for yr in h_data["tickers"]["GEV"]:
        h_data["tickers"]["GEV"][yr]["capex"] = None
        h_data["tickers"]["GEV"][yr]["net_income"] = None
    h_path.write_text(json.dumps(h_data), encoding="utf-8")
    fin_path = cap.SD / "financials" / "GEV.json"
    fin = rs2_data.load_json(fin_path)
    fin["Capital_Expenditure"] = None
    fin_path.write_text(json.dumps(fin), encoding="utf-8")

    # 1. Missing capex
    orig_capex = ttm_data["tickers"]["GEV"]["fields"]["capex"]
    ttm_data["tickers"]["GEV"]["fields"]["capex"] = None
    ttm_path.write_text(json.dumps(ttm_data), encoding="utf-8")
    pack = cap.build_pack("GEV")
    # S3 C (brief \u00a75.6): the label drops "(default base_cf)".
    assert "- OWNER EARNINGS: not available \u2014 TTM capex missing; declare your base and why." in pack

    # 2. Missing net income
    ttm_data["tickers"]["GEV"]["fields"]["capex"] = orig_capex
    ttm_data["tickers"]["GEV"]["fields"]["net_income"] = None
    ttm_path.write_text(json.dumps(ttm_data), encoding="utf-8")
    pack = cap.build_pack("GEV")
    assert "- OWNER EARNINGS: not available \u2014 TTM net income missing; declare your base and why." in pack

    # 3. Missing D&A
    ttm_data["tickers"]["GEV"]["fields"]["net_income"] = 9529000000
    ttm_path.write_text(json.dumps(ttm_data), encoding="utf-8")
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)
    for yr in h_data["tickers"]["GEV"]:
        h_data["tickers"]["GEV"][yr]["da"] = None
    h_path.write_text(json.dumps(h_data), encoding="utf-8")
    pack = cap.build_pack("GEV")
    assert "- OWNER EARNINGS: not available \u2014 D&A missing; declare your base and why." in pack

    # 4. Missing net income and capex (TTM record empty)
    ttm_data["tickers"]["GEV"]["fields"] = {}
    ttm_path.write_text(json.dumps(ttm_data), encoding="utf-8")
    pack = cap.build_pack("GEV")
    assert "- OWNER EARNINGS: not available \u2014 TTM net income, D&A, TTM capex missing; declare your base and why." in pack


def test_cash_flow_quality_line_at_26_pct_and_not_at_24_pct(screener_data_stub, monkeypatch):
    """CASH-FLOW QUALITY line triggers when gap > 25% of (NI + D&A), and does not trigger at 24%."""
    ttm_path = cap.SD / "fundamentals_ttm.json"
    ttm_data = rs2_data.load_json(ttm_path)
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)

    # Set up fixed denominator: NI = $8.0B, D&A = $2.0B -> NI + D&A = $10.0B
    ttm_data["tickers"]["GEV"]["fields"]["net_income"] = 8000000000
    ttm_data["tickers"]["GEV"]["fields"]["capex"] = 1000000000
    h_data["tickers"]["GEV"]["2025"]["da"] = 2000000000
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    # Case 1: 26% gap -> OCF = $12.6B, gap = $2.6B (26% of $10.0B)
    ttm_data["tickers"]["GEV"]["fields"]["ocf"] = 12600000000
    ttm_path.write_text(json.dumps(ttm_data), encoding="utf-8")
    pack_26 = cap.build_pack("GEV")
    expected_quality_26 = (
        "- CASH-FLOW QUALITY: TTM operating cash flow exceeds net income + D&A by "
        "$2.600B (26%). That gap is working capital \u2014 customer prepayments, deposits "
        "or collection timing. It recurs only while advance bookings keep growing: count it as "
        "recurring owner cash flow only if you show it is structural to the business (deposits "
        "that grow with bookings), and never extrapolate a one-off swing. A base built on TTM OCF "
        "or FCF (including the CASH BASIS line) includes it; the OWNER EARNINGS default does not."
    )
    assert expected_quality_26 in pack_26

    # Case 2: 24% gap -> OCF = $12.4B, gap = $2.4B (24% of $10.0B)
    ttm_data["tickers"]["GEV"]["fields"]["ocf"] = 12400000000
    ttm_path.write_text(json.dumps(ttm_data), encoding="utf-8")
    pack_24 = cap.build_pack("GEV")
    assert "CASH-FLOW QUALITY" not in pack_24


def test_point_in_time_never_uses_post_asof_data(screener_data_stub, monkeypatch):
    """Point-in-time mode never uses post-asof figures for D&A or cash flows."""
    from test_point_in_time_pack import _fake_mri_asof, _fake_asof_price_lookup
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch, asof_str="2026-03-31")

    # Inject a post-asof fiscal year FY2026 into fundamentals_history
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)
    h_data["tickers"]["GEV"]["2026"] = {
        "revenue": 50000000000,
        "net_income": 15000000000,
        "da": 5000000000,
        "shares_diluted": 1000000000,
    }
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    # Standard point-in-time pack (no quarterly capex in quarterly file)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    # Must never reference FY2026 post-asof D&A ($5.000B)
    assert "$5.000B" not in pack
    assert "FY2026" not in _sec3(pack)
    # Standard PIT pack missing capex reports missing capex without leak
    # S3 C (brief \u00a75.6): the label drops "(default base_cf)".
    assert "- OWNER EARNINGS: not available (point-in-time) \u2014 TTM capex missing" in pack

    # Now provide quarterly capex in quarterly file for allowed quarters
    q_path = cap.SD / "fundamentals_quarterly.json"
    q_data = rs2_data.load_json(q_path)
    for q in q_data["tickers"]["GEV"]["quarters"]:
        q["capex"] = 500000000  # $0.5B each -> 4 quarters = $2.0B
    q_path.write_text(json.dumps(q_data), encoding="utf-8")

    pack_with_capex = cap.build_pack("GEV", asof="2026-03-31")
    sec3 = _sec3(pack_with_capex)
    # Uses FY2025 D&A (0.853, bare per §5.7), NEVER FY2026 ($5.000B)
    assert "D&A (FY2025) 0.853" in sec3
    assert "FY2026" not in sec3
    assert "$5.000B" not in sec3
