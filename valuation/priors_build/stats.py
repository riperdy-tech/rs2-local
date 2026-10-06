"""stats.py - the statistics of one vintage, from its observation table.  Pure functions on DataFrames (tested on synthetic panels).

Conventions (every one a stated convention, none tuned to a result):
  * quantiles: type 7 (linear interpolation) at P5, P10, P25, P50, P75, P90, P95, with n.
  * a cell with n < MIN_N (50) is merged with its ADJACENT neighbour (`merge_1d`), and flagged `merged`.
  * bucket edges are fixed numbers (SIZE_EDGES, GROWTH_EDGES, ...); terciles / quintiles of the state are measured within the vintage (point in time).
  * an observation counts in a table only when every figure the table needs is defined; nothing is imputed.
  * the unit of observation is a company-year; neighbouring years of one company overlap, so n is not an independent-sample size (stated in the report).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .config import MAX_K, MIN_N, QUANTILE_LEVELS

SIZE_EDGES = [50e6, 250e6, 1e9, 5e9, 20e9]                 # revenue, USD: <50M, 50-250M, 250M-1B, 1-5B, 5-20B, >20B
GROWTH_EDGES = [-0.10, 0.0, 0.05, 0.10, 0.20, 0.40]          # <-10%, -10..0, 0..5, 5..10, 10..20, 20..40, >40%
FCF_GROWTH_EDGES = [0.0, 0.10, 0.25]                         # realised next-year growth for the EV/FCFF reference
ROTE_EDGES = [0.0, 0.05, 0.10, 0.15]                         # return on tangible equity bins for P/TBV
A2_MIN_DEV = 0.005                                           # A2: a margin deviation of less than 0.5 points has no direction to measure
CURVE_REF_YEAR = 5                                           # the year at which a curve input is positioned (Muse: schema.CURVE_REF_YEAR)
RATIO_KS = tuple(range(1, 8))                                # A2 horizon k = 1..7
FAMILIES = ("operating", "commodity", "financial")
SANE_MARGIN = 1.0                                            # |margin| <= 100% for the weight fit (the A2 tables keep the rest, flagged)


def qdict(values, levels=QUANTILE_LEVELS) -> dict:
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    out = {"n": int(a.size)}
    if a.size == 0:
        return out
    qs = np.quantile(a, levels, method="linear")
    for p, q in zip(levels, qs):
        out[f"p{p * 100:g}"] = float(q)
    return out


def bucket(x, edges) -> np.ndarray:
    """Bucket index of each x: bucket i holds edges[i-1] <= x < edges[i] (0 below the first edge, len(edges) at or above the last).  NaN -> -1."""
    a = np.asarray(x, dtype=float)
    b = np.searchsorted(np.asarray(edges, dtype=float), a, side="right")
    b = np.where(np.isfinite(a), b, -1)
    return b


def merge_1d(counts: Sequence[int], min_n: int = MIN_N) -> List[Tuple[int, int]]:
    """Merge ordered buckets until every group has at least `min_n` observations (or one group is left).  Rule: the smallest group (the lower index on a
    tie) merges with its ADJACENT neighbour that has fewer observations (the lower index on a tie).  Returns inclusive (lo, hi) index ranges."""
    groups = [[i, i, int(c)] for i, c in enumerate(counts)]
    while len(groups) > 1:
        j = min(range(len(groups)), key=lambda g: (groups[g][2], g))
        if groups[j][2] >= min_n:
            break
        nb = [x for x in (j - 1, j + 1) if 0 <= x < len(groups)]
        k = min(nb, key=lambda x: (groups[x][2], x))
        lo, hi = (k, j) if k < j else (j, k)
        groups[lo] = [groups[lo][0], groups[hi][1], groups[lo][2] + groups[hi][2]]
        del groups[hi]
    return [(g[0], g[1]) for g in groups]


def grid_cells(rows: np.ndarray, cols: np.ndarray, values: np.ndarray, nrow: int, ncol: int, min_n: int = MIN_N) -> List[dict]:
    """A two-way table of quantiles: `rows` x `cols` bucket indices (-1 = not defined, dropped), `values` the measure.  Row groups are merged by `merge_1d` on
    the row totals, then the column groups inside each row group.  Each cell: row range, column range, n, quantiles, merged flags."""
    ok = (rows >= 0) & (cols >= 0) & np.isfinite(values)
    rows, cols, values = rows[ok], cols[ok], values[ok]
    row_tot = [int((rows == i).sum()) for i in range(nrow)]
    cells = []
    for (r0, r1) in merge_1d(row_tot, min_n):
        inrow = (rows >= r0) & (rows <= r1)
        col_tot = [int(((cols == j) & inrow).sum()) for j in range(ncol)]
        for (c0, c1) in merge_1d(col_tot, min_n):
            sel = inrow & (cols >= c0) & (cols <= c1)
            q = qdict(values[sel])
            cells.append({"row": [r0, r1], "col": [c0, c1], **q, "merged_rows": r1 > r0, "merged_cols": c1 > c0,
                          "thin": q["n"] < min_n})
    return cells


def find_cell(cells: List[dict], r: int, c: int) -> Optional[dict]:
    for cell in cells:
        if cell["row"][0] <= r <= cell["row"][1] and cell["col"][0] <= c <= cell["col"][1]:
            return cell
    return None


# ---- the working frame ------------------------------------------------------------------------------------------------------------------------

def prep_frame(df: pd.DataFrame, status: Optional[pd.DataFrame], cut_iso: str) -> pd.DataFrame:
    """Derived columns: base year, the buckets, year-alone growth paths g_1..g_10 (revenue) and tg_1..tg_10 (tangible book), the CAGRs, the
    survivorship labels (hindsight, reporting only)."""
    d = df.copy()
    text = {"cik", "fye", "own_filed", "form", "currency", "family", "family_basis", "sic", "obs_date"}
    for c in d.columns:
        if c not in text and not c.startswith("filed_") and d[c].dtype == object:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["year"] = d["fye"].str.slice(0, 4).astype(int)
    d["usd"] = d["currency"].eq("USD")
    rev = d["rev"].where(d["rev"] > 0)
    d["size_b"] = np.where(d["usd"] & rev.notna(), bucket(rev.fillna(0.0), SIZE_EDGES), -1)
    d["g3_b"] = bucket(d["g3"], GROWTH_EDGES)
    d["glat_b"] = bucket(d["g_latest"], GROWTH_EDGES)
    d["tg3_b"] = bucket(d["tbv_g3"], GROWTH_EDGES)
    d["tglat_b"] = bucket(d["tbv_g_latest"], GROWTH_EDGES)
    prev = rev
    tprev = d["tbv"].where(d["tbv"] > 0)
    for k in range(1, MAX_K + 1):
        rk = d[f"rev_{k}"].where(d[f"rev_{k}"] > 0)
        d[f"g_{k}"] = rk / prev - 1.0
        prev = rk
        tk = d[f"tbv_{k}"].where(d[f"tbv_{k}"] > 0)
        d[f"tg_{k}"] = tk / tprev - 1.0
        tprev = tk
    d["cagr5"] = (d["rev_5"].where(d["rev_5"] > 0) / rev) ** 0.2 - 1.0
    d["cagr10"] = (d["rev_10"].where(d["rev_10"] > 0) / rev) ** 0.1 - 1.0
    d["y1"], d["ty1"] = d["g_1"], d["tg_1"]
    d["g_base"] = d["g3"].where(d["g3"].notna(), d["g_latest"])          # the mechanical baseline's growth: trailing 3-year CAGR, else the latest year
    d["tg_base"] = d["tbv_g3"].where(d["tbv_g3"].notna(), d["tbv_g_latest"])
    if status is not None:
        s = status.set_index("cik")
        d["ceased"] = d["cik"].map(s["ceased"]).fillna(False).astype(bool)
        d["last_periodic"] = d["cik"].map(s["last_periodic_filed"])
        d["ceased_before_cut"] = d["last_periodic"].fillna("0000") < cut_iso
        cutm = (pd.Timestamp(cut_iso) - pd.DateOffset(months=18)).date().isoformat()
        d["known_ceased_at_cut"] = d["last_periodic"].fillna("0000") < cutm
    else:
        d["ceased"] = False
        d["last_periodic"] = None
        d["ceased_before_cut"] = False
        d["known_ceased_at_cut"] = False
    return d


def terciles(x: pd.Series) -> List[float]:
    a = x.dropna().to_numpy(dtype=float)
    return [float(np.quantile(a, 1 / 3)), float(np.quantile(a, 2 / 3))] if a.size >= 3 else []


def quintiles(x: pd.Series) -> List[float]:
    a = x.dropna().to_numpy(dtype=float)
    return [float(np.quantile(a, q)) for q in (0.2, 0.4, 0.6, 0.8)] if a.size >= 5 else []


def band(x, cuts: List[float]) -> np.ndarray:
    """Band index 0..len(cuts) of each x (a value equal to a cut goes to the upper band); NaN -> -1."""
    return bucket(x, cuts) if cuts else np.where(np.isfinite(np.asarray(x, dtype=float)), 0, -1)


# ---- growth: g1 cells, decay curves ---------------------------------------------------------------------------------------------------------

def g1_tables(d: pd.DataFrame) -> dict:
    """Next-year growth (revenue; tangible book for financials) by size and growth delivered.  Two growth bases: the trailing 3-year CAGR and the latest
    year.  Each cell carries the quantiles and the mechanical baseline's error against the cell's own median (mean absolute error of each)."""
    out = {}
    for fam in FAMILIES:
        sub = d[d["family"].eq(fam)]
        yv, base_col, gcol = ("ty1", "tg_base", {"g3": "tg3_b", "latest": "tglat_b"}) if fam == "financial" else ("y1", "g_base", {"g3": "g3_b", "latest": "glat_b"})
        out[fam] = {}
        for basis, bcol in gcol.items():
            s = sub[sub["size_b"] >= 0]
            gv = s["tbv_g3" if (fam == "financial" and basis == "g3") else ("tbv_g_latest" if fam == "financial" else ("g3" if basis == "g3" else "g_latest"))]
            cells = grid_cells(s["size_b"].to_numpy(), s[bcol].to_numpy(), s[yv].to_numpy(), len(SIZE_EDGES) + 1, len(GROWTH_EDGES) + 1)
            blcol = ("tbv_g3" if basis == "g3" else "tbv_g_latest") if fam == "financial" else ("g3" if basis == "g3" else "g_latest")

            def attach(cells_, frame, use_size):
                for cell in cells_:
                    sel = (frame[bcol] >= cell["col"][0]) & (frame[bcol] <= cell["col"][1]) & frame[yv].notna()
                    if use_size:
                        sel &= (frame["size_b"] >= cell["row"][0]) & (frame["size_b"] <= cell["row"][1])
                    y = frame.loc[sel, yv].to_numpy()
                    bl = frame.loc[sel, blcol].to_numpy()
                    ok = np.isfinite(bl)
                    cell["baseline_growth_median"] = float(np.median(bl[ok])) if ok.any() else None
                    cell["baseline_mae"] = float(np.mean(np.abs(y[ok] - bl[ok]))) if ok.any() else None
                    cell["baseline_medae"] = float(np.median(np.abs(y[ok] - bl[ok]))) if ok.any() else None
                    cell["cell_median_mae"] = float(np.mean(np.abs(y - cell["p50"]))) if len(y) else None
                    cell["cell_median_medae"] = float(np.median(np.abs(y - cell["p50"]))) if len(y) else None

            attach(cells, s, True)
            allv = sub[yv].to_numpy(dtype=float)
            pooled = grid_cells(np.zeros(len(sub), dtype=int), sub[bcol].to_numpy(), allv, 1, len(GROWTH_EDGES) + 1)
            attach(pooled, sub, False)
            out[fam][basis] = {"cells": cells, "n": int(sum(c["n"] for c in cells)), "size_pooled_cells": pooled, "all": qdict(allv)}
    return out


def decay_tables(d: pd.DataFrame, min_n: int = MIN_N) -> dict:
    """The curve of year-by-year growth t+1..t+10 by growth-delivered bucket: median ratio (g_k - T) / (g_1 - T), T the terminal reference.
    T: the pooled median year-alone growth at the largest horizon with at least 500 observations (stated in the table).  The per-observation ratio is
    taken where |g_1 - T| >= 0.02 (the count of those left out is reported); the ratio of medians is reported beside it.  The raw paths (median,
    P25, P75 of g_k) are kept per bucket.  Buckets with fewer than min_n observations at k=1 are merged by `merge_1d`."""
    out = {}
    for fam in FAMILIES:
        sub = d[d["family"].eq(fam)]
        pre, gb, gcol = ("tg", "tg3_b", "tg3") if fam == "financial" else ("g", "g3_b", "g3")
        gk = lambda k: sub[f"{pre}_{k}"]
        # terminal reference
        ref_k, T = None, None
        for k in range(MAX_K, 0, -1):
            if gk(k).notna().sum() >= 500:
                ref_k, T = k, float(gk(k).median())
                break
        if T is None:
            out[fam] = {"terminal_reference": None, "buckets": []}
            continue
        has1 = sub[f"{pre}_1"].notna() & (sub[gb] >= 0)
        counts = [int(((sub[gb] == i) & has1).sum()) for i in range(len(GROWTH_EDGES) + 1)]
        buckets = []
        for (lo, hi) in merge_1d(counts, min_n):
            s = sub[(sub[gb] >= lo) & (sub[gb] <= hi) & has1]
            g1 = s[f"{pre}_1"].to_numpy()
            keep = np.abs(g1 - T) >= 0.02
            ks = []
            for k in range(1, MAX_K + 1):
                v = s[f"{pre}_{k}"].to_numpy()
                ok = np.isfinite(v)
                n_k = int(ok.sum())
                row = {"k": k, "n": n_k}
                if n_k:
                    row["raw_p25"], row["raw_p50"], row["raw_p75"] = (float(np.quantile(v[ok], q)) for q in (0.25, 0.5, 0.75))
                okr = ok & keep
                row["n_ratio"] = int(okr.sum())
                if okr.sum():
                    ratio = (v[okr] - T) / (g1[okr] - T)
                    row["ratio_median"] = float(np.median(ratio))
                    row["ratio_p25"], row["ratio_p75"] = (float(np.quantile(ratio, q)) for q in (0.25, 0.75))
                    if k <= CURVE_REF_YEAR:
                        row["ratio_q"] = qdict(ratio)
                m1 = float(np.median(g1))
                if ok.any() and abs(m1 - T) > 1e-9:
                    row["ratio_of_medians"] = (float(np.median(v[ok])) - T) / (m1 - T)
                ks.append(row)
            buckets.append({"bucket": [lo, hi], "n_k1": int(len(s)), "excluded_small_g1_gap": int((~keep).sum()), "merged": hi > lo, "ks": ks})
        out[fam] = {"terminal_reference": {"value": T, "horizon_k": ref_k, "rule": "pooled median year-alone growth at the largest k with >= 500 obs"},
                    "buckets": buckets}
    return out


# ---- margin retention (the A2 method) ---------------------------------------------------------------------------------------------------------

def retention_table(dev: np.ndarray, med: np.ndarray, levels_k: Dict[int, np.ndarray], mask: np.ndarray) -> dict:
    """For the observations in `mask`: the median / quartiles of (level_k - med) / dev for k = 1..7, n per k.  `levels_k[k]` is the series level k years
    on (a margin, or a return on tangible equity); `dev` = level_t - med (the deviation from the company's 8-year median)."""
    out = {"n": int(mask.sum()), "ks": []}
    for k in RATIO_KS:
        v = levels_k[k]
        ok = mask & np.isfinite(v)
        row = {"k": k, "n": int(ok.sum())}
        if ok.any():
            r = (v[ok] - med[ok]) / dev[ok]
            row["median"], row["p25"], row["p75"] = (float(np.quantile(r, q)) for q in (0.5, 0.25, 0.75))
            if k <= CURVE_REF_YEAR:
                row["q"] = qdict(r)              # the whole distribution of the fraction still open, for the curve-position reference
        out["ks"].append(row)
    return out


def margin_retention(d: pd.DataFrame, cyc_cuts: List[float]) -> dict:
    """A2 on the point-in-time panel: operating and commodity companies, record rule (>= 5 defined margin years in t-7..t), |dev| >= 0.5 points.
    Bands: cyclicality-score tercile (cuts measured in this vintage) x sign of the deviation, plus every band pooled; also the share of observations
    with |margin| > 100% (kept, flagged).  The level distribution K = 5 years on is reported as the residual about the median path."""
    sub = d[d["family"].isin(["operating", "commodity"])]
    ok = sub["dev"].notna() & (sub["dev"].abs() >= A2_MIN_DEV) & sub["med8"].notna()
    s = sub[ok]
    dev, med = s["dev"].to_numpy(), s["med8"].to_numpy()
    levels = {k: s[f"m_{k}"].to_numpy(dtype=float) for k in RATIO_KS}
    cb = band(s["cyc"], cyc_cuts)
    sign = np.where(dev > 0, 1, -1)
    out = {"filter": {"record_rule_min_years": 5, "min_abs_dev": A2_MIN_DEV, "obs_with_record": int(sub["dev"].notna().sum()), "obs_used": int(len(s)),
                      "excluded_small_dev": int((sub["dev"].notna() & ~(sub["dev"].abs() >= A2_MIN_DEV)).sum()),
                      "share_abs_margin_gt_100pct": float((s["m"].abs() > 1.0).mean()) if len(s) else None},
           "cyc_cuts": cyc_cuts, "bands": {}}
    names = {0: "low", 1: "mid", 2: "high"}
    for b in range(len(cyc_cuts) + 1):
        for sg, sn in ((1, "pos"), (-1, "neg")):
            m = (cb == b) & (sign == sg)
            out["bands"][f"{names.get(b, b)}_{sn}"] = {"band": b, "sign": sg, **retention_table(dev, med, levels, m)}
        m = cb == b
        out["bands"][f"{names.get(b, b)}_all"] = {"band": b, "sign": 0, **retention_table(dev, med, levels, m)}
    for sg, sn in ((1, "pos"), (-1, "neg")):
        out["bands"][f"pooled_{sn}"] = {"band": -1, "sign": sg, **retention_table(dev, med, levels, sign == sg)}
    out["bands"]["pooled_all"] = {"band": -1, "sign": 0, **retention_table(dev, med, levels, np.ones(len(s), bool))}
    # level distribution K = 5: residual about the median-retention path of the band x sign
    K = 5
    res = {}
    for key, bd in out["bands"].items():
        if bd["sign"] == 0 or key.startswith("pooled"):
            pass
        v = levels[K]
        if bd["band"] >= 0:
            m = (cb == bd["band"]) & ((sign == bd["sign"]) if bd["sign"] != 0 else True)
        else:
            m = (sign == bd["sign"]) if bd["sign"] != 0 else np.ones(len(s), bool)
        m = m & np.isfinite(v)
        vk = [r for r in bd["ks"] if r["k"] == K][0].get("median")
        if m.sum() and vk is not None:
            e = (v[m] - med[m]) - vk * dev[m]
            res[key] = {**qdict(e), "retention_k5_used": vk, "level_dev_raw": qdict(v[m] - med[m])}
    out["residual_k5"] = res
    return out


def rote_retention(d: pd.DataFrame) -> dict:
    """The A2 method on return on tangible equity of financial companies: by sign of the deviation from the company's 8-year median ROTE."""
    s = d[d["family"].eq("financial")]
    ok = s["rote_dev"].notna() & (s["rote_dev"].abs() >= A2_MIN_DEV) & s["rote_med8"].notna()
    s = s[ok]
    dev, med = s["rote_dev"].to_numpy(), s["rote_med8"].to_numpy()
    levels = {k: s[f"rote_{k}"].to_numpy(dtype=float) for k in RATIO_KS}
    sign = np.where(dev > 0, 1, -1)
    out = {"obs_used": int(len(s)), "bands": {}}
    for sg, sn in ((1, "pos"), (-1, "neg")):
        out["bands"][sn] = {"sign": sg, **retention_table(dev, med, levels, sign == sg)}
    out["bands"]["all"] = {"sign": 0, **retention_table(dev, med, levels, np.ones(len(s), bool))}
    K = 5
    res = {}
    for sn, bd in out["bands"].items():
        m = ((sign == bd["sign"]) if bd["sign"] != 0 else np.ones(len(s), bool)) & np.isfinite(levels[K])
        vk = [r for r in bd["ks"] if r["k"] == K][0].get("median")
        if m.sum() and vk is not None:
            res[sn] = {**qdict((levels[K][m] - med[m]) - vk * dev[m]), "retention_k5_used": vk}
    out["residual_k5"] = res
    return out


# ---- return on new capital ---------------------------------------------------------------------------------------------------------------------

IC_GROWTH_FLOOR = 0.10        # RONIC is defined where invested capital grew by at least 10% of its base over the 3-year window (below that the ratio has no meaning)


def ronic_frame(d: pd.DataFrame) -> pd.DataFrame:
    """ronic3 = (NOPAT_{t+3} - NOPAT_t) / (IC_{t+3} - IC_t) on the observations with IC_t > 0 and IC growing by at least IC_GROWTH_FLOOR of IC_t; `ronic3_any` = the
    same without the floor where the capital change is positive (reported beside it)."""
    dd = d["ic_3"] - d["ic"]
    dn = d["nopat_3"] - d["nopat"]
    pos = d["ic"] > 0
    d = d.copy()
    d["ronic3_any"] = (dn / dd).where(pos & (dd > 0))
    d["ronic3"] = (dn / dd).where(pos & (dd >= IC_GROWTH_FLOOR * d["ic"]))
    return d


def ronic_tables(d: pd.DataFrame, roic_cuts: List[float]) -> dict:
    d = ronic_frame(d)
    out = {"ic_growth_floor": IC_GROWTH_FLOOR, "roic_cuts": roic_cuts, "families": {}}
    names = {0: "low", 1: "mid", 2: "high"}
    for fam in ("operating", "commodity"):
        s = d[d["family"].eq(fam)]
        have = s["nopat"].notna() & s["ic"].notna() & s["nopat_3"].notna() & s["ic_3"].notna()
        fam_out = {"obs_with_window": int(have.sum()), "ronic_defined": int(s["ronic3"].notna().sum()),
                   "ronic_unfloored_defined": int(s["ronic3_any"].notna().sum()), "unfloored": qdict(s["ronic3_any"]), "floored_all": qdict(s["ronic3"]),
                   "bands": {}}
        rb = band(s["roic"], roic_cuts)
        for b in range(len(roic_cuts) + 1):
            m = rb == b
            fam_out["bands"][names.get(b, str(b))] = {"band": b, **qdict(s.loc[m, "ronic3"])}
        out["families"][fam] = fam_out
    return out


def excess_return_fade(d: pd.DataFrame, level_col: str, k_col_fmt: str, fam_mask: pd.Series, ref: float) -> dict:
    """The retention of a return's excess over a reference level `ref` (the population median of that return in the vintage): median of
    (r_{t+k} - ref) / (r_t - ref), k = 1..7, where |r_t - ref| >= 0.02.  A MEASURED PROXY for the fade of the return on new capital toward the cost of
    capital (the priors do not know the cost of capital)."""
    s = d[fam_mask]
    r0 = s[level_col].to_numpy(dtype=float)
    keep = np.isfinite(r0) & (np.abs(r0 - ref) >= 0.02)
    out = {"reference": ref, "n_base": int(keep.sum()), "ks": []}
    for k in RATIO_KS:
        v = s[k_col_fmt.format(k=k)].to_numpy(dtype=float)
        ok = keep & np.isfinite(v)
        row = {"k": k, "n": int(ok.sum())}
        if ok.any():
            r = (v[ok] - ref) / (r0[ok] - ref)
            row["median"], row["p25"], row["p75"] = (float(np.quantile(r, q)) for q in (0.5, 0.25, 0.75))
        out["ks"].append(row)
    return out


def add_roic_k(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    for k in range(1, MAX_K + 1):
        d[f"roic_{k}"] = (d[f"nopat_{k}"] / d[f"ic_{k}"]).where(d[f"ic_{k}"] > 0)
    return d


# ---- terminal growth and the persistence of shrinking companies -------------------------------------------------------------------------------------

def terminal_tables(d: pd.DataFrame, min_complete: int = 200) -> dict:
    """Long-horizon revenue growth.  K_eff = the longest horizon (<= 10) with at least `min_complete` complete observations in the vintage (K = 10 where the
    panel is old enough).  Variants of the K-year CAGR, each with n:
      complete      : every observation with rev_K filed (companies that stopped filing before K are out by construction),
      with_delisted : complete + observations of companies KNOWN at the cut to have stopped filing (last periodic filing more than 18 months before the cut)
                      that lack rev_K, at their last available horizon h >= 3 (a proxy of the business, not of the shareholders' outcome),
      without_ceased: complete, minus companies that later stopped filing (hindsight label, reporting only).
    By family; and for shrinking companies (trailing 8-year slope of ln revenue < 0) the forward CAGR at k = 3, 5, 7, 10."""
    n_by_k = {k: int(d[f"rev_{k}"].where(d[f"rev_{k}"] > 0).notna().sum()) for k in range(1, MAX_K + 1)}
    K = max([k for k in range(1, MAX_K + 1) if n_by_k[k] >= min_complete] or [0])
    out = {"K_eff": K, "complete_obs_by_k": n_by_k, "families": {}, "shrinking": {}}
    if K == 0:
        return out
    rev = d["rev"].where(d["rev"] > 0)

    ck = (d[f"rev_{K}"].where(d[f"rev_{K}"] > 0) / rev) ** (1.0 / K) - 1.0
    # truncated horizon for known-ceased companies
    h = d["n_ahead"].clip(upper=K)
    last_rev = np.full(len(d), np.nan)
    for hh in range(3, K + 1):
        sel = (h == hh).to_numpy()
        last_rev[sel] = d.loc[sel, f"rev_{hh}"].where(d.loc[sel, f"rev_{hh}"] > 0).to_numpy()
    trunc = (last_rev / rev.to_numpy()) ** (1.0 / h.to_numpy().clip(min=1)) - 1.0
    trunc = pd.Series(trunc, index=d.index).where(d["known_ceased_at_cut"] & ck.isna() & (h >= 3))
    fam_all = d["family"].isin(FAMILIES)
    strata = {"all": pd.Series(True, index=d.index), "shrinking": d["trend8"] < 0, "not_shrinking": d["trend8"] >= 0}
    for fam in FAMILIES + ("all",):
        base = fam_all if fam == "all" else d["family"].eq(fam)
        out["families"][fam] = {}
        for sname, smask in strata.items():
            m = base & smask
            comp = ck[m]
            wd = pd.concat([comp, trunc[m]]).dropna()
            out["families"][fam][sname] = {"complete": qdict(comp), "with_delisted": qdict(wd),
                                           "without_ceased": qdict(comp[~d.loc[comp.index, "ceased"]]),
                                           "share_of_complete_from_companies_that_later_ceased":
                                               float(d.loc[comp.dropna().index, "ceased"].mean()) if comp.notna().any() else None,
                                           "truncated_added": int(trunc[m].notna().sum())}
    sh = d["trend8"] < 0
    for fam in ("operating", "commodity"):
        m = d["family"].eq(fam) & sh
        row = {"n_shrinking_obs": int(m.sum()), "ks": {}}
        for k in (3, 5, 7, 10):
            if k > MAX_K:
                continue
            v = (d.loc[m, f"rev_{k}"].where(d.loc[m, f"rev_{k}"] > 0) / rev[m]) ** (1.0 / k) - 1.0
            row["ks"][str(k)] = {"complete": qdict(v), "without_ceased": qdict(v[~d.loc[v.index, "ceased"]])}
        out["shrinking"][fam] = row
    return out


# ---- the engine references from prices ----------------------------------------------------------------------------------------------------------

def ev_fcf_tables(d: pd.DataFrame, roic_cuts: List[float]) -> dict:
    """EV / FCFF_1 by realised next-year growth and return-on-capital tercile (operating and commodity, observations with a price at the observation date
    and a positive realised FCFF in year t+1).  EV = market cap at the observation date less the equity bridge items of the base year (the engine's own
    `equity_bridge` inverted); `ev` and `fcff1` columns are supplied by the caller."""
    s = d[d["family"].isin(["operating", "commodity"]) & d["ev"].notna()]
    out = {"obs_with_price_and_state": int(len(s)), "fcff1_not_positive": int((s["fcff1"] <= 0).sum()), "ev_not_positive": int((s["ev"] <= 0).sum())}
    s = s[(s["fcff1"] > 0) & (s["ev"] > 0)]
    mult = (s["ev"] / s["fcff1"]).to_numpy()
    gb = bucket(s["g_1"], FCF_GROWTH_EDGES)
    rb = band(s["roic"], roic_cuts)
    cells = grid_cells(gb, rb, mult, len(FCF_GROWTH_EDGES) + 1, len(roic_cuts) + 1)
    out.update({"edges_growth": FCF_GROWTH_EDGES, "roic_cuts": roic_cuts, "cells": cells, "pooled": qdict(mult), "n": int(len(s))})
    return out


def ptbv_tables(d: pd.DataFrame) -> dict:
    """Price / tangible book against ROTE (financials; price at the observation date, tangible book of the base year)."""
    s = d[d["family"].eq("financial") & d["mcap"].notna() & (d["tbv"] > 0) & d["rote"].notna()]
    pt = (s["mcap"] / s["tbv"]).to_numpy()
    rb = bucket(s["rote"], ROTE_EDGES)
    counts = [int((rb == i).sum()) for i in range(len(ROTE_EDGES) + 1)]
    groups = []
    for (lo, hi) in merge_1d(counts):
        m = (rb >= lo) & (rb <= hi)
        groups.append({"bucket": [lo, hi], **qdict(pt[m]), "rote_median": float(np.median(s["rote"].to_numpy()[m])) if m.any() else None,
                       "merged": hi > lo})
    return {"edges": ROTE_EDGES, "groups": groups, "n": int(len(s))}


# ---- the correlation of the three judgment inputs -------------------------------------------------------------------------------------------------

def spearman(a: np.ndarray, b: np.ndarray) -> Tuple[Optional[float], int]:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 30:
        return None, int(ok.sum())
    ra = pd.Series(a[ok]).rank().to_numpy()
    rb = pd.Series(b[ok]).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1]), int(ok.sum())


