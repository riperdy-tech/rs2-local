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


def _world(tmp_path, extra=False, exit_records=None, p4=False, missing_doc=False):
    """With `extra`: company 9 (a Form 25 for another security: class exit_record_still_reporting, dated 2021-12-15) and company 10 (a first Form 25 on 2020-12-01, before T).  Companies: 1 acquired for cash after T; 5 bankrupt after T; 6 delisted for no stated reason after T; 2 below the float floor; 3 still priced at T (D5 holds it); 4 left before T; 7 no cover;
    8 no annual report known at T.  The D5 folder holds company 3 and SPY.
    `p4` (implies `extra`): an index with `events_all.json`: company 9 has a second event (a delisting dated 2022-03-01, after its Form 25 for another security), company 10 a second (2021-12-01, after T), and
    company 11 a Form 25 before T (a delisting of another security) and its cash acquisition on 2021-11-15.  `missing_doc`: company 1's Item 2.01 document is not on disk."""
    extra = extra or p4
    zpath = tmp_path / "cf.zip"
    docs = {}
    for i, fl in ((1, 900e6), (2, 100e6), (3, 700e6), (4, 900e6), (5, 600e6), (6, 450e6), (8, 900e6)) + (((9, 900e6), (10, 800e6)) if extra else ()) + (((11, 700e6),) if p4 else ()):
        docs[f"CIK{i:010d}.json"] = _company(i, f"Co{i}", [_fact("2020-06-30", fl, f"C{i}-20", "2021-03-01")], [_fact("2021-02-15", 50e6 if i != 6 else 30e6, f"C{i}-20", "2021-03-01")])
    with zipfile.ZipFile(zpath, "w") as z:
        for n, d in docs.items():
            z.writestr(n, json.dumps(d))
    sv.build_cover_index(zpath, tmp_path / "cover", workers=1)
    events = [ev("0000000001", "acquisition_completed", "2021-11-15", "A-1", ["2.01"]), ev("0000000002", "acquisition_completed", "2021-11-15", "A-2", ["2.01"]),
              ev("0000000003", "acquisition_completed", "2021-11-15", "A-3", ["2.01"]), ev("0000000004", "bankruptcy", "2021-01-15", "A-4", ["1.03"]),
              ev("0000000005", "bankruptcy", "2021-09-15", "A-5", ["1.03"]), ev("0000000006", "delisted_other", "2021-10-01", "A-6", []),
              ev("0000000007", "delisted_other", "2021-10-01", "A-7", []), ev("0000000008", "delisted_other", "2021-12-01", "A-8", [])]
    if extra:
        events += [ev("0000000009", "exit_record_still_reporting", "2021-12-15", "A-9", []), ev("0000000010", "delisted_other", "2020-12-01", "A-10", [])]
    if p4:
        events += [ev("0000000011", "delisted_other", "2020-10-01", "A-11x", [])]
    idx, docs3 = build(tmp_path, events, {("0000000001", "A-1"): None if missing_doc else CASH_8K, ("0000000005", "A-5"): BK_8K, **({("0000000011", "A-11"): CASH_8K} if p4 else {})})
    if p4:
        from rebuild_harness import delisting_inputs as di
        second = []
        for cik, cls, date, acc, items in (("0000000009", "delisted_other", "2022-03-01", "A-9b", []), ("0000000010", "delisted_other", "2021-12-01", "A-10b", []),
                                           ("0000000011", "acquisition_completed", "2021-11-15", "A-11", ["2.01"])):
            e = ev(cik, cls, date, acc, items)
            e["evidence"][0]["accession"] = acc + "-25"
            second.append(e)
        (tmp_path / "d1" / "events_all.json").write_text(json.dumps(events + second), encoding="utf-8")
        idx = di.EventIndex(tmp_path / "d1")
    d5 = tmp_path / "d5"
    d5.mkdir()
    write(d5, "THREE", run("2021-05-01", 120, 50.0, 0.1))
    write(d5, "SPY", run("2021-05-01", 700, 400.0, 0.5))
    src = dp.LazyDailyPriceSource(d5)
    store = tmp_path / "store"
    for i in (1, 2, 3, 4, 5, 6) + ((9, 10) if extra else ()) + ((11,) if p4 else ()):
        synth.simple_company(store, i, 6)                          # an annual report known at T (the last is the 2020 one, filed 2021-03-01)
    # company 8: its first annual report is filed after T
    synth.simple_company(store, 8, 1, first_year=2021)
    pit = pdm.PitData(store, price_source=src)
    tk = {"0000000003": ["THREE"]}
    return sv.Survivorship(sv.CoverIndex(tmp_path / "cover"), idx, docs3, lambda c: tk.get(c, []), src, exit_records=exit_records), pit, src


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


