"""Tests of the Stage 1 forensic instruments (rebuild_harness/forensics): the implied-input solve, the oracle paths, the block bootstrap, the draw variants."""
import numpy as np

from rebuild_harness.forensics import analytics as A
from rebuild_harness.forensics import fxm


def test_solve_implied_finds_root_nearest_x0():
    f = lambda x: x * x - 0.25            # roots +-0.5
    x, st = A.solve_implied(f, np.linspace(-1, 1, 41), 0.4)
    assert st == "ok" and abs(x - 0.5) < 1e-9
    x, st = A.solve_implied(f, np.linspace(-1, 1, 41), -0.4)
    assert abs(x + 0.5) < 1e-9


def test_solve_implied_no_root_statuses():
    x, st = A.solve_implied(lambda v: v + 5.0, np.linspace(0, 1, 11), 0.5)
    assert x is None and st == "no_root_value_above_price"
    x, st = A.solve_implied(lambda v: v - 5.0, np.linspace(0, 1, 11), 0.5)
    assert x is None and st == "no_root_value_below_price"


def test_oracle_paths_consecutive_and_zero_is_a_value():
    real = {"base": {"revenue": 100.0, "tbv": 50.0, "operating_margin": 0.1},
            "years": [{"k": 1, "revenue": 110.0, "operating_margin": 0.0, "rote": 0.0, "tbv": 55.0},
                      {"k": 2, "revenue": None, "operating_margin": 0.2, "rote": 0.1, "tbv": 60.0},
                      {"k": 3, "revenue": 130.0, "operating_margin": 0.2, "rote": 0.1, "tbv": 66.0}]}
    p = A.oracle_paths(real, "operating")
    assert list(p["g"]) == [1] and abs(p["g"][1] - 0.10) < 1e-12      # the chain stops at the missing revenue
    assert p["m"][1] == 0.0 and 3 in p["m"]                            # margin 0.0 is kept
    assert p["rote"][1] == 0.0
    pf = A.oracle_paths(real, "financial")
    assert list(pf["g"]) == [1, 2, 3] and abs(pf["g"][2] - 60 / 55 + 1) < 1e-12


def test_draw_summary_variants_order():
    # operating draws: (equity, pv_terminal, rest incl. items, factor, cap leg)
    rng = np.random.default_rng(1)
    d = [(max(0.0, (e + t) * 1.0), t, e, 1.0, e) for e, t in zip(rng.uniform(1, 5, 500), rng.uniform(0, 20, 500))]
    s = A.draw_summary(d, 1.0, 3.0)
    assert s["notv"]["p50"] <= s["cap50"]["p50"] <= s["full"]["p50"]
    assert 0.0 <= s["full"]["prob_above_price"] <= 1.0


def test_block_ci_contains_mean_and_is_wider_with_blocks():
    rng = np.random.default_rng(2)
    v = np.cumsum(rng.normal(size=48)) * 0.1
    lo1, hi1 = fxm.block_ci(v, 1)
    lo6, hi6 = fxm.block_ci(v, 6)
    assert lo1 < v.mean() < hi1
    assert (hi6 - lo6) > (hi1 - lo1)
