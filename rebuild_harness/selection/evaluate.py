"""selection/evaluate.py - the evaluation of REGISTRATION_selection.md v2 (approved 2026-10-11; O3 adopted, D9 kept), plan E1.

INPUT: a panel, one row per (date, company) of the evaluated universe, with
  date, cik, industry (SIC 2-digit), family, signal columns (`hs2`, `hs1_raw`= log expected IV / price, `trend` in {up, flat, down} for H-S3),
  the controls (CORE + EXPANDED below), `adv` (3-month average dollar volume), and the excess returns `ret_<h>_<bound>` for h in {1, 3, 6} and bound in
  {excluded, minus100, last_close} (None where unobservable: the Z 4 exit rule is the caller's, never imputed here).
WHAT IT COMPUTES (registration sections 2-5):
  hs1_signal     H-S1: the within-industry rank (industries under 5 names pooled within family; ties averaged), residualised cross-sectionally on book/price
                 and log size, the residual ranked
  ic_series      per date: Spearman(signal, the residual of the excess return after a cross-sectional OLS on the controls and industry dummies)
  nw_mean_t      the mean of a series with its Newey-West t (Bartlett kernel), 2 lags for 3-month returns (registration section 3)
  long_short     the top-minus-bottom quintile book, equal weight, monthly, no turnover cap, the liquidity-tiered cost schedule and short borrow
  sized_book     long only against SPY: weights proportional to (signal percentile - 0.5) in the top half, entry at the top quintile and hold above the median,
                 5% name / 25% industry caps with pro-rata redistribution and cash, 30% monthly turnover cap cutting the smallest trades first
  alpha          time-series OLS of a monthly return on in-house factors (market, size, value, momentum, reversal, low volatility) with a Newey-West t
  sequence       the fixed sequence H-S2 -> H-S1 -> H-S3 at t >= 2.0 over at least 36 confirmatory dates
  crisis_months  SPY 21-session realised volatility annualised above 35% at the month end
Nothing here is fitted on a return; every threshold is the registration's.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

CORE = ("bp", "log_size", "mom_12_1", "rev_1m", "beta", "idio_vol", "liquidity", "inv_price")
EXPANDED = CORE + ("ey", "fcfy", "gp", "roic")
T_BAR = 2.0
MIN_DATES = 36
NW_LAGS = {1: 0, 3: 2, 6: 5}
COST_SIDE, COST_SIDE_ILLIQ = 0.0030, 0.0060
BORROW_PA, BORROW_PA_ILLIQ = 0.0100, 0.0500
NAME_CAP, INDUSTRY_CAP, TURNOVER_CAP = 0.05, 0.25, 0.30
SEQUENCE = ("hs2", "hs1", "hs3")


# ---- signals ----------------------------------------------------------------------------------------------------------------------------------

def _rank_pct(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def hs1_signal(day: pd.DataFrame) -> pd.Series:
    """H-S1 for one date (registration section 2)."""
    d = day.copy()
    size = d.groupby("industry")["cik"].transform("count")
    d["grp"] = np.where(size >= 5, d["industry"].astype(str), "pool_" + d["family"].astype(str))
    d["r"] = d.groupby("grp")["hs1_raw"].transform(_rank_pct)
    ok = d[["r", "bp", "log_size"]].notna().all(axis=1)
    out = pd.Series(np.nan, index=d.index)
    if ok.sum() > 3:
        X = np.column_stack([np.ones(ok.sum()), d.loc[ok, "bp"], d.loc[ok, "log_size"]])
        b, *_ = np.linalg.lstsq(X, d.loc[ok, "r"].to_numpy(float), rcond=None)
        out[ok] = _rank_pct(pd.Series(d.loc[ok, "r"].to_numpy(float) - X @ b, index=d.index[ok]))
    return out


def hs3_signal(day: pd.DataFrame, hs1: pd.Series) -> pd.Series:
    """H-S3: H-S1 restricted to names whose SCR-10 trend is not "down" (O3); the excluded are not ranked."""
    return hs1.where(day["trend"] != "down")


# ---- information ------------------------------------------------------------------------------------------------------------------------------

def residual_returns(day: pd.DataFrame, ret: str, controls: Sequence[str]) -> pd.Series:
    """The excess return's residual after a cross-sectional OLS on the controls and industry dummies (rows with any missing input dropped)."""
    cols = [ret] + list(controls)
    ok = day[cols].notna().all(axis=1)
    d = day[ok]
    out = pd.Series(np.nan, index=day.index)
    if len(d) <= len(controls) + 5:
        return out
    dummies = pd.get_dummies(d["industry"].astype(str), drop_first=True, dtype=float)
    X = np.column_stack([np.ones(len(d)), d[list(controls)].to_numpy(float), dummies.to_numpy(float)])
    y = d[ret].to_numpy(float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    out[ok] = y - X @ b
    return out


def ic_series(panel: pd.DataFrame, signal: str, horizon: int, bound: str, controls: Sequence[str] = EXPANDED) -> pd.Series:
    """{date: Spearman(signal, residual excess return)} (registration section 3)."""
    ret = f"ret_{horizon}_{bound}"
    out = {}
    for d, day in panel.groupby("date"):
        res = residual_returns(day, ret, controls)
        both = pd.concat([day[signal], res], axis=1).dropna()
        if len(both) >= 10:
            out[d] = both.iloc[:, 0].rank().corr(both.iloc[:, 1].rank())
    return pd.Series(out).sort_index()


def nw_mean_t(x: Sequence[float], lags: int) -> Dict[str, float]:
    """The mean and its Newey-West t (Bartlett weights 1 - l/(lags+1))."""
    x = np.asarray([v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))], dtype=float)
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float(x.mean()) if n else None, "t": None, "lags": lags}
    u = x - x.mean()
    s = u @ u / n
    for l in range(1, lags + 1):
        s += 2 * (1 - l / (lags + 1)) * (u[l:] @ u[:-l]) / n
    se = math.sqrt(s / n) if s > 0 else float("nan")
    return {"n": n, "mean": float(x.mean()), "t": float(x.mean() / se) if se and not math.isnan(se) else None, "lags": lags}


