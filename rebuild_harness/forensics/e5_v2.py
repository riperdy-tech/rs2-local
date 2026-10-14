"""E5, the oracle for engine v2 (REGISTRATION_engine_v2 section 1; method registered in SPEC_rebuild Addendum AL.24).

Per valued operating or financial name, from the forensic run's capture of the v1 engine call (`analytics.CAP`: the state, the prior set, the discount rate)
and the name's realised first-reported chain (`rec["fx_out"]`), three point values per share on ONE information set (AL.24's fairness rule):
  * `v1_same`: v1's chain (`chains.op_chain` / `fin_chain`, equal to the engine's at the P50) with realised years 1..min(K, 3) only;
  * `v2`: engine v2's chain (`operating_chain_v2` / `financial_chain_v2`) at v2's median point with the near-term inputs of years 1..min(K, 3) set to the
    realised values (`nt_lgrowth_k` = log(1 + g_k), `nt_margin_k`, `nt_rote_k`);
  * both operating values take the realised year-5 margin as the long-run margin when K >= 5, the prior's P50 otherwise.  Financial tangible-book growth
    stays each engine's own P50 path.
Also `v2_p50`: v2's chain at its median point with no override, and `v1_p50`: v1's, for the parity check against the engines' own `at_median_inputs`.
Nothing here alters a value the engines produce; refusals of v2 (no table, an undersized cell) are recorded with their reasons."""
from __future__ import annotations

import math
from typing import Mapping, Optional

from valuation import near_term as nt
from valuation.common import DrawInvalid, InputError, terminal_growth_rate
from valuation.engine_financial_v2 import financial_chain_v2
from valuation.engine_operating_v2 import operating_chain_v2
from valuation.priors import features as prior_features

from . import analytics as A

K_MAX = 3


def _ps_value(r, shares) -> Optional[float]:
    return None if r is None or not shares else r["equity"] / shares


def realised(rec: dict, family: str) -> dict:
    """{g: {k: growth}, m: {k: margin}, rote: {k: ROTE}, m5: margin of year 5 or None}: AL.24's information set (k <= 3)."""
    p = A.oracle_paths(rec.get("fx_out"), family)
    cut = lambda d: {k: v for k, v in d.items() if k <= K_MAX}
    return {"g": cut(p["g"]), "m": cut(p["m"]), "rote": cut(p["rote"]), "m5": p["m"].get(5) if family != "financial" else None,
            "k": {"g": len(p["g"]), "m": len(p["m"]), "rote": len(p["rote"])}}


def v2_point(family: str, st: dict, ps, disc, table: Mapping, shares: float, over: Optional[dict] = None) -> dict:
    """Engine v2's point value at its median inputs, with `over` replacing named inputs.  {"ps": value per share or None, "reason": ...}."""
    g_term = terminal_growth_rate(disc.rf)
    try:
        ndists, _corr, _info = nt.near_term_inputs(family, st, ps, g_term, table, prior_features(st, family), None)
    except nt.NearTermRefusal as e:
        return {"ps": None, "reason": "; ".join(e.reasons)[:200]}
    dists = {k: v for k, v in ps.inputs.items() if k != "g_terminal"}
    dists.update(ndists)
    mid = {k: d.ppf(0.5) for k, d in dists.items()}
    mid["g_terminal"] = g_term
    if over:
        unknown = [k for k in over if k not in mid]
        if unknown:
            return {"ps": None, "reason": f"override of an input the engine does not draw: {unknown}"}
        mid.update(over)
    try:
        if family == "financial":
            r = financial_chain_v2(st, mid, ps.curves, disc)
        else:
            r = operating_chain_v2(st, mid, dict(ps.curves), disc)
    except (DrawInvalid, InputError, ZeroDivisionError, ValueError) as e:
        return {"ps": None, "reason": f"{type(e).__name__}: {str(e)[:160]}"}
    return {"ps": _ps_value(r, shares), "reason": None}


