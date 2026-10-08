"""Metrics of the forensic tests, on the forensic panel (`panel.py`): per-date rank IC and B2-style residual quintile spread at any horizon, block-bootstrap intervals over dates, and the pooled
regression of B1 with extra controls.  The B2 construction is the registered one (rebuild_harness.gate1_v2.b2_v2: the engine's percentile rank, industry-demeaned, regressed on the five
yardstick ranks plus the missing-yardstick indicators; the industry-neutral top-minus-bottom quintile spread of the excess return by that residual), with the horizon as a parameter.

Overlapping horizons: monthly dates with a 12-month return share 11 months of return with their neighbour, so an interval that resamples dates one at a time is too narrow.  The intervals here
resample circular BLOCKS of consecutive dates, of length min(h, n_dates // 3) months (at least 1).  The point estimate is the plain mean over dates."""
import math
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from rebuild_harness import gate1_metrics as gm
from rebuild_harness import gate1_v2 as v2m
from rebuild_harness import metrics as hm

BOUNDS = ("excluded", "minus100", "last_close")
BLABEL = {"excluded": "excl", "minus100": "-100%", "last_close": "last"}
YSH = ("ey", "fcfy", "gp", "roc", "mom")
MIN_NAMES = gm.MIN_NAMES
N_BLOCK = 1000
SEED = 20261009


def pct_rank(x):
    return hm.pct_rank(np.asarray(x, dtype=float))


def rank_nan(s):
    """Percentile ranks of a Series with NaN left as NaN (ranks among the non-missing; +-inf allowed)."""
    v = s.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    ok = ~np.isnan(v)
    if ok.sum() > 1:
        out[ok] = pct_rank(v[ok])
    return pd.Series(out, index=s.index)


def yard_design(sub, ycols):
    """(rank columns, indicator columns) of the yardsticks for the names of one date (a name without the yardstick enters at rank 0.5, with an indicator column when anyone lacks it)."""
    cols, inds = [], []
    for c in ycols:
        v = sub[c].to_numpy(dtype=float)
        miss = np.isnan(v)
        rank = np.full(len(v), 0.5)
        if (~miss).any():
            rank[~miss] = pct_rank(v[~miss])
        cols.append(rank)
        if miss.any():
            inds.append(miss.astype(float))
    return cols, inds


def per_date(df: pd.DataFrame, score: str, h: int, bound: str, ycols=("y_ey", "y_fcfy", "y_gp", "y_roc", "y_mom"), min_names: int = MIN_NAMES, extra_resid_cols: Sequence[str] = (),
             score_values: Optional[pd.Series] = None) -> pd.DataFrame:
    """Per date: n, ic (Spearman rank correlation of the score with the excess return), ic_resid (the same for the score's residual after the yardsticks and any extra columns, industry-demeaned),
    spread_raw and spread_resid (industry-neutral top-minus-bottom quintile spread of the excess return).  `score_values` overrides the column (aligned on the index)."""
    xcol = f"x{h}_{bound}"
    out = {}
    s_all = df[score] if score_values is None else score_values
    for d, idx in df.groupby("date").groups.items():
        sub = df.loc[idx]
        s = s_all.loc[idx].to_numpy(dtype=float)
        x = sub[xcol].to_numpy(dtype=float)
        ok = np.isfinite(s) & np.isfinite(x)
        if ok.sum() < min_names:
            out[d] = {"n": int(ok.sum()), "ic": np.nan, "ic_resid": np.nan, "spread_raw": np.nan, "spread_resid": np.nan}
            continue
        sub = sub[ok]
        s, x = s[ok], x[ok]
        inds = [i if isinstance(i, str) else "unknown" for i in sub["industry"].tolist()]
        rk = pct_rank(s)
        ic = float(np.corrcoef(rk, pct_rank(x))[0, 1])
        sp_raw, _ = gm._neutral_spread(s, x, inds)
        Yc, Ic = yard_design(sub, ycols)
        extra = []
        for c in extra_resid_cols:
            v = sub[c].to_numpy(dtype=float)
            miss = np.isnan(v)
            r_ = np.full(len(v), 0.5)
            if (~miss).any():
                r_[~miss] = pct_rank(v[~miss])
            extra.append(r_)
            if miss.any():
                extra.append(miss.astype(float))
        Y = np.column_stack(Yc + Ic + extra) if (Yc or Ic or extra) else np.zeros((len(s), 0))
        Xd = np.column_stack([gm._demean_by(Y[:, j], inds) for j in range(Y.shape[1])]) if Y.shape[1] else Y
        e_dm = gm._demean_by(rk, inds)
        if Xd.shape[1]:
            beta, *_ = np.linalg.lstsq(Xd, e_dm, rcond=None)
            resid = e_dm - Xd @ beta
        else:
            resid = e_dm
        sp_res, _ = gm._neutral_spread(resid + 1e-12 * np.arange(len(resid)), x, inds)
        icr = float(np.corrcoef(pct_rank(resid + 1e-12 * np.arange(len(resid))), pct_rank(x))[0, 1])
        out[d] = {"n": int(len(s)), "ic": ic, "ic_resid": icr, "spread_raw": sp_raw, "spread_resid": sp_res}
    return pd.DataFrame.from_dict(out, orient="index").sort_index()


