"""Per-name forensic analytics around the frozen engine (SPEC_rebuild Addendum U, Stage 1).  Called by forensics.run on the objects the registered `gate1.value_company` used for a name
(captured by wrapping the engine modules' `run` and `simulate`; the engine is called unchanged and its record is the registered record).  Everything returned is JSON-friendly.

0.0 is a value: every test is `is None`."""
from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

import numpy as np

from valuation import common
from valuation.common import DrawInvalid, build_state, terminal_growth_rate
from valuation.pit_data import is_num, to_date
from rebuild_harness import fundamentals
from . import chains

INPUT_KEYS = {"operating": ("g1", "margin_target", "ronic"), "commodity": ("g1", "margin_target", "ronic"), "financial": ("g1", "rote_target")}
G_GRID_OP = np.linspace(-0.60, 1.50, 43)
M_GRID_OP = np.linspace(-0.50, 0.80, 53)
G_GRID_FIN = np.linspace(-0.50, 1.00, 31)
R_GRID_FIN = np.linspace(-0.30, 0.60, 37)


def fnum(x):
    return None if x is None or not is_num(x) else float(x)


# ---- the realised (first-reported) fundamentals after the base year -------------------------------------------------------------------------

def realised_chain(pit, cik, base_fye, kmax=8) -> dict:
    """The first-reported fundamentals of the fiscal years after the base year, as in outcomes.fundamental_outcomes (consecutive years 350-380 days apart; a gap ends the chain), for k = 1..kmax:
    revenue, operating margin, return on tangible equity, tangible equity, net income, filing date.  OUTCOME DATA: it looks ahead by design and is read only by the forensic tests."""
    fys = pit.outcome_fiscal_years(cik)
    order = sorted(fys)
    out = {"base": None, "years": []}
    if base_fye not in fys:
        return out
    i = order.index(base_fye)
    chain = [fys[base_fye]]
    b = chain[0].row()
    out["base"] = {"fye": base_fye, "revenue": fnum(b.get("revenue")), "tbv": fnum(fundamentals.tangible_equity(b)), "operating_margin": fundamentals.operating_margin(b)}
    for step in range(1, kmax + 1):
        if i + step >= len(order):
            break
        nxt = fys[order[i + step]]
        gap = (to_date(nxt.fye) - to_date(chain[-1].fye)).days
        if not 350 <= gap <= 380:
            break
        row, prow = nxt.row(), chain[-1].row()
        out["years"].append({"k": step, "fye": nxt.fye, "filed": nxt.exists_from, "revenue": fnum(row.get("revenue")), "operating_margin": fundamentals.operating_margin(row),
                             "rote": fundamentals.rote(row, prow), "tbv": fnum(fundamentals.tangible_equity(row)), "net_income": fnum(row.get("net_income"))})
        chain.append(nxt)
    return out


def oracle_paths(real: Optional[dict], family: str) -> dict:
    """{g: {t: realised revenue (financial: tangible-book) growth}, m: {t: operating margin}, rote: {t: ROTE}} for the consecutive years from the base year with the measure defined."""
    g, m, ro = {}, {}, {}
    if not real or not real.get("base"):
        return {"g": g, "m": m, "rote": ro}
    key = "tbv" if family == "financial" else "revenue"
    prev = real["base"][key]
    for y in real["years"]:
        cur = y[key]
        if prev is not None and cur is not None and prev > 0 and cur > 0:
            g[y["k"]] = cur / prev - 1.0
        else:
            break
        prev = cur
    if family != "financial":
        for y in real["years"]:
            if y["operating_margin"] is not None:
                m[y["k"]] = y["operating_margin"]
            else:
                break
    for y in real["years"]:
        if y["rote"] is not None:
            ro[y["k"]] = y["rote"]
        else:
            break
    return {"g": g, "m": m, "rote": ro}


# ---- the population's P50 inputs of a date -----------------------------------------------------------------------------------------------

