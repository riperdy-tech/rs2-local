"""Item 3: regress the engine's monthly long-short (top minus bottom quintile of the registered within-industry rank, buy-and-hold, MAIN universe) on in-house factors:
MKT (SPY - rf/12), SMB, HML (book/price), MOM (12-1), STR (1-month reversal, long the losers), LVOL (long low volatility); quintile long-short factors from the same point-in-time panel (z06).
Equal-weighted engine on equal-weighted factors, value-weighted engine on value-weighted factors.  OLS with an intercept; alpha annualised x12 (arithmetic); t-statistics Newey-West (Bartlett kernel,
lag = floor(4 (n/100)^(2/9)): n=60 -> 3, n=20 -> 2, n=9 -> 2), the plain OLS t beside it.  HOLDOUT: 9 monthly observations, 7 parameters (2 degrees of freedom): the t-statistics are NOT reliable; the smaller
two-factor (MKT, HML) specification is added.  DEVELOPMENT: the 60 monthly returns of the QUARTERLY-rebalanced book (months 2 and 3 use the quarter-start ranks); the 20 month-1-only observations (fresh ranks)
are the supplement.  Subperiods 2020-2022 and 2023-2024 of the development book are given as a stability check."""
import math

import numpy as np
import pandas as pd

from leak_audit import libz

S = pd.read_pickle(libz.OUT / "z06_series.pkl")
FACT = ["MKT", "SMB", "HML", "MOM", "STR", "LVOL"]
out = {}


def nw_lag(n):
    return int(math.floor(4 * (n / 100) ** (2 / 9)))


