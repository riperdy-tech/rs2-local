"""Backtest registration sections 7 and 8: the metrics and the intervals.  PURE functions of arrays: no file, no price, no
look gate here (the gate is in look_gate.py and run_look.py, the only place a return is ever built).  Tested on synthetic
data only.

Conventions (the registration's, and the literal reading where it is silent - see the report's questions):
  * V/P is a name's per-share value over P(T), the unadjusted price on T.
  * Spearman: ties averaged; undefined (nan) below 3 observations or when either variable is constant.
  * The 40th and 60th percentiles of R are numpy's linear-interpolation percentiles; "between" is inclusive.
  * Buy call: V/P >= 1.3, "beat SPY" is R > R_SPY; avoid call: V/P <= 0.7, "underperform" is R < R_SPY.
  * Lift is in percentage points.  A date with fewer than 30 calls is flagged thin and still counts; a date with no calls has
    an undefined lift and is left out of the average, counted.
"""
import math

import numpy as np

BUY, AVOID = 1.3, 0.7
THIN = 30


def rankdata_avg(x):
    """Ranks 1..n, ties given the average of the ranks they span."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    xs = x[order]
    i = 0
    n = len(x)
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x) < 3:
        return float("nan")
    rx, ry = rankdata_avg(x), rankdata_avg(y)
    sx, sy = rx.std(), ry.std()
    if sx == 0.0 or sy == 0.0:
        return float("nan")
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def apv_median(vp, r, lo=40.0, hi=60.0):
    """The median V/P among the names whose R lies between the lo-th and hi-th percentile of R (inclusive).  nan when none."""
    vp, r = np.asarray(vp, dtype=float), np.asarray(r, dtype=float)
    if len(r) == 0:
        return float("nan")
    p_lo, p_hi = np.percentile(r, [lo, hi])
    sel = (r >= p_lo) & (r <= p_hi)
    return float(np.median(vp[sel])) if sel.any() else float("nan")


def apv(medians):
    """APV = exp(mean over dates of ln(median)); dates with an undefined or non-positive median are left out (counted by the caller)."""
    m = [x for x in medians if x == x and x > 0]
    return float(math.exp(sum(math.log(x) for x in m) / len(m))) if m else float("nan")


def call_lift(vp, r, r_spy, buy=True):
    """(lift in points, number of calls).  buy: V/P >= 1.3 and the share that beat SPY, less the share of all names that beat it;
    avoid: V/P <= 0.7 and the share that underperformed SPY, less the share of all names that did.  nan when there are no calls."""
    vp, r = np.asarray(vp, dtype=float), np.asarray(r, dtype=float)
    hit = (r > r_spy) if buy else (r < r_spy)
    calls = (vp >= BUY) if buy else (vp <= AVOID)
    n = int(calls.sum())
    if n == 0 or len(r) == 0:
        return float("nan"), n
    return float((hit[calls].mean() - hit.mean()) * 100.0), n


def quintile_excess(vp, r):
    """Mean R in each V/P quintile (ranks cut into five near-equal groups, lowest V/P first), less the mean R of all names."""
    vp, r = np.asarray(vp, dtype=float), np.asarray(r, dtype=float)
    n = len(vp)
    if n < 5:
        return [float("nan")] * 5
    order = np.argsort(vp, kind="mergesort")
    grp = np.empty(n, dtype=int)
    grp[order] = (np.arange(n) * 5) // n
    mean_all = r.mean()
    return [float(r[grp == g].mean() - mean_all) for g in range(5)]


def calibration(vp_by_date, r_by_date):
    """Pooled OLS of [ln(1+R) - median over that date's names of ln(1+R)] on ln(V/P).  (lambda, a, V/P* = exp(-a/lambda), n)."""
    xs, ys = [], []
    for vp, r in zip(vp_by_date, r_by_date):
        vp, r = np.asarray(vp, dtype=float), np.asarray(r, dtype=float)
        ok = (vp > 0) & (r > -1)
        if not ok.any():
            continue
        lr = np.log1p(r[ok])
        ys.append(lr - np.median(lr))
        xs.append(np.log(vp[ok]))
    if not xs:
        return float("nan"), float("nan"), float("nan"), 0
    x, y = np.concatenate(xs), np.concatenate(ys)
    if len(x) < 3 or x.std() == 0.0:
        return float("nan"), float("nan"), float("nan"), len(x)
    lam, a = np.polyfit(x, y, 1)
    return float(lam), float(a), float(math.exp(-a / lam)) if lam != 0 else float("nan"), len(x)


# ---- the period statistics ------------------------------------------------------------------------------------------

def date_stats(t):
    """The decisive statistics of one date's table `t`, a dict of equal-length arrays on P(T): vp_B, vp_S, r (R(T,36)), r_spy (scalar)."""
    r = np.asarray(t["r"], dtype=float)
    out = {"n": int(len(r))}
    for arm in ("B", "S"):
        vp = np.asarray(t["vp_" + arm], dtype=float)
        out["rho_" + arm] = spearman(vp, r)
        out["apv_med_" + arm] = apv_median(vp, r)
        lift, ncalls = call_lift(vp, r, t["r_spy"], buy=True)
        out["lift_" + arm], out["calls_" + arm] = lift, ncalls
        out["thin_" + arm] = ncalls < THIN
    out["dRho"] = out["rho_S"] - out["rho_B"]
    return out


def period_stats(tables):
    """Per-date statistics and the period's aggregates over `tables` (a list of per-date tables)."""
    per = [date_stats(t) for t in tables]
    agg = {"dRho_mean": float(np.nanmean([p["dRho"] for p in per])) if per else float("nan")}
    for arm in ("B", "S"):
        agg["rho_mean_" + arm] = float(np.nanmean([p["rho_" + arm] for p in per])) if per else float("nan")
        agg["APV_" + arm] = apv([p["apv_med_" + arm] for p in per])
        lifts = [p["lift_" + arm] for p in per if p["lift_" + arm] == p["lift_" + arm]]
        agg["lift_mean_" + arm] = float(np.mean(lifts)) if lifts else float("nan")
        agg["dates_without_calls_" + arm] = int(sum(1 for p in per if p["lift_" + arm] != p["lift_" + arm]))
        agg["thin_dates_" + arm] = int(sum(1 for p in per if p["thin_" + arm]))
    # C-3: F3 compares the arms on the dates where BOTH have at least one call (point estimate and bootstrap alike); each arm's own-date
    # average stays as reported above.
    common = [p for p in per if p["lift_S"] == p["lift_S"] and p["lift_B"] == p["lift_B"]]
    agg["common_lift_dates"] = len(common)
    agg["lift_mean_S_common"] = float(np.mean([p["lift_S"] for p in common])) if common else float("nan")
    agg["lift_mean_B_common"] = float(np.mean([p["lift_B"] for p in common])) if common else float("nan")
    agg["lift_diff"] = agg["lift_mean_S_common"] - agg["lift_mean_B_common"]
    return per, agg


# ---- section 8: the company-cluster bootstrap -----------------------------------------------------------------------

def cluster_bootstrap(tables, companies, n_resamples=2000, seed=20261001, stats=("dRho_mean", "rho_mean_S", "rho_mean_B",
                                                                                 "APV_S", "APV_B", "lift_mean_S", "lift_mean_B", "lift_mean_S_common",
                                                                                 "lift_mean_B_common", "lift_diff")):
    """Draw companies with replacement from the union of the period's companies (as many as there are), keep every row a drawn
    company has, with its multiplicity, at every date.  `companies` is a list (one per date) of arrays of company ids aligned
    with that date's table rows.  2,000 resamples with numpy default_rng(20261001); the 90% interval runs from the 5th to the
    95th percentile.  Returns {stat: (low, high, nan_resamples)}."""
    universe = sorted({c for cs in companies for c in cs})
    idx = {c: i for i, c in enumerate(universe)}
    K = len(universe)
    rows_of = [np.array([idx[c] for c in cs], dtype=int) for cs in companies]
    rng = np.random.default_rng(seed)
    draws = {s: [] for s in stats}
    for _ in range(n_resamples):
        counts = np.bincount(rng.integers(0, K, size=K), minlength=K)
        sub = []
        for t, rows in zip(tables, rows_of):
            take = np.repeat(np.arange(len(rows)), counts[rows])
            sub.append({k: (np.asarray(v)[take] if isinstance(v, (list, np.ndarray)) else v) for k, v in t.items()})
        _per, agg = period_stats(sub)
        for s in stats:
            draws[s].append(agg[s])
    out = {}
    for s, v in draws.items():
        a = np.array(v, dtype=float)
        ok = a[~np.isnan(a)]
        out[s] = (float(np.percentile(ok, 5)), float(np.percentile(ok, 95)), int(len(a) - len(ok))) if len(ok) else (float("nan"), float("nan"), len(a))
    return out


# ---- section 10: the freeze criteria, mechanically (the decision and its words are the reviewer's) -------------------

def freeze_criteria(val_agg, val_per, val_ci, design_agg, coverage_by_date):
    """The registered tests, as booleans with the numbers they rest on.
    val_agg / val_per: `period_stats` of the five validation dates; val_ci: `cluster_bootstrap` of them; design_agg: `period_stats`
    aggregates of the design dates; coverage_by_date: [(n_valued_by_both, n_valued_by_revision_16)] per validation date: F0 is the
    intersection (names both arms value) over the names revision 16 values."""
    f0 = all(s >= 0.95 * b for s, b in coverage_by_date)
    n_ok = sum(1 for p in val_per if p["dRho"] >= -0.03)
    ci_low = val_ci["dRho_mean"][0]
    f1 = (ci_low >= -0.02) and (n_ok >= 4)
    f1c = design_agg["dRho_mean"] >= -0.02
    f2 = 0.87 <= val_agg["APV_S"] <= 1.15
    f3 = val_agg["lift_mean_S_common"] >= val_agg["lift_mean_B_common"] - 3.0       # the dates where both arms have a call
    return {"F0": f0, "F1": f1, "F1_ci_low": ci_low, "F1_dates_ok": n_ok, "F1c": f1c, "F2": f2, "F3": f3,
            "adopted": bool(f0 and f1 and f1c and f2 and f3)}


def fitness(rho_mean, rho_ci_low, lift_mean):
    """The fitness rule of the frozen arm: mean rho >= 0.03 with a 90% interval above 0, and buy-call lift >= +5 points."""
    return bool(rho_mean >= 0.03 and rho_ci_low > 0.0 and lift_mean >= 5.0)
