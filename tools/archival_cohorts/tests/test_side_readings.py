"""side_readings: the PREREG_cohorts_nextq readings that decide nothing, on hand-computed synthetic cases (no store, no network, no real
company, no cohort folder)."""
import copy
import hashlib
import json
import math
import os
from datetime import date

import pytest

import score_nextq as Q
import side_readings as S
from qwen_c.tests import test_value_checks as C
from qwen_c.value import consensus, menu, run as vrun, task

T1, T2, T3, T4 = Q.COHORTS
LN = math.log


def wins(closed=(True, True, True)):
    """windows as with_returns reports them, for every cohort."""
    return {T: {str(m): {"end": S.add_months(date.fromisoformat(T), m).isoformat(), "closed": c} for m, c in zip((3, 6, 12), closed)}
            for T in Q.COHORTS}


def R(cohort=T1, ticker="AAA", cik=None, close=10.0, base=None, bear=None, bull=None, code=None, unheld=None, seeds=(None, None),
      abn=None, vp=None):
    """A row as make_row and with_returns leave it. vp (record, code, unheld) overrides the ratios; abn is {m: abnormal return}."""
    rec = None if base is None else {"status": "ok", "base": base, "bear": bear, "bull": bull}
    v = {"record": S.ratio(base, close), "code_only": S.ratio(code, close), "unheld": S.ratio(unheld, close)}
    if vp is not None:
        v = dict(zip(("record", "code_only", "unheld"), vp))
    return {"cohort": cohort, "ticker": ticker, "cik": cik or ticker, "sector": "S", "cap_tercile": "T1", "close": close, "reason": None,
            "seed_status": {}, "seed_base": {str(s): b for s, b in zip(Q.SEEDS, seeds)}, "record": rec, "code_only": code, "unheld": unheld,
            "annotations": [], "held_at_record": False, "vp": v, "ret": {}, "ret_reason": {},
            "abn": {str(m): (abn or {}).get(m) for m in (3, 6, 12)}}


# ------------------------------------------------------------------ numbers
def test_quartile_rule_is_linear_interpolation():
    assert S.quartiles([4, 1, 3, 2]) == {"n": 4, "q1": 1.75, "median": 2.5, "q3": 3.25}
    assert S.quartiles([5]) == {"n": 1, "q1": 5, "median": 5, "q3": 5}
    assert S.quartiles([]) == {"n": 0, "q1": None, "median": None, "q3": None}
    assert S.quantile([1, 2, 3, 4, 5], 0.5) == 3 and S.quantile([0.0, 1.0], 0.25) == 0.25


def test_ranks_average_ties():
    assert S.ranks([10, 20, 20, 30]) == [1, 2.5, 2.5, 4]
    assert S.ranks([3, 1, 2]) == [3, 1, 2] and S.ranks([7, 7, 7]) == [2, 2, 2]


def test_spearman_by_hand():
    assert S.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == pytest.approx(0.8)             # 1 - 6 * 4 / (5 * 24)
    assert S.spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(3 / math.sqrt(10))      # ties: Pearson of the average ranks
    assert S.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1)
    assert S.spearman([1, 2], [1, 2]) is None and S.spearman([1, 1, 1], [1, 2, 3]) is None     # n < 3; no spread


def test_permutation_p_is_deterministic_and_two_sided():
    x, y = [1, 2, 3, 4, 5], [2, 1, 4, 3, 5]                  # 120 orderings; |rho| >= 0.8 in 16 of them (sum of squared rank gaps <= 4, either sign)
    p = S.spearman_p(x, y)
    assert p == S.spearman_p(x, y) and abs(p - 16 / 120) < 0.02
    assert S.spearman_p(x, [-v for v in y]) == p              # two-sided: the sign of the correlation does not matter
    assert abs(S.spearman_p([1, 2, 3], [1, 2, 3]) - 1 / 3) < 0.03     # 2 of 6 orderings
    assert S.spearman_p(list(range(8)), list(range(8))) < 0.001
    assert S.spearman_p([1, 2], [1, 2]) is None


def test_value_over_price_and_logs():
    assert S.ratio(25.0, 10.0) == 2.5 and S.ratio(0.0, 10.0) == 0.0 and S.ratio(None, 10.0) is None
    assert S.ratio(5.0, 0.0) is None and S.ratio(5.0, None) is None
    assert S.ln_ratio(2.0, 1.0) == pytest.approx(LN(2)) and S.ln_ratio(0.0, 1.0) is None and S.ln_ratio(1.0, -1.0) is None


# ------------------------------------------------------------------ prices and windows
def test_add_months_clamps_to_the_month_end():
    assert S.add_months(date(2026, 8, 31), 6) == date(2027, 2, 28)
    assert S.add_months(date(2024, 8, 31), 6) == date(2025, 2, 28) and S.add_months(date(2023, 8, 31), 6) == date(2024, 2, 29)
    assert S.add_months(date(2025, 11, 20), 3) == date(2026, 2, 20) and S.add_months(date(2025, 11, 20), 6) == date(2026, 5, 20)
    assert S.add_months(date(2025, 10, 1), 12) == date(2026, 10, 1)


