"""Revision 19, 10c C9: an undated enrich or openbb record is not read as fresh (it was, through `(_age_days(x) or 0)`)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import capability_test as cap
from test_consensus_estimates import _patch_load_json, _slice

EST = {"0y": {"revenue": {"avg": 5e10, "analysts": 4, "growth": 0.4}, "eps": {"avg": 7.5, "analysts": 4, "growth": 0.5}},
       "+1y": {"revenue": {"avg": 8e10, "analysts": 4, "growth": 0.6}, "eps": {"avg": 15.5, "analysts": 4, "growth": 1.0}}}
STALE_LINE = "- CONSENSUS ESTIMATES: not available \u2014 stale (> 45 days)"


def _sec8(screener_data_stub, monkeypatch, enrich=None, openbb=None):
    over = {}                                                   # openbb first: "AMD.json" is also the end of "openbb_AMD.json"
    if openbb is not None:
        over["openbb_AMD.json"] = openbb
    if enrich is not None:
        over["AMD.json"] = enrich
    _patch_load_json(monkeypatch, over)
    return _slice(cap.build_pack("AMD"), "DATA 8 - CONSENSUS & MULTIPLES")


def test_age_days_and_not_fresh_on_the_four_kinds_of_record():
    now = datetime.now()
    assert cap._age_days({"_fetched_at": now.isoformat()}) == 0 and cap._not_fresh({"_fetched_at": now.isoformat()}) is False
    assert cap._not_fresh({"_fetched_at": (now - timedelta(days=46)).isoformat()}) is True
    assert cap._not_fresh({"_fetched_at": (now - timedelta(days=45)).isoformat()}) is False        # the limit itself is fresh, as before
    assert cap._not_fresh({"estimates": {}}) is True and cap._not_fresh({"_fetched_at": "yesterday"}) is True and cap._not_fresh({"_fetched_at": None}) is True
    assert cap._not_fresh({}) is False and cap._not_fresh(None) is False                          # absent is not "not fresh": the callers say it is missing


def test_an_undated_enrich_record_suppresses_the_consensus_like_a_stale_one(screener_data_stub, monkeypatch):
    sec8 = _sec8(screener_data_stub, monkeypatch, enrich={"_ticker": "AMD", "estimates": EST, "analyst_target_mean": 600.0})
    assert STALE_LINE in sec8 and "| current FY |" not in sec8 and "600" not in sec8


def test_a_dated_enrich_record_still_prints_and_a_missing_one_still_says_so(screener_data_stub, monkeypatch):
    fresh = {"_ticker": "AMD", "_fetched_at": datetime.now().isoformat(), "estimates": EST}
    sec8 = _sec8(screener_data_stub, monkeypatch, enrich=fresh)
    assert STALE_LINE not in sec8 and "| current FY |" in sec8
    assert "- CONSENSUS ESTIMATES: not available \u2014 enrich record missing" in _sec8(screener_data_stub, monkeypatch, enrich={})


def test_an_undated_openbb_record_has_its_values_suppressed(screener_data_stub, monkeypatch):
    fresh_enrich = {"_ticker": "AMD", "_fetched_at": datetime.now().isoformat(), "estimates": EST}
    ob = {"metrics": {"pe_ratio": 22.5, "price_to_book": 3.1}}
    undated = _sec8(screener_data_stub, monkeypatch, enrich=fresh_enrich, openbb=ob)
    dated = _sec8(screener_data_stub, monkeypatch, enrich=fresh_enrich, openbb=dict(ob, _fetched_at=datetime.now().isoformat()))
    assert "Trailing P/E: " + cap.STALE_NULL in undated and "22.5" not in undated
    assert "Trailing P/E: 22.5" in dated
