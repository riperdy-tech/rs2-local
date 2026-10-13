"""near_term.py - engine v2's years 1-3 (SPEC_engine_v2.md sections 2-3, approved 2026-10-11): base-rate point forecasts and measured dispersion.

THE CENTRES (section 2; the forecast study's exact formulas, `forecast_study/pass_priors.forecasts`, with the spec's fixed weights):
  ii      the v1 chain at the prior's median.  growth_k = g_T + (g1_P50 - g_T) d_k;  margin_k = m0 + (m5c - m0) w_k with m5c = centre + r_5 dev, centre = med8
          (else m0) (the retention-only path);  rote_k = ind + ((centre + (R0 - centre) rho_k) - ind) phi_k with centre = rote_med8 (else R0);  tbvg_k as growth_k
  i       the family's population median of the year-k outcome in the vintage's observation table (outcomes filed before the cut); fewer than MIN_N refuses
  rule    operating growth: k=1 i + 0.5 (ii - i), k=2,3 i;  operating margin: ii;  financial ROTE: i + 0.75 (ii - i);  financial tangible-book growth: ii
THE DISTRIBUTIONS (section 3): centre + the measured residual quantiles of the company's cell (v2's own walk-forward misses), kept un-centred (the median bias
is reported), as a QuantileDist named nt_<variable>_<k>.  They join the engine's other inputs in `common.simulate`, so v1's Gaussian copula draws them with the
measured pairs (`corr`).  `deviations[variable][k]` (S5) shifts a centre and is stamped; none by default.
A missing piece is a refusal naming it (NearTermRefusal), never a fill-in.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np

from .common import InputError, QuantileDist, _cholesky, level_path_weights

ENGINE_VERSION = "v2.0"
KS = (1, 2, 3)
MIN_N = 50
RESID_LEVELS = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
REPORT_LEVELS = (0.10, 0.25, 0.50, 0.75, 0.90)
VARIABLES = {"operating": ("growth", "margin"), "financial": ("tbvg", "rote")}
# section 2's fixed constants (weight w on ii - i; 1 = the code's path, 0 = the population median)
WEIGHTS = {("operating", "growth"): {1: 0.5, 2: 0.0, 3: 0.0}, ("operating", "margin"): {1: 1.0, 2: 1.0, 3: 1.0},
           ("financial", "rote"): {1: 0.75, 2: 0.75, 3: 0.75}, ("financial", "tbvg"): {1: 1.0, 2: 1.0, 3: 1.0}}
GROWTH_VARS = ("growth", "tbvg")
LONG_RUN_PARTNER = {"operating": ("nt_margin_3", "margin_target"), "financial": ("nt_rote_3", "rote_target")}


class NearTermRefusal(InputError):
    """A piece of v2's years 1-3 cannot be formed: the engine refuses naming it."""

    def __init__(self, reasons: List[str]):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


def name(var: str, k: int) -> str:
    return f"nt_{var}_{k}"


# ---- the centres ----------------------------------------------------------------------------------------------------------------------------------

def code_paths(family: str, st: Mapping, ps, g_term: float) -> Dict[str, Dict[int, Optional[float]]]:
    """ii: the v1 chain's year-1..3 values at the prior's median (pass_priors.forecasts, the retention-only margin and the faded ROTE curve)."""
    out: Dict[str, Dict[int, Optional[float]]] = {}
    cur, dist = ps.curves, ps.inputs
    gd = cur.get("growth_decay")
    feats = (getattr(ps, "meta", None) or {}).get("features") or {}
    gvar = "growth" if family == "operating" else "tbvg"
    if gd is not None and "g1" in dist:
        g1 = dist["g1"].ppf(0.5)
        out[gvar] = {k: g_term + (g1 - g_term) * gd.at(k) for k in KS}
    if family == "operating":
        mr, m0 = cur.get("margin_retention"), st.get("op_margin")
        if mr is not None and gd is not None and m0 is not None:
            wm, _ = level_path_weights(mr, len(gd))
            med8, dev = feats.get("med8"), feats.get("dev")
            centre = med8 if (med8 is not None and dev is not None) else m0
            m5c = centre + mr.at(5) * (0.0 if dev is None else dev)
            out["margin"] = {k: m0 + (m5c - m0) * wm[k - 1] for k in KS}
    else:
        rho, phi = cur.get("rote_retention"), cur.get("excess_fade")
        R0, ind = st.get("rote_latest"), (st.get("industry_rote") or {}).get("value")
        if rho is not None and phi is not None and R0 is not None and ind is not None:
            med8 = feats.get("rote_med8")
            centre = med8 if med8 is not None else R0
            out["rote"] = {k: ind + ((centre + (R0 - centre) * rho.at(k)) - ind) * phi.at(k) for k in KS}
    return out


