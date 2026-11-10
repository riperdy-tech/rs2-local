"""score_nextq: the PREREG_cohorts_nextq section 7 rules on synthetic quarters (no store, no network, no real company)."""
import math

import pytest

import score_nextq as Q
from qwen_c.value import menu

R0, YP, YC = 400.0, 190.0, 209.0          # base year 400; the first half 190 a year ago, 209 now: pace +10%
PACE = YC / YP - 1


def test_tolerance_is_the_menus():
    assert Q.TOL == menu.TOL


def test_g_rest_of_the_pace_is_the_pace():
    G_ytd = (YC + (R0 - YP) * (1 + PACE)) / R0 - 1          # ytd's year growth: the rest at the pace
    assert Q.g_rest(G_ytd, R0, YC, YP) == pytest.approx(PACE, abs=1e-12)


@pytest.mark.parametrize("v", [-0.2, 0.0, 0.03, 0.25])
def test_g_rest_of_a_record_option_is_its_own_number(v):
    G = (YC + (R0 - YP) * (1 + v)) / R0 - 1                  # menu.py: (yc + q4p * (1 + v)) / r0 - 1, q4p = R0 - yp
    assert Q.g_rest(G, R0, YC, YP) == pytest.approx(v, abs=1e-12)


def test_g_rest_of_a_guided_year_is_the_year_less_what_is_reported():
    G = 0.08                                                  # guided year: 432; reported 209; the rest 223 against 210
    assert Q.g_rest(G, R0, YC, YP) == pytest.approx(223 / 210 - 1)


def test_g_rest_has_no_figure_without_an_unreported_rest():
    assert Q.g_rest(0.1, 400.0, 420.0, 400.0) is None and Q.g_rest(None, R0, YC, YP) is None


def test_error_metric_and_its_edges():
    assert Q.error(0.10, 0.10) == 0
    assert Q.error(0.21, 0.10) == pytest.approx(math.log(1.21 / 1.10))
    assert Q.error(-1.0, 0.1) == math.inf and Q.error(-1.5, 0.1) == math.inf
    assert Q.error(0.1, -1.0) is None and Q.error(0.1, None) is None


def test_departure_rules():
    assert Q.departure([0.05, 0.06], 0.10) == ("departs", 0.06)
    assert Q.departure([0.15, 0.13], 0.10) == ("departs", 0.13)
    assert Q.departure([0.1005, 0.0995], 0.10) == ("no_departure", None)
    assert Q.departure([0.15, 0.1005], 0.10) == ("one_seed_departs", None)
    assert Q.departure([0.15, 0.05], 0.10) == ("split", None)
    assert Q.departure([0.15, None], 0.10) == ("one_seed_invalid", None)


def test_outcome_and_ties():
    assert Q.outcome(0.01, 0.02) == "win" and Q.outcome(0.02, 0.01) == "loss"
    assert Q.outcome(0.01, 0.01 + 1e-12) == "tie" and Q.outcome(math.inf, math.inf) == "tie"
    assert Q.outcome(math.inf, 0.3) == "loss" and Q.outcome(None, 0.1) is None


def test_sign_p():
    assert Q.sign_p(5, 5) == pytest.approx(1 / 32) and Q.sign_p(0, 4) == 1.0 and Q.sign_p(0, 0) is None


def test_winsorised_mean_clamps_the_tails():
    xs = [-0.01] * 19 + [5.0]
    assert Q.winsorised_mean(xs) == pytest.approx(-0.01)
    assert Q.winsorised_mean(xs, 0, 1) == pytest.approx((19 * -0.01 + 5) / 20)


def rows(per_cohort):
    """{cohort: (wins, losses)} -> rows with d = -0.01 on a win, +0.01 on a loss."""
    return [{"cohort": c, "outcome": o, "d": -0.01 if o == "win" else 0.01}
            for c, (w, l) in per_cohort.items() for o in ["win"] * w + ["loss"] * l]


