"""Study A (shrinkage of company-specific inputs) and Study B (margin baselines): walk-forward, forecast loss only, information to 2024-12-31.

Everything here is a pure function of the study panel (`panel.build`) and the priors vintage-2024 observation table.  There is no price, no return and no valuation in this module; the score is the absolute
error of a forecast of a reported fundamental.

WALK-FORWARD RULE.  A fit at origin year Y (T = Y-06-30) may use an observation only if (a) its origin is before T and (b) its outcome annual report was filed strictly before T.  Every estimate (the population
medians and quantiles, the blend weight w, the mean-reversion speeds, the cyclicality cut points, a company's operating-leverage regression) is re-made at each origin from that set alone.

VARIABLES.  family x variable:  operating growth (revenue), operating margin, financial growth (tangible book, the engine's g1) and financial ROTE.  Horizons k = 1, 2, 3 (the year-k value, not cumulative).
CANDIDATES (Study A).  i   unconditional population median of the same family's year-k outcome (all companies of any size, outcomes known at T);
                       ii  the state-conditioned prior P50 = the code's input (the engine's own chain at the prior's median);
                       iii naive persistence (margin, ROTE held) / the trailing CAGR (growth: the 3-year CAGR, else the latest year: the mechanical baseline of the priors);
                       blends  x = i + w (ii - i), w per variable x family x horizon fitted walk-forward: `b_mae` (the grid w in [0, 1] step 0.05 minimising the training mean absolute error) and `b_eb`
                       (Gemini's empirical-Bayes form w = max(0, 1 - sigma^2/tau^2): tau^2 the cross-sectional variance of the company deviation d = ii - i, sigma^2 = Var(d) - Cov(d, r) the part of that
                       variance that does not move with the realised deviation r = y - i; both winsorised at the 1st and 99th percentile; clipped to [0, 1]).  The training pairs use the (i) value of their own origin.
"""
import math

import numpy as np
import pandas as pd

KS = (1, 2, 3)
GRID = np.round(np.arange(0.0, 1.0001, 0.05), 2)
AUDIT = []                         # (what, key, T, latest outcome filing used, latest origin year used): every fit appends; the report asserts that none reaches T
MIN_TRAIN = 100                    # a fit on fewer observations is not made (the blend is then undefined that year)
HIST_MAX, HIST_MIN = 8, 5          # the operating-leverage regression: the latest 8 fiscal years, at least 5

# (family, variable) -> y stem of the outcome, the code's column stem, the naive column, the population stem, alternative code columns
VARS = {
    ("operating", "growth"): dict(y="g", c="c_growth_{k}", naive="mech_g1", pop="g", alt={"iii_last": "f_g_latest"}),
    ("operating", "margin"): dict(y="m", c="c_margin_{k}", naive="f_m", pop="m", alt={"ii_curve": "c_margin_curve_{k}_p50"}),
    ("financial", "growth"): dict(y="tg", c="c_growth_{k}", naive="mech_g1", pop="tg", alt={"iii_last": "f_tg_latest"}),
    ("financial", "rote"): dict(y="rote", c="c_rote_{k}", naive="rote_latest", pop="rote", alt={"ii_norm": "c_rote_norm_{k}_p50", "ii_curve": "c_rote_curve_{k}_p50"}),
}


def t_of(year):
    return f"{year}-06-30"


# ---- (i) the population -----------------------------------------------------------------------------------------------------------------------------

class Population:
    """The year-k outcomes of the whole archive population (any size), by family, as known at an origin: the outcome's annual report filed strictly before it."""

    def __init__(self, obs):
        self.obs = obs
        self._c = {}

    def stats(self, family, stem, k, T):
        key = (family, stem, k, T)
        if key not in self._c:
            d = self.obs
            f = d[f"filed_{k}"]
            m = (d["family"] == family) & f.notna() & (f < T)
            v = d.loc[m, f"{stem}_{k}"].astype(float).dropna().to_numpy()
            if len(v) < MIN_TRAIN:
                self._c[key] = None
            else:
                q = np.quantile(v, [0.1, 0.5, 0.9])
                self._c[key] = {"p10": float(q[0]), "p50": float(q[1]), "p90": float(q[2]), "n": int(len(v)), "max_filed": str(f[m].max())}
                AUDIT.append(("population", key, T, self._c[key]["max_filed"], None))
        return self._c[key]