def test_the_close_is_on_or_at_most_seven_days_before():
    s = {"2025-09-24": 9.0, "2025-12-31": 12.0}
    assert S.price_at(s, date(2025, 10, 1)) == 9.0 and S.price_at(s, date(2025, 10, 2)) is None
    assert S.simple_return(s, date(2025, 10, 1), date(2026, 1, 1)) == (pytest.approx(12 / 9 - 1), None)
    assert S.simple_return(s, date(2025, 10, 2), date(2026, 1, 1)) == (None, "no_price_at_T")
    assert S.simple_return(s, date(2025, 10, 1), date(2026, 1, 9)) == (None, "no_price_at_end")
    assert S.simple_return({}, date(2025, 10, 1), date(2026, 1, 1)) == (None, "no_price_series")
    assert S.simple_return({"2025-10-01": 0.0, "2026-01-01": 1.0}, date(2025, 10, 1), date(2026, 1, 1)) == (None, "price_at_T_not_positive")


def test_returns_abnormal_mean_and_the_survivor_gap():
    def ser(p1):
        return {"2025-10-01": 100.0, "2026-01-01": p1}
    prices = {"A": ser(110.0), "B": ser(130.0), "D": ser(90.0)}             # C has no series; A+B+D mean return (0.1 + 0.3 - 0.1) / 3 = 0.1
    rows = [R(ticker=t) for t in "ABCD"] + [R(cohort=T2, ticker="Z")]
    out, w, gap = S.with_returns(rows, prices, date(2026, 2, 1))             # 3-month window ended 2026-01-01; the 6-month one has not
    by = {r["ticker"]: r for r in out if r["cohort"] == T1}
    assert by["A"]["ret"]["3"] == pytest.approx(0.1) and by["A"]["abn"]["3"] == pytest.approx(0.0)
    assert by["B"]["abn"]["3"] == pytest.approx(0.2) and by["D"]["abn"]["3"] == pytest.approx(-0.2)
    assert by["C"]["ret"]["3"] is None and by["C"]["abn"]["3"] is None and by["C"]["ret_reason"]["3"] == "no_price_series"
    g = gap[T1]["3"]
    assert (g["census"], g["with_return"], g["no_price_series"], g["reasons"]) == (4, 3, 1, {"no_price_series": 1})
    assert g["equal_weight_mean"] == pytest.approx(0.1)                       # C is left out of the mean, and counted
    assert gap[T1]["6"] == {"window_not_closed": True} and by["A"]["ret_reason"]["6"] == "window_not_closed" and by["A"]["abn"]["6"] is None
    assert w[T1]["3"] == {"end": "2026-01-01", "closed": True} and w[T1]["6"] == {"end": "2026-04-01", "closed": False}
    assert gap[T2]["3"] == {"window_not_closed": True}                       # cohort 2 ends 2026-02-20, after the last session


def test_a_window_closes_on_the_last_session_itself():
    out, w, _ = S.with_returns([R(cohort=T4)], {}, date(2026, 11, 20))
    assert w[T4]["3"] == {"end": "2026-11-20", "closed": True} and w[T4]["6"]["closed"] is False
    assert out[0]["ret_reason"]["3"] == "no_price_series" and out[0]["ret_reason"]["12"] == "window_not_closed"


def test_the_price_rows_hash_does_not_depend_on_order():
    a = {"A": {"2026-01-01": 1.0, "2026-01-02": 2.0}, "B": {"2026-01-01": 3.0}}
    b = {"B": {"2026-01-01": 3.0}, "A": {"2026-01-02": 2.0, "2026-01-01": 1.0}}
    assert S.prices_sha256(a) == S.prices_sha256(b) != S.prices_sha256({"A": {"2026-01-01": 1.0}})


# ------------------------------------------------------------------ one row
def cons(base=100.0, bear=80.0, bull=130.0, code=90.0, ann=(), status="ok", unheld=110.0, **kw):
    return dict({"held": {"status": status, "values": {"base": base, "bear": bear, "bull": bull}, "diagnostics": {"record_neutral": {"value": code}},
                          "annotations": list(ann)},
                 "unheld": {"status": "ok", "values": {"base": unheld}}, "held_error": None, "unheld_error": None}, **kw)


META = {"cohort": T1, "ticker": "AAA", "cik": "1", "sector": "S", "cap_tercile": "T1", "close": 10.0}


def sr(status="ok", base=100.0):
    return {"status": status, "values": {"base": base} if status.startswith("ok") else {}}


def test_a_name_with_no_packet_or_no_checked_seed_has_a_row_with_its_reason_and_no_values():
    r = S.make_row(META, None, None)
    assert r["reason"] == "no_packet" and r["record"] is None and r["vp"] == {"record": None, "code_only": None, "unheld": None}
    r = S.make_row(META, {1200: sr("reply_invalid"), 3200: sr("malformed")}, None)
    assert r["reason"] == "no_checked_seed" and r["record"] is None and r["seed_status"] == {"1200": "reply_invalid", "3200": "malformed"}