def block_ci(values: Sequence[float], block: int, n: int = N_BLOCK, seed: int = SEED, level: float = 0.90):
    """(lo, hi) of the mean of a date series by a circular moving-block bootstrap."""
    v = np.array([x for x in values if x == x], dtype=float)
    m = len(v)
    if m < 4:
        return (float("nan"), float("nan"))
    block = max(1, min(block, max(1, m // 3)))
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(m / block))
    means = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, m, size=nb)
        idx = (starts[:, None] + np.arange(block)[None, :]) % m
        means[i] = v[idx.ravel()[:m]].mean()
    a = (1 - level) / 2
    return (float(np.quantile(means, a)), float(np.quantile(means, 1 - a)))


def summarize(pd_: pd.DataFrame, h: int) -> Dict[str, float]:
    """Mean over dates of each per-date statistic, its 90% block interval (columns *_lo, *_hi) and the number of dates and name-dates."""
    res = {"n_dates": int(pd_["spread_resid"].notna().sum()), "n_obs": int(pd_["n"].sum())}
    for c in ("ic", "ic_resid", "spread_raw", "spread_resid"):
        v = pd_[c].to_numpy(dtype=float)
        ok = v[~np.isnan(v)]
        res[c] = float(ok.mean()) if len(ok) else float("nan")
        lo, hi = block_ci(v, h)
        res[c + "_lo"], res[c + "_hi"] = lo, hi
    return res


def metric_row(df, score, h, ycols=("y_ey", "y_fcfy", "y_gp", "y_roc", "y_mom"), bounds=BOUNDS, **kw) -> Dict[str, Dict[str, float]]:
    """{bound: summarize(per_date(...))} for one score and horizon."""
    return {b: summarize(per_date(df, score, h, b, ycols, **kw), h) for b in bounds}


def fmt_pct(x, nd=2, star=None):
    if x is None or x != x:
        return "n/a"
    s = f"{100 * x:+.{nd}f}"
    return s + ("*" if star else "")


def sig(res, key):
    lo, hi = res.get(key + "_lo"), res.get(key + "_hi")
    if lo is None or lo != lo or hi != hi:
        return False
    return lo > 0 or hi < 0


def triple(row, key, scale=100.0, nd=2, stars=True):
    """'a / b / c' of a metric under the three bounds (percent points for spreads, hundredths for IC), * where the 90% block interval excludes zero."""
    parts = []
    for b in BOUNDS:
        r = row[b]
        v = r.get(key)
        if v is None or v != v:
            parts.append("n/a")
        else:
            parts.append(f"{scale * v:+.{nd}f}" + ("*" if stars and sig(r, key) else ""))
    return " / ".join(parts)


# ---- the pooled regression with extra controls (B1 and F5) -----------------------------------------------------------------------------------------

def pooled_design(df: pd.DataFrame, score_vals: pd.Series, h: int, bound: str, ycols, control_cols: Sequence[str] = (), family_dummies: bool = False, min_names: int = MIN_NAMES):
    """The pooled B1 design: y = the excess return; X = [engine percentile rank, the yardstick ranks and their missing indicators, the controls' ranks and indicators (rank 0.5 where missing),
    family dummies]; fixed effects: date and industry.  Ranks are by date among the names with a score and an outcome.  Returns (y, X, cols, date codes, industry codes)."""
    xcol = f"x{h}_{bound}"
    ys, Xs, dts, inds = [], [], [], []
    cols = None
    for d, idx in df.groupby("date").groups.items():
        sub = df.loc[idx]
        s = score_vals.loc[idx].to_numpy(dtype=float)
        x = sub[xcol].to_numpy(dtype=float)
        ok = np.isfinite(s) & np.isfinite(x)
        if ok.sum() < min_names:
            continue
        sub, s, x = sub[ok], s[ok], x[ok]
        eng = pct_rank(s)
        Yc, Ic = [], []
        for c in ycols:                                   # a fixed layout: every yardstick has its indicator column on every date (all-zero columns are dropped afterwards)
            v = sub[c].to_numpy(dtype=float)
            miss = np.isnan(v)
            r_ = np.full(len(v), 0.5)
            if (~miss).any():
                r_[~miss] = pct_rank(v[~miss])
            Yc.append(r_)
            Ic.append(miss.astype(float))
        cc, ci = [], []
        for c in control_cols:
            v = sub[c].to_numpy(dtype=float)
            miss = np.isnan(v)
            r_ = np.full(len(v), 0.5)
            if (~miss).any():
                r_[~miss] = pct_rank(v[~miss])
            cc.append(r_)
            ci.append(miss.astype(float))
        fam = []
        if family_dummies:
            for f in ("financial", "commodity"):
                fam.append((sub["family"] == f).to_numpy(dtype=float))
        block = np.column_stack([eng] + Yc + cc + fam + Ic + ci)
        Xs.append(block)
        ys.append(x)
        dts += [d] * len(x)
        inds += [i if isinstance(i, str) else "unknown" for i in sub["industry"].tolist()]
    if not ys:
        return None
    X = np.vstack(Xs)
    keep = [0] + [j for j in range(1, X.shape[1]) if X[:, j].std() > 0]
    return np.concatenate(ys), X[:, keep], keep, v2m._codes(dts), v2m._codes(inds)


def pooled_coef(df, score_vals, h, bound, ycols, control_cols=(), family_dummies=False, fixed=("date", "industry"), n_boot=0):
    """Coefficient of the engine rank, its date-clustered (CR1) t-statistic and, when n_boot > 0, the wild-cluster bootstrap-t one-sided 90% lower bound (registered B1 method)."""
    des = pooled_design(df, score_vals, h, bound, ycols, control_cols, family_dummies)
    if des is None:
        return None
    y, X, _keep, dt, ind = des
    factors = [dt] + ([ind] if "industry" in fixed else [])
    try:
        beta, u, Xt, yt = v2m.fe_ols(y, X, factors)
        se = v2m.cluster_se(Xt, u, dt, 0)
    except np.linalg.LinAlgError:
        return None
    out = {"beta": float(beta[0]), "se": se, "t": float(beta[0] / se) if se > 0 else float("nan"), "n": int(len(y)), "n_dates": int(dt.max() + 1)}
    if n_boot:
        wb = v2m.wild_cluster_bootstrap(y, X, factors, dt, n_boot)
        out["lower90"] = wb["lower_90_one_sided"]
        out["p_one_sided"] = wb["p_one_sided"]
    return out