def population_p50(recs, preps, ctx, priors, mcap_floor) -> dict:
    """{family: {input: (median over the date's prepared names of mcap >= floor of the prior's P50, n)}}: the 'population P50' of the one-at-a-time swaps."""
    from valuation import gate1
    acc: Dict[str, Dict[str, list]] = {}
    for rec in recs:
        if rec["status"] != "prepared" or rec["market_cap"] is None or rec["market_cap"] < mcap_floor:
            continue
        prep = preps[rec["cik"]]
        try:
            pit = gate1.unpack(prep["blob"])
            st = build_state(pit)
            fam = prep["family"]
            ir = ctx.industry_return(prep["industry"], fam)
            if ir is not None:
                st["industry_roic" if fam != "financial" else "industry_rote"] = ir
            ps = priors.for_company(fam, st, pit.asof)
            if ps.source == "UNAVAILABLE":
                continue
            for k in INPUT_KEYS[fam]:
                if k in ps.inputs:
                    acc.setdefault(fam, {}).setdefault(k, []).append(ps.inputs[k].ppf(0.5))
        except Exception:
            continue
    return {fam: {k: (statistics.median(v), len(v)) for k, v in d.items()} for fam, d in acc.items()}


# ---- the capture of a name's engine run --------------------------------------------------------------------------------------------------

class Capture:
    """What the wrapped engine run saw: pit, priors set, discount, state, result, per-draw rows."""

    def __init__(self):
        self.clear()

    def clear(self):
        self.family = self.pit = self.ps = self.disc = self.st = self.res = None
        self.draws: List[tuple] = []


CAP = Capture()


def _slim_draw(kind, r):
    """(equity, PV of the terminal leg, the rest of the value as it enters equity before the roll-forward, the roll-forward factor, the leg the 50% cap is measured against).  Operating: rest = explicit PV +
    bridge items, cap leg = explicit PV (enterprise value without the terminal leg).  Financial: rest = cap leg = tangible book + explicit excess."""
    if kind == "financial":
        base0 = r["tbv_0"] + r["pv_explicit_excess"]
        return (r["equity"], r["pv_terminal_excess"], base0, r["roll_forward_factor"], base0)
    items = r["bridge"]["equity_value"] - r["ev"]
    return (r["equity"], r["pv_terminal"], r["pv_explicit"] + items, r["roll_forward_factor"], r["pv_explicit"])


def wrap_engines(gate1_module, op_module, fin_module):
    """Replace the engines' `simulate` (a name bound in each engine module) by a recorder and gate1.FAMILY_ENGINES by capturing wrappers.  The engine code runs unchanged."""
    orig_op, orig_fin = op_module.simulate, fin_module.simulate

    def make_sim(orig, kind):
        def sim(chain_fn, dists, n, seed, corr=None, price_per_share=None, shares=None):
            def wrapped(draw):
                r = chain_fn(draw)
                CAP.draws.append(_slim_draw(kind, r))
                return r
            return orig(wrapped, dists, n, seed, corr, price_per_share, shares)
        return sim

    op_module.simulate = make_sim(orig_op, "operating")
    fin_module.simulate = make_sim(orig_fin, "financial")

    class _Eng:
        def __init__(self, name, mod):
            self.name, self.mod = name, mod

        def run(self, pit, priors, disc, **kw):
            CAP.clear()
            CAP.family, CAP.pit, CAP.ps, CAP.disc, CAP.st = self.name, pit, getattr(priors, "_ps", None), disc, kw.get("state")
            res = self.mod.run(pit, priors, disc, **kw)
            CAP.res = res
            return res

    gate1_module.FAMILY_ENGINES = {k: _Eng(k, m) for k, m in gate1_module.FAMILY_ENGINES.items()}


# ---- point values -------------------------------------------------------------------------------------------------------------------------

