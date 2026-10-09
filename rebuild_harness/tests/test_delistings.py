import json

import pytest

from rebuild_harness import delistings as D, metrics as M, outcomes, run_harness
from rebuild_harness.tests.test_outcomes_prices import days, _delisted_world
from rebuild_harness.tests.test_run_harness import build_world
from valuation.pit_data import DailyPriceSource, PitData


def subs(forms):
    """A submissions document from [(form, date, items)]."""
    return {"name": "X", "filings": {"recent": {"form": [f[0] for f in forms], "filingDate": [f[1] for f in forms],
                                                  "items": [f[2] if len(f) > 2 else "" for f in forms],
                                                  "accessionNumber": [f"a{i}" for i in range(len(forms))]}}}


def classify(forms):
    return D.classify_company("0000000001", D.filings_of(subs(forms)))


def test_an_acquisition_is_completion_item_2_01_with_a_delisting_notice_or_change_of_control():
    e = classify([("10-K", "2019-03-01"), ("8-K", "2020-05-01", "1.01"), ("8-K", "2020-06-10", "2.01,3.01,5.01,9.01"), ("25", "2020-06-12"), ("15-12B", "2020-06-22")])
    assert e["class"] == "acquisition_completed" and e["date"] == "2020-06-12" and {x["form"] for x in e["evidence"]} == {"25", "8-K"}
    assert classify([("8-K", "2020-06-10", "2.01"), ("25", "2020-06-12")])["class"] == "acquisition_weak"           # 2.01 alone: maybe the acquirer


def test_a_bankruptcy_is_item_1_03_before_the_exit_and_wins_over_the_rest():
    assert classify([("8-K", "2019-01-15", "1.03,9.01"), ("25-NSE", "2019-03-01")])["class"] == "bankruptcy"
    assert classify([("8-K", "2017-01-15", "1.03"), ("25", "2019-03-01")])["class"] == "delisted_other"              # more than 540 days earlier
    assert classify([("8-K", "2019-01-15", "1.03")])["class"] == "bankruptcy_no_exit_record"


def test_other_exits_and_no_event():
    assert classify([("10-K", "2019-03-01"), ("25", "2020-01-02")])["class"] == "delisted_other"
    # the company kept reporting after the Form 25 (notes or preferred delisted, or an exchange move): not a delisting of the common stock
    assert classify([("10-K", "2019-03-01"), ("25", "2020-01-02"), ("10-K", "2021-03-01")])["class"] == "exit_record_still_reporting"
    assert classify([("8-K", "2019-01-15", "1.03"), ("25", "2019-03-01"), ("10-K", "2020-03-01")])["class"] == "bankruptcy"      # reporting through Chapter 11
    assert classify([("10-K", "2019-03-01"), ("15-12G", "2020-01-02")])["class"] == "deregistered_other"
    assert classify([("10-K", "2019-03-01"), ("8-K", "2019-04-01", "2.02")]) is None


def test_counts_per_class_per_year_and_per_valuation_date(tmp_path):
    (tmp_path / "CIK0000000001.json").write_text(json.dumps(subs([("8-K", "2019-01-15", "1.03"), ("25", "2019-03-01")])), encoding="utf-8")
    (tmp_path / "CIK0000000002.json").write_text(json.dumps(subs([("8-K", "2020-06-10", "2.01,5.01"), ("25", "2020-06-12")])), encoding="utf-8")
    (tmp_path / "CIK0000000003.json").write_text(json.dumps(subs([("10-K", "2020-03-01")])), encoding="utf-8")
    ev = D.classify_dir(tmp_path)
    assert D.counts_per_class_per_year(ev) == {"2019": {"bankruptcy": 1}, "2020": {"acquisition_completed": 1}}
    assert D.counts_for_valuation_dates(ev, ["2018-06-29", "2020-06-30"]) == {"2018-06-29": {"bankruptcy": 1, "acquisition_completed": 1}, "2020-06-30": {}}


def test_the_readers_are_strict_and_default_to_not_decided():
    assert D.read_cash_consideration("each share will be converted into the right to receive $45.00 in cash, without interest") == 45.0
    assert D.read_cash_consideration("holders may elect to receive $45.00 in cash or shares of the Parent common stock") is None       # stock words
    assert D.read_cash_consideration("$45.00 per share in cash ... or $47.50 per share") is None                                         # two amounts
    assert D.read_cash_consideration(None) is None
    assert D.read_equity_cancelled("All existing common stock will be cancelled and holders of common stock will not receive any distribution under the plan") is True
    assert D.read_equity_cancelled("existing common stock will be cancelled in exchange for warrants") is None


