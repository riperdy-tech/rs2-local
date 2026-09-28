"""Reviewer's tests for the brief F review (2026-09-28), one or more per defect fixed.

1. The sibling fetcher's reason names the step that failed (F1.4 "says why"). The build reported
   an unreadable CIK map, an unreadable stocks.csv, a ticker missing from stocks.csv and failed
   sibling fetches all as "no_sibling_in_stocks_csv" or "no_sibling_with_targets". stocks.csv is
   read with utf-8-sig, as depth_gates.producer_class reads it, so a BOM cannot hide every symbol.
2. The pack's share-class line prints the sibling's median or "not available". The build printed
   the mean, or the low-high midpoint, under the median's label.
3. A sibling record whose price_ratio or legs are not numbers is unusable; the build raised
   inside `_consensus_band`. One function (`valuation_backbone._sibling_scaled`) now owns the
   scaling that the band and the pack line used to repeat.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools" / "audit_202608"))

import capability_test as cap  # noqa: E402
import enrich_ticker as et  # noqa: E402
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402

CIK_MAP = {"map": {"MOG-A": "0000067887", "MOG-B": "0000067887", "NVDA": "0001045810"}}
STOCKS = "Symbol,Name,Price\nMOG-A,Moog Inc.,371.68\nMOG-B,Moog  Inc.,374.49\nNVDA,NVIDIA Corporation,120.0\n"


class _Tk:
    def __init__(self, info):
        self.info = info


@pytest.fixture
def screener_dir(tmp_path, monkeypatch):
    d = tmp_path / "screener"
    d.mkdir()
    (d / "cik_map.json").write_text(json.dumps(CIK_MAP), encoding="utf-8")
    (d / "stocks.csv").write_text("﻿" + STOCKS, encoding="utf-8")   # with a BOM
    monkeypatch.setattr(et.paths, "resolve", lambda key, config=None, required=True: d)
    return d


def _sibling_info(sym):
    if sym == "MOG-A":
        return {"currentPrice": 371.68, "targetLowPrice": 350.0, "targetMedianPrice": 400.0,
                "targetMeanPrice": 395.0, "targetHighPrice": 450.0, "numberOfAnalystOpinions": 4}
    raise AssertionError(f"unexpected fetch {sym}")


def test_bom_in_stocks_csv_still_finds_the_sibling(screener_dir, monkeypatch):
    monkeypatch.setattr(et.yf, "Ticker", lambda s: _Tk(_sibling_info(s)))
    rec, why = et.fetch_sibling_targets("MOG-B", {"currentPrice": 374.49})
    assert why is None and rec["ticker"] == "MOG-A"
    assert rec["price_ratio"] == round(374.49 / 371.68, 4)


def test_unreadable_cik_map_is_named(screener_dir, monkeypatch):
    (screener_dir / "cik_map.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(et.yf, "Ticker", lambda s: pytest.fail("no fetch expected"))
    rec, why = et.fetch_sibling_targets("MOG-B", {"currentPrice": 374.49})
    assert rec is None and why.startswith("cik_map_unreadable")


def test_missing_stocks_csv_is_named(screener_dir, monkeypatch):
    (screener_dir / "stocks.csv").unlink()
    rec, why = et.fetch_sibling_targets("MOG-B", {"currentPrice": 374.49})
    assert rec is None and why.startswith("stocks_csv_unreadable")


def test_ticker_missing_from_stocks_csv_is_named(screener_dir, monkeypatch):
    (screener_dir / "stocks.csv").write_text(STOCKS.replace("MOG-B,Moog  Inc.,374.49\n", ""), encoding="utf-8")
    rec, why = et.fetch_sibling_targets("MOG-B", {"currentPrice": 374.49})
    assert rec is None and why == "ticker_not_in_stocks_csv"


def test_ticker_missing_from_cik_map_is_named(screener_dir, monkeypatch):
    rec, why = et.fetch_sibling_targets("ZZZ", {"currentPrice": 1.0})
    assert rec is None and why == "ticker_not_in_cik_map"


def test_failed_sibling_fetch_is_not_no_targets(screener_dir, monkeypatch):
    def boom(s):
        raise ConnectionError("offline")
    monkeypatch.setattr(et.yf, "Ticker", boom)
    rec, why = et.fetch_sibling_targets("MOG-B", {"currentPrice": 374.49})
    assert rec is None and why == "sibling_fetch_failed: MOG-A"


def test_no_same_name_sibling_keeps_its_reason(screener_dir, monkeypatch):
    rec, why = et.fetch_sibling_targets("NVDA", {"currentPrice": 120.0})
    assert rec is None and why == "no_sibling_in_stocks_csv"


@pytest.mark.parametrize("bad", [{"price_ratio": "0.8"}, {"price_ratio": None}, {"price_ratio": True},
                                 {"price_ratio": 0.0}, "not a dict"])
def test_unusable_sibling_record_is_not_a_band(bad, monkeypatch):
    sib = dict(ticker="MOG-A", low=100.0, median=150.0, mean=140.0, high=200.0, count=4,
               fetched_at="2026-09-27T12:00:00+00:00", **bad) if isinstance(bad, dict) else bad
    assert vb._sibling_scaled(sib) is None
    en = {"_fetched_at": "2026-09-27T12:00:00+00:00", "analyst_target_low": None,
          "analyst_target_high": None, "analyst_targets_sibling": sib}
    monkeypatch.setattr(rs2_data, "load_json", lambda p: en if "enrich" in str(p) else None)
    assert vb._consensus_band("MOG-B") is None      # no band, and no exception


def test_sibling_scaled_legs_skip_non_numbers():
    s = vb._sibling_scaled({"price_ratio": 0.5, "low": "100", "median": 150.0, "mean": None, "high": 200.0})
    assert s == {"low": None, "median": 75.0, "mean": None, "high": 100.0}


def test_share_class_line_never_labels_the_mean_as_the_median(screener_data_stub, monkeypatch):
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-27T12:00:00", "analyst_target_low": None,
          "analyst_target_high": None, "analyst_target_median": None, "analyst_target_mean": None,
          "analyst_count": None,
          "analyst_targets_sibling": {"ticker": "GEV-SIB", "price_ratio": 0.8, "low": 100.0,
                                      "median": None, "mean": 140.0, "high": 200.0, "count": 12,
                                      "fetched_at": "2026-09-27T12:00:00"}}
    orig = rs2_data.load_json
    monkeypatch.setattr(rs2_data, "load_json",
                        lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p) else orig(p))
    text = str(cap.build_pack("GEV", include_research=False))
    line = next(l for l in text.splitlines() if l.startswith("- Analyst price targets, share class GEV-SIB"))
    assert "median not available" in line
    assert "112.0" not in line and "120.0" not in line     # 0.8 x the mean, and the midpoint of 80-160
