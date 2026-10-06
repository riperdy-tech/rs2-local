"""engine_operating.py - SPEC 3.1: the layered DCF for operating companies.

THE CHAIN (all money in the filing's units; year t = 1..N, N = the length of the growth-decay curve, at most 25):

  growth_t     = g_T + (g_1 - g_T) x d_t                 d = growth-decay curve (d_1 = 1, falls to its last value), g_T may be negative
  Rev_t        = Rev_{t-1} x (1 + growth_t)              Rev_0 = the base fiscal year's revenue
  margin_t     = m_0 + (m_5 - m_0) x w_t                 m_0 = the base year's operating margin as filed; m_5 = the margin LEVEL five years on (an input, drawn
                                                         from the measured distribution of that level: Addendum H1); w_t = (1 - r_t) / (1 - r_5) for
                                                         t <= 5 (r = the measured margin-retention curve), 1 after: the margin reaches m_5 along the
                                                         measured curve's shape and is held there (common.level_path_weights)
  EBIT_t       = margin_t x Rev_t
  NOPAT_t      = EBIT_t - tax x max(EBIT_t, 0)           = EBIT x (1 - tax) when EBIT > 0; no tax shield is booked on losses (no NOL asset)
  RONIC_t      = WACC + (RONIC - WACC) x phi_t           phi = fade curve toward the cost of capital
  growth reinvestment_t
       growth_t >= 0 : (Rev_t - Rev_{t-1}) x m_5 (1 - tax) / RONIC_t      capital needed per dollar of added revenue, i.e. reinvestment =
                                                         growth / return on new capital, priced at the LONG-RUN margin (m_5) so that a
                                                         temporarily depressed or inflated margin does not change the capital a unit of
                                                         growth needs
       growth_t <  0 : (Rev_t - Rev_{t-1}) x NWC/Rev       working-capital RELEASE of a shrinking company (negative reinvestment); fixed
                                                         capital is not assumed to be liquidated
  maintenance_t = max(gap, 0) x Rev_t                     gap = median over the latest 8 years of (Greenwald maintenance capex - D&A) / revenue,
                                                         maintenance capex = capex - (PP&E / revenue) x (change in revenue). EBIT already
                                                         bears D&A; the gap is what keeping the asset base intact costs beyond it. A negative
                                                         gap (D&A above maintenance capex) is floored at 0: an asset base cannot be depreciated
                                                         into cash for ever (set maint_gap_floor=None to disable; the raw gap is always reported)
  FCFF_t       = NOPAT_t - growth reinvestment_t - maintenance_t
  EV           = sum_t FCFF_t / (1+WACC)^t  +  TV / (1+WACC)^N ,   TV = FCFF_{N+1} / (WACC - g_T)
                 FCFF_{N+1} built from Rev_N x (1+g_T), the margin m_5 and the RONIC of year N (held), growth reinvestment at g_T
  equity       = common.equity_bridge(EV)                (debt, finance leases, minority interest out; cash, investments in; no double count)
  value at the valuation date = equity at the base fiscal year end x (1 + cost of equity)^(years from that year end to the valuation date)

Cash flows fall at year ends. The terminal-value share (PV of TV / EV) is always reported. TERMINAL GROWTH (Addendum H2): not a drawn input. It is min(the risk-free rate at T, the 3.75% anchor), one value per date (common.terminal_growth_rate), which
is also the asymptote the growth-decay path fades to; if the path has reached a negative rate by the last explicit year, that rate continues as terminal growth
(no floor). Terminal growth must be below WACC: a draw that is not is counted as invalid with its reason (never repaired).

SECONDARY CROSS-CHECK: EV = (EV / FCFF_1 multiple of the population at the same growth and return state, from priors.refs
["ev_fcf_multiple"]) x FCFF_1 of the same draw, bridged and rolled like the primary. Diagnostics (not values): the capital intensity the
chain implies against the company's own history, and the terminal reinvestment rate. Cross-checks are never averaged in;
model_disagreement = ln(median primary / median secondary).
"""
from __future__ import annotations

from typing import Dict, Optional

from .common import (Curve, DrawInvalid, InputError, MAX_HORIZON, QuantileDist, build_state, equity_bridge, level_path_weights, model_disagreement,
                     parse_date, simulate, terminal_growth_after, terminal_growth_rate, CompanyPIT, TERMINAL_G_ANCHOR)
from .discount_rate import DiscountRate

ENGINE = "operating"
INPUTS = ("g1", "margin_target", "ronic")      # margin_target = the margin level five years on (Addendum H1); terminal growth is not an input (Addendum H2)
CURVES = ("growth_decay", "margin_retention", "ronic_fade")


def refusal(engine, reasons, **extra):
    out = {"status": "refused", "engine": engine, "reasons": list(reasons)}
    out.update(extra)
    return out