def test_events_become_price_events_only_when_a_reader_resolves_them():
    ev = [{"cik": "0000000001", "date": "2020-03-01", "class": "acquisition_completed", "evidence": []},
          {"cik": "0000000002", "date": "2020-03-01", "class": "bankruptcy", "evidence": []},
          {"cik": "0000000003", "date": "2020-03-01", "class": "delisted_other", "evidence": []}]
    tk = lambda cik: {"0000000001": ["A"], "0000000002": ["B"], "0000000003": ["C"]}[cik]
    none = D.to_price_events(ev, tk)
    assert {k: v["type"] for k, v in none.items()} == {"A": "unresolved_acquisition_completed", "B": "unresolved_bankruptcy", "C": "unresolved_delisted_other"}
    texts = {"0000000001": "right to receive $60.00 in cash", "0000000002": "common stock will be cancelled; holders will not receive any distribution"}
    got = D.to_price_events(ev, tk, lambda e: texts.get(e["cik"]))
    assert got["A"]["type"] == "acquisition" and got["A"]["cash_per_share"] == 60.0 and got["B"]["type"] == "bankruptcy" and got["C"]["type"].startswith("unresolved")


def test_an_unresolved_delisting_is_reported_under_three_bounds():
    pit = _delisted_world({"date": "2020-03-01", "type": "unresolved_acquisition_completed"})
    o = outcomes.horizon_outcome(pit, "A", "2020-01-10", 3)
    assert o["status"] == "OUTCOME_UNOBSERVABLE" and not o["available"] and o["excess"] is None
    assert o["bounds"]["excluded"] is None and o["bounds"]["minus100"] == -1.0
    assert o["bounds"]["last_close"] == pytest.approx(159.0 / 110.0 - 1.0)       # last bar 2020-02-29 at 159, entry 110, benchmark flat
    assert "history_ended_before_horizon" in o["flags"]
    o = outcomes.horizon_outcome(_delisted_world(None), "A", "2020-01-10", 3)    # no record at all: the same three bounds
    assert o["bounds"]["minus100"] == -1.0 and o["bounds"]["excluded"] is None
    ob = outcomes.horizon_outcome(_delisted_world(None), "SPY", "2020-01-10", 3)
    assert ob["status"] == "observed" and set(ob["bounds"].values()) == {ob["excess"]}      # observed: one value under every bound


def test_a_gap_that_trades_later_is_not_a_delisting():
    rows = {"A": {k: v for k, v in days("2020-01-01", 300, 100.0, 1.0).items() if not ("2020-04-05" <= k <= "2020-04-20")},
            "SPY": days("2020-01-01", 300, 300.0, 0.0)}
    pit = PitData("unused", price_source=DailyPriceSource(rows, splits={"A": [], "SPY": []}, max_gap_days=1))
    o = outcomes.horizon_outcome(pit, "A", "2020-01-10", 3)                      # exit 2020-04-10 falls in the gap; the stock trades after it
    assert o["status"] == "OUTCOME_UNOBSERVABLE" and "gap_not_delisting" in o["flags"] and o["bounds"]["minus100"] is None


def test_gate_status_is_not_decided_when_the_bounds_straddle_the_bar():
    assert M.gate_status({"excluded": 0.05, "minus100": 0.04, "last_close": 0.045}, 0.03) == "pass"
    assert M.gate_status({"excluded": 0.05, "minus100": 0.01, "last_close": 0.045}, 0.03) == "not decided"
    assert M.gate_status({"excluded": 0.02, "minus100": 0.01, "last_close": 0.0}, 0.03) == "fail"
    assert M.gate_status({"excluded": float("nan"), "minus100": 0.4, "last_close": 0.4}, 0.03) == "not decided"
    assert M.gate_status({"excluded": 0.1, "minus100": 0.2}, 0.3, "<=") == "pass"


def test_view_for_bound_replaces_the_excess_and_leaves_observed_outcomes_alone():
    recs = [{"excess": {12: 0.1}, "bounds": {12: {"excluded": 0.1, "minus100": 0.1, "last_close": 0.1}}},
            {"excess": {12: None}, "bounds": {12: {"excluded": None, "minus100": -1.2, "last_close": -0.3}}}]
    assert [r["excess"][12] for r in M.view_for_bound(recs, "excluded")] == [0.1, None]
    assert [r["excess"][12] for r in M.view_for_bound(recs, "minus100")] == [0.1, -1.2]
    assert [r["excess"][12] for r in M.view_for_bound(recs, "last_close")] == [0.1, -0.3]


