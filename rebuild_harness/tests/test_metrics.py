import math

import numpy as np

from rebuild_harness import metrics as M


def recs(n_dates=6, n=120, seed=0, edge=0.5):
    """score s = 0.8 y + 0.6 z with a yardstick y; the excess return depends on y and on the independent part z (weight edge)."""
    rng = np.random.default_rng(seed)
    out = []
    for d in range(n_dates):
        date = f"2018-{d + 1:02d}-28"
        y = rng.normal(size=n)
        z = rng.normal(size=n)
        s = 0.8 * y + 0.6 * z
        ret = 0.5 * y + edge * z + rng.normal(size=n) * 1.0
        fam = rng.choice(["operating", "financial"], size=n)
        sec = rng.choice(["A", "B", "C"], size=n)
        for i in range(n):
            out.append({"date": date, "cik": f"{d}-{i}", "sector": str(sec[i]), "family": str(fam[i]), "price": 10.0,
                        "score": {"eng": float(s[i]), "ys": float(y[i])}, "vp": {"eng": float(math.exp(s[i]))},
                        "excess": {12: float(ret[i])}, "base": {}, "out": {}, "forecasts": {}})
    return out


def test_ic_is_one_for_a_perfect_ranking_and_nan_for_a_constant():
    r = [{"date": "d", "score": {"e": float(i)}, "excess": {12: float(i) * 2}} for i in range(20)]
    ic = M.ic_by_date(M.by_date(r), "e", 12)
    assert abs(ic["d"][0] - 1.0) < 1e-12 and ic["d"][1] == 20
    r = [{"date": "d", "score": {"e": 1.0}, "excess": {12: float(i)}} for i in range(20)]
    assert math.isnan(M.ic_by_date(M.by_date(r), "e", 12)["d"][0])


def test_a_date_below_the_minimum_is_nan_but_counted():
    r = [{"date": "d", "score": {"e": float(i)}, "excess": {12: float(i)}} for i in range(5)]
    ic = M.ic_by_date(M.by_date(r), "e", 12)
    assert math.isnan(ic["d"][0]) and ic["d"][1] == 5


def test_records_without_an_outcome_are_left_out_not_zeroed():
    r = [{"date": "d", "score": {"e": float(i)}, "excess": {12: float(i) if i % 2 else None}} for i in range(40)]
    assert M.ic_by_date(M.by_date(r), "e", 12)["d"][1] == 20


def test_quintile_spread_positive_for_informative_score_and_nan_when_too_few():
    rec = recs()
    q = M.quintiles_by_date(M.by_date(rec), "eng", 12)
    assert all(v["spread"] > 0 for v in q.values())
    assert all(math.isnan(x) for x in M.quintile_means([0.0] * 10, [1.0] * 10))


def test_pooled_ic_and_sector_neutral_ic_are_positive():
    rbd = M.by_date(recs())
    p, n = M.pooled_ic(rbd, "eng", 12)
    sn = M.sector_neutral_by_date(rbd, "eng", 12)
    assert p > 0.15 and n == 6 * 120
    assert all(v[0] > 0.1 for v in sn.values())


def test_incremental_information_separates_a_new_signal_from_a_repackaged_yardstick():
    rbd = M.by_date(recs(edge=0.6))
    inc = M.incremental_by_date(rbd, "eng", ["ys"], 12)
    assert np.nanmean([v["resid_ic"] for v in inc.values()]) > 0.1
    assert np.nanmean([v["fm_coef"] for v in inc.values()]) > 0.05
    # the return depends on y only: the engine adds nothing beyond the yardstick
    rbd0 = M.by_date(recs(edge=0.0, seed=3))
    inc0 = M.incremental_by_date(rbd0, "eng", ["ys"], 12)
    assert abs(np.nanmean([v["resid_ic"] for v in inc0.values()])) < 0.07
    assert abs(np.nanmean([v["fm_coef"] for v in inc0.values()])) < 0.07


def test_incremental_uses_only_the_common_sample():
    rec = recs(n_dates=2, n=60)
    for r in rec[:30]:
        r["score"]["ys"] = None
    inc = M.incremental_by_date(M.by_date(rec), "eng", ["ys"], 12)
    first = inc["2018-01-28"]
    assert first["n"] == 30 and first["n_engine"] == 60


def test_vp_distribution_shares_and_family_sorting():
    rec = []
    for i in range(100):
        fam = "financial" if i < 30 else "operating"
        vp = 0.3 if i < 20 else (3.0 if 20 <= i < 30 else 1.0)           # every extreme is financial
        rec.append({"date": "d", "family": fam, "vp": {"e": vp}, "score": {}, "excess": {}})
    d = M.vp_distribution(rec, "e")
    assert d["overall"]["share_below_0_4"] == 0.2 and d["overall"]["share_above_2_5"] == 0.1
    assert abs(d["by_family"]["financial"]["share_below_0_4"] - 20 / 30) < 1e-12
    lift = d["family_sorting"]["below_0_4"]["lift_by_family"]
    assert abs(lift["financial"] - 1 / 0.3) < 1e-9 and lift["operating"] == 0.0
    assert d["family_sorting"]["below_0_4"]["cramers_v"] > 0.5
    assert M.vp_distribution([], "e") == {"n": 0}


def test_forecast_error_against_the_naive_forecast():
    rec = []
    for i in range(50):
        rec.append({"date": f"d{i % 5}", "base": {"revenue": 100.0, "operating_margin": 0.20}, "out": {1: {"revenue": 110.0, "operating_margin": 0.22}},
                    "forecasts": {"e": {1: {"revenue": 108.0, "operating_margin": 0.21}}}, "score": {}, "vp": {}, "excess": {}})
    r = M.forecast_error(rec, "e", "revenue", 1)
    assert r["n"] == 50 and r["skill"] > 0 and r["mae_naive"] > r["mae_engine"]
    m = M.forecast_error(rec, "e", "operating_margin", 1)
    assert abs(m["mae_engine"] - 0.01) < 1e-12 and abs(m["mae_naive"] - 0.02) < 1e-12 and abs(m["skill"] - 0.5) < 1e-9
    assert M.forecast_error(rec, "e", "roc", 1) == {"n": 0}
    lo, hi, _ = M.bootstrap_skill(rec, "e", "revenue", 1, n=200)
    assert lo <= r["skill"] <= hi


def test_forecast_log_error_needs_positive_values():
    assert M._err("revenue", -1.0, 5.0) is None and M._err("roc", -1.0, 5.0) == -6.0
    assert M._err("roc", 0.0, 0.0) == 0.0                                  # zero is a value


def test_bootstrap_is_reproducible_and_brackets_the_mean():
    v = [0.02, 0.05, 0.01, 0.04, 0.03, 0.06]
    a, b = M.bootstrap_mean_over_dates(v, n=500), M.bootstrap_mean_over_dates(v, n=500)
    assert a == b and a[0] <= np.mean(v) <= a[1]
    assert math.isnan(M.bootstrap_mean_over_dates([0.1], n=10)[0])


def test_summarize_runs_end_to_end_on_synthetic_records():
    rec = recs(n_dates=5, n=80)
    s = M.summarize(rec, ["eng", "ys"], ["ys"], [12], value_engines=["eng"], n_resamples=100)
    h = s["engines"]["eng"]["horizons"]["12"]
    assert h["mean_ic"] > 0.1 and h["mean_ic_ci90"][0] <= h["mean_ic"] <= h["mean_ic_ci90"][1]
    assert "incremental" in h and "incremental" not in s["engines"]["ys"]["horizons"]["12"]
    assert "value_over_price" in s["engines"]["eng"]
