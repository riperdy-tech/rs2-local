"""engine_financial.py - SPEC 3.2: excess return on tangible equity, for banks, insurers, specialty finance and broker-dealers.

  TBV_0      = tangible common equity at the base fiscal year end = equity - goodwill - intangibles ex goodwill - preferred equity
               (a goodwill or intangibles tag that is not filed counts as none and the state is stamped tbv_partial)
  growth_t   = g_T + (g_1 - g_T) x d_t                          growth of tangible book (retention funds it; the payout is whatever NI - dTBV leaves); g_T is the date's
                                                                 terminal growth, min(risk-free rate, 3.75%) (Addendum H2), and a negative last-year rate continues as terminal growth
  ROTE_t     = rote_T + (ROTE_0 - rote_T) x rho_t                normalization of the return from the base year's ROTE_0 toward the through-cycle
                                                                 level rote_T (an input), speed rho = the measured normalization curve
  ROTE'_t    = I + (ROTE_t - I) x phi_t                          competitive fade of the excess return toward I, the median return on tangible equity of the company's industry at T on the
                                                                 date's population (phi: the measured retention of ROTE's excess)
  RI_t       = (ROTE'_t - COE) x TBV_{t-1}                       excess return (residual income) of year t
  TBV_t      = TBV_{t-1} x (1 + growth_t)
  value      = TBV_0 + sum_{t=1..N} RI_t / (1+COE)^t  +  RI_{N+1} / (COE - g_T) / (1+COE)^N ,   RI_{N+1} = kappa x max(I - COE, 0) x TBV_N

TERMINAL EXCESS RETURN (Addendum I4).  In perpetuity the excess of the return on tangible equity over the cost of equity is the industry median's excess x kappa, the MEASURED long-run
retention of ROTE's excess: the plateau of the measured retention curve (`excess_fade`), its value at the longest k with at least 50 observations (the curve holds it beyond).  Not
the full median excess for ever (Addendum H3 is superseded for the terminal).  The excess stays floored at 0 (a perpetuity does not earn below the cost of equity, the
stable-growth convention); the operating engine's terminal return on new capital is a different object (it prices growth only) and is unchanged.
  at the valuation date = value x (1 + COE)^(years since the base year end)

ROTE_0 = net income / average tangible common equity of the base year (the ending balance in the first held year). Net income is the
parent's as filed; amortization of acquired intangibles is not added back (state stamp). COE comes from discount_rate. COE must exceed
g_T (an invalid draw otherwise, counted and reported). A tangible book that is not positive is a refusal: the method has no base.

INSURERS: where the XBRL concepts are tagged (PremiumsEarnedNet, PolicyholderBenefitsAndClaimsIncurredNet, NetInvestmentIncome, optionally
DeferredPolicyAcquisitionCostAmortizationExpense) the result carries `insurer_decomposition`: per year the underwriting result
(premiums - claims incurred - DAC amortization; other underwriting expenses are NOT separated, so it is stamped partial) and net
investment income, their medians over EVERY held year (catastrophe years are in, nothing is trimmed), and the return on tangible equity those
medians imply. A diagnostic and a state feature for the priors; it is not added to the value.

SECONDARY CROSS-CHECK: price-to-tangible-book of the population at the same ROTE (priors.refs["ptbv_of_rote"](rote_T, COE, g_T)) x TBV_0, rolled
forward like the primary. model_disagreement = ln(median primary / median secondary).
"""
from __future__ import annotations

from typing import Dict, Optional

from .common import (CompanyPIT, Curve, DrawInvalid, EQUITY_FLOOR_RULE, MAX_HORIZON, TERMINAL_G_ANCHOR, build_state, model_disagreement, simulate,
                     terminal_growth_after, terminal_growth_rate)
from .discount_rate import DiscountRate
from .engine_operating import refusal, years_between

ENGINE = "financial"
INPUTS = ("g1", "rote_target")                  # terminal growth is not an input (Addendum H2)
CURVES = ("growth_decay", "rote_retention", "excess_fade")

INSURER_PREMIUMS = ("PremiumsEarnedNet", "PremiumsEarnedNetPropertyAndCasualty", "PremiumsEarnedNetLife")
INSURER_CLAIMS = ("PolicyholderBenefitsAndClaimsIncurredNet", "PolicyholderBenefitsAndClaimsIncurredGross")
INSURER_DAC = ("DeferredPolicyAcquisitionCostAmortizationExpense",)
INSURER_NII = ("NetInvestmentIncome",)


