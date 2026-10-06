"""priors.py - population priors at T (SPEC_rebuild.md section 4, Addenda A-D): the `Priors` implementation the engines call.

`PopulationPriors.for_company(family, state, asof)` returns a `PriorSet` whose inputs, curves and references are MEASURED on the filed history of the whole
SEC population, point in time:

  * VINTAGE.  A valuation date T uses the vintage year(T) - 1: its tables are built only from fiscal years whose own annual report was filed strictly
    before Jan 1 of year(T), and from outcomes in annual reports filed before that date as well.  Nothing filed on or after the cut date can reach a prior
    for any date T >= that cut date (valuation/tests/test_priors.py proves it by changing every later fact).  Vintages are cut at year ends
    (a coarser, conservative rule: a prior at T is on average about 6 months stale, never ahead).
  * DELISTED COMPANIES STAY IN.  The observations are every company in the SEC archive with a filed annual report, delisted ones included, up to their
    last filing; the survivorship shares are reported in PRIORS_REPORT.md.
  * NO RETURNS.  No prior reads a return.  The two valuation references (EV / FCFF1, P / TBV) read the month-end close at the observation date and
    nothing after it; they exist only for survivors (no price file holds a delisted company) and are cross-check references, never averaged in.
  * NOTHING IS FILLED IN SILENTLY.  A lookup that cannot be answered at the company's own state falls back to a stated pooled table and the fallback is
    listed in `meta["fallbacks"]`; an input the vintage cannot support is absent from `inputs`, so the engine refuses naming it (`meta["unavailable"]`).
  * SPREADS BY LEVEL (Addendum I1).  The year-5 residuals of the margin level and of the ROIC level are measured by the company's CURRENT level band (quintiles of the
    current level within the cell, merged to n >= 50 by `stats.merge_1d`); the prior's quantiles are the median path plus the residual quantiles of the company's own band.
  * MIN_N IS ENFORCED (Addendum I5).  A cell with fewer than 50 observations after the stated merges refuses the input, named in `meta["unavailable"]`: the residual cell of the
    company's cyclicality x sign band is merged up (sign-pooled, then fully pooled) and, if the pooled cell is still under 50, there is no prior (never an invented spread).

The state is the engines' own `common.build_state` dict, so the features priors condition on are computed the way the observation panel computed them
(valuation/priors_build/obs.py): the same chain-index windows, the same cyclicality function.

The mechanical baseline (Gemini's naive prior: growth year 1 = the trailing 3-year CAGR, margin held) is in `meta["mechanical_baseline"]`.
`meta["corr"]` is the Gaussian-copula correlation of the inputs (pass it to `draw_inputs` / `run(corr=...)`); independence is the fallback and is stamped.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from .common import Curve, DataNotPresent, InputError, QuantileDist, parse_date
from .priors_build import config as C
from .priors_build.obs import RECORD_MIN, WINDOW, chain_index, nopat_of, trend_slope
from .priors_interface import PriorSet, Priors

HORIZON = 10
SIZE_EDGES = [50e6, 250e6, 1e9, 5e9, 20e9]
LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
NAMES = {0: "low", 1: "mid", 2: "high"}


class PriorsUnavailable(DataNotPresent):
    """No vintage serves the date."""


def _bucket(x: Optional[float], edges) -> int:
    if x is None or not math.isfinite(x):
        return -1
    return int(np.searchsorted(np.asarray(edges, dtype=float), x, side="right"))


def _band(x: Optional[float], cuts) -> int:
    if x is None or not math.isfinite(x):
        return -1
    return int(np.searchsorted(np.asarray(cuts, dtype=float), x, side="right")) if cuts else 0


def _qd(cell: dict, shift: float = 0.0, label: str = "") -> Optional[QuantileDist]:
    """A QuantileDist from a table cell's quantiles (P10, P50, P90 are required), shifted by `shift` (a centre)."""
    q = {}
    for p in LEVELS:
        v = cell.get(f"p{p * 100:g}")
        if v is not None:
            q[p] = v + shift
    if not all(x in q for x in (0.10, 0.50, 0.90)):
        return None
    return QuantileDist(q, label)


def _find_cell(cells, r, c):
    for cell in cells:
        if cell["row"][0] <= r <= cell["row"][1] and cell["col"][0] <= c <= cell["col"][1]:
            return cell
    return None


def _level_group(tab: Optional[dict], level: Optional[float]):
    """(group, n_cell): the group of a residual-by-level table (`stats.residual_by_level`) that holds `level` (its range is [lower, upper), open ends None), and the n of the
    whole cell.  The group is None when the table is absent, the level is not a number, or the whole cell has fewer than MIN_N observations (Addendum I5: refuse, do not merge
    below 50 here; the caller merges UP to the next pooled cell)."""
    if not tab or not tab.get("groups"):
        return None, 0
    n_cell = int(tab.get("n", 0))
    if n_cell < C.MIN_N or level is None or not math.isfinite(level):
        return None, n_cell
    for g in tab["groups"]:
        lo, hi = g.get("lower"), g.get("upper")
        if (lo is None or level >= lo) and (hi is None or level < hi):
            return (g if g.get("n", 0) >= C.MIN_N else None), n_cell
    return None, n_cell


