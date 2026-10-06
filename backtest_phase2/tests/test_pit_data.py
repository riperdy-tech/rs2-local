"""C6: split handling in P(T) and shares, the base year, the cover-page count, y_L, and the universe construction on a tiny synthetic world."""
import json
import math
from datetime import date

import pytest

from backtest_phase2 import pit_data
from backtest_phase2.common import (PriceBook, add_months, month_index, split_events, split_in_month, split_product, ym, ym_add)

# ---- months and splits -------------------------------------------------------------------------------------------------------

def test_month_arithmetic():
    assert add_months(date(2016, 6, 30), -15) == date(2015, 3, 30)
    assert add_months(date(2020, 3, 31), -1) == date(2020, 2, 29)
    assert add_months(date(2019, 1, 31), 13) == date(2020, 2, 29)
    assert ym("2016-06-30") == "2016-06" and ym(date(2016, 6, 30)) == "2016-06"
    assert month_index("2017-01") - month_index("2016-12") == 1 and ym_add("2016-11", 3) == "2017-02"


SERIES = {"2016-01": [10.0, 10.0, 0.0, 0.0], "2016-02": [11.0, 11.0, 0.0, 1.5],     # 3-for-2 in Feb 2016
          "2016-04": [12.0, 12.0, 0.0, 2.0],                                            # 2-for-1 in Apr 2016
          "2016-06": [50.0, 49.0, 0.1, 0.0],
          "2017-03": [60.0, 58.0, 0.0, 2.0],                                            # 2-for-1 in Mar 2017 (after T)
          "2019-05": [70.0, 68.0, 0.0, 3.0],                                            # 3-for-1 in May 2019 (after T)
          "2019-06": [71.0, 70.0, 0.0, 0.0]}


def test_split_events_keep_only_real_ratios():
    assert split_events(SERIES) == [("2016-02", 1.5), ("2016-04", 2.0), ("2017-03", 2.0), ("2019-05", 3.0)]
    assert split_events({"2016-01": [1, 1, 0.0, None], "2016-02": [1, 1, 0.0, 0.0]}) == []


def test_price_at_T_undoes_every_split_after_T_and_only_those():
    book = PriceBook({"prices": {"X": SERIES}, "empty_tickers": []})
    # Close(2016-06) = 50 is adjusted for the 2017 and 2019 splits (2 x 3); the price on T was 50 x 2 x 3 = 300
    assert book.price_at_T("X", "2016") == pytest.approx(300.0)
    # a split inside June, on or before T, stays in the Close: no June split is undone
    s2 = dict(SERIES, **{"2016-06": [50.0, 49.0, 0.1, 2.0]})
    assert PriceBook({"prices": {"X": s2}, "empty_tickers": []}).price_at_T("X", "2016") == pytest.approx(300.0)
    assert book.price_at_T("X", "2018") is None                                          # no bar at T: no price


def test_split_product_boundaries_are_strict_after_and_inclusive_up_to():
    ev = split_events(SERIES)
    assert split_product(ev, "2016-02", "2016-06") == 2.0                              # after Feb, up to June: only April's
    assert split_product(ev, "2016-01", "2016-06") == 3.0                              # Feb's 1.5 and April's 2.0
    assert split_product(ev, "2016-06") == 6.0                                         # after T, no upper bound
    assert split_product(ev, "2016-04", "2016-06") == 1.0
    assert split_in_month(ev, "2016-04") and not split_in_month(ev, "2016-05")


def test_has_bar_is_a_presence_test():
    book = PriceBook({"prices": {"X": {"2019-06": [71.0, 70.0, 0.0, 0.0], "2020-06": [None, None, 0.0, 0.0]}}, "empty_tickers": ["E"]})
    assert book.has_bar("X", "2019-06") and not book.has_bar("X", "2020-06") and not book.has_bar("X", "2021-06")
    assert not book.has_ticker("E") and "E" in book.empty