def test_a_row_carries_the_record_the_code_only_and_the_unheld_value_over_price():
    r = S.make_row(META, {1200: sr(base=100.0), 3200: sr("ok_with_reverts", 104.0)}, cons(ann=["held_at_record: rev_growth.y1 model 0.05 valued at 0.03"]))
    assert r["reason"] is None and r["record"] == {"status": "ok", "base": 100.0, "bear": 80.0, "bull": 130.0}
    assert r["code_only"] == 90.0 and r["unheld"] == 110.0 and r["held_at_record"] is True
    assert r["vp"] == {"record": 10.0, "code_only": 9.0, "unheld": 11.0} and r["seed_base"] == {"1200": 100.0, "3200": 104.0}


def test_one_checked_seed_still_has_a_value_of_record_and_no_second_seed_base():
    r = S.make_row(META, {1200: sr(base=100.0), 3200: sr("reply_invalid")}, cons(ann=["one_seed_only: ['1200']"]))
    assert r["record"]["base"] == 100.0 and r["seed_base"] == {"1200": 100.0, "3200": None}


def test_zero_is_a_value_and_a_consensus_failure_is_a_reason():
    r = S.make_row(META, {1200: sr(base=0.0), 3200: sr(base=0.0)}, cons(base=0.0, bear=0.0, bull=0.0, code=0.0, unheld=0.0))
    assert r["record"]["base"] == 0.0 and r["vp"]["record"] == 0.0 and r["vp"]["code_only"] == 0.0 and r["code_only"] == 0.0
    r = S.make_row(META, {1200: sr(), 3200: sr()}, {"held": None, "held_error": "DeskRefusal: x", "unheld": None, "unheld_error": None})
    assert r["reason"] == "consensus_error: DeskRefusal: x" and r["record"] is None
    r = S.make_row(META, {1200: sr(), 3200: sr()}, {"held": {"status": "no_call", "reason": "no_checked_seed"}, "held_error": None})
    assert r["reason"] == "consensus_no_call: no_checked_seed"
    r = S.make_row(META, {1200: sr(), 3200: sr()}, dict(cons(), unheld=None, unheld_error="ValueError: y"))
    assert r["record"] is not None and r["unheld"] is None and r["unheld_error"] == "ValueError: y"


# ------------------------------------------------------------------ S2, S3, S6
def test_s2_rank_correlation_per_cohort_beside_code_only_and_unheld():
    abn = [0.2, 0.1, 0.4, 0.3, 0.5]
    rows = [R(ticker=f"N{i}", abn={3: a, 6: a}, vp=(i + 1, 5 - i, 3.0 if i < 2 else 4.0)) for i, a in enumerate(abn)]
    rows.append(R(ticker="NONE", abn={3: 0.9, 6: 0.9}, vp=(None, None, None)))             # no value: counted, not dropped silently
    out = S.s2(rows, wins((True, True, True)))
    c = out[T1]["3m"]
    assert c["record"]["n"] == 5 and c["record"]["rho"] == pytest.approx(0.8) and abs(c["record"]["p_two_sided_permutation"] - 16 / 120) < 0.02
    assert c["code_only"]["rho"] == pytest.approx(-0.8) and c["record"]["left_out"] == {"missing_value_or_return": 1}
    assert c["unheld"]["n"] == 5 and c["unheld"]["rho"] is not None
    assert out[T2]["3m"]["record"]["n"] == 0 and out[T2]["3m"]["record"]["rho"] is None and "pooled" not in json.dumps(out)
    assert S.s2(rows, wins((True, False, False)))[T1]["6m"] == {"window_not_closed": True, "end": "2026-04-01"}


def test_top_third_takes_n_over_three_by_value_over_price_ties_by_ticker():
    for n, k in ((5, 1), (6, 2), (7, 2)):
        rows = [R(ticker=f"T{i}", vp=(float(n - i), None, None)) for i in range(n)]
        assert [r["ticker"] for r in S.top_third(rows, "record")] == [f"T{i}" for i in range(k)]
    tie = [R(ticker="B", vp=(2.0, None, None)), R(ticker="A", vp=(2.0, None, None)), R(ticker="C", vp=(2.0, None, None)),
           R(ticker="D", vp=(3.0, None, None))]
    assert [r["ticker"] for r in S.top_third(tie, "record")] == ["D"]
    assert [r["ticker"] for r in S.top_third(tie[:3] + [R(ticker="E", vp=(2.0, None, None)), R(ticker="F", vp=(1.0, None, None))], "record")] == ["A"]