def _extend(vals: List[float], n: int) -> List[float]:
    return vals + [vals[-1]] * (n - len(vals)) if len(vals) < n else vals[:n]


def _curve_from_rows(rows: List[dict], key: str, n_key: str, name: str, source: str, flags: List[str], horizon: int = HORIZON, min_n: int = C.MIN_N,
                     first_is_one: bool = False) -> Optional[Curve]:
    """The measured median at k = 1.. while at least `min_n` observations stand behind it; clipped to [0, 1] (clips are flagged); extended by holding the
    last measured value to `horizon` years (flagged)."""
    vals = []
    for r in rows:
        if r.get(key) is None or r.get(n_key, 0) < min_n:
            break
        vals.append(r[key])
    if not vals:
        return None
    clipped = [min(1.0, max(0.0, v)) for v in vals]
    if clipped != vals:
        flags.append(f"{name}: {sum(1 for a, b in zip(vals, clipped) if a != b)} measured value(s) outside [0, 1] clipped (raw: {[round(v, 3) for v in vals]})")
    if len(clipped) < horizon:
        flags.append(f"{name}: measured to k={len(clipped)} (n >= {min_n}); the last value is held to year {horizon}")
    mono = all(b <= a + 1e-12 for a, b in zip(vals, vals[1:]))
    if not mono:
        flags.append(f"{name}: the measured curve is not monotone (reported, not forced): {[round(v, 3) for v in vals]}")
    return Curve(_extend(clipped, horizon), name, source)


CURVE_REF_YEAR = 5          # a curve input is the fraction of the initial gap still open this many years on (Muse schema.CURVE_REF_YEAR)


def _pos_row(rows, key, n_key, min_n=C.MIN_N, ref=CURVE_REF_YEAR):
    """The table row whose distribution stands behind the curve's value at year `ref`: the same rows `_curve_from_rows` reads (consecutive from k = 1 while
    n >= min_n); year `ref`, or the last measured year before it when the measurement stops sooner (the curve holds that value)."""
    used = []
    for r in rows:
        if r.get(key) is None or r.get(n_key, 0) < min_n:
            break
        used.append(r)
    return used[min(ref, len(used)) - 1] if used else None


def _pos_dist(row, qkey, label):
    """The quantiles (P5..P95) of the per-observation fraction of the gap still open in `row`, clipped to [0, 1] (a fraction of a gap; the curve is clipped
    the same way, and clipping is monotone, so the median equals the curve's value)."""
    q = (row or {}).get(qkey)
    if not q:
        return None
    qs = {}
    for p in LEVELS:
        v = q.get(f"p{p * 100:g}")
        if v is not None:
            qs[p] = min(1.0, max(0.0, v))
    return QuantileDist(qs, label) if all(x in qs for x in (0.10, 0.50, 0.90)) else None


# ---- the company's features, from the engines' state -------------------------------------------------------------------------------------------

def features(st: dict, family: str) -> dict:
    """The state variables the tables condition on, from `common.build_state`'s dict.  Same definitions as valuation/priors_build/obs.py."""
    out = {"missing": []}
    periods = st.get("periods") or []
    base = st.get("base_period")
    if not periods or base is None:
        out["missing"].append("no fiscal year")
        return out
    idx = chain_index(list(periods))
    by_idx = {i: p for p, i in idx.items()}
    t = idx[base]
    rev = {p: v for p, v in (st.get("revenue_series") or {}).items() if v is not None and v > 0}
    r0 = rev.get(base)
    out["rev"] = r0
    out["usd"] = not any(str(n).startswith("reporting_currency") for n in st.get("notes", []))
    pm, p3 = by_idx.get(t - 1), by_idx.get(t - 3)
    out["g_latest"] = (r0 / rev[pm] - 1.0) if (r0 is not None and pm in rev) else None
    out["g3"] = ((r0 / rev[p3]) ** (1.0 / 3.0) - 1.0) if (r0 is not None and p3 in rev) else None
    tb = {p: v for p, v in (st.get("tbv_series") or {}).items() if v is not None and v > 0}
    out["tg_latest"] = (tb[base] / tb[pm] - 1.0) if (base in tb and pm in tb) else None
    out["tg3"] = ((tb[base] / tb[p3]) ** (1.0 / 3.0) - 1.0) if (base in tb and p3 in tb) else None
    om = st.get("op_margin_series") or {}
    win = [by_idx[i] for i in range(t - WINDOW + 1, t + 1) if i in by_idx]
    mw = [om[p] for p in win if p in om]
    out["m"] = om.get(base)
    out["med8"] = float(np.median(mw)) if len(mw) >= RECORD_MIN else None
    out["n8"] = len(mw)
    out["dev"] = (out["m"] - out["med8"]) if (out["m"] is not None and out["med8"] is not None) else None
    rs = st.get("rote_series") or {}
    rw = [rs[p] for p in win if p in rs]
    out["rote"] = rs.get(base)
    out["rote_med8"] = float(np.median(rw)) if len(rw) >= RECORD_MIN else None
    out["rote_dev"] = (out["rote"] - out["rote_med8"]) if (out["rote"] is not None and out["rote_med8"] is not None) else None
    lr = {idx[p]: math.log(rev[p]) for p in win if p in rev}
    out["trend8"] = trend_slope(lr)
    cyc = st.get("cyclicality")
    out["cyc_components"] = (cyc or {}).get("components")
    out["cyc_equal"] = (cyc or {}).get("score")
    oi, tax = st.get("operating_income"), st.get("tax_rate")
    eq, debt, cash, sti = st.get("equity"), st.get("debt"), st.get("cash"), st.get("st_investments")
    ic = None if (eq is None or debt is None or cash is None) else eq + debt - cash - (0.0 if sti is None else sti)
    nop = None if (oi is None or tax is None) else nopat_of(oi, tax)
    out["roic"] = (nop / ic) if (nop is not None and ic is not None and ic > 0) else None
    out["tbv"] = st.get("tbv")
    out["roic3"] = st.get("roic3")                       # Addendum H3: the trailing 3-year ROIC level
    out["industry_roic"] = st.get("industry_roic")       # {"value", "n", "basis"}: the date's industry median ROIC, attached by the caller (the population of the date)
    return out


