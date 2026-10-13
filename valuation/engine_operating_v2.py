"""engine_operating_v2.py - engine v2 for operating companies (SPEC_engine_v2.md, approved 2026-10-11).

What differs from v1 (`engine_operating`, frozen at c7d7a4f and not edited):
  years 1-3   revenue growth and the operating margin are drawn inputs: log growth `nt_lgrowth_k` (g = exp(z) - 1, Addendum AL.1) and `nt_margin_k`
              (valuation/near_term.py: base-rate centres + the measured residuals of v2's own forecasts, joined to v1's Gaussian copula)
  years 4-5   growth_t = g_T + (g_3 - g_T) d_t / d_3; margin_t = m_3 + (m_5 - m_3) (w_t - w_3) / (1 - w_3) on v1's own level-path weights w (clipped as v1
              clips them; Addendum AL.1 4), m_5 when w_3 = 1
  any year    growth at or below -100% is an invalid draw (never repaired; counted by `simulate`)
  after       v1 unchanged (margin m_5; the decay path; the ROIC path H3, reinvestment priced at m_5, maintenance, the I2 rules, the terminal value, the
              equity bridge and floor)
WHY THE CHAIN IS A COPY (Addendum AK.6): v1's loop computes each year's growth and margin inline; replacing years 1-5 needs its own loop.  Every line other than
the growth and margin of years 1-5 is v1's, and `test_engine_v2` proves the copy: with the near-term draws equal to v1's own year-1..3 path the v2 chain
reproduces v1's result exactly (algebraically, the years 4-5 continuation then equals v1's path).
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional

from . import engine_operating as v1
from . import near_term as nt
from .common import (Curve, DrawInvalid, EQUITY_FLOOR_RULE, InputError, LEVEL_REF_YEAR, MAX_HORIZON, CompanyPIT, TERMINAL_G_ANCHOR, build_state,
                     equity_bridge, level_path_weights, model_disagreement, simulate, terminal_growth_after, terminal_growth_rate)
from .discount_rate import DiscountRate
from .priors import features as prior_features

ENGINE = "operating_v2"
RULE_FLAT_DECAY = "v2: the growth-decay curve is 0 at year 3; growth after year 3 is terminal growth"
INVALID_GROWTH = "growth at or below -100% (revenue would not be positive)"
# Addendum AL.1 4: v1's level path reached m_5 by year 3 and (a non-monotone curve) moves back before year 5; the year-3 draw cannot carry v1's base margin,
# so v2 holds m_5 for years 4-5 (the one case where v2's continuation is not v1's path), stamped
RULE_HELD_AFTER_TARGET = "v2: the margin path reached m_5 by year 3 under a non-monotone retention curve; held at m_5 in years 4-5 (v1 would move back)"


def operating_chain_v2(st: dict, p: Dict[str, float], curves: Dict[str, Curve], disc: DiscountRate, *,
                       operating_leases_in_cash_flow: bool = True, maint_gap_floor: Optional[float] = 0.0, roll_forward: bool = True, detail: bool = False) -> dict:
    """v1's operating_chain with years 1-5 of growth and margin as in the module docstring.  p = {nt_lgrowth_1..3, nt_margin_1..3, g_terminal, margin_target, ronic}."""
    gd, mr, rfade = curves["growth_decay"], curves["margin_retention"], curves["ronic_fade"]
    N = len(gd)
    if N > MAX_HORIZON:
        raise InputError(f"horizon {N} exceeds {MAX_HORIZON} years")
    tax, wacc, coe = st["tax_rate"], disc.wacc, disc.coe
    gT, m5, ronic = p["g_terminal"], p["margin_target"], p["ronic"]
    wr, ronic_path = level_path_weights(rfade, N)
    wm, _wm_info = level_path_weights(mr, N)
    roic0, ind_med = st["roic3"], st["industry_roic"]["value"]
    if wacc <= gT:
        raise DrawInvalid("terminal growth is not below the discount rate")
    gap_raw = st["maint_gap_ratio"]
    gap = gap_raw if maint_gap_floor is None else max(gap_raw, maint_gap_floor)
    nwc = st["nwc_ratio"]
    rev_prev = st["revenue"]
    rows, pv_exp = [], 0.0
    fcff1 = None
    rules = []
    lr_margin_bad, lr_ronic_bad = m5 * (1.0 - tax) <= 0.0, ronic <= 0.0
    no_growth = lr_margin_bad or lr_ronic_bad
    if lr_margin_bad:
        rules.append(v1.RULE_NO_GROWTH_MARGIN)
    if lr_ronic_bad:
        rules.append(v1.RULE_NO_GROWTH_RONIC)
    if no_growth:
        rules.append(v1.RULE_NO_GROWTH)
    g3, m3, d3 = math.expm1(p["nt_lgrowth_3"]), p["nt_margin_3"], gd.at(3)
    w3 = wm[2]
    if d3 <= 0.0:
        rules.append(RULE_FLAT_DECAY)
    if w3 >= 1.0 - 1e-12 and min(wm[3:LEVEL_REF_YEAR]) < 1.0 - 1e-12:
        rules.append(RULE_HELD_AFTER_TARGET)
    unpriced_years = []
    margin_path = []
    for t in range(1, N + 1):
        if t <= 3:                                                                     # v2: drawn years 1-3
            g, m = math.expm1(p[f"nt_lgrowth_{t}"]), p[f"nt_margin_{t}"]
        else:                                                                          # v2: the measured shapes, continued from the year-3 draw
            g = gT + (g3 - gT) * gd.at(t) / d3 if d3 > 0.0 else gT
            m = (m3 + (m5 - m3) * (wm[t - 1] - w3) / (1.0 - w3)) if w3 < 1.0 - 1e-12 else m5
        if no_growth and t > LEVEL_REF_YEAR:
            g = min(g, 0.0)
        if g <= -1.0:
            raise DrawInvalid(INVALID_GROWTH)
        margin_path.append(m)
        rev = rev_prev * (1.0 + g)
        ebit = m * rev
        nopat = ebit - tax * max(ebit, 0.0)
        ronic_t = roic0 + (ronic - roic0) * wr[t - 1]
        reinv, priced = v1._growth_reinvestment(g, rev - rev_prev, m5, tax, ronic_t, nwc)
        if not priced:
            unpriced_years.append(t)
        maint = gap * rev
        fcff = nopat - reinv - maint
        df = (1.0 + wacc) ** (-t)
        pv_exp += fcff * df
        if t == 1:
            fcff1 = fcff
        if detail:
            rows.append({"t": t, "growth": g, "revenue": rev, "margin": m, "ebit": ebit, "nopat": nopat, "ronic": ronic_t,
                         "growth_reinvestment": reinv, "maintenance_gap": maint, "fcff": fcff, "discount_factor": df, "pv": fcff * df})
        rev_prev = rev
        g_last = g
    if unpriced_years:
        rules.append(v1.RULE_UNPRICED_EARLY)
    if no_growth:
        gT, gT_basis = ((g_last, "decay path reached a negative rate by the last explicit year: that rate continues") if g_last < 0.0
                        else (0.0, "no growth: the long-run NOPAT margin or the return on new capital of the draw is not positive (Addendum I2)"))
    else:
        gT, gT_basis = terminal_growth_after(g_last, gT)
    if wacc <= gT:
        raise DrawInvalid("terminal growth is not below the discount rate")
    rev_T = rev_prev * (1.0 + gT)
    ebit_T = m5 * rev_T
    nopat_T = ebit_T - tax * max(ebit_T, 0.0)
    kappa = rfade.values[-1]
    ronic_formula = wacc + kappa * (ind_med - wacc)
    ronic_TV = max(ronic_formula, wacc)
    reinv_T, priced_T = v1._growth_reinvestment(gT, rev_T - rev_prev, m5, tax, ronic_TV, nwc)
    if not priced_T:
        raise DrawInvalid("terminal growth reinvestment cannot be priced")
    fcff_T = nopat_T - reinv_T - gap * rev_T
    tv = fcff_T / (wacc - gT)
    pv_tv = tv * (1.0 + wacc) ** (-N)
    ev = pv_exp + pv_tv
    tv_share = (pv_tv / ev) if ev != 0 else None
    br = equity_bridge(ev, st, operating_leases_in_cash_flow=operating_leases_in_cash_flow)
    yrs = v1.years_between(st["base_period"], disc.asof) if roll_forward else 0.0
    factor = (1.0 + coe) ** yrs
    eq_raw = br["equity_value"] * factor
    if eq_raw < 0.0:
        rules.append(EQUITY_FLOOR_RULE)
    out = {"ev": ev, "equity": max(eq_raw, 0.0), "equity_unfloored": eq_raw, "equity_at_base_year_end": max(br["equity_value"], 0.0), "rules": rules,
           "roll_forward_years": yrs, "roll_forward_factor": factor, "tv_share": tv_share, "pv_explicit": pv_exp, "pv_terminal": pv_tv, "terminal_value": tv,
           "fcff_terminal_year": fcff_T, "terminal_reinvestment_rate": (reinv_T / nopat_T) if nopat_T > 0 else None,
           "maint_gap_ratio_raw": gap_raw, "maint_gap_ratio_used": gap, "bridge": br, "fcff1": fcff1, "margin_path": margin_path, "ronic_path": ronic_path, "ronic_terminal": ronic_TV,
           "ronic_terminal_kappa": kappa, "ronic_terminal_floored_at_wacc": ronic_formula < wacc,
           "terminal_growth": {"value": gT, "basis": gT_basis}}
    if detail:
        out["years"] = rows
    return out


