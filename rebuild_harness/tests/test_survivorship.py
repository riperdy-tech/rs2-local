"""The survivorship machinery (Addendum M): the cover index, the missing-name census (M1), the price proxy (M2), the outcomes of the names that left (M3), the three bounds (M4), the scoped cash
reader (M5) and the monthly fallback behind a D5 ticker whose history starts late (M6).  Synthetic data only."""
import gzip
import json
import zipfile
from pathlib import Path

import pytest

from rebuild_harness import daily_prices as dp, delistings as D, metrics as hm, outcomes, survivorship as sv
from rebuild_harness.tests.test_daily_prices import run, write
from rebuild_harness.tests.test_delisting_inputs import BK_8K, CASH_8K, STOCK_8K, build, ev
from valuation import pit_data as pdm
from valuation.common import DataNotPresent
from valuation.tests import synth


# ---- the cover index -----------------------------------------------------------------------------------------------------------------------------------

def _fact(end, val, accn, filed, form="10-K"):
    return {"end": end, "val": val, "accn": accn, "filed": filed, "form": form}


def _company(cik, name, floats, shares):
    return {"cik": cik, "entityName": name, "facts": {"dei": {"EntityPublicFloat": {"units": {"USD": floats}}, "EntityCommonStockSharesOutstanding": {"units": {"shares": shares}}}}}


def _zip(tmp_path):
    p = tmp_path / "companyfacts.zip"
    docs = {
        "CIK0000000001.json": _company(1, "Alpha", [_fact("2019-06-30", 500e6, "A-19", "2020-03-01"), _fact("2020-06-30", 900e6, "A-20", "2021-03-02"), _fact("2021-06-30", 1.2e9, "A-21", "2022-03-01")],
                                       [_fact("2021-02-15", 30e6, "A-20", "2021-03-02"), _fact("2021-02-15", 20e6, "A-20", "2021-03-02"), _fact("2022-02-15", 40e6, "A-21", "2022-03-01")]),
        "CIK0000000002.json": _company(2, "Beta", [_fact("2020-06-30", 100e6, "B-20", "2021-03-01")], [_fact("2021-02-15", 10e6, "B-20", "2021-03-01")]),
        "CIK0000000003.json": _company(3, "Gamma", [_fact("2020-06-30", 800e6, "G-20", "2021-03-01")], []),                                  # a float and no share count on its cover
        "CIK0000000004.json": {"cik": 4, "entityName": "Delta", "facts": {"us-gaap": {}}},                                                    # no public float at all
    }
    with zipfile.ZipFile(p, "w") as z:
        for n, d in docs.items():
            z.writestr(n, json.dumps(d))
    return p


def test_the_cover_index_keeps_the_companies_with_a_public_float_and_names_its_source(tmp_path):
    man = sv.build_cover_index(_zip(tmp_path), tmp_path / "cover", workers=1)
    assert man["n_companies_with_public_float"] == 3 and man["n_archive_members"] == 4 and len(man["source_zip_sha256"]) == 64
    idx = sv.CoverIndex(tmp_path / "cover")
    assert set(idx.by_cik) == {"0000000001", "0000000002", "0000000003"} and (tmp_path / "cover" / "manifest.json").is_file()
    with pytest.raises(DataNotPresent, match="not empty"):
        sv.build_cover_index(_zip(tmp_path), tmp_path / "cover", workers=1)                  # a new folder every time: nothing is overwritten
    with pytest.raises(DataNotPresent, match="not at"):
        sv.CoverIndex(tmp_path / "nowhere")


