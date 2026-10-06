"""End-to-end tests of the runner on a synthetic world: 40 companies, 10 annual reports each, monthly prices, SPY.  No network, no archive."""
import gzip
import json
from datetime import date, timedelta

import numpy as np
import pytest

from rebuild_harness import engines, outcomes, run_harness
from valuation.pit_data import PitData, MonthlyRawPriceSource
from valuation.tests import synth

N = 40
DATES = ["2018-06-29", "2019-06-28"]


def month_keys(y0=2015, y1=2023):
    return [f"{y}-{m:02d}" for y in range(y0, y1 + 1) for m in range(1, 13)]


def build_world(tmp_path, seed=1, price_after=None):
    """Companies i = 0..N-1: growth rises with i; price drifts with growth so a gross-profitability or growth signal has some information."""
    rng = np.random.default_rng(seed)
    store = tmp_path / "store"
    prices = {"SPY": {}}
    idm = {}
    for i in range(N):
        cik = i + 1
        synth.simple_company(store, cik, 10, base_rev=100 + 5 * i, growth=0.02 + 0.004 * i, margin=0.1 + 0.004 * i, first_year=2012)
        facts = []
        for y in range(2012, 2022):
            filed = (date(y, 12, 31) + timedelta(days=60)).isoformat()
            facts.append(synth.cover(f"{y + 1}-02-15", filed, 100.0, form="10-K", accn=f"cv{cik}-{y}"))
            facts += synth.annual_report(f"{y}-12-31", filed, {"WeightedAverageNumberOfDilutedSharesOutstanding": 100.0}, unit="shares", accn=f"sh{cik}-{y}")
        synth.append_facts(store, cik, facts)
        t = f"T{i}"
        idm[t] = str(cik)
        p, drift = 10.0 + i, 0.002 + 0.0004 * i
        prices[t] = {}
        for k in month_keys():
            p *= 1 + drift + rng.normal() * 0.01
            prices[t][k] = [p, p, 0.0, None]
    q = 100.0
    for k in month_keys():
        q *= 1.004
        prices["SPY"][k] = [q, q, 0.0, None]
    if price_after:
        for t in prices:
            for k in prices[t]:
                if k >= price_after:
                    prices[t][k][0] *= 5.0
                    prices[t][k][1] *= 5.0
    return PitData(store, price_source=MonthlyRawPriceSource({"prices": prices}), id_map=idm), [str(i + 1) for i in range(N)]