def test_a_delisted_other_event_inside_the_horizon_is_excluded_minus_100_or_the_proxy_price_held(tmp_path):
    surv, pit, src = _world(tmp_path)
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000006"], src, T, 12)        # a delisting with no reader for its class, inside the horizon
    b = _bench(src, T)
    assert o["status"] == outcomes.UNOBSERVABLE and not o["available"] and o["excess"] is None and o["ret"] is None
    assert o["bounds"] == {"excluded": None, "minus100": pytest.approx(-1.0 - b), "last_close": pytest.approx(0.0 - b)}          # Addendum P1: an exchange delisting inside the horizon is bounded as distress
    assert o["bounds_basis"] == {"minus100": sv.MINUS100_BASIS}
    assert any(f.startswith("unobservable_delisting:unresolved_delisted_other") for f in o["flags"])


def test_p1_the_pessimistic_bound_by_event_class_inside_the_horizon_and_after_it(tmp_path):
    surv, pit, src = _world(tmp_path)
    surv.docs = None                                                    # no documents: no reader resolves anything
    surv._price_events.clear()
    base = surv.items_by_cik(T, pit)["0000000006"]                       # inside the 12-month horizon
    b = _bench(src, T)
    for cls in ("bankruptcy", "bankruptcy_no_exit_record", "delisted_other", "deregistered_other"):
        o = surv.outcome(dict(base, **{"class": cls}), src, T, 12)
        assert o["bounds"]["minus100"] == pytest.approx(-1.0 - b) and o["bounds"]["last_close"] == pytest.approx(0.0 - b) and o["bounds"]["excluded"] is None, cls
        assert o["bounds_basis"] == {"minus100": sv.MINUS100_BASIS}, cls
        late = surv.outcome(dict(base, **{"class": cls}, event_date="2022-09-15"), src, T, 12)        # after the horizon: the date's p10, whatever the class
        assert late["bounds"]["minus100"] is None and late["bounds_basis"] == {"minus100": sv.P10_BASIS} and "event_after_horizon" in late["flags"], cls
    for cls in ("acquisition_completed", "acquisition_weak"):             # an acquisition no reader resolves: acquisitions are usually at a premium, the p10
        o = surv.outcome(dict(base, **{"class": cls}), src, T, 12)
        assert o["bounds"]["minus100"] is None and o["bounds_basis"] == {"minus100": sv.P10_BASIS} and o["bounds"]["last_close"] == pytest.approx(0.0 - b), cls
    assert set(sv.MINUS100_CLASSES) == {"bankruptcy", "bankruptcy_no_exit_record", "delisted_other", "deregistered_other"}


def test_a_bankruptcy_class_event_inside_the_horizon_that_no_reader_resolves_keeps_the_minus_100_bound(tmp_path):
    surv, pit, src = _world(tmp_path)
    surv.docs = None                                                    # no documents: the Item 1.03 text cannot be read
    surv._price_events.clear()
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000005"], src, T, 12)
    b = _bench(src, T)
    assert o["status"] == outcomes.UNOBSERVABLE and o["bounds"] == {"excluded": None, "minus100": pytest.approx(-1.0 - b), "last_close": pytest.approx(0.0 - b)} and o["bounds_basis"] == {"minus100": sv.MINUS100_BASIS}
    late = dict(surv.items_by_cik(T, pit)["0000000005"], event_date="2022-09-15")                 # the same bankruptcy dated after the horizon is not a death inside it
    o2 = surv.outcome(late, src, T, 12)
    assert "event_after_horizon" in o2["flags"] and o2["bounds"]["minus100"] is None and o2["bounds_basis"] == {"minus100": sv.P10_BASIS}