def test_the_latest_cover_is_the_newest_filed_strictly_before_the_date_and_its_proxy_is_float_over_the_same_covers_shares(tmp_path):
    sv.build_cover_index(_zip(tmp_path), tmp_path / "cover", workers=1)
    idx = sv.CoverIndex(tmp_path / "cover")
    c = idx.latest("0000000001", "2021-06-30")
    assert c["accession"] == "A-20" and c["public_float"] == 900e6 and c["shares"] == 50e6 and c["n_share_entries"] == 2          # two classes summed
    assert c["price_proxy"] == pytest.approx(18.0) and c["filed"] == "2021-03-02"
    assert idx.latest("0000000001", "2021-03-02")["accession"] == "A-19"                      # filed ON the date: not known (strictly before)
    assert idx.latest("0000000001", "2021-03-03")["accession"] == "A-20"
    assert idx.latest("0000000001", "2020-03-01") is None                                       # the earliest cover is filed that day
    assert idx.latest("0000000001", "2022-12-31")["price_proxy"] == pytest.approx(1.2e9 / 40e6)  # the newer cover, with its own share count (not the older one's)
    g = idx.latest("0000000003", "2021-06-30")
    assert g["public_float"] == 800e6 and g["shares"] is None and g["price_proxy"] is None       # no share count on that cover: no proxy, and none is borrowed from another cover
    assert idx.latest("0000000099", "2021-06-30") is None


# ---- the census ------------------------------------------------------------------------------------------------------------------------------------

T = "2021-06-30"


def _world(tmp_path):
    """Companies: 1 acquired for cash after T; 5 bankrupt after T; 6 delisted for no stated reason after T; 2 below the float floor; 3 still priced at T (D5 holds it); 4 left before T; 7 no cover;
    8 no annual report known at T.  The D5 folder holds company 3 and SPY."""
    zpath = tmp_path / "cf.zip"
    docs = {}
    for i, fl in ((1, 900e6), (2, 100e6), (3, 700e6), (4, 900e6), (5, 600e6), (6, 450e6), (8, 900e6)):
        docs[f"CIK{i:010d}.json"] = _company(i, f"Co{i}", [_fact("2020-06-30", fl, f"C{i}-20", "2021-03-01")], [_fact("2021-02-15", 50e6 if i != 6 else 30e6, f"C{i}-20", "2021-03-01")])
    with zipfile.ZipFile(zpath, "w") as z:
        for n, d in docs.items():
            z.writestr(n, json.dumps(d))
    sv.build_cover_index(zpath, tmp_path / "cover", workers=1)
    events = [ev("0000000001", "acquisition_completed", "2021-11-15", "A-1", ["2.01"]), ev("0000000002", "acquisition_completed", "2021-11-15", "A-2", ["2.01"]),
              ev("0000000003", "acquisition_completed", "2021-11-15", "A-3", ["2.01"]), ev("0000000004", "bankruptcy", "2021-01-15", "A-4", ["1.03"]),
              ev("0000000005", "bankruptcy", "2021-09-15", "A-5", ["1.03"]), ev("0000000006", "delisted_other", "2021-10-01", "A-6", []),
              ev("0000000007", "delisted_other", "2021-10-01", "A-7", []), ev("0000000008", "delisted_other", "2021-12-01", "A-8", [])]
    idx, docs3 = build(tmp_path, events, {("0000000001", "A-1"): CASH_8K, ("0000000005", "A-5"): BK_8K})
    d5 = tmp_path / "d5"
    d5.mkdir()
    write(d5, "THREE", run("2021-05-01", 120, 50.0, 0.1))
    write(d5, "SPY", run("2021-05-01", 700, 400.0, 0.5))
    src = dp.LazyDailyPriceSource(d5)
    store = tmp_path / "store"
    for i in (1, 2, 3, 4, 5, 6):
        synth.simple_company(store, i, 6)                          # an annual report known at T (the last is the 2020 one, filed 2021-03-01)
    # company 8: its first annual report is filed after T
    synth.simple_company(store, 8, 1, first_year=2021)
    pit = pdm.PitData(store, price_source=src)
    tk = {"0000000003": ["THREE"]}
    return sv.Survivorship(sv.CoverIndex(tmp_path / "cover"), idx, docs3, lambda c: tk.get(c, []), src), pit, src