def test_s3_names_in_one_top_third_and_not_the_other():
    ab = {"A": 0.1, "B": -0.1, "C": 0.0, "D": 0.0, "E": 0.2, "F": 0.3}
    q = dict(zip("ABCDEF", (6.0, 5.0, 4.0, 3.0, 2.0, 1.0)))
    c = dict(zip("ABCDEF", (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)))
    rows = [R(ticker=t, abn={6: ab[t]}, vp=(q[t], c[t], None)) for t in "ABCDEF"]
    out = S.s3(rows, wins())[T1]
    assert out["eligible"] == 6 and out["top_third_n"] == 2
    assert out["qwen_not_code_only"] == {"n": 2, "share_positive": 0.5, "mean_abnormal_return": pytest.approx(0.0), "tickers": ["A", "B"]}
    assert out["code_only_not_qwen"] == {"n": 2, "share_positive": 1.0, "mean_abnormal_return": pytest.approx(0.25), "tickers": ["E", "F"]}
    same = S.s3([R(ticker=t, abn={6: ab[t]}, vp=(q[t], q[t], None)) for t in "ABCDEF"], wins())[T1]          # the same top third: nothing differs
    assert same["qwen_not_code_only"]["n"] == 0 and same["qwen_not_code_only"]["share_positive"] is None
    assert S.s3(rows, wins((True, False, False)))[T1] == {"window_not_closed": True, "end": "2026-04-01"}


def test_s3_leaves_out_a_name_without_a_code_only_value_or_a_return():
    rows = [R(ticker="A", abn={6: 0.1}, vp=(3.0, 3.0, None)), R(ticker="B", abn={6: 0.1}, vp=(2.0, None, None)),
            R(ticker="C", abn={6: None}, vp=(1.0, 1.0, None))]
    assert S.s3(rows, wins())[T1]["eligible"] == 1


def test_s6_logs_and_counts_what_has_none():
    ab = [0.1, 0.3, 0.2, 0.4]
    rows = [R(ticker=f"N{i}", abn={12: a}, vp=(2.0 ** i, 4.0 - i, None)) for i, a in enumerate(ab)]
    rows.append(R(ticker="NEG", abn={12: 0.5}, vp=(-0.5, 0.0, None)))                                    # at or below zero: no logarithm
    out = S.s6(rows, wins())
    assert set(out) == {T1, T2} and out[T1]["record"] == {"n": 4, "rho": pytest.approx(0.8), "left_out": {"non_positive_value": 1}}
    assert out[T1]["code_only"]["n"] == 4 and out[T1]["code_only"]["left_out"] == {"non_positive_value": 1}
    assert out[T2]["record"]["n"] == 0
    assert S.s6(rows, wins((True, True, False)))[T1] == {"window_not_closed": True, "end": "2026-10-01"}


# ------------------------------------------------------------------ E1 to E5
def test_e1_agreement_of_the_two_seeds():
    rows = [R(ticker="A", seeds=(100.0, 102.0)), R(ticker="B", seeds=(100.0, 110.0)), R(ticker="C", seeds=(100.0, 100.0)),
            R(ticker="D", seeds=(0.0, 100.0)), R(ticker="E", seeds=(100.0, None)), R(cohort=T2, ticker="F", seeds=(200.0, 209.0))]
    out = S.e1(rows)
    xs = sorted([abs(LN(100 / 102)), abs(LN(100 / 110)), 0.0])
    assert out[T1]["n"] == 3 and out[T1]["median"] == pytest.approx(xs[1]) and out[T1]["share_within_5pct"] == pytest.approx(2 / 3)
    assert out[T1]["excluded"] == {"non_positive_base": 1, "not_two_checked_seeds": 1}
    assert out[T2]["n"] == 1 and out[T2]["share_within_5pct"] == 1.0 and out[T3]["n"] == 0 and out[T3]["median"] is None
    assert out["all"]["n"] == 4 and out["all"]["median"] == pytest.approx(sorted(xs + [abs(LN(200 / 209))])[2] / 2 + sorted(xs + [abs(LN(200 / 209))])[1] / 2)


def test_e2_a_company_in_three_cohorts_gives_two_pairs():
    rows = [R(cohort=T3, ticker="K", cik="K", base=99.0, code=60.0), R(cohort=T1, ticker="K", cik="K", base=100.0, code=50.0),
            R(cohort=T2, ticker="K", cik="K", base=110.0, code=55.0),
            R(cohort=T1, ticker="M", cik="M", base=100.0, code=50.0), R(cohort=T4, ticker="M", cik="M", code=70.0),         # no value of record
            R(cohort=T1, ticker="N", cik="N", base=100.0), R(cohort=T2, ticker="N", cik="N", base=100.0, code=50.0),      # no code-only value
            R(cohort=T1, ticker="P", cik="P", base=100.0, code=-5.0), R(cohort=T2, ticker="P", cik="P", base=100.0, code=50.0),
            R(cohort=T1, ticker="Q", cik="Q", base=100.0, code=50.0)]                                                      # one cohort only
    out = S.e2(rows)
    a, b = 0.0, abs(LN(99 / 110) - LN(60 / 55))                         # pair 1: ln(110/100) - ln(55/50) = 0
    assert out["companies_in_more_than_one_cohort"] == 4 and out["pairs"] == 5 and out["used"] == 2
    assert out["median_abs_remainder"] == pytest.approx((a + b) / 2) and b == pytest.approx(0.19237, abs=1e-5)
    assert out["share_within_5pct"] == 0.5 and out["share_within_10pct"] == 0.5
    assert out["left_out"] == {"no_value_of_record": 1, "no_code_only_value": 1, "non_positive_value": 1}