def test_an_acquisition_the_strict_reader_declines_is_unobservable_and_so_is_an_event_after_the_horizon(tmp_path):
    surv, pit, src = _world(tmp_path)
    surv.docs = build_stock(tmp_path)                                  # the same event, now read from a stock-and-cash text: the reader declines
    surv._price_events.clear()
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000001"], src, T, 12)
    assert o["status"] == outcomes.UNOBSERVABLE and o["bounds"]["excluded"] is None and o["bounds"]["minus100"] is None and o["bounds"]["last_close"] == pytest.approx(0.0 - _bench(src, T))
    assert o["bounds_basis"] == {"minus100": sv.P10_BASIS}
    late = dict(surv.items_by_cik(T, pit)["0000000001"], event_date="2022-09-15")                   # after the 12-month horizon (2022-06-30): the company still traded then
    surv._price_events.clear()
    o2 = surv.outcome(late, src, T, 12)
    assert o2["status"] == outcomes.UNOBSERVABLE and "event_after_horizon" in o2["flags"] and o2["bounds"]["excluded"] is None
    assert o2["bounds"]["minus100"] is None and o2["bounds_basis"] == {"minus100": sv.P10_BASIS} and o2["bounds"]["last_close"] == pytest.approx(0.0 - _bench(src, T))      # N1: excluded, p10, held


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


def test_a_par_value_is_not_a_price():
    assert D.read_cash_consideration("each share of common stock, par value $0.0001 per share, of the Company was converted into the right to receive a promissory note.") is None
    assert D.read_cash_consideration("each Class A ordinary share, par value US$0.0001 per share, of the Company was converted into one share of the surviving company.") is None
    assert D.read_cash_consideration("each share of common stock, par value $0.0001 per share, of the Company was converted into the right to receive $12.05 in cash.") == 12.05
    assert D.read_cash_consideration("Purchaser tendered for all shares of common stock, $0.01 par value per share, at $9.10 per share in cash.") == 9.10
    assert D.read_cash_consideration("Purchaser tendered for all shares of common stock, $0.01 per share par value, at $9.10 per share in cash.") == 9.10
    assert D.read_cash_consideration("each share of common stock, par value of $0.01 per share, was converted into the right to receive $0.35 in cash.") == 0.35       # a genuine penny price still counts
    assert D.consideration_sentences("The shares have a par value $0.01 per share. Each share was converted into the right to receive $5.00 in cash.") == ["Each share was converted into the right to receive $5.00 in cash."]


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


# ---- N2: a Form 25 for another security is not a delisting of the common ------------------------------------------------------------------------------------------

def test_exit_record_still_reporting_is_not_in_the_census_and_is_counted_apart(tmp_path):
    surv, pit, _src = _world(tmp_path, extra=True)
    c = surv.census(T, pit)
    assert "0000000009" not in {i["cik"] for i in c["items"]} and c["counts"]["dropped_class:exit_record_still_reporting"] == 1
    assert c["counts"]["events_after_T"] == 8 and c["counts"]["census"] == 3                    # the seven events of the plain world, and company 9, which only the drop keeps out


# ---- N4: the share count of the price proxy is the latest 10-K or 10-Q cover before T ------------------------------------------------------------------------------

def _two_covers_zip(tmp_path):
    p = tmp_path / "cf4.zip"
    docs = {"CIK0000000001.json": _company(1, "Alpha", [_fact("2020-06-30", 900e6, "A-20", "2021-03-02")],
                                           [_fact("2021-02-15", 50e6, "A-20", "2021-03-02", "10-K"), _fact("2021-04-20", 48e6, "A-Q1", "2021-05-05", "10-Q"),
                                            _fact("2021-04-20", 2e6, "A-Q1", "2021-05-05", "10-Q"), _fact("2021-07-20", 45e6, "A-Q2", "2021-08-04", "10-Q"),
                                            _fact("2021-08-01", 99e6, "A-S1", "2021-08-20", "S-1")]),     # not a 10-K / 10-Q cover: never read
            "CIK0000000002.json": _company(2, "Beta", [_fact("2020-06-30", 500e6, "B-20", "2021-03-02")], [_fact("2021-04-20", 25e6, "B-Q1", "2021-05-05", "10-Q")])}      # the 10-K cover states no count; a 10-Q does
    with zipfile.ZipFile(p, "w") as z:
        for n, d in docs.items():
            z.writestr(n, json.dumps(d))
    return p