def centres(family: str, st: Mapping, ps, g_term: float, table: Mapping) -> Tuple[Dict[str, Dict[int, float]], Dict[str, dict]]:
    """({variable: {k: the section-2 rule value}}, detail with ii, i and w per variable and year).  Raises NearTermRefusal naming every missing piece."""
    ii = code_paths(family, st, ps, g_term)
    pop = ((table.get("i") or {}).get(family)) or {}
    out, detail, miss = {}, {}, []
    for var in VARIABLES[family]:
        if var not in ii:
            miss.append(f"v2 {var}: the v1 path at the prior's median cannot be formed (prior or state missing)")
            continue
        out[var], detail[var] = {}, {}
        for k in KS:
            w = WEIGHTS[(family, var)][k]
            iv = None
            if w < 1.0:
                cell = (pop.get(var) or {}).get(str(k)) or {}
                if cell.get("median") is None or (cell.get("n") or 0) < MIN_N:
                    miss.append(f"v2 {var} year {k}: population median not available (n={cell.get('n')}, minimum {MIN_N})")
                    continue
                iv = float(cell["median"])
            x = ii[var][k] if w == 1.0 else iv + w * (ii[var][k] - iv)
            out[var][k], detail[var][k] = x, {"ii": ii[var][k], "i": iv, "w": w, "rule": x}
    if miss:
        raise NearTermRefusal(miss)
    return out, detail


# ---- the cells ------------------------------------------------------------------------------------------------------------------------------------

def _bucket(x: Optional[float], edges) -> int:
    if x is None or not math.isfinite(x):
        return -1
    return int(np.searchsorted(np.asarray(edges, dtype=float), x, side="right"))


def cell_key(var: str, family: str, feats: Mapping, table: Mapping) -> Optional[str]:
    """The cell of a variable (section 3): growth variables by size bucket x growth band (priors v3 axes); levels by the current-level band (quintiles)."""
    if var in GROWTH_VARS:
        gv = feats.get("tg3" if var == "tbvg" else "g3")
        if gv is None:
            gv = feats.get("tg_latest" if var == "tbvg" else "g_latest")
        sb = _bucket(feats.get("rev"), table["edges"]["size_usd"]) if feats.get("usd") else -1
        gb = _bucket(gv, table["edges"]["growth"])
        return None if (sb < 0 or gb < 0) else f"s{sb}_g{gb}"
    lv = feats.get("m" if var == "margin" else "rote")
    cuts = (table.get("level_cuts") or {}).get(family)
    lb = _bucket(lv, cuts) if cuts else -1
    return None if lb < 0 else f"l{lb}"