class PointModel:
    """A name's point valuation at chosen inputs, through the engine's own chain (copied with overrides; verified equal to the engine's at the P50)."""

    def __init__(self, family, ps, disc, st, shares):
        self.family, self.st, self.disc, self.shares = family, st, disc, shares
        self.g_term = terminal_growth_rate(disc.rf)
        curves = dict(ps.curves)
        if family == "commodity":
            nc = ps.refs.get("normalization_curve")
            horizon = len(ps.curves["growth_decay"])
            curves["margin_retention"] = nc(st["cyclicality"]["score"], horizon)
        self.curves = curves
        self.p50 = {k: d.ppf(0.5) for k, d in ps.inputs.items() if k != "g_terminal"}
        self.p50["g_terminal"] = self.g_term
        self._wm = None

    def run(self, over=None, g_over=None, m_over=None, rp_over=None):
        p = dict(self.p50)
        if over:
            p.update(over)
        try:
            if self.family == "financial":
                return chains.fin_chain(self.st, p, self.curves, self.disc, g_over=g_over, rp_over=rp_over)
            return chains.op_chain(self.st, p, self.curves, self.disc, g_over=g_over, m_over=m_over)
        except (DrawInvalid, ZeroDivisionError, ValueError, KeyError):
            return None

    def ps_value(self, r):
        return None if r is None else r["equity"] / self.shares

    def growth_path(self, g1, n=5):
        gd = self.curves["growth_decay"]
        return [self.g_term + (g1 - self.g_term) * gd.at(t) for t in range(1, n + 1)]

    def margin_path(self, m5, n=5):
        wm, _ = common.level_path_weights(self.curves["margin_retention"], len(self.curves["growth_decay"]))
        m0 = self.st["op_margin"]
        return [m0 + (m5 - m0) * wm[t - 1] for t in range(1, n + 1)]


def own_state(family, st) -> dict:
    """The company's own state as the 'no change' value of each judgment input: latest growth, current margin, own 3-year ROIC (financial: tangible-book growth, ROTE)."""
    if family == "financial":
        ts = st.get("tbv_series") or {}
        ks = sorted(ts)
        g = None
        if len(ks) >= 2 and ks[-1] == st.get("base_period") and ts[ks[-2]] > 0 and ts[ks[-1]] > 0:
            g = ts[ks[-1]] / ts[ks[-2]] - 1.0
        return {"g1": g, "rote_target": fnum(st.get("rote_latest"))}
    return {"g1": fnum(st.get("growth_latest")), "margin_target": fnum(st.get("op_margin")), "ronic": fnum(st.get("roic3"))}


def solve_implied(f, grid, x0):
    """Root of f(x) = value(x) - price on `grid`: the sign change closest to x0, refined by bisection.  (x, status): status ok / no_root_value_above_price (value above the price on the
    whole grid) / no_root_value_below_price (value below the price everywhere) / undefined."""
    vals = []
    for x in grid:
        try:
            v = f(float(x))
        except Exception:
            v = None
        vals.append(v)
    ok = [(float(x), v) for x, v in zip(grid, vals) if v is not None and math.isfinite(v)]
    if len(ok) < 2:
        return None, "undefined"
    roots = []
    for (xa, va), (xb, vb) in zip(ok, ok[1:]):
        if va == 0.0:
            roots.append((xa, xa))
        elif va * vb < 0.0:
            roots.append((xa, xb))
    if not roots:
        return None, ("no_root_value_above_price" if min(v for _, v in ok) > 0 else "no_root_value_below_price")
    xa, xb = min(roots, key=lambda ab: abs(0.5 * (ab[0] + ab[1]) - x0))
    fa = f(xa)
    for _ in range(60):
        xm = 0.5 * (xa + xb)
        fm = f(xm)
        if fm is None or fa is None:
            break
        if fa * fm <= 0:
            xb = xm
        else:
            xa, fa = xm, fm
    return 0.5 * (xa + xb), "ok"


# ---- the draws ------------------------------------------------------------------------------------------------------------------------------

