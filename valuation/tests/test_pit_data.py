"""Tests of the point-in-time layer on synthetic companyfacts (no network, no archive)."""
import json
from pathlib import Path

import pytest

from valuation import pit_data as pdm
from valuation.pit_data import PitData, Panel, MonthlyRawPriceSource, DailyPriceSource, AdjustedOnlyMonthlySource, to_date
from valuation.tests import synth


def pit_with(tmp_path, price=None, id_map=None):
    return PitData(tmp_path / "store", price_source=price, id_map=id_map)


def test_filing_counts_only_strictly_before_the_date(tmp_path):
    facts = synth.annual_report("2019-12-31", "2020-03-02", {"Revenues": 100.0, "Assets": 50.0})
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert pit.fiscal_years("1", "2020-03-02") == {}                      # the filing day itself: not before the date
    assert list(pit.fiscal_years("1", "2020-03-03")) == ["2019-12-31"]
    assert pit.snapshot("1", "2020-03-03").L == 2019


def test_inputs_are_as_known_and_outcomes_are_first_filed(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0}, comparatives={"2019-12-31": {"Revenues": 90.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    known = pit.fiscal_years("1", "2021-06-01")                              # input rule: the latest filing known at the date
    assert known["2019-12-31"].cells["revenue"].val == 90.0
    assert pit.fiscal_years("1", "2020-06-01")["2019-12-31"].cells["revenue"].val == 100.0       # before the restatement was filed
    first = pit.fiscal_years("1", "2021-06-01", mode="first_filed")          # outcome rule: the first value reported, never the restated one
    assert first["2019-12-31"].cells["revenue"].val == 100.0
    assert pit.outcome_fiscal_years("1")["2019-12-31"].cells["revenue"].val == 100.0
    marked = pit.company_pit("1", "2021-06-01")
    assert marked.provenance[("revenue", "2019-12-31")] == "RESTATED" and marked.provenance[("revenue", "2020-12-31")] == "PIT_VALID"
    assert marked.series["revenue"]["2019-12-31"].value == 90.0 and marked.series["revenue"]["2019-12-31"].filed == "2021-03-01"


def test_a_restatement_filed_after_the_date_is_invisible(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0}, comparatives={"2019-12-31": {"Revenues": 90.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    a = pit.rows("1", "2020-12-31")
    facts2 = facts + synth.annual_report("2021-12-31", "2022-03-01", {"Revenues": 130.0}, comparatives={"2019-12-31": {"Revenues": 80.0}})
    synth.write_company(tmp_path / "store2", 1, facts2)
    b = PitData(tmp_path / "store2").rows("1", "2020-12-31")
    assert a == b                                                         # filings after the date change nothing


def test_a_fiscal_year_exists_only_from_its_own_filing(tmp_path):
    # FY2018 is only a comparative column of the FY2019 report (an IPO company: its pre-IPO year was in an S-1, which is never read)
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "Assets": 60.0}, comparatives={"2018-12-31": {"Revenues": 80.0, "Assets": 50.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert list(pit.fiscal_years("1", "2020-06-01")) == ["2019-12-31"]
    assert list(pit.fiscal_years("1", "2020-02-01")) == []                  # and nothing before the first annual report
    assert list(pit.outcome_fiscal_years("1")) == ["2019-12-31"]            # not even with no cutoff: the comparative is never read


def test_only_annual_forms_count_and_s1_data_is_never_stored(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2018-12-31", "2019-01-15", {"Revenues": 999.0}, form="S-1") +
             synth.annual_report("2019-09-30", "2019-11-01", {"Revenues": 777.0}, form="10-Q"))
    obj = {"cik": 1, "entityName": "x", "facts": {"us-gaap": {}}}
    for taxo, tag, unit, start, end, val, accn, filed, form in facts:
        obj["facts"]["us-gaap"].setdefault(tag, {"units": {}})["units"].setdefault(unit, []).append(
            {"start": start, "end": end, "val": val, "accn": accn, "filed": filed, "form": form})
    doc = pdm.compact_company(obj)
    forms = {r[5] for units in doc["facts"]["us-gaap"].values() for rows in units.values() for r in rows}
    assert forms == {"10-K"}
    flat = [[t, tag, u, *r] for t, tags in doc["facts"].items() for tag, units in tags.items() for u, rows in units.items() for r in rows]
    synth.write_company(tmp_path / "store", 1, [[f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8]] for f in flat])
    assert list(pit_with(tmp_path).fiscal_years("1", "2021-01-01")) == ["2019-12-31"]


def test_an_amendment_eligible_at_the_date_replaces_the_original_one_filed_later_is_invisible(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "Assets": 50.0}) +
             synth.annual_report("2019-12-31", "2020-09-01", {"Revenues": 95.0, "Assets": 50.0}, form="10-K/A"))      # a full restating amendment
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert pit.fiscal_years("1", "2020-12-01")["2019-12-31"].cells["revenue"].val == 95.0        # the 10-K/A is known: it replaces the 10-K
    assert pit.fiscal_years("1", "2020-06-01")["2019-12-31"].cells["revenue"].val == 100.0       # filed after the date: invisible
    assert pit.fiscal_years("1", "2020-12-01", mode="first_filed")["2019-12-31"].cells["revenue"].val == 100.0
    synth.write_company(tmp_path / "store", 2, synth.annual_report("2019-12-31", "2020-09-01", {"Revenues": 95.0}, form="10-K/A"))
    fy = pit.fiscal_years("2", "2021-01-01")["2019-12-31"]
    assert fy.cells["revenue"].val == 95.0 and "from_amendment" in fy.cells["revenue"].flags
    assert "own_filing_is_amendment" in fy.stamps


def test_the_production_extractors_tag_backfill_reads_a_year_whose_own_report_used_the_old_tag(tmp_path):
    # ASC 606: FY2019's own report files SalesRevenueNet, FY2020's files Revenues and restates FY2019 (99) under the new tag.
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"SalesRevenueNet": 100.0, "Assets": 50.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0, "Assets": 55.0}, comparatives={"2019-12-31": {"Revenues": 99.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    known = pit.fiscal_years("1", "2021-06-01")
    assert (known["2019-12-31"].cells["revenue"].val, known["2019-12-31"].cells["revenue"].tag) == (99.0, "Revenues")      # as known: the restated column
    first = pit.fiscal_years("1", "2021-06-01", mode="first_filed")
    c19 = first["2019-12-31"].cells["revenue"]
    assert (c19.val, c19.tag, c19.filed) == (100.0, "SalesRevenueNet", "2020-03-01")      # first filed: the production ladder backfills the year the winner lacks
    assert first["2020-12-31"].cells["revenue"].val == 120.0


def test_the_production_scale_correction_applies_to_first_filed_values(tmp_path):
    facts = []
    for i, y in enumerate(range(2013, 2020)):
        rev = 1_000_000.0 * (1.05 ** i) * (0.001 if y == 2016 else 1.0)           # FY2016 filed in thousands: a clean power of 1000 below the latest year's scale
        facts += synth.annual_report(f"{y}-12-31", f"{y + 1}-03-01", {"Revenues": rev, "Assets": 2_000_000.0})
    synth.write_company(tmp_path / "store", 1, facts)
    rows = pit_with(tmp_path).rows("1", "2021-01-01")
    assert abs(rows[2016]["revenue"] - 1_000_000.0 * 1.05 ** 3) < 1.0


def test_zero_is_a_value_and_a_non_usd_reporter_is_carried_in_its_own_currency_and_stamped(tmp_path):
    facts = synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "GrossProfit": 0.0, "Assets": 50.0})
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert pit.rows("1", "2021-01-01")[2019]["gross_profit"] == 0.0
    eur = synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "Assets": 50.0}, unit="EUR")
    synth.write_company(tmp_path / "store", 2, eur)
    snap = pit.snapshot("2", "2021-01-01")
    assert snap.currency == "EUR" and snap.rows()[2019]["revenue"] == 100.0           # EUR, not dollars
    assert "reporting_currency:EUR" in snap.years["2019-12-31"].stamps
    cp = PitData(tmp_path / "store", price_source=DailyPriceSource({"E": {"2021-01-04": {"close": 5.0, "adj": 5.0}}}), id_map={"E": "2"})
    assert cp.market_cap("2", "2021-01-04", "E")["reason"] == "reporting_currency_not_usd"


