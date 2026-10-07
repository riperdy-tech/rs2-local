"""Registration v2 (REGISTRATION_gate1_v2_DRAFT.md, Addendum J 5-9): the bars B1-B5 on MONTH-END dates, from the compact rows `gate1_metrics.load_run` reads.  Pure functions of
rows (tested on synthetic panels in rebuild_harness/tests/test_gate1_v2.py); nothing here reads a price, a filing or the network.

EVERY FIGURE COMPUTED ON THE DEVELOPMENT RUN IS PROVISIONAL (raw month-end prices of today's listings, survivors only; Addendum H9) and counts toward no gate.

B1, incremental information (HARD).  Pooled OLS over every (date, name) pair of the 12-month excess return on the percentile rank of IV / price (rank among the names of the date that
  have an outcome) and the ranks of earnings yield, FCF yield, gross profitability, return on capital and 12-1 momentum (a missing yardstick enters at the median rank 0.5 with an
  indicator column: Addendum H7), with INDUSTRY and DATE fixed effects (absorbed by alternating projections).  The engine's coefficient has a one-sided 90% lower bound from a WILD
  CLUSTER BOOTSTRAP-t clustered by date: Rademacher weights per date, the null imposed (restricted residuals, Cameron-Gelbach-Miller / Roodman et al.), `N_BOOT` draws, the lower end
  being  b - q90(t*) x se  with se the date-clustered (CR1) standard error and q90 the 90th percentile of the null-imposed bootstrap t.  PASS when the lower bound is > 0.
  Reported: the share of positive per-date (monthly) cross-sectional coefficients, the Fama-MacBeth mean and its date bootstrap, the p-value of the wild bootstrap.
B2, economic usefulness (HARD).  The industry-neutral top-minus-bottom quintile spread of the engine's RESIDUAL after the yardsticks (per date, then the mean over dates) is > 0: PASS;
  >= +3 pp: STRONG PASS.  The raw (not residualised) spread is reported.
B3, level (HARD).  The median IV / price of the universe (every valued name on the return dates) lies in [0.67, 1.5].  Diagnostics (not bars): the share below 0.4x or above 2.5x, the
  family concentration of the extremes, the family medians, the IQR of ln(IV / price), the median by date.
B4, forecasts (HARD).  Per family, the median absolute error of the engine's P50 for the next fiscal year against the first-filed outcome is at most the naive baseline's: revenue growth
  (naive: the trailing 3-year CAGR) and operating margin (naive: held at the base year) for the operating and commodity families; return on tangible equity (naive: held at the base
  year; the engine's forecast is ROTE'_1, the return that enters the year's residual income) for the financial family.  Reported: the share of outcomes inside the engine's P10..P90
  (target 80%), and the directional accuracy (the sign of the forecast change from the base value against the sign of the outcome's).
B5, stability (HARD on direction).  B1 and B2 keep their sign (coefficient > 0; residual spread > 0) under each survivorship bound and with the 1% of observations with the largest
  |residual| of the B1 regression removed.  Reported variants: the price-basis variant (adjusted-only proxy), the equity premium +-1 pp, sector-neutral, size-neutral.
The three bounds (Addendum D) are `metrics.BOUNDS`: PASS needs every hard bar to pass under all three; FAIL when a hard bar fails under all three; otherwise NOT DECIDED.
"""
import math

import numpy as np

from . import gate1_metrics as gm
from . import metrics as hm

N_BOOT = 999
BOOT_SEED = 20261007
LEVEL_LOW, LEVEL_HIGH = 0.67, 1.5       # B3 level band
B2_STRONG = 0.03
ONE_SIDED = 0.90
TRIM = 0.01                              # B5: the share of observations with the largest |residual| removed
MIN_PANEL = 200                          # a pooled regression needs this many observations
SIZE_BUCKETS = 5
ENGINE = gm.ENGINE
YARDSTICKS = gm.YARDSTICKS


# ---- the panel and the absorbed fixed effects -------------------------------------------------------------------------------------------------

def _codes(labels):
    u = {}
    return np.array([u.setdefault(x, len(u)) for x in labels], dtype=np.int64)


