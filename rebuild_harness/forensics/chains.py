"""Point-value chains for the forensic tests: faithful copies of valuation.engine_operating.operating_chain and engine_financial.financial_chain with two additions, per-year OVERRIDES
(growth, margin, return on tangible equity) and a PV decomposition by year.  With no override the copies reproduce the engine's own functions exactly (tests/test_forensics_chains.py compares
ev, equity, pv_explicit, pv_terminal and the rules on real engine inputs).  The engine files are imported, never edited."""
from __future__ import annotations

from typing import Dict, Optional

from valuation.common import (DrawInvalid, EQUITY_FLOOR_RULE, LEVEL_REF_YEAR, MAX_HORIZON, InputError, equity_bridge, level_path_weights, terminal_growth_after)
from valuation.engine_operating import (RULE_NO_GROWTH, RULE_NO_GROWTH_MARGIN, RULE_NO_GROWTH_RONIC, RULE_UNPRICED_EARLY, _growth_reinvestment, years_between)


def op_chain(st: dict, p: Dict[str, float], curves, disc, *, g_over: Optional[dict] = None, m_over: Optional[dict] = None, maint_gap_floor: Optional[float] = 0.0,
             operating_leases_in_cash_flow: bool = True, detail: bool = False) -> dict:
    """operating_chain with `g_over` {t: growth of year t} and `m_over` {t: operating margin of year t} replacing the engine's own value in those years (t = 1..K).  Everything else, the
    long-run margin p['margin_target'] included, is the caller's.  Returns the engine's fields plus `pv_years` (PV of FCFF by year)."""
    g_over, m_over = g_over or {}, m_over or {}
    gd, mr, rfade = curves["growth_decay"], curves["margin_retention"], curves["ronic_fade"]
    N = len(gd)
    if N > MAX_HORIZON:
        raise InputError(f"horizon {N} exceeds {MAX_HORIZON} years")
    tax, wacc, coe = st["tax_rate"], disc.wacc, disc.coe
    g1, gT, m5, ronic = p["g1"], p["g_terminal"], p["margin_target"], p["ronic"]
    wm, _ = level_path_weights(mr, N)
    wr, _ = level_path_weights(rfade, N)
    roic0, ind_med = st["roic3"], st["industry_roic"]["value"]
    if wacc <= gT:
        raise DrawInvalid("terminal growth is not below the discount rate")
    m0 = st["op_margin"]
    gap_raw = st["maint_gap_ratio"]
    gap = gap_raw if maint_gap_floor is None else max(gap_raw, maint_gap_floor)
    nwc = st["nwc_ratio"]
    rev_prev = st["revenue"]
    pv_exp, fcff1 = 0.0, None
    rules = []
    lr_margin_bad, lr_ronic_bad = m5 * (1.0 - tax) <= 0.0, ronic <= 0.0
    no_growth = lr_margin_bad or lr_ronic_bad
    if lr_margin_bad:
        rules.append(RULE_NO_GROWTH_MARGIN)
    if lr_ronic_bad:
        rules.append(RULE_NO_GROWTH_RONIC)
    if no_growth:
        rules.append(RULE_NO_GROWTH)
    unpriced = []
    pv_years, rows = [], []
    g_last = None
    for t in range(1, N + 1):
        g = g_over[t] if t in g_over else gT + (g1 - gT) * gd.at(t)
        if no_growth and t > LEVEL_REF_YEAR:
            g = min(g, 0.0)
        rev = rev_prev * (1.0 + g)
        m = m_over[t] if t in m_over else m0 + (m5 - m0) * wm[t - 1]
        ebit = m * rev
        nopat = ebit - tax * max(ebit, 0.0)
        ronic_t = roic0 + (ronic - roic0) * wr[t - 1]
        reinv, priced = _growth_reinvestment(g, rev - rev_prev, m5, tax, ronic_t, nwc, False)
        if not priced:
            unpriced.append(t)
        fcff = nopat - reinv - gap * rev
        df = (1.0 + wacc) ** (-t)
        pv_exp += fcff * df
        pv_years.append(fcff * df)
        if t == 1:
            fcff1 = fcff
        if detail:
            rows.append({"t": t, "growth": g, "margin": m, "revenue": rev, "fcff": fcff})
        rev_prev = rev
        g_last = g
    if unpriced:
        rules.append(RULE_UNPRICED_EARLY)
    if no_growth:
        gT2 = g_last if g_last < 0.0 else 0.0
    else:
        gT2, _b = terminal_growth_after(g_last, gT)
    if wacc <= gT2:
        raise DrawInvalid("terminal growth is not below the discount rate")
    rev_T = rev_prev * (1.0 + gT2)
    ebit_T = m5 * rev_T
    nopat_T = ebit_T - tax * max(ebit_T, 0.0)
    kappa = rfade.values[-1]
    ronic_TV = max(wacc + kappa * (ind_med - wacc), wacc)
    reinv_T, priced_T = _growth_reinvestment(gT2, rev_T - rev_prev, m5, tax, ronic_TV, nwc, False)
    if not priced_T:
        raise DrawInvalid("terminal growth reinvestment cannot be priced")
    fcff_T = nopat_T - reinv_T - gap * rev_T
    tv = fcff_T / (wacc - gT2)
    pv_tv = tv * (1.0 + wacc) ** (-N)
    ev = pv_exp + pv_tv
    br = equity_bridge(ev, st, operating_leases_in_cash_flow=operating_leases_in_cash_flow)
    yrs = years_between(st["base_period"], disc.asof)
    factor = (1.0 + coe) ** yrs
    eq_raw = br["equity_value"] * factor
    if eq_raw < 0.0:
        rules.append(EQUITY_FLOOR_RULE)
    out = {"ev": ev, "equity": max(eq_raw, 0.0), "equity_unfloored": eq_raw, "rules": rules, "factor": factor, "pv_explicit": pv_exp, "pv_terminal": pv_tv,
           "pv_years": pv_years, "net_items": br["equity_value"] - ev, "tv_share": (pv_tv / ev) if ev != 0 else None, "N": N}
    if detail:
        out["years"] = rows
    return out


