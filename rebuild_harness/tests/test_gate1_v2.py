"""Tests of the registration-v2 machinery (rebuild_harness/gate1_v2.py) on synthetic panels: no file, no price, no network.  Bootstrap sizes are small here; the maths is checked
against independent computations (dummy-variable OLS, a hand-built cluster-robust variance)."""
import json
import math
import random

import numpy as np
import pytest

from rebuild_harness import gate1_metrics as gm
from rebuild_harness import gate1_v2 as v2

ENG = gm.ENGINE


def rec(date, i, vp, excess, industry="I1", sector=None, family="operating", ys=None, mc=1e9, **extra):
    ys = ys if ys is not None else {y: 0.5 for y in gm.YARDSTICKS}
    r = {"date": date, "cik": str(i), "industry": industry, "sector": sector or ("S1" if industry in ("I1", "I2") else "S2"), "family": family, "status": "valued",
         "mcap_group": ">=300M", "vp": vp, "score": dict({ENG: vp}, **ys), "excess": {12: excess}, "bounds": {}, "market_cap": mc, "stale": False}
    r.update(extra)
    return r


def population(date, n=160, slope=0.5, seed=1, noise=0.05, industries=("I1", "I2", "I3", "I4")):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        vp = math.exp(rng.gauss(0, 0.5))
        ys = {y: rng.random() for y in gm.YARDSTICKS}
        rows.append(rec(date, f"{date}-{i}", vp, slope * (vp - 1.0) + rng.gauss(0, noise), industry=industries[i % len(industries)], ys=ys, mc=1e8 * math.exp(rng.gauss(2, 1))))
    return rows


def panel_rows(slope, n_dates=8, seed=100, noise=0.05):
    rows = []
    for k in range(n_dates):
        rows += population(f"2020-{k + 1:02d}-28", slope=slope, seed=seed + k, noise=noise)
    return rows


# ---- the machinery ---------------------------------------------------------------------------------------------------------------------------

def test_absorbed_fixed_effects_equal_the_dummy_variable_regression():
    rng = np.random.default_rng(3)
    n = 600
    d = rng.integers(0, 6, n)
    ind = rng.integers(0, 9, n)
    x = rng.normal(size=(n, 3)) + 0.4 * ind[:, None] * 0.1
    y = 0.7 * x[:, 0] - 0.3 * x[:, 1] + 0.5 * d + 0.2 * ind + rng.normal(size=n)
    b, _u, _Xt, _yt = v2.fe_ols(y, x, [d, ind])
    D = np.column_stack([np.eye(6)[d], np.eye(9)[ind][:, 1:]])
    full, *_ = np.linalg.lstsq(np.column_stack([x, D]), y, rcond=None)
    assert b == pytest.approx(full[:3], abs=1e-7)


def test_demean_with_one_factor_is_the_group_mean_removal_and_two_factors_remove_both():
    v = np.array([1.0, 2.0, 3.0, 4.0, 10.0, 12.0])
    g = np.array([0, 0, 0, 1, 1, 1])
    assert v2.demean(v, [g]) == pytest.approx([-1, 0, 1, -14 / 3, 4 / 3, 10 / 3])
    rng = np.random.default_rng(1)
    a, c = rng.integers(0, 5, 400), rng.integers(0, 7, 400)
    z = v2.demean(rng.normal(size=400) + a + 2 * c, [a, c])
    assert max(abs(z[a == k].mean()) for k in range(5)) < 1e-8 and max(abs(z[c == k].mean()) for k in range(7)) < 1e-8