def test_the_proxy_share_count_is_the_latest_10k_or_10q_cover_filed_before_T_not_only_the_floats_cover(tmp_path):
    sv.build_cover_index(_two_covers_zip(tmp_path), tmp_path / "cover4", workers=1)
    idx = sv.CoverIndex(tmp_path / "cover4")
    c = idx.latest("0000000001", "2021-06-30")                                # the 10-Q filed 2021-05-05 is newer than the 10-K that states the float
    assert c["accession"] == "A-20" and c["public_float"] == 900e6 and c["shares_accession"] == "A-Q1" and c["shares_form"] == "10-Q" and c["shares"] == 50e6 and c["price_proxy"] == pytest.approx(18.0)
    assert idx.latest("0000000001", "2021-05-05")["shares_accession"] == "A-20" and idx.latest("0000000001", "2021-05-05")["shares"] == 50e6      # filed ON the date: not known
    c2 = idx.latest("0000000001", "2021-12-31")
    assert c2["shares_accession"] == "A-Q2" and c2["shares"] == 45e6 and c2["price_proxy"] == pytest.approx(20.0) and c2["accession"] == "A-20"      # the S-1's 99e6 is not a 10-K / 10-Q cover
    b = idx.latest("0000000002", "2021-12-31")
    assert b["shares"] == 25e6 and b["price_proxy"] == pytest.approx(20.0) and b["shares_accession"] == "B-Q1"                    # N4 gives a proxy where the 10-K cover alone gave none
    assert idx.latest("0000000002", "2021-04-01")["shares"] is None and idx.latest("0000000002", "2021-04-01")["price_proxy"] is None   # no such cover before the date: still no proxy


def test_the_census_items_carry_the_share_cover_and_count_the_priced_ones(tmp_path):
    surv, pit, _src = _world(tmp_path)
    c = surv.census(T, pit)
    assert c["counts"]["census_with_price_proxy"] == 3 and "census_no_shares_on_cover" not in c["counts"]
    i = surv.items_by_cik(T, pit)["0000000001"]
    assert i["shares_accession"] == "C1-20" and i["shares_form"] == "10-K" and i["shares_filed"] == "2021-03-01"


# ---- N6: one dividing line ----------------------------------------------------------------------------------------------------------------------------------------

class _LastWeekdayTarget:
    """A monthly source's horizon date (the last weekday of the month): where it differs from the same calendar day the old census flag and the outcome disagreed."""

    def __init__(self, base):
        self._b = base

    def __getattr__(self, name):
        return getattr(self._b, name)

    def target_date(self, asof, months):
        return pdm._last_weekday_of_month(pdm.add_months(pdm.to_date(asof), months))


def test_the_census_flag_and_the_outcome_use_the_same_dividing_line_the_horizon_date_of_the_source(tmp_path):
    surv, pit, src = _world(tmp_path)
    wk = _LastWeekdayTarget(src)
    surv.src = wk                                                                  # T + 10 months: the same day is Saturday 2022-04-30, the horizon date is Friday 2022-04-29
    assert surv.horizon_date(T, 10) == "2022-04-29"
    assert sv.event_after_horizon("2022-04-29", "2022-04-29") is False and sv.event_after_horizon("2022-04-30", "2022-04-29") is True
    surv._events = [dict(e, date="2022-04-30") if e["cik"] == "0000000006" else e for e in surv._events]
    item = {i["cik"]: i for i in surv.census(T, pit, 10)["items"]}["0000000006"]
    assert item["within_horizon"] is False and "event_after_horizon" in surv.outcome(item, wk, T, 10)["flags"]          # both say: after the horizon
    on_the_line = dict(item, event_date="2022-04-29")
    assert "event_after_horizon" not in surv.outcome(on_the_line, wk, T, 10)["flags"]                                  # an event ON the horizon date is inside it


# ---- N1: the date's cross-sectional 10th percentile ---------------------------------------------------------------------------------------------------------------

def _rec(cik, excess, group=">=300M", surv_item=None, basis=None, bounds=None):
    r = {"cik": cik, "mcap_group": group, "excess": {12: excess}, "bounds": {12: bounds or {"excluded": None, "minus100": excess, "last_close": excess}}}
    if surv_item:
        r["survivorship"] = surv_item
    if basis:
        r["bounds_basis"] = {12: basis}
    return r