def draw_summary(draws, shares, price) -> dict:
    """Distribution summaries of the value per share over the engine's valid draws: mean and quantiles of the full value; the two terminal-value variants (the terminal leg capped at the rest of the
    enterprise value, i.e. at most 50% of it; the terminal leg removed); the share of draws above the price."""
    if not draws:
        return {}
    a = np.array(draws, dtype=float)
    eq, tv, base, fac, capleg = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    capped = np.maximum((base + np.minimum(tv, np.maximum(capleg, 0.0))) * fac, 0.0)
    notv = np.maximum(base * fac, 0.0)
    out = {}
    for lab, v in (("full", eq), ("cap50", capped), ("notv", notv)):
        p = v / shares
        out[lab] = {"p10": float(np.quantile(p, 0.10)), "p25": float(np.quantile(p, 0.25)), "p50": float(np.quantile(p, 0.50)), "p75": float(np.quantile(p, 0.75)),
                    "p90": float(np.quantile(p, 0.90)), "mean": float(p.mean())}
    p = eq / shares
    out["full"]["prob_above_price"] = float((p > price).mean()) if price is not None else None
    out["n_valid"] = int(len(eq))
    return out


def solvency_inputs(pit, st) -> dict:
    """Point-in-time balance-sheet and income items of the base year for the solvency score (F4): liquidity, leverage, coverage, cash-flow sign.  None where not filed."""
    try:
        r = pit.row(st["base_period"])
        periods = st.get("periods") or []
        pr = pit.row(periods[-2]) if len(periods) > 1 else {}
    except Exception:
        return {}
    return {"current_assets": fnum(r.get("current_assets")), "current_liabilities": fnum(r.get("current_liabilities")), "cash": fnum(st.get("cash")), "st_investments": fnum(st.get("st_investments")),
            "debt": fnum(st.get("debt")), "operating_income": fnum(r.get("operating_income")), "da": fnum(r.get("da")), "interest_expense": fnum(r.get("interest_expense")), "ocf": fnum(r.get("ocf")),
            "ocf_prev": fnum(pr.get("ocf")), "total_assets": fnum(r.get("total_assets")), "total_liabilities": fnum(r.get("total_liabilities")), "equity": fnum(r.get("equity")),
            "net_income": fnum(r.get("net_income")), "revenue": fnum(r.get("revenue")), "finance_leases": fnum(st.get("finance_lease_liability")), "tbv": fnum(st.get("tbv"))}


# ---- the whole record of a name --------------------------------------------------------------------------------------------------------------

def _sub(a, b):
    return None if a is None else a - b


