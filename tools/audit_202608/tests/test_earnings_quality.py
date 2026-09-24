"""Tests for Item 5: EARNINGS QUALITY line in capability_test.py SECTION 3."""
import json
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import capability_test as cap
import rs2_data


def test_earnings_quality_triggers_on_gev_fixture(screener_data_stub):
    """GEV fixture has FY2025 net income $4.884B > operating income $1.388B > 0, triggering EARNINGS QUALITY."""
    pack = cap.build_pack("GEV")
    expected = (
        "- EARNINGS QUALITY: in FY2025 net income ($4.884B) exceeded operating income ($1.388B) \u2014 "
        "non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on "
        "cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. "
        "Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find "
        "it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not "
        "switch to an older fiscal year or to another base because of this line alone."
    )
    assert expected in pack
    sec3 = pack.split("SECTION 3")[1].split("SECTION 4")[0]
    assert expected in sec3


def test_earnings_quality_nvda_like_does_not_trigger(screener_data_stub):
    """NVDA-like where net income < operating income prints nothing."""
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)
    h_data["tickers"]["GEV"]["2025"]["net_income"] = 120000000000
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = 130000000000
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    pack = cap.build_pack("GEV")
    assert "EARNINGS QUALITY" not in pack


def test_earnings_quality_equality_does_not_trigger(screener_data_stub):
    """When net income == operating income, print nothing."""
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)
    h_data["tickers"]["GEV"]["2025"]["net_income"] = 5000000000
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = 5000000000
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    pack = cap.build_pack("GEV")
    assert "EARNINGS QUALITY" not in pack


def test_earnings_quality_negative_or_zero_operating_income_triggers(screener_data_stub):
    """When operating income <= 0 and net income > 0, variant wording triggers."""
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)

    # 1. Negative operating income
    h_data["tickers"]["GEV"]["2025"]["net_income"] = 1000000000
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = -500000000
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    pack_neg = cap.build_pack("GEV")
    expected_neg = (
        "- EARNINGS QUALITY: in FY2025 net income ($1.000B) was positive while operating income was not ($-0.500B) \u2014 "
        "non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on "
        "cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. "
        "Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find "
        "it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not "
        "switch to an older fiscal year or to another base because of this line alone."
    )
    assert expected_neg in pack_neg

    # 2. Zero operating income
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = 0
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    pack_zero = cap.build_pack("GEV")
    expected_zero = (
        "- EARNINGS QUALITY: in FY2025 net income ($1.000B) was positive while operating income was not ($0.000B) \u2014 "
        "non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on "
        "cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. "
        "Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find "
        "it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not "
        "switch to an older fiscal year or to another base because of this line alone."
    )
    assert expected_zero in pack_zero


def test_earnings_quality_missing_figures_do_not_trigger(screener_data_stub):
    """When either figure is missing, print nothing."""
    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)

    # Missing operating income
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = None
    h_path.write_text(json.dumps(h_data), encoding="utf-8")
    assert "EARNINGS QUALITY" not in cap.build_pack("GEV")

    # Missing net income
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = 1388000000
    h_data["tickers"]["GEV"]["2025"]["net_income"] = None
    h_path.write_text(json.dumps(h_data), encoding="utf-8")
    assert "EARNINGS QUALITY" not in cap.build_pack("GEV")


def test_earnings_quality_point_in_time_never_reads_post_asof_year(screener_data_stub, monkeypatch):
    """Point-in-time mode never reads a post-asof fiscal year for EARNINGS QUALITY."""
    from test_point_in_time_pack import _fake_mri_asof, _fake_asof_price_lookup
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch, asof_str="2026-03-31")

    h_path = cap.SD / "fundamentals_history.json"
    h_data = rs2_data.load_json(h_path)

    # FY2025 is clean (net income < operating income)
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = 10000000000
    h_data["tickers"]["GEV"]["2025"]["net_income"] = 5000000000

    # Inject post-asof FY2026 that would trigger if read
    h_data["tickers"]["GEV"]["2026"] = {
        "revenue": 50000000000,
        "operating_income": 1000000000,
        "net_income": 15000000000,
        "da": 5000000000,
        "shares_diluted": 1000000000,
    }
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec3 = pack.split("SECTION 3")[1].split("SECTION 4")[0]
    assert "FY2026" not in sec3
    assert "EARNINGS QUALITY" not in sec3

    # Now make FY2025 trigger
    h_data["tickers"]["GEV"]["2025"]["operating_income"] = 1388000000
    h_data["tickers"]["GEV"]["2025"]["net_income"] = 4884000000
    h_path.write_text(json.dumps(h_data), encoding="utf-8")

    pack_trig = cap.build_pack("GEV", asof="2026-03-31")
    sec3_trig = pack_trig.split("SECTION 3")[1].split("SECTION 4")[0]
    assert "in FY2025 net income ($4.884B) exceeded operating income ($1.388B)" in sec3_trig
    assert "FY2026" not in sec3_trig
