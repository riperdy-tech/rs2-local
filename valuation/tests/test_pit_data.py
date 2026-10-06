"""Tests of the point-in-time layer on synthetic companyfacts (no network, no archive)."""
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


def test_values_are_as_first_filed_and_latest_mode_only_measures_restatements(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0}, comparatives={"2019-12-31": {"Revenues": 90.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    first = pit.fiscal_years("1", "2021-06-01")
    assert first["2019-12-31"].cells["revenue"].val == 100.0              # never the restated 90
    assert first["2020-12-31"].cells["revenue"].val == 120.0
    latest = pit.fiscal_years("1", "2021-06-01", mode="latest")
    assert latest["2019-12-31"].cells["revenue"].val == 90.0              # diagnostic mode shows the restatement
    assert pit.fiscal_years("1", "2020-06-01")["2019-12-31"].cells["revenue"].val == 100.0


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
    # FY2018's own report is not in the archive: only a later report's comparative carries it
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}, comparatives={"2018-12-31": {"Revenues": 80.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    fy = pit.fiscal_years("1", "2020-06-01")
    assert fy["2018-12-31"].exists_from == "2020-03-01"                   # the comparative's filing date, not the year end
    assert "no_own_filing_in_companyfacts" in fy["2018-12-31"].stamps
    assert fy["2019-12-31"].stamps == ()
    assert "2018-12-31" not in pit.fiscal_years("1", "2020-02-01")        # and nothing before


def test_only_annual_forms_count_and_s1_data_is_never_stored(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2018-12-31", "2019-01-15", {"Revenues": 999.0}, form="S-1") +
             synth.annual_report("2019-09-30", "2019-11-01", {"Revenues": 777.0}, form="10-Q"))
    obj = {"cik": 1, "entityName": "x", "facts": {"us-gaap": {}}}
    for taxo, tag, unit, start, end, val, accn, filed, form in facts:
        obj["facts"]["us-gaap"].setdefault(tag, {"units": {}})["units"].setdefault(unit, []).append(
            {"start": start, "end": end, "val": val, "accn": accn, "filed": filed, "form": form})
    doc = pdm.compact_company(obj)
    assert {f[8] for f in doc["facts"]} == {"10-K"}
    synth.write_company(tmp_path / "store", 1, doc["facts"])
    assert list(pit_with(tmp_path).fiscal_years("1", "2021-01-01")) == ["2019-12-31"]


def test_an_amendment_never_overrides_the_original_but_stands_when_alone(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0}) +
             synth.annual_report("2019-12-31", "2020-09-01", {"Revenues": 95.0}, form="10-K/A"))
    synth.write_company(tmp_path / "store", 1, facts)
    pit = pit_with(tmp_path)
    assert pit.fiscal_years("1", "2021-01-01")["2019-12-31"].cells["revenue"].val == 100.0
    synth.write_company(tmp_path / "store", 2, synth.annual_report("2019-12-31", "2020-09-01", {"Revenues": 95.0}, form="10-K/A"))
    fy = pit.fiscal_years("2", "2021-01-01")["2019-12-31"]
    assert fy.cells["revenue"].val == 95.0 and "from_amendment" in fy.cells["revenue"].flags
    assert "own_filing_is_amendment" in fy.stamps


def test_earlier_filed_lower_priority_tag_beats_a_later_preferred_tag_and_ties_use_ladder_order(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"SalesRevenueNet": 100.0, "Revenues": 101.0}) +      # same filing: ladder order
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0}, comparatives={"2019-12-31": {"Revenues": 100.0}}))
    synth.write_company(tmp_path / "store", 1, facts)
    c = pit_with(tmp_path).fiscal_years("1", "2021-06-01")["2019-12-31"].cells["revenue"]
    assert c.tag == "Revenues" and c.val == 101.0 and c.filed == "2020-03-01"
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"SalesRevenueNet": 100.0}) +
             synth.annual_report("2020-12-31", "2021-03-01", {"Revenues": 120.0}, comparatives={"2019-12-31": {"Revenues": 99.0}}))
    synth.write_company(tmp_path / "store", 2, facts)
    c = pit_with(tmp_path).fiscal_years("2", "2021-06-01")["2019-12-31"].cells["revenue"]
    assert c.tag == "SalesRevenueNet" and c.val == 100.0


def test_non_usd_cells_are_not_read_and_zero_is_a_value(tmp_path):
    facts = (synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 100.0, "GrossProfit": 0.0}) +
             synth.annual_report("2019-12-31", "2020-03-01", {"OperatingIncomeLoss": 5.0}, unit="EUR", accn="eur"))
    synth.write_company(tmp_path / "store", 1, facts)
    row = pit_with(tmp_path).rows("1", "2021-01-01")[2019]
    assert row["gross_profit"] == 0.0 and row["operating_income"] is None


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
    cov = [synth.cover("2020-02-20", "2020-03-01", 100000.0, form="10-K", accn="c1")]
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