def test_cover_shares_take_the_latest_filing_before_the_date_and_sum_the_classes(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             [synth.cover("2020-02-20", "2020-03-01", 700.0, form="10-K", accn="a"), synth.cover("2020-02-20", "2020-03-01", 300.0, form="10-K", accn="a"),
              synth.cover("2020-04-20", "2020-05-05", 1100.0, form="10-Q", accn="b")])
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert pit.snapshot("1", "2020-05-05").cover["value"] == 1000.0       # the 10-Q filed the same day is not before the date
    assert pit.snapshot("1", "2020-05-06").cover["value"] == 1100.0
    assert pit.snapshot("1", "2020-03-01").cover is None


def test_outcome_years_are_first_filed_and_a_gap_is_not_bridged(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "OperatingIncomeLoss": 20.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 110.0, "OperatingIncomeLoss": 22.0}, comparatives={"2019-12-31": {"Revenues": 90.0}}) +
             synth.annual_report("2022-12-31", "2023-03-01", {"Revenues": 150.0}))      # FY2021's report is missing
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    from rebuild_harness import outcomes
    fo = outcomes.fundamental_outcomes(pit, "1", "2019-12-31", ks=(1, 2, 3))
    assert fo[1]["measures"]["revenue"] == 110.0 and fo[1]["filed"] == "2021-03-01"
    assert fo[2] is None and fo[3] is None                                  # FY2021 missing: the chain stops