# ---- money ------------------------------------------------------------------------------------------------------------------------------------

def _cost_side(adv: pd.Series) -> pd.Series:
    q20 = adv.quantile(0.2)
    return pd.Series(np.where(adv <= q20, COST_SIDE_ILLIQ, COST_SIDE), index=adv.index)


def long_short(panel: pd.DataFrame, signal: str, bound: str = "excluded") -> pd.DataFrame:
    """Monthly top-minus-bottom quintile, equal weight, no turnover cap; costs on actual turnover by liquidity tier, borrow on the short leg (registration
    section 3).  Returns per date: gross, cost, borrow, net."""
    rows, prev = [], {"L": {}, "S": {}}
    for d, day in sorted(panel.groupby("date"), key=lambda x: x[0]):
        day = day[day[signal].notna() & day[f"ret_1_{bound}"].notna()]
        if len(day) < 10:
            continue
        q = _rank_pct(day[signal])
        side = _cost_side(day["adv"])
        legs = {"L": day.index[q > 0.8], "S": day.index[q <= 0.2]}
        w = {k: {day.at[i, "cik"]: 1.0 / len(ix) for i in ix} for k, ix in legs.items()}
        cost_by = dict(zip(day["cik"], side))
        cost = 0.0
        for k in ("L", "S"):
            names = set(w[k]) | set(prev[k])
            cost += sum(abs(w[k].get(c, 0.0) - prev[k].get(c, 0.0)) * cost_by.get(c, COST_SIDE_ILLIQ) for c in names)
        illiq = set(day.loc[side == COST_SIDE_ILLIQ, "cik"])
        borrow = sum(wt * ((BORROW_PA_ILLIQ if c in illiq else BORROW_PA) / 12.0) for c, wt in w["S"].items())
        gross = day.loc[legs["L"], f"ret_1_{bound}"].mean() - day.loc[legs["S"], f"ret_1_{bound}"].mean()
        rows.append({"date": d, "gross": gross, "cost": cost, "borrow": borrow, "net": gross - cost - borrow})
        prev = w
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=["gross", "cost", "borrow", "net"])


def _cap(weights: Dict[str, float], industry: Dict[str, str]) -> Dict[str, float]:
    """5% per name and 25% per industry; the excess redistributed pro rata among names below their caps; what cannot be placed stays cash."""
    w = dict(weights)
    for _ in range(50):
        over = False
        for c in w:
            if w[c] > NAME_CAP + 1e-12:
                w[c], over = NAME_CAP, True
        by = {}
        for c, x in w.items():
            by[industry[c]] = by.get(industry[c], 0.0) + x
        for ind, tot in by.items():
            if tot > INDUSTRY_CAP + 1e-12:
                for c in w:
                    if industry[c] == ind:
                        w[c] *= INDUSTRY_CAP / tot
                over = True
        free = 1.0 - sum(w.values())
        room = {c: x for c, x in w.items() if x < NAME_CAP - 1e-12 and by.get(industry[c], 0.0) < INDUSTRY_CAP - 1e-12}
        if free > 1e-9 and room and not over:
            tot = sum(room.values())
            for c in room:
                w[c] += free * room[c] / tot
            continue
        if not over:
            break
    return w