def gaussian_copula_r(rs: float) -> float:
    """The correlation of a Gaussian copula that reproduces a Spearman rank correlation: 2 sin(pi rs / 6)."""
    return 2.0 * math.sin(math.pi * rs / 6.0)


def nearest_psd(mat: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Clip negative eigenvalues of a correlation matrix and rescale to unit diagonal; True when a change was needed."""
    w, v = np.linalg.eigh(mat)
    if w.min() >= 1e-8:
        return mat, False
    w = np.clip(w, 1e-8, None)
    m = (v * w) @ v.T
    dg = np.sqrt(np.diag(m))
    return m / np.outer(dg, dg), True


def correlation_tables(d: pd.DataFrame) -> dict:
    d = ronic_frame(d)
    out = {}
    for fam in ("operating", "commodity"):
        s = d[d["family"].eq(fam)]
        var = {"g1": s["y1"].to_numpy(dtype=float), "margin_target": (s["m_3"] - s["m"]).to_numpy(dtype=float), "ronic": s["ronic3"].to_numpy(dtype=float)}
        names = ["g1", "margin_target", "ronic"]
        mat = np.eye(3)
        pairs = {}
        for i in range(3):
            for j in range(i + 1, 3):
                rs, n = spearman(var[names[i]], var[names[j]])
                r = None if rs is None else gaussian_copula_r(rs)
                pairs[f"{names[i]}|{names[j]}"] = {"spearman": rs, "copula_r": r, "n": n}
                if r is not None:
                    mat[i, j] = mat[j, i] = r
        m2, fixed = nearest_psd(mat)
        out[fam] = {"pairs": pairs, "psd_adjusted": fixed, "matrix": m2.tolist(), "names": names,
                    "definitions": {"g1": "revenue growth t->t+1", "margin_target": "operating margin change t -> t+3", "ronic": "3-year RONIC (floored definition)"}}
    s = d[d["family"].eq("financial")]
    rs, n = spearman(s["ty1"].to_numpy(dtype=float), (s["rote_3"] - s["rote"]).to_numpy(dtype=float))
    out["financial"] = {"pairs": {"g1|rote_target": {"spearman": rs, "copula_r": None if rs is None else gaussian_copula_r(rs), "n": n}},
                        "definitions": {"g1": "tangible-book growth t->t+1", "rote_target": "ROTE change t -> t+3"}}
    return out


# ---- the cyclicality weights --------------------------------------------------------------------------------------------------------------------

def nnls_small(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Non-negative least squares for a handful of columns: the best of all active sets (2^p), each solved by ordinary least squares and kept only if
    it is non-negative.  Exact, deterministic, no dependency."""
    p = X.shape[1]
    best, best_sse = np.zeros(p), float(np.sum(y ** 2))
    import itertools
    for r in range(1, p + 1):
        for S in itertools.combinations(range(p), r):
            cols = list(S)
            w, *_ = np.linalg.lstsq(X[:, cols], y, rcond=None)
            if (w < 0).any():
                continue
            full = np.zeros(p)
            full[cols] = w
            sse = float(np.sum((y - X @ full) ** 2))
            if sse < best_sse - 1e-15:
                best, best_sse = full, sse
    return best


COMPONENTS = ("c_mv", "c_rf", "c_ac", "c_rc")


R_CLIP = (-1.0, 2.0)          # the per-observation reversion fraction is winsorized to [-1, 2]: at most a doubling away from the median, at most a full overshoot


def weight_frame(d: pd.DataFrame, max_year: int, ks=(1, 2, 3, 4, 5)) -> pd.DataFrame:
    """Rows for the weight fit: operating and commodity observations with the four components, the record rule, |dev| >= A2_MIN_DEV, base year and the
    outcome year <= `max_year`.  One row per (observation, k): r = clip((dev - (m_k - med8)) / dev, R_CLIP), the fraction of the deviation that reverted
    k years on (A2's ratio is 1 - r); r is what a score s = sum w_i c_i is asked to predict.  The squared error of the ratio is dominated by a few
    enormous deviations in margin points, which is why the loss is taken on the winsorized fraction, not on margin points."""
    s = d[d["family"].isin(["operating", "commodity"]) & d["cyc"].notna() & d["dev"].notna() & (d["dev"].abs() >= A2_MIN_DEV) & (d["year"] <= max_year)]
    rows = []
    for k in ks:
        mk = s[f"m_{k}"]
        ok = mk.notna() & ((s["year"] + k) <= max_year)
        t = s[ok]
        r = ((t["dev"] - (t[f"m_{k}"] - t["med8"])) / t["dev"]).clip(*R_CLIP)
        rows.append(pd.DataFrame({"cik": t["cik"].to_numpy(), "year": t["year"].to_numpy(), "k": k, "dev": t["dev"].to_numpy(), "y": r.to_numpy(),
                                  **{c: t[c].to_numpy() for c in COMPONENTS}}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def fit_weights(w: pd.DataFrame) -> dict:
    """NNLS weights of the four components (no intercept), the equal-weight baseline's single scale, and the constant-reversion baseline."""
    X = w[list(COMPONENTS)].to_numpy()
    y = w["y"].to_numpy()
    wt = nnls_small(X, y)
    mc = X.mean(axis=1)
    den = float(np.sum(mc ** 2))
    return {"weights": wt.tolist(), "equal_scale": float(np.sum(mc * y) / den) if den > 0 else 0.0, "constant": float(np.mean(y))}


def predict_sse(w: pd.DataFrame, fit: dict) -> Tuple[float, float, float, float]:
    """(sse of the NNLS weights, of the scaled equal weights, of the constant reversion, of no reversion) on the rows of `w`."""
    X = w[list(COMPONENTS)].to_numpy()
    y = w["y"].to_numpy()
    mc = X.mean(axis=1)
    return (float(np.sum((y - X @ np.array(fit["weights"])) ** 2)), float(np.sum((y - fit["equal_scale"] * mc) ** 2)),
            float(np.sum((y - fit["constant"]) ** 2)), float(np.sum(y ** 2)))


def cyc_weight_study(d: pd.DataFrame, cut_year: int, dev_last: int) -> dict:
    """The fit and its out-of-sample check.  Data: observations whose base year and outcome years are <= min(vintage year, development end).  Cross-fitting
    by base year: the rows of year y are predicted by a fit on the rows of every OTHER year, leaving out every company that appears in year y (a
    company's margins are shared by its overlapping windows; the held-out year's common shock is out too).  Adopt the fitted weights only if the
    cross-fitted error of the fitted weights is below the scaled equal weights' error."""
    max_year = min(cut_year, dev_last)
    w = weight_frame(d, max_year)
    out = {"max_year": max_year, "rows": int(len(w)), "obs": int(len(w[w["k"] == 1])) if len(w) else 0, "adopted": False, "weights": [0.25] * 4,
           "equal_scale": None, "fitted_weights": None, "loss": "squared error of the winsorized reversion fraction (clip -1..2), k = 1..5 stacked",
           "cross_fit_rule": "leave one base year out, and every company present in that year out of the training rows"}
    if len(w) < 200 or w["year"].nunique() < 4:
        out["reason"] = "too few rows or years for a fit"
        return out
    fit = fit_weights(w)
    out["fitted_weights"], out["equal_scale"], out["constant_reversion"] = fit["weights"], fit["equal_scale"], fit["constant"]
    names = ("nnls", "equal_scaled", "constant", "no_reversion")
    out["in_sample_mse"] = {k: v / len(w) for k, v in zip(names, predict_sse(w, fit))}
    sse = np.zeros(4)
    used = 0
    folds = 0
    for y in sorted(w["year"].unique()):
        test = w[w["year"] == y]
        train = w[(w["year"] != y) & ~w["cik"].isin(set(test["cik"]))]
        if len(train) < 100 or train["year"].nunique() < 2:
            continue
        f = fit_weights(train)
        sse += np.array(predict_sse(test, f))
        used += len(test)
        folds += 1
    out["cross_fit"] = {"folds": folds, "rows_scored": used, "mse": ({k: float(v / used) for k, v in zip(names, sse)} if used else None)}
    if used:
        out["adopted"] = bool(sse[0] < sse[1])
        out["reason"] = ("cross-fitted error of the fitted weights is lower than the scaled equal weights'" if out["adopted"] else
                         "cross-fitted error of the fitted weights is not lower than the scaled equal weights': equal weights kept")
        if out["adopted"]:
            tot = sum(fit["weights"])
            out["weights"] = [x / tot for x in fit["weights"]] if tot > 0 else [0.25] * 4
            out["weights_scale"] = tot
    else:
        out["reason"] = "no fold had enough training rows"
    return out


# ---- normalization by score, population state, survivorship, mechanical baseline -----------------------------------------------------------------------

def normalization_bands(d: pd.DataFrame, cuts5: List[float]) -> dict:
    """The margin-retention curve as a function of the cyclicality score: median (A2) ratio at k = 1..7 by score quintile (cuts measured in the vintage),
    signs pooled, and the median score of each quintile (the curve is interpolated between quintile medians)."""
    sub = d[d["family"].isin(["operating", "commodity"])]
    ok = sub["dev"].notna() & (sub["dev"].abs() >= A2_MIN_DEV) & sub["med8"].notna() & sub["cyc"].notna()
    s = sub[ok]
    dev, med = s["dev"].to_numpy(), s["med8"].to_numpy()
    levels = {k: s[f"m_{k}"].to_numpy(dtype=float) for k in RATIO_KS}
    qb = band(s["cyc"], cuts5)
    out = {"cuts": cuts5, "bands": []}
    for b in range(len(cuts5) + 1):
        m = qb == b
        for sg, sn in ((0, "all"), (1, "pos"), (-1, "neg")):
            mm = m & ((np.where(dev > 0, 1, -1) == sg) if sg else True)
            t = retention_table(dev, med, levels, mm)
            if sn == "all":
                out["bands"].append({"band": b, "score_median": float(np.median(s["cyc"].to_numpy()[m])) if m.any() else None, "all": t})
            else:
                out["bands"][-1][sn] = t
    return out


def population_state(d: pd.DataFrame, cut_iso: str) -> dict:
    """The cross-section at the cut: each company's latest fiscal year (own annual report before the cut) not older than 15 months at the cut."""
    last = d.sort_values("fye").groupby("cik", as_index=False).tail(1)
    age = (pd.Timestamp(cut_iso) - pd.to_datetime(last["fye"])).dt.days / 30.4375
    cur = last[age <= 15]
    out = {"companies_with_a_year": int(len(last)), "companies_current_at_cut": int(len(cur)), "family_counts": cur["family"].value_counts(dropna=False).to_dict()}
    for name, col in (("revenue", "rev"), ("growth_latest", "g_latest"), ("growth_3y_cagr", "g3"), ("operating_margin", "m"), ("margin_dev_from_8y_median", "dev"),
                      ("cyclicality_score", "cyc"), ("roic", "roic"), ("rote", "rote")):
        out[name] = qdict(cur[col])
    out["size_bucket_counts"] = {str(k): int(v) for k, v in pd.Series(bucket(cur["rev"].where(cur["currency"].eq("USD")), SIZE_EDGES)).value_counts().sort_index().items()}
    return out


def survivorship(d: pd.DataFrame) -> dict:
    """The share of observations from companies that later stopped filing (hindsight label; reporting only), for every observation, by family, by size
    bucket, and for the observations a table can use (k = 1 known).  `ceased_before_cut` = stopped before the vintage (known then)."""
    def share(m):
        n = int(m.sum())
        return {"n": n, "share_later_ceased": float(d.loc[m, "ceased"].mean()) if n else None,
                "share_ceased_before_cut": float(d.loc[m, "ceased_before_cut"].mean()) if n else None}
    base = d["family"].isin(FAMILIES)
    out = {"all_family_obs": share(base), "k1_known": share(base & d["rev_1"].notna()), "by_family": {f: share(d["family"].eq(f)) for f in FAMILIES + ("family_not_built",)},
           "by_size": {str(b): share(base & (d["size_b"] == b)) for b in range(len(SIZE_EDGES) + 1)}, "non_usd": share(base & ~d["usd"])}
    out["by_basis"] = {b: share(base & d["family_basis"].eq(b)) for b in ("sic+bs", "bs_only")}
    out["companies"] = {"with_obs": int(d["cik"].nunique()), "later_ceased": int(d.drop_duplicates("cik")["ceased"].sum()),
                        "ceased_before_cut": int(d.drop_duplicates("cik")["ceased_before_cut"].sum())}
    return out


def mechanical_baseline(d: pd.DataFrame, retention: dict) -> dict:
    """Gemini's naive prior, reported beside the measured one: growth year 1 = trailing 3-year CAGR (the latest year where fewer than four years are
    held), margin held at the base year's.  Mean absolute error against what happened, next to the population median's error (in sample)."""
    out = {}
    s = d[d["family"].isin(["operating", "commodity"]) & d["y1"].notna() & d["g_base"].notna() & d["size_b"].ge(0)]
    out["g1"] = {"n": int(len(s)), "baseline_medae": float(np.median(np.abs(s["y1"] - s["g_base"]))) if len(s) else None,
                 "baseline_median_error": float(np.median(s["y1"] - s["g_base"])) if len(s) else None,
                 "population_median_medae": float(np.median(np.abs(s["y1"] - s["y1"].median()))) if len(s) else None,
                 "note": "median absolute error: the mean absolute error of a growth rate is dominated by a few companies whose revenue multiplied"}
    a = d[d["family"].isin(["operating", "commodity"]) & d["dev"].notna() & (d["dev"].abs() >= A2_MIN_DEV) & d["med8"].notna() & d["cyc"].notna()]
    cuts = retention.get("cyc_cuts", [])
    cb = band(a["cyc"], cuts)
    out["margin"] = {}
    for k in (1, 3, 5):
        v = a[f"m_{k}"].to_numpy(dtype=float)
        ok = np.isfinite(v) & (np.abs(a["m"].to_numpy()) <= SANE_MARGIN) & (np.abs(v) <= SANE_MARGIN)
        pred = np.full(len(a), np.nan)
        for b in range(len(cuts) + 1):
            for sg in (1, -1):
                key = f"{ {0: 'low', 1: 'mid', 2: 'high'}.get(b, b) }_{'pos' if sg == 1 else 'neg'}"
                bd = retention["bands"].get(key)
                if not bd:
                    continue
                med_k = [r for r in bd["ks"] if r["k"] == k][0].get("median")
                if med_k is None:
                    continue
                m = (cb == b) & (np.where(a["dev"].to_numpy() > 0, 1, -1) == sg)
                pred[m] = a["med8"].to_numpy()[m] + med_k * a["dev"].to_numpy()[m]
        ok = ok & np.isfinite(pred)
        base = a["m"].to_numpy()
        out["margin"][str(k)] = {"n": int(ok.sum()), "baseline_held_medae": float(np.median(np.abs(v[ok] - base[ok]))) if ok.any() else None,
                                 "median_path_medae": float(np.median(np.abs(v[ok] - pred[ok]))) if ok.any() else None}
    return out