# ---- shares ---------------------------------------------------------------------------------------------------------------------

def test_diluted_shares_apply_only_the_splits_after_the_filing_and_up_to_T():
    ev = split_events(SERIES)
    # a figure filed 2016-02-20: Feb's own split cannot be placed before or after the filing (flagged, not applied);
    # April's 2-for-1 comes after the filing and before T (applied); 2017 and 2019 are after T (not applied)
    adj, ambiguous = pit_data.adjusted_diluted_shares(100.0, "2016-02-20", ev, "2016", "2015-12-31")
    assert adj == pytest.approx(200.0) and ambiguous is True
    adj, ambiguous = pit_data.adjusted_diluted_shares(100.0, "2016-03-05", ev, "2016", "2015-12-31")
    assert adj == pytest.approx(200.0) and ambiguous is False
    adj, _ = pit_data.adjusted_diluted_shares(100.0, "2016-01-15", ev, "2016", "2015-12-31")
    assert adj == pytest.approx(300.0)                                                   # filed before both: both apply
    adj, _ = pit_data.adjusted_diluted_shares(100.0, "2016-05-10", ev, "2016", "2015-12-31")
    assert adj == pytest.approx(100.0)                                                   # filed after both: the filing is already restated


def test_a_filing_already_restates_a_split_made_before_it_was_filed():
    # the registration's reason for using the filing date: a count filed after the split is not multiplied again
    ev = split_events(SERIES)
    late, _ = pit_data.adjusted_diluted_shares(200.0, "2016-05-20", ev, "2016", "2015-12-31")
    assert late == pytest.approx(200.0)


def test_shares_filing_date_prefers_the_exact_value_then_the_period():
    dil = [["WeightedAverageNumberOfDilutedSharesOutstanding", "2015-01-01", "2015-12-31", 100, "2016-02-20", "10-K"],
           ["WeightedAverageNumberOfDilutedSharesOutstanding", "2015-01-01", "2015-12-31", 150, "2016-05-01", "10-K/A"],
           ["WeightedAverageNumberOfDilutedSharesOutstanding", "2014-01-01", "2014-12-31", 90, "2015-02-20", "10-K"]]
    assert pit_data.shares_filing_date(dil, "2015-12-31", 100) == ("2016-02-20", "exact")
    assert pit_data.shares_filing_date(dil, "2015-12-31", 150) == ("2016-05-01", "exact")
    assert pit_data.shares_filing_date(dil, "2015-12-31", 123) == ("2016-05-01", "period_only")
    assert pit_data.shares_filing_date(dil, "2013-12-31", 1) == (None, "unknown")


def test_cover_page_shares_sum_the_classes_of_the_latest_filing_and_apply_later_splits():
    ev = split_events(SERIES)
    cover = [["2016-04-30", 60.0, "a", "10-Q", "2016-05-10"], ["2016-04-30", 40.0, "a", "10-Q", "2016-05-10"]]
    sh, end, ambiguous = pit_data.cover_shares(cover, ev, "2016")
    assert end == "2016-04-30" and ambiguous is True                                     # April's split is in the cover month: flagged
    assert sh == pytest.approx(100.0)                                                    # ... and not applied
    cover = [["2016-03-31", 100.0, "a", "10-Q", "2016-05-10"]]
    sh, end, ambiguous = pit_data.cover_shares(cover, ev, "2016")
    assert sh == pytest.approx(200.0) and not ambiguous                                  # April's 2-for-1 came after the cover date
    assert pit_data.cover_shares([], ev, "2016") == (None, None, False)


# ---- the base year, y_L, the scale slip ----------------------------------------------------------------------------------------