def test_the_census_is_float_at_or_above_the_floor_no_price_at_T_an_event_after_T_and_an_annual_report_known(tmp_path):
    surv, pit, _src = _world(tmp_path)
    c = surv.census(T, pit)
    got = {i["cik"]: i for i in c["items"]}
    assert set(got) == {"0000000001", "0000000005", "0000000006"}
    k = c["counts"]
    assert k["events_after_T"] == 7                                  # 4 left before T
    assert k["no_public_float_cover_before_T"] == 1                  # company 7
    assert k["public_float_below_floor"] == 1                        # company 2
    assert k["float_at_or_above_floor"] == 5 and k["has_price_at_T"] == 1 and k["no_price_at_T"] == 4
    assert k["no_annual_report_at_T"] == 1 and k["census"] == 3      # company 8: its first annual report is filed after T
    assert k["census_class:acquisition_completed"] == 1 and k["census_class:bankruptcy"] == 1 and k["census_class:delisted_other"] == 1
    assert got["0000000001"]["price_proxy"] == pytest.approx(18.0) and got["0000000001"]["within_horizon"] is True
    assert c["annual_report_checked"] is True and surv.census(T, pit) is c                      # cached per date
    assert sv.dev_census_counts(surv, [T], pit)[T]["census"] == 3
    unchecked = sv.Survivorship(surv.cover, surv.index, surv.docs, lambda c: [], surv.src).census(T)
    assert unchecked["annual_report_checked"] is False and unchecked["counts"]["census"] == 5      # no store: the annual-report test is skipped (company 8 stays), and with no tickers company 3 has no price either


def test_a_later_date_drops_the_names_that_left_before_it_and_the_horizon_flag_follows_the_event(tmp_path):
    surv, pit, _src = _world(tmp_path)
    later = {i["cik"] for i in surv.census("2021-10-31", pit)["items"]}
    assert "0000000001" in later and "0000000005" not in later and "0000000006" not in later          # 5 left on 2021-09-15 and 6 on 2021-10-01: before this date
    items = {i["cik"]: i for i in surv.census(T, pit, horizon_months=3)["items"]}                       # a three-month horizon ends 2021-09-30
    assert items["0000000005"]["within_horizon"] is True and items["0000000006"]["within_horizon"] is False and items["0000000001"]["within_horizon"] is False
    assert surv.census(T, pit, horizon_months=3)["counts"]["census_event_after_horizon"] == 2


# ---- the outcomes (M3) and the three bounds (M4) -----------------------------------------------------------------------------------------------------------

def _bench(src, asof, months=12):
    return src.adj_close("SPY", src.target_date(asof, months)).price / src.entry_point("SPY", asof).price - 1.0


def test_an_acquisition_with_a_resolved_cash_price_is_valued_against_the_proxy_price(tmp_path):
    surv, pit, src = _world(tmp_path)
    item = surv.items_by_cik(T, pit)["0000000001"]
    o = surv.outcome(item, src, T, 12)
    b = _bench(src, T)
    assert o["status"] == outcomes.ACQUIRED and o["available"] and o["ret"] == pytest.approx(45.0 / 18.0 - 1.0) and o["bench"] == pytest.approx(b) and o["excess"] == pytest.approx(45.0 / 18.0 - 1.0 - b)
    assert sv.PROXY_STAMP in o["flags"] and "deal_value_against_the_proxy_price" in o["flags"]
    assert set(o["bounds"]) == set(hm.BOUNDS) and all(v == pytest.approx(o["excess"]) for v in o["bounds"].values())        # resolved: the same under all three bounds


def test_a_bankruptcy_with_the_equity_cancelled_is_minus_100_percent(tmp_path):
    surv, pit, src = _world(tmp_path)
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000005"], src, T, 12)
    assert o["status"] == outcomes.BANKRUPT and o["ret"] == -1.0 and o["excess"] == pytest.approx(-1.0 - _bench(src, T)) and "delisting_bankruptcy_minus_100pct" in o["flags"]
    assert all(v == pytest.approx(o["excess"]) for v in o["bounds"].values())