def state_gaps(st) -> list:
    gaps = []
    if not st.get("periods"):
        gaps.append("no annual report filed before the valuation date")
        return gaps
    if st.get("tbv") is None:
        gaps.append("tangible equity (parent equity not filed)")
    elif st["tbv"] <= 0:
        gaps.append(f"tangible book value is not positive ({st['tbv']:.4g}): the excess-return method has no base")
    if st.get("rote_latest") is None:
        gaps.append("base-year return on tangible equity (net income and tangible equity in the base year)")
    if st.get("industry_rote") is None:
        gaps.append("industry median return on tangible equity at T (the population of the date was not supplied)")
    return gaps


def financial_chain(st: dict, p: Dict[str, float], curves: Dict[str, Curve], disc: DiscountRate, *, roll_forward: bool = True,
                    detail: bool = False) -> dict:
    gd, rho, phi = curves["growth_decay"], curves["rote_retention"], curves["excess_fade"]
    N = len(gd)
    if N > MAX_HORIZON:
        raise ValueError(f"horizon {N} exceeds {MAX_HORIZON} years")
    coe = disc.coe
    g1, gT, rT = p["g1"], p["g_terminal"], p["rote_target"]       # gT: the date's terminal growth (Addendum H2), the asymptote of the decay path
    if coe <= gT:
        raise DrawInvalid("terminal growth is not below the cost of equity")
    R0 = st["rote_latest"]
    ind = st["industry_rote"]["value"]
    tbv_prev = st["tbv"]
    pv_exp = 0.0
    rows = []
    ri_first = None
    Rp = None
    for t in range(1, N + 1):
        g = gT + (g1 - gT) * gd.at(t)
        R = rT + (R0 - rT) * rho.at(t)
        Rp = ind + (R - ind) * phi.at(t)
        ri = (Rp - coe) * tbv_prev
        tbv = tbv_prev * (1.0 + g)
        df = (1.0 + coe) ** (-t)
        pv_exp += ri * df
        if t == 1:
            ri_first = ri
        if detail:
            rows.append({"t": t, "growth": g, "rote": R, "rote_after_fade": Rp, "tbv_begin": tbv_prev, "excess_return": ri,
                         "tbv_end": tbv, "discount_factor": df, "pv": ri * df})
        tbv_prev = tbv
        g_last = g
    gT, gT_basis = terminal_growth_after(g_last, gT)
    kappa = phi.values[-1]                                # Addendum I4: the plateau of the measured retention of ROTE's excess (its value at the longest k with n >= 50)
    excess_T = kappa * max(ind - coe, 0.0)                # the industry median's excess over the cost of equity x the retention, floored at 0
    ri_next = excess_T * tbv_prev
    tv = ri_next / (coe - gT)
    pv_tv = tv * (1.0 + coe) ** (-N)
    value = st["tbv"] + pv_exp + pv_tv
    yrs = years_between(st["base_period"], disc.asof) if roll_forward else 0.0
    factor = (1.0 + coe) ** yrs
    # the financial value is already an equity value; "ev" in the shared result shape carries the same number
    pv_total_excess = pv_exp + pv_tv
    eq_raw = value * factor
    rules = [EQUITY_FLOOR_RULE] if eq_raw < 0.0 else []            # Addendum I2: limited liability, equity per draw is at least 0
    out = {"ev": value, "equity": max(eq_raw, 0.0), "equity_unfloored": eq_raw, "rules": rules, "equity_at_base_year_end": max(value, 0.0), "roll_forward_years": yrs,
           "roll_forward_factor": factor, "tv_share": (pv_tv / value) if value != 0 else None,
           "tbv_0": st["tbv"], "pv_explicit_excess": pv_exp, "pv_terminal_excess": pv_tv, "excess_share_of_value": pv_total_excess / value if value else None,
           "price_to_tbv_implied": value / st["tbv"], "terminal_growth": {"value": gT, "basis": gT_basis}, "terminal_rote": coe + excess_T,
           "terminal_excess_retention": kappa, "terminal_excess_industry_median_over_coe": ind - coe}
    if detail:
        out["years"] = rows
    return out