def build_panel(rows, bound, score_fn=None, yardsticks=YARDSTICKS, h=gm.HORIZON, min_names=gm.MIN_NAMES):
    """The pooled design of B1 from `rows` (the compact rows of the dates in scope): {"y", "X" (the engine's rank, the yardstick ranks, one indicator column per yardstick that is
    missing for at least one name), "date", "industry", "sector", "size" (integer codes), "keep" (the rows used, in order), "cols"}.  Ranks are percentile ranks among the date's usable
    names (an engine score and an outcome under the bound); a yardstick missing for a name is the median rank 0.5 with an indicator (Addendum H7).  `score_fn(row)` is the engine's
    score (default IV / price); a row it maps to None is not usable.  A date with fewer than `min_names` usable names is left out."""
    score_fn = score_fn or (lambda r: r["score"].get(ENGINE))
    by_d = gm.by_date(rows)
    ys, Xs, dts, inds, secs, sizes, keep = [], [], [], [], [], [], []
    for d, rs in by_d.items():
        pairs = []
        for r in rs:
            s = score_fn(r)
            e = None if s is None else gm.excess_under(r, bound, h)
            if s is not None and e is not None:
                pairs.append((r, s, e))
        if len(pairs) < min_names:
            continue
        eng = hm.pct_rank(np.array([p[1] for p in pairs], dtype=float))
        ycols, miss_cols = [], []
        for y in yardsticks:
            v = np.array([np.nan if p[0]["score"].get(y) is None else p[0]["score"][y] for p in pairs], dtype=float)
            miss = np.isnan(v)
            rank = np.full(len(v), 0.5)
            if (~miss).any():
                rank[~miss] = hm.pct_rank(v[~miss])
            ycols.append(rank)
            miss_cols.append(miss.astype(float))
        mc = np.array([(p[0].get("market_cap") if p[0].get("market_cap") is not None else np.nan) for p in pairs], dtype=float)
        if np.isnan(mc).all():
            size = np.zeros(len(pairs), dtype=int)
        else:
            size = np.minimum((hm.pct_rank(np.where(np.isnan(mc), np.nanmedian(mc), mc)) * SIZE_BUCKETS).astype(int), SIZE_BUCKETS - 1)
        for i, (r, s, e) in enumerate(pairs):
            ys.append(e)
            Xs.append([eng[i]] + [c[i] for c in ycols] + [c[i] for c in miss_cols])
            dts.append(d)
            inds.append(r.get("industry") or "unknown")
            secs.append(r.get("sector") or r.get("industry") or "unknown")
            sizes.append(f"{d}|{int(size[i])}")
            keep.append(r)
    if not ys:
        return None
    X = np.array(Xs, dtype=float)
    # an indicator column that is zero everywhere carries no information (and makes the design singular): dropped, named
    nz = [0] + list(range(1, 1 + len(yardsticks))) + [1 + len(yardsticks) + j for j in range(len(yardsticks)) if X[:, 1 + len(yardsticks) + j].any()]
    cols = (["engine"] + list(yardsticks) + [f"missing:{y}" for y in yardsticks])
    return {"y": np.array(ys, dtype=float), "X": X[:, nz], "date": _codes(dts), "industry": _codes(inds), "sector": _codes(secs), "size": _codes(sizes), "dates": dts,
            "keep": keep, "n_dates": len(set(dts)), "cols": [cols[i] for i in nz]}


def demean(v, factors, tol=1e-10, max_iter=200):
    """The residual of `v` (n,) or (n, k) after absorbing the fixed effects of each factor in `factors` (a list of integer code arrays): alternating projections (exact for one
    factor; converges for several)."""
    out = np.array(v, dtype=float, copy=True)
    if out.ndim == 1:
        out = out[:, None]
        squeeze = True
    else:
        squeeze = False
    facs = [(f, np.bincount(f)) for f in factors]
    for _ in range(max_iter):
        prev = out.copy()
        for f, cnt in facs:
            for j in range(out.shape[1]):
                s = np.bincount(f, weights=out[:, j], minlength=len(cnt))
                out[:, j] -= (s / np.maximum(cnt, 1))[f]
        if np.max(np.abs(out - prev)) < tol:
            break
    return out[:, 0] if squeeze else out


