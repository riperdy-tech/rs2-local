"""C6: every metric of sections 7-8, on SYNTHETIC data with hand-computed answers (never on the real prices), and the look gate."""
import math

import numpy as np
import pytest

from backtest_phase2 import metrics, run_look
from backtest_phase2.common import PriceBook
from backtest_phase2.look_gate import gate_path, require_look


# ---- Spearman ---------------------------------------------------------------------------------------------------------

def test_spearman_hand_value_no_ties():
    # d = [1, -1, 1, -1, 0], sum d^2 = 4: rho = 1 - 6 x 4 / (5 x 24) = 0.8
    assert metrics.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == pytest.approx(0.8)


def test_spearman_ties_are_averaged():
    # ranks x = [1, 2.5, 2.5, 4], y = [1, 2, 3, 4]: cov 1.125, var 1.125 and 1.25 -> 1.125 / sqrt(1.125 x 1.25)
    assert metrics.spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(1.125 / math.sqrt(1.125 * 1.25))
    assert list(metrics.rankdata_avg([10, 20, 20, 20, 5])) == [2.0, 4.0, 4.0, 4.0, 1.0]


def test_spearman_extremes_and_degenerate_cases():
    assert metrics.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert metrics.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert math.isnan(metrics.spearman([1, 1, 1, 1], [1, 2, 3, 4]))
    assert math.isnan(metrics.spearman([1, 2], [1, 2]))


# ---- the value/price of the average performer ----------------------------------------------------------------------------

def test_apv_median_uses_the_40th_to_60th_percentile_of_returns_inclusive():
    r = np.arange(1.0, 11.0)                        # 1..10: the 40th and 60th percentiles are 4.6 and 6.4 (linear interpolation)
    vp = np.array([9, 9, 9, 9, 0.8, 1.2, 9, 9, 9, 9])
    assert metrics.apv_median(vp, r) == pytest.approx(1.0)       # the two names with R = 5 and 6: median of 0.8 and 1.2
    r2 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert metrics.apv_median([5, 5, 7, 5, 5], r2) == pytest.approx(7.0)    # p40 = 2.6, p60 = 3.4: only R = 3


def test_apv_is_the_exponential_of_the_mean_log_of_the_per_date_medians():
    assert metrics.apv([1.0, 4.0]) == pytest.approx(2.0)
    assert metrics.apv([0.9, 0.9, 0.9]) == pytest.approx(0.9)
    assert math.isnan(metrics.apv([]))


# ---- calls ------------------------------------------------------------------------------------------------------------------

def test_buy_call_lift_in_points_over_the_base_rate_of_beating_spy():
    vp = np.array([1.5, 1.4, 1.3, 1.29, 0.5, 0.6, 0.7, 1.0])
    r = np.array([0.30, 0.20, -0.10, 0.50, 0.00, 0.40, -0.20, 0.10])
    lift, n = metrics.call_lift(vp, r, r_spy=0.15, buy=True)
    # buys: V/P >= 1.3 -> R = .30, .20, -.10: two of three beat 15%; all names: .30, .20, .50, .40 beat it: 4 of 8
    assert n == 3
    assert lift == pytest.approx((2 / 3 - 4 / 8) * 100.0)


def test_avoid_call_lift_measures_underperformance():
    vp = np.array([0.7, 0.69, 0.71, 1.5])
    r = np.array([-0.2, 0.3, -0.1, 0.2])
    lift, n = metrics.call_lift(vp, r, r_spy=0.10, buy=False)
    # avoids: V/P <= 0.7 -> R = -.2 (under), .3 (not): 1 of 2; all names under 10%: -.2, -.1 -> 2 of 4
    assert n == 2 and lift == pytest.approx((0.5 - 0.5) * 100.0)
    lift, n = metrics.call_lift(np.array([0.5, 0.6, 2.0]), np.array([-0.5, -0.4, 0.5]), r_spy=0.0, buy=False)
    assert lift == pytest.approx((1.0 - 2 / 3) * 100.0)


def test_no_calls_is_undefined_not_zero():
    lift, n = metrics.call_lift([1.0, 1.1], [0.1, 0.2], 0.0, buy=True)
    assert n == 0 and math.isnan(lift)