def ols_nw(y, X, lag=None, names=None):
    """OLS y = Xb + e (X includes the constant first).  Returns coefficients, NW and OLS t-statistics, R2, adj R2, n, k, lag."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    u = y - X @ b
    L = nw_lag(n) if lag is None else lag
    Xu = X * u[:, None]
    Sg = Xu.T @ Xu
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        G = Xu[l:].T @ Xu[:-l]
        Sg += w * (G + G.T)
    V = XtXi @ Sg @ XtXi
    se_nw = np.sqrt(np.diag(V))
    s2 = (u @ u) / (n - k) if n > k else float("nan")
    se_ols = np.sqrt(np.diag(XtXi) * s2) if n > k else np.full(k, np.nan)
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (u @ u) / ss_tot if ss_tot > 0 else float("nan")
    r2a = 1 - (1 - r2) * (n - 1) / (n - k) if n > k else float("nan")
    return {"b": b, "t_nw": b / se_nw, "t_ols": b / se_ols, "se_nw": se_nw, "r2": float(r2), "r2_adj": float(r2a), "n": int(n), "k": int(k), "lag": int(L), "resid": u}


# self-test: lag 0 equals White's HC0; the OLS part equals lstsq
_rng = np.random.default_rng(1)
_X = np.column_stack([np.ones(40), _rng.normal(size=40)])
_y = 0.3 + 0.7 * _X[:, 1] + _rng.normal(size=40) * (1 + np.abs(_X[:, 1]))
_r = ols_nw(_y, _X, lag=0)
_bl = np.linalg.lstsq(_X, _y, rcond=None)[0]
_u = _y - _X @ _bl
_V = np.linalg.inv(_X.T @ _X) @ ((_X * _u[:, None]).T @ (_X * _u[:, None])) @ np.linalg.inv(_X.T @ _X)
assert np.allclose(_r["b"], _bl) and np.allclose(_r["se_nw"], np.sqrt(np.diag(_V)))


C = 0.003


def monthly(pn, name, kind, first_only=False, net=False):
    """(dates of the holding month, values) of a long-short series, flattened chronologically.  first_only: month 1 of every holding period only."""
    dts, vals = [], []
    for o in S[pn][(name, kind)]:
        if not o["ok"]:
            continue
        T = pd.Timestamp(o["date"])
        for j, v in enumerate(o["ls"]):
            if first_only and j > 0:
                continue
            if net and j == 0:
                v = v - C * (o["trades_L"] + o["trades_S"])          # 30 bp x every trade of the rebalance, both legs (the initial build is charged too)
            dts.append((T + pd.offsets.MonthEnd(j + 1)).strftime("%Y-%m"))
            vals.append(v)
    return pd.Series(vals, index=dts)


def mkt(pn, first_only=False):
    dts, vals = [], []
    for o in S[pn]["mkt"]:
        T = pd.Timestamp(o["date"])
        for j, v in enumerate(o["mkt"]):
            if first_only and j > 0:
                continue
            dts.append((T + pd.offsets.MonthEnd(j + 1)).strftime("%Y-%m"))
            vals.append(v)
    return pd.Series(vals, index=dts)


def frame(pn, kind, first_only=False, net=False):
    d = pd.DataFrame({"ENGINE": monthly(pn, "engine", kind, first_only, net), "MKT": mkt(pn, first_only)})
    for f in FACT[1:]:
        d[f] = monthly(pn, f, kind, first_only)
    return d.dropna()


def reg(d, cols, lab):
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in cols])
    r = ols_nw(d.ENGINE.to_numpy(), X)
    res = {"label": lab, "n": r["n"], "k": r["k"], "df": r["n"] - r["k"], "nw_lag": r["lag"], "alpha_monthly": float(r["b"][0]), "alpha_annual": 12 * float(r["b"][0]), "alpha_t_nw": float(r["t_nw"][0]), "alpha_t_ols": float(r["t_ols"][0]),
           "r2": r["r2"], "r2_adj": r["r2_adj"], "loadings": {c: {"b": float(r["b"][1 + i]), "t_nw": float(r["t_nw"][1 + i]), "t_ols": float(r["t_ols"][1 + i])} for i, c in enumerate(cols)},
           "engine_mean_monthly": float(d.ENGINE.mean()), "engine_mean_annual": 12 * float(d.ENGINE.mean()), "engine_t_mean_ols": float(d.ENGINE.mean() / (d.ENGINE.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 else None}
    return res


def show(res):
    ld = " ".join(f"{c} {v['b']:+.2f}({v['t_nw']:+.1f})" for c, v in res["loadings"].items())
    print(f"  {res['label']:46s} n={res['n']:3d} df={res['df']:3d} lag={res['nw_lag']} | alpha {100*res['alpha_annual']:+6.1f}%/yr  t_NW {res['alpha_t_nw']:+5.2f}  t_OLS {res['alpha_t_ols']:+5.2f} | R2 {res['r2']:.2f} adj {res['r2_adj']:.2f} | engine mean {100*res['engine_mean_annual']:+5.1f}%/yr | {ld}")


print("=== factor sanity: monthly mean (annualised), correlation with the engine ===")
for pn in ("hold", "dev"):
    for kind in ("ew", "vw"):
        d = frame(pn, kind)
        out[f"factors|{pn}|{kind}"] = {c: {"mean_annual": 12 * float(d[c].mean()), "t_ols": float(d[c].mean() / (d[c].std(ddof=1) / math.sqrt(len(d)))), "corr_with_engine": float(d[c].corr(d.ENGINE))} for c in ["ENGINE"] + FACT}
        print(pn, kind, "n=", len(d), " ".join(f"{c}:{100*12*d[c].mean():+.1f}%" for c in ["ENGINE"] + FACT), "| corr w/ engine " + " ".join(f"{c}:{d[c].corr(d.ENGINE):+.2f}" for c in FACT))
for kind in ("ew", "vw"):
    d = frame("dev", kind)
    print("dev", kind, "factor correlation matrix\n", d[FACT].corr().round(2).to_string())
print("=== regressions ===")
for pn, lab in (("dev", "2020-2024 development (quarterly book, 60 months)"), ("hold", "2025-01..09 holdout (monthly book, 9 months)")):
    for kind in ("ew", "vw"):
        d = frame(pn, kind)
        print(f"{pn} {kind.upper()} -- {lab}")
        for cols, tag in ((FACT, "6 factors"), (["MKT", "HML"], "MKT + HML"), ([], "no factors (mean)")):
            r = reg(d, cols, f"{tag}")
            out[f"reg|{pn}|{kind}|{tag}"] = r
            show(r)
        if pn == "dev":
            for a, b, tag in (("2020-01", "2022-12", "2020-2022"), ("2023-01", "2024-12", "2023-2024")):
                dd = d[(d.index >= a) & (d.index <= b)]
                r = reg(dd, FACT, f"6 factors, {tag}")
                out[f"reg|{pn}|{kind}|6 factors|{tag}"] = r
                show(r)
            d1 = frame(pn, kind, first_only=True)
            for cols, tag in ((FACT, "6 factors"), (["MKT", "HML"], "MKT + HML")):
                r = reg(d1, cols, f"month-1-only (fresh ranks), {tag}")
                out[f"reg|{pn}|{kind}|month1|{tag}"] = r
                show(r)
print("=== regressions on the engine long-short NET of 30 bp per trade (cost charged in the first month of each holding period) ===")
for pn in ("dev", "hold"):
    for kind in ("ew", "vw"):
        d = frame(pn, kind, net=True)
        for cols, tag in ((FACT, "6 factors"), ([], "no factors (mean)")):
            r = reg(d, cols, f"NET {pn} {kind} {tag}")
            out[f"regnet|{pn}|{kind}|{tag}"] = r
            show(r)
libz.dump(out, "z08_factor_regression.json")