def test_base_year_is_the_latest_year_ended_within_15_months_of_T():
    T = date(2016, 6, 30)
    rows = {"2014": {}, "2015": {}}
    assert pit_data.base_year(rows, {"2014": "2014-12-31", "2015": "2015-12-31"}, T) == (2015, "2015-12-31", None)
    assert pit_data.base_year(rows, {"2015": "2015-03-30"}, T) == (2015, "2015-03-30", None)         # exactly 15 months: inside
    assert pit_data.base_year(rows, {"2015": "2015-03-29"}, T)[2] == "stale"
    assert pit_data.base_year(rows, {}, T)[2] == "no_fiscal_year_end"
    assert pit_data.base_year({}, {}, T)[2] == "no_rows"
    assert pit_data.base_year({"2016": {}}, {"2016": "2016-09-30"}, T)[2] == "stale"                 # cannot end after T


def test_dtb3_mean_covers_the_twelve_months_to_the_fiscal_year_end():
    daily = [["2014-12-31", 0.5], ["2015-01-02", 1.0], ["2015-06-30", 2.0], ["2015-12-31", 3.0], ["2016-01-04", 9.0]]
    assert pit_data.dtb3_mean(daily, "2015-12-31") == pytest.approx(2.0)                # (1 + 2 + 3) / 3: the first date is outside (FYE - 12m, FYE]
    assert pit_data.dtb3_mean([], "2015-12-31") is None


@pytest.mark.parametrize("cover,dil,expect", [
    (1.0e8, 1.0e8, False), (2.0e8, 1.0e8, False), (5.0e9, 1.0e8, False), (9.9e9, 1.0e8, False), (1.0e8, 9.9e9, False),     # up to 99x: valid
    (1.0e10, 1.0e8, True), (1.0e8, 1.0e10, True),                                                                          # exactly 100x either way
    (1.0e11, 1.0e8, True), (1.0e5, 1.0e8, True), (1.0e14, 1.0e8, True), (1.0e8, 1.0e11, True),
    (1.49e11, 1.0e8, True),                                                                                                # the 1,490x case, which no 0.7-1.4 band caught
    (1.0e6, 1.0e8, True), (1.01e6, 1.0e8, False), (1.0e8, 1.01e6, False), (1.0e8, 1.0e7, False),
    (None, 1.0e8, False), (1.0e8, None, False), (1.0e8, 0.0, False)])
def test_share_scale_conflict_is_a_factor_of_100_in_either_direction(cover, dil, expect):
    assert pit_data.share_scale_conflict(cover, dil) is expect


# ---- the tiny synthetic world: universe, collapse, exclusions, the aggregate ------------------------------------------------------

def monthly(close_t, extra=None):
    d = {"2016-06": [close_t, close_t, 0.0, 0.0], "2019-06": [close_t, close_t, 0.0, 0.0]}
    d.update(extra or {})
    return d


def row(rev=2e8, ni=2e7, da=1e7, capex=5e6, shares=1e7, op=3e7, cash=1e7):
    return {"revenue": rev, "net_income": ni, "da": da, "capex": capex, "shares_diluted": shares, "operating_income": op,
            "pretax_income": ni * 1.3, "tax_provision": ni * 0.3, "cash": cash, "equity": 1e8, "current_assets": 5e7, "current_liabilities": 3e7}


def hist_rows(r0, years=range(2008, 2016)):
    return {str(y): dict(r0, revenue=r0["revenue"] * 0.95 ** (2015 - y)) for y in years}