def winsor(x, lo=1, hi=99):
    a, b = np.percentile(x, [lo, hi])
    return np.clip(x, a, b)


def fit_w_mae(p, c, y):
    best, bw = None, None
    for w in GRID:
        e = float(np.mean(np.abs(y - (p + w * (c - p)))))
        if best is None or e < best - 1e-15:
            best, bw = e, float(w)
    return bw


def fit_w_eb(p, c, y):
    d, r = winsor(c - p), winsor(y - p)
    vd = float(np.var(d))
    if vd <= 0:
        return 0.0
    cov = float(np.mean((d - d.mean()) * (r - r.mean())))
    return float(min(1.0, max(0.0, 1.0 - (vd - cov) / vd)))


# ---- Study A -------------------------------------------------------------------------------------------------------------------------------------------

def build_candidates(P, pop, family, var, k):
    """The panel rows of one family with the candidates' point forecasts for horizon k, the outcome and the (i) / (ii) quantiles.  Columns: year, cik, y, x_i, x_ii, x_iii, alternatives, quantiles."""
    spec = VARS[(family, var)]
    d = P[(P.family == family)].copy()
    cbase = spec["c"].format(k=k)
    nan = pd.Series(np.nan, index=d.index)
    d["y"] = d[f"{spec['y']}_{k}"].astype(float)
    d["x_ii"] = d[cbase + "_p50"] if (cbase + "_p50") in d else nan
    d["x_ii_p10"] = d[cbase + "_p10"] if (cbase + "_p10") in d else nan
    d["x_ii_p90"] = d[cbase + "_p90"] if (cbase + "_p90") in d else nan
    d["x_iii"] = d[spec["naive"]].astype(float)
    for nm, col in spec["alt"].items():
        c = col.format(k=k)
        d["x_" + nm] = d[c] if c in d else nan
    px = {yr: pop.stats(family, spec["pop"], k, t_of(yr)) for yr in sorted(d.year.unique())}
    for q in ("p50", "p10", "p90"):
        d["x_i" + ("" if q == "p50" else "_" + q)] = d.year.map(lambda yr: np.nan if px[yr] is None else px[yr][q])
    for c in [c for c in d.columns if c.startswith("x_")]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["filed"] = d[f"filed_{k}"]
    # (i-u): the median outcome of this study's own universe (market cap >= $300M) at the earlier origins, outcomes filed before T (a size-matched population median; a robustness candidate)
    iu = {}
    for Y in sorted(d.year.unique()):
        tr = d[(d.year < Y) & d["y"].notna() & d["filed"].notna() & (d["filed"] < t_of(Y))]
        iu[Y] = float(tr["y"].median()) if len(tr) >= MIN_TRAIN else np.nan
    d["x_iu"] = d.year.map(iu)
    return d


def walk_forward_w(d, years):
    """{year: {"mae": w, "eb": w, "n": n} or None}: fitted at each origin year on the rows of earlier origins whose outcome was filed before T."""
    out = {}
    ok = d["y"].notna() & d["x_i"].notna() & d["x_ii"].notna() & d["filed"].notna()
    for Y in years:
        tr = d[ok & (d.year < Y) & (d["filed"] < t_of(Y))]
        if len(tr) < MIN_TRAIN:
            out[Y] = None
            continue
        p, c, y = tr["x_i"].to_numpy(float), tr["x_ii"].to_numpy(float), tr["y"].to_numpy(float)
        out[Y] = {"mae": fit_w_mae(p, c, y), "eb": fit_w_eb(p, c, y), "n": int(len(tr)), "max_filed": str(tr["filed"].max()), "max_origin_year": int(tr.year.max())}
        AUDIT.append(("blend_weight", Y, t_of(Y), out[Y]["max_filed"], out[Y]["max_origin_year"]))
    return out