def residual_quantiles(family: str, var: str, k: int, key: Optional[str], table: Mapping) -> Tuple[Dict[float, float], str]:
    """(quantiles, the cell used): the company's cell when it has at least MIN_N residuals, else the family pool (stated); neither refuses."""
    r = (((table.get("residuals") or {}).get(family) or {}).get(var) or {}).get(str(k)) or {}
    c = (r.get("cells") or {}).get(key) if key else None
    if c and c.get("n", 0) >= MIN_N:
        return {float(p): float(v) for p, v in c["q"].items()}, key
    pool = r.get("pool") or {}
    if pool.get("n", 0) >= MIN_N:
        return {float(p): float(v) for p, v in pool["q"].items()}, "pool"
    raise NearTermRefusal([f"v2 {var} year {k}: no residual table with at least {MIN_N} observations (cell {key}, family pool n={pool.get('n')})"])


# ---- the distributions and their dependence -------------------------------------------------------------------------------------------------------

def near_term_inputs(family: str, st: Mapping, ps, g_term: float, table: Mapping, feats: Mapping,
                     deviations: Optional[Mapping[str, Mapping[int, float]]] = None) -> Tuple[Dict[str, QuantileDist], Dict[tuple, float], dict]:
    """(dists, corr, info): the nt_* inputs for `common.simulate`, the measured copula pairs among them and with the long-run partner, and what the result
    reports (section 5).  Raises NearTermRefusal."""
    cen, detail = centres(family, st, ps, g_term, table)
    dists, info = {}, {"engine_version": ENGINE_VERSION, "near_term_vintage": table.get("vintage"), "cells": {}, "fallbacks": [], "deviations": {},
                                                   "forecast_years": {}}
    for var in VARIABLES[family]:
        info["forecast_years"][var] = {}
        for k in KS:
            q, used = residual_quantiles(family, var, k, cell_key(var, family, feats, table), table)
            if used == "pool":
                info["fallbacks"].append(f"{var} year {k}: the company's cell is under {MIN_N}; the family pool is used")
            dev = float(((deviations or {}).get(var) or {}).get(k) or 0.0)
            if dev:
                info["deviations"][f"{var}_{k}"] = dev
            c = cen[var][k] + dev
            d = QuantileDist({p: c + v for p, v in q.items()}, f"v2 {var} y{k} centre+residuals ({used})")
            dists[name(var, k)] = d
            info["cells"][name(var, k)] = used
            info["forecast_years"][var][k] = dict({f"p{int(round(p * 100))}": d.ppf(p) for p in REPORT_LEVELS},
                                                  forecast_p50_rule=cen[var][k], median_bias=q.get(0.5), deviation=dev or None, rule=detail[var][k])
    corr, paired, independent = {}, [], []
    for key, r in (((table.get("corr") or {}).get(family)) or {}).items():
        a, b = key.split("|")
        if r is None or not math.isfinite(float(r)):
            independent.append(key)
            continue
        corr[(a, b)] = float(r)
        paired.append(key)
    info["copula"] = {"measured": paired, "independent": independent}
    return dists, corr, info


def checked_corr(names: List[str], corr: Mapping[tuple, float], info: dict) -> Dict[tuple, float]:
    """The pairs as given when the full matrix over `names` is positive definite; otherwise the near-term pairs are dropped (independence, stamped)."""
    def matrix(c):
        k = len(names)
        m = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
        for (a, b), r in c.items():
            if a in names and b in names and a != b:
                i, j = names.index(a), names.index(b)
                m[i][j] = m[j][i] = float(r)
        return m
    try:
        _cholesky(matrix(corr))
        return dict(corr)
    except InputError:
        kept = {p: r for p, r in corr.items() if not (p[0].startswith("nt_") or p[1].startswith("nt_"))}
        info.setdefault("fallbacks", []).append("near-term copula not positive definite with the long-run pairs: near-term pairs dropped (independence)")
        return kept


# ---- the tables -----------------------------------------------------------------------------------------------------------------------------------

def load_table(data_dir, vintage: int) -> dict:
    p = Path(data_dir) / str(vintage) / "near_term.json"
    if not p.exists():
        raise NearTermRefusal([f"v2: no near-term table for vintage {vintage} at {p}"])
    return json.loads(p.read_text(encoding="utf-8"))
