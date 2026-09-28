"""tools/audit_202608/tests/test_fence_band.py — Tests for Brief F (fence-band outlier resistance & sibling share classes).

Covers:
- _band_legs leg rule (MU, ATAT, boundary at 3x and 6x, unordered, missing median, neither, zero low, 0.0 median).
- Band order & stale shadowing (openbb vs enrich vs sibling).
- Pack printing of sibling line and facts parity.
- Sibling target fetcher in enrich_ticker.py.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import capability_test as cap
import common
import enrich_ticker as et
import pack_facts
import rs2_data
import valuation_backbone as vb


# ================================================================================================
# 1. _band_legs
# ================================================================================================

def test_band_legs_mu_winsorized():
    # MU: low $361, median $1545, high $2200 -> low pulled to $515.00
    legs, why = vb._band_legs(361.0, 1545.0, 2200.0)
    assert why is None
    lo, med, hi, wins = legs
    assert lo == 515.00
    assert med == 1545.0
    assert hi == 2200.0
    assert wins == ["low"]

    # Fence check: [$234.09, $4,000.00]
    fence_lo = round(0.5 * lo / 1.10, 2)
    fence_hi = round(2.0 * hi / 1.10, 2)
    assert fence_lo == 234.09
    assert fence_hi == 4000.00


def test_band_legs_atat_implausible():
    # ATAT reconstruction: low $30, median $35, high $558 -> high / median = 15.9 > 6.0
    legs, why = vb._band_legs(30.0, 35.0, 558.0)
    assert legs is None
    assert why == "band_implausible"


def test_band_legs_exactly_3x_and_just_above_3x():
    # Exactly 3x: med=30, lo=10 -> 30/10 = 3.0 (not > 3.0, not winsorized)
    legs, why = vb._band_legs(10.0, 30.0, 30.0)
    assert why is None
    lo, med, hi, wins = legs
    assert lo == 10.0
    assert wins == []

    # Just above 3x: med=30, lo=9.99 -> 30/9.99 > 3.0, pulled to 30/3 = 10.0
    legs, why = vb._band_legs(9.99, 30.0, 30.0)
    assert why is None
    lo, med, hi, wins = legs
    assert lo == 10.0
    assert wins == ["low"]

    # High exactly 3x: med=30, hi=90 -> 90/30 = 3.0 (not > 3.0)
    legs, why = vb._band_legs(30.0, 30.0, 90.0)
    assert why is None
    lo, med, hi, wins = legs
    assert hi == 90.0
    assert wins == []

    # High just above 3x: med=30, hi=90.03 -> 90.03/30 > 3.0, pulled to 90.0
    legs, why = vb._band_legs(30.0, 30.0, 90.03)
    assert why is None
    lo, med, hi, wins = legs
    assert hi == 90.0
    assert wins == ["high"]


def test_band_legs_exactly_6x_and_just_above_6x():
    # Exactly 6x: med=60, lo=10 -> 60/10 = 6.0 (not > 6.0, plausible, low pulled to 20.0)
    legs, why = vb._band_legs(10.0, 60.0, 60.0)
    assert why is None
    lo, med, hi, wins = legs
    assert lo == 20.0
    assert wins == ["low"]

    # Just above 6x: med=60, lo=9.99 -> 60/9.99 > 6.0 -> implausible
    legs, why = vb._band_legs(9.99, 60.0, 60.0)
    assert legs is None
    assert why == "band_implausible"

    # High just above 6x: med=60, hi=360.06 -> 360.06/60 > 6.0 -> implausible
    legs, why = vb._band_legs(60.0, 60.0, 360.06)
    assert legs is None
    assert why == "band_implausible"


def test_band_legs_unordered():
    # lo > hi
    legs, why = vb._band_legs(50.0, 40.0, 30.0)
    assert legs is None
    assert why == "band_implausible"

    # med < lo
    legs, why = vb._band_legs(50.0, 40.0, 60.0)
    assert legs is None
    assert why == "band_implausible"

    # med > hi
    legs, why = vb._band_legs(30.0, 70.0, 60.0)
    assert legs is None
    assert why == "band_implausible"


def test_band_legs_missing_median_with_mean():
    legs, why = vb._band_legs(10.0, None, 20.0, mean=15.0)
    assert why is None
    lo, med, hi, wins = legs
    assert lo == 10.0
    assert med == 15.0
    assert hi == 20.0
    assert wins == []


def test_band_legs_neither_median_nor_mean():
    # Neither: centre is midpoint (10 + 20) / 2 = 15.0
    legs, why = vb._band_legs(10.0, None, 20.0)
    assert why is None
    lo, med, hi, wins = legs
    assert lo == 10.0
    assert med == 15.0
    assert hi == 20.0
    assert wins == []

    # Neither with hi / lo > 6 -> implausible
    legs, why = vb._band_legs(10.0, None, 70.0)
    assert legs is None
    assert why == "band_implausible"


def test_band_legs_zero_low():
    legs, why = vb._band_legs(0.0, 15.0, 20.0)
    assert legs is None
    assert why == "no_targets"

    legs, why = vb._band_legs(None, 15.0, 20.0)
    assert legs is None
    assert why == "no_targets"


def test_band_legs_median_zero_unordered_implausible():
    # Median 0.0 is a value, not absence; 0.0 is outside [10, 20], so unordered -> implausible
    legs, why = vb._band_legs(10.0, 0.0, 20.0)
    assert legs is None
    assert why == "band_implausible"


# ================================================================================================
# 2. Band Order & Stale Shadowing
# ================================================================================================

def test_stale_openbb_does_not_shadow_fresh_enrich(monkeypatch):
    t = "TEST_SHADOW"
    now_iso = datetime.now(timezone.utc).isoformat()
    # openbb is 60 days old (> 45 days stale)
    stale_dt = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 60 * 86400, tz=timezone.utc).isoformat()

    ob_data = {
        "_fetched_at": stale_dt,
        "analyst_consensus": {"target_low": 10.0, "target_median": 15.0, "target_high": 20.0, "number_of_analysts": 5}
    }
    en_data = {
        "_ticker": t,
        "_fetched_at": now_iso,
        "analyst_target_low": 20.0, "analyst_target_median": 25.0, "analyst_target_high": 30.0, "analyst_count": 8
    }

    def mock_load(p):
        sp = str(p)
        if f"openbb_{t}.json" in sp:
            return ob_data
        if f"{t}.json" in sp and "enrich" in sp:
            return en_data
        return None

    monkeypatch.setattr(rs2_data, "load_json", mock_load)

    band = vb._consensus_band(t)
    assert band is not None
    assert band["source"] == "enrich"
    assert band["stale"] is False
    assert band["low"] == 20.0
    assert band["high"] == 30.0


def test_when_all_stale_freshest_returns_stale(monkeypatch):
    t = "TEST_ALL_STALE"
    ts_60d = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 60 * 86400, tz=timezone.utc).isoformat()
    ts_50d = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 50 * 86400, tz=timezone.utc).isoformat()

    ob_data = {
        "_fetched_at": ts_60d,
        "analyst_consensus": {"target_low": 10.0, "target_median": 15.0, "target_high": 20.0, "number_of_analysts": 5}
    }
    en_data = {
        "_ticker": t,
        "_fetched_at": ts_50d,  # freshest between 60d and 50d
        "analyst_target_low": 20.0, "analyst_target_median": 25.0, "analyst_target_high": 30.0, "analyst_count": 8
    }

    def mock_load(p):
        sp = str(p)
        if f"openbb_{t}.json" in sp:
            return ob_data
        if f"{t}.json" in sp and "enrich" in sp:
            return en_data
        return None

    monkeypatch.setattr(rs2_data, "load_json", mock_load)

    band = vb._consensus_band(t)
    assert band is not None
    assert band["source"] == "enrich"
    assert band["stale"] is True
    assert band["age_days"] == pytest.approx(50.0, abs=0.5)


def test_sibling_record_scaled_and_source_named(monkeypatch):
    t = "MOG-B"
    now_iso = datetime.now(timezone.utc).isoformat()

    en_data = {
        "_ticker": t,
        "_fetched_at": now_iso,
        "analyst_target_low": None,
        "analyst_target_high": None,
        "analyst_targets_sibling": {
            "ticker": "MOG-A",
            "price_ratio": 0.5,
            "low": 100.0,
            "median": 150.0,
            "mean": 145.0,
            "high": 200.0,
            "count": 10,
            "fetched_at": now_iso,
        }
    }

    def mock_load(p):
        sp = str(p)
        if f"openbb_{t}.json" in sp:
            return None
        if f"{t}.json" in sp and "enrich" in sp:
            return en_data
        return None

    monkeypatch.setattr(rs2_data, "load_json", mock_load)

    band = vb._consensus_band(t)
    assert band is not None
    assert band["source"] == "enrich_sibling:MOG-A"
    assert band["low"] == 50.0
    assert band["median"] == 75.0
    assert band["high"] == 100.0
    assert band["raw_low"] == 50.0
    assert band["raw_high"] == 100.0
    assert band["winsorized"] == []
    assert band["n"] == 10

    fence = vb.street_fence(t)
    assert fence is not None
    assert fence["source"] == "enrich_sibling:MOG-A"
    assert fence["low"] == round(0.5 * 50.0 / 1.10, 2)
    assert fence["high"] == round(2.0 * 100.0 / 1.10, 2)
    assert fence["winsorized"] == []


# ================================================================================================
# 3. Pack: Sibling Line & Facts Parity
# ================================================================================================

def test_pack_sibling_line_and_facts_parity(screener_data_stub, monkeypatch):
    # Base enrich record with missing own targets but usable sibling targets
    now_iso = "2026-09-27T12:00:00"
    en = {
        "_ticker": "GEV",
        "_fetched_at": now_iso,
        "analyst_target_low": None,
        "analyst_target_high": None,
        "analyst_target_median": None,
        "analyst_target_mean": None,
        "analyst_count": None,
        "fifty_two_week_low": 150.0,
        "fifty_two_week_high": 350.0,
        "analyst_targets_sibling": {
            "ticker": "GEV-SIB",
            "price_ratio": 0.8000,
            "low": 100.0,
            "median": 150.0,
            "mean": 140.0,
            "high": 200.0,
            "count": 12,
            "fetched_at": now_iso,
        },
    }

    orig_load = rs2_data.load_json
    monkeypatch.setattr(
        rs2_data,
        "load_json",
        lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p) else orig_load(p),
    )

    pack = cap.build_pack("GEV", include_research=False)
    text = str(pack)

    # Verify regular line is followed by sibling line
    lines = text.splitlines()
    target_idx = next(i for i, l in enumerate(lines) if l.startswith("- Analyst price targets:"))
    sib_line = lines[target_idx + 1]

    expected_prefix = (
        "- Analyst price targets, share class GEV-SIB (this class has none; scaled by the price ratio 0.8000): "
        "low 80.0 / median 120.0 / high 160.0   [Aggregator - 12 analysts, "
    )
    assert sib_line.startswith(expected_prefix), f"Line was: {sib_line}"

    # Verify facts parity
    parsed_facts = pack_facts.from_text(text)
    assert pack_facts.parity(pack.facts, parsed_facts) == []


# ================================================================================================
# 4. Fetcher (enrich_ticker.py)
# ================================================================================================

class _StubTicker:
    def __init__(self, sym, info):
        self.sym = sym
        self.info = info or {}
        self.calendar = None
        self.options = ()


def test_fetcher_own_targets_present_no_sibling_fetched(monkeypatch):
    # When own targets are present, yf.Ticker must never be called for any sibling
    calls = []

    def stub_ticker(s):
        calls.append(s)
        return _StubTicker(s, {
            "currentPrice": 100.0,
            "targetLowPrice": 80.0,
            "targetHighPrice": 120.0,
            "targetMedianPrice": 100.0,
        })

    monkeypatch.setattr(et.yf, "Ticker", stub_ticker)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None, "dxy_direction": None})

    data = et.enrich("MOG-B")
    assert calls == ["MOG-B"]
    assert data.get("analyst_targets_sibling") is None


def test_fetcher_own_targets_missing_sibling_with_targets(monkeypatch):
    calls = []

    def stub_ticker(s):
        calls.append(s)
        if s == "MOG-B":
            return _StubTicker(s, {
                "currentPrice": 371.68,
                "targetLowPrice": None,
                "targetHighPrice": None,
            })
        if s == "MOG-A":
            return _StubTicker(s, {
                "currentPrice": 374.49,
                "targetLowPrice": 350.0,
                "targetMedianPrice": 400.0,
                "targetMeanPrice": 395.0,
                "targetHighPrice": 450.0,
                "numberOfAnalystOpinions": 8,
            })
        raise AssertionError(f"unexpected ticker: {s}")

    monkeypatch.setattr(et.yf, "Ticker", stub_ticker)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None, "dxy_direction": None})

    data = et.enrich("MOG-B")
    assert "MOG-A" in calls
    sib = data.get("analyst_targets_sibling")
    assert sib is not None
    assert sib["ticker"] == "MOG-A"
    assert sib["price_ratio"] == round(371.68 / 374.49, 4)
    assert sib["low"] == 350.0
    assert sib["median"] == 400.0
    assert sib["mean"] == 395.0
    assert sib["high"] == 450.0
    assert sib["count"] == 8


def test_fetcher_no_sibling_in_stocks_csv(monkeypatch):
    # NVDA shares no CIK with common share class siblings in stocks.csv
    def stub_ticker(s):
        return _StubTicker(s, {
            "currentPrice": 120.0,
            "targetLowPrice": None,
            "targetHighPrice": None,
        })

    monkeypatch.setattr(et.yf, "Ticker", stub_ticker)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None, "dxy_direction": None})

    data = et.enrich("NVDA")
    assert data.get("analyst_targets_sibling") is None
    assert data.get("analyst_targets_sibling_reason") == "no_sibling_in_stocks_csv"


def test_fetcher_sibling_without_usable_price(monkeypatch):
    # Sibling MOG-A has targets, but missing price
    def stub_ticker(s):
        if s == "MOG-B":
            return _StubTicker(s, {
                "currentPrice": 371.68,
                "targetLowPrice": None,
                "targetHighPrice": None,
            })
        if s == "MOG-A":
            return _StubTicker(s, {
                "currentPrice": None,
                "regularMarketPrice": None,
                "targetLowPrice": 350.0,
                "targetHighPrice": 450.0,
                "numberOfAnalystOpinions": 8,
            })
        raise AssertionError(f"unexpected ticker: {s}")

    monkeypatch.setattr(et.yf, "Ticker", stub_ticker)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None, "dxy_direction": None})

    data = et.enrich("MOG-B")
    assert data.get("analyst_targets_sibling") is None
    assert data.get("analyst_targets_sibling_reason") == "no_usable_price"