def test_the_runner_reports_every_metric_under_the_three_bounds(tmp_path):
    pit, ciks = build_world(tmp_path)
    for i in range(0, 8):                                                       # eight companies' price history ends before the 12-month horizon
        rows = pit.price_source.prices[f"T{i}"]
        for k in [k for k in rows if k > "2018-12"]:
            del rows[k]
    res = run_harness.run(["2018-06-29"], ciks, ["yardstick_earnings_yield"], pit, tmp_path / "out", n_resamples=20)
    s = res["summary"]
    assert s["bound"] == "excluded" and set(s["other_bounds"]) == {"minus100", "last_close"}
    n_ex = s["engines"]["yardstick_earnings_yield"]["horizons"]["12"]["ic_by_date"]["2018-06-29"]["n"]
    n_m100 = s["other_bounds"]["minus100"]["engines"]["yardstick_earnings_yield"]["horizons"]["12"]["ic_by_date"]["2018-06-29"]["n"]
    assert n_ex == 40 - 8 and n_m100 == 40                                      # excluded drops them; at -100% they count
    assert res["coverage"]["dates"]["2018-06-29"]["unresolved_delistings"]["12"] == 8


# ---- Addendum P4: every exit event of a company ---------------------------------------------------------------------------------------------------------------

def events_of(forms, cik="0000000001"):
    return D.classify_exit_events(cik, D.filings_of(subs(forms)))


def test_p4_a_notes_delisting_then_the_common_stock_are_two_events_and_a_form_15_after_its_form_25_is_one():
    forms = [("10-K", "2019-03-01"), ("25", "2020-01-02"), ("10-Q", "2020-11-01"), ("10-K", "2021-03-01"),                 # a Form 25 for notes: the company kept reporting
             ("8-K", "2022-02-10", "2.01,3.01"), ("25", "2022-03-01"), ("15-12B", "2022-03-08")]                            # the common stock leaves, a Form 15 a week later
    evs = events_of(forms)
    assert [(e["date"], e["class"]) for e in evs] == [("2020-01-02", "exit_record_still_reporting"), ("2022-03-01", "acquisition_completed")]
    assert D.classify_company("0000000001", D.filings_of(subs(forms)))["date"] == "2020-01-02"                           # D1 keeps the first only
    assert evs[1]["evidence"][0]["form"] == "25" and {x["form"] for x in evs[1]["evidence"]} == {"25", "8-K"}


def test_p4_a_form_15_far_from_the_form_25_is_its_own_event_and_a_single_cluster_equals_the_first_event_rule():
    forms = [("10-K", "2019-03-01"), ("25", "2020-01-02"), ("15-12G", "2021-06-01")]                                      # 17 months apart: two events
    assert [(e["date"], e["class"]) for e in events_of(forms)] == [("2020-01-02", "delisted_other"), ("2021-06-01", "deregistered_other")]
    for single in ([("10-K", "2019-03-01"), ("25", "2020-01-02")],
                   [("8-K", "2019-01-15", "1.03,9.01"), ("25-NSE", "2019-03-01")],
                   [("8-K", "2020-06-10", "2.01,3.01,5.01,9.01"), ("25", "2020-06-12"), ("15-12B", "2020-06-22")],
                   [("10-K", "2019-03-01"), ("15-12G", "2020-01-02")],
                   [("10-K", "2019-03-01"), ("25", "2020-01-02"), ("10-K", "2021-03-01")],
                   [("8-K", "2019-01-15", "1.03")]):
        assert events_of(single) == [classify(single)], single                                                           # one cluster: the same event, the same evidence
    assert events_of([("10-K", "2019-03-01"), ("8-K", "2019-04-01", "2.02")]) == []


def test_p4_the_cluster_gap_is_a_parameter_and_the_event_date_is_the_first_form_25():
    forms = [("25", "2020-01-02"), ("15-12B", "2020-02-20")]                                                              # 49 days apart
    assert len(D.classify_exit_events("0000000001", D.filings_of(subs(forms)))) == 2
    assert len(D.classify_exit_events("0000000001", D.filings_of(subs(forms)), cluster_days=60)) == 1
    # a Form 15 that comes first in a cluster does not make the event a deregistration when a Form 25 is in it
    cl = events_of([("15-12B", "2020-01-02"), ("25", "2020-01-10")])
    assert [(e["date"], e["class"]) for e in cl] == [("2020-01-10", "delisted_other")]