def test_everything_else_is_unobservable_with_the_three_bounds_excluded_minus100_and_the_proxy_price_held(tmp_path):
    surv, pit, src = _world(tmp_path)
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000006"], src, T, 12)        # a delisting with no reader for its class
    b = _bench(src, T)
    assert o["status"] == outcomes.UNOBSERVABLE and not o["available"] and o["excess"] is None and o["ret"] is None
    assert o["bounds"] == {"excluded": None, "minus100": pytest.approx(-1.0 - b), "last_close": pytest.approx(0.0 - b)}
    assert any(f.startswith("unobservable_delisting:unresolved_delisted_other") for f in o["flags"])


def test_an_acquisition_the_strict_reader_declines_is_unobservable_and_so_is_an_event_after_the_horizon(tmp_path):
    surv, pit, src = _world(tmp_path)
    surv.docs = build_stock(tmp_path)                                  # the same event, now read from a stock-and-cash text: the reader declines
    surv._price_events.clear()
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000001"], src, T, 12)
    assert o["status"] == outcomes.UNOBSERVABLE and o["bounds"]["excluded"] is None and o["bounds"]["minus100"] < o["bounds"]["last_close"]
    late = dict(surv.items_by_cik(T, pit)["0000000001"], event_date="2022-09-15")                   # after the 12-month horizon (2022-06-30): the company still traded then
    surv._price_events.clear()
    o2 = surv.outcome(late, src, T, 12)
    assert o2["status"] == outcomes.UNOBSERVABLE and "event_after_horizon" in o2["flags"] and o2["bounds"]["excluded"] is None


def build_stock(tmp_path):
    from rebuild_harness import delisting_inputs as di
    d3 = tmp_path / "d3_stock"
    (d3 / "0000000001" / "A-1").mkdir(parents=True)
    (d3 / "0000000001" / "A-1" / "d8k.htm").write_text(STOCK_8K, encoding="utf-8")
    (d3 / "_manifest.jsonl").write_text(json.dumps({"cik": "0000000001", "accession": "A-1", "form": "8-K", "status": "ok", "files": [{"name": "d8k.htm", "status": "ok", "bytes": 1}]}) + "\n", encoding="utf-8")
    return di.DelistingDocs(d3)


def test_a_company_with_no_price_proxy_or_no_benchmark_has_no_outcome_and_no_bound(tmp_path):
    surv, pit, src = _world(tmp_path)
    item = surv.items_by_cik(T, pit)["0000000001"]
    o = surv.outcome(dict(item, price_proxy=None), src, T, 12)
    assert o["status"] == outcomes.UNOBSERVABLE and "no_price_proxy" in o["flags"] and set(o["bounds"].values()) == {None}
    o = surv.outcome(item, src, T, 120)                                 # a horizon beyond the benchmark's data
    assert o["status"] == outcomes.BEYOND


# ---- M5: the scoped reader ------------------------------------------------------------------------------------------------------------------------------

MIXED = ("Item 2.01. Completion of Acquisition. On June 3, 2021, Acme Corp. (the Company) completed its merger with Parent Inc. At the Effective Time each share of the Company's common stock, "
         "par value $0.01, was converted into the right to receive $45.00 in cash per share, without interest. Item 5.02. The Board announced the election of a new director and an exchange ratio "
         "for the Company's warrants is described in Exhibit 99.1.")


def test_the_reader_is_scoped_to_the_sentence_that_states_the_per_share_consideration():
    assert D.read_cash_consideration_whole_text(MIXED) is None                # before M5: 'election' and 'exchange ratio' elsewhere in the 8-K declined it
    assert D.read_cash_consideration(MIXED) == 45.0                           # after M5: only the sentence stating the consideration is read
    assert D.consideration_sentences(MIXED)[0].endswith("without interest.")