def state_gaps(st) -> list:
    """What the operating chain needs from the filings and does not have."""
    gaps = list(st.get("missing", []))
    for k, why in (("op_margin", "base-year operating margin (operating income and revenue)"),
                   ("maint_gap_ratio", "maintenance capex ratio (Greenwald: capex, PP&E, D&A and revenue in at least two consecutive years)"),
                   ("nwc_ratio", "net working capital / revenue (current assets, current liabilities, cash)")):
        if st.get(k) is None:
            gaps.append(why)
    return gaps


def years_between(base_period_end: str, asof) -> float:
    return (parse_date(asof) - parse_date(base_period_end)).days / 365.25


def _growth_reinvestment(g, drev, m_t, tax, ronic_t, nwc_ratio):
    if g >= 0:
        net = m_t * (1.0 - tax)
        if net <= 0:
            raise DrawInvalid("long-run NOPAT margin not positive: growth cannot be priced")
        if ronic_t <= 0:
            raise DrawInvalid("return on new capital not positive")
        return drev * net / ronic_t
    return drev * nwc_ratio


def operating_chain(st: dict, p: Dict[str, float], curves: Dict[str, Curve], disc: DiscountRate, *,
                    operating_leases_in_cash_flow: bool = True, maint_gap_floor: Optional[float] = 0.0,
                    roll_forward: bool = True, detail: bool = False) -> dict:
    """One deterministic pass of the chain for point inputs p = {g1, g_terminal, margin_target (the level five years on), ronic}. DrawInvalid when not valuable."""
    gd, mr, rfade = curves["growth_decay"], curves["margin_retention"], curves["ronic_fade"]
    N = len(gd)
    if N > MAX_HORIZON:
        raise InputError(f"horizon {N} exceeds {MAX_HORIZON} years")
    tax, wacc, coe = st["tax_rate"], disc.wacc, disc.coe
    g1, gT, m5, ronic = p["g1"], p["g_terminal"], p["margin_target"], p["ronic"]       # gT: the date's terminal growth (the asymptote of the decay path)
    wm, margin_path = level_path_weights(mr, N)
    if wacc <= gT:
        raise DrawInvalid("terminal growth is not below the discount rate")
    m0 = st["op_margin"]
    gap_raw = st["maint_gap_ratio"]
    gap = gap_raw if maint_gap_floor is None else max(gap_raw, maint_gap_floor)
    nwc = st["nwc_ratio"]
    rev_prev = st["revenue"]
    rows, pv_exp = [], 0.0
    fcff1 = None
    for t in range(1, N + 1):
        g = gT + (g1 - gT) * gd.at(t)
        rev = rev_prev * (1.0 + g)
        m = m0 + (m5 - m0) * wm[t - 1]
        ebit = m * rev
        nopat = ebit - tax * max(ebit, 0.0)
        ronic_t = wacc + (ronic - wacc) * rfade.at(t)
        reinv = _growth_reinvestment(g, rev - rev_prev, m5, tax, ronic_t, nwc)
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
    # terminal
    gT, gT_basis = terminal_growth_after(g_last, gT)
    rev_T = rev_prev * (1.0 + gT)
    ebit_T = m5 * rev_T
    nopat_T = ebit_T - tax * max(ebit_T, 0.0)
    ronic_TV = wacc + (ronic - wacc) * rfade.at(N)
    reinv_T = _growth_reinvestment(gT, rev_T - rev_prev, m5, tax, ronic_TV, nwc)
    fcff_T = nopat_T - reinv_T - gap * rev_T
    tv = fcff_T / (wacc - gT)
    pv_tv = tv * (1.0 + wacc) ** (-N)
    ev = pv_exp + pv_tv
    tv_share = (pv_tv / ev) if ev != 0 else None
    br = equity_bridge(ev, st, operating_leases_in_cash_flow=operating_leases_in_cash_flow)
    yrs = years_between(st["base_period"], disc.asof) if roll_forward else 0.0
    factor = (1.0 + coe) ** yrs
    out = {"ev": ev, "equity": br["equity_value"] * factor, "equity_at_base_year_end": br["equity_value"], "roll_forward_years": yrs,
           "roll_forward_factor": factor, "tv_share": tv_share, "pv_explicit": pv_exp, "pv_terminal": pv_tv, "terminal_value": tv,
           "fcff_terminal_year": fcff_T, "terminal_reinvestment_rate": (reinv_T / nopat_T) if nopat_T > 0 else None,
           "maint_gap_ratio_raw": gap_raw, "maint_gap_ratio_used": gap, "bridge": br, "fcff1": fcff1, "margin_path": margin_path,
           "terminal_growth": {"value": gT, "basis": gT_basis}}
    if detail:
        out["years"] = rows
    return out


def _median_point(dists: Dict[str, QuantileDist]) -> Dict[str, float]:
    return {k: d.ppf(0.5) for k, d in dists.items()}