# ---- Addendum P3: the reader declines on the residue the par-value guard left -------------------------------------------------------------------------------------

def test_p3_the_reader_declines_on_warrants_exercise_prices_liquidating_distributions_redemption_values_trust_accounts_and_spac_cover_text():
    price = "Each share of common stock was converted into the right to receive $12.05 in cash."
    assert D.read_cash_consideration(price) == 12.05
    for decline in ("Each warrant was converted into a warrant to purchase shares at an exercise price of $0.75 per share.",
                    "The Company's warrants entitle holders to purchase one share at $11.50 per share.",
                    "Holders will receive a liquidating distribution of $3.20 per share in cash.",
                    "Holders exercised their right to redeem at a redemption price of approximately $10.10 per share.",
                    "The redemption value was $10.05 per share, paid from the Trust Account.",
                    "An aggregate of $195,826,566 was removed from the trust account, or $10.10 per share.",
                    "Units, each consisting of one share of Class A common stock and one-half of one redeemable warrant, at $11.50 per share.",
                    "GXII:WarrantsEachExercisableForOneShareClassCommonStockFor11.50PerShareMember 2023-03-16 $11.50 per share."):
        assert D.read_cash_consideration(decline) is None, decline
        assert D.read_cash_consideration(price + " " + decline) is None, decline                       # the decline sentence states an amount too: the whole reading declines
    assert D.read_cash_consideration(price + " The Company has warrants outstanding.") == 12.05       # a word in a sentence that states no per-share amount does not decline
    assert D.read_cash_consideration("Each unit consisting of one share was converted into the right to receive $12.05 in cash.") == 12.05
    # a SPAC's cover page anywhere in the document declines it whole, even when the sentence that states the amount has none of the words
    spac = "UnitsEachConsistingOfOneClassOrdinaryShareAndOnehalfOfRedeemableWarrantMember 2024-08-15 FORM 8-K Units, each consisting of one Class A ordinary share and one-half of one redeemable warrant. "
    assert D.read_cash_consideration(spac + "Greenstar agreed to purchase 200,000 shares at a price of $10.00 per share.") is None
    assert D.read_cash_consideration("dei:FormerAddressMember us-gaap:CommonStockMember 2024-08-15 FORM 8-K. " + price) == 12.05           # an ordinary inline-XBRL header is not a SPAC cover page


def test_p3_the_report_only_pattern_is_inert_when_swapped_out_and_stock_words_still_apply():
    import re
    saved, saved_doc = D._P3_WORDS, D._P3_DOC_WORDS
    try:
        D._P3_WORDS = D._P3_DOC_WORDS = re.compile(r"(?!x)x")
        assert D.read_cash_consideration("Each warrant had an exercise price of $0.75 per share.") == 0.75        # what the reader said before P3 (the yield script's stage E)
    finally:
        D._P3_WORDS, D._P3_DOC_WORDS = saved, saved_doc
    assert D.read_cash_consideration("Each warrant had an exercise price of $0.75 per share.") is None
    assert D.read_cash_consideration("Each share was converted into $5.00 in cash or, at the holder's election, stock.") is None


def test_r2_the_reader_declines_on_a_declared_dividend_or_distribution():
    price = "Each share of common stock was converted into the right to receive $12.05 in cash."
    assert D.read_cash_consideration(price) == 12.05
    for decline in ("On June 2, 2024, the Company's board of directors declared a distribution of $0.0944 per share, payable on June 6, 2024.",
                    "The board of directors declared a special cash dividend of $0.25 per share of Company Common Stock.",
                    "The board has declared a stub period cash dividend in an amount equal to $0.1462 per share."):
        assert D.read_cash_consideration(decline) is None, decline
        assert D.read_cash_consideration(price + " " + decline) is None, decline
    assert D.read_cash_consideration("On June 2, 2024, the board declared a distribution of $0.0944 per share.") is None
    # a word elsewhere that states no per-share amount, and "Dividend Adjustments" in an offer price, do not decline
    assert D.read_cash_consideration(price + " The board declared the Offer fair to holders.") == 12.05
    assert D.read_cash_consideration("The offer price is $10.20 per Share in cash, less any Dividend Adjustments.") == 10.2
