"""tests/test_thesis_triggers.py — P4.5/DEP-13: thesis_break and momentum_flip additions to
depth_triggers.triggers_for(), reading thesis_monitor.py's own output (cache/depth_thesis.json).

Isolates the SEC (8-K/filing) and live-price (move) blocks — irrelevant to what's under test here
and covered by their own existing behaviour — by stubbing `_cik` to None and `_price_now` to
(None, None), and points THESIS_CACHE at tmp_path so nothing here reads or writes the real cache/.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import depth_triggers as dt  # noqa: E402

TODAY = date.today().strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(dt, "_cik", lambda t: None)
    monkeypatch.setattr(dt, "_price_now", lambda t: (None, None))
    monkeypatch.setattr(dt, "THESIS_CACHE", tmp_path / "depth_thesis.json")
    monkeypatch.setattr(dt, "ENRICH_DIR", tmp_path / "enrich")
    (tmp_path / "enrich").mkdir()


def _kinds(t, verdict):
    return {k for k, _ in dt.triggers_for(t, verdict)}


def _verdict(**over):
    v = {"ticker": "AAA", "date": TODAY, "pack_revision": dt.cap.PACK_REVISION,
         "entry_timing": None, "price": 100.0}
    v.update(over)
    return v


def test_thesis_break_fires_on_a_breached_record(tmp_path):
    (tmp_path / "depth_thesis.json").write_text(json.dumps({
        "asof": TODAY, "tickers": {"AAA": {
            "thesis_status": "breached",
            "checks": [{"metric": "gross_margin_pct", "breached": True}],
            "entry_timing_now": None, "momentum_flip_met": False}}}), encoding="utf-8")
    kinds = _kinds("AAA", _verdict())
    assert "thesis_break" in kinds
    assert "momentum_flip" not in kinds


def test_thesis_break_absent_on_an_intact_record(tmp_path):
    (tmp_path / "depth_thesis.json").write_text(json.dumps({
        "asof": TODAY, "tickers": {"AAA": {
            "thesis_status": "intact", "checks": [{"metric": "gross_margin_pct", "breached": False}],
            "entry_timing_now": None, "momentum_flip_met": False}}}), encoding="utf-8")
    assert "thesis_break" not in _kinds("AAA", _verdict())


def test_thesis_break_absent_when_no_thesis_cache_file():
    # THESIS_CACHE points at a tmp_path file that was never written — must degrade quietly.
    assert "thesis_break" not in _kinds("AAA", _verdict())


def test_momentum_flip_fires_when_met(tmp_path):
    (tmp_path / "depth_thesis.json").write_text(json.dumps({
        "asof": TODAY, "tickers": {"AAA": {
            "thesis_status": "unknown", "checks": [],
            "entry_timing_now": "buy_now", "momentum_flip_met": True}}}), encoding="utf-8")
    kinds = _kinds("AAA", _verdict(entry_timing="wait_for_momentum"))
    assert "momentum_flip" in kinds
    assert "thesis_break" not in kinds


def test_momentum_flip_absent_when_not_met(tmp_path):
    (tmp_path / "depth_thesis.json").write_text(json.dumps({
        "asof": TODAY, "tickers": {"AAA": {
            "thesis_status": "unknown", "checks": [],
            "entry_timing_now": "wait_for_momentum", "momentum_flip_met": False}}}), encoding="utf-8")
    assert "momentum_flip" not in _kinds("AAA", _verdict(entry_timing="wait_for_momentum"))


def test_thesis_record_for_a_different_ticker_does_not_leak(tmp_path):
    (tmp_path / "depth_thesis.json").write_text(json.dumps({
        "asof": TODAY, "tickers": {"BBB": {
            "thesis_status": "breached", "checks": [], "entry_timing_now": None,
            "momentum_flip_met": True}}}), encoding="utf-8")
    kinds = _kinds("AAA", _verdict())
    assert "thesis_break" not in kinds
    assert "momentum_flip" not in kinds


def test_corrupt_thesis_cache_degrades_quietly(tmp_path):
    (tmp_path / "depth_thesis.json").write_text("{not json", encoding="utf-8")
    assert "thesis_break" not in _kinds("AAA", _verdict())  # no crash
