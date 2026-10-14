"""engine_financial_v2.py - engine v2 for financial companies (SPEC_engine_v2.md, approved 2026-10-11).

What differs from v1 (`engine_financial`, frozen at c7d7a4f and not edited):
  years 1-3   tangible-book growth, drawn as log growth `nt_ltbvg_k` (g = exp(z) - 1, Addendum AL.1), and the return on tangible equity after the fade toward the industry, `nt_rote_k` (the quantity v1's
              forecast_year1 reports as `rote`), are drawn inputs (valuation/near_term.py)
  years 4+    (v2.0.1, Addendum AL.27: d, rho and phi below are each the running minimum of the measured curve; v2.0 used the curves themselves)
              growth_t = g_T + (g_3 - g_T) d_t / d_3;  the pre-fade ROTE R_t = rT + (R*_3 - rT) rho_t / rho_3 with R*_3 = I + (ROTE'_3 - I) / phi_3 (the year-3 draw
              undone from its fade), and ROTE'_t = I + (R_t - I) phi_t; with phi_3 or rho_3 at 0 the path is rT (stamped)
  after       v1 unchanged (the terminal excess I4, the value, the roll-forward and the floor)
WHY THE CHAIN IS A COPY: as engine_operating_v2 (Addendum AK.6); `test_engine_v2` proves that with the near-term draws equal to v1's own path the result is v1's.
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional

from . import engine_financial as v1
from . import near_term as nt
from .common import (CompanyPIT, Curve, DrawInvalid, EQUITY_FLOOR_RULE, MAX_HORIZON, TERMINAL_G_ANCHOR, build_state, model_disagreement, simulate,
                     terminal_growth_after, terminal_growth_rate)
from .discount_rate import DiscountRate
from .engine_operating import refusal, years_between
from .priors import features as prior_features

ENGINE = "financial_v2"
RULE_FLAT_DECAY = "v2: the growth-decay curve is 0 at year 3; growth after year 3 is terminal growth"
INVALID_GROWTH = "tangible-book growth at or below -100% (tangible book would not be positive)"
RULE_FLAT_ROTE = "v2: the ROTE retention or the excess fade is 0 at year 3; ROTE after year 3 is the long-run level"
# Addendum AL.27 (v2.0.1): every continuation after year 3 uses the running minimum of its curve, so a year-3 deviation is never amplified (AL.25)
RULE_ENVELOPE = "v2.0.1: a continuation curve (growth decay, ROTE retention or excess fade) rises after a year; years 4+ use its running minimum"


def financial_chain_v2(st: dict, p: Dict[str, float], curves: Dict[str, Curve], disc: DiscountRate, *, roll_forward: bool = True, detail: bool = False) -> dict:
    gd, rho, phi = curves["growth_decay"], curves["rote_retention"], curves["excess_fade"]
    N = len(gd)
    if N > MAX_HORIZON:
        raise ValueError(f"horizon {N} exceeds {MAX_HORIZON} years")
    coe = disc.coe
    gT, rT = p["g_terminal"], p["rote_target"]
    if coe <= gT:
        raise DrawInvalid("terminal growth is not below the cost of equity")
    ind = st["industry_rote"]["value"]
    tbv_prev = st["tbv"]
    pv_exp, rows, rules = 0.0, [], []
    gde, rhoe, phie = nt.envelope(gd), nt.envelope(rho), nt.envelope(phi)              # AL.27: ratios <= 1 after year 3 (v2.0 used the curves themselves)
    if nt.rises(gd) or nt.rises(rho) or nt.rises(phi):
        rules.append(RULE_ENVELOPE)
    g3, d3 = math.expm1(p["nt_ltbvg_3"]), gde.at(3)
    rho3, phi3 = rhoe.at(3), phie.at(3)
    R3 = ind + (p["nt_rote_3"] - ind) / phi3 if phi3 > 0.0 else None
    if d3 <= 0.0:
        rules.append(RULE_FLAT_DECAY)
    if R3 is None or rho3 <= 0.0:
        rules.append(RULE_FLAT_ROTE)
    for t in range(1, N + 1):
        if t <= 3:
            g, Rp = math.expm1(p[f"nt_ltbvg_{t}"]), p[f"nt_rote_{t}"]
        else:
            g = gT + (g3 - gT) * gde.at(t) / d3 if d3 > 0.0 else gT
            R = rT + (R3 - rT) * rhoe.at(t) / rho3 if (R3 is not None and rho3 > 0.0) else rT
            Rp = ind + (R - ind) * phie.at(t)
        if g <= -1.0:
            raise DrawInvalid(INVALID_GROWTH)
        ri = (Rp - coe) * tbv_prev
        tbv = tbv_prev * (1.0 + g)
        df = (1.0 + coe) ** (-t)
        pv_exp += ri * df
        if detail:
            rows.append({"t": t, "growth": g, "rote_after_fade": Rp, "tbv_begin": tbv_prev, "excess_return": ri, "tbv_end": tbv, "discount_factor": df, "pv": ri * df})
        tbv_prev = tbv
        g_last = g
    gT, gT_basis = terminal_growth_after(g_last, gT)
    kappa = phi.values[-1]
    excess_T = kappa * max(ind - coe, 0.0)
    tv = excess_T * tbv_prev / (coe - gT)
    pv_tv = tv * (1.0 + coe) ** (-N)
    value = st["tbv"] + pv_exp + pv_tv
    yrs = years_between(st["base_period"], disc.asof) if roll_forward else 0.0
    factor = (1.0 + coe) ** yrs
    eq_raw = value * factor
    if eq_raw < 0.0:
        rules.append(EQUITY_FLOOR_RULE)
    pv_total_excess = pv_exp + pv_tv
    out = {"ev": value, "equity": max(eq_raw, 0.0), "equity_unfloored": eq_raw, "rules": rules, "equity_at_base_year_end": max(value, 0.0), "roll_forward_years": yrs,
           "roll_forward_factor": factor, "tv_share": (pv_tv / value) if value != 0 else None,
           "tbv_0": st["tbv"], "pv_explicit_excess": pv_exp, "pv_terminal_excess": pv_tv, "excess_share_of_value": pv_total_excess / value if value else None,
           "price_to_tbv_implied": value / st["tbv"], "terminal_growth": {"value": gT, "basis": gT_basis}, "terminal_rote": coe + excess_T,
           "terminal_excess_retention": kappa, "terminal_excess_industry_median_over_coe": ind - coe}
    if detail:
        out["years"] = rows
    return out


def run(pit: CompanyPIT, priors, disc: DiscountRate, near_term_table: Mapping, *, n_draws: int = 2000, seed: int = 20261006, corr=None,
        price_per_share: Optional[float] = None, roll_forward: bool = True, state: Optional[dict] = None, deviations: Optional[Mapping] = None) -> dict:
    st = state if state is not None else build_state(pit)
    gaps = v1.state_gaps(st)
    if gaps:
        return refusal(ENGINE, [f"not available: {g}" for g in gaps], ticker=pit.ticker, asof=st.get("asof"))
    ps = priors.for_company("financial", st, pit.asof)
    miss = [k for k in v1.INPUTS if k not in ps.inputs] + [k for k in v1.CURVES if k not in ps.curves]
    if miss:
        return refusal(ENGINE, [f"priors do not supply: {miss}"], ticker=pit.ticker)
    ref = ps.refs.get("ptbv_of_rote")
    g_term = terminal_growth_rate(disc.rf)
    try:
        ndists, ncorr, info = nt.near_term_inputs("financial", st, ps, g_term, near_term_table, prior_features(st, "financial"), deviations)
    except nt.NearTermRefusal as e:
        return refusal(ENGINE, e.reasons, ticker=pit.ticker)
    dists = {k: v for k, v in ps.inputs.items() if k != "g_terminal"}
    dists.update(ndists)
    allcorr = dict(corr or {})
    allcorr.update(ncorr)
    allcorr = nt.checked_corr(sorted(dists), allcorr, info)
    curves = ps.curves

    def chain(draw):
        draw = dict(draw, g_terminal=g_term)
        r = financial_chain_v2(st, draw, curves, disc, roll_forward=roll_forward)
        if ref is not None:
            m = ref(draw["rote_target"], disc.coe, draw["g_terminal"])
            if m is None:
                r["secondary_equity"], r["secondary_reason"] = None, "population price-to-tangible-book not defined for this draw"
            else:
                r["secondary_equity"] = m * st["tbv"] * r["roll_forward_factor"]
        return r

    dist = simulate(chain, dists, n_draws, seed, allcorr or None, price_per_share, st.get("shares_outstanding"))
    mid = dict({k: d.ppf(0.5) for k, d in dists.items()}, g_terminal=g_term)
    try:
        at_median = financial_chain_v2(st, mid, curves, disc, roll_forward=roll_forward, detail=True)
    except DrawInvalid as e:
        at_median = {"invalid": str(e)}
    md, why = None, "no secondary cross-check supplied by the priors"
    if dist["equity"] is not None and dist["secondary_equity"] is not None:
        md, why = model_disagreement(dist["equity"]["p50"], dist["secondary_equity"]["p50"])
    fy = info["forecast_years"]
    return {"status": "ok", "engine": ENGINE, "engine_version": nt.CHAIN_VERSION, "engine_interim": nt.INTERIM, "near_term_table_version": nt.ENGINE_VERSION, "family": "financial", "ticker": pit.ticker, "asof": st["asof"],
            "base_period": st["base_period"], "base_filed": st["base_filed"], "base_accession": st["base_accession"],
            "placeholder": bool(ps.placeholder or disc.placeholder), "prior_source": ps.source, "discount": disc.as_dict(), "distribution": dist,
            "at_median_inputs": at_median, "model_disagreement": md, "model_disagreement_note": why,
            "forecast_year1": {"rote": {p: fy["rote"][1][p] for p in ("p10", "p50", "p90")}, "growth": {p: fy["tbvg"][1][p] for p in ("p10", "p50", "p90")}},
            "forecast_years": fy, "near_term": {k: v for k, v in info.items() if k != "forecast_years"},
            "inputs": {k: v.as_dict() for k, v in dists.items()},
            "terminal_growth": {"base": g_term, "rf": disc.rf, "anchor": TERMINAL_G_ANCHOR, "rule": "Addendum H2"},
            "notes": ["return on tangible equity: net income / average tangible common equity; acquired-intangible amortization not added back"]}