def test_thin_date_is_flagged_and_still_counts():
    n = 20
    t = {"vp_B": np.full(n, 1.5), "vp_S": np.full(n, 1.5), "r": np.linspace(-0.2, 0.5, n), "r_spy": 0.1}
    s = metrics.date_stats(t)
    assert s["thin_S"] is True and s["calls_S"] == 20 and not math.isnan(s["lift_S"])


# ---- quintiles and the calibration slope -------------------------------------------------------------------------------------

def test_quintile_excess_return_over_the_mean():
    vp = np.arange(1.0, 11.0)
    r = np.arange(1.0, 11.0)
    assert metrics.quintile_excess(vp, r) == pytest.approx([-4.0, -2.0, 0.0, 2.0, 4.0])


def test_calibration_slope_and_break_even_pooled_ols():
    # one date: x = ln(V/P) = 0..4, ln(1+R) = 2x + 1: the median is 5, so y = 2x - 4: lambda = 2, a = -4, V/P* = exp(4/2)
    x = np.arange(5.0)
    vp = np.exp(x)
    r = np.exp(2 * x + 1) - 1
    lam, a, vp_star, n = metrics.calibration([vp], [r])
    assert (lam, a, n) == (pytest.approx(2.0), pytest.approx(-4.0), 5)
    assert vp_star == pytest.approx(math.exp(2.0))


def test_calibration_pools_dates_and_centres_each_date_separately():
    x = np.arange(5.0)
    vp = np.exp(x)
    r1 = np.exp(2 * x + 1) - 1
    r2 = np.exp(2 * x + 3) - 1                      # the same cross-section 2 higher in log return: the date median absorbs it
    lam, a, vp_star, n = metrics.calibration([vp, vp], [r1, r2])
    assert n == 10 and lam == pytest.approx(2.0) and a == pytest.approx(-4.0)


# ---- the period statistics and the criteria --------------------------------------------------------------------------------

def make_tables(rho_s_better=True, n=60, dates=3, seed=1):
    rng = np.random.default_rng(seed)
    tabs = []
    for _ in range(dates):
        r = rng.normal(0.3, 0.4, n)
        good = np.exp(r + rng.normal(0, 0.1, n))
        noise = np.exp(rng.normal(0, 0.5, n))
        tabs.append({"vp_S": good if rho_s_better else noise, "vp_B": noise if rho_s_better else good, "r": r, "r_spy": 0.2})
    return tabs


def test_period_stats_orders_the_arms_when_one_ranks_better():
    per, agg = metrics.period_stats(make_tables(True))
    assert len(per) == 3 and all(p["rho_S"] > p["rho_B"] for p in per)
    assert agg["dRho_mean"] == pytest.approx(np.mean([p["rho_S"] - p["rho_B"] for p in per]))
    assert agg["lift_diff"] == pytest.approx(agg["lift_mean_S"] - agg["lift_mean_B"])


def test_cluster_bootstrap_is_seeded_and_reproducible_and_the_interval_brackets_the_point_estimate():
    tabs = make_tables(True, n=80)
    comps = [np.arange(80) for _ in tabs]                         # the same 80 companies at every date
    a = metrics.cluster_bootstrap(tabs, comps, n_resamples=200)
    b = metrics.cluster_bootstrap(tabs, comps, n_resamples=200)
    assert a == b                                                  # default_rng(20261001): the same draws every time
    _per, agg = metrics.period_stats(tabs)
    lo, hi, _ = a["dRho_mean"]
    assert lo <= agg["dRho_mean"] <= hi and lo < hi


def test_cluster_bootstrap_draws_companies_and_keeps_all_their_rows(monkeypatch):
    # three companies; company 0 has rows at both dates.  Capture what each resample hands to period_stats.
    tabs = [{"vp_B": np.array([1.0, 2.0, 3.0]), "vp_S": np.array([1.0, 2.0, 3.0]), "r": np.array([10.0, 20.0, 30.0]), "r_spy": 0.0},
            {"vp_B": np.array([1.0, 2.0]), "vp_S": np.array([1.0, 2.0]), "r": np.array([10.0, 30.0]), "r_spy": 0.0}]
    comps = [np.array([0, 1, 2]), np.array([0, 2])]
    seen = []
    real = metrics.period_stats

    def spy(sub):
        seen.append([list(t["r"]) for t in sub])
        return real(sub)

    monkeypatch.setattr(metrics, "period_stats", spy)
    metrics.cluster_bootstrap(tabs, comps, n_resamples=3, stats=("dRho_mean",))
    counts = np.bincount(np.random.default_rng(20261001).integers(0, 3, size=3), minlength=3)     # the first resample's draw
    first = seen[0]
    for company, r in ((0, 10.0), (1, 20.0), (2, 30.0)):
        assert first[0].count(r) == counts[company]                 # multiplicity at the first date
    assert first[1].count(10.0) == counts[0] and first[1].count(30.0) == counts[2]      # the same multiplicity at the second date
    assert 20.0 not in first[1]                                      # company 1 has no row at the second date