def test_end_to_end_on_a_synthetic_world(tmp_path):
    pit, ciks = build_world(tmp_path)
    res = run_harness.run(DATES, ciks, list(engines.YARDSTICKS), pit, tmp_path / "out", n_resamples=50)
    cov = res["coverage"]
    for d in DATES:
        c = cov["dates"][d]
        assert c["with_annual_report"] == N and c["records"] == N and c["window"] == "development"
        assert c["engine_scored"]["yardstick_earnings_yield"] == N
        assert c["outcome_available"]["36"]["available"] == N
        assert c["fund_outcome_available"]["1"] == N
    s = res["summary"]
    eyh = s["engines"]["yardstick_earnings_yield"]["horizons"]
    assert set(eyh) == {"3", "6", "12", "24", "36"}
    assert eyh["12"]["n_dates_with_ic"] == 2
    assert (tmp_path / "out" / "records.jsonl.gz").is_file() and (tmp_path / "out" / "summary.json").is_file()
    with gzip.open(tmp_path / "out" / "records.jsonl.gz", "rt", encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert rec["excess"]["12"] is not None and rec["base"]["revenue"] > 0 and rec["out"]["1"]["revenue"] > 0


def test_scores_do_not_depend_on_anything_after_the_date(tmp_path):
    a, ciks = build_world(tmp_path / "a")
    b, _ = build_world(tmp_path / "b", price_after="2018-07")          # every price after the valuation month is 5x
    ra = run_harness.run(["2018-06-29"], ciks, list(engines.YARDSTICKS), a, tmp_path / "oa", n_resamples=20)
    rb = run_harness.run(["2018-06-29"], ciks, list(engines.YARDSTICKS), b, tmp_path / "ob", n_resamples=20)
    with gzip.open(tmp_path / "oa" / "records.jsonl.gz", "rt") as f:
        A = [json.loads(l) for l in f]
    with gzip.open(tmp_path / "ob" / "records.jsonl.gz", "rt") as f:
        B = [json.loads(l) for l in f]
    for x, y in zip(A, B):
        assert x["score"] == y["score"] and x["price"] == y["price"]
        assert x["excess"]["12"] != y["excess"]["12"]                    # only the outcomes see the future


def test_scores_do_not_change_when_later_filings_are_removed(tmp_path):
    a, ciks = build_world(tmp_path / "a")
    recs = run_harness.run(["2018-06-29"], ciks, list(engines.YARDSTICKS), a, tmp_path / "oa", n_resamples=20, coverage_only=False)
    # drop every filing after 2018-06-29 from the store, rerun: the scores are the same
    b, _ = build_world(tmp_path / "b")
    for cik in ciks:
        synth.drop_filed_on_or_after(tmp_path / "b" / "store", cik, "2018-06-29")
    run_harness.run(["2018-06-29"], ciks, list(engines.YARDSTICKS), b, tmp_path / "ob", n_resamples=20)
    with gzip.open(tmp_path / "oa" / "records.jsonl.gz", "rt") as f:
        A = {json.loads(l)["cik"]: json.loads(l) for l in f}
    with gzip.open(tmp_path / "ob" / "records.jsonl.gz", "rt") as f:
        B = {json.loads(l)["cik"]: json.loads(l) for l in f}
    assert A.keys() == B.keys() and all(A[k]["score"] == B[k]["score"] for k in A)


def test_coverage_only_reads_no_return_and_writes_no_metric(tmp_path):
    pit, ciks = build_world(tmp_path)
    res = run_harness.run(DATES, ciks, ["yardstick_earnings_yield"], pit, tmp_path / "out", coverage_only=True)
    assert res["summary"] is None
    assert not (tmp_path / "out" / "records.jsonl.gz").exists() and not (tmp_path / "out" / "summary.json").exists()
    cov = json.loads((tmp_path / "out" / "coverage.json").read_text(encoding="utf-8"))
    assert cov["mode"] == "coverage_only" and cov["dates"][DATES[0]]["outcome_available"]["12"]["available"] == N
    o = outcomes.horizon_outcome(pit, "T0", "2018-06-29", 12, coverage_only=True)
    assert o["available"] is True and o["ret"] is None and o["excess"] is None and o["bench"] is None


def test_an_outcome_beyond_the_price_data_is_missing_not_imputed(tmp_path):
    pit, ciks = build_world(tmp_path)
    o = outcomes.horizon_outcome(pit, "T0", "2022-06-30", 36)              # prices end 2023-12
    assert o["available"] is False and o["excess"] is None
    o = outcomes.horizon_outcome(pit, "T0", "2018-06-29", 36)
    assert o["available"] is True and o["excess"] == pytest.approx(o["ret"] - o["bench"])


def test_a_custom_value_engine_is_ranked_by_value_over_price(tmp_path):
    pit, ciks = build_world(tmp_path)

    @engines.engine("test_value_engine", kind="value", files=[__file__])
    def val(ticker, asof, data_root):
        mc = data_root.market_cap(data_root.cik_for(ticker), asof, ticker)
        return engines.result(value_per_share=1.5 * mc["price"], family="operating")

    res = run_harness.run(["2018-06-29"], ciks, ["test_value_engine"], pit, tmp_path / "out", n_resamples=20)
    s = res["summary"]["engines"]["test_value_engine"]
    assert abs(s["value_over_price"]["overall"]["quantiles_5_25_50_75_95"][2] - 1.5) < 1e-9
    assert s["value_over_price"]["overall"]["share_below_0_4"] == 0.0


def test_share_classes_are_one_row_and_the_extra_ticker_is_counted(tmp_path):
    pit, ciks = build_world(tmp_path)
    pit2 = PitData(pit.store_dir, price_source=pit.price_source, id_map={**{k: v for k, v in pit.id_map.items()}, "T0B": "1"})
    pit2.price_source.prices["T0B"] = pit.price_source.prices["T0"]
    res = run_harness.run(["2018-06-29"], ciks, ["yardstick_earnings_yield"], pit2, tmp_path / "out", n_resamples=20)
    c = res["coverage"]["dates"]["2018-06-29"]
    assert c["records"] == N and c["share_class_duplicates"] == 1


def test_a_stale_base_year_is_excluded_and_counted(tmp_path):
    pit, ciks = build_world(tmp_path)
    res = run_harness.run(["2022-12-30"], ciks, ["yardstick_earnings_yield"], pit, tmp_path / "out", coverage_only=True, max_base_age_months=6)
    c = res["coverage"]["dates"]["2022-12-30"]
    assert c["excluded_stale_base_year"] == N and c["records"] == 0       # the base year (FY2021) ended 12 months before the date; the limit here is 6
