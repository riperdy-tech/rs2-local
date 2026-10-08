"""F1-F9 of Stage 1 (SPEC_rebuild Addendum U) on the forensic panel.

    python -m rebuild_harness.forensics.analysis_f PANEL.pkl OUT_DIR [--only F1 F6 ...] [--n-boot N]

Writes one markdown file and one JSON file per section into OUT_DIR (a NEW folder per attempt).  Every return result is reported under the three survivorship bounds of gate 1, in the order
excluded / -100% / last close.  Spreads are in percentage points of excess return (over SPY) per horizon; IC is the mean per-date Spearman rank correlation times 100.  A star marks a 90% block-bootstrap
interval over dates that excludes zero (blocks of min(h, n_dates / 3) consecutive months: overlapping returns).  Development data only (valuation dates 2020-01 .. 2024-12).
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import fxm
from .fxm import BOUNDS

HZ = (3, 6, 12, 18, 24, 36)
Y5 = ("y_ey", "y_fcfy", "y_gp", "y_roc", "y_mom")
FAMILIES = ("operating", "financial", "commodity")


# ---- helpers ------------------------------------------------------------------------------------------------------------------------------------

def md(header, rows):
    out = ["| " + " | ".join(str(h) for h in header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def scopes_of(df, by_year=True):
    s = [("all", df)]
    if by_year:
        s += [(str(y), df[df["year"] == y]) for y in sorted(df["year"].unique())]
    return s


def horizon_table(df, score, hs=HZ, by_year=True, metric="spread_resid", scale=100.0, score_values=None, label=None, min_names=fxm.MIN_NAMES):
    """{(h, scope): metric_row}, and the rendered rows for `metric`."""
    res = {}
    for h in hs:
        for name, sub in scopes_of(df, by_year):
            sv = None if score_values is None else score_values.loc[sub.index]
            if len(sub) == 0:
                continue
            res[(h, name)] = fxm.metric_row(sub, score, h, score_values=sv, min_names=min_names)
    return res


def render_metric(res, metric, hs=HZ, scopes=None, title="", scale=100.0, nd=2):
    scopes = scopes or sorted({k[1] for k in res}, key=lambda s: (s != "all", s))
    rows = []
    for h in hs:
        row = [f"{h}m"]
        for s in scopes:
            r = res.get((h, s))
            if r is None or r["excluded"]["n_dates"] == 0:
                row.append("n/a")
            else:
                row.append(fxm.triple(r, metric, scale, nd))
        rows.append(row)
    nrow = ["dates (excl)"] + [str((res.get((hs[0], s)) or {"excluded": {"n_dates": 0}})["excluded"]["n_dates"]) for s in scopes]
    return [f"**{title}**", ""] + md(["horizon"] + list(scopes), rows) + [""]


def ranked_within(df, col, by=("date", "family")):
    return df.groupby(list(by))[col].transform(fxm.rank_nan)


# ---- F1, F2 -------------------------------------------------------------------------------------------------------------------------------------

def f1(df, out):
    res = horizon_table(df, "vp")
    L = ["# F1. Horizons: 3, 6, 12, 18, 24, 36 months", "",
         "Score: the registered median IV / price. Universe: valued names with market cap >= $300M, month-end dates 2020-01 .. 2024-12. Each cell: excluded / -100% / last close. A horizon is formed only where the "
         "outcome date is on or before 2026-10-06 (prices to 2026-10-06), so later valuation years drop out of the long horizons.", ""]
    L += render_metric(res, "spread_resid", title="B2-style residual quintile spread (industry-neutral, after the five yardsticks), percentage points of excess return")
    L += render_metric(res, "spread_raw", title="Raw industry-neutral top-minus-bottom quintile spread, percentage points")
    L += render_metric(res, "ic", title="Rank IC x 100 (Spearman, per date, mean over dates)")
    L += render_metric(res, "ic_resid", title="Rank IC x 100 of the residual after the five yardsticks")
    coefs = {}
    rows = []
    for h in HZ:
        row = [f"{h}m"]
        for b in BOUNDS:
            c = fxm.pooled_coef(df, df["vp"], h, b, Y5)
            coefs[(h, b)] = c
            row.append("n/a" if c is None else f"{c['beta']:+.4f} (t {c['t']:+.1f})")
        rows.append(row)
    L += ["**B1-style pooled coefficient on the engine's rank (date and industry effects, five yardsticks; date-clustered t-statistic, 12-month-style CR1 not bootstrap)**", ""] + md(["horizon"] + [fxm.BLABEL[b] for b in BOUNDS], rows) + [""]
    out["F1"] = {"metrics": {f"{h}|{s}": v for (h, s), v in res.items()}, "pooled": {f"{h}|{b}": v for (h, b), v in coefs.items()}}
    return L


def f2(df, out):
    L = ["# F2. By family (operating, financial, commodity)", "", "Same metrics as F1 per family. Ranks, yardstick residuals and industry-neutral quintiles are formed inside the family subset on each date.", ""]
    res_all = {}
    for fam in FAMILIES:
        sub = df[df["family"] == fam]
        res = horizon_table(sub, "vp", by_year=True)
        res_all[fam] = res
        npd = sub.groupby("date").size()
        L += [f"## {fam} (median names per date {int(npd.median()) if len(npd) else 0}, name-dates {len(sub)})", ""]
        L += render_metric(res, "spread_resid", title=f"{fam}: B2-style residual quintile spread, pp")
        L += render_metric(res, "ic", title=f"{fam}: rank IC x 100")
        L += render_metric(res, "spread_raw", title=f"{fam}: raw neutral spread, pp")
        rows = []
        for h in HZ:
            row = [f"{h}m"]
            for b in BOUNDS:
                c = fxm.pooled_coef(sub, sub["vp"], h, b, Y5)
                row.append("n/a" if c is None else f"{c['beta']:+.4f} (t {c['t']:+.1f})")
            rows.append(row)
        L += [f"**{fam}: pooled coefficient (t, date-clustered)**", ""] + md(["horizon"] + [fxm.BLABEL[b] for b in BOUNDS], rows) + [""]
    out["F2"] = {fam: {f"{h}|{s}": v for (h, s), v in res.items()} for fam, res in res_all.items()}
    return L


# ---- F7 (and the generic score comparison) ------------------------------------------------------------------------------------------------------------

def score_compare(df, scores, hs=(6, 12, 24, 36), title="", by_year=False, metrics=("spread_resid", "ic")):
    out = {}
    L = []
    for h in hs:
        rows_s, rows_i = [], []
        for lab, col in scores:
            sub = df[df[col].notna()] if col in df else df.iloc[0:0]
            r = fxm.metric_row(sub, col, h)
            out[(lab, h)] = r
            rows_s.append([lab, fxm.triple(r, "spread_resid"), fxm.triple(r, "ic"), fxm.triple(r, "spread_raw"), r["excluded"]["n_dates"], r["excluded"]["n_obs"]])
        L += [f"**{title} h = {h} months**", ""] + md(["score", "residual spread pp (excl / -100% / last)", "IC x 100", "raw neutral spread pp", "dates", "name-dates (excl)"], rows_s) + [""]
    return L, out


def f7(df, out):
    scores = [("median of the draws (registered)", "vp"), ("mean of the draws", "vp_mean"), ("P25", "vp_p25"), ("P75", "vp_p75"), ("P10", "vp_p10"), ("P90", "vp_p90"),
              ("share of draws above the price", "pgt"), ("point value at the P50 inputs", "vp_pt")]
    L = ["# F7. Summary statistic of the IV draw distribution as the ranking variable", "",
         "Same names, same dates, only the ranking statistic changes (value per share over the 2,000 draws, divided by the price; ranks are by date).", ""]
    L2, res = score_compare(df, scores, title="F7")
    out["F7"] = {f"{k[0]}|{k[1]}": v for k, v in res.items()}
    return L + L2


# ---- F9 ------------------------------------------------------------------------------------------------------------------------------------------

def f9(df, out):
    df = df.copy()
    df["vp_fam"] = ranked_within(df, "vp", ("date", "family"))
    df["vp_ind"] = ranked_within(df, "vp", ("date", "industry"))
    L = ["# F9. Within-family ranking before pooling", "",
         "`vp_fam` is the percentile rank of IV / price among the names of the SAME FAMILY on the date (pooled afterwards); `vp_ind` is the rank inside the Damodaran industry. B1 and B2 already use industry effects "
         "(finer than families), so the registered figures are the comparison.", ""]
    scores = [("IV/price pooled rank (registered)", "vp"), ("rank within family, then pooled", "vp_fam"), ("rank within industry, then pooled", "vp_ind")]
    L2, res = score_compare(df, scores, title="F9")
    rows = []
    for lab, col in scores:
        row = [lab]
        for h in (12,):
            for b in BOUNDS:
                c = fxm.pooled_coef(df, df[col], h, b, Y5)
                row.append("n/a" if c is None else f"{c['beta']:+.4f} (t {c['t']:+.1f})")
        rows.append(row)
    L3 = ["**Pooled coefficient, 12 months (date and industry effects)**", ""] + md(["score"] + [fxm.BLABEL[b] for b in BOUNDS], rows) + [""]
    out["F9"] = {f"{k[0]}|{k[1]}": v for k, v in res.items()}
    return L + L2 + L3