def test_panel_view_equals_direct_read(tmp_path):
    for cik in (1, 2, 3):
        synth.simple_company(tmp_path / "store", cik, 8, base_rev=100 + 10 * cik, growth=0.05 * cik)
    pit = pit_with(tmp_path)
    panel = Panel(pit, ["1", "2", "3"], ("revenue", "net_income"))
    for asof in ("2017-06-30", "2019-03-15", "2022-12-31"):
        view = panel.asof(asof)
        for cik in ("1", "2", "3"):
            c = cik.zfill(10)
            direct = pit.rows(cik, asof)
            got = view.get(c, {})
            assert set(got) == set(direct)
            for y in direct:
                assert got[y].get("revenue") == direct[y]["revenue"]


def test_universe_counts_reasons(tmp_path):
    synth.simple_company(tmp_path / "store", 1, 5)
    synth.write_company(tmp_path / "store", 2, synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 1.0}))
    pit = pit_with(tmp_path)
    keep, why = pit.universe("2019-06-30", ["1", "2", "99"])
    assert keep == ["0000000001"] and why == {"no_annual_report_before_date": 1, "not_in_archive": 1}


# ---- prices ---------------------------------------------------------------------------------------------------------------------------

def monthly_doc():
    return {"prices": {"AAA": {"2019-12": [50.0, 45.0, 0.0, None], "2020-01": [52.0, 47.0, 0.0, None],
                               "2020-02": [30.0, 28.0, 0.0, 0.5], "2020-03": [32.0, 30.0, 0.0, None]}}}


def test_monthly_source_unadjusted_close_undoes_later_splits_only():
    src = MonthlyRawPriceSource(monthly_doc())
    assert src.close_unadjusted("AAA", "2020-01-31").price == 52.0 * 0.5   # the Feb 1-for-2 reverse split is after Jan: the traded Jan price was 26
    assert src.close_unadjusted("AAA", "2020-03-31").price == 32.0
    p = src.close_unadjusted("AAA", "2020-02-28")
    assert "split_in_bar_month" in p.flags
    assert src.close_unadjusted("AAA", "2020-03-15") is None              # not a month end: refused, never filled
    assert src.adj_close("AAA", "2020-01-31").price == 47.0


