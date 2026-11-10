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