def attach_blends(d, W):
    for nm in ("mae", "eb"):
        d[f"w_{nm}"] = d.year.map(lambda Y: np.nan if W.get(Y) is None else W[Y][nm])
        w = d[f"w_{nm}"]
        d[f"x_b_{nm}"] = d["x_i"] + w * (d["x_ii"] - d["x_i"])
        d[f"x_b_{nm}_p10"] = d["x_i_p10"] + w * (d["x_ii_p10"] - d["x_i_p10"])
        d[f"x_b_{nm}_p90"] = d["x_i_p90"] + w * (d["x_ii_p90"] - d["x_i_p90"])
    return d


def run_cell(P, pop, family, var, k):
    d = build_candidates(P, pop, family, var, k)
    W = walk_forward_w(d, sorted(d.year.unique()))
    return attach_blends(d, W), W


def cluster_t(diff, cik):
    """Mean of a paired difference (candidate error minus reference error) with its cluster-robust (by company) t statistic."""
    m = diff.notna()
    x, g = diff[m].to_numpy(float), cik[m].to_numpy()
    if len(x) < 30:
        return {"mean": float(np.mean(x)) if len(x) else float("nan"), "t": float("nan"), "n": int(len(x))}
    mu = x.mean()
    s = pd.DataFrame({"x": x - mu, "g": g}).groupby("g")["x"].sum()
    se = math.sqrt(float((s ** 2).sum())) / len(x)
    return {"mean": float(mu), "t": float(mu / se) if se > 0 else float("nan"), "n": int(len(x))}


A_CANDS = ("i", "ii", "iii", "b_mae", "b_eb")


def score_cell(d, cands, need=("i", "ii", "iii")):
    """Absolute errors of each candidate on the common sample (rows where the outcome and every candidate in `need` exist).  Returns (frame of errors with year, cik, sample flags)."""
    ok = d["y"].notna()
    for c in need:
        ok &= d["x_" + c].notna()
    s = d[ok]
    e = pd.DataFrame({"year": s.year, "cik": s.cik}, index=s.index)
    for c in cands:
        if "x_" + c in s:
            e[c] = (s["y"] - s["x_" + c]).abs()
    return e, s


def by_year(e, cands):
    rows = []
    for Y, g in e.groupby("year"):
        r = {"year": Y, "n": len(g)}
        for c in cands:
            if c in g:
                v = g[c].dropna()
                r[c + "_mae"] = v.mean() if len(v) else np.nan
                r[c + "_med"] = v.median() if len(v) else np.nan
                r[c + "_n"] = len(v)
        rows.append(r)
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["year", "n"])


def coverage(s, cands):
    out = {}
    for c in cands:
        lo, hi = s.get(f"x_{c}_p10"), s.get(f"x_{c}_p90")
        if lo is None or hi is None:
            continue
        m = lo.notna() & hi.notna() & s["y"].notna()
        if m.sum() >= 30:
            out[c] = float(((s["y"][m] >= lo[m]) & (s["y"][m] <= hi[m])).mean())
    return out


# ---- Study B -------------------------------------------------------------------------------------------------------------------------------------------

def tercile_cuts(v):
    v = v[np.isfinite(v)]
    return None if len(v) < MIN_TRAIN else (float(np.quantile(v, 1 / 3)), float(np.quantile(v, 2 / 3)))


def band_of(x, cuts):
    if cuts is None or x is None or not np.isfinite(x):
        return "none"
    return "low" if x < cuts[0] else ("mid" if x < cuts[1] else "high")