def test_the_pessimistic_bound_of_an_unobservable_name_is_the_dates_cross_sectional_10th_percentile_of_the_gate_universe():
    import numpy as np
    obs = [i / 100.0 for i in range(-40, 61)]                                      # 101 observed excess returns in the gate universe
    recs = [_rec(f"{i:010d}", x) for i, x in enumerate(obs, 1)]
    recs.append(_rec("0000000900", -0.99, group="<300M"))                          # below the floor: not in the cross-section
    recs.append(_rec("0000000901", -0.95, surv_item={"stamp": "x"}))               # a census name: not in the cross-section
    recs.append(_rec("0000000902", None))                                          # no measured excess
    pending = _rec("0000000903", None, surv_item={"stamp": "x"}, basis={"minus100": sv.P10_BASIS}, bounds={"excluded": None, "minus100": None, "last_close": -0.1})
    resolved = _rec("0000000904", 0.3, surv_item={"stamp": "x"})
    recs += [pending, resolved]
    stats = sv.fill_cross_section_bounds(recs)
    want = float(np.percentile(obs, 10))
    assert stats[12]["n"] == 101 and stats[12]["p10"] == pytest.approx(want) and want == pytest.approx(-0.30)
    assert pending["bounds"][12] == {"excluded": None, "minus100": pytest.approx(want), "last_close": -0.1} and pending["bound_p10"][12]["n"] == 101
    assert resolved["bounds"][12]["minus100"] == 0.3 and "bound_p10" not in resolved                  # a resolved name keeps its value under every bound
    assert recs[0]["bounds"][12]["minus100"] == obs[0]                              # an observed name is untouched


def test_with_no_measured_excess_the_pessimistic_bound_stays_none():
    pending = _rec("0000000903", None, surv_item={"stamp": "x"}, basis={"minus100": sv.P10_BASIS}, bounds={"excluded": None, "minus100": None, "last_close": -0.1})
    stats = sv.fill_cross_section_bounds([pending])
    assert stats[12] == {"p10": None, "n": 0} and pending["bounds"][12]["minus100"] is None


def test_the_bounds_flow_into_the_registered_three_bound_rule_with_the_p10_in_the_minus100_slot(tmp_path):
    surv, pit, src = _world(tmp_path)
    surv.docs = build_stock(tmp_path)                                  # company 1 read from a stock-and-cash text: the acquisition is unresolved, its pessimistic bound is the date's p10
    surv._price_events.clear()
    o = surv.outcome(surv.items_by_cik(T, pit)["0000000001"], src, T, 12)
    rec = {"cik": "0000000001", "mcap_group": ">=300M", "survivorship": {"x": 1}, "excess": {12: o["excess"]}, "bounds": {12: o["bounds"]}, "bounds_basis": {12: o["bounds_basis"]}}
    other = _rec("0000000002", -0.2)
    sv.fill_cross_section_bounds([rec, other])
    view = {b: hm.view_for_bound([rec], b)[0]["excess"][12] for b in hm.BOUNDS}
    assert view["excluded"] is None and view["minus100"] == pytest.approx(-0.2) and view["last_close"] == pytest.approx(0.0 - _bench(src, T))


# ---- N3: the one-event-per-company limitation, counted where detectable --------------------------------------------------------------------------------------------

def test_build_exit_records_reads_every_form_25_and_15_and_the_periodic_dates_of_the_wanted_companies_including_older_pages(tmp_path):
    z = tmp_path / "subs.zip"

    def recent(forms, dates):
        return {"filings": {"recent": {"form": forms, "filingDate": dates, "items": [""] * len(forms), "accessionNumber": [f"a{i}" for i in range(len(forms))]},
                            "files": [{"name": "CIK0000000010-submissions-001.json"}]}}

    older = {"form": ["25-NSE", "10-Q"], "filingDate": ["2019-01-10", "2018-11-01"], "items": ["", ""], "accessionNumber": ["old", "oldq"]}
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("CIK0000000010.json", json.dumps(recent(["8-K", "25", "15-12B", "10-K"], ["2020-12-01", "2020-12-01", "2022-03-01", "2020-03-01"])))
        zz.writestr("CIK0000000010-submissions-001.json", json.dumps(older))
        zz.writestr("CIK0000000011.json", json.dumps(recent(["10-K"], ["2020-03-01"])))
        zz.writestr("CIK0000000012.json", json.dumps(recent(["25"], ["2021-01-01"])))
    got = sv.build_exit_records(z, ["0000000010", "0000000011"])
    assert got == {"0000000010": {"exit": ["2019-01-10", "2020-12-01", "2022-03-01"], "periodic": ["2018-11-01", "2020-03-01"]}}      # no exit record: absent; not wanted: absent; the older page is merged