def test_f3_uses_only_the_dates_where_both_arms_have_a_call():
    # date 1: both have calls (S 10, B 20); date 2: only S has calls (S 50); date 3: neither
    def table(vp_s, vp_b):
        n = len(vp_s)
        return {"vp_S": np.array(vp_s, dtype=float), "vp_B": np.array(vp_b, dtype=float), "r": np.linspace(-0.2, 0.6, n), "r_spy": 0.2}
    # arm calls (V/P >= 1.3) on the top three returns for date 1 -> all beat 20%? hand-build instead via two-call sets
    t1 = table([1.5, 1.5, 1.5, 1.5, 1.5, 0.5, 0.5, 0.5, 0.5, 0.5], [1.5, 1.5, 1.5, 1.5, 1.5, 0.5, 0.5, 0.5, 0.5, 0.5])
    t2 = table([1.5, 1.5, 1.5, 1.5, 1.5, 0.5, 0.5, 0.5, 0.5, 0.5], [1.0] * 10)               # arm B makes no buy call
    t3 = table([1.0] * 10, [1.0] * 10)
    per, agg = metrics.period_stats([t1, t2, t3])
    assert agg["common_lift_dates"] == 1
    assert agg["lift_mean_S"] == pytest.approx((per[0]["lift_S"] + per[1]["lift_S"]) / 2)         # S's own-date average: two dates
    assert agg["lift_mean_B"] == pytest.approx(per[0]["lift_B"])                                  # B's own-date average: one date
    assert agg["lift_mean_S_common"] == pytest.approx(per[0]["lift_S"]) and agg["lift_mean_B_common"] == pytest.approx(per[0]["lift_B"])
    assert agg["lift_diff"] == pytest.approx(per[0]["lift_S"] - per[0]["lift_B"])
    assert agg["dates_without_calls_B"] == 2 and agg["dates_without_calls_S"] == 1


def test_f3_bootstrap_statistics_use_the_common_dates_too():
    rng = np.random.default_rng(3)
    def table(call_b):
        n = 40
        r = rng.normal(0.2, 0.3, n)
        vp_s = np.exp(r + rng.normal(0, 0.2, n)) * 1.2
        vp_b = np.exp(r + rng.normal(0, 0.2, n)) * 1.2 if call_b else np.full(n, 1.0)
        return {"vp_S": vp_s, "vp_B": vp_b, "r": r, "r_spy": 0.1}
    tabs = [table(True), table(False)]
    comps = [np.arange(40), np.arange(40)]
    out = metrics.cluster_bootstrap(tabs, comps, n_resamples=50)
    assert {"lift_mean_S_common", "lift_mean_B_common", "lift_diff"} <= set(out)
    lo, hi, n_nan = out["lift_diff"]
    assert lo == lo and hi == hi and n_nan == 0                     # defined in every resample: it rests on the one common date


def test_f0_is_the_intersection_over_the_names_revision_16_values():
    ok = metrics.freeze_criteria({"APV_S": 1.0, "lift_mean_S_common": 5.0, "lift_mean_B_common": 5.0},
                                 [{"dRho": 0.0}] * 5, {"dRho_mean": (0.0, 0.1, 0)}, {"dRho_mean": 0.0}, [(95, 100)] * 5)
    assert ok["F0"]
    bad = metrics.freeze_criteria({"APV_S": 1.0, "lift_mean_S_common": 5.0, "lift_mean_B_common": 5.0},
                                  [{"dRho": 0.0}] * 5, {"dRho_mean": (0.0, 0.1, 0)}, {"dRho_mean": 0.0}, [(95, 100)] * 4 + [(94, 100)])
    assert not bad["F0"] and not bad["adopted"]