def fin_chain(st: dict, p: Dict[str, float], curves, disc, *, g_over: Optional[dict] = None, rp_over: Optional[dict] = None, detail: bool = False) -> dict:
    """financial_chain with `g_over` {t: growth of tangible book} and `rp_over` {t: the return that enters year t's residual income (ROTE'_t)} replacing the engine's own value."""
    g_over, rp_over = g_over or {}, rp_over or {}
    gd, rho, phi = curves["growth_decay"], curves["rote_retention"], curves["excess_fade"]
    N = len(gd)
    coe = disc.coe
    g1, gT, rT = p["g1"], p["g_terminal"], p["rote_target"]
    if coe <= gT:
        raise DrawInvalid("terminal growth is not below the cost of equity")
    R0 = st["rote_latest"]
    ind = st["industry_rote"]["value"]
    tbv_prev = st["tbv"]
    pv_exp = 0.0
    pv_years = []
    g_last = None
    for t in range(1, N + 1):
        g = g_over[t] if t in g_over else gT + (g1 - gT) * gd.at(t)
        R = rT + (R0 - rT) * rho.at(t)
        Rp = rp_over[t] if t in rp_over else ind + (R - ind) * phi.at(t)
        ri = (Rp - coe) * tbv_prev
        tbv = tbv_prev * (1.0 + g)
        df = (1.0 + coe) ** (-t)
        pv_exp += ri * df
        pv_years.append(ri * df)
        tbv_prev = tbv
        g_last = g
    gT2, _b = terminal_growth_after(g_last, gT)
    kappa = phi.values[-1]
    excess_T = kappa * max(ind - coe, 0.0)
    ri_next = excess_T * tbv_prev
    tv = ri_next / (coe - gT2)
    pv_tv = tv * (1.0 + coe) ** (-N)
    value = st["tbv"] + pv_exp + pv_tv
    yrs = years_between(st["base_period"], disc.asof)
    factor = (1.0 + coe) ** yrs
    eq_raw = value * factor
    rules = [EQUITY_FLOOR_RULE] if eq_raw < 0.0 else []
    return {"ev": value, "equity": max(eq_raw, 0.0), "equity_unfloored": eq_raw, "rules": rules, "factor": factor, "pv_explicit": pv_exp, "pv_terminal": pv_tv,
            "pv_years": pv_years, "net_items": st["tbv"] - 0.0, "tbv_0": st["tbv"], "tv_share": (pv_tv / value) if value != 0 else None, "N": N}