def test_e3_coverage_by_cohort_and_sector():
    names = {T: [] for T in Q.COHORTS}
    names[T1] = [{"ticker": "A", "sector": "X", "stage": None}, {"ticker": "B", "sector": "X", "stage": None},
                 {"ticker": "C", "sector": "Y", "stage": None}, {"ticker": "D", "sector": "Y", "stage": "not_drawn"},
                 {"ticker": "E", "sector": None, "stage": "no_sector"}]
    rows = [R(ticker="A", base=1.0), R(ticker="B"), R(ticker="C", base=1.0), R(cohort=T2, ticker="A", base=1.0)]
    out = S.e3(names, rows)[T1]
    assert (out["drawn"], out["census"], out["valued"]) == (5, 3, 2)
    assert out["by_sector"] == {"None": {"drawn": 1, "census": 0, "valued": 0}, "X": {"drawn": 2, "census": 2, "valued": 1},
                                "Y": {"drawn": 2, "census": 1, "valued": 1}}
    assert S.e3(names, rows)[T2]["drawn"] == 0


def test_e4_precision_quartiles_and_nonpositive_legs():
    rows = [R(ticker="A", base=1.0, bear=80.0, bull=120.0), R(ticker="B", base=1.0, bear=100.0, bull=100.0),
            R(ticker="C", base=1.0, bear=100.0, bull=200.0), R(ticker="D", base=1.0, bear=0.0, bull=100.0),
            R(ticker="E", base=1.0, bear=-1.0, bull=5.0), R(ticker="F"), R(cohort=T2, ticker="G", base=1.0, bear=50.0, bull=50.0)]
    out = S.e4(rows)
    assert out[T1]["n"] == 3 and out[T1]["excluded_non_positive_leg"] == 2
    assert (out[T1]["q1"], out[T1]["median"], out[T1]["q3"]) == pytest.approx((LN(1.5) / 2, LN(1.5), LN(1.5) + (LN(2) - LN(1.5)) / 2))
    assert out[T2]["n"] == 1 and out["all"]["n"] == 4 and out["all"]["excluded_non_positive_leg"] == 2


def test_e5_the_level_per_cohort():
    rows = [R(ticker=t, close=10.0, base=b, code=c) for t, b, c in (("A", 10.0, 20.0), ("B", 20.0, 40.0), ("C", 30.0, 60.0), ("D", 40.0, 80.0))]
    rows.append(R(ticker="E", close=10.0))                                                                               # no value: not in either
    out = S.e5(rows)[T1]
    assert out["record"] == {"n": 4, "q1": 1.75, "median": 2.5, "q3": 3.25} and out["code_only"]["median"] == 5.0
    assert S.e5(rows)[T3]["record"]["n"] == 0


# ------------------------------------------------------------------ E6 and the run health
def res(status="ok", base=100.0, option="ytd", unreadable=False):
    r = {"status": status, "values": {"base": base}, "checks": {"options": {"rev_growth.y1": option},
                                                                 "reverts": [Q.UNREADABLE + "ordinal 2 of 1"] if unreadable else []}}
    return r


def entry(high, medium, vh, vm, sh=(100, 100), sm=(50, 50)):
    return {"high": dict(zip(Q.SEEDS, high)), "medium": dict(zip(Q.SEEDS, medium)), "value": {"high": vh, "medium": vm},
            "seconds": {"high": list(sh), "medium": list(sm)}}


def test_e6_levels_side_by_side():
    es = [entry((res(base=100, option="guidance"), res(base=102, unreadable=True)), (res(base=100), res(base=130)), 100.0, 120.0, sh=(100, 300)),
          entry((res(base=50), res(base=50)), (res(base=50), res(base=51)), 50.0, 51.0, sh=(200, 200)),
          entry((res(base=10), res(base=10)), (res(base=10), res(base=10)), None, 10.0, sh=(100, 100))]
    out = S.e6(es)
    h, m = out["levels"]["high"], out["levels"]["medium"]
    assert out["names"] == 3 and h["e1"]["n"] == 3 and h["e1"]["share_within_5pct"] == 1.0
    assert m["e1"]["n"] == 3 and m["e1"]["share_within_5pct"] == pytest.approx(2 / 3)
    assert h["guidance_picks"] == {"picked": 2, "reverted_unreadable": 1, "share": 0.5}
    assert m["guidance_picks"] == {"picked": 0, "reverted_unreadable": 0, "share": None}                  # zero picks: None, not a division error
    assert h["seconds_per_slot"]["n"] == 6 and h["seconds_per_slot"]["mean"] == pytest.approx(1000 / 6) and h["seconds_per_slot"]["median"] == 150
    assert m["seconds_per_slot"]["mean"] == 50 and m["seconds_per_slot"]["median"] == 50
    assert out["value_of_record_differs_more_than_5pct"] == {"n": 2, "differs": 1, "share": 0.5, "excluded": {"no_value_of_record_at_a_level": 1}}


