"""tests/test_earnings_window_trigger.py — P4.10/DEP-02: the earnings_window trigger in
depth_triggers.triggers_for() (sourced from enrich/{T}.json's next_earnings_date), plus the pure
_trading_days_until() helper it depends on.

Isolates the SEC (8-K/filing) and live-price (move) blocks — irrelevant to what's under test here
and covered by their own existing behaviour — by stubbing `_cik` to None and `_price_now` to
(None, None), and points ENRICH_DIR at tmp_path so nothing here reads or writes real screener data.
"""
import json
import sys
from datetime import date, timedelta
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


# ---- earnings_window -----------------------------------------------------------------------

def test_earnings_window_fires_within_5_trading_days(tmp_path):
    near = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
    (tmp_path / "enrich" / "AAA.json").write_text(
        json.dumps({"next_earnings_date": near}), encoding="utf-8")
    kinds = _kinds("AAA", _verdict())
    assert "earnings_window" in kinds


def test_earnings_window_absent_beyond_the_window(tmp_path):
    far = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
    (tmp_path / "enrich" / "AAA.json").write_text(
        json.dumps({"next_earnings_date": far}), encoding="utf-8")
    assert "earnings_window" not in _kinds("AAA", _verdict())


def test_earnings_window_absent_when_no_enrich_record():
    assert "earnings_window" not in _kinds("AAA", _verdict())


def test_earnings_window_absent_for_a_past_date(tmp_path):
    past = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    (tmp_path / "enrich" / "AAA.json").write_text(
        json.dumps({"next_earnings_date": past}), encoding="utf-8")
    assert "earnings_window" not in _kinds("AAA", _verdict())


# ---- _trading_days_until — pure helper -------------------------------------------------------

def test_trading_days_until_same_day_is_zero():
    d = date(2026, 9, 24)   # a Thursday
    assert dt._trading_days_until("2026-09-24", today=d) == 0


def test_trading_days_until_skips_weekends():
    # Thursday 2026-09-24 -> Monday 2026-09-28 is 2 trading days (Fri, Mon), not 4 calendar days.
    d = date(2026, 9, 24)
    assert dt._trading_days_until("2026-09-28", today=d) == 2


def test_trading_days_until_past_date_is_none():
    d = date(2026, 9, 24)
    assert dt._trading_days_until("2026-09-20", today=d) is None


def test_trading_days_until_none_or_unparseable_is_none():
    d = date(2026, 9, 24)
    assert dt._trading_days_until(None, today=d) is None
    assert dt._trading_days_until("not-a-date", today=d) is None