def insurer_decomposition(pit: CompanyPIT, tax: float, tbv: Optional[float]) -> Optional[dict]:
    """See the module docstring. None when the premiums, claims and investment income concepts are not all tagged for >= 3 years."""
    def pick(names):
        for n in names:
            v = pit.concept_values(n)
            if v:
                return n, v
        return None, {}
    pn, prem = pick(INSURER_PREMIUMS)
    cn, clm = pick(INSURER_CLAIMS)
    dn, dac = pick(INSURER_DAC)
    nn, nii = pick(INSURER_NII)
    periods = sorted(p for p in prem if p in clm and p in nii and p in set(pit.periods()))
    if len(periods) < 3:
        return None
    rows = []
    for p in periods:
        uw = prem[p] - clm[p] - dac.get(p, 0.0)
        rows.append({"period": p, "premiums_earned": prem[p], "claims_incurred": clm[p], "dac_amortization": dac.get(p),
                     "underwriting_result_partial": uw, "net_investment_income": nii[p],
                     "loss_ratio": clm[p] / prem[p] if prem[p] else None})
    import statistics
    mu = statistics.median(r["underwriting_result_partial"] for r in rows)
    mi = statistics.median(r["net_investment_income"] for r in rows)
    imp = ((mu + mi) * (1.0 - tax) / tbv) if (tbv and tbv > 0) else None
    return {"tags": {"premiums": pn, "claims": cn, "dac": dn, "investment_income": nn}, "years": rows,
            "median_underwriting_result_partial": mu, "median_net_investment_income": mi,
            "implied_rote_from_medians_partial": imp,
            "stamps": ["other underwriting expenses and corporate costs are not separated: partial",
                       "medians over every held year; catastrophe years are included, nothing trimmed"
                       + ("" if dn else "; DAC amortization not tagged, read as none")]}


def run(pit: CompanyPIT, priors, disc: DiscountRate, *, n_draws: int = 2000, seed: int = 20261006, corr=None,
        price_per_share: Optional[float] = None, roll_forward: bool = True, state: Optional[dict] = None) -> dict:
    st = state if state is not None else build_state(pit)
    gaps = state_gaps(st)
    if gaps:
        return refusal(ENGINE, [f"not available: {g}" for g in gaps], ticker=pit.ticker, asof=st.get("asof"))
    ps = priors.for_company("financial", st, pit.asof)
    miss = [k for k in INPUTS if k not in ps.inputs] + [k for k in CURVES if k not in ps.curves]
    if miss:
        return refusal(ENGINE, [f"priors do not supply: {miss}"], ticker=pit.ticker)
    ref = ps.refs.get("ptbv_of_rote")
    g_term = terminal_growth_rate(disc.rf)
    dists = {k: v for k, v in ps.inputs.items() if k != "g_terminal"}

    def chain(draw):
        draw = dict(draw, g_terminal=g_term)
        r = financial_chain(st, draw, ps.curves, disc, roll_forward=roll_forward)
        if ref is not None:
            m = ref(draw["rote_target"], disc.coe, draw["g_terminal"])
            if m is None:
                r["secondary_equity"], r["secondary_reason"] = None, "population price-to-tangible-book not defined for this draw"
            else:
                r["secondary_equity"] = m * st["tbv"] * r["roll_forward_factor"]
        return r

    dist = simulate(chain, dists, n_draws, seed, corr, price_per_share, st.get("shares_outstanding"))
    mid = dict({k: d.ppf(0.5) for k, d in dists.items()}, g_terminal=g_term)
    try:
        at_median = financial_chain(st, mid, ps.curves, disc, roll_forward=roll_forward, detail=True)
    except DrawInvalid as e:
        at_median = {"invalid": str(e)}
    md, why = None, "no secondary cross-check supplied by the priors"
    if dist["equity"] is not None and dist["secondary_equity"] is not None:
        md, why = model_disagreement(dist["equity"]["p50"], dist["secondary_equity"]["p50"])
    notes = ["return on tangible equity: net income / average tangible common equity; acquired-intangible amortization not added back"]
    if corr is None:
        notes.append("inputs drawn independently (no correlation supplied): dispersion is understated if inputs move together")
    if st.get("tbv_partial"):
        notes.append("tangible equity is partial: goodwill or intangibles tag not filed, read as none")
    return {"status": "ok", "engine": ENGINE, "family": "financial", "ticker": pit.ticker, "asof": st["asof"], "base_period": st["base_period"],
            "base_filed": st["base_filed"], "base_accession": st["base_accession"], "placeholder": bool(ps.placeholder or disc.placeholder),
            "prior_source": ps.source, "discount": disc.as_dict(), "distribution": dist, "at_median_inputs": at_median,
            "model_disagreement": md, "model_disagreement_note": why, "cyclicality": st.get("cyclicality"),
            "insurer_decomposition": insurer_decomposition(pit, st["tax_rate"], st["tbv"]),
            "inputs": {k: v.as_dict() for k, v in dists.items()},
            "terminal_growth": {"base": g_term, "rf": disc.rf, "anchor": TERMINAL_G_ANCHOR, "rule": "Addendum H2: min(risk-free rate at T, 3.75%); a negative decay-path rate "
                                "at the last explicit year continues (see at_median_inputs)"}, "notes": notes}