def test_daily_source_serves_the_bar_or_a_recent_earlier_one():
    src = DailyPriceSource({"A": {"2020-03-02": {"close": 10.0, "adj": 9.0}}}, splits={"A": [("2020-05-01", 2.0)]}, max_gap_days=3)
    assert src.close_unadjusted("A", "2020-03-02").price == 10.0
    p = src.close_unadjusted("A", "2020-03-04")
    assert p.price == 10.0 and "stale_bar" in p.flags
    assert src.close_unadjusted("A", "2020-03-10") is None
    assert src.splits("A") == [("2020-05-01", 2.0)]


def test_adjusted_only_source_is_marked_proxy():
    src = AdjustedOnlyMonthlySource({"prices": {"A": {"2020-03": 10.0}}})
    assert src.basis == "adjusted_proxy" and src.splits("A") is None
    assert "PROXY_adjusted_close" in src.close_unadjusted("A", "2020-03-31").flags


def _cap_pit(tmp_path, price_doc, cover_vals, dil=100.0, splits=None, ticker="AAA"):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2019-12-31", "2020-03-01", {"WeightedAverageNumberOfDilutedSharesOutstanding": dil}, unit="shares", accn="sh") +
             cover_vals)
    synth.write_company(tmp_path / "store", 1, facts)
    src = DailyPriceSource({ticker: {d: {"close": c, "adj": c} for d, c in price_doc.items()}}, splits=splits or {})
    return PitData(tmp_path / "store", price_source=src, id_map={ticker: "1"})


def test_market_cap_puts_cover_shares_on_the_traded_basis(tmp_path):
    cov = [synth.cover("2020-02-20", "2020-03-01", 100.0, form="10-K", accn="c1")]
    pit = _cap_pit(tmp_path, {"2020-06-30": 10.0}, cov, splits={"AAA": [("2020-05-01", 2.0)]})
    mc = pit.market_cap("1", "2020-06-30", "AAA")
    assert mc["shares"] == 200.0 and mc["market_cap"] == 2000.0           # the 2-for-1 after the cover date: 100 pre-split shares are 200 now
    pit2 = _cap_pit(tmp_path / "b", {"2020-06-30": 10.0}, cov, splits={"AAA": [("2020-01-01", 2.0)]})
    assert pit2.market_cap("1", "2020-06-30", "AAA")["shares"] == 100.0   # a split before the cover date is already in the count


def test_market_cap_refuses_a_scale_slip_and_an_undetermined_basis(tmp_path):
    cov = [synth.cover("2020-02-20", "2020-03-01", 15000.0, form="10-K", accn="c1")]          # 150x the filed 100: not a power of 1000
    pit = _cap_pit(tmp_path, {"2020-06-30": 10.0}, cov)
    assert pit.market_cap("1", "2020-06-30", "AAA")["reason"] == "share_count_scale_conflict"
    cov = [synth.cover("2020-02-20", "2020-03-01", 100.0, form="10-K", accn="c1")]
    pit = _cap_pit(tmp_path / "u", {"2020-06-30": 10.0}, cov, splits={"AAA": [("2020-02-20", 2.0)]})
    assert pit.market_cap("1", "2020-06-30", "AAA")["reason"] == "share_basis_undetermined"


def test_market_cap_without_split_events_is_flagged_not_a_result(tmp_path):
    cov = [synth.cover("2020-02-20", "2020-03-01", 100.0, form="10-K", accn="c1")]
    synth.write_company(tmp_path / "store", 1, synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) + cov)
    pit = PitData(tmp_path / "store", price_source=AdjustedOnlyMonthlySource({"prices": {"AAA": {"2020-06": 10.0}}}), id_map={"AAA": "1"})
    mc = pit.market_cap("1", "2020-06-30", "AAA")
    assert "splits_unknown" in mc["flags"] and "market_cap_not_on_traded_basis" in mc["flags"] and mc["price_basis"] == "adjusted_proxy"


