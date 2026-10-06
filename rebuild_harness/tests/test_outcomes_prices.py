"""Outcomes with next-session entry and delisting events, the price-quality labels, the Yahoo provider (offline), and SIC as filed at T."""
import json

import pytest

from rebuild_harness import outcomes, run_harness
from rebuild_harness.tests.test_run_harness import build_world, N
from valuation import pit_data as pdm
from valuation.pit_data import DailyPriceSource, MonthlyRawPriceSource, PitData, YahooPriceProvider, NetworkNotAllowed
from valuation.tests import synth


def days(start, n, price0, step):
    """n consecutive calendar days from `start` (ISO), price0 growing by `step` per day; close = adj."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return {(d0 + timedelta(days=i)).isoformat(): {"close": price0 + step * i, "adj": price0 + step * i} for i in range(n)}


def pit_of(src):
    return PitData("unused", price_source=src)


def test_the_return_starts_at_the_next_session_not_the_decision_close():
    rows = {"A": days("2020-01-01", 200, 100.0, 1.0), "SPY": days("2020-01-01", 200, 300.0, 0.0)}
    src = DailyPriceSource(rows, splits={"A": [], "SPY": []})
    pit = pit_of(src)
    o = outcomes.horizon_outcome(pit, "A", "2020-01-10", 3)                  # entry 2020-01-11 (price 110), exit 2020-04-10 (price 100+100=200)
    assert o["status"] == "observed" and o["ret"] == pytest.approx(200.0 / 110.0 - 1.0)
    assert o["bench"] == 0.0 and o["excess"] == o["ret"]
    assert "no_next_session_in_monthly_data" not in o["flags"]


def test_a_monthly_source_has_no_next_session_and_says_so():
    doc = {"prices": {"A": {"2020-01": [10.0, 10.0, 0.0, None], "2020-04": [12.0, 12.0, 0.0, None]}, "SPY": {"2020-01": [100.0, 100.0, 0.0, None], "2020-04": [100.0, 100.0, 0.0, None]}}}
    pit = pit_of(MonthlyRawPriceSource(doc))
    o = outcomes.horizon_outcome(pit, "A", "2020-01-31", 3)
    assert o["status"] == "observed" and "no_next_session_in_monthly_data" in o["flags"] and o["ret"] == pytest.approx(0.2)


def _delisted_world(event):
    a = days("2020-01-01", 60, 100.0, 1.0)                               # last bar 2020-02-29 at 159 (adj 159)
    rows = {"A": a, "SPY": days("2020-01-01", 300, 300.0, 0.0), "ACQ": days("2020-01-01", 300, 80.0, 0.0)}
    return pit_of(DailyPriceSource(rows, splits={"A": [], "SPY": [], "ACQ": []}, delistings={"A": event} if event else None))


def test_bankruptcy_is_minus_100_percent():
    o = outcomes.horizon_outcome(_delisted_world({"date": "2020-03-01", "type": "bankruptcy"}), "A", "2020-01-10", 3)
    assert o["status"] == "delisted_bankruptcy" and o["available"] and o["ret"] == -1.0 and o["excess"] == -1.0


def test_an_acquisition_pays_its_consideration_in_cash_or_stock():
    o = outcomes.horizon_outcome(_delisted_world({"date": "2020-03-01", "type": "acquisition", "cash_per_share": 200.0}), "A", "2020-01-10", 3)
    assert o["status"] == "delisted_acquisition" and o["ret"] == pytest.approx(159.0 * (200.0 / 159.0) / 110.0 - 1.0)
    assert "proceeds_held_as_cash" in o["flags"]
    o = outcomes.horizon_outcome(_delisted_world({"date": "2020-03-01", "type": "acquisition", "stock_ratio": 2.0, "acquirer_key": "ACQ"}), "A", "2020-01-10", 3)
    assert o["ret"] == pytest.approx(160.0 / 110.0 - 1.0)                # 2 x 80
    o = outcomes.horizon_outcome(_delisted_world({"date": "2020-03-01", "type": "acquisition", "stock_ratio": 2.0, "acquirer_key": "NOPE"}), "A", "2020-01-10", 3)
    assert o["status"] == "OUTCOME_UNOBSERVABLE" and o["ret"] is None


def test_no_event_is_unobservable_never_an_invented_loss():
    o = outcomes.horizon_outcome(_delisted_world(None), "A", "2020-01-10", 3)
    assert o["status"] == "OUTCOME_UNOBSERVABLE" and not o["available"] and o["ret"] is None and "no_delisting_event_on_record" in o["flags"]
    o = outcomes.horizon_outcome(_delisted_world({"date": "2020-03-01", "type": "otc_continuation"}), "A", "2020-01-10", 3)
    assert o["status"] == "OUTCOME_UNOBSERVABLE"


def test_a_horizon_beyond_the_data_is_not_a_missing_security_and_coverage_only_forms_no_return():
    pit = _delisted_world({"date": "2020-03-01", "type": "bankruptcy"})
    assert outcomes.horizon_outcome(pit, "A", "2020-01-10", 36)["status"] == "horizon_beyond_data"
    o = outcomes.horizon_outcome(pit, "A", "2020-01-10", 3, coverage_only=True)
    assert o["available"] and o["ret"] is None and o["excess"] is None


def test_price_quality_labels():
    src = DailyPriceSource({"A": {"2020-03-02": {"close": 10.0, "adj": 10.0}}}, splits={"A": []})
    assert src.price_quality("A", "2020-03-02") == ("verified", "exact_session")
    assert src.price_quality("A", "2020-03-04")[0] == "unverified"
    assert src.price_quality("A", "2020-03-30") == ("missing", "no_close_on_date")
    assert src.price_quality("B", "2020-03-02") == ("missing", "ticker_not_in_provider")
    assert DailyPriceSource({"A": {"2020-03-02": {"close": 10.0, "adj": 10.0}}}).price_quality("A", "2020-03-02")[0] == "unverified"   # splits unknown
    m = MonthlyRawPriceSource({"prices": {"A": {"2020-03": [10.0, 10.0, 0.0, None]}}})
    assert m.price_quality("A", "2020-03-31")[0] == "unverified"


def test_the_yahoo_provider_is_offline_unless_permitted_and_undoes_splits(tmp_path):
    prov = YahooPriceProvider(tmp_path / "y")
    with pytest.raises(NetworkNotAllowed):
        prov.fetch(["A"], "2020-01-01", "2020-12-31")
    fake = {"A": [{"date": "2020-01-02", "close": 50.0, "adj_close": 49.0, "dividend": 0.0, "split": 0.0},
                  {"date": "2020-06-01", "close": 30.0, "adj_close": 29.0, "dividend": 0.0, "split": 2.0},      # Yahoo's Close is already split-adjusted
                  {"date": "2020-06-02", "close": 31.0, "adj_close": 30.0, "dividend": 0.0, "split": 0.0}],
            "GONE": []}
    prov = YahooPriceProvider(tmp_path / "y2", downloader=lambda k, s, e: fake[k])
    prov.fetch(["A", "GONE"], "2020-01-01", "2020-12-31")
    src = prov.load(["A", "GONE"])
    assert src.close_unadjusted("A", "2020-01-02").price == 100.0 and src.close_unadjusted("A", "2020-06-02").price == 31.0
    assert src.splits("A") == [("2020-06-01", 2.0)] and src.close_unadjusted("A", "2020-01-02").quality == "verified"
    assert prov.unpriceable(["A", "GONE", "NEVER"]) == ["GONE", "NEVER"] and not src.has_key("GONE")


HDR = """<SEC-HEADER>0001234567-19-000001.hdr.sgml : 20190301
ACCESSION NUMBER:		0001234567-19-000001
CONFORMED SUBMISSION TYPE:	10-K
CONFORMED PERIOD OF REPORT:	20181231
FILED AS OF DATE:		20190301
<ACCEPTANCE-DATETIME>20190301161530
FILER:
	COMPANY DATA:
		COMPANY CONFORMED NAME:			OLD NAME INC
		CENTRAL INDEX KEY:			0000000001
		STANDARD INDUSTRIAL CLASSIFICATION:	CRUDE PETROLEUM & NATURAL GAS [1311]