def cluster_se(Xt, u, g, j=0):
    """CR1 date-clustered standard error of coefficient j of the OLS of u's regression on Xt: (X'X)^-1 (sum_g X_g' u_g u_g' X_g) (X'X)^-1 x G/(G-1) x (N-1)/(N-K)."""
    n, k = Xt.shape
    G = int(g.max()) + 1
    XtX_inv = np.linalg.inv(Xt.T @ Xt)
    S = np.zeros((G, k))
    np.add.at(S, g, Xt * u[:, None])
    meat = S.T @ S
    V = XtX_inv @ meat @ XtX_inv * (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    return float(math.sqrt(max(V[j, j], 0.0)))


def fe_ols(y, X, factors):
    """(beta, residuals, Xt, yt): the OLS of y on X with the fixed effects of `factors` absorbed."""
    Z = demean(np.column_stack([y, X]), factors)
    yt, Xt = Z[:, 0], Z[:, 1:]
    beta, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
    return beta, yt - Xt @ beta, Xt, yt


def wild_cluster_bootstrap(y, X, factors, cluster, n_boot=N_BOOT, seed=BOOT_SEED, j=0):
    """The wild cluster bootstrap-t of coefficient j (null imposed): {"beta", "se", "lower_90_one_sided", "p_one_sided" (H0: beta <= 0), "n_boot", "t_boot_q90"}.  Rademacher weights
    per cluster applied to the restricted residuals of the model without column j; each draw re-absorbs the fixed effects."""
    beta, u, Xt, yt = fe_ols(y, X, factors)
    se = cluster_se(Xt, u, cluster, j)
    t_hat = beta[j] / se if se > 0 else float("nan")
    keep = [c for c in range(X.shape[1]) if c != j]
    if keep:
        bR, *_ = np.linalg.lstsq(Xt[:, keep], yt, rcond=None)
        fitted = Xt[:, keep] @ bR
        uR = yt - fitted
    else:
        fitted, uR = np.zeros_like(yt), yt
    G = int(cluster.max()) + 1
    rng = np.random.default_rng(seed)
    XtX_inv_Xt = np.linalg.solve(Xt.T @ Xt, Xt.T)
    ts = np.empty(n_boot)
    for b in range(n_boot):
        w = rng.choice(np.array([-1.0, 1.0]), size=G)[cluster]
        ystar = fitted + demean(w * uR, factors)
        bs = XtX_inv_Xt @ ystar
        us = ystar - Xt @ bs
        se_b = cluster_se(Xt, us, cluster, j)
        ts[b] = bs[j] / se_b if se_b > 0 else 0.0
    q90 = float(np.quantile(ts, ONE_SIDED))
    p = float((1 + np.sum(ts >= t_hat)) / (n_boot + 1)) if t_hat == t_hat else float("nan")
    return {"beta": float(beta[j]), "se": se, "t": float(t_hat), "lower_90_one_sided": float(beta[j] - q90 * se), "p_one_sided": p, "n_boot": n_boot, "t_boot_q90": q90,
            "residuals": u, "n": int(len(y)), "n_clusters": G}


# ---- B1 ---------------------------------------------------------------------------------------------------------------------------------------

def _factors(panel, kind="industry"):
    if kind == "industry":
        return [panel["date"], panel["industry"]]
    if kind == "sector":
        return [panel["date"], panel["sector"]]
    if kind == "size":
        return [panel["date"], panel["industry"], panel["size"]]
    if kind == "sector_size":
        return [panel["date"], panel["sector"], panel["size"]]
    raise ValueError(kind)


def b1_pooled(rows, bound, score_fn=None, effects="industry", n_boot=N_BOOT, yardsticks=YARDSTICKS):
    """Registration v2 B1 on the pooled panel.  `effects`: "industry" (the bar: industry and date effects), "sector" (sector and date), "size" (industry, date, and date x size bucket) for
    the reported variants."""
    pn = build_panel(rows, bound, score_fn, yardsticks)
    if pn is None or len(pn["y"]) < MIN_PANEL or pn["n_dates"] < 3:
        return {"status": "not computed", "n": 0 if pn is None else len(pn["y"])}
    wb = wild_cluster_bootstrap(pn["y"], pn["X"], _factors(pn, effects), pn["date"], n_boot)
    per = b1_per_date(rows, bound, score_fn, yardsticks)
    cs = [v["coef"] for v in per.values() if v["coef"] == v["coef"]]
    out = {k: wb[k] for k in ("beta", "se", "t", "lower_90_one_sided", "p_one_sided", "n_boot", "n", "n_clusters")}
    miss = {y: (float(pn["X"][:, pn["cols"].index(f"missing:{y}")].mean()) if f"missing:{y}" in pn["cols"] else 0.0) for y in yardsticks}
    out.update({"status": "pass" if wb["lower_90_one_sided"] > 0 else "fail", "effects": effects, "columns": pn["cols"], "yardstick_missing_share": miss,
                "share_positive_monthly_coefficients": (float(np.mean([c > 0 for c in cs])) if cs else None), "n_months": len(cs),
                "mean_monthly_coefficient": float(np.mean(cs)) if cs else None})
    out["_residuals"], out["_keep"] = wb["residuals"], pn["keep"]
    return out


def b1_per_date(rows, bound, score_fn=None, yardsticks=YARDSTICKS):
    """{date: {"n", "coef"}}: the engine's coefficient of each date's industry-demeaned cross-sectional OLS (the monthly coefficients)."""
    out = {}
    for d, rs in gm.by_date(rows).items():
        pairs = []
        for r in rs:
            s = (score_fn or (lambda r_: r_["score"].get(ENGINE)))(r)
            e = None if s is None else gm.excess_under(r, bound)
            if s is not None and e is not None:
                pairs.append((r, s, e))
        if len(pairs) < gm.MIN_NAMES:
            out[d] = {"n": len(pairs), "coef": float("nan")}
            continue
        ex = np.array([p[2] for p in pairs], dtype=float)
        inds = [p[0].get("industry") or "unknown" for p in pairs]
        eng = hm.pct_rank(np.array([p[1] for p in pairs], dtype=float))
        Y, I, _ = gm.yardstick_design([p[0] for p in pairs], yardsticks)
        X = np.column_stack([eng] + Y + I)
        X = np.column_stack([gm._demean_by(X[:, k], inds) for k in range(X.shape[1])])
        beta, *_ = np.linalg.lstsq(X, gm._demean_by(ex, inds), rcond=None)
        out[d] = {"n": len(pairs), "coef": float(beta[0])}
    return out


# ---- B2 ---------------------------------------------------------------------------------------------------------------------------------------

def b2_v2(rows, bound, score_fn=None, group="industry", yardsticks=YARDSTICKS, n_resamples=hm.N_RESAMPLES):
    """Registration v2 B2.  Per date the neutral top-minus-bottom quintile spread of the engine's residual after the yardsticks (and the raw spread); the mean over dates.  `group`:
    "industry" (the bar), "sector" or "size" (date x size bucket) for the reported variants."""
    per = {}
    for d, rs in gm.by_date(rows).items():
        pairs = []
        for r in rs:
            s = (score_fn or (lambda r_: r_["score"].get(ENGINE)))(r)
            e = None if s is None else gm.excess_under(r, bound)
            if s is None or e is None:
                continue
            pairs.append((r, s, e))
        if len(pairs) < gm.MIN_NAMES:
            per[d] = {"n": len(pairs), "spread": float("nan"), "spread_residual": float("nan")}
            continue
        rs_ = [p[0] for p in pairs]
        ex = np.array([p[2] for p in pairs], dtype=float)
        sc = np.array([p[1] for p in pairs], dtype=float)
        if group == "industry":
            gk = [r.get("industry") or "unknown" for r in rs_]
        elif group == "sector":
            gk = [r.get("sector") or r.get("industry") or "unknown" for r in rs_]
        else:
            mc = np.array([(r.get("market_cap") if r.get("market_cap") is not None else np.nan) for r in rs_], dtype=float)
            q = np.minimum((hm.pct_rank(np.where(np.isnan(mc), np.nanmedian(mc) if (~np.isnan(mc)).any() else 0.0, mc)) * SIZE_BUCKETS).astype(int), SIZE_BUCKETS - 1)
            gk = [int(x) for x in q]
        sp, n_used = gm._neutral_spread(sc, ex, gk)
        eng = hm.pct_rank(sc)
        Yc, Ic, _ = gm.yardstick_design(rs_, yardsticks)
        Y = np.column_stack(Yc + Ic)
        Xd = np.column_stack([gm._demean_by(Y[:, k], gk) for k in range(Y.shape[1])])
        e_dm = gm._demean_by(eng, gk)
        beta, *_ = np.linalg.lstsq(Xd, e_dm, rcond=None)
        resid = e_dm - Xd @ beta
        spr, _ = gm._neutral_spread(resid + 1e-12 * np.arange(len(resid)), ex, gk)
        per[d] = {"n": len(pairs), "n_neutral": n_used, "spread": sp, "spread_residual": spr}
    sr = [v["spread_residual"] for v in per.values() if v["spread_residual"] == v["spread_residual"]]
    sw = [v["spread"] for v in per.values() if v["spread"] == v["spread"]]
    mean_r = float(np.mean(sr)) if sr else float("nan")
    status = "not computed" if not sr else ("strong pass" if mean_r >= B2_STRONG else "pass" if mean_r > 0 else "fail")
    return {"mean_spread_residual": mean_r, "mean_spread_raw": float(np.mean(sw)) if sw else float("nan"), "n_dates": len(sr),
            "ci90_residual": list(hm.bootstrap_mean_over_dates([v["spread_residual"] for v in per.values()], n_resamples)[:2]),
            "ci90_raw": list(hm.bootstrap_mean_over_dates([v["spread"] for v in per.values()], n_resamples)[:2]),
            "share_dates_positive_residual": (float(np.mean([x > 0 for x in sr])) if sr else None), "status": status, "by_date": per, "group": group}


# ---- B3 ---------------------------------------------------------------------------------------------------------------------------------------

def b3_v2(rows):
    """Level (the hard bar: the universe median IV / price in [0.67, 1.5]) and the pathology diagnostics (no bar)."""
    vp = [(r["vp"], r["family"] or "unclassified", r["date"]) for r in rows if r.get("vp") is not None]
    if not vp:
        return {"status": "not computed", "n": 0}
    v = np.array([x[0] for x in vp], dtype=float)
    fam = np.array([x[1] for x in vp])
    dts = np.array([x[2] for x in vp])
    med = float(np.median(v))
    base = gm.b3(rows)
    by_date = {d: float(np.median(v[dts == d])) for d in sorted(set(dts.tolist()))}
    fam_med = {f: float(np.median(v[fam == f])) for f in sorted(set(fam.tolist()))}
    return {"n": int(len(v)), "median_vp": med, "band": [LEVEL_LOW, LEVEL_HIGH], "status": "pass" if LEVEL_LOW <= med <= LEVEL_HIGH else "fail",
            "median_vp_by_date": by_date, "share_dates_median_in_band": float(np.mean([LEVEL_LOW <= x <= LEVEL_HIGH for x in by_date.values()])),
            "family_medians": fam_med, "diagnostics": {k: base.get(k) for k in ("share_below_0_4", "share_above_2_5", "share_extreme", "share_nonpositive_iv", "family_share_universe",
                                                                                "family_share_extremes", "family_gap_points", "iqr_ln_vp_positive_iv", "n_positive_iv")}}


# ---- B4 ---------------------------------------------------------------------------------------------------------------------------------------

def _sgn(x):
    return (x > 0) - (x < 0)


def b4_v2(rows):
    """Registration v2 B4, per family and measure: n, the engine's median absolute error against the naive baseline's, the P10..P90 coverage and the directional accuracy; the bar
    passes when every required family-measure has data and the engine's median is not above the naive's."""
    spec = {"revenue_growth": ("operating", "commodity"), "operating_margin": ("operating", "commodity"), "rote": ("financial",)}
    acc = {(m, f): [] for m, fams in spec.items() for f in fams}
    for r in rows:
        fam = r.get("family")
        fq = (r.get("fq") or {})
        base, o = r.get("base") or {}, r.get("out1") or {}
        st = r.get("state") or {}
        if fam in ("operating", "commodity") and fq.get("growth"):
            rev0, rev1 = base.get("revenue"), o.get("revenue")
            if rev0 and rev1 and r.get("g_naive") is not None:
                a = rev1 / rev0 - 1.0
                acc[("revenue_growth", fam)].append((r["date"], fq["growth"]["p50"], r["g_naive"], a, fq["growth"]["p10"], fq["growth"]["p90"], st.get("growth_latest")))
            m1 = o.get("operating_margin")
            if m1 is not None and r.get("m0") is not None and fq.get("margin"):
                acc[("operating_margin", fam)].append((r["date"], fq["margin"]["p50"], r["m0"], m1, fq["margin"]["p10"], fq["margin"]["p90"], r["m0"]))
        if fam == "financial" and fq.get("rote"):
            a, r0 = o.get("rote"), st.get("rote_latest")
            if a is not None and r0 is not None:
                acc[("rote", "financial")].append((r["date"], fq["rote"]["p50"], r0, a, fq["rote"]["p10"], fq["rote"]["p90"], r0))
    out = {}
    for (m, fam), xs in acc.items():
        if not xs:
            out[f"{m} | {fam}"] = {"n": 0, "status": "not computed"}
            continue
        eng = np.array([abs(x[1] - x[3]) for x in xs])
        nai = np.array([abs(x[2] - x[3]) for x in xs])
        cov = np.mean([x[4] <= x[3] <= x[5] for x in xs])
        dirs = [(_sgn(x[1] - x[6]), _sgn(x[3] - x[6])) for x in xs if x[6] is not None]
        dir_used = [(a, b) for a, b in dirs if a != 0 and b != 0]
        out[f"{m} | {fam}"] = {"n": len(xs), "median_abs_error_engine": float(np.median(eng)), "median_abs_error_naive": float(np.median(nai)),
                               "engine_not_worse": bool(np.median(eng) <= np.median(nai)), "share_engine_closer": float((eng < nai).mean()),
                               "coverage_p10_p90": float(cov), "directional_accuracy": (float(np.mean([a == b for a, b in dir_used])) if dir_used else None),
                               "n_direction": len(dir_used), "n_direction_excluded_zero_change": len(dirs) - len(dir_used),
                               "n_dates": len({x[0] for x in xs}), "status": "pass" if np.median(eng) <= np.median(nai) else "fail"}
    fams_present = {fam for (m, fam), xs in acc.items() if xs}
    required = [k for k in out]
    stats = [out[k]["status"] for k in required]
    status = ("not computed" if "not computed" in stats else "pass" if all(s == "pass" for s in stats) else "fail")
    return {"by_family_measure": out, "status": status, "families_with_data": sorted(fams_present)}


# ---- B5 and the whole -------------------------------------------------------------------------------------------------------------------------

def _score_alt(label):
    return lambda r: (r.get("score_alt") or {}).get(label)


def b5_and_b1_b2(rows, bound, n_boot=N_BOOT, price_basis_rows=None, with_variants=True):
    """B1 and B2 under one bound, B5's direction checks (the full sample and without the top 1% of |residual|) and the reported variants."""
    b1 = b1_pooled(rows, bound, n_boot=n_boot)
    b2 = b2_v2(rows, bound)
    out = {"B1": {k: v for k, v in b1.items() if not k.startswith("_")}, "B2": {k: v for k, v in b2.items() if k != "by_date"}, "B2_by_date": b2.get("by_date")}
    if b1.get("status") == "not computed":
        out["B5"] = {"status": "not computed"}
        return out
    # B5: the 1% of observations with the largest |residual| of the B1 regression are removed (from the rows of both bars; the ranks are then recomputed on the remaining names)
    res = b1["_residuals"]
    cut = np.quantile(np.abs(res), 1.0 - TRIM)
    drop = {id(r) for r, e in zip(b1["_keep"], np.abs(res)) if e > cut}
    rows_t = [r for r in rows if id(r) not in drop]
    b1t = b1_pooled(rows_t, bound, n_boot=n_boot)
    b2t = b2_v2(rows_t, bound)
    checks = {"B1_coefficient_positive": b1["beta"] > 0, "B2_residual_spread_positive": b2["mean_spread_residual"] > 0,
              "B1_coefficient_positive_without_top1pct_abs_resid": b1t.get("beta", float("nan")) > 0, "B2_residual_spread_positive_without_top1pct_abs_resid": b2t["mean_spread_residual"] > 0}
    out["B5"] = {"direction_checks": {k: bool(v) for k, v in checks.items()}, "status": "pass" if all(checks.values()) else "fail",
                 "without_top1pct_abs_resid": {"B1": {k: v for k, v in b1t.items() if not k.startswith("_")}, "B2": {k: v for k, v in b2t.items() if k != "by_date"}, "n_removed": len(drop)}}
    if not with_variants:
        return out
    # reported variants
    var = {}
    for lab, name in (("erp+100bp", "equity premium +100bp"), ("erp-100bp", "equity premium -100bp"), ("erp_damodaran", "equity premium: Damodaran's own (Addendum M sensitivity)")):
        if any((r.get("score_alt") or {}).get(lab) is not None for r in rows):
            f = _score_alt(lab)
            vb1 = b1_pooled(rows, bound, score_fn=f, n_boot=n_boot)
            vb2 = b2_v2(rows, bound, score_fn=f)
            var[name] = {"B1": {k: v for k, v in vb1.items() if not k.startswith("_")}, "B2": {k: v for k, v in vb2.items() if k != "by_date"}}
    for lab, eff, grp in (("sector-neutral", "sector", "sector"), ("size-neutral", "size", "size")):
        vb1 = b1_pooled(rows, bound, effects=eff, n_boot=n_boot)
        vb2 = b2_v2(rows, bound, group=grp)
        var[lab] = {"B1": {k: v for k, v in vb1.items() if not k.startswith("_")}, "B2": {k: v for k, v in vb2.items() if k != "by_date"}}
    if price_basis_rows is not None:
        vb1 = b1_pooled(price_basis_rows, bound, n_boot=n_boot)
        vb2 = b2_v2(price_basis_rows, bound)
        var["price basis: adjusted-only proxy"] = {"B1": {k: v for k, v in vb1.items() if not k.startswith("_")}, "B2": {k: v for k, v in vb2.items() if k != "by_date"}}
    out["variants_reported"] = var
    return out


def over_bounds(statuses):
    vals = set(statuses)
    return "not computed" if vals == {"not computed"} else ("pass" if vals == {"pass"} else ("fail" if vals == {"fail"} else "not decided"))


def v2_bars(rows, universe_label, n_boot=N_BOOT, return_end=gm.RETURN_DATES_END, price_basis_rows=None, with_variants=True):
    """Every registration-v2 bar for `rows` (the valued names of a universe, all development dates): B1, B2, B5 under the three bounds on the return dates, B3 on the return dates,
    B4 on every date; the overall outcome."""
    ret = [r for r in rows if r["date"] <= return_end]
    pbr = None if price_basis_rows is None else [r for r in price_basis_rows if r["date"] <= return_end]
    out = {"universe": universe_label, "n_valued": len(rows), "n_valued_return_dates": len(ret), "provisional": gm.PROVISIONAL, "return_dates": sorted({r["date"] for r in ret}),
           "b4_dates": sorted({r["date"] for r in rows}), "return_end": return_end, "n_boot": n_boot, "registration": "REGISTRATION_gate1_v2_DRAFT.md"}
    out["by_bound"] = {b: b5_and_b1_b2(ret, b, n_boot, pbr, with_variants) for b in gm.BOUNDS}
    out["B3"] = b3_v2(ret)
    out["B3_all_dates"] = b3_v2(rows)
    out["B4"] = b4_v2(rows)
    out["B4_return_dates_only"] = b4_v2(ret)
    st = {"B1": over_bounds([out["by_bound"][b]["B1"]["status"] for b in gm.BOUNDS]),
          "B2": over_bounds(["pass" if out["by_bound"][b]["B2"]["status"] in ("pass", "strong pass") else out["by_bound"][b]["B2"]["status"] for b in gm.BOUNDS]),
          "B3": over_bounds([out["B3"]["status"]] * 3), "B4": over_bounds([out["B4"]["status"]] * 3),
          "B5": over_bounds([out["by_bound"][b]["B5"]["status"] for b in gm.BOUNDS])}
    out["bar_status_over_bounds"] = st
    out["B2_strong_pass_by_bound"] = {b: out["by_bound"][b]["B2"]["status"] == "strong pass" for b in gm.BOUNDS}
    vals = list(st.values())
    out["outcome"] = ("PASS" if all(v == "pass" for v in vals) else "FAIL" if any(v == "fail" for v in vals) else "NOT DECIDED" if "not decided" in vals else "NOT COMPUTED")
    out["outcome_rule"] = "PASS: every hard bar passes under all three bounds; FAIL: a hard bar fails under all three; NOT DECIDED: a hard bar straddles across the bounds (Registration v2 section 4)"
    return out