def values(cap, rec: dict, shares: float, table: Optional[Mapping]) -> dict:
    """The E5 record of one name (see the module docstring)."""
    fam, st, ps, disc = cap.family, cap.st, cap.ps, cap.disc
    if fam not in ("operating", "financial"):
        return {"family": fam, "skipped": "family out of E5's scope"}
    rz = realised(rec, fam)
    out = {"family": fam, "k": rz["k"]}
    pm = A.PointModel(fam, ps, disc, st, shares)
    out["v1_p50"] = pm.ps_value(pm.run())
    if fam == "financial":
        out["v1_same"] = pm.ps_value(pm.run(rp_over=rz["rote"])) if rz["rote"] else None
    else:
        lr = {"margin_target": rz["m5"]} if rz["m5"] is not None else {}
        out["v1_same"] = pm.ps_value(pm.run(lr, g_over=rz["g"], m_over=rz["m"])) if (rz["g"] and rz["m"]) else None
    if table is None:
        out["v2_reason"] = "no near-term table for the vintage"
        return out
    p = v2_point(fam, st, ps, disc, table, shares)
    out["v2_p50"], out["v2_p50_reason"] = p["ps"], p["reason"]
    over = {}
    if fam == "financial":
        over.update({nt.name("rote", k): v for k, v in rz["rote"].items()})
        ok = bool(rz["rote"])
    else:
        bad = [k for k, g in rz["g"].items() if g <= -1.0]
        over.update({nt.name("growth", k): math.log1p(g) for k, g in rz["g"].items() if g > -1.0})
        over.update({nt.name("margin", k): m for k, m in rz["m"].items()})
        if rz["m5"] is not None:
            over["margin_target"] = rz["m5"]
        ok = bool(rz["g"]) and bool(rz["m"]) and not bad
    if not ok:
        out["v2"], out["v2_reason"] = None, "no realised year 1 (or growth at or below -100%)"
        return out
    q = v2_point(fam, st, ps, disc, table, shares, over)
    out["v2"], out["v2_reason"] = q["ps"], q["reason"]
    return out


def _envelope_prior(ps):
    """PROTOTYPE for AL.25 (diagnostic, not the engine): the prior set with `growth_decay` replaced by its running minimum (non-increasing), so a year-3
    deviation can never be amplified after year 3."""
    import copy
    from valuation.common import Curve
    gd = ps.curves["growth_decay"]
    vals, env, m = list(gd.values), [], float("inf")
    for v in vals:
        m = min(m, v)
        env.append(m)
    q = copy.copy(ps)
    q.curves = dict(ps.curves, growth_decay=Curve(env, gd.name, getattr(gd, "source", "") + " | running-min envelope (AL.25 prototype)"))
    return q


def v2_distribution(cap, table: Optional[Mapping], shares: float, n_draws: int = 2000, seed: int = 20261006, envelope: bool = False) -> dict:
    """DIAGNOSTIC (Addendum AL.25): engine v2's full run on the captured state, beside v1's own: the invalid-draw share and the per-share P10/P50/P90/mean.
    Reads no outcome."""
    from valuation import engine_financial_v2 as f2, engine_operating_v2 as o2
    if cap.family not in ("operating", "financial") or table is None:
        return {"skipped": True}

    class _Fixed:                                                       # the prior set the v1 run used, handed to v2 unchanged
        def __init__(self, ps):
            self._ps = ps

        def for_company(self, family, state, asof):
            return self._ps
    mod = o2 if cap.family == "operating" else f2
    kept = []
    orig_sim = mod.simulate

    def sim(chain_fn, dists, n, sd, corr=None, price_per_share=None, sh=None):     # records each valid draw's equity (the module's own simulate runs unchanged)
        def wrapped(draw):
            out = chain_fn(draw)
            kept.append(out["equity"])
            return out
        return orig_sim(wrapped, dists, n, sd, corr, price_per_share, sh)
    mod.simulate = sim
    try:
        r = mod.run(cap.pit, _Fixed(_envelope_prior(cap.ps) if envelope else cap.ps), cap.disc, table, n_draws=n_draws, seed=seed, state=cap.st)
    finally:
        mod.simulate = orig_sim
    if r.get("status") != "ok":
        return {"status": r.get("status"), "reasons": [str(x)[:120] for x in (r.get("reasons") or [])][:3]}
    d = r["distribution"]
    eq, ev = d.get("equity") or {}, d.get("ev") or {}
    per = {k: (eq.get(k) / shares if eq.get(k) is not None and shares else None) for k in ("p10", "p50", "p90", "mean")}
    top = None
    if kept and sum(kept) > 0:
        ks = sorted(kept, reverse=True)
        top = sum(ks[:max(1, len(ks) // 100)]) / sum(ks)
    return {"status": "ok", "n_invalid": d["n_invalid"], "n_draws": d["n_draws"], "invalid_reasons": d["invalid_reasons"], **{f"ps_{k}": v for k, v in per.items()},
            "ev_p10": ev.get("p10"), "ev_p50": ev.get("p50"), "ev_p90": ev.get("p90"), "ev_mean": ev.get("mean"), "share_floored": d.get("share_negative_equity"),
            "top1pct_share_of_mean": top}