def test_pass_needs_all_three_conditions():
    v = Q.verdict(rows({1: (15, 5), 2: (15, 5), 3: (15, 5), 4: (10, 10)}))
    assert v["verdict"] == "PASS" and v["cohorts_ahead"] == 3
    v = Q.verdict(rows({1: (30, 5), 2: (30, 5), 3: (8, 12), 4: (8, 12)}))       # pooled 0.69 but only two cohorts ahead
    assert v["verdict"] == "NOT_DECIDED" and v["conditions"] == {"a": True, "b": False, "c": True}
    big = rows({1: (15, 5), 2: (15, 5), 3: (15, 5), 4: (15, 5)})
    for r in big:
        if r["outcome"] == "loss":
            r["d"] = 1.0                                                          # a few large misses outweigh many small wins
    assert Q.verdict(big)["verdict"] == "NOT_DECIDED" and Q.verdict(big)["conditions"]["c"] is False


def test_fail_floor_and_cohorts():
    assert Q.verdict(rows({1: (8, 12), 2: (8, 12), 3: (8, 12), 4: (8, 12)}))["verdict"] == "FAIL"
    assert Q.verdict(rows({1: (5, 10), 2: (5, 10)}))["verdict"] == "NOT_DECIDED"              # 30 departures: under the floor
    assert Q.verdict(rows({1: (30, 40), 2: (1, 1)}))["verdict"] == "NOT_DECIDED"              # 72, but one countable cohort


def test_selection_rule_takes_the_latest_readable_record_else_the_pace():
    found = [{"number": 0.06, "period_of_evidence": "2025-05-01"}, {"number": None, "period_of_evidence": "2025-09-01"},
             {"number": 0.08, "period_of_evidence": "2025-08-01"}, {"number": 0.02, "period_of_evidence": "2025-08-01"}]
    g, src = Q.selection_rule(found, PACE, R0, YC, YP)
    assert src == "guidance" and g == pytest.approx(Q.g_rest(0.08, R0, YC, YP))           # date tie: the first listed
    assert Q.selection_rule([], PACE, R0, YC, YP) == (PACE, "pace")
    assert Q.selection_rule([{"number": None}], PACE, R0, YC, YP) == (PACE, "pace")


def result(G, option="guidance", status="ok", found=(), quarter=2):
    base = {"R0": R0, "ytd": {"revenue": YC, "revenue_prior": YP, "rev_growth": PACE, "end": "2025-06-30", "start": "2025-01-01",
                              "year1_start": "2025-01-01", "quarter": quarter}}
    return {"status": status, "base": base, "checks": {"numbers": {"rev_growth.y1": G}, "options": {"rev_growth.y1": option},
                                                       "found": list(found)}}


def realised_at(g, status="ok"):
    calls = []
    def f(end):
        calls.append(end)
        return {"status": status, "revenue_growth": g, "quarter": {"report_date": "2025-09-30"}}
    f.calls = calls
    return f


def test_name_row_scores_a_departure_on_the_rest_of_year_and_anchors_on_ytd_end():
    G = 0.08                                              # guided year; rest-of-year +6.19% against a pace of +10%
    rq = realised_at(0.05)
    row = Q.name_row(1, [result(G), result(0.07)], rq)
    assert rq.calls == ["2025-06-30"] and row["p1"] == "scored" and row["G"] == G
    assert row["g_qwen"] == pytest.approx(Q.g_rest(G, R0, YC, YP)) and row["outcome"] == "win"


def test_name_row_counts_what_does_not_enter():
    assert Q.name_row(1, [result(0.08), result(None, status="reply_invalid")], realised_at(0.05))["p1"] == "one_seed_invalid"
    ytd_G = (YC + (R0 - YP) * (1 + PACE)) / R0 - 1
    assert Q.name_row(1, [result(ytd_G, "ytd"), result(ytd_G, "ytd")], realised_at(0.05))["p1"] == "no_departure"
    assert Q.name_row(1, [result(0.08), result(0.07)], realised_at(None, "no_quarter_filed"))["p1"] == "no_realised"
    assert Q.name_row(1, [result(0.08), result(0.07)], realised_at(-1.0))["p1"] == "realised_not_positive"
    # the menu did not map year 1's options onto a rest of the year (menu._year1_rest is None): outside the primary, counted
    assert Q.name_row(1, [result(0.08, quarter=4), result(0.07, quarter=4)], realised_at(0.05))["p1"] == "no_rest_of_year"


