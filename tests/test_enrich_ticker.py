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


# ================================================================================================
# consensus_estimates() — DataFrame parsing, nulls, exceptions
# ================================================================================================

import pandas as pd


class _FakeEstimatesTicker:
    def __init__(self, earn=None, rev=None, trend=None, revs=None, info=None, calendar=None):
        self.earnings_estimate = earn
        self.revenue_estimate = rev
        self.eps_trend = trend
        self.eps_revisions = revs
        self.info = info or {}
        self.calendar = calendar
        self.options = ()


def test_consensus_estimates_full_dataframe():
    earn_df = pd.DataFrame({
        "avg": [7.57578, 15.57069],
        "low": [7.00, 9.60],
        "high": [8.20, 20.25],
        "numberOfAnalysts": [49, 50],
        "growth": [0.8167, 1.0553],
        "yearAgoEps": [4.17, 7.57578],
    }, index=["0y", "+1y"])

    rev_df = pd.DataFrame({
        "avg": [50875836660.0, 88076709870.0],
        "low": [48339000000.0, 61257000000.0],
        "high": [52659500000.0, 116095000000.0],
        "numberOfAnalysts": [49, 52],
        "growth": [0.4687, 0.7312],
        "yearAgoRevenue": [34639000000.0, 50875836660.0],
    }, index=["0y", "+1y"])

    trend_df = pd.DataFrame({
        "current": [7.57578, 15.57069],
        "7daysAgo": [7.57578, 15.57069],
        "30daysAgo": [7.56688, 15.35551],
        "60daysAgo": [7.43974, 13.49207],
        "90daysAgo": [7.38350, 13.16372],
    }, index=["0y", "+1y"])

    revs_df = pd.DataFrame({
        "upLast7days": [1, 1],
        "upLast30days": [28, 33],
        "downLast30days": [9, 3],
        "downLast7Days": [1, 0],
    }, index=["0y", "+1y"])

    tk = _FakeEstimatesTicker(earn=earn_df, rev=rev_df, trend=trend_df, revs=revs_df)
    res = et.consensus_estimates(tk)

    assert res is not None
    assert "0y" in res and "+1y" in res

    # Check 0y
    assert res["0y"]["revenue"]["avg"] == 50875836660.0
    assert res["0y"]["revenue"]["analysts"] == 49
    assert res["0y"]["eps"]["avg"] == pytest.approx(7.57578)
    assert res["0y"]["eps_trend"]["current"] == pytest.approx(7.57578)
    assert res["0y"]["eps_revisions"]["up30"] == 28

    # Check +1y
    assert res["+1y"]["revenue"]["avg"] == 88076709870.0
    assert res["+1y"]["revenue"]["analysts"] == 52
    assert res["+1y"]["eps"]["avg"] == pytest.approx(15.57069)
    assert res["+1y"]["eps"]["low"] == 9.60
    assert res["+1y"]["eps"]["high"] == 20.25
    assert res["+1y"]["eps_trend"]["current"] == pytest.approx(15.57069)
    assert res["+1y"]["eps_trend"]["d90"] == pytest.approx(13.16372)
    assert res["+1y"]["eps_revisions"]["up30"] == 33
    assert res["+1y"]["eps_revisions"]["down30"] == 3
    assert res["+1y"]["eps_revisions"]["up7"] == 1
    assert res["+1y"]["eps_revisions"]["down7"] == 0


def test_consensus_estimates_nulls_and_nans():
    earn_df = pd.DataFrame({
        "avg": [float("nan"), float("inf")],
        "low": [None, 9.60],
        "high": [8.20, float("-inf")],
        "numberOfAnalysts": [None, 50],
        "growth": [float("nan"), None],
        "yearAgoEps": [None, None],
    }, index=["0y", "+1y"])

    tk = _FakeEstimatesTicker(earn=earn_df)
    res = et.consensus_estimates(tk)
    assert res is not None
    assert res["0y"]["eps"]["avg"] is None
    assert res["0y"]["eps"]["low"] is None
    assert res["+1y"]["eps"]["avg"] is None
    assert res["+1y"]["eps"]["high"] is None
    assert res["+1y"]["eps"]["low"] == 9.60
    assert res["+1y"]["eps"]["analysts"] == 50
    assert res["0y"]["revenue"]["avg"] is None


def test_consensus_estimates_none_or_empty_is_none():
    tk = _FakeEstimatesTicker(earn=None, rev=None, trend=None, revs=None)
    assert et.consensus_estimates(tk) is None


def test_consensus_estimates_exception_returns_none():
    class _RaisingEstimates:
        @property
        def earnings_estimate(self):
            raise RuntimeError("yfinance failed")
    assert et.consensus_estimates(_RaisingEstimates()) is None


def test_enrich_stamps_estimates(monkeypatch):
    earn_df = pd.DataFrame({
        "avg": [7.57578, 15.57069],
        "low": [7.00, 9.60],
        "high": [8.20, 20.25],
        "numberOfAnalysts": [49, 50],
        "growth": [0.8167, 1.0553],
        "yearAgoEps": [4.17, 7.57578],
    }, index=["0y", "+1y"])
    fake = _FakeEstimatesTicker(earn=earn_df)
    monkeypatch.setattr(et.yf, "Ticker", lambda t: fake)
    monkeypatch.setattr(et, "dxy", lambda: {"dxy_level": None, "dxy_1mo_change_pct": None,
                                            "dxy_direction": None})
    data = et.enrich("AMD")
    assert "estimates" in data
    assert data["estimates"] is not None
    assert data["estimates"]["+1y"]["eps"]["avg"] == pytest.approx(15.57069)