# ---- the implementation --------------------------------------------------------------------------------------------------------------------------

class PopulationPriors(Priors):
    """Priors measured on the point-in-time population.  `data_dir` holds one folder per vintage with `tables.json`."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir is not None else C.DATA_DIR
        self._tables: Dict[int, dict] = {}

    # -- vintages --
    def vintages_available(self) -> List[int]:
        return sorted(int(p.name) for p in self.data_dir.iterdir() if p.is_dir() and p.name.isdigit() and (p / "tables.json").exists())

    def tables(self, vintage: int) -> dict:
        if vintage not in self._tables:
            p = self.data_dir / str(vintage) / "tables.json"
            if not p.exists():
                raise PriorsUnavailable(f"no priors vintage {vintage} in {self.data_dir} (built: {self.vintages_available()})")
            self._tables[vintage] = json.loads(p.read_text(encoding="utf-8"))
        return self._tables[vintage]

    def vintage_for(self, asof) -> int:
        return C.vintage_for(parse_date(asof))

    # -- the PriorSet --
    def for_company(self, family: str, state: dict, asof) -> PriorSet:
        if family not in ("operating", "commodity", "financial"):
            raise InputError(f"no priors for family {family!r}")
        try:
            V = self.vintage_for(asof)
            T = self.tables(V)
        except PriorsUnavailable as e:
            return PriorSet(family, {}, {}, {}, "UNAVAILABLE", False, {"unavailable": [str(e)], "fallbacks": []})
        ft = features(state, family)
        flags: List[str] = []
        fallbacks: List[str] = []
        unavailable: List[str] = []
        positions: Dict[str, Optional[QuantileDist]] = {}
        src = f"population_priors v{T['priors_version']} vintage={V} cut={T['cut_date']} obs_sha256={T['obs_sha256'][:12]} store={T['store_fingerprint_sha256'][:12]}"
        inputs: Dict[str, QuantileDist] = {}
        curves: Dict[str, Curve] = {}
        refs: Dict[str, Callable] = {}
        meta = {"vintage": V, "cut_date": T["cut_date"], "features": {k: v for k, v in ft.items() if k not in ("cyc_components",)},
                "cells": {}, "fallbacks": fallbacks, "unavailable": unavailable, "flags": flags}
        # the cyclicality score on the vintage's weights (equal unless the fit was adopted out of sample)
        w = T["cyc_weights"]
        score, score_basis = ft.get("cyc_equal"), "equal weights"
        comp = ft.get("cyc_components")
        if comp and w.get("adopted"):
            score = sum(wi * comp[c] for wi, c in zip(w["weights"], ("margin_volatility", "reversal_frequency", "autocorrelation", "revenue_cyclicality")))
            score_basis = "fitted weights " + str([round(x, 3) for x in w["weights"]])
        meta["cyc_score"], meta["cyc_score_basis"] = score, score_basis
        if family in ("operating", "commodity"):
            self._operating(family, T, ft, score, inputs, curves, refs, meta, fallbacks, unavailable, flags, src, positions)
        else:
            self._financial(T, ft, inputs, curves, refs, meta, fallbacks, unavailable, flags, src, positions)
        # the correlation of the inputs, by family
        cor = T["correlation"].get(family if family in T["correlation"] else "operating")
        if cor and "pairs" in cor:
            corr = {}
            for k, v in cor["pairs"].items():
                a, b = k.split("|")
                if v.get("copula_r") is not None and a in inputs and b in inputs:
                    corr[(a, b)] = v["copula_r"]
            meta["corr"] = corr
            meta["corr_psd_adjusted"] = cor.get("psd_adjusted")
        else:
            meta["corr"] = {}
            fallbacks.append("input correlation not measured: independence (stamped)")
        meta["mechanical_baseline"] = self._baseline(family, T, ft)
        pos = {k: v for k, v in positions.items() if v is not None}
        if pos:
            def curve_position(name, st=None, _pos=pos):
                """The measured distribution (P5..P95) of the fraction of the initial gap still open CURVE_REF_YEAR (5) years out, in the cell the company's own
                curve was read from (the state the PriorSet was built for).  Its median equals the curve's value at year 5.  None for a name this family has no
                curve for (the input is then not asked of Muse)."""
                return _pos.get(name)
            refs["curve_position"] = curve_position
        return PriorSet(family, inputs, curves, refs, src, False, meta)

    # -- operating and commodity --
    def _g1_cell(self, T, fam, ft, growth, usd_size, label, fallbacks):
        """(cell, basis) for the family's next-year growth: the size x growth cell on the 3-year CAGR basis, else the latest-year basis, else size-pooled."""
        tg = T["g1"].get(fam)
        for basis, gv in (("g3", ft.get("tg3" if fam == "financial" else "g3")), ("latest", ft.get("tg_latest" if fam == "financial" else "g_latest"))):
            if gv is None or tg is None or basis not in tg:
                continue
            gb = _bucket(gv, T["edges"]["growth"])
            sb = _bucket(ft.get("rev"), T["edges"]["size_usd"]) if (ft.get("usd") and ft.get("rev") is not None) else -1
            if sb >= 0:
                cell = _find_cell(tg[basis]["cells"], sb, gb)
                if cell is not None and cell["n"] >= 1:
                    return cell, basis, False
            cell = _find_cell(tg[basis].get("size_pooled_cells", []), 0, gb)
            if cell is not None:
                fallbacks.append(f"g1: size {'unknown (non-USD or no revenue)' if sb < 0 else 'cell empty'}: size-pooled cell on the {basis} basis")
                return cell, basis, True
        return None, None, False

    def _operating(self, family, T, ft, score, inputs, curves, refs, meta, fallbacks, unavailable, flags, src, positions):
        fam = family
        # g1
        cell, basis, pooled = self._g1_cell(T, fam, ft, None, None, "g1", fallbacks)
        if cell is None or cell["n"] < C.MIN_N:
            if fam != "operating":
                c2, b2, p2 = self._g1_cell(T, "operating", ft, None, None, "g1", fallbacks)
                if c2 is not None:
                    fallbacks.append(f"g1: the {fam} family has too few observations in this vintage; the operating family's table is used")
                    cell, basis = c2, b2
        if cell is None:
            unavailable.append("g1: no growth delivered (fewer than two fiscal years of revenue) or no cell in this vintage")
        elif cell["n"] < C.MIN_N:
            unavailable.append(f"g1: the size x growth cell has n={cell['n']} < {C.MIN_N} after the stated merges (Addendum I5)")
        else:
            qd = _qd(cell, 0.0, src)
            if qd is None:
                unavailable.append("g1: the cell has too few observations for P10/P50/P90")
            else:
                inputs["g1"] = qd
                meta["cells"]["g1"] = {k: cell[k] for k in ("n", "merged_rows", "merged_cols", "thin", "baseline_growth_median", "baseline_mae", "cell_median_mae") if k in cell}
                meta["cells"]["g1"]["basis"] = basis
        # growth decay (by growth bucket)
        gd = T["growth_decay"].get(fam)
        if (not gd or not gd.get("buckets")) and fam != "operating":
            gd = T["growth_decay"].get("operating")
            fallbacks.append("growth_decay: family table unavailable; the operating family's table is used")
        gv = ft.get("g3") if ft.get("g3") is not None else ft.get("g_latest")
        if gd and gd.get("buckets") and gv is not None:
            gb = _bucket(gv, T["edges"]["growth"])
            bk = next((b for b in gd["buckets"] if b["bucket"][0] <= gb <= b["bucket"][1]), None)
            if bk is not None:
                cv = _curve_from_rows(bk["ks"], "ratio_median", "n_ratio", "growth_decay", src, flags)
                if cv is not None:
                    curves["growth_decay"] = cv
                    positions["growth_persistence"] = _pos_dist(_pos_row(bk["ks"], "ratio_median", "n_ratio"), "ratio_q", src)
                    meta["cells"]["growth_decay"] = {"bucket": bk["bucket"], "n_k1": bk["n_k1"], "terminal_reference": gd["terminal_reference"]}
        if "growth_decay" not in curves:
            unavailable.append("growth_decay: no growth delivered or no measured curve for the bucket")
        # terminal growth is not a prior (Addendum H2): the engines take min(risk-free rate at T, 3.75%); the table of realized K-year growth stays in the vintage
        # margin target and retention
        mr = T["margin_retention"]
        cuts = mr["cyc_cuts"]
        ret_key, centre = None, None
        if ft.get("med8") is not None and ft.get("dev") is not None and abs(ft["dev"]) >= 0.005:
            sg = "pos" if ft["dev"] > 0 else "neg"
            cb = _band(score, cuts)
            if cb >= 0:
                ret_key = f"{NAMES.get(cb, cb)}_{sg}"
            else:
                ret_key = f"pooled_{sg}"
                fallbacks.append("margin_retention: no cyclicality score (fewer than 6 years): the sign-only pooled curve")
            centre = ft["med8"]
        elif ft.get("med8") is not None and ft.get("dev") is not None:
            ret_key = "pooled_all"
            centre = ft["med8"]
            fallbacks.append("margin_retention: |deviation| < 0.5 points (no direction): the pooled curve")
        else:
            ret_key = "pooled_all"
            centre = state_median(ft)
            fallbacks.append("margin_target: fewer than 5 defined margin years (the record rule): no 8-year median; centred on the margin held, pooled curve")
        bd = mr["bands"].get(ret_key)
        if bd is not None and bd["n"] < C.MIN_N:
            fallbacks.append(f"margin_retention: band {ret_key} has n={bd['n']} < {C.MIN_N}: pooled curve")
            ret_key = "pooled_all" if "pos" not in ret_key and "neg" not in ret_key else ("pooled_pos" if ret_key.endswith("pos") else "pooled_neg")
            bd = mr["bands"].get(ret_key)
        if bd is not None:
            cv = _curve_from_rows(bd["ks"], "median", "n", "margin_retention", src, flags)
            if cv is not None:
                curves["margin_retention"] = cv
                positions["margin_retention"] = _pos_dist(_pos_row(bd["ks"], "median", "n"), "q", src)
            # Addendum I1/I5: the residual of the margin level five years on, by the company's CURRENT margin band, in the cell of its cyclicality x sign band; a cell
            # under MIN_N is merged up (sign-pooled, then fully pooled); under MIN_N there too, the input is refused, named
            rl_tab = mr.get("residual_k5_by_level")
            cands = [ret_key] + ([f"pooled_{ret_key.rsplit('_', 1)[1]}"] if ret_key.rsplit("_", 1)[-1] in ("pos", "neg") and not ret_key.startswith("pooled") else []) + (
                ["pooled_all"] if ret_key != "pooled_all" else [])
            res, grp, used, ns = None, None, None, []
            if rl_tab is None:
                unavailable.append("margin_target: this vintage has no level-conditional residual table (priors version < 3)")
            else:
                for k in cands:
                    g_, n_ = _level_group(rl_tab.get(k), ft.get("m"))
                    ns.append(f"{k} n={n_}")
                    if g_ is not None:
                        grp, used = g_, k
                        break
                if grp is None:
                    unavailable.append(f"margin_target: no residual cell with n >= {C.MIN_N} after the stated merges ({'; '.join(ns)})" if ft.get("m") is not None
                                       else "margin_target: no current operating margin to place in a level band")
                elif used != ret_key:
                    fallbacks.append(f"margin_target: residual cell of band {ret_key} has n={rl_tab.get(ret_key, {}).get('n', 0)} < {C.MIN_N}: merged up to {used} (n={rl_tab[used]['n']})")
                res = grp
            if centre is not None and res is not None:
                # Addendum H1: margin_target is the margin LEVEL five years on, drawn directly.  Its median is on the engine's own retention curve at year 5
                # (the curve the chain moves along: the band's curve, the normalization curve of the score for the commodity family), centre + r_5 x dev, and
                # its spread is the measured residual of the level five years on about the median-retention path.  No rescale.
                cv_eng, cv_src = cv, f"band {ret_key} curve"
                if family == "commodity" and score is not None:
                    try:
                        cv_eng, cv_src = self._normalization_ref(T, ft, score, meta["cyc_score_basis"], [])(score, HORIZON), "normalization curve of the cyclicality score"
                    except DataNotPresent:
                        pass
                r5 = cv_eng.at(CURVE_REF_YEAR) if cv_eng is not None else None
                dev = ft.get("dev")
                if r5 is not None:
                    shift = r5 * (0.0 if dev is None else dev)
                    qd = _qd(res, centre + shift, src)
                    if qd is not None:
                        inputs["margin_target"] = qd
                        meta["cells"]["margin_target"] = {
                            "band": ret_key, "residual_cell": used, "n": res["n"], "centre_8y_median": centre, "dev": dev, "r5": r5, "r5_source": cv_src, "level5_median": centre + shift,
                            "level_band": {"level": ft.get("m"), "band": res.get("band"), "lower": res.get("lower"), "upper": res.get("upper"), "merged": res.get("merged")},
                            "p10_p90_width": qd.ppf(0.9) - qd.ppf(0.1),
                            "note": "the margin level 5 years on: the company's 8-year median + r_5 x its deviation + the measured residual of the company's CURRENT margin band "
                                    "(Addenda H1, I1)"}
        if "margin_retention" not in curves:
            unavailable.append("margin_retention: no measured curve")
        if "margin_target" not in inputs and not any(u.startswith("margin_target:") for u in unavailable):
            unavailable.append("margin_target: no centre (no margin) or no residual spread")
        # ronic (Addendum H3): the ROIC LEVEL five years on.  The company's own trailing 3-year ROIC (L0) fades along the measured retention of ROIC's excess to the
        # median ROIC I of its industry at T, so the median level five years on is I + phi_5 (L0 - I); the spread is the measured dispersion of the ROIC level path
        # about that median path (T["roic_level"]), not of incremental ROIC.  The engine moves L0 -> that level along the curve's shape, holds it, and ends in
        # perpetuity at WACC + kappa (I - WACC), kappa the plateau of that retention curve (Addendum J3), floored at WACC only where the formula goes below it.
        rl = T.get("roic_level")
        L0, ind = ft.get("roic3"), ft.get("industry_roic")
        if not rl or not rl.get("bands"):
            unavailable.append("ronic: this vintage has no roic_level table (priors version < 2)")
        elif L0 is None:
            unavailable.append("ronic: no trailing 3-year ROIC for the company (three consecutive fiscal years with NOPAT and positive invested capital)")
        elif ind is None:
            unavailable.append("ronic: no industry median ROIC at T was supplied (the population of the date)")
        else:
            I = ind["value"]
            gap = L0 - I
            key = "pos" if gap >= rl["min_abs_gap"] else ("neg" if gap <= -rl["min_abs_gap"] else "all")
            bd = rl["bands"].get(key)
            if bd is None or bd.get("n", 0) < C.MIN_N:
                fallbacks.append(f"ronic: band {key} too thin in this vintage: the sign-pooled ROIC retention")
                bd, key = rl["bands"].get("all"), "all"
            cv = _curve_from_rows(bd["ks"], "median", "n", "ronic_fade", src, flags) if bd else None
            res, used_r = None, None
            lv_tab = rl.get("residual_k5_by_level")
            if lv_tab is None:
                unavailable.append("ronic: this vintage has no level-conditional ROIC residual table (priors version < 3)")
            else:
                ns = []
                for k in ([key] + (["all"] if key != "all" else [])):
                    g_, n_ = _level_group(lv_tab.get(k), L0)
                    ns.append(f"{k} n={n_}")
                    if g_ is not None:
                        res, used_r = g_, k
                        break
                if res is None:
                    unavailable.append(f"ronic: no ROIC residual cell with n >= {C.MIN_N} after the stated merges ({'; '.join(ns)})")
                elif used_r != key:
                    fallbacks.append(f"ronic: residual cell {key} has n={lv_tab.get(key, {}).get('n', 0)} < {C.MIN_N}: merged to {used_r} (n={lv_tab[used_r]['n']})")
            if cv is None or res is None:
                if cv is None:
                    unavailable.append("ronic: no measured ROIC retention curve in this vintage")
            else:
                phi5 = cv.at(CURVE_REF_YEAR)
                centre5 = I + phi5 * gap
                qd = _qd(res, centre5, src)
                if qd is None:
                    unavailable.append("ronic: the residual spread has too few observations for P10/P50/P90")
                else:
                    inputs["ronic"] = qd
                    curves["ronic_fade"] = cv
                    k_used = 0
                    for r_ in bd["ks"]:
                        if r_.get("median") is None or r_.get("n", 0) < C.MIN_N:
                            break
                        k_used = r_["k"]
                    meta["cells"]["ronic_fade"] = {"plateau": cv.values[-1], "plateau_k": k_used, "plateau_n": next(r_["n"] for r_ in bd["ks"] if r_["k"] == k_used), "band": key,
                                                   "note": "Addendum J3: the terminal return on new capital is WACC + this plateau x (the industry median ROIC - WACC), floored at WACC where the formula goes below it"}
                    meta["cells"]["ronic"] = {"band": key, "residual_cell": used_r, "n": res.get("n"), "L0_trailing_3y_roic": L0, "industry_median_roic": I, "industry_basis": ind.get("basis"),
                                              "industry_n": ind.get("n"), "phi5": phi5, "level5_median": centre5, "p10_p90_width": qd.ppf(0.9) - qd.ppf(0.1),
                                              "level_band": {"level": L0, "band": res.get("band"), "lower": res.get("lower"), "upper": res.get("upper"), "merged": res.get("merged")},
                                              "note": "ROIC level five years on: I + phi_5 (L0 - I) with the measured residual of the company's CURRENT ROIC band (Addenda H3, I1)"}
                    flags.append("ronic_fade: the measured retention of ROIC's excess over the same-year population median (the date's industry median applies it in the engine)")
        if "ronic_fade" not in curves:
            unavailable.append("ronic_fade: no measured curve")
        # references
        refs["ev_fcf_multiple"] = self._ev_fcf_ref(T, ft)
        refs["normalization_curve"] = self._normalization_ref(T, ft, score, meta["cyc_score_basis"], flags)
        if family == "commodity":
            # the commodity engine's margin-retention curve is the normalization curve of the company's score: its position distribution is the quintile
            # bands' distributions interpolated quantile by quantile at that score (the median interpolates the way the curve does)
            pdist = self._normalization_position(T, score, src)
            if pdist is not None:
                positions["margin_retention"] = pdist

    def _financial(self, T, ft, inputs, curves, refs, meta, fallbacks, unavailable, flags, src, positions):
        fam = "financial"
        cell, basis, pooled = self._g1_cell(T, fam, ft, None, None, "g1", fallbacks)
        if cell is None or cell["n"] < C.MIN_N:
            unavailable.append("g1: no tangible-book growth delivered or no cell with enough observations in this vintage")
        else:
            qd = _qd(cell, 0.0, src)
            if qd is None:
                unavailable.append("g1: cell too thin")
            else:
                inputs["g1"] = qd
                meta["cells"]["g1"] = {k: cell[k] for k in ("n", "merged_rows", "merged_cols", "thin", "baseline_growth_median", "baseline_mae") if k in cell}
                meta["cells"]["g1"]["basis"] = basis
        gd = T["growth_decay"].get(fam)
        gv = ft.get("tg3") if ft.get("tg3") is not None else ft.get("tg_latest")
        if gd and gd.get("buckets") and gv is not None:
            gb = _bucket(gv, T["edges"]["growth"])
            bk = next((b for b in gd["buckets"] if b["bucket"][0] <= gb <= b["bucket"][1]), None)
            cv = _curve_from_rows(bk["ks"], "ratio_median", "n_ratio", "growth_decay", src, flags) if bk else None
            if cv is not None:
                curves["growth_decay"] = cv
                positions["growth_persistence"] = _pos_dist(_pos_row(bk["ks"], "ratio_median", "n_ratio"), "ratio_q", src)
        if "growth_decay" not in curves:
            unavailable.append("growth_decay: no tangible-book growth delivered or no measured curve")
        rr = T["rote_retention"]
        key = "all"
        if ft.get("rote_dev") is not None and abs(ft["rote_dev"]) >= 0.005:
            key = "pos" if ft["rote_dev"] > 0 else "neg"
        bd = rr["bands"].get(key)
        if bd is None or bd["n"] < C.MIN_N:
            bd, key = rr["bands"].get("all"), "all"
            fallbacks.append("rote_retention: signed band too thin: sign-pooled curve")
        centre = ft.get("rote_med8")
        if centre is None:
            centre = ft.get("rote")
            fallbacks.append("rote_target: fewer than 5 ROTE years: centred on the latest ROTE")
        if bd is not None:
            cv = _curve_from_rows(bd["ks"], "median", "n", "rote_retention", src, flags)
            if cv is not None:
                curves["rote_retention"] = cv
                positions["rote_retention"] = _pos_dist(_pos_row(bd["ks"], "median", "n"), "q", src)
            # Addendum I5: the residual cell of the sign band, merged to the sign-pooled cell when under MIN_N, refused when that is under MIN_N too
            res, used_t = None, None
            ns = []
            for k in ([key] + (["all"] if key != "all" else [])):
                c_ = rr["residual_k5"].get(k)
                ns.append(f"{k} n={0 if not c_ else c_.get('n', 0)}")
                if c_ is not None and c_.get("n", 0) >= C.MIN_N:
                    res, used_t = c_, k
                    break
            if res is None:
                unavailable.append(f"rote_target: no residual cell with n >= {C.MIN_N} after the stated merges ({'; '.join(ns)})")
            elif used_t != key:
                fallbacks.append(f"rote_target: residual cell {key} has n={(rr['residual_k5'].get(key) or {}).get('n', 0)} < {C.MIN_N}: merged to {used_t} (n={res['n']})")
            if centre is not None and res is not None:
                qd = _qd(res, centre, src)
                if qd is not None:
                    inputs["rote_target"] = qd
                    meta["cells"]["rote_target"] = {"band": key, "residual_cell": used_t, "n": res["n"], "centre": centre}
        for k in ("rote_retention",):
            if k not in curves:
                unavailable.append(f"{k}: no measured curve")
        if "rote_target" not in inputs and not any(u.startswith("rote_target:") for u in unavailable):
            unavailable.append("rote_target: no centre or no residual spread")
        ef = T.get("excess_fade_financial")
        if ef:
            cv = _curve_from_rows(ef["ks"], "median", "n", "excess_fade", src, flags)
            if cv is not None:
                curves["excess_fade"] = cv
                flags.append("excess_fade: a measured PROXY: the retention of ROTE's excess over the population median ROTE, not the fade toward the cost of equity")
                k_used = 0
                for r in ef["ks"]:
                    if r.get("median") is None or r.get("n", 0) < C.MIN_N:
                        break
                    k_used = r["k"]
                meta["cells"]["excess_fade"] = {"plateau": cv.values[-1], "plateau_k": k_used, "plateau_n": next(r["n"] for r in ef["ks"] if r["k"] == k_used),
                                                "note": "Addendum I4: the terminal excess of the financial engine is the industry median's excess x this plateau (the value at the longest k with n >= 50)"}
        if "excess_fade" not in curves:
            unavailable.append("excess_fade: no measured curve")
        refs["ptbv_of_rote"] = self._ptbv_ref(T)

    # -- references --
    @staticmethod
    def _ev_fcf_ref(T, ft):
        ev = T["ev_fcf"]
        rb = _band(ft.get("roic"), ev.get("roic_cuts") or [])

        def f(state, draw, disc) -> Optional[float]:
            """The population's median EV / FCFF1 at the draw's year-1 growth and the company's return-on-capital tercile (survivors; a cross-check reference)."""
            if rb < 0 or not ev.get("cells"):
                return None
            gb = _bucket(draw.get("g1"), ev["edges_growth"])
            cell = _find_cell(ev["cells"], gb, rb)
            if cell is None or cell.get("n", 0) < C.MIN_N or cell.get("p50") is None:
                return None
            return float(cell["p50"])
        f.n_cells = len(ev.get("cells") or [])
        return f

    @staticmethod
    def _ptbv_ref(T):
        groups = [g for g in T["ptbv"]["groups"] if g.get("p50") is not None and g.get("rote_median") is not None and g["n"] >= C.MIN_N]

        def f(rote: float, coe: float, g: float) -> Optional[float]:
            """The population's median price / tangible book at this ROTE: linear between the group medians (by median ROTE), flat beyond the ends."""
            if not groups or rote is None:
                return None
            xs = [x["rote_median"] for x in groups]
            ys = [x["p50"] for x in groups]
            return float(np.interp(rote, xs, ys))
        f.n_groups = len(groups)
        return f

    @staticmethod
    def _normalization_position(T, score, src):
        pts = []
        for b in T["normalization"]["bands"]:
            if b["score_median"] is None or b["all"]["n"] < C.MIN_N:
                continue
            d = _pos_dist(_pos_row(b["all"]["ks"], "median", "n"), "q", src)
            if d is not None:
                pts.append((b["score_median"], dict(d.q)))
        if not pts or score is None:
            return None
        xs = [p[0] for p in pts]
        qs = {}
        for lv in LEVELS:
            if all(lv in q for _, q in pts):
                qs[lv] = float(np.interp(score, xs, [q[lv] for _, q in pts]))
        return QuantileDist(qs, src) if all(x in qs for x in (0.10, 0.50, 0.90)) else None

    @staticmethod
    def _normalization_ref(T, ft, score, score_basis, flags):
        nb = T["normalization"]["bands"]
        use = [b for b in nb if b["score_median"] is not None and b["all"]["n"] >= C.MIN_N]
        fl: List[str] = []
        curves = []
        for b in use:
            cv = _curve_from_rows(b["all"]["ks"], "median", "n", f"normalization_q{b['band']}", "", fl)
            if cv is not None:
                curves.append((b["score_median"], cv.values))
        if fl:
            flags.append("normalization_curve: " + "; ".join(fl)[:300])

        def f(s: float, horizon: int = HORIZON) -> Curve:
            """The margin-retention curve for a cyclicality score: the quintile curves interpolated at the score (flat beyond the end quintiles).  When the
            vintage adopted fitted weights, the company's own weighted score (from its state components) replaces the engine's equal-weight score."""
            if not curves:
                raise DataNotPresent("no normalization curve measured in this vintage")
            sc = score if score is not None else s
            xs = [c[0] for c in curves]
            vals = []
            for k in range(horizon):
                ys = [c[1][min(k, len(c[1]) - 1)] for c in curves]
                vals.append(float(np.interp(sc, xs, ys)))
            return Curve(vals, "normalization", f"measured by cyclicality score ({score_basis})")
        f.n_bands = len(curves)
        return f

    @staticmethod
    def _baseline(family, T, ft) -> dict:
        """The mechanical baseline: growth year 1 = the trailing 3-year CAGR (latest year where fewer than four are held), margin held."""
        if family == "financial":
            g = ft.get("tg3") if ft.get("tg3") is not None else ft.get("tg_latest")
            return {"g1": g, "g1_basis": "trailing 3-year CAGR of tangible book" if ft.get("tg3") is not None else "latest-year tangible-book growth",
                    "rote_held": ft.get("rote"), "population_error": T["baseline"].get("g1")}
        g = ft.get("g3") if ft.get("g3") is not None else ft.get("g_latest")
        return {"g1": g, "g1_basis": "trailing 3-year CAGR" if ft.get("g3") is not None else "latest-year growth", "margin_held": ft.get("m"),
                "population_error": T["baseline"]}


def state_median(ft: dict) -> Optional[float]:
    """The margin to centre on when no 8-year median can be formed: the margin held."""
    return ft.get("m")