def test_e6_with_no_names_or_unchecked_seeds_has_no_figures_not_errors():
    out = S.e6([])
    assert out["levels"]["high"]["e1"]["n"] == 0 and out["levels"]["high"]["guidance_picks"]["share"] is None
    assert out["value_of_record_differs_more_than_5pct"]["share"] is None
    bad = entry((res("reply_invalid"), res()), (res(), res()), 1.0, 1.0)
    assert S.e6([bad])["levels"]["high"]["e1"]["excluded"] == {"not_two_checked_seeds": 1}


def test_run_health_counts_from_the_attempts():
    a = lambda o, d: {"outcome": o, "done_reason": d}                                                       # noqa: E731
    out = S.run_health([{"attempts": [a("reply", "stop")]},
                        {"attempts": [a("malformed", "length"), a("reply", "stop")]},
                        {"attempts": [a("infra_retry", None), a("infra_retry", None)]},
                        {"attempts": [a("timeout", None)]},
                        {"status": "ok"}])
    assert out == {"slots": 4, "attempts": 6, "slots_with_second_attempt": 2, "attempts_done_reason_length": 1, "attempts_server_error": 2,
                   "attempts_timeout": 1, "results_without_attempts": 1}


# ------------------------------------------------------------------ the consensus, held and not held (qwen_c fixtures)
@pytest.fixture(scope="module")
def ctx():
    return C.ctx_of()


def seed_of(ctx, reply):
    out = C.run(ctx, copy.deepcopy(reply))
    return {"status": out["status"], "inputs": reply, "checks": out, "values": out["values"]}