def run(pit: CompanyPIT, priors, disc: DiscountRate, near_term_table: Mapping, *, n_draws: int = 2000, seed: int = 20261006, corr=None,
        price_per_share: Optional[float] = None, operating_leases_in_cash_flow: bool = True, maint_gap_floor: Optional[float] = 0.0, roll_forward: bool = True,
        state: Optional[dict] = None, deviations: Optional[Mapping] = None) -> dict:
    """Value one company with engine v2: v1's state, priors, gaps and refusals; years 1-3 from valuation/near_term.py; the v2 chain."""
    st = state if state is not None else build_state(pit)
    gaps = v1.state_gaps(st)
    if gaps:
        return v1.refusal(ENGINE, [f"not available: {g}" for g in gaps], ticker=pit.ticker, asof=st.get("asof"))
    ps = priors.for_company("operating", st, pit.asof)
    miss = [k for k in v1.INPUTS if k not in ps.inputs] + [k for k in v1.CURVES if k not in ps.curves]
    if miss:
        return v1.refusal(ENGINE, [f"priors do not supply: {miss}"], ticker=pit.ticker)
    curves = dict(ps.curves)
    ref = ps.refs.get("ev_fcf_multiple")
    g_term = terminal_growth_rate(disc.rf)
    try:
        ndists, ncorr, info = nt.near_term_inputs("operating", st, ps, g_term, near_term_table, prior_features(st, "operating"), deviations)
    except nt.NearTermRefusal as e:
        return v1.refusal(ENGINE, e.reasons, ticker=pit.ticker)
    dists = {k: v for k, v in ps.inputs.items() if k != "g_terminal"}
    dists.update(ndists)
    allcorr = dict(corr or {})
    allcorr.update(ncorr)
    allcorr = nt.checked_corr(sorted(dists), allcorr, info)

    def chain(draw):
        draw = dict(draw, g_terminal=g_term)
        mult = ref(st, draw, disc) if ref is not None else None
        r = operating_chain_v2(st, draw, curves, disc, operating_leases_in_cash_flow=operating_leases_in_cash_flow, maint_gap_floor=maint_gap_floor,
                               roll_forward=roll_forward)
        if ref is not None:
            if mult is None:
                r["secondary_equity"], r["secondary_reason"] = None, "population multiple not defined for this draw"
            elif r["fcff1"] is None or r["fcff1"] <= 0:
                r["secondary_equity"], r["secondary_reason"] = None, "year-1 FCFF not positive"
            else:
                sb = equity_bridge(mult * r["fcff1"], st, operating_leases_in_cash_flow=operating_leases_in_cash_flow)
                r["secondary_equity"] = sb["equity_value"] * r["roll_forward_factor"]
        return r

    dist = simulate(chain, dists, n_draws, seed, allcorr or None, price_per_share, st.get("shares_outstanding"))
    mid = dict(v1._median_point(dists), g_terminal=g_term)
    try:
        at_median = operating_chain_v2(st, mid, curves, disc, operating_leases_in_cash_flow=operating_leases_in_cash_flow, maint_gap_floor=maint_gap_floor,
                                       roll_forward=roll_forward, detail=True)
    except DrawInvalid as e:
        at_median = {"invalid": str(e)}
    md, why = (None, "no secondary cross-check supplied by the priors")
    if dist["equity"] is not None and dist["secondary_equity"] is not None:
        md, why = model_disagreement(dist["equity"]["p50"], dist["secondary_equity"]["p50"])
    fy = info["forecast_years"]
    notes = []
    if st["read_as_none"]:
        notes.append("read as none: " + "; ".join(st["read_as_none"]))
    if disc.de_basis == "book":
        notes.append("discount rate uses the book D/E")
    return {"status": "ok", "engine": ENGINE, "engine_version": nt.ENGINE_VERSION, "family": "operating", "ticker": pit.ticker, "asof": st["asof"],
            "base_period": st["base_period"], "base_filed": st["base_filed"], "base_accession": st["base_accession"],
            "placeholder": bool(ps.placeholder or disc.placeholder), "prior_source": ps.source, "discount": disc.as_dict(), "distribution": dist,
            "at_median_inputs": at_median, "model_disagreement": md, "model_disagreement_note": why,
            "forecast_year1": {"growth": {p: fy["growth"][1][p] for p in ("p10", "p50", "p90")}, "margin": {p: fy["margin"][1][p] for p in ("p10", "p50", "p90")}},
            "forecast_years": fy, "near_term": {k: v for k, v in info.items() if k != "forecast_years"},
            "consistency": v1.capital_intensity_check(st, mid, disc), "cyclicality": st.get("cyclicality"),
            "inputs": {k: v.as_dict() for k, v in dists.items()},
            "terminal_growth": {"base": g_term, "rf": disc.rf, "anchor": TERMINAL_G_ANCHOR, "rule": "Addendum H2"}, "notes": notes}