def analyze(cap: Capture, rec: dict, pop: dict, price: float, shares: float) -> dict:
    """The forensic record of one valued name (see the module docstring)."""
    fam, st, disc, ps = cap.family, cap.st, cap.disc, cap.ps
    res = cap.res
    pm = PointModel(fam, ps, disc, st, shares)
    fx: dict = {"family": fam}
    base_run = pm.run()
    at = res.get("at_median_inputs") or {}
    chk = None
    if base_run is not None and "equity" in at:
        a, b = base_run["equity"], at["equity"]
        chk = bool(abs(a - b) <= 1e-9 * max(1.0, abs(b)))
    fx["chain_matches_engine"] = chk
    fx["point_p50_ps"] = pm.ps_value(base_run)
    if base_run is not None:
        py = base_run["pv_years"]
        ev = base_run["ev"]
        e15, fade, tvp = sum(py[:5]), sum(py[5:]), base_run["pv_terminal"]
        fx["pv"] = {"explicit_1_5": e15, "fade_6_N": fade, "terminal": tvp, "ev": ev, "N": base_run["N"], "net_items": base_run["net_items"], "factor": base_run["factor"]}
        if ev != 0:
            fx["pv"]["share_explicit_1_5"], fx["pv"]["share_fade"], fx["pv"]["share_terminal"] = e15 / ev, fade / ev, tvp / ev
    own = own_state(fam, st)
    swaps = {}
    for key in INPUT_KEYS[fam]:
        popv = (pop.get(fam) or {}).get(key)
        if popv is not None:
            swaps["pop_" + key] = pm.ps_value(pm.run({key: popv[0]}))
        if own.get(key) is not None:
            swaps["own_" + key] = pm.ps_value(pm.run({key: own[key]}))
    pall = {k: (pop.get(fam) or {}).get(k) for k in INPUT_KEYS[fam]}
    if all(v is not None for v in pall.values()):
        swaps["pop_all"] = pm.ps_value(pm.run({k: v[0] for k, v in pall.items()}))
    if all(own.get(k) is not None for k in INPUT_KEYS[fam]):
        swaps["own_all"] = pm.ps_value(pm.run({k: own[k] for k in INPUT_KEYS[fam]}))
    fx["swaps"] = swaps
    fx["p50_inputs"] = {k: pm.p50[k] for k in INPUT_KEYS[fam]}
    fx["own_inputs"] = own
    paths = oracle_paths(rec.get("fx_out"), fam)
    fx["oracle_k"] = {"g": len(paths["g"]), "m": len(paths["m"]), "rote": len(paths["rote"])}
    orc = {}
    if fam == "financial":
        if paths["rote"]:
            orc["rote"] = pm.ps_value(pm.run(rp_over=paths["rote"]))
        if paths["rote"] and paths["g"]:
            orc["rote_tbv"] = pm.ps_value(pm.run(rp_over=paths["rote"], g_over=paths["g"]))
        if paths["g"]:
            orc["tbv_growth_only"] = pm.ps_value(pm.run(g_over=paths["g"]))
    else:
        over = {"margin_target": paths["m"][5]} if 5 in paths["m"] else {}
        if paths["g"] and paths["m"]:
            orc["both"] = pm.ps_value(pm.run(over, g_over=paths["g"], m_over=paths["m"]))
        if paths["g"]:
            orc["growth_only"] = pm.ps_value(pm.run(g_over=paths["g"]))
        if paths["m"]:
            orc["margin_only"] = pm.ps_value(pm.run(over, m_over=paths["m"]))
    fx["oracle"] = orc
    impl = {"price": price}
    if price is not None and price > 0:
        if fam == "financial":
            gi, gs = solve_implied(lambda x: _sub(pm.ps_value(pm.run({"g1": x})), price), G_GRID_FIN, pm.p50["g1"])
            ri, rs = solve_implied(lambda x: _sub(pm.ps_value(pm.run({"rote_target": x})), price), R_GRID_FIN, pm.p50["rote_target"])
            impl.update({"g1_imp": gi, "g1_status": gs, "rote_imp": ri, "rote_status": rs})
        else:
            gi, gs = solve_implied(lambda x: _sub(pm.ps_value(pm.run({"g1": x})), price), G_GRID_OP, pm.p50["g1"])
            mi, ms = solve_implied(lambda x: _sub(pm.ps_value(pm.run({"margin_target": x})), price), M_GRID_OP, pm.p50["margin_target"])
            impl.update({"g1_imp": gi, "g1_status": gs, "m5_imp": mi, "m5_status": ms})
            if mi is not None:
                impl["m3_imp"] = pm.margin_path(mi, 3)[2]
            impl["m3_eng"] = pm.margin_path(pm.p50["margin_target"], 3)[2]
        if impl.get("g1_imp") is not None:
            impl["g_avg3_imp"] = float(np.mean(pm.growth_path(impl["g1_imp"], 3)))
        impl["g_avg3_eng"] = float(np.mean(pm.growth_path(pm.p50["g1"], 3)))
    fx["implied"] = impl
    fx["draws"] = draw_summary(cap.draws, shares, price)
    fx["solvency"] = solvency_inputs(cap.pit, st)
    return fx
