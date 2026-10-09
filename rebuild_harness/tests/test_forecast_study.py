"""Tests of the forecast study (Addendum Z 5, 6): the walk-forward discipline, the weight estimators, the leverage regression and the information cut."""
import numpy as np
import pandas as pd
import pytest

from rebuild_harness.forecast_study import panel as PN
from rebuild_harness.forecast_study import study as S


def _obs(rows):
    return pd.DataFrame(rows)


def test_population_median_uses_only_outcomes_filed_before_the_origin():
    n = 200
    obs = pd.DataFrame({"family": ["operating"] * n, "g_1": [0.10] * n, "filed_1": ["2017-03-01"] * n})
    late = pd.DataFrame({"family": ["operating"] * n, "g_1": [9.0] * n, "filed_1": ["2018-03-01"] * n})
    pop = S.Population(pd.concat([obs, late], ignore_index=True))
    assert pop.stats("operating", "g", 1, "2017-06-30")["p50"] == pytest.approx(0.10)       # the 2018 outcomes are invisible at 2017-06-30
    assert pop.stats("operating", "g", 1, "2018-06-30")["n"] == 2 * n
    assert pop.stats("operating", "g", 1, "2017-03-01") is None                              # an outcome filed ON the origin is not known (strictly before)


def test_weight_fit_ignores_later_origins_and_unfiled_outcomes():
    rng = np.random.default_rng(0)
    rows = []
    for Y in (2018, 2019, 2020):
        c = rng.normal(0, 1, 400)
        y = 0.5 * c + rng.normal(0, 0.3, 400)                                  # the true weight is 0.5 in every year
        rows.append(pd.DataFrame({"year": Y, "cik": range(400), "y": y, "x_i": 0.0, "x_ii": c, "filed": f"{Y + 1}-03-01"}))
    d = pd.concat(rows, ignore_index=True)
    d.loc[d.year == 2020, "y"] = 100.0 * d.loc[d.year == 2020, "x_ii"]               # a wild year that must not reach the 2019 fit nor, by its filing date, the 2020 fit
    W = S.walk_forward_w(d, [2018, 2019, 2020, 2021])
    assert W[2018] is None                                                         # nothing earlier
    assert W[2019]["mae"] == pytest.approx(0.5, abs=0.1) and W[2019]["n"] == 400
    assert W[2020]["n"] == 800                                                     # 2018 and 2019 (filed 2019-03 and 2020-03, both before 2020-06-30)
    assert W[2021]["n"] == 1200                                                    # the wild 2020 year (filed 2021-03-01) is known by 2021-06-30
    assert W[2021]["mae"] != W[2020]["mae"]


def test_outcome_filed_after_the_origin_year_end_is_not_in_the_fit():
    rng = np.random.default_rng(1)
    c = rng.normal(0, 1, 300)
    d = pd.DataFrame({"year": 2018, "cik": range(300), "y": c, "x_i": 0.0, "x_ii": c, "filed": "2019-07-15"})      # filed after T of 2019
    d = pd.concat([d, pd.DataFrame({"year": 2019, "cik": range(300), "y": c, "x_i": 0.0, "x_ii": c, "filed": "2020-03-01"})], ignore_index=True)
    W = S.walk_forward_w(d, [2019])
    assert W[2019] is None                                                         # the only earlier origin's outcomes arrive after 2019-06-30


def test_mae_grid_recovers_the_weight_and_eb_is_the_truncated_signal_share():
    rng = np.random.default_rng(2)
    p = np.zeros(5000)
    theta = rng.normal(0, 1, 5000)
    c = theta + rng.normal(0, 1, 5000)                                             # signal = truth + noise of equal variance: reliability 0.5
    y = theta + rng.normal(0, 0.5, 5000)
    assert S.fit_w_mae(p, c, y) == pytest.approx(0.5, abs=0.08)
    assert S.fit_w_eb(p, c, y) == pytest.approx(0.5, abs=0.06)
    assert S.fit_w_eb(p, rng.normal(0, 1, 5000), rng.normal(0, 1, 5000)) < 0.1     # a signal unrelated to the outcome gets about 0
    assert S.fit_w_eb(p[:10], np.zeros(10), np.ones(10)) == 0.0                         # no variance, no weight (0.0 is a value)
    assert S.fit_w_mae(p, c, c) == 1.0


def test_leverage_fit_recovers_contribution_margin_and_fixed_cost():
    fye = np.array([f"{y}-12-31" for y in range(2010, 2020)])
    rev = np.linspace(100.0, 190.0, 10)
    oi = 0.4 * rev - 20.0
    h = {"c1": (fye, rev, oi)}
    c, a = S.leverage_fit(h, "c1", "2017-12-31")
    assert c == pytest.approx(0.4) and a == pytest.approx(-20.0)
    assert S.leverage_fit(h, "c1", "2012-12-31") is None                              # only three years up to 2012
    assert S.leverage_fit(h, "nobody", "2017-12-31") is None
    flat = {"c2": (fye, np.full(10, 100.0), oi)}
    assert S.leverage_fit(flat, "c2", "2019-12-31") is None                         # no revenue variation, no slope


def test_reversion_fit_uses_only_filed_outcomes_and_zero_is_a_value():
    n = 300
    rng = np.random.default_rng(3)
    x0 = rng.normal(0.1, 0.05, n)
    a = np.full(n, 0.1)
    o = pd.DataFrame({"family": "operating", "m": x0, "med8": a, "cyc": rng.uniform(0, 1, n), "m_1": x0 + 0.6 * (a - x0), "filed_1": "2017-03-01"})
    o2 = o.copy()
    o2["m_1"], o2["filed_1"] = x0, "2019-03-01"                                    # persistence in a later set
    rv = S.Reversion(pd.concat([o, o2], ignore_index=True), "operating", "m", "med8", "m", True)
    assert rv.fit(1, "2018-06-30")["lam"]["_pooled"] == pytest.approx(0.6, abs=0.06)
    assert rv.fit(1, "2020-06-30")["lam"]["_pooled"] < 0.6                         # now both sets are known
    pred, lam, band = rv.predict(1, "2018-06-30", 0.2, 0.1, 0.5)
    assert band in ("low", "mid", "high") and pred == pytest.approx(0.2 + lam * (0.1 - 0.2))
    zero = pd.concat([o.assign(m_1=x0), o2], ignore_index=True)
    assert S.Reversion(zero, "operating", "m", "med8", "m", True).fit(1, "2018-06-30")["lam"]["_pooled"] == 0.0


def test_assert_cut_refuses_a_2025_filing():
    d = pd.DataFrame({"filed_1": ["2024-12-31", None], "filed_2": [None, None], "filed_3": [None, None], "own_filed": ["2024-12-31", "2024-01-01"]})
    PN.assert_cut(d)
    d.loc[0, "filed_1"] = "2025-02-14"
    with pytest.raises(AssertionError):
        PN.assert_cut(d)


def test_cluster_t_handles_ties_and_small_samples():
    s = pd.Series([0.1] * 50 + [np.nan])
    r = S.cluster_t(s, pd.Series(range(51)))
    assert r["mean"] == pytest.approx(0.1) and r["n"] == 50
    assert np.isnan(S.cluster_t(pd.Series([1.0, 2.0]), pd.Series([1, 2]))["t"])