def test_a_cash_and_stock_election_in_that_sentence_still_declines_and_so_do_two_amounts_and_stock_consideration():
    assert D.read_cash_consideration("Each share was converted into the right to receive $45.00 in cash per share or, at the holder's election, 0.5 shares of Parent common stock.") is None
    assert D.read_cash_consideration("Each share was converted into the right to receive $10.00 in cash and 0.5 shares of the Parent common stock (the exchange ratio).") is None
    assert D.read_cash_consideration("Holders receive $45.00 per share in cash. Holders of another series receive $47.50 per share.") is None           # two distinct amounts in the stating sentences
    assert D.read_cash_consideration("Holders receive $45.00 per share in cash. Holders of options receive $45.00 per share.") == 45.0                   # the same amount twice is one amount
    assert D.read_cash_consideration("The merger closed on June 3. Nothing is said about a price.") is None
    assert D.read_cash_consideration(None) is None and D.read_cash_consideration("") is None
    assert D.read_cash_consideration("Each share was converted into the right to receive $45.00 in cash per share, subject to the election.") is None


# ---- N5: 'common stock of' is not a stock word -----------------------------------------------------------------------------------------------------------

TARGET_STOCK_NAMED = "At the Effective Time each share of common stock of the Company was converted into the right to receive $45.00 in cash, without interest."


def test_common_stock_of_in_the_consideration_sentence_names_the_shares_bought_and_no_longer_declines():
    assert D.read_cash_consideration_whole_text(TARGET_STOCK_NAMED) is None               # before M5 and N5
    assert D.read_cash_consideration(TARGET_STOCK_NAMED, stock_words=D._STOCK_WORDS_M5) is None      # the M5 reader (scoped, with the phrase)
    assert D.read_cash_consideration(TARGET_STOCK_NAMED) == 45.0                          # the N5 reader


def test_elections_exchange_ratios_and_named_acquirer_stock_still_decline_after_n5():
    for tail in ("or, at the holder's election, 0.5 shares of Parent common stock.",
                 "and 0.5 shares of Parent common stock (the exchange ratio).",
                 "and 0.5 shares of common stock of Parent.",
                 "and 0.5 shares of common stock of the Acquirer.",
                 "and 0.5 shares of the buyer.",
                 "plus one contingent value right.",
                 "payable in stock consideration at the holder's option."):
        t = "Each share of common stock of the Company was converted into the right to receive $45.00 in cash " + tail
        assert D.read_cash_consideration(t) is None, tail


def test_an_abbreviation_never_ends_a_sentence_and_a_missed_split_only_makes_the_reader_stricter():
    t = "Acme Corp. and Parent Inc. agreed. Each share receives $45.00 in cash per share (the election of Parent Inc. is irrelevant)."
    assert [s for s in D.sentences(t)] == ["Acme Corp. and Parent Inc. agreed.", "Each share receives $45.00 in cash per share (the election of Parent Inc. is irrelevant)."]
    assert D.read_cash_consideration(t) is None                               # the stating sentence holds the word 'election'
    assert D.sentences("Item 2.01. On Dec. 3, 2021 the deal closed at $12.50 per share.") == ["Item 2.01.", "On Dec. 3, 2021 the deal closed at $12.50 per share."]


def test_a_price_event_is_the_same_for_the_ticker_keyed_and_the_company_keyed_paths():
    e = ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01"])
    assert D.price_event(e, MIXED) == D.to_price_events([e], lambda c: ["AAA"], lambda ee: MIXED)["AAA"]
    assert D.price_event(e, None)["type"] == "unresolved_acquisition_completed" and D.price_event(e, MIXED)["cash_per_share"] == 45.0


# ---- M6: the monthly fallback --------------------------------------------------------------------------------------------------------------------------------

def _fallback(tmp_path):
    d5 = tmp_path / "d5f"
    d5.mkdir()
    write(d5, "LATE", run("2021-03-01", 300, 20.0, 0.1))                       # D5 history starts on 2021-03-01
    write(d5, "FULL", run("2020-01-01", 800, 50.0, 0.1))
    write(d5, "SPY", run("2020-01-01", 800, 300.0, 0.5))
    monthly = pdm.MonthlyRawPriceSource({"prices": {"LATE": {"2020-12": [10.0, 9.0, 0.0, 0.0], "2021-01": [11.0, 9.9, 0.0, 0.0], "2021-02": [12.0, 10.8, 0.0, 0.0], "2021-06": [15.0, 13.5, 0.0, 0.0]},
                                                    "FULL": {"2020-12": [999.0, 999.0, 0.0, 0.0]}, "NOD5": {"2020-12": [7.0, 7.0, 0.0, 0.0]}}})
    return dp.FallbackPriceSource(dp.LazyDailyPriceSource(d5), monthly)


