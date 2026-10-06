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
