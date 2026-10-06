"""C6 / C2b: the as-of-T aggregate follows the rules of MRI's build_equity_aggregate.py (restated here; nothing is imported across repositories)."""
import json
import os
from pathlib import Path

import pytest

from backtest_phase2 import aggregate as ag


def rows(rev0=100.0, g=0.10, ni=10.0, da=3.0, capex=2.0, years=range(2012, 2018)):
    return {str(y): {"revenue": rev0 * (1 + g) ** (y - years[0]), "net_income": ni, "da": da, "capex": capex} for y in years}


def item(t, cik, cap, r):
    return {"ticker": t, "cik": cik, "market_cap": cap, "rows": r}


def test_revenue_cagr_over_up_to_six_fiscal_years_needs_four_points():
    r = rows(years=range(2008, 2018))                                  # ten years: the CAGR uses the last six (five intervals)
    assert ag.revenue_cagr(r) == pytest.approx(0.10)
    assert ag.revenue_cagr(rows(years=range(2015, 2018))) is None      # three points: not enough
    assert ag.revenue_cagr(rows(years=range(2014, 2018))) == pytest.approx(0.10)    # four points: enough
    r2 = rows(years=range(2012, 2018))
    r2["2014"]["revenue"] = None                                       # a missing year drops a point: the CAGR spans the years that remain
    assert ag.revenue_cagr(r2) == pytest.approx(0.10)


def test_owner_earnings_of_the_latest_year_only_and_zero_is_a_value():
    r = rows()
    assert ag.owner_earnings_latest(r, "2017") == pytest.approx(11.0)
    r["2017"]["capex"] = 0.0
    assert ag.owner_earnings_latest(r, "2017") == pytest.approx(13.0)
    r["2017"]["da"] = None
    assert ag.owner_earnings_latest(r, "2017") is None


def test_classes_collapse_by_company_and_the_largest_cap_wins():
    agg, stats = ag.build_aggregate([item("A1", "C1", 90.0, rows()), item("A2", "C1", 100.0, rows()), item("B", "C2", 50.0, rows())])
    caps = {c["cik"]: c["market_cap"] for c in agg["constituents"]}
    assert caps == {"C1": 100.0, "C2": 50.0}
    assert stats["share_classes_collapsed"] == 1 and stats["names_with_market_cap"] == 3


def test_only_positive_owner_earnings_with_growth_and_a_cap_are_constituents():
    bad_oe = rows(ni=1.0, da=0.0, capex=5.0)
    short = rows(years=range(2016, 2018))
    agg, stats = ag.build_aggregate([item("OK", "1", 10.0, rows()), item("NEG", "2", 20.0, bad_oe), item("SHORT", "3", 30.0, short),
                                     item("NOCAP", "4", 0.0, rows()), item("NONE", "5", None, rows())])
    assert [c["cik"] for c in agg["constituents"]] == ["1"]
    lost = stats["cap_share_lost"]
    assert lost["owner_earnings_not_positive"] == pytest.approx(20.0 / 60.0, abs=1e-4)
    assert lost["revenue_growth_missing"] == pytest.approx(30.0 / 60.0, abs=1e-4)
    assert stats["coverage_share"] == pytest.approx(10.0 / 60.0, abs=1e-4)


def test_growth_is_clamped_to_minus_5_and_plus_35_percent_and_values_are_rounded():
    hi = rows(g=0.80)
    lo = rows(g=-0.30)
    agg, _ = ag.build_aggregate([item("H", "1", 1000.0, hi), item("L", "2", 500.0, lo)])
    g = {c["cik"]: c["growth"] for c in agg["constituents"]}
    assert g == {"1": 0.35, "2": -0.05}
    assert [c["cik"] for c in agg["constituents"]] == ["1", "2"]            # sorted by market cap, largest first


def test_constituents_are_company_ids_and_the_aggregate_has_mris_schema():
    agg, _ = ag.build_aggregate([item("A", "C1", 100.0, rows())], as_of="2016-06-30")
    assert set(agg) >= {"asof", "basis", "growth", "coverage_share", "constituents", "universe_stats"}
    assert agg["basis"] == "universe" and agg["growth"] is None and agg["asof"] == "2016-06-30"
    c = agg["constituents"][0]
    assert set(c) >= {"cik", "cash_flow", "market_cap", "growth"}


MRI_AGG = Path(r"C:/Users/riper/stocks/macro-regime-indicator/data/anchors/equity_aggregate.json")
SD = Path(r"C:/Users/riper/stocks/stock-screener/public/data")


@pytest.mark.skipif(not (MRI_AGG.exists() and (SD / "financials").exists()), reason="MRI's aggregate or the screener data are not on this machine")
def test_restated_rules_reproduce_mris_aggregate_on_todays_inputs():
    from backtest_phase2.checks import c2b_aggregate_rules
    agg, stats = c2b_aggregate_rules(SD)
    mine = {c["ticker_key"]: c for c in agg["constituents"]}
    theirs = {c["ticker"]: c for c in json.loads(MRI_AGG.read_text(encoding="utf-8"))["constituents"]}
    both = [t for t in theirs if t in mine]
    assert len(both) >= 0.98 * len(theirs)                              # the data moved since MRI built its file; the rules did not
    assert sum(1 for t in both if mine[t]["cash_flow"] == theirs[t]["cash_flow"]) >= 0.98 * len(both)
    assert sum(1 for t in both if mine[t]["growth"] == theirs[t]["growth"]) >= 0.98 * len(both)
