"""Tests for P4 T5: SECTION 8.5 peer trailing P/E, computed from live fields.

`peRatio` in stocks.json is measured 0 for every one of 6,949 names on file (capability_test.py
comment, 2026-09-24) - a dead field, not a real trailing P/E of zero. This computes trailing P/E
per cluster peer from fields that DO carry real values instead: price / metrics.epsTtm, falling
back to fundamentals_history.json's latest net_income / shares_diluted only if epsTtm itself is
absent from the corpus's schema.
"""
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import capability_test as cap


def _slice(pack, header, next_prefix="## "):
    i = pack.find("## " + header)
    assert i != -1, f"section {header!r} not found in pack"
    j = pack.find("\n" + next_prefix, i + 3)
    return pack[i:j if j != -1 else len(pack)]


def _patch_load_json(monkeypatch, overrides):
    """overrides: {filename: value}. Every other path falls through to the real loader, exactly
    like the existing SECTION 1.5 / 1.6 fixture tests in test_pack_enrichment.py."""
    import rs2_data
    orig = rs2_data.load_json

    def fake(p):
        for name, value in overrides.items():
            if str(p).endswith(name):
                return value
        return orig(p)

    monkeypatch.setattr(rs2_data, "load_json", fake)


def _factor_scores(cluster_map):
    return {"tickers": {sym: {"cluster": cl} for sym, cl in cluster_map.items()}}


def test_peer_pe_computed_from_eps_ttm_excludes_nonpositive_earnings(screener_data_stub, monkeypatch):
    # The subject ticker (GEV) is itself a member of its own cluster, so it is included in the
    # peer set - that is pre-existing behaviour (unchanged by this fix) and is accounted for
    # below rather than assumed away.
    stocks_list = [
        {"symbol": "GEV", "price": 300.0, "metrics": {"epsTtm": 3.0}, "peRatio": 0},      # 100x
        {"symbol": "PEER1", "price": 100.0, "metrics": {"epsTtm": 10.0}, "peRatio": 0},   # 10x
        {"symbol": "PEER2", "price": 80.0, "metrics": {"epsTtm": 4.0}, "peRatio": 0},     # 20x
        {"symbol": "PEER3", "price": 90.0, "metrics": {"epsTtm": 3.0}, "peRatio": 0},     # 30x
        {"symbol": "PEER4", "price": 50.0, "metrics": {"epsTtm": -2.0}, "peRatio": 0},    # excluded: loss-making
        {"symbol": "PEER5", "price": 60.0, "metrics": {"epsTtm": 0.0}, "peRatio": 0},     # excluded: zero EPS
        {"symbol": "OUTSIDE", "price": 40.0, "metrics": {"epsTtm": 5.0}, "peRatio": 0},   # different cluster
    ]
    _patch_load_json(monkeypatch, {
        "factor_scores.json": _factor_scores(
            {"GEV": "X", "PEER1": "X", "PEER2": "X", "PEER3": "X", "PEER4": "X", "PEER5": "X",
             "OUTSIDE": "Y"}),
        "stocks.json": stocks_list,
    })

    pack = cap.build_pack("GEV")
    sec85 = _slice(pack, "SECTION 8.5 - PEER CONTEXT")

    assert "computed instead from" in sec85 or "epsTtm" in sec85
    # n=4: GEV(100x)/PEER1(10x)/PEER2(20x)/PEER3(30x) -> sorted [10,20,30,100]
    # (PEER4 loss-making, PEER5 zero EPS, OUTSIDE a different cluster all excluded)
    assert "trailing P/E (n=4" in sec85
    assert "median 25.0x" in sec85
    assert "p25 20.0x" in sec85
    assert "p75 100.0x" in sec85
    assert "epsTtm" in sec85  # source is disclosed, not silent


def test_peer_pe_falls_back_to_fundamentals_history_when_eps_ttm_absent(screener_data_stub, monkeypatch):
    # No stocks.json row anywhere carries `metrics.epsTtm` - the field itself is treated as
    # absent from the corpus schema, not merely unpopulated for these particular peers.
    stocks_list = [
        {"symbol": "GEV", "price": 300.0, "metrics": {}, "peRatio": 0},
        {"symbol": "PEER1", "price": 200.0, "metrics": {}, "peRatio": 0},
        {"symbol": "PEER2", "price": 150.0, "metrics": {}, "peRatio": 0},
    ]
    fundamentals_history = {"tickers": {
        "PEER1": {"2024": {"net_income": 100.0, "shares_diluted": 50.0},   # eps 2.0 -> pe 100
                  "2025": {"net_income": 200.0, "shares_diluted": 50.0}},  # eps 4.0 -> pe 50 (latest year wins)
        "PEER2": {"2025": {"net_income": -10.0, "shares_diluted": 20.0}},  # excluded: net loss
    }}
    _patch_load_json(monkeypatch, {
        "factor_scores.json": _factor_scores({"GEV": "X", "PEER1": "X", "PEER2": "X"}),
        "stocks.json": stocks_list,
        "fundamentals_history.json": fundamentals_history,
    })

    pack = cap.build_pack("GEV")
    sec85 = _slice(pack, "SECTION 8.5 - PEER CONTEXT")

    assert "trailing P/E (n=1" in sec85
    assert "median 50.0x" in sec85
    assert "fundamentals_history.json" in sec85


def test_peer_pe_not_available_when_neither_source_has_usable_data(screener_data_stub, monkeypatch):
    stocks_list = [
        {"symbol": "GEV", "price": 300.0, "metrics": {}, "peRatio": 0},
        {"symbol": "PEER1", "price": 200.0, "metrics": {}, "peRatio": 0},
    ]
    _patch_load_json(monkeypatch, {
        "factor_scores.json": _factor_scores({"GEV": "X", "PEER1": "X"}),
        "stocks.json": stocks_list,
        "fundamentals_history.json": {"tickers": {}},
    })

    pack = cap.build_pack("GEV")
    sec85 = _slice(pack, "SECTION 8.5 - PEER CONTEXT")

    assert f"Cluster peers' trailing P/E: {cap.NULL}" in sec85


def test_peer_pe_dead_peratio_field_is_named_not_silently_dropped(screener_data_stub, monkeypatch):
    """The pack must keep saying `peRatio` was checked and found dead - never just go silent
    about it once a computed substitute is available (non-negotiable 3: annotate, never gate)."""
    stocks_list = [
        {"symbol": "GEV", "price": 300.0, "metrics": {"epsTtm": 3.0}, "peRatio": 0},
        {"symbol": "PEER1", "price": 100.0, "metrics": {"epsTtm": 10.0}, "peRatio": 0},
    ]
    _patch_load_json(monkeypatch, {
        "factor_scores.json": _factor_scores({"GEV": "X", "PEER1": "X"}),
        "stocks.json": stocks_list,
    })

    pack = cap.build_pack("GEV")
    sec85 = _slice(pack, "SECTION 8.5 - PEER CONTEXT")

    assert "`peRatio`" in sec85
    assert "measured 0 for every one of" in sec85