class Reversion:
    """Measured partial mean reversion, walk-forward: x_k = x0 + lam (anchor - x0), lam fitted by the grid MAE on the whole population's rows of the family whose year-k outcome is filed before T, separately
    for each cell of the conditioning: the cyclicality band (equal-weight terciles of the training rows; operating family only - the margin-based score is not defined for the financial family) and,
    with `signed`, the sign of the deviation x0 - anchor (|deviation| < 0.5 points is `flat`: the code's own rule).  A cell with fewer than MIN_TRAIN rows uses the pooled fit."""

    def __init__(self, obs, family, level, anchor, y, banded, signed=False):
        o = obs[obs.family == family]
        self.o, self.level, self.anchor, self.y, self.banded, self.signed, self._c = o, level, anchor, y, banded, signed, {}

    @staticmethod
    def sign_of(x0, a):
        d = x0 - a
        return "flat" if abs(d) < 0.005 else ("pos" if d > 0 else "neg")

    def cell_of(self, x0, a, cyc, cuts):
        b = band_of(cyc, cuts) if self.banded else "none"
        if self.signed:
            b = b + "_" + self.sign_of(x0, a)
        return b

    def fit(self, k, T):
        key = (k, T)
        if key in self._c:
            return self._c[key]
        o = self.o
        f = o[f"filed_{k}"]
        tr = o[f.notna() & (f < T) & o[self.level].notna() & o[self.anchor].notna() & o[f"{self.y}_{k}"].notna()]
        res = {"cuts": None, "lam": {}, "n": {}, "max_filed": None}
        if len(tr) >= MIN_TRAIN:
            res["max_filed"] = str(f[tr.index].max())
            AUDIT.append(("reversion", (self.level, k, self.signed), T, res["max_filed"], None))
            if self.banded:
                res["cuts"] = tercile_cuts(o.loc[f.notna() & (f < T), "cyc"].to_numpy(float))
            cells = [self.cell_of(x0, a, c, res["cuts"]) for x0, a, c in zip(tr[self.level], tr[self.anchor], tr["cyc"] if "cyc" in tr else [None] * len(tr))]
            cells = pd.Series(cells, index=tr.index)
            for b, g in tr.groupby(cells):
                if len(g) >= MIN_TRAIN:
                    res["lam"][b] = fit_w_mae(g[self.level].to_numpy(float), g[self.anchor].to_numpy(float), g[f"{self.y}_{k}"].to_numpy(float))
                    res["n"][b] = int(len(g))
            res["lam"]["_pooled"] = fit_w_mae(tr[self.level].to_numpy(float), tr[self.anchor].to_numpy(float), tr[f"{self.y}_{k}"].to_numpy(float))
        self._c[key] = res
        return res

    def predict(self, k, T, x0, anchor, cyc):
        r = self.fit(k, T)
        if not r["lam"]:
            return np.nan, np.nan, "none"
        a = x0 if (anchor is None or not np.isfinite(anchor)) else anchor
        b = self.cell_of(x0, a, cyc, r["cuts"])
        lam = r["lam"].get(b, r["lam"].get("_pooled"))
        return x0 + lam * (a - x0), lam, b


def universe_frame(P, level, anchor, y, cyc=None):
    """The study universe's own rows as a training table for `Reversion` (columns named like the observation table's): the earlier origins' state and outcomes.  A fit at T keeps the rows whose outcome
    was filed before T, which are exactly the earlier origins' (an outcome is filed after its own origin)."""
    u = pd.DataFrame({"family": P.family, level: P[level if level in P else {"m": "f_m", "rote": "rote_latest"}[level]], anchor: P[{"med8": "f_med8", "rote_med8": "f_rote_med8"}[anchor]]})
    u["cyc"] = P["f_cyc_equal"] if cyc is None else P[cyc]
    for k in KS:
        u[f"{y}_{k}"], u[f"filed_{k}"] = P[f"{y}_{k}"], P[f"filed_{k}"]
    return u


def history_index(obs):
    """cik -> arrays (fye, revenue, operating income) of its first-filed fiscal years, ascending: the company's own history (operating income = margin x revenue)."""
    o = obs[obs.rev.notna() & (obs.rev > 0) & obs.m.notna()][["cik", "fye", "rev", "m"]].sort_values(["cik", "fye"])
    h = {}
    for cik, g in o.groupby("cik", sort=False):
        h[cik] = (g.fye.to_numpy(), g.rev.to_numpy(float), (g.m * g.rev).to_numpy(float))
    return h


def leverage_fit(h, cik, base_fye):
    """(contribution margin c, intercept a) of OI = a + c x Rev over the company's latest HIST_MAX fiscal years up to the base year (at least HIST_MIN), or None."""
    x = h.get(cik)
    if x is None:
        return None
    fye, rev, oi = x
    n = int(np.searchsorted(fye, base_fye, side="right"))
    lo = max(0, n - HIST_MAX)
    r, o = rev[lo:n], oi[lo:n]
    if len(r) < HIST_MIN or np.ptp(r) <= 0:
        return None
    rm, om = r.mean(), o.mean()
    c = float(((r - rm) * (o - om)).sum() / ((r - rm) ** 2).sum())
    return c, float(om - c * rm)