def test_cluster_se_matches_a_hand_computed_sandwich():
    rng = np.random.default_rng(7)
    n, G = 200, 10
    g = np.repeat(np.arange(G), n // G)
    X = np.column_stack([rng.normal(size=n), rng.normal(size=n)])
    u = rng.normal(size=n) * (1 + g)
    se = v2.cluster_se(X, u, g, 0)
    bread = np.linalg.inv(X.T @ X)
    meat = sum(np.outer(X[g == k].T @ u[g == k], X[g == k].T @ u[g == k]) for k in range(G))
    V = bread @ meat @ bread * (G / (G - 1)) * ((n - 1) / (n - 2))
    assert se == pytest.approx(math.sqrt(V[0, 0]), rel=1e-10)


def test_the_wild_cluster_bootstrap_is_seeded_and_keeps_the_null_imposed_t_distribution_centred():
    rng = np.random.default_rng(11)
    n, G = 480, 12
    g = np.repeat(np.arange(G), n // G)
    x = rng.normal(size=n)
    y = 0.4 * x + rng.normal(size=n)
    a = v2.wild_cluster_bootstrap(y, x[:, None], [g], g, n_boot=199, seed=5)
    b = v2.wild_cluster_bootstrap(y, x[:, None], [g], g, n_boot=199, seed=5)
    assert a["lower_90_one_sided"] == b["lower_90_one_sided"] and a["p_one_sided"] == b["p_one_sided"]
    assert a["beta"] == pytest.approx(0.4, abs=0.1) and 0 < a["lower_90_one_sided"] < a["beta"] and a["p_one_sided"] < 0.05 and a["n_clusters"] == 12


def test_the_one_sided_lower_bound_rarely_clears_zero_when_there_is_no_effect():
    """Calibration: with no effect the null-imposed wild cluster bootstrap-t should pass (lower bound > 0) in about 10% of samples; 40 samples, a ceiling of 25% (binomial tail < 1%)."""
    rng = np.random.default_rng(2024)
    n, G = 120, 12
    g = np.repeat(np.arange(G), n // G)
    hits = 0
    for k in range(40):
        x = rng.normal(size=n)
        y = rng.normal(size=n) * (1.0 + (g % 3))                            # cluster-heteroskedastic noise, no effect
        hits += v2.wild_cluster_bootstrap(y, x[:, None], [g], g, n_boot=99, seed=k)["lower_90_one_sided"] > 0
    assert hits <= 10


# ---- B1 ---------------------------------------------------------------------------------------------------------------------------------------

def test_b1_pooled_passes_a_real_signal_and_reports_the_share_of_positive_months():
    r = v2.b1_pooled(panel_rows(0.5), "excluded", n_boot=199)
    assert r["status"] == "pass" and r["lower_90_one_sided"] > 0 and r["beta"] > 0.1 and r["n_months"] == 8 and r["share_positive_monthly_coefficients"] == 1.0
    assert r["n"] == 8 * 160 and r["n_clusters"] == 8 and r["effects"] == "industry" and "engine" == r["columns"][0]


def test_b1_pooled_fails_a_reversed_signal_and_a_noise_engine_has_a_lower_bound_below_zero():
    assert v2.b1_pooled(panel_rows(-0.5), "excluded", n_boot=199)["status"] == "fail"
    noise = v2.b1_pooled(panel_rows(0.0, noise=0.2), "excluded", n_boot=199)
    assert noise["status"] == "fail" and noise["lower_90_one_sided"] < 0 < 1                     # a point estimate of either sign: the interval rule is what passes or fails
    assert v2.b1_pooled(population("d1", n=10), "excluded", n_boot=20)["status"] == "not computed"


def test_b1_pooled_uses_industry_and_date_effects():
    rng = random.Random(5)
    rows = []
    for k in range(6):
        for i in range(150):
            ind = ("A", "B", "C")[i % 3]
            vp = math.exp(rng.gauss(0, 0.3)) * {"A": 0.5, "B": 1.0, "C": 2.0}[ind] * (1 + 0.1 * k)       # the industry sets the level of value / price and of the return; the date shifts both
            ex = {"A": -0.2, "B": 0.0, "C": 0.2}[ind] + 0.05 * k + rng.gauss(0, 0.05)
            rows.append(rec(f"2020-{k + 1:02d}-28", f"{k}-{i}", vp, ex, industry=ind, ys={y: rng.random() for y in gm.YARDSTICKS}))
    r = v2.b1_pooled(rows, "excluded", n_boot=99)
    assert abs(r["beta"]) < 0.05 and r["status"] == "fail"


def test_the_survivorship_bound_changes_the_outcome_used():
    rows = []
    for r in panel_rows(0.5, n_dates=5, seed=7):
        r["bounds"] = {12: {"excluded": r["excess"][12], "minus100": -1.0, "last_close": r["excess"][12]}}
        rows.append(r)
    ex = v2.b1_pooled(rows, "excluded", n_boot=99)
    m100 = v2.b1_pooled(rows, "minus100", n_boot=99)
    assert ex["status"] == "pass" and abs(m100["beta"]) < 1e-9 and m100["status"] == "fail"


def test_a_missing_yardstick_stays_in_the_pooled_regression_at_the_median_rank_with_an_indicator():
    rows = panel_rows(0.5, n_dates=4, seed=9)
    for r in rows[::7]:
        r["score"]["yardstick_gross_profitability"] = None
    pn = v2.build_panel(rows, "excluded")
    assert len(pn["y"]) == len(rows) and "missing:yardstick_gross_profitability" in pn["cols"] and "missing:yardstick_fcf_yield" not in pn["cols"]
    j = pn["cols"].index("yardstick_gross_profitability")
    jm = pn["cols"].index("missing:yardstick_gross_profitability")
    miss = pn["X"][:, jm] == 1.0
    assert miss.sum() == len(rows[::7]) and (pn["X"][miss, j] == 0.5).all()


# ---- B2 ---------------------------------------------------------------------------------------------------------------------------------------

def test_b2_has_a_pass_a_strong_pass_and_a_fail_and_reports_the_raw_spread():
    strong = v2.b2_v2(panel_rows(0.5), "excluded")
    assert strong["status"] == "strong pass" and strong["mean_spread_residual"] >= 0.03 and strong["mean_spread_raw"] > 0.1 and strong["n_dates"] == 8
    rev = v2.b2_v2(panel_rows(-0.5), "excluded")
    assert rev["status"] == "fail" and rev["mean_spread_residual"] < 0
    # a weak signal: a positive residual spread below 3 pp is a pass, not a strong pass
    weak = v2.b2_v2(panel_rows(0.005, noise=0.1, seed=300), "excluded")
    assert weak["status"] in ("pass", "fail") and (weak["status"] != "pass" or weak["mean_spread_residual"] < v2.B2_STRONG)


def test_b2_sector_and_size_neutral_variants_run_on_the_same_rows():
    rows = panel_rows(0.5, n_dates=4, seed=40)
    for g in ("sector", "size"):
        r = v2.b2_v2(rows, "excluded", group=g)
        assert r["status"] == "strong pass" and r["group"] == g


# ---- B3 ---------------------------------------------------------------------------------------------------------------------------------------

def test_b3_level_is_the_universe_median_in_the_band_and_the_diagnostics_do_not_decide():
    def rows_with(vps, fam="operating"):
        return [rec(f"2020-{1 + i % 3:02d}-28", i, v, 0.0, family=fam) for i, v in enumerate(vps)]
    ok = v2.b3_v2(rows_with([0.5, 0.7, 1.0, 1.4, 3.0]))
    assert ok["median_vp"] == 1.0 and ok["status"] == "pass" and ok["band"] == [0.67, 1.5]
    assert v2.b3_v2(rows_with([0.2, 0.3, 0.5, 0.66, 0.9]))["status"] == "fail"                    # median 0.5
    assert v2.b3_v2(rows_with([0.67] * 3))["status"] == "pass" and v2.b3_v2(rows_with([1.5] * 3))["status"] == "pass" and v2.b3_v2(rows_with([1.51] * 3))["status"] == "fail"
    mixed = rows_with([0.1] * 10 + [3.0] * 10) + rows_with([1.0] * 11, fam="financial")
    b = v2.b3_v2(mixed)
    assert b["status"] == "pass" and b["diagnostics"]["share_extreme"] == pytest.approx(20 / 31) and set(b["family_medians"]) == {"operating", "financial"}   # many extremes: still a pass
    assert len(b["median_vp_by_date"]) == 3 and v2.b3_v2([])["status"] == "not computed"


# ---- B4 ---------------------------------------------------------------------------------------------------------------------------------------

def _fc(g_p50, g10, g90, m_p50, m10, m90):
    return {"growth": {"p10": g10, "p50": g_p50, "p90": g90}, "margin": {"p10": m10, "p50": m_p50, "p90": m90}}


def forecast_row(i, fam="operating", engine_g=0.05, naive_g=0.0, actual_g=0.06, engine_m=0.11, m0=0.10, actual_m=0.115, growth_latest=0.02):
    return rec("2022-03-31", i, 1.0, 0.0, family=fam, fq=_fc(engine_g, engine_g - 0.1, engine_g + 0.1, engine_m, engine_m - 0.03, engine_m + 0.03), g_naive=naive_g, m0=m0,
               base={"revenue": 100.0}, out1={"revenue": 100.0 * (1 + actual_g), "operating_margin": actual_m}, state={"growth_latest": growth_latest})


def rote_row(i, engine=0.11, naive=0.09, actual=0.12):
    return rec("2022-03-31", i, 1.0, 0.0, family="financial", fq={"rote": {"p10": engine - 0.04, "p50": engine, "p90": engine + 0.04}}, state={"rote_latest": naive}, out1={"rote": actual})


def test_b4_compares_the_p50_with_the_naive_baseline_per_family_and_reports_coverage_and_direction():
    rows = [forecast_row(i) for i in range(10)] + [rote_row(100 + i) for i in range(10)]
    b = v2.b4_v2(rows)
    g = b["by_family_measure"]["revenue_growth | operating"]
    assert g["n"] == 10 and g["median_abs_error_engine"] == pytest.approx(0.01) and g["median_abs_error_naive"] == pytest.approx(0.06) and g["engine_not_worse"]
    assert g["coverage_p10_p90"] == 1.0 and g["directional_accuracy"] == 1.0                      # forecast 0.05 and actual 0.06 both above the latest growth 0.02
    m = b["by_family_measure"]["operating_margin | operating"]
    assert m["median_abs_error_engine"] == pytest.approx(0.005) and m["median_abs_error_naive"] == pytest.approx(0.015) and m["directional_accuracy"] == 1.0
    r = b["by_family_measure"]["rote | financial"]
    assert r["median_abs_error_engine"] == pytest.approx(0.01) and r["median_abs_error_naive"] == pytest.approx(0.03) and r["status"] == "pass"
    assert b["by_family_measure"]["revenue_growth | commodity"]["status"] == "not computed" and b["status"] == "not computed"          # a family-measure with no data: the bar is not computed
    full = v2.b4_v2(rows + [forecast_row(200 + i, fam="commodity") for i in range(5)])
    assert full["status"] == "pass"


def test_b4_fails_when_any_required_measure_is_worse_than_naive_and_direction_ties_are_excluded():
    rows = [forecast_row(i) for i in range(6)] + [forecast_row(10 + i, fam="commodity") for i in range(6)] + [rote_row(100 + i, engine=0.2, naive=0.12, actual=0.12) for i in range(4)]
    b = v2.b4_v2(rows)
    assert b["by_family_measure"]["rote | financial"]["status"] == "fail" and b["status"] == "fail"
    tie = v2.b4_v2([forecast_row(i, engine_m=0.10, m0=0.10) for i in range(5)])                 # the forecast change from the base is exactly 0: no direction
    m = tie["by_family_measure"]["operating_margin | operating"]
    assert m["directional_accuracy"] is None and m["n_direction"] == 0 and m["n_direction_excluded_zero_change"] == 5
    wrong = v2.b4_v2([forecast_row(i, actual_m=0.07) for i in range(4)])                       # forecast margin up (0.11 against 0.10), outcome down (0.07), outside P10 = 0.08
    assert wrong["by_family_measure"]["operating_margin | operating"]["directional_accuracy"] == 0.0
    assert wrong["by_family_measure"]["operating_margin | operating"]["coverage_p10_p90"] == 0.0
    edge = v2.b4_v2([forecast_row(i, actual_m=0.08) for i in range(4)])                        # exactly on the P10 (0.11 - 0.03): inside
    assert edge["by_family_measure"]["operating_margin | operating"]["coverage_p10_p90"] == 1.0
    # a zero error is a value: a perfect forecast has median error 0.0
    perfect = v2.b4_v2([forecast_row(i, engine_g=0.06, actual_g=0.06) for i in range(3)])
    assert perfect["by_family_measure"]["revenue_growth | operating"]["median_abs_error_engine"] == pytest.approx(0.0, abs=1e-12)


# ---- B5 and the whole -------------------------------------------------------------------------------------------------------------------------

def test_b5_keeps_the_sign_without_the_top_one_percent_and_flags_a_sign_that_is_carried_by_outliers():
    rows = panel_rows(0.5, n_dates=6, seed=60)
    out = v2.b5_and_b1_b2(rows, "excluded", n_boot=99)
    assert out["B5"]["status"] == "pass" and all(out["B5"]["direction_checks"].values())
    assert out["B5"]["without_top1pct_abs_resid"]["n_removed"] == pytest.approx(0.01 * 6 * 160, abs=3)
    assert set(out["variants_reported"]) >= {"sector-neutral", "size-neutral"}
    # a signal that lives only in a handful of extreme observations: positive with them, gone without them
    rng = random.Random(8)
    rows = []
    for k in range(6):
        for i in range(160):
            vp = math.exp(rng.gauss(0, 0.5))
            ex = rng.gauss(0, 0.1)
            if i < 2:
                vp, ex = 3.0 + i, 40.0           # 12 of 960 observations (1.25%): a huge positive return on the highest value / price
            rows.append(rec(f"2020-{k + 1:02d}-28", f"{k}-{i}", vp, ex, industry=("I1", "I2", "I3", "I4")[i % 4], ys={y: rng.random() for y in gm.YARDSTICKS}))
    o = v2.b5_and_b1_b2(rows, "excluded", n_boot=49)
    assert o["B1"]["beta"] > 0 and o["B5"]["without_top1pct_abs_resid"]["B1"]["beta"] < o["B1"]["beta"] and o["B5"]["status"] in ("pass", "fail")


def test_the_erp_shift_variants_use_their_own_scores_and_drop_names_without_one():
    rows = panel_rows(0.5, n_dates=5, seed=70)
    for i, r in enumerate(rows):
        r["score_alt"] = {"erp+100bp": r["vp"] * 0.8, "erp-100bp": None if i % 5 == 0 else r["vp"] * 1.25}
    out = v2.b5_and_b1_b2(rows, "excluded", n_boot=49)
    up, dn = out["variants_reported"]["equity premium +100bp"], out["variants_reported"]["equity premium -100bp"]
    assert up["B1"]["n"] == 5 * 160 and dn["B1"]["n"] < up["B1"]["n"] and up["B1"]["beta"] > 0                  # a monotone rescaling keeps every rank: the same coefficient
    base = v2.b1_pooled(rows, "excluded", n_boot=49)["beta"]
    assert up["B1"]["beta"] == pytest.approx(base, abs=1e-9)


def _whole(bounds_fn, seed):
    rows = []
    for r in panel_rows(0.5, n_dates=6, seed=seed):
        r["bounds"] = {12: bounds_fn(r["excess"][12])}
        r.update(fq=_fc(0.05, -0.05, 0.15, 0.11, 0.08, 0.14), g_naive=0.0, m0=0.10, base={"revenue": 100.0}, out1={"revenue": 106.0, "operating_margin": 0.115}, state={"growth_latest": 0.02})
        rows.append(r)
    rows += [forecast_row(500 + i, fam="commodity") for i in range(6)] + [rote_row(600 + i) for i in range(6)]
    return rows


def test_the_whole_outcome_is_pass_when_every_hard_bar_passes_under_all_three_bounds():
    rows = _whole(lambda e: {"excluded": e, "minus100": e, "last_close": e}, 80)
    out = v2.v2_bars(rows, ">=300M", n_boot=49, return_end="2020-12-31")
    assert out["bar_status_over_bounds"] == {"B1": "pass", "B2": "pass", "B3": "pass", "B4": "pass", "B5": "pass"} and out["outcome"] == "PASS"
    assert out["B2_strong_pass_by_bound"] == {"excluded": True, "minus100": True, "last_close": True} and out["n_valued_return_dates"] == 6 * 160
    assert out["B3"]["status"] == "pass" and out["B4"]["status"] == "pass" and out["return_dates"][0] == "2020-01-28"


def test_the_whole_outcome_is_not_decided_when_hard_bars_straddle_the_bounds_and_fail_when_one_fails_under_all():
    rows = _whole(lambda e: {"excluded": e, "minus100": -1.0, "last_close": e}, 90)
    out = v2.v2_bars(rows, ">=300M", n_boot=49, return_end="2020-12-31")
    assert out["bar_status_over_bounds"]["B1"] == "not decided" and out["bar_status_over_bounds"]["B2"] == "not decided" and out["outcome"] == "NOT DECIDED"
    bad = _whole(lambda e: {"excluded": -1.0, "minus100": -1.0, "last_close": -1.0}, 91)                  # no cross-sectional information under any bound
    assert v2.v2_bars(bad, ">=300M", n_boot=49, return_end="2020-12-31")["outcome"] == "FAIL"
    assert v2.over_bounds(["pass", "pass", "pass"]) == "pass" and v2.over_bounds(["fail"] * 3) == "fail" and v2.over_bounds(["pass", "fail", "pass"]) == "not decided"
    assert v2.over_bounds(["not computed"] * 3) == "not computed"
    assert out["outcome_rule"].startswith("PASS: every hard bar passes under all three bounds")


# ---- the report -------------------------------------------------------------------------------------------------------------------------------

def _write_run(tmp_path, n_dates=5, n=160):
    import gzip
    rng = random.Random(3)
    for k in range(n_dates):
        d = f"2020-{k + 1:02d}-28"
        with gzip.open(tmp_path / f"records_{d}.jsonl.gz", "wt", encoding="utf-8") as f:
            for i in range(n):
                vp = math.exp(rng.gauss(0, 0.5))
                price = 10.0
                ex = 0.5 * (vp - 1.0) + rng.gauss(0, 0.05)
                fam = "operating" if i % 8 else "commodity"
                ys = {y: rng.random() for y in gm.YARDSTICKS}
                rec_ = {"date": d, "cik": f"{k}-{i}", "ticker": f"T{i}", "industry": ("I1", "I2", "I3", "I4")[i % 4], "sector": ("S1", "S1", "S2", "S2")[i % 4], "family": fam, "status": "valued",
                        "reasons": [], "price": price, "market_cap": 1e8 * math.exp(rng.gauss(2, 1)), "mcap_group": ">=300M", "base_age_months": 5.0, "score": dict({ENG: vp}, **ys),
                        "excess": {"12": ex}, "bounds": {"12": {"excluded": ex, "minus100": ex, "last_close": ex}}, "base": {"revenue": 100.0}, "out": {"1": {"revenue": 106.0, "operating_margin": 0.115}},
                        "stamps": [], "score_alt": {"erp+100bp": vp * 0.9, "erp-100bp": vp * 1.1},
                        "val": {"iv_ps": {"p10": 0.5 * vp * price, "p25": 0.8 * vp * price, "p50": vp * price, "p75": 1.2 * vp * price, "p90": 1.5 * vp * price}, "iv_point_p50_inputs_ps": vp * price,
                                "secondary_ps": vp * price, "model_disagreement": 0.0, "tv_share_p50": 0.5, "n_valid": 2000, "n_draws": 2000,
                                "forecast": {"year1_growth_point": 0.05, "year1_margin_point": 0.11, "year1_quantiles": _fc(0.05, -0.05, 0.15, 0.11, 0.08, 0.14)}, "state": {"op_margin": 0.10, "growth_latest": 0.02},
                                "prior_meta": {"mechanical_baseline_g1": 0.0}, "discount": {"coe": 0.08, "wacc": 0.07, "beta_levered": 1.0, "beta_unlevered": 0.9, "erp": 0.05, "de_ratio": 0.2}, "inputs": {}}}
                f.write(json.dumps(rec_) + "\n")
    (tmp_path / "run_meta.json").write_text(json.dumps({"git_head": "x", "dates": [], "price_file": str(tmp_path / "none.json")}), encoding="utf-8")


def test_the_v2_report_builds_and_renders_every_bar(tmp_path):
    from rebuild_harness import gate1_report as rp
    _write_run(tmp_path)
    rep = rp.build(tmp_path, v2=True, n_boot=49, extremes_dates=())
    r = rep["gate1_universe_ge_300M"]
    assert rep["registration"] == "v2" and r["by_bound"]["excluded"]["B1"]["status"] == "pass" and r["B3"]["status"] == "pass"
    assert r["B4"]["by_family_measure"]["revenue_growth | operating"]["status"] == "pass" and "equity premium +100bp" in r["by_bound"]["excluded"]["variants_reported"]
    md = rp.render(rep)
    for needle in ("registration v2", "B1: pooled regression", "one-sided 90% lower bound", "B2: industry-neutral", "B3: level", "B4: forecasts", "B5: stability", "B5 reported variants",
                   "PROVISIONAL", "Outcome (provisional)"):
        assert needle in md


def test_the_round_comparison_reads_runs_on_the_same_dates_and_computes_v2_bars_for_one(tmp_path):
    from rebuild_harness import gate1_compare_v2 as cmp
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    _write_run(a, n_dates=4)
    _write_run(b, n_dates=3)
    dates = [f"2020-{k + 1:02d}-28" for k in range(3)]
    out = tmp_path / "cmp.md"
    cmp.main(["--out", str(out), "--run", f"old={a}", "--run", f"new={b}", "--dates", *dates, "--bars", "old", "--n-boot", "49"])
    md = out.read_text(encoding="utf-8")
    js = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert js["summaries"]["old"]["n"] == js["summaries"]["new"]["n"] == 3 * 160                     # the same dates: the fourth date of `old` is not read
    assert "median IV / price (operating)" in md and "old: registration-v2 bars B1-B3" in md and "B3: median IV / price" in md and "PROVISIONAL" in md
    assert js["summaries"]["old"]["operating"]["share_draws_floored_at_zero"] == 0.0
