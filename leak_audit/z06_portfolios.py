"""Items 2 and 3, step 2: monthly long-short portfolios of the engine and the in-house factors (series and turnover).

UNIVERSE: MAIN (Addendum Z 4): survivor == False (an observed traded price at T).  The ENGINE book is family != commodity (V3) with the registered within-industry quintiles; the FACTOR book uses every family
  (commodity included) of the same point-in-time panel (valued names, market cap >= $300M).  Census names (no traded price) are in neither.
PORTFOLIOS: formed at each panel date T from information at T; entry = adjusted OPEN of the first session after T (the registered convention); monthly returns tile the calendar (open after each month-end to the
  next); buy-and-hold weights drift inside the holding period.  HOLDOUT: 9 month-end dates, rebalanced monthly (1-month holding).  DEVELOPMENT: only the 20 QUARTER-ENDS were ever run (the engine takes ~25 min per
  date: 40 more month-ends are out of scope), so the book is rebalanced quarterly and held 3 months; its monthly series has 60 months (stale ranks in months 2-3); the month-1-only series (20 obs) has fresh ranks.
ENGINE LONG-SHORT: top minus bottom quintile of the registered within-industry rank (libz.within_industry_quintile), equal- and value-weighted (market cap at T), each leg one unit of notional.
FACTORS (pooled-rank quintiles of the panel universe at T; long-short = Q5 - Q1 unless noted): SMB = small - big (log market cap); HML = high - low book/price (sv_equity / mcap);
  MOM = winners - losers (12-1: adj close 21 -> 252 sessions back); STR = losers - winners (1-month return); LVOL = low - high volatility (std of 252 daily returns); MKT = SPY - rf/12 (rf = the
  panel's MRI risk-free).  Equal- and value-weighted variants.
DELISTING inside a holding period: the name is held to its last adjusted close and the proceeds sit flat afterwards (the 'last_close' convention); counts are reported.
TURNOVER of a leg = 0.5 * sum |w_new - w_drifted| (the share of the book replaced); trades = sum |dw| = 2 x turnover; cost = 30 bp x trades, both legs of the long-short (z07).
Output: z06_series.pkl (monthly series and trades), z06_book_{hold,dev}.pkl."""
import time
from datetime import date

import numpy as np
import pandas as pd

from leak_audit import lib, libz

t0 = time.time()
PR = pd.read_pickle(libz.OUT / "z05_prices.pkl")
SPY = pd.read_pickle(libz.OUT / "z05_spy.pkl").set_index("S")["P"]
CHAR = {"SMB": ("lmcap", -1), "HML": ("bp", +1), "MOM": ("mom_12_1", +1), "STR": ("ret_1m", -1), "LVOL": ("vol_1y", -1)}      # (characteristic, +1: long the high quintile, -1: long the low)


def build(panel_name):
    if panel_name == "hold":
        raw, score, J = lib.load_panel(), "s_cfg", 1
    else:
        raw, score, J = pd.read_pickle(libz.DEV_PANEL), "vp_mean", 3
    raw = raw[~raw.survivor.astype(bool)].drop(columns=[c for c in ("ret_1m", "mom_12_1", "vol_1y", "dvol_3m", "bar_gap") if c in raw.columns]).copy()      # own D5 features, identical for both panels
    raw = raw.merge(PR[PR.panel == panel_name].drop(columns=["panel"]), on=["date", "cik", "ticker"], how="inner")
    raw["lmcap"] = np.log(raw.mcap)
    raw["bp"] = raw.sv_equity / raw.mcap
    raw["engine_ok"] = (raw.family != "commodity") & raw[score].notna()
    raw["q"] = np.nan
    eng = raw[raw.engine_ok]
    raw.loc[eng.index, "q"] = libz.within_industry_quintile(eng, score)
    P0 = raw.P0.to_numpy(dtype=float)
    raw["G0"] = np.where(np.isfinite(P0), 1.0, np.nan)
    ended = np.zeros(len(raw), dtype=int)
    gap = np.zeros(len(raw), dtype=int)
    last_ratio = (raw.last_adj / raw.P0).to_numpy(dtype=float)
    Ssets = [libz.month_ends(date.fromisoformat(d), J + 1) for d in raw.date]
    end = pd.to_datetime(raw.end_date).dt.date.to_numpy()
    for j in range(1, J + 1):
        pj = raw[f"P{j}"].to_numpy(dtype=float)
        prev = raw[f"G{j-1}"].to_numpy(dtype=float)
        g = pj / P0
        miss = ~np.isfinite(g) & np.isfinite(prev)
        ser_end = np.array([end[i] <= Ssets[i][j] for i in range(len(raw))])
        g = np.where(miss & ser_end, last_ratio, g)                  # the series ended: held to the last adjusted close
        g = np.where(miss & ~ser_end, prev, g)                       # a data gap with the series still alive: carried
        ended += (miss & ser_end).astype(int)
        gap += (miss & ~ser_end).astype(int)
        raw[f"G{j}"] = g
    raw["n_flat"] = ended
    raw["n_gap"] = gap
    return raw, score, J