def margin_study(P, obs, pop, growth_cells, rev_key):
    """One frame per horizon with the margin baselines of Study B for the operating family, indexed like P.  `growth_cells[k]` is the Study-A growth cell (frame with x_* columns) from which the revenue
    forecast `rev_key` (a candidate name such as "b_mae") is read; the oracle variants use the realised (first-filed) revenue of the year.  Columns:
      y        the year-k operating margin, first filed         ref      the population median margin known at T (the trimming reference, candidate-independent)
      persist  the base margin held (as known at T)             ii       the engine's P50 margin path (needs the vintage's margin_target)      ii_curve  the engine's retention-only path
      rev_band persistence + measured partial mean reversion toward the 8-year median, one speed per cyclicality band, fitted at T on the population (walk-forward)
      lev_pred / lev_oracle  OI = a + c Rev fitted on the company's own latest 8 fiscal years (at least 5) up to the base year, applied to the forecast / the realised revenue; `_clip`: c held in [0, 1]"""
    h = history_index(obs)
    rv = Reversion(obs, "operating", "m", "med8", "m", True)
    rvs = Reversion(obs, "operating", "m", "med8", "m", True, signed=True)
    U = universe_frame(P, "m", "med8", "m")
    rvu, rvus = Reversion(U, "operating", "m", "med8", "m", True), Reversion(U, "operating", "m", "med8", "m", True, signed=True)
    op = P[P.family == "operating"]
    cum, cumhat = pd.Series(1.0, index=op.index), {}
    for k in KS:
        cum = cum * (1.0 + growth_cells[k]["x_" + rev_key].reindex(op.index))
        cumhat[k] = cum.copy()
    out = {}
    for k in KS:
        rows = []
        for idx, r in op.iterrows():
            T = t_of(r.year)
            m0 = r["f_m"]
            st = pop.stats("operating", "m", k, T)
            rec = {"idx": idx, "year": r.year, "cik": r.cik, "y": r[f"m_{k}"], "persist": m0, "ref": np.nan if st is None else st["p50"],
                   "ii": r.get(f"c_margin_{k}_p50", np.nan), "ii_curve": r.get(f"c_margin_curve_{k}_p50", np.nan)}
            if pd.notna(m0):
                rec["rev_band"], rec["rev_lam"], rec["band"] = rv.predict(k, T, m0, r["f_med8"], r["f_cyc_equal"])
                rec["rev_band_sign"] = rvs.predict(k, T, m0, r["f_med8"], r["f_cyc_equal"])[0]
                rec["rev_band_u"], rec["rev_lam_u"], _ = rvu.predict(k, T, m0, r["f_med8"], r["f_cyc_equal"])
                rec["rev_band_sign_u"] = rvus.predict(k, T, m0, r["f_med8"], r["f_cyc_equal"])[0]
            x = h.get(r.cik)
            fit = leverage_fit(h, r.cik, r.base_fye)
            rec["lev_c"] = np.nan if fit is None else fit[0]
            rev0 = pd.to_numeric(r["f_rev"], errors="coerce")
            for tag, revk in (("pred", rev0 * cumhat[k].get(idx, np.nan)), ("oracle", r.get(f"rev_{k}", np.nan))):
                rec["lev_" + tag] = rec["lev_" + tag + "_clip"] = np.nan
                if fit is None or not pd.notna(revk) or revk <= 0:
                    continue
                c, a = fit
                rec["lev_" + tag] = c + a / revk
                cc = min(1.0, max(0.0, c))
                n = int(np.searchsorted(x[0], r.base_fye, side="right"))
                lo = max(0, n - HIST_MAX)
                a2 = x[2][lo:n].mean() - cc * x[1][lo:n].mean()
                rec["lev_" + tag + "_clip"] = cc + a2 / revk
            rows.append(rec)
        out[k] = pd.DataFrame(rows).set_index("idx")
    return out