def test_freeze_criteria_mechanics():
    per = [{"dRho": 0.0}, {"dRho": 0.01}, {"dRho": -0.04}, {"dRho": 0.02}, {"dRho": -0.01}]
    agg = {"APV_S": 1.0, "lift_mean_S": 4.0, "lift_mean_B": 6.0, "lift_mean_S_common": 4.0, "lift_mean_B_common": 6.0}
    ci = {"dRho_mean": (-0.015, 0.02, 0)}
    ok = metrics.freeze_criteria(agg, per, ci, {"dRho_mean": -0.01}, [(96, 100)] * 5)
    assert ok["F0"] and ok["F1"] and ok["F1c"] and ok["F2"] and ok["F3"] and ok["adopted"] and ok["F1_dates_ok"] == 4
    assert not metrics.freeze_criteria(agg, per, ci, {"dRho_mean": -0.021}, [(96, 100)] * 5)["F1c"]
    assert not metrics.freeze_criteria(agg, per, ci, {"dRho_mean": -0.01}, [(94, 100)] * 5)["F0"]        # below 95%
    assert not metrics.freeze_criteria(dict(agg, APV_S=0.86), per, ci, {"dRho_mean": 0.0}, [(96, 100)] * 5)["F2"]
    assert not metrics.freeze_criteria(dict(agg, APV_S=1.151), per, ci, {"dRho_mean": 0.0}, [(96, 100)] * 5)["F2"]
    assert not metrics.freeze_criteria(dict(agg, lift_mean_S_common=2.9), per, ci, {"dRho_mean": 0.0}, [(96, 100)] * 5)["F3"]
    two_bad = [{"dRho": -0.04}, {"dRho": -0.031}, {"dRho": 0.0}, {"dRho": 0.0}, {"dRho": 0.0}]
    assert not metrics.freeze_criteria(agg, two_bad, ci, {"dRho_mean": 0.0}, [(96, 100)] * 5)["F1"]
    assert not metrics.freeze_criteria(agg, per, {"dRho_mean": (-0.0201, 0.1, 0)}, {"dRho_mean": 0.0}, [(96, 100)] * 5)["F1"]
    assert metrics.fitness(0.03, 0.001, 5.0) and not metrics.fitness(0.029, 0.01, 6.0) and not metrics.fitness(0.05, 0.0, 6.0)


# ---- the look gate ---------------------------------------------------------------------------------------------------------------

def test_look_refuses_without_the_authorisation_file(tmp_path):
    for n in (1, 2):
        with pytest.raises(PermissionError):
            require_look(n, tmp_path)
    with pytest.raises(ValueError):
        require_look(3, tmp_path)
    (tmp_path / "AUTHORISED_LOOK_1.txt").write_text("authorised by the reviewer", encoding="utf-8")
    assert require_look(1, tmp_path) == gate_path(tmp_path, 1)
    with pytest.raises(PermissionError):
        require_look(2, tmp_path)                                    # one file authorises one look only


def test_run_look_stops_at_the_gate_before_reading_any_price_or_table(tmp_path):
    # an empty bt-root: if the gate did not come first this would fail with FileNotFoundError on the price file instead
    for n in ("1", "2"):
        with pytest.raises(PermissionError):
            run_look.main(["--look", n, "--bt-root", str(tmp_path)])


# ---- a Look on a synthetic price book -------------------------------------------------------------------------------------------

def synthetic_book(n_names=40, years=("2016", "2017")):
    """A made-up price book: monthly Close/Adj Close, SPY and n_names tickers.  Returns (PriceBook, tables)."""
    rng = np.random.default_rng(7)
    months = [f"{y}-{m:02d}" for y in range(2015, 2030) for m in range(1, 13)]
    prices = {}

    def series(drift):
        px, out = 100.0, {}
        for mo in months:
            px *= 1.0 + drift
            out[mo] = [px, px, 0.0, 0.0]
        return out

    prices["SPY"] = series(0.006)
    tables = {}
    for y in years:
        rows = []
        for i in range(n_names):
            t = f"S{y}{i}"
            drift = 0.002 + 0.0005 * i
            prices[t] = series(drift)
            vp_good = 0.6 + 0.04 * i                               # V/P rises with the future drift: perfect ranking for arm S
            vp_bad = 0.6 + 0.04 * ((i * 17) % n_names)             # a scrambled ranking for arm B
            price = 20.0 + i
            rows.append({"cik": f"{i:010d}", "ticker": t, "price": price, "cap": 1e9 * (1 + i), "sector": "Industrials" if i % 2 else "Energy",
                         "in_U": True, "rev_years": 8 if i % 4 else 3, "V_B": vp_bad * price, "V_S": vp_good * price, "V_a": vp_bad * price, "V_b": vp_good * price,
                         "oe_yield": 0.01 * (i + 1)})
        tables[y] = rows
    return PriceBook({"meta": {}, "prices": prices, "empty_tickers": []}), tables