def leg_returns(members: pd.DataFrame, w: np.ndarray, J: int):
    V = [1.0]
    for j in range(1, J + 1):
        V.append(float(np.sum(w * members[f"G{j}"].to_numpy(dtype=float))))
    r = [V[j] / V[j - 1] - 1.0 for j in range(1, J + 1)]
    wd = w * members[f"G{J}"].to_numpy(dtype=float) / V[J]
    return r, dict(zip(members.cik, wd))


def weights(members, kind):
    if kind == "ew":
        return np.full(len(members), 1.0 / len(members))
    m = members.mcap.to_numpy(dtype=float)
    return m / m.sum()


def ls_series(raw, J, legs_fn, kind):
    """Long-short series, trades and membership for one construction.  legs_fn(sub) -> (long_members, short_members)."""
    rec, prev = [], None
    for d in sorted(raw.date.unique()):
        sub = raw[(raw.date == d) & np.isfinite(raw["G%d" % J].to_numpy(dtype=float))]
        L, S = legs_fn(sub)
        if len(L) < 5 or len(S) < 5:
            rec.append({"date": d, "ok": False})
            prev = None
            continue
        wL, wS = weights(L, kind), weights(S, kind)
        rL, dL = leg_returns(L, wL, J)
        rS, dS = leg_returns(S, wS, J)
        o = {"date": d, "ok": True, "nL": len(L), "nS": len(S), "rL": rL, "rS": rS, "ls": [a - b for a, b in zip(rL, rS)], "flatL": int((L.n_flat > 0).sum()), "flatS": int((S.n_flat > 0).sum()),
             "membL": set(L.cik), "membS": set(S.cik)}
        newL, newS = dict(zip(L.cik, wL)), dict(zip(S.cik, wS))
        if prev is not None:
            for nm, new, old in (("L", newL, prev[0]), ("S", newS, prev[1])):
                o[f"trades_{nm}"] = float(sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in set(new) | set(old)))
                o[f"to_{nm}"] = o[f"trades_{nm}"] / 2
            o["initial"] = False
        else:
            o["trades_L"] = o["trades_S"] = 1.0                       # building a leg from cash: one unit bought
            o["initial"] = True
        prev = (dL, dS)
        rec.append(o)
    return rec


def engine_legs(sub):
    return sub[sub.q == 4], sub[sub.q == 0]


def factor_legs(name):
    ch, sgn = CHAR[name]

    def fn(sub):
        s = sub[np.isfinite(sub[ch].to_numpy(dtype=float))]
        if len(s) < 50:
            return s.iloc[0:0], s.iloc[0:0]
        order = np.argsort(s[ch].to_numpy(dtype=float), kind="mergesort")
        grp = np.empty(len(s), dtype=int)
        grp[order] = (np.arange(len(s)) * 5) // len(s)
        hi, lo = s[grp == 4], s[grp == 0]
        return (hi, lo) if sgn > 0 else (lo, hi)
    return fn


series = {}
for pn in ("hold", "dev"):
    raw, score, J = build(pn)
    print(pn, "names", len(raw), "engine-eligible", int(raw.engine_ok.sum()), "with quintile", int(raw.q.notna().sum()), "series ended inside the horizon (name-dates):", int((raw.n_flat > 0).sum()),
          "data gaps:", int((raw.n_gap > 0).sum()), f"[{time.time()-t0:.0f}s]", flush=True)
    dates = sorted(raw.date.unique())
    series[pn] = {"dates": dates, "J": J, "n_flat": int((raw.n_flat > 0).sum()), "n_gap": int((raw.n_gap > 0).sum()), "n_names": int(len(raw))}
    for kind in ("ew", "vw"):
        series[pn][("engine", kind)] = ls_series(raw, J, engine_legs, kind)
        for f in CHAR:
            series[pn][(f, kind)] = ls_series(raw, J, factor_legs(f), kind)
    mk = []
    for d in dates:
        S = libz.month_ends(date.fromisoformat(d), J + 1)
        p = [SPY.get(s.isoformat(), np.nan) for s in S]
        rf = float(raw.loc[raw.date == d, "rf"].iloc[0])
        mk.append({"date": d, "mkt": [p[j] / p[j - 1] - 1.0 - rf / 12 for j in range(1, J + 1)], "spy": [p[j] / p[j - 1] - 1.0 for j in range(1, J + 1)]})
    series[pn]["mkt"] = mk
    raw.to_pickle(libz.OUT / f"z06_book_{pn}.pkl")
pd.to_pickle(series, libz.OUT / "z06_series.pkl")
print("done", time.time() - t0)