def guided():
    g = {"evidence": "G1.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}
    return C.depart(C.clean(), "rev_growth.y1", "guidance", "guidance", ["G1.s1"], g)          # 5% guided against the record-neutral year 1


def of(ctx, replies, tmp_path, monkeypatch, held):
    b, bar, ids = ctx
    seen = {}

    def prepare(packet, cik, sector, mc, **kw):
        seen["env"], seen["held"], seen["args"] = os.environ.get(S.ARCHIVAL_ENV), menu.HELD, (cik, sector, mc, kw)
        return None, b, bar, None, C.R, None, C.ENDS
    monkeypatch.setattr(vrun, "prepare", prepare)
    monkeypatch.setattr(task, "evidence_ids", lambda *a: ids)
    pk = tmp_path / "packet.json"
    pk.write_text("{}", encoding="utf-8")
    results = {s: seed_of(ctx, r) for s, r in zip(Q.SEEDS, replies)}
    out = S.consensus_of(tmp_path / "cohort", {"cik": "1", "sector": "S", "market_cap": None, "family": "operating"}, {"packet": str(pk)},
                         results, held=held)
    return out, seen


def test_a_departure_both_seeds_share_is_held_at_record_unless_not_held(ctx, tmp_path, monkeypatch):
    before = os.environ.get(S.ARCHIVAL_ENV)
    kept, seen = of(ctx, [guided(), guided()], tmp_path, monkeypatch, held=True)
    free, seen_free = of(ctx, [guided(), guided()], tmp_path, monkeypatch, held=False)
    neutral = C.run(ctx, C.clean())["values"]
    assert kept["status"] == free["status"] == "ok"
    assert kept["values"] == neutral and any(a.startswith("held_at_record: rev_growth.y1") for a in kept["annotations"])
    assert free["values"]["base"] != kept["values"]["base"] and not any(a.startswith("held_at_record") for a in free["annotations"])
    assert free["options"]["rev_growth.y1"] == "guidance" and free["numbers"]["rev_growth.y1"] == 0.05
    assert seen["held"] == menu.HELD != () and seen_free["held"] == ()                                  # emptied for the call only
    assert menu.HELD == ("rev_growth.y1", "op_margin.y1") and os.environ.get(S.ARCHIVAL_ENV) == before    # both restored
    assert seen["env"] == str(tmp_path / "cohort" / "coe_pinned") and seen["args"] == ("1", "S", 0, {"online": False, "family": "operating"})


def test_with_no_departure_the_held_and_unheld_values_are_equal(ctx, tmp_path, monkeypatch):
    kept, _ = of(ctx, [C.clean(), C.clean()], tmp_path, monkeypatch, held=True)
    free, _ = of(ctx, [C.clean(), C.clean()], tmp_path, monkeypatch, held=False)
    assert kept["values"] == free["values"] and not any(a.startswith("held_at_record") for a in kept["annotations"] + free["annotations"])


def test_held_is_restored_when_the_consensus_fails(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(vrun, "prepare", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    pk = tmp_path / "p.json"
    pk.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        S.consensus_of(tmp_path, {"cik": "1", "sector": "S", "market_cap": 5.0, "family": "operating"}, {"packet": str(pk)}, {}, held=False)
    assert menu.HELD == ("rev_growth.y1", "op_margin.y1")


def test_j2_annual_reports_not_available_when_the_scorer_refuses(tmp_path):
    out = S.j2_annual(tmp_path / "nothing_here", "0" * 64)
    assert set(out) == {"not_available"} and "FileNotFoundError" in out["not_available"]


# ------------------------------------------------------------------ the driver on synthetic folders
def sha(b):
    return hashlib.sha256(b).hexdigest()


def write_result(d, name, r):
    p = d / "results" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(r).encode("utf-8")
    p.write_bytes(raw)
    return {"status": r["status"], "result": str(p), "result_sha256": sha(raw), "seconds": 100.0}


def build(tmp_path, bad_hash=False, drop_slot=False, medium=True):
    """Four cohorts. Company K is in the first three; each cohort has a no-packet name, an uncensused name, and (cohort 1) a name whose
    consensus will fail."""
    value = tmp_path / "value"
    for i, T in enumerate(Q.COHORTS):
        d = value / f"archival_cohort_{T}"
        d.mkdir(parents=True)
        tick = [("K", "K", 100.0 + i)] if i < 3 else []
        tick += [(f"U{i}", f"U{i}", 120.0), (f"V{i}", f"V{i}", 80.0), (f"W{i}", f"W{i}", 90.0)]
        names = [{"ticker": t, "cik": c, "sector": "S", "cap_tercile": "T1", "close": 10.0, "stage": None, "family": "operating",
                  "market_cap": 1e9, "_v": v} for t, c, v in tick]
        names.append({"ticker": f"NP{i}", "cik": f"NP{i}", "sector": "S", "cap_tercile": "T1", "close": 10.0, "stage": None, "family": "operating",
                      "market_cap": 1e9, "_v": 1.0})
        names.append({"ticker": f"X{i}", "cik": f"X{i}", "sector": "S", "stage": "not_drawn"})
        packets, slots, mslots = {}, {}, {}
        for n in names:
            t = n["ticker"]
            if t.startswith(("NP", "X")):
                packets[t] = {"packet": None, "refused": "r"}
                continue
            packets[t] = {"packet": str(d / f"{t}.pk")}
            for seed in Q.SEEDS:
                r = {"status": "ok", "values": {"base": n["_v"] + (seed == 3200)}, "checks": {"options": {"rev_growth.y1": "guidance"}, "reverts": []},
                     "attempts": [{"outcome": "reply", "done_reason": "stop"}]}
                slots[f"{t}:{seed}"] = write_result(d, f"{t}_{seed}", r)
                if i == 0 and t == "K":
                    mslots[f"{t}:{seed}"] = write_result(d, f"{t}_{seed}_m", dict(r, values={"base": n["_v"] * 1.2}))
        if i == 0 and bad_hash:
            slots["K:1200"]["result_sha256"] = "0" * 64
        if i == 3 and drop_slot:
            del slots["K:3200" if "K:3200" in slots else "U3:3200"]
        (d / "pool.json").write_text(json.dumps({"T": T, "names": names}), encoding="utf-8")
        (d / "runs.json").write_text(json.dumps({"pool_sha256": f"p{i}", "packets": packets}), encoding="utf-8")
        (d / "slots.json").write_text(json.dumps({"slots": slots}), encoding="utf-8")
        if i == 0 and medium:
            (d / S.MEDIUM_FILE).write_text(json.dumps({"git": "x", "note": "n", "slots": mslots}), encoding="utf-8")
    return value, {n["ticker"]: n for T in Q.COHORTS for n in json.loads((value / f"archival_cohort_{T}" / "pool.json").read_text())["names"]}


def injected(calls=None):
    def consensus_of(d, n, packet, results, held=True):
        if calls is not None:
            calls.append((n["ticker"], held))
        if n["ticker"] == "W0":
            raise RuntimeError("desk refused offline")
        v = n["_v"] + (7.0 if not held else 0.0) + (50.0 if any(r["values"]["base"] > n["_v"] * 1.1 for r in results.values()) else 0.0)
        return {"status": "ok", "values": {"base": v, "bear": v * 0.8, "bull": v * 1.3}, "diagnostics": {"record_neutral": {"value": 100.0}},
                "annotations": ["held_at_record: x"] if held else []}

    def fetch(tickers, start, end):
        px = {}
        for t in tickers:
            if t.startswith("V"):
                continue                                                     # no series: the survivor gap
            px[t] = {}
            for i, T in enumerate(Q.COHORTS):
                for m in (0, 3, 6, 12):
                    px[t][S.add_months(date.fromisoformat(T), m).isoformat()] = 10.0 * (1 + 0.01 * m * (1 + (t == "K")))
        return "synthetic", px
    return consensus_of, fetch


def drive(value, today="2026-11-20", calls=None, last=date(2026, 11, 20)):
    c, f = injected(calls)
    return S.run(value, today, consensus_of=c, fetch=f, s5=lambda d, sha_: {"keys": {}, "dir": d.name, "sha": sha_}, last_session=lambda: last)


def test_the_driver_refuses_before_by_without_reading_anything(tmp_path):
    with pytest.raises(SystemExit, match="STOP.*2026-11-20"):
        drive(tmp_path / "does_not_exist", today="2026-11-19")
    assert Q.BY == "2026-11-20" and S.BY is Q.BY


def test_the_driver_refuses_a_missing_slot_and_a_result_that_does_not_hash_to_its_slot(tmp_path):
    value, _ = build(tmp_path / "a", drop_slot=True)
    with pytest.raises(SystemExit, match="STOP.*has no slot"):
        drive(value)
    value, _ = build(tmp_path / "b", bad_hash=True)
    with pytest.raises(SystemExit, match="STOP.*does not hash to its slot"):
        drive(value)
    assert not (value / S.OUT_NAME).exists()


def test_the_driver_writes_once_and_never_overwrites(tmp_path, capsys):
    value, pool = build(tmp_path)
    calls = []
    assert drive(value, calls=calls) == 0
    out = json.loads((value / S.OUT_NAME).read_text(encoding="utf-8"))
    with pytest.raises(SystemExit, match="never overwritten"):
        drive(value)
    assert json.loads((value / S.OUT_NAME).read_text(encoding="utf-8")) == out
    assert ("U0", True) in calls and ("U0", False) in calls and not any(t.startswith("NP") for t, _ in calls)

    assert out["decides"] == "nothing" and out["last_completed_session"] == "2026-11-20" and out["price"]["source"] == "synthetic"
    for k in ("S2", "S3", "S5", "S6", "E1", "E2", "E3", "E4", "E5", "E6", "run_health", "survivor_gap"):
        assert out[k]["decides"] == "nothing", k
    rows = {(r["cohort"], r["ticker"]): r for r in out["rows"]}
    assert len(rows) == 19 and (T1, "NP0") in rows and (T1, "X0") not in rows                # the uncensused name has no row
    assert rows[(T1, "NP0")]["reason"] == "no_packet" and rows[(T1, "NP0")]["record"] is None
    assert rows[(T1, "W0")]["reason"].startswith("consensus_error: RuntimeError") and rows[(T1, "U0")]["record"]["base"] == 120.0
    assert rows[(T1, "U0")]["unheld"] == 127.0 and rows[(T1, "U0")]["vp"]["record"] == 12.0 and rows[(T1, "U0")]["vp"]["code_only"] == 10.0
    # windows: cohort 4's 3-month window ends on the last session; its 6-month window has not closed; cohorts 1 and 2 have a 12-month window
    assert out["windows"][T4]["3"]["closed"] and not out["windows"][T4]["6"]["closed"] and out["windows"][T2]["12"]["closed"]
    assert not out["windows"][T3]["12"]["closed"] and out["S2"][T4]["6m"]["window_not_closed"] and out["S3"][T4]["window_not_closed"]
    assert set(out["S6"]) == {T1, T2, "decides"} and out["S2"][T1]["3m"]["record"]["n"] > 0
    # the survivor gap: the V name has no series
    g = out["survivor_gap"][T1]["3"]
    assert g["no_price_series"] == 1 and g["census"] == 5 and g["reasons"] == {"no_price_series": 1}
    # coverage and repeats: K is in cohorts 1 to 3
    assert out["E3"][T1] == dict(out["E3"][T1], drawn=6, census=5, valued=3) and out["E2"]["pairs"] == 2 and out["E2"]["used"] == 2
    assert out["E1"]["all"]["n"] == 15 and out["E1"]["all"]["share_within_5pct"] == 1.0
    assert out["S5"][T1] == {"keys": {}, "dir": f"archival_cohort_{T1}", "sha": "p0"} and set(out["S5"]) == {"decides", T1, T2}
    # E6: company K at both levels in cohort 1 (medium values 1.2 times; the +50 in the fake marks a medium reply)
    assert out["E6"]["names"] == 1 and out["E6"]["levels"]["medium"]["seconds_per_slot"]["mean"] == 100.0
    assert out["E6"]["value_of_record_differs_more_than_5pct"] == {"n": 1, "differs": 1, "share": 1.0, "excluded": {}}
    assert out["run_health"][T1]["slots"] == 2 * 4 and out["run_health"][T1]["attempts_done_reason_length"] == 0


def test_the_driver_reports_e6_as_not_available_without_the_medium_file(tmp_path):
    value, _ = build(tmp_path, medium=False)
    drive(value)
    out = json.loads((value / S.OUT_NAME).read_text(encoding="utf-8"))
    assert out["E6"]["not_available"].startswith(S.MEDIUM_FILE)