def test_compute_look_on_synthetic_data_ranks_the_better_arm_higher():
    book, tables = synthetic_book()
    res = run_look.compute_look(("2016", "2017"), tables, book)
    h36 = res["horizons"]["36"]
    assert h36["dates"] == ["2016", "2017"]
    assert h36["n_P"] == [40, 40] and h36["n_missing_h"] == [0, 0]
    assert h36["agg"]["rho_mean_S"] == pytest.approx(1.0)               # V/P rises with return by construction
    assert h36["agg"]["rho_mean_B"] < 0.5
    assert h36["agg"]["dRho_mean"] > 0.5
    lo, hi, _ = h36["bootstrap_90"]["dRho_mean"]
    assert lo > 0.0 and hi >= lo
    assert h36["report_only_rho"]["naive"]["rho_mean"] == pytest.approx(1.0)
    assert "12" in res["horizons"] and "60" in res["horizons"]
    assert set(h36["by_sector"]) == {"Industrials", "Energy"}
    assert set(h36["by_size_tercile"]) == {"0", "1", "2"}
    assert len(h36["quintile_excess"]["S"]) == 2 and h36["calibration"]["S"]["lambda"] > 0
    json_ready = run_look._clean(res)
    import json
    json.dumps(json_ready)


def test_total_return_is_month_end_adj_close_to_adj_close():
    book = PriceBook({"meta": {}, "prices": {"X": {"2016-06": [10.0, 8.0, 0.0, 0.0], "2019-06": [12.0, 12.0, 0.0, 0.0]}}, "empty_tickers": []})
    assert run_look.total_return(book, "X", "2016", 36) == pytest.approx(12.0 / 8.0 - 1.0)       # the adjusted series, not the Close
    assert run_look.total_return(book, "X", "2016", 12) is None


def test_a_look_stops_when_a_date_has_no_pre_outcome_table_unless_the_omission_is_allowed(tmp_path):
    import pickle
    pre = tmp_path / "out" / "prelook"
    pre.mkdir(parents=True)
    (pre / "table_2017.pkl").write_bytes(pickle.dumps([]))
    with pytest.raises(FileNotFoundError):
        run_look.load_tables(tmp_path, ("2016", "2017"))
    tables, missing = run_look.load_tables(tmp_path, ("2016", "2017"), skip_missing=True)
    assert list(tables) == ["2017"] and missing == ["2016"]


def test_record_depth_slice_splits_the_36_month_correlations_at_five_revenue_years():
    book, tables = synthetic_book(n_names=40)
    res = run_look.compute_look(("2016", "2017"), tables, book)
    depth = res["horizons"]["36"]["by_record_depth"]
    assert set(depth) == {"5_or_more_revenue_years", "fewer_than_5_revenue_years"}
    deep = depth["5_or_more_revenue_years"][0]
    thin = depth["fewer_than_5_revenue_years"][0]
    assert deep["n"] == 30 and thin["n"] == 10                          # i % 4 == 0 gets 3 years: ten of forty
    assert deep["n"] + thin["n"] == 40
    assert deep["rho_S"] == pytest.approx(1.0) and thin["rho_S"] == pytest.approx(1.0)       # arm S ranks perfectly inside each slice
    assert deep["dRho"] == pytest.approx(deep["rho_S"] - deep["rho_B"])


def test_twelve_month_horizon_covers_2017_onwards_only():
    book, tables = synthetic_book(years=("2016", "2017"))
    res = run_look.compute_look(("2016", "2017"), tables, book)
    assert res["horizons"]["12"]["dates"] == ["2017"]                   # amendment A3
    assert res["horizons"]["36"]["dates"] == ["2016", "2017"]
