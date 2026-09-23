"""tests/test_enrich_ticker.py — P4.10/DEP-04: enrich_ticker.py records next_earnings_date from
yfinance's Ticker.calendar. No network: yfinance is monkeypatched throughout.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import enrich_ticker as et  # noqa: E402


# ================================================================================================
# next_earnings_date() — pure, given a `calendar` value
# ================================================================================================

def test_next_earnings_date_dict_shape_future_date():
    future = (date.today() + timedelta(days=20)).isoformat()
    cal = {"Earnings Date": [date.fromisoformat(future)]}
    assert et.next_earnings_date(cal) == future


def test_next_earnings_date_dict_shape_string_date():
    future = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
    cal = {"Earnings Date": [future]}
    assert et.next_earnings_date(cal) == future


def test_next_earnings_date_picks_the_nearest_of_several():
    d1 = date.today() + timedelta(days=40)
    d2 = date.today() + timedelta(days=10)
    cal = {"Earnings Date": [d1, d2]}
    assert et.next_earnings_date(cal) == d2.isoformat()


def test_next_earnings_date_drops_past_dates():
    past = date.today() - timedelta(days=3)
    future = date.today() + timedelta(days=8)
    cal = {"Earnings Date": [past, future]}
    assert et.next_earnings_date(cal) == future.isoformat()


def test_next_earnings_date_all_past_is_none():
    past = date.today() - timedelta(days=3)
    cal = {"Earnings Date": [past]}
    assert et.next_earnings_date(cal) is None


def test_next_earnings_date_none_calendar_is_none():
    assert et.next_earnings_date(None) is None


def test_next_earnings_date_empty_dict_is_none():
    assert et.next_earnings_date({}) is None


def test_next_earnings_date_malformed_entries_are_skipped_not_fatal():
    future = date.today() + timedelta(days=8)
    cal = {"Earnings Date": ["not-a-date", None, future]}
    assert et.next_earnings_date(cal) == future.isoformat()


class _FakeDataFrame:
    """Minimal stand-in for the DataFrame shape yfinance's `Ticker.calendar` sometimes returns —
    only what next_earnings_date() reads: `.index` and `.loc["Earnings Date"]`."""
    def __init__(self, index, values):
        self.index = index
        self._values = values

    @property
    def loc(self):
        return self

    def __getitem__(self, key):
        return self._values[key]


def test_next_earnings_date_dataframe_shape():
    future = date.today() + timedelta(days=12)
    df = _FakeDataFrame(index=["Earnings Date", "Earnings High"],
                        values={"Earnings Date": [future]})
    assert et.next_earnings_date(df) == future.isoformat()


def test_next_earnings_date_unrecognised_shape_is_none():
    assert et.next_earnings_date(object()) is None


# ================================================================================================
# enrich() — full pipeline, yfinance fully monkeypatched (no network)
# ================================================================================================

class _FakeTicker:
    def __init__(self, info=None, calendar=None, options=()):
        self.info = info or {}
        self.calendar = calendar
        self.options = options

    def option_chain(self, exp):
        raise AssertionError("not exercised by this test")


def test_enrich_stamps_next_earnings_date(monkeypatch):
    future = date.today() + timedelta(days=15)
    fake = _FakeTicker(info={}, calendar={"Earnings Date": [future]})
    monkeypatch.setattr(et.yf, "Ticker", lambda t: fake)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None,
                                            "dxy_direction": None})
    data = et.enrich("AAPL")
    assert data["next_earnings_date"] == future.isoformat()


def test_enrich_next_earnings_date_none_when_calendar_raises(monkeypatch):
    class _RaisingCalendar(_FakeTicker):
        @property
        def calendar(self):
            raise RuntimeError("boom")

        @calendar.setter
        def calendar(self, v):
            pass

    fake = _RaisingCalendar(info={})
    monkeypatch.setattr(et.yf, "Ticker", lambda t: fake)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None,
                                            "dxy_direction": None})
    data = et.enrich("AAPL")
    assert data["next_earnings_date"] is None