"""


def test_sic_and_name_as_filed_at_the_date_from_filing_headers(tmp_path):
    h = pdm.parse_sec_header(HDR)
    assert h["sic"] == "1311" and h["name"] == "OLD NAME INC" and h["cik"] == "0000000001" and h["filed"] == "2019-03-01" and h["period"] == "2018-12-31"
    assert h["accepted_at"].isoformat() == "2019-03-01T21:15:30+00:00"
    later = HDR.replace("19-000001", "21-000009").replace("20190301", "20210301").replace("OLD NAME INC", "NEW NAME CORP").replace("[1311]", "[2911]").replace(
        "CRUDE PETROLEUM & NATURAL GAS", "PETROLEUM REFINING")
    (tmp_path / "h").mkdir()
    (tmp_path / "h" / "a.hdr.sgml").write_text(HDR, encoding="utf-8")
    (tmp_path / "h" / "b.hdr.sgml").write_text(later, encoding="utf-8")
    hs = pdm.HeaderSic.from_dir(tmp_path / "h")
    assert hs("1", "2018-12-31") is None                                   # before the first header on record: today's SIC is never substituted
    assert hs("1", "2019-03-01") is None                                   # accepted at 16:15 ET: after the decision time of that day
    assert hs("1", "2019-03-02").code == "1311" and hs("1", "2019-03-02").point_in_time is True
    assert hs("1", "2021-06-30").code == "2911" and hs.name_asof("1", "2020-06-30") == "OLD NAME INC" and hs.name_asof("1", "2021-06-30") == "NEW NAME CORP"
    synth.write_company(tmp_path / "store", 1, synth.annual_report("2018-12-31", "2019-03-01", {"Revenues": 1.0}))
    pit = PitData(tmp_path / "store", sic_history=hs, sic_source=lambda cik: pdm.SicRecord("9999", "today", "current", False))
    assert pit.sic("1", "2020-01-01").code == "1311" and pit.sic("1", "2018-01-01") is None and pit.sic("1").code == "9999"
    assert pit.company_pit("1", "2020-01-01").sic.code == "1311"


def test_the_share_of_the_universe_the_provider_cannot_price_is_measured_per_date(tmp_path):
    pit, ciks = build_world(tmp_path)
    for i in range(10, 20):                                               # ten companies the provider does not hold
        del pit.price_source.prices[f"T{i}"]
    synth.simple_company(pit.store_dir, 900, 8, first_year=2012)           # a filer with no ticker at all (a delisted or unmapped company)
    res = run_harness.run(["2018-06-29"], ciks + ["900"], ["yardstick_earnings_yield"], pit, tmp_path / "out", coverage_only=True)
    c = res["coverage"]["dates"]["2018-06-29"]
    assert c["price_coverage"]["priced"] == N - 10 and c["price_coverage"]["unpriceable_ticker_not_in_provider"] == 10
    assert c["price_coverage"]["unpriceable_no_ticker_mapping"] == 1
    assert c["unpriceable_share_of_universe"] == pytest.approx(11 / (N + 1))
    assert c["price_quality"]["unverified"] == N - 10 and c["outcome_status"]["12"]["observed"] == N - 10