@pytest.fixture()
def world(tmp_path):
    root = tmp_path
    (root / "prices").mkdir()
    (root / "mri").mkdir()
    (root / "pit" / "universe").mkdir(parents=True)
    (root / "pit" / "H_2016").mkdir()
    (root / "pit" / "cut").mkdir()
    prices = {"AAA": monthly(50.0), "AAB": monthly(49.0), "BBB": monthly(10.0), "CCC": monthly(30.0), "DDD": monthly(30.0, {"2019-06": [None, None, 0, 0]}),
              "FFF": monthly(40.0), "NOL": monthly(40.0), "XXX": monthly(20.0)}
    (root / "prices" / "prices_monthly_raw.json").write_text(json.dumps({"meta": {}, "prices": prices, "empty_tickers": ["YHN"]}), encoding="utf-8")
    labels = {t: {"cik": c, "sector": s, "fx": fx, "has_financials_file": True} for t, c, s, fx in [
        ("AAA", "0000000001", "Industrials", None), ("AAB", "0000000001", "Industrials", None),      # two classes of one company
        ("BBB", "0000000002", "Industrials", None),                                                    # market cap below $300M
        ("CCC", "0000000003", "Industrials", None), ("DDD", "0000000004", "Industrials", None),      # DDD: no price at T+36
        ("FFF", "0000000005", "Industrials", "EUR"),                                                   # not a USD reporter
        ("NOL", "0000000006", "Real Estate", None),                                                    # no loading in this world
        ("YHN", "0000000007", "Industrials", None), ("XXX", None, "Industrials", None)]}
    (root / "pit" / "universe" / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    days = [[f"2015-{m:02d}-15", 0.01] for m in range(1, 13)]
    anchors = {"dates": {"2016": {"T": "2016-06-30", "rf": 0.0149, "pi": 0.014, "gA": 0.0325, "dtb3": 0.0026, "dtb3_daily": days,
                                  "raw_loadings": {"industrials": 1.0, "materials": 1.0}, "loadings_reasons": []}}}
    (root / "mri" / "pit_anchors.json").write_text(json.dumps(anchors), encoding="utf-8")
    hist = {}
    big = row()
    hist["AAA"], hist["AAB"] = hist_rows(big), hist_rows(big)
    hist["BBB"] = hist_rows(row(rev=2e8, ni=2e7))
    hist["CCC"] = hist_rows(row(ni=-1e6, da=1e6, capex=1e7))                      # owner earnings negative
    hist["DDD"] = hist_rows(big)
    hist["FFF"] = hist_rows(big)
    hist["NOL"] = hist_rows(big)
    hist["YHN"] = hist_rows(big)
    pe = {t: {str(y): f"{y}-12-31" for y in range(2008, 2016)} for t in hist}
    doc = {"tickers": hist, "provenance": {"period_end": pe, "untagged_fields": {t: ["goodwill", "intangibles_ex_goodwill", "amortization_intangibles"] for t in hist},
                                          "runs": {}, "_tags": []}}
    (root / "pit" / "H_2016" / "fundamentals_history.json").write_text(json.dumps(doc), encoding="utf-8")
    cover = lambda sh: {"k10": True, "cover": [["2016-04-30", sh, "a", "10-Q", "2016-05-10"]],
                        "dil": [["WeightedAverageNumberOfDilutedSharesOutstanding", "2015-01-01", "2015-12-31", 1e7, "2016-02-20", "10-K"]]}
    side = {"0000000001": cover(1e7), "0000000002": cover(1e7), "0000000003": cover(1e7), "0000000004": cover(1e7), "0000000005": cover(1e7),
            "0000000006": cover(1e7), "0000000007": cover(1e7)}
    side["0000000002"]["cover"] = [["2016-04-30", 1e6, "a", "10-Q", "2016-05-10"]]       # 1e6 shares x $10 = $10M: below the floor
    (root / "pit" / "cut" / "side_2016-06-30.json").write_text(json.dumps(side), encoding="utf-8")
    return root


@pytest.fixture()
def ctx(world):
    import pathlib
    tree = pathlib.Path(__file__).resolve().parents[2]
    return pit_data.Context(world, tree)


def test_universe_construction_counts_every_exclusion_by_reason(ctx):
    res = pit_data.build_date(ctx, "2016")
    pre, uni = res["tally_pre_collapse"], res["universe"]
    assert pre["no_cik"] == 1 and pre["fx_not_usd"] == 1 and pre["share_class_duplicate"] == 1
    assert pre["yahoo_no_data"] == 1                                                    # a ticker the download returned nothing for
    by = {n["cik"]: n for n in res["pop"]}
    assert "0000000001" in by and by["0000000001"]["ticker"] == "AAA"                  # the larger class (cap 50 x 1e7) is the company's
    assert uni["cap_below_300M"] == 1                                                   # BBB
    assert uni["no_price_at_T_plus_36"] == 1                                            # DDD has no bar three years on
    assert uni["owner_earnings_not_positive"] == 1                                      # CCC
    assert uni["no_loading"] == 1                                                       # the real-estate name has no loading in this world
    assert uni["U"] == 1 and by["0000000001"]["in_U"]
    assert res["agg_stats"]["share_classes_collapsed"] == 1


def test_a_stale_company_is_counted_not_valued(world, ctx):
    p = world / "pit" / "H_2016" / "fundamentals_history.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["provenance"]["period_end"]["AAA"] = {str(y): f"{y - 1}-12-31" for y in range(2008, 2016)}      # the last year ended 2014-12-31: 18 months before T
    p.write_text(json.dumps(doc), encoding="utf-8")
    res = pit_data.build_date(ctx, "2016")
    assert res["universe"]["L_undefined_stale"] == 1
    assert all(n["cik"] != "0000000001" for n in res["pop"])


def test_aggregate_collapses_classes_and_uses_the_largest_cap(ctx):
    res = pit_data.build_date(ctx, "2016")
    ciks = [c["cik"] for c in res["agg"]["constituents"]]
    assert ciks.count("0000000001") == 1
    c1 = next(c for c in res["agg"]["constituents"] if c["cik"] == "0000000001")
    assert c1["market_cap"] == pytest.approx(50.0 * 1e7)                                # P(T) x cover shares
    assert all("ticker" not in c and "ticker_key" not in c for c in res["agg"]["constituents"])        # company ids only


def test_scale_slip_in_the_cover_count_is_counted_and_the_name_leaves_the_aggregate(world, ctx):
    p = world / "pit" / "cut" / "side_2016-06-30.json"
    side = json.loads(p.read_text(encoding="utf-8"))
    side["0000000001"]["cover"] = [["2016-04-30", 1e10, "a", "10-Q", "2016-05-10"]]     # 1,000 times the filed count
    p.write_text(json.dumps(side), encoding="utf-8")
    res = pit_data.build_date(ctx, "2016")
    assert res["tally_pre_collapse"]["share_count_scale_conflict"] == 2                  # both classes of the company
    assert all(c["cik"] != "0000000001" for c in res["agg"]["constituents"])
    ctx.share_guard = False                                                              # the registration's literal cap(T)
    lit = pit_data.build_date(ctx, "2016")
    top = max(c["market_cap"] for c in lit["agg"]["constituents"])
    assert top == pytest.approx(50.0 * 1e10)


def test_pop_names_carry_the_registered_inputs(ctx):
    res = pit_data.build_date(ctx, "2016")
    n = next(n for n in res["pop"] if n["cik"] == "0000000001")
    assert n["L"] == 2015 and n["fye"] == "2015-12-31"
    assert n["stub_months"] == pytest.approx((date(2016, 6, 30) - date(2015, 12, 31)).days / 30.4375)
    assert n["shares"] == pytest.approx(1e7)                                            # filed 2016-02-20, no split after it up to T
    assert n["raw_beta"] == 1.0 and n["adjL"] == pytest.approx(1.0)
    assert n["y_L"] == pytest.approx(0.01)
    assert n["cap_src"] == "cover" and n["cap"] == pytest.approx(50.0 * 1e7)


def test_a_1490x_cover_count_is_a_conflict_in_the_universe_build(world, ctx):
    p = world / "pit" / "cut" / "side_2016-06-30.json"
    side = json.loads(p.read_text(encoding="utf-8"))
    side["0000000001"]["cover"] = [["2016-04-30", 1.49e10, "a", "10-Q", "2016-05-10"]]
    p.write_text(json.dumps(side), encoding="utf-8")
    res = pit_data.build_date(ctx, "2016")
    assert res["tally_pre_collapse"]["share_count_scale_conflict"] == 2
    assert all(n["cik"] != "0000000001" for n in res["pop"])


def test_a_count_99x_apart_is_still_valued(world, ctx):
    p = world / "pit" / "cut" / "side_2016-06-30.json"
    side = json.loads(p.read_text(encoding="utf-8"))
    side["0000000001"]["cover"] = [["2016-04-30", 9.9e8, "a", "10-Q", "2016-05-10"]]
    p.write_text(json.dumps(side), encoding="utf-8")
    res = pit_data.build_date(ctx, "2016")
    assert "share_count_scale_conflict" not in res["tally_pre_collapse"]
    assert any(n["cik"] == "0000000001" for n in res["pop"])


def _add_split(world, ticker, month, ratio, ctx=None):
    p = world / "prices" / "prices_monthly_raw.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["prices"][ticker][month] = [40.0, 40.0, 0.0, ratio]
    p.write_text(json.dumps(d), encoding="utf-8")
    ctx.book = PriceBook.load(p)                                    # the context read the price file when it was built


def test_a_split_in_the_month_of_the_diluted_share_filing_leaves_the_basis_undetermined(world, ctx):
    _add_split(world, "AAA", "2016-02", 2.0, ctx)                       # the diluted figure was filed 2016-02-20
    _add_split(world, "AAB", "2016-02", 2.0, ctx)
    res = pit_data.build_date(ctx, "2016")
    assert res["tally_pre_collapse"]["share_basis_undetermined"] == 2        # both classes
    assert all(n["cik"] != "0000000001" for n in res["pop"])                  # not valued in any arm
    assert all(c["cik"] != "0000000001" for c in res["agg"]["constituents"])    # and not in the aggregate
    assert res["universe"]["share_basis_undetermined_would_be_in_U"] == 1     # it would have been the one company in the universe
    assert res["universe"].get("U", 0) == 0


def test_a_split_in_the_month_of_the_cover_date_leaves_the_basis_undetermined(world, ctx):
    _add_split(world, "AAA", "2016-04", 2.0, ctx)                       # the cover count is as of 2016-04-30
    res = pit_data.build_date(ctx, "2016")
    assert res["tally_pre_collapse"]["share_basis_undetermined"] == 1
    # the other class of the same company has no split: the company stays, represented by it
    assert any(n["cik"] == "0000000001" and n["ticker"] == "AAB" for n in res["pop"])


def test_a_split_in_a_different_month_is_determined(world, ctx):
    _add_split(world, "AAA", "2016-03", 2.0, ctx)                       # after the filing month, before the cover month
    res = pit_data.build_date(ctx, "2016")
    assert "share_basis_undetermined" not in res["tally_pre_collapse"]
    n = next(n for n in res["pop"] if n["cik"] == "0000000001")
    assert n["shares"] == pytest.approx(2e7)                       # the filing predates the split: applied


def test_literal_build_does_not_apply_the_undetermined_rule(world, ctx):
    _add_split(world, "AAA", "2016-02", 2.0, ctx)
    ctx.share_guard = False
    res = pit_data.build_date(ctx, "2016")
    assert "share_basis_undetermined" not in res["tally_pre_collapse"]


def test_revenue_years_in_the_eight_year_window():
    rows = {str(y): {"revenue": 10.0} for y in range(2008, 2016)}
    assert pit_data.revenue_years(rows, 2015) == 8
    rows["2012"]["revenue"] = None
    rows["2013"]["revenue"] = 0.0                                   # zero is a value but not a revenue year
    assert pit_data.revenue_years(rows, 2015) == 6
    assert pit_data.revenue_years({str(y): {"revenue": 1.0} for y in range(2012, 2016)}, 2015) == 4
    assert pit_data.revenue_years(rows, 2018) == 3                  # the window moves with L: 2011..2018 holds 2011, 2014, 2015