def test_the_limitation_counters_count_the_detectable_second_exit_records(tmp_path):
    exits = {"0000000001": {"exit": ["2021-11-15", "2021-11-20"], "periodic": []},        # a census company with a Form 15 five days after its Form 25: same week
             "0000000005": {"exit": ["2021-09-15", "2022-03-01"], "periodic": []},        # a census company with a later record more than 30 days on
             "0000000009": {"exit": ["2021-12-15", "2022-06-01"], "periodic": []},        # company 9: the first Form 25 was for another security, the next is more than 30 days later
             "0000000010": {"exit": ["2020-12-01", "2022-03-01"], "periodic": ["2021-03-01"]},       # company 10: first event before T, still filing after it and before T; a second exit record inside the horizon
             "0000000004": {"exit": ["2021-01-15", "2021-12-20"], "periodic": []}}        # company 4 left on 2021-01-15 and filed its Form 15 later: not alive at T, not a miss
    surv, pit, _src = _world(tmp_path, extra=True, exit_records=exits)
    k = surv.census(T, pit)["counts"]
    assert k["limitation_census_later_exit_record"] == 2 and k["limitation_census_later_exit_record:gap_gt_30d"] == 1 and k["limitation_census_later_exit_record:gap_le_30d"] == 1
    assert k["limitation_missed_event_before_T"] == 1 and k["limitation_missed_event_before_T:next_exit_record_within_horizon"] == 1
    assert k["limitation_dropped_class_later_exit"] == 1 and k["limitation_dropped_class_later_exit:gap_gt_30d"] == 1
    assert k["census"] == 3                                                       # counted, never corrected: the census itself is unchanged
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    plain, pit2, _ = _world(plain_dir)
    assert not any(x.startswith("limitation_") for x in plain.census(T, pit2)["counts"])    # with no exit-record index the census does not count them


def test_the_run_attaches_the_survivor_outcome_with_its_bound_basis_and_fills_the_p10_from_the_dates_records(tmp_path):
    from datetime import date
    from rebuild_harness import gate1_run as g
    surv, pit, src = _world(tmp_path)
    surv.docs = build_stock(tmp_path)                                  # an unresolved acquisition: its pessimistic bound is the date's p10
    surv._price_events.clear()
    g._ENV["surv"] = surv
    try:
        item = surv.items_by_cik(T, pit)["0000000001"]
        rec = {"cik": "0000000001", "mcap_group": ">=300M", "survivorship": dict(item)}
        g._attach_outcomes(rec, pit, "0000000001", None, T, pit.snapshot("0000000001", T), horizons=(12,), outcomes_end=date(2030, 1, 1), survivor=item)
    finally:
        g._ENV.pop("surv", None)
    assert rec["bounds"][12]["minus100"] is None and rec["bounds_basis"] == {12: {"minus100": sv.P10_BASIS}} and rec["excess"][12] is None
    others = [_rec(f"{i:010d}", x / 100.0) for i, x in enumerate(range(-50, 51), 1)]
    sv.fill_cross_section_bounds(others + [rec])
    assert rec["bounds"][12]["minus100"] == pytest.approx(-0.40) and rec["bound_p10"][12]["n"] == 101


# ---- Addendum P4: the first qualifying exit event dated after T, from every event of the company -----------------------------------------------------------------