def capital_intensity_check(st, p, disc) -> dict:
    """Diagnostic: capital the chain assumes per dollar of revenue (m_T (1-tax) / RONIC) against the company's own history
    (revenue / (equity + debt - cash - short-term investments) at the base year). Not a value, not a gate."""
    tax = st["tax_rate"]
    implied = (p["margin_target"] * (1.0 - tax) / p["ronic"]) if p["ronic"] > 0 else None
    eq, debt, cash = st.get("equity"), st.get("debt"), st.get("cash")
    ic = None
    if None not in (eq, debt, cash):
        sti = st.get("st_investments")
        ic = eq + debt - cash - (0.0 if sti is None else sti)        # untagged short-term investments read as none
    hist = (ic / st["revenue"]) if (ic is not None and ic > 0 and st.get("revenue")) else None
    return {"implied_capital_per_revenue": implied, "historical_invested_capital_per_revenue": hist,
            "ratio_implied_to_historical": (implied / hist) if (implied is not None and hist) else None}


def run(pit: CompanyPIT, priors, disc: DiscountRate, *, n_draws: int = 2000, seed: int = 20261006, corr=None,
        price_per_share: Optional[float] = None, operating_leases_in_cash_flow: bool = True,
        maint_gap_floor: Optional[float] = 0.0, roll_forward: bool = True, state: Optional[dict] = None,
        engine: str = ENGINE, family: str = "operating", curves_override: Optional[Dict[str, Curve]] = None) -> dict:
    """Value one company at pit.asof: state from the filings, priors for its state, a distribution of equity value, the secondary
    cross-check and the model disagreement. A refusal names every gap."""
    st = state if state is not None else build_state(pit)
    gaps = state_gaps(st)
    if gaps:
        return refusal(engine, [f"not available: {g}" for g in gaps], ticker=pit.ticker, asof=st.get("asof"))
    ps = priors.for_company(family, st, pit.asof)
    miss = [k for k in INPUTS if k not in ps.inputs] + [k for k in CURVES if k not in ps.curves and not (curves_override and k in curves_override)]
    if miss:
        return refusal(engine, [f"priors do not supply: {miss}"], ticker=pit.ticker)
    curves = dict(ps.curves)
    if curves_override:
        curves.update(curves_override)
    ref = ps.refs.get("ev_fcf_multiple")
    g_term = terminal_growth_rate(disc.rf)
    dists = {k: v for k, v in ps.inputs.items() if k != "g_terminal"}        # a prior may still carry one (placeholders); the date's value replaces it

    def chain(draw):
        draw = dict(draw, g_terminal=g_term)
        mult = None
        if ref is not None:
            mult = ref(st, draw, disc)
        r = operating_chain(st, draw, curves, disc, operating_leases_in_cash_flow=operating_leases_in_cash_flow,
                            maint_gap_floor=maint_gap_floor, roll_forward=roll_forward)
        if ref is not None:
            if mult is None:
                r["secondary_equity"], r["secondary_reason"] = None, "population multiple not defined for this draw"
            elif r["fcff1"] is None or r["fcff1"] <= 0:
                r["secondary_equity"], r["secondary_reason"] = None, "year-1 FCFF not positive"
            else:
                sb = equity_bridge(mult * r["fcff1"], st, operating_leases_in_cash_flow=operating_leases_in_cash_flow)
                r["secondary_equity"] = sb["equity_value"] * r["roll_forward_factor"]
        return r

    dist = simulate(chain, dists, n_draws, seed, corr, price_per_share, st.get("shares_outstanding"))
    mid = dict(_median_point(dists), g_terminal=g_term)
    at_median = None
    try:
        at_median = operating_chain(st, mid, curves, disc, operating_leases_in_cash_flow=operating_leases_in_cash_flow,
                                    maint_gap_floor=maint_gap_floor, roll_forward=roll_forward, detail=True)
    except DrawInvalid as e:
        at_median = {"invalid": str(e)}
    md, why = (None, "no secondary cross-check supplied by the priors")
    if dist["equity"] is not None and dist["secondary_equity"] is not None:
        md, why = model_disagreement(dist["equity"]["p50"], dist["secondary_equity"]["p50"])
    notes = []
    if corr is None:
        notes.append("inputs drawn independently (no correlation supplied): dispersion is understated if inputs move together")
    if st["read_as_none"]:
        notes.append("read as none: " + "; ".join(st["read_as_none"]))
    if disc.de_basis == "book":
        notes.append("discount rate uses the book D/E")
    return {"status": "ok", "engine": engine, "family": family, "ticker": pit.ticker, "asof": st["asof"], "base_period": st["base_period"],
            "base_filed": st["base_filed"], "base_accession": st["base_accession"], "placeholder": bool(ps.placeholder or disc.placeholder),
            "prior_source": ps.source, "discount": disc.as_dict(), "distribution": dist, "at_median_inputs": at_median,
            "model_disagreement": md, "model_disagreement_note": why,
            "consistency": capital_intensity_check(st, mid, disc), "cyclicality": st.get("cyclicality"),
            "inputs": {k: v.as_dict() for k, v in dists.items()},
            "terminal_growth": {"base": g_term, "rf": disc.rf, "anchor": TERMINAL_G_ANCHOR, "rule": "Addendum H2: min(risk-free rate at T, 3.75%); a negative decay-path rate "
                                "at the last explicit year continues (see at_median_inputs)"}, "notes": notes}