def test_price_after_the_date_is_not_visible_to_the_close(tmp_path):
    cov = [synth.cover("2020-02-20", "2020-03-01", 100.0, form="10-K", accn="c1")]
    pit = _cap_pit(tmp_path, {"2020-06-30": 10.0, "2020-07-01": 999.0}, cov)
    assert pit.market_cap("1", "2020-06-30", "AAA")["price"] == 10.0


def test_a_quarter_end_balance_inside_an_annual_report_does_not_create_a_fiscal_year(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "Assets": 50.0}) +
             [["us-gaap", "Assets", "USD", None, "2019-06-30", 40.0, "acc-x", "2020-03-01", "10-K"]])
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert list(pit.fiscal_years("1", "2021-01-01")) == ["2019-12-31"]
    assert pit.fiscal_years("1", "2021-01-01")["2019-12-31"].cells["total_assets"].val == 50.0


def test_a_52_week_year_end_within_ten_days_is_the_same_fiscal_year(tmp_path):
    facts = (synth.annual_report("2019-12-28", "2020-03-01", {"Revenues": 100.0, "Assets": 50.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 110.0}, comparatives={"2019-12-28": {"Revenues": 99.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    fy = pit_with(tmp_path).fiscal_years("1", "2021-06-01")
    assert list(fy) == ["2019-12-28", "2020-12-31"] and fy["2019-12-28"].cells["revenue"].val == 100.0


# ---- the engines' interface, supplements, SIC, vendoring ------------------------------------------------------------------------------

def test_company_pit_carries_filed_values_with_their_filings_and_nothing_on_or_after_the_date(tmp_path):
    facts = (synth.annual_report("2018-12-31", "2019-03-01", {"Revenues": 90.0, "Assets": 50.0, "PreferredStockValue": 5.0, "OperatingIncomeLoss": 9.0,
                                                              "LongTermDebtNoncurrent": 20.0, "LongTermDebtCurrent": 3.0, "ShortTermBorrowings": 4.0}) +
             synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "Assets": 60.0}) +
             synth.annual_report("2019-12-31", "2020-03-01", {"LiabilityForFuturePolicyBenefits": 30.0}, accn="ins") +
             [synth.cover("2020-02-20", "2020-03-01", 700.0, form="10-K", accn="a")])
    synth.write_company(tmp_path / "store", 1, facts)
    pit = PitData(tmp_path / "store", id_map={"AAA": "1"})
    cp = pit.company_pit("1", "2020-03-02")
    assert cp.ticker == "AAA" and cp.cik == "0000000001"
    assert cp.periods() == ["2018-12-31", "2019-12-31"]
    f = cp.series["revenue"]["2019-12-31"]
    assert (f.value, f.period_end, f.filed, f.form, f.tag) == (100.0, "2019-12-31", "2020-03-01", "10-K", "Revenues") and f.accession
    assert cp.series["preferred_equity"]["2018-12-31"].value == 5.0 and "pit_supplement" not in cp.series["preferred_equity"]["2018-12-31"].tag
    assert cp.series["debt_current"]["2018-12-31"].value == 3.0 and cp.series["short_term_borrowings_separate"]["2018-12-31"].value == 4.0
    assert cp.shares_outstanding.value == 700.0 and cp.shares_outstanding.filed == "2020-03-01"
    assert cp.concept_values("LiabilityForFuturePolicyBenefits") == {"2019-12-31": 30.0}
    assert all(set(cp.row(pe)) >= set(pdm.ENGINE_FIELDS) for pe in cp.periods())
    assert pit.company_pit("1", "2019-03-01").periods() == []              # the first report was filed that day: not before
    assert pit.company_pit("1", "2019-03-02").periods() == ["2018-12-31"]
    assert pit.company_pit("1", "2020-03-02").cik == cp.cik


def test_ep_revenue_and_capex_supplements_fill_only_empty_cells_and_are_flagged(tmp_path):
    synth.write_company(tmp_path / "store", 1, synth.annual_report(
        "2019-12-31", "2020-03-01", {"OilAndGasRevenue": 500.0, "PaymentsToExploreAndDevelopOilAndGasProperties": 200.0, "Assets": 900.0}))
    synth.write_company(tmp_path / "store", 2, synth.annual_report(
        "2019-12-31", "2020-03-01", {"Revenues": 700.0, "OilAndGasRevenue": 500.0, "PaymentsToAcquirePropertyPlantAndEquipment": 80.0,
                                     "PaymentsToExploreAndDevelopOilAndGasProperties": 200.0, "Assets": 900.0}))
    pit = pit_with(tmp_path)
    fy = pit.fiscal_years("1", "2021-01-01")["2019-12-31"]
    assert fy.row()["revenue"] == 500.0 and "pit_supplement" in fy.cells["revenue"].flags and fy.cells["revenue"].tag == "OilAndGasRevenue"
    assert fy.row()["capex"] == 200.0 and "capex_ep_exploration_and_development_unproven_total" in fy.cells["capex"].flags
    fy2 = pit.fiscal_years("2", "2021-01-01")["2019-12-31"]
    assert fy2.row()["revenue"] == 700.0 and fy2.row()["capex"] == 80.0       # extracted values are never replaced
    assert "pit_supplement" not in fy2.cells["revenue"].flags


def test_sic_comes_from_submissions_files_and_is_stamped_not_point_in_time(tmp_path):
    (tmp_path / "subs").mkdir()
    (tmp_path / "subs" / "CIK0000000001.json").write_text('{"sic": "1311", "sicDescription": "Crude Petroleum & Natural Gas"}', encoding="utf-8")
    synth.write_company(tmp_path / "store", 1, synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 1.0}))
    pit = PitData(tmp_path / "store", sic_source=pdm.SubmissionsDirSic(tmp_path / "subs"))
    s = pit.sic("1")
    assert s.code == "1311" and s.point_in_time is False and "current" in s.source
    assert pit.sic("2") is None
    assert pit.company_pit("1", "2021-01-01").sic.code == "1311"