def test_p4_the_census_takes_the_first_qualifying_event_after_T_of_all_the_companys_events(tmp_path):
    (tmp_path / "one").mkdir()
    (tmp_path / "p4").mkdir()
    one, pit1, _ = _world(tmp_path / "one", extra=True)
    got1 = {i["cik"] for i in one.census(T, pit1)["items"]}
    assert got1 == {"0000000001", "0000000005", "0000000006"}                       # D1's one event per company: 9's Form 25 is of the dropped class, 10's is before T
    surv, pit, src = _world(tmp_path / "p4", p4=True)
    c = surv.census(T, pit)
    items = {i["cik"]: i for i in c["items"]}
    assert set(items) == got1 | {"0000000009", "0000000010", "0000000011"}          # all three found by an event dated after T that D1's first-event rule did not hold
    assert items["0000000009"]["event_date"] == "2022-03-01" and items["0000000009"]["event_accession"] == "A-9b-25"           # its dropped-class Form 25 (2021-12-15) is skipped
    assert items["0000000010"]["event_date"] == "2021-12-01"                                                                   # its first event (2020-12-01) is before T
    assert items["0000000011"]["event_date"] == "2021-11-15" and items["0000000011"]["class"] == "acquisition_completed"      # a Form 25 for another security before T does not hide it
    k = c["counts"]
    assert k["census"] == 6 and k["events_after_T"] == 10 and "dropped_class:exit_record_still_reporting" not in k          # company 9 now has a qualifying event after T
    assert all(i["within_horizon"] for i in items.values())
    assert not any(x.startswith("limitation_") for x in k)                          # the N3 counters are not produced: those cases are in the census


def test_p4_a_company_whose_only_events_after_T_are_of_the_dropped_class_stays_out_and_is_counted(tmp_path):
    surv, pit, _ = _world(tmp_path, extra=True)                                   # one event per company: company 9's only event is the dropped class
    c = surv.census(T, pit)
    assert "0000000009" not in {i["cik"] for i in c["items"]} and c["counts"]["dropped_class:exit_record_still_reporting"] == 1


def test_p4_the_outcome_of_a_picked_second_event_is_read_from_that_events_own_document(tmp_path):
    surv, pit, src = _world(tmp_path, p4=True)
    item = surv.items_by_cik(T, pit)["0000000011"]
    ev_, why = surv.price_event(item)
    assert why is None and ev_["type"] == "acquisition" and ev_["cash_per_share"] == 45.0 and ev_["date"] == "2021-11-15"
    o = surv.outcome(item, src, T, 12)
    assert o["status"] == outcomes.ACQUIRED and o["ret"] == pytest.approx(45.0 / item["price_proxy"] - 1.0)
    o9 = surv.outcome(surv.items_by_cik(T, pit)["0000000009"], src, T, 12)               # a delisting dated 2022-03-01, inside the horizon: no reader: -100%
    assert o9["status"] == outcomes.UNOBSERVABLE and o9["bounds"]["minus100"] == pytest.approx(-1.0 - _bench(src, T)) and o9["bounds_basis"] == {"minus100": sv.MINUS100_BASIS}


def test_p4_the_run_adds_the_new_census_names_to_the_dates_companies(tmp_path):
    surv, pit, _ = _world(tmp_path, p4=True)
    by = surv.items_by_cik(T, pit)
    assert {"0000000009", "0000000010", "0000000011"} <= set(by) and all(by[c]["price_proxy"] is not None for c in ("0000000009", "0000000010", "0000000011"))


# ---- Addendum P5: a missing D3 document leaves the event unresolved, counted ---------------------------------------------------------------------------------------

def test_p5_a_missing_document_leaves_the_event_unresolved_counted_and_with_the_p10_bound(tmp_path):
    surv, pit, src = _world(tmp_path, missing_doc=True)
    c = surv.census(T, pit)["counts"]
    assert c["census_event_unresolved_missing_document"] == 1 and c["census_event_unresolved_no_text"] == 1 and c["census"] == 3          # company 1: counted, still in the census
    item = surv.items_by_cik(T, pit)["0000000001"]
    ev_, why = surv.price_event(item)
    assert ev_["type"] == "unresolved_acquisition_completed" and why == "accession_not_in_d3_manifest"                          # never read as "no cash"
    o = surv.outcome(item, src, T, 12)
    assert o["status"] == outcomes.UNOBSERVABLE and o["bounds_basis"] == {"minus100": sv.P10_BASIS} and "unobservable_delisting:unresolved_acquisition_completed" in o["flags"]


def test_p5_with_every_document_on_disk_nothing_is_counted_as_missing(tmp_path):
    surv, pit, _ = _world(tmp_path)
    c = surv.census(T, pit)["counts"]
    assert "census_event_unresolved_missing_document" not in c and "census_event_unresolved_no_text" not in c
