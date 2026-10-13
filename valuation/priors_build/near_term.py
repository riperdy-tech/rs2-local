"""near_term.py (build) - engine v2's per-vintage near-term tables (SPEC_engine_v2.md sections 2-3, 6): `data/priors_v4/<vintage>/near_term.json`.

    python -m valuation.priors_build.near_term --vintages 2016 ... 2024 [--obs OBS] [--panel PANEL] [--out DATA_DIR]

POPULATION MEDIANS i_k as of a cut date C: the observation table's rows whose own annual report was filed before C, and whose year-k outcome was filed before C
(first-filed values, so any later vintage's table gives the same set; the forecast study's method).  Year-k growth = rev_k / rev_(k-1) - 1 (rev_0 = rev),
tangible-book growth likewise, the margin and ROTE as filed (`forecast_study/panel.load_obs`).
RESIDUALS for vintage V (cut C = Jan 1 of V+1): the forecast-study panel's rows (the >= $300M universe at each 30 June origin) whose origin is before C; for each
year k with its outcome filed before C, the residual = outcome - v2's section-2 forecast at that origin, the forecast made with the population medians as of the
origin's own cut (Jan 1 of the origin's year: the vintage that origin would use); for the two growth variables in log space,
log(1 + outcome) - log(1 + forecast) (Addendum AL.1).  Quantiles RESID_LEVELS per cell and for the family pool; cells as in
valuation/near_term.cell_key, with the size axis read as USD (the panel's universe is priced in USD; a reporting-currency revenue mis-buckets, a stated limit).
COPULA: Spearman correlations of paired residuals, as Gaussian r = 2 sin(pi rho / 6), for each variable across years and between the family's two variables in
the same year; fewer than MIN_N pairs, or the year-3 level with its long-run partner (not in the panel), is independence, listed.
NOTHING IS FITTED: the weights are section 2's constants; these tables only measure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd

from .. import near_term as nt
from . import config as C

PANEL = C.WORKSPACE / "scratch" / "rev23" / "forecast_study" / "out" / "panel.pkl"
OBS = C.WORKSPACE / "data" / "priors_v3" / "2025" / "obs.csv.gz"
OUT_DIR = C.WORKSPACE / "data" / "priors_v4"
EDGES = {"size_usd": [5e7, 2.5e8, 1e9, 5e9, 2e10], "growth": [-0.1, 0.0, 0.05, 0.1, 0.2, 0.4]}      # priors v3 tables["edges"], the g1 cell axes
OUTCOME = {"growth": "g", "margin": "m", "tbvg": "tg", "rote": "rote"}
CODE = {"growth": "c_growth_{k}_p50", "margin": "c_margin_curve_{k}_p50", "tbvg": "c_growth_{k}_p50", "rote": "c_rote_curve_{k}_p50"}


def load_obs(path=OBS) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    for k in nt.KS:
        pr, pt = ("rev", "tbv") if k == 1 else (f"rev_{k - 1}", f"tbv_{k - 1}")
        d[f"g_{k}"] = np.where((d[pr] > 0) & (d[f"rev_{k}"] > 0), d[f"rev_{k}"] / d[pr] - 1.0, np.nan)
        d[f"tg_{k}"] = np.where((d[pt] > 0) & (d[f"tbv_{k}"] > 0), d[f"tbv_{k}"] / d[pt] - 1.0, np.nan)
    return d


def population_medians(obs: pd.DataFrame, cut: str) -> Dict[str, Dict[str, Dict[str, dict]]]:
    """{family: {variable: {k: {"median", "n", "max_filed"}}}} as of `cut` (only what the near-term rules use: operating growth, financial ROTE)."""
    out = {}
    for fam, var in (("operating", "growth"), ("financial", "rote")):
        out.setdefault(fam, {})[var] = {}
        for k in nt.KS:
            f = obs[f"filed_{k}"].astype(str)
            m = (obs["family"] == fam) & (obs["own_filed"].astype(str) < cut) & obs[f"filed_{k}"].notna() & (f < cut)
            v = obs.loc[m, f"{OUTCOME[var]}_{k}"].astype(float).dropna()
            out[fam][var][str(k)] = {"median": float(v.median()) if len(v) else None, "n": int(len(v)), "max_filed": str(f[m].max()) if m.any() else None}
    return out


def _rule(fam, var, k, ii, i):
    w = nt.WEIGHTS[(fam, var)][k]
    if w == 1.0:
        return ii
    if i is None or ii is None or not math.isfinite(ii):
        return np.nan
    return i + w * (ii - i)


def residual_frame(panel: pd.DataFrame, obs: pd.DataFrame, cut: str) -> pd.DataFrame:
    """One row per panel row x variable x k with an outcome filed before `cut`: the residual and the features of the cell."""
    rows = []
    medians_at = {}
    p = panel[panel["date"].astype(str) < cut]
    for _, r in p.iterrows():
        fam = r["family"]
        if fam not in nt.VARIABLES:
            continue
        ocut = date(int(str(r["date"])[:4]), 1, 1).isoformat()                          # the vintage the origin would use: cut Jan 1 of its year
        if ocut not in medians_at:
            medians_at[ocut] = population_medians(obs, ocut)
        pop = medians_at[ocut]
        for var in nt.VARIABLES[fam]:
            for k in nt.KS:
                y, ii, filed = r.get(f"{OUTCOME[var]}_{k}"), r.get(CODE[var].format(k=k)), r.get(f"filed_{k}")
                if pd.isna(y) or pd.isna(ii) or pd.isna(filed) or str(filed) >= cut:
                    continue
                cell = (pop.get(fam, {}).get(var) or {}).get(str(k)) or {}
                i = cell.get("median") if (cell.get("n") or 0) >= nt.MIN_N else None
                x = _rule(fam, var, k, float(ii), i)
                if not math.isfinite(x):
                    continue
                if var in nt.GROWTH_VARS:                                                 # Addendum AL.1 2: growth residuals in log space
                    if float(y) <= -1.0 or x <= -1.0:
                        continue
                    resid = math.log1p(float(y)) - math.log1p(x)
                else:
                    resid = float(y) - x
                rows.append({"cik": r["cik"], "date": r["date"], "family": fam, "var": var, "k": k, "resid": resid,
                             "rev": r.get("f_rev"), "g3": r.get("f_g3"), "g_latest": r.get("f_g_latest"), "tg3": r.get("f_tg3"), "tg_latest": r.get("f_tg_latest"),
                             "m": r.get("f_m"), "rote": r.get("f_rote")})
    return pd.DataFrame(rows)


def _q(v) -> dict:
    return {"n": int(len(v)), "q": {str(p): float(np.quantile(v, p)) for p in nt.RESID_LEVELS}}


def build_table(vintage: int, panel: pd.DataFrame, obs: pd.DataFrame) -> dict:
    cut = C.cut_date(vintage)
    res = residual_frame(panel, obs, cut)
    level_cuts = {}
    for fam, col in (("operating", "m"), ("financial", "rote")):
        lv = res[(res["family"] == fam) & (res["k"] == 1)].drop_duplicates(["cik", "date"])[col].astype(float).dropna() if len(res) else pd.Series(dtype=float)
        level_cuts[fam] = [float(x) for x in np.quantile(lv, [0.2, 0.4, 0.6, 0.8])] if len(lv) >= 5 * nt.MIN_N else None
    t = {"version": nt.ENGINE_VERSION, "vintage": vintage, "cut_date": cut, "edges": EDGES, "level_cuts": level_cuts, "i": population_medians(obs, cut),
         "residuals": {}, "corr": {}, "rule": __doc__.split("\n\n")[1].strip()[:400]}
    for fam, vars_ in nt.VARIABLES.items():
        t["residuals"][fam] = {}
        for var in vars_:
            t["residuals"][fam][var] = {}
            for k in nt.KS:
                sub = res[(res["family"] == fam) & (res["var"] == var) & (res["k"] == k)] if len(res) else res
                entry = {"pool": _q(sub["resid"].to_numpy()) if len(sub) else {"n": 0, "q": {}}, "cells": {}}
                if len(sub):
                    keys = sub.apply(lambda r: nt.cell_key(var, fam, {"rev": r["rev"], "usd": True, "g3": r["g3"], "g_latest": r["g_latest"], "tg3": r["tg3"],
                                                                      "tg_latest": r["tg_latest"], "m": r["m"], "rote": r["rote"]}, t), axis=1)
                    for key, grp in sub.groupby(keys):
                        if key is not None and len(grp) >= nt.MIN_N:
                            entry["cells"][key] = _q(grp["resid"].to_numpy())
                t["residuals"][fam][var][str(k)] = entry
        t["corr"][fam] = copula_pairs(res[res["family"] == fam] if len(res) else res, fam)
    return t


def copula_pairs(res: pd.DataFrame, fam: str) -> Dict[str, Optional[float]]:
    a_var, b_var = nt.VARIABLES[fam]
    pairs = [((v, 1), (v, 2)) for v in (a_var, b_var)] + [((v, 2), (v, 3)) for v in (a_var, b_var)] + [((v, 1), (v, 3)) for v in (a_var, b_var)]
    pairs += [((a_var, k), (b_var, k)) for k in nt.KS]
    out = {}
    piv = res.pivot_table(index=["cik", "date"], columns=["var", "k"], values="resid") if len(res) else None
    for (va, ka), (vb, kb) in pairs:
        key = f"{nt.name(va, ka)}|{nt.name(vb, kb)}"
        if piv is None or (va, ka) not in piv or (vb, kb) not in piv:
            out[key] = None
            continue
        both = piv[[(va, ka), (vb, kb)]].dropna()
        if len(both) < nt.MIN_N:
            out[key] = None
            continue
        rho = both.rank().corr().iloc[0, 1]
        out[key] = float(2.0 * math.sin(math.pi * rho / 6.0))
    partner = nt.LONG_RUN_PARTNER[fam]
    out[f"{partner[0]}|{partner[1]}"] = None                                             # not measurable in the panel (no year-5 outcome): independence
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vintages", type=int, nargs="+", required=True)
    ap.add_argument("--obs", type=Path, default=OBS)
    ap.add_argument("--panel", type=Path, default=PANEL)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args(argv)
    obs, panel = load_obs(a.obs), pd.read_pickle(a.panel)
    for v in a.vintages:
        t = build_table(v, panel, obs)
        t["inputs"] = {"obs": str(a.obs), "obs_sha256": hashlib.sha256(Path(a.obs).read_bytes()).hexdigest(), "panel": str(a.panel),
                       "panel_sha256": hashlib.sha256(Path(a.panel).read_bytes()).hexdigest()}
        d = a.out / str(v)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "near_term.json"
        with open(p, "x", encoding="utf-8") as fh:                                       # written once
            json.dump(t, fh, indent=1)
        (d / "near_term.sha256").write_text(hashlib.sha256(p.read_bytes()).hexdigest(), encoding="utf-8")
        print(v, "pools:", {f"{f}.{x}.{k}": t["residuals"][f][x][str(k)]["pool"]["n"] for f in t["residuals"] for x in t["residuals"][f] for k in nt.KS})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
