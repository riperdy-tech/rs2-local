"""tests for Item 1: consensus estimates and revisions in SECTION 8 of the pack."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import capability_test as cap


def _patch_load_json(monkeypatch, overrides):
    import rs2_data
    orig = rs2_data.load_json

    def fake(p):
        for name, value in overrides.items():
            if str(p).endswith(name):
                return value
        return orig(p)

    monkeypatch.setattr(rs2_data, "load_json", fake)


def _slice(pack, header, next_prefix="## "):
    i = pack.find("## " + header)
    assert i != -1, f"section {header!r} not found in pack"
    j = pack.find("\n" + next_prefix, i + 3)
    return pack[i:j if j != -1 else len(pack)]


def test_section_8_consensus_estimates_table_and_trend_revisions(screener_data_stub, monkeypatch):
    en_data = {
        "_ticker": "AMD",
        "_fetched_at": "2026-09-24T12:00:00",
        "estimates": {
            "0y": {
                "revenue": {"avg": 50875836660.0, "low": 48339000000.0, "high": 52659500000.0, "analysts": 49, "growth": 0.4687},
                "eps": {"avg": 7.57578, "low": 7.00, "high": 8.20, "analysts": 49, "growth": 0.8167},
                "eps_trend": {"current": 7.57578, "d7": 7.57578, "d30": 7.56688, "d60": 7.43974, "d90": 7.38350},
                "eps_revisions": {"up7": 1, "up30": 28, "down7": 1, "down30": 9},
            },
            "+1y": {
                "revenue": {"avg": 88076709870.0, "low": 61257000000.0, "high": 116095000000.0, "analysts": 52, "growth": 0.7312},
                "eps": {"avg": 15.57069, "low": 9.60, "high": 20.25, "analysts": 50, "growth": 1.0553},
                "eps_trend": {"current": 15.57069, "d7": 15.57069, "d30": 15.35551, "d60": 13.49207, "d90": 13.16372},
                "eps_revisions": {"up7": 1, "up30": 33, "down7": 0, "down30": 3},
            },
        },
        "analyst_target_low": 350.0,
        "analyst_target_mean": 600.0,
        "analyst_target_median": 610.0,
        "analyst_target_high": 800.0,
        "fifty_two_week_low": 200.0,
        "fifty_two_week_high": 700.0,
    }
    _patch_load_json(monkeypatch, {"AMD.json": en_data})

    pack = cap.build_pack("AMD")
    sec8 = _slice(pack, "SECTION 8 - CONSENSUS & MULTIPLES")

    # The old Consensus forward growth line must be REMOVED
    assert "Consensus forward growth" not in sec8

    # The new CONSENSUS ESTIMATES header and table must be present
    assert "- CONSENSUS ESTIMATES   [yfinance, fetched 2026-09-24; sell-side estimates, not company guidance]" in sec8
    assert "| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | growth |" in sec8
    assert "| current FY | $50.876B | $48.339B | $52.660B | 49 | +46.9% | $7.58 | $7.00 | $8.20 | +81.7% |" in sec8
    assert "| next FY | $88.077B | $61.257B | $116.095B | 52 | +73.1% | $15.57 | $9.60 | $20.25 | +105.5% |" in sec8

    # Trend line
    assert "- Next-FY EPS estimate trend: now $15.57 | 30 days ago $15.36 | 60 days ago $13.49 | 90 days ago $13.16  (+18.3% in 90 days)" in sec8

    # Revisions line
    assert "- Estimate revisions, last 30 days (next FY): 33 up / 3 down  (last 7 days: 1 up / 0 down)" in sec8


def test_section_8_consensus_estimates_missing_enrich(screener_data_stub, monkeypatch):
    _patch_load_json(monkeypatch, {"AMD.json": {}})
    pack = cap.build_pack("AMD")
    sec8 = _slice(pack, "SECTION 8 - CONSENSUS & MULTIPLES")
    assert "- CONSENSUS ESTIMATES: not available \u2014 enrich record missing" in sec8


def test_section_8_consensus_estimates_missing_estimates(screener_data_stub, monkeypatch):
    en_data = {
        "_ticker": "AMD",
        "_fetched_at": "2026-09-24T12:00:00",
        "estimates": None,
    }
    _patch_load_json(monkeypatch, {"AMD.json": en_data})
    pack = cap.build_pack("AMD")
    sec8 = _slice(pack, "SECTION 8 - CONSENSUS & MULTIPLES")
    assert "- CONSENSUS ESTIMATES: not available \u2014 yfinance estimates unavailable" in sec8


def test_section_8_consensus_estimates_staleness_suppression(screener_data_stub, monkeypatch):
    stale_dt = (datetime.now() - timedelta(days=50)).isoformat()
    en_data = {
        "_ticker": "AMD",
        "_fetched_at": stale_dt,
        "estimates": {"0y": {}, "+1y": {}},
    }
    _patch_load_json(monkeypatch, {"AMD.json": en_data})
    pack = cap.build_pack("AMD")
    sec8 = _slice(pack, "SECTION 8 - CONSENSUS & MULTIPLES")
    assert "- CONSENSUS ESTIMATES: not available \u2014 stale (> 45 days)" in sec8


def test_section_8_point_in_time_unchanged(screener_data_stub):
    from datetime import date
    pack = cap.build_pack("GEV", asof=date(2026, 3, 31))
    sec8 = _slice(pack, "SECTION 8 - CONSENSUS & MULTIPLES")
    assert "not available (point-in-time)" in sec8
    assert "CONSENSUS ESTIMATES" not in sec8