def sized_targets(day: pd.DataFrame, signal: str, held: Sequence[str]) -> Dict[str, float]:
    """Long-only targets for one date: entry at the top quintile, hold while above the median; weights proportional to (percentile - 0.5); then the caps."""
    p = _rank_pct(day[signal])
    pct = dict(zip(day["cik"], p))
    keep = [c for c in held if pct.get(c) is not None and not math.isnan(pct[c]) and pct[c] > 0.5]
    enter = [c for c, x in pct.items() if x is not None and not math.isnan(x) and x > 0.8]
    names = sorted(set(keep) | set(enter))
    raw = {c: pct[c] - 0.5 for c in names}
    tot = sum(raw.values())
    if tot <= 0:
        return {}
    return _cap({c: x / tot for c, x in raw.items()}, dict(zip(day["cik"], day["industry"].astype(str))))


def turnover_capped(prev: Dict[str, float], target: Dict[str, float], cap: float = TURNOVER_CAP) -> Dict[str, float]:
    """Move from prev toward target with one-way turnover at most `cap`, cutting the smallest trades first (they are skipped, never partly filled)."""
    trades = {c: target.get(c, 0.0) - prev.get(c, 0.0) for c in set(prev) | set(target)}
    budget = 2 * cap                                                                       # buys + sells, one-way turnover = half the sum
    if sum(abs(x) for x in trades.values()) <= budget + 1e-12:
        return {c: x for c, x in target.items() if x > 0}
    kept = sorted(trades.items(), key=lambda kv: abs(kv[1]))                            # smallest first: dropped first
    while kept and sum(abs(x) for _, x in kept) > budget + 1e-12:
        kept.pop(0)
    # long only, never above full investment: a dropped sell must not leave a kept buy unfunded; the smallest kept buys go first (the remainder is cash)
    while kept and sum(prev.values()) + sum(x for _, x in kept) > 1.0 + 1e-12:
        buys = [i for i, (_, x) in enumerate(kept) if x > 0]
        if not buys:
            break
        kept.pop(buys[0])
    out = dict(prev)
    for c, x in kept:
        out[c] = out.get(c, 0.0) + x
    return {c: x for c, x in out.items() if x > 1e-12}


# ---- alpha, crisis months and the sequence ------------------------------------------------------------------------------------------------------

def alpha(y: Sequence[float], factors: pd.DataFrame, lags: int = 2) -> Dict[str, float]:
    """OLS y = a + F b; a monthly, its Newey-West t."""
    y = np.asarray(y, dtype=float)
    X = np.column_stack([np.ones(len(y)), factors.to_numpy(float)])
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for l in range(1, lags + 1):
        G = Xu[l:].T @ Xu[:-l]
        S += (1 - l / (lags + 1)) * (G + G.T)
    V = XtXi @ S @ XtXi
    return {"alpha_monthly": float(b[0]), "t": float(b[0] / math.sqrt(V[0, 0])), "n": n, "betas": dict(zip(factors.columns, map(float, b[1:])))}


def crisis_months(spy_close: pd.Series) -> pd.Series:
    """{month end: True when SPY's 21-session realised volatility annualised is above 35%} (registration section 3)."""
    r = np.log(spy_close).diff()
    vol = r.rolling(21).std() * math.sqrt(252)
    me = vol.groupby(vol.index.to_period("M")).last()
    return me > 0.35


def sequence(results: Dict[str, Dict[str, float]], adopted_o3: bool = True) -> Dict[str, object]:
    """The fixed sequence (registration section 2): each hypothesis tested only if every earlier one passed S1 (t >= 2.0, mean > 0, n >= 36 dates)."""
    order = [h for h in SEQUENCE if h != "hs3" or adopted_o3]
    out, ok = {}, True
    for h in order:
        r = results.get(h) or {}
        if not ok:
            out[h] = "not tested (an earlier hypothesis failed)"
            continue
        passed = (r.get("n") or 0) >= MIN_DATES and (r.get("mean") or 0) > 0 and (r.get("t") or 0) >= T_BAR
        out[h] = "pass" if passed else ("not decided (fewer than 36 dates)" if (r.get("n") or 0) < MIN_DATES else "fail")
        ok = passed
    return out