def test_a_ticker_whose_d5_history_starts_after_the_date_takes_the_monthly_bar_stamped(tmp_path):
    s = _fallback(tmp_path)
    p = s.close_unadjusted("LATE", "2021-01-31")
    assert p.price == pytest.approx(11.0) and dp.FALLBACK_FLAG in p.flags and p.quality == "unverified"
    assert s.close_unadjusted("LATE", "2021-06-30").price != 15.0 and dp.FALLBACK_FLAG not in s.close_unadjusted("LATE", "2021-06-30").flags      # the daily bar exists: the daily one
    assert s.adj_close("LATE", "2021-01-31").price == pytest.approx(9.9) and dp.FALLBACK_FLAG in s.adj_close("LATE", "2021-01-31").flags
    e = s.entry_point("LATE", "2021-01-31")
    assert e.price == pytest.approx(9.9) and dp.FALLBACK_FLAG in e.flags and "no_next_session_in_monthly_data" in e.flags       # a monthly bar has no next session
    assert s.price_quality("LATE", "2021-01-31")[0] == "unverified"


def test_the_fallback_applies_only_to_the_late_start_case(tmp_path):
    s = _fallback(tmp_path)
    assert s.close_unadjusted("FULL", "2020-01-01").flags == () and s.close_unadjusted("FULL", "2020-12-31") is not None and s.close_unadjusted("FULL", "2020-12-31").price != 999.0
    assert not s.has_key("NOD5") and s.close_unadjusted("NOD5", "2020-12-31") is None                  # a ticker D5 does not hold is not a key
    assert s.close_unadjusted("LATE", "2021-04-30") is not None                                          # the daily history has started
    assert s.close_unadjusted("LATE", "2021-03-02").flags == ()
    assert s.close_unadjusted("LATE", "2021-04-30").bar != "2021-04"
    assert s.late("LATE", "2021-02-28") and not s.late("LATE", "2021-03-01") and not s.late("FULL", "2020-06-30")


def test_the_late_ticker_has_splits_from_both_sources_and_the_delisting_events_of_the_daily_source(tmp_path):
    d5 = tmp_path / "d5s"
    d5.mkdir()
    write(d5, "LATE", [("2021-03-01", 1, 20.0, 20.0, 0), ("2021-04-01", 1, 21.0, 21.0, 2.0), ("2021-05-03", 1, 22.0, 22.0, 0)])
    monthly = pdm.MonthlyRawPriceSource({"prices": {"LATE": {"2020-11": [10.0, 10.0, 0.0, 3.0], "2021-01": [11.0, 11.0, 0.0, 0.0]}}})
    ev_ = {"LATE": {"date": "2021-06-01", "type": "bankruptcy"}}
    s = dp.FallbackPriceSource(dp.LazyDailyPriceSource(d5), monthly, delistings=ev_)
    assert s.splits("LATE") == [("2020-11", 3.0), ("2021-04-01", 2.0)]                                  # the monthly split before D5 starts, then D5's own, exact
    assert s.delisting("LATE") == ev_["LATE"] and s.last_date("LATE") == "2021-05-03" and s.splits("NOPE") is None


def test_the_outcome_flag_carries_the_fallback_stamp(tmp_path):
    s = _fallback(tmp_path)
    pit = pdm.PitData("unused", price_source=s)
    o = outcomes.horizon_outcome(pit, "LATE", "2021-01-31", 3)                                           # entry from the monthly bar, exit from the daily one
    assert o["status"] == "observed" and "price_monthly_fallback" in o["flags"] and "no_next_session_in_monthly_data" in o["flags"]