def test_readings_count_and_verdict():
    rows = [Q.name_row(c, [result(0.08), result(0.07)], realised_at(0.05)) for c in (1, 2, 3, 4) for _ in range(16)]
    r = Q.readings(rows)
    assert r["verdict"] == "PASS" and r["counts"] == {"scored": 64} and r["winner_changes_under_points"] == 0


def named(cohort, cik, results, **meta):
    return {"meta": dict({"cohort": cohort, "cik": cik, "cell": "S|T1", "sector": "S", "cap_tercile": "T1", "in_prior_pool": False}, **meta),
            "results": results}


def test_beside_scores_the_rule_r_and_the_single_quarter():
    found = [{"number": 0.08, "period_of_evidence": "2025-08-01"}]
    row = {"pace": PACE, "R0": R0, "yc": YC, "yp": YP, "found": found}                     # Qwen kept the pace; R is the guidance
    out = Q.beside(row, 0.06, 0.12)
    assert out["rule_source"] == "guidance" and out["g_rule"] == pytest.approx(223 / 210 - 1)
    assert out["s1"] == "loss"                                                             # realised +6%: R (+6.19%) beats the pace
    assert out["single_vs_pace"] == "loss" and out["qwen_vs_single"] == "win"              # +12% is further out than +10%
    assert Q.beside(dict(row, found=[]), 0.06, None) == {"rule_source": "pace", "g_rule": PACE, "s1": "tie"}


def test_score_counts_every_name_and_reads_only_what_a_reading_needs():
    calls = []

    def realised(meta, end):
        calls.append((meta["cik"], end))
        return {"status": "ok", "revenue_growth": 0.05, "quarter": {"report_date": "2025-09-30"}}
    unread = result((YC + (R0 - YP) * (1 + PACE)) / R0 - 1, "ytd")
    unread["checks"]["reverts"] = ["guidance_unreadable: rev_growth.y1 x"]
    names = [named("2025-10-01", "1", [result(0.08), result(0.07)]),
             named("2025-10-01", "2", None),
             named("2025-10-01", "3", [result(None, status="no_call"), result(None, status="no_call")]),
             named("2025-11-20", "1", [result(0.08), result(0.07)], in_prior_pool=True),
             named("2025-11-20", "4", [unread, unread])]
    doc = Q.score(names, realised, lambda meta, row: 0.12)
    assert doc["p1"]["counts"] == {"scored": 2, "no_packet": 1, "no_checked_reply": 1, "no_departure": 1}
    assert doc["attempted"] == {"2025-11-20": 2}
    assert doc["sensitivity"]["first_appearance"]["counts"]["scored"] == 1
    assert doc["sensitivity"]["without_prior_pools"]["counts"]["scored"] == 1
    assert doc["sensitivity"]["without_cohort_1"]["counts"] == {"scored": 1, "no_departure": 1}
    assert doc["single_quarter"]["qwen_vs_rule"] == {"wins": 2, "n": 2, "p": 0.25}
    assert doc["segments"]["option"] == {"guidance": {"wins": 2, "n": 2, "p": 0.25}}
    assert doc["s4"]["median_e_pace"] == pytest.approx(math.log(1.10 / 1.05))
    assert sorted(set(calls)) == [("1", "2025-06-30")]            # a name that kept the pace and found no guidance reads no outcome


def test_the_driver_is_set_to_the_registration():
    assert Q.BY == "2026-12-31" and Q.SEEDS == (1200, 3200) and Q.COHORTS == ("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