def test_the_vendored_extractor_is_the_screeners_file_byte_for_byte():
    import hashlib
    man = json.loads((pdm.VENDORED_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, meta in man["files"].items():
        assert hashlib.sha256((pdm.VENDORED_DIR / name).read_bytes()).hexdigest() == meta["sha256"], name
    # when a screener copy can be located it must be identical (a stale vendored copy is the failure this test exists to catch)
    import os
    for root in filter(None, [os.environ.get("SCREENER_PUBLISH_REPO"), str(Path(__file__).resolve().parents[4] / "screener-publish")]):
        src = Path(root) / "scripts" / "build_fundamentals_history.py"
        if src.is_file():
            assert hashlib.sha256(src.read_bytes()).hexdigest() == man["files"]["build_fundamentals_history.py"]["sha256"], \
                "the screener's extractor changed: re-copy valuation/vendored (see MANIFEST.json)"
            break


# ---- Addendum C: the decision time, acceptance timestamps, provenance states --------------------------------------------------------------

def test_the_decision_time_is_16_00_eastern_with_the_daylight_rule():
    assert pdm.decision_time_utc("2019-03-01").isoformat() == "2019-03-01T21:00:00+00:00"          # EST
    assert pdm.decision_time_utc("2019-07-01").isoformat() == "2019-07-01T20:00:00+00:00"          # EDT
    assert pdm.decision_time_utc("2019-03-08").hour == 21 and pdm.decision_time_utc("2019-03-11").hour == 20     # DST began 2019-03-10
    assert pdm.decision_time_utc("2019-11-01").hour == 20 and pdm.decision_time_utc("2019-11-04").hour == 21     # and ended 2019-11-03
    assert pdm.parse_accepted("2019-03-01T21:15:34.000Z").hour == 21 and pdm.parse_accepted("20190701101500").hour == 14
    assert pdm.parse_accepted("garbage") is None and pdm.parse_accepted(None) is None


def _accepting(tmp_path, accepted):
    subs = tmp_path / "subs"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / "CIK0000000001.json").write_text(json.dumps({"filings": {"recent": {
        "accessionNumber": list(accepted), "acceptanceDateTime": list(accepted.values())}}}), encoding="utf-8")
    return pdm.SubmissionsAcceptance(subs)


def test_a_filing_accepted_before_16_00_eastern_on_the_date_is_known_one_accepted_after_is_not(tmp_path):
    facts = synth.annual_report("2019-12-31", "2020-03-02", {"Revenues": 100.0, "Assets": 50.0}, accn="a1")
    synth.write_company(tmp_path / "store", 1, facts)
    early = _accepting(tmp_path, {"a1": "2020-03-02T20:59:59.000Z"})          # 15:59:59 EST
    late = _accepting(tmp_path / "late", {"a1": "2020-03-02T21:00:01.000Z"})  # 16:00:01 EST
    assert list(PitData(tmp_path / "store", acceptance_source=early).fiscal_years("1", "2020-03-02")) == ["2019-12-31"]
    assert PitData(tmp_path / "store", acceptance_source=late).fiscal_years("1", "2020-03-02") == {}
    assert list(PitData(tmp_path / "store", acceptance_source=late).fiscal_years("1", "2020-03-03")) == ["2019-12-31"]


def test_without_a_timestamp_a_filing_on_the_date_is_ambiguous_and_not_used(tmp_path):
    facts = synth.annual_report("2019-12-31", "2020-03-02", {"Revenues": 100.0, "Assets": 50.0}, accn="a1")
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert pit.fiscal_years("1", "2020-03-02") == {}
    assert list(pit.fiscal_years("1", "2020-03-03")) == ["2019-12-31"]
    states = {r["state"] for r in pit.company("1").facts_table("2020-03-02") if r["tag"] == "Revenues"}
    assert states == {"AMBIGUOUS"}


def test_facts_table_carries_every_field_and_the_provenance_states(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}, accn="a1") +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0}, comparatives={"2019-12-31": {"Revenues": 90.0}}, accn="a2") +
             synth.annual_report("2021-12-31", "2022-03-01", {"Revenues": 130.0}, accn="a3"))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    recs = [r for r in pit.company("1").facts_table("2021-06-01") if r["tag"] == "Revenues"]
    by = {(r["accession"], r["end"]): r for r in recs}
    assert by[("a1", "2019-12-31")]["state"] == "RESTATED"          # superseded by the 90 in a2
    assert by[("a2", "2019-12-31")]["state"] == "PIT_VALID" and by[("a2", "2020-12-31")]["state"] == "PIT_VALID"
    assert by[("a3", "2021-12-31")]["state"] == "PIT_INVALID"       # filed after the date
    r = by[("a2", "2020-12-31")]
    assert {"cik", "taxonomy", "tag", "unit", "value", "start", "end", "instant", "dimensions", "form", "filed", "accepted_at", "accession", "amended",
            "fy", "fp", "state"} <= set(r) and r["instant"] is False and r["dimensions"] is None and r["amended"] is False
    assert [x for x in pit.company("1").facts_table("2021-06-01") if x["tag"] == "Revenues" and x["state"] == "PIT_INVALID"]


def test_the_company_pit_never_carries_a_value_accepted_after_the_decision_time(tmp_path):
    facts = (synth.annual_report("2018-12-31", "2019-03-01", {"Revenues": 90.0, "Assets": 50.0}, accn="a1") +
             synth.annual_report("2019-12-31", "2020-03-02", {"Revenues": 100.0, "Assets": 60.0}, accn="a2"))
    synth.write_company(tmp_path / "store", 1, facts)
    acc = _accepting(tmp_path, {"a1": "2019-03-01T21:00:00.000Z", "a2": "2020-03-02T22:30:00.000Z"})
    cp = PitData(tmp_path / "store", acceptance_source=acc, id_map={"AAA": "1"}).company_pit("1", "2020-03-02")
    assert cp.periods() == ["2018-12-31"]
    assert all(f.filed < "2020-03-02" or f.filed == "2019-03-01" for per in cp.series.values() for f in per.values())
