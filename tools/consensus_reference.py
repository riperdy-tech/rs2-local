"""consensus_reference.py - what the analysts' own earnings path is worth at our discount rate.

Phase 4 E10, the F1 fix from the 2026-09-24 Fable cross-review. The desk compounds a CASH-FLOW
base by whatever growth rates it is given. The AMD probe gave it consensus REVENUE growth
(+46.9%, +73.1%) on a $5.1B base, so its "consensus plays out" case reached $13.0B of cash flow
in year 2. Consensus next-FY net income is $25.4B ($15.57 x 1.632B shares): the case was half of
consensus before any judgement was applied.

This module computes, in code and the same way for every name:
- the consensus EARNINGS growth that years 1-2 are checked against; and
- a reference value on that path. It is not a forecast and not a target: the analyst explains
  large deviations from it.

Reference path:
- Years 1-2 grow at consensus EPS growth, so margins move as analysts expect.
- From year 3, growth follows revenue again as margins settle. It fades linearly from next-FY
  consensus revenue growth to the growth base rate median by year 5 (the conditional median for
  the growth just delivered, else the size-bucket 5y median).
- Years 6-10 fade linearly to the terminal-growth anchor.
- Discounting is at the COE anchor, with a Gordon terminal value, per diluted share. This is the
  desk's stage-1 + stage-2 + Gordon arithmetic, with no exit multiple.
- When consensus EPS growth is unusable (a trough or a negative base) but the EPS levels exist,
  years 1-2 are consensus EPS x diluted shares + D&A - capex (MU and LIND on 2026-09-24).

Known approximations: consensus EPS growth is non-GAAP while the base is GAAP owner earnings,
which errs low for growers because the add-backs stay fixed. A TTM base with fiscal-year growth
runs year 2 about 10% high (AMD), and end-of-year discounting runs about 5-7% low; the two
roughly cancel today.
"""

EPS_GROWTH_MAX = 1.5   # above +150% an EPS growth rate is a recovery off a trough, not a cash-flow rate
FADE_YEARS = 5         # years 6-10
NEAR_LOW, NEAR_HIGH = 0.75, 1.33    # years 1-2 tolerance vs consensus earnings (x (1+c1)(1+c2))
FAR_LOW, FAR_HIGH = NEAR_LOW, NEAR_HIGH   # one rule: more than a quarter away from consensus needs a reason


def consensus_earnings_growth(estimates):
    """(g_current_fy, g_next_fy, None), or (None, None, reason) when consensus EPS growth is not a
    usable cash-flow growth rate for this name."""
    if not isinstance(estimates, dict):
        return None, None, "no consensus estimates"
    out = []
    for key in ("0y", "+1y"):
        eps = (estimates.get(key) or {}).get("eps") or {}
        g, prior = eps.get("growth"), eps.get("year_ago")
        if not eps.get("analysts"):
            return None, None, f"no EPS estimate for {key}"
        if not isinstance(g, (int, float)):
            return None, None, f"EPS growth missing for {key}"
        if isinstance(prior, (int, float)) and prior <= 0:
            return None, None, f"EPS base for {key} is not positive"
        if g > EPS_GROWTH_MAX or g <= -0.9:
            return None, None, f"EPS growth {g:+.0%} for {key} is off a trough, not a cash-flow growth rate"
        out.append(float(g))
    return out[0], out[1], None


def revenue_growth_next_fy(estimates):
    rev = ((estimates or {}).get("+1y") or {}).get("revenue") or {}
    g = rev.get("growth")
    return float(g) if isinstance(g, (int, float)) and rev.get("analysts") else None


def reference_path(c1, c2, rev_g2, median_5y):
    """Years 1-5 growth: consensus EPS growth, then a fade from next-FY revenue growth to the
    base-rate median. With no revenue estimate the fade starts AT the median (Fable check: falling
    back to EPS growth made the reference more generous exactly when data was thinner)."""
    start = rev_g2 if rev_g2 is not None else median_5y
    return [c1, c2] + _fade35(start, median_5y)


def _fade35(start, median_5y):
    return [start + (median_5y - start) / 3, start + (median_5y - start) * 2 / 3, median_5y]


def _pv(flows, g_last, coe, terminal_g, fade_years):
    """PV of explicit flows (years 1..n), then a linear fade from g_last to terminal_g over
    fade_years, then a Gordon terminal value, all at coe."""
    pv = sum(cf / (1 + coe) ** (y + 1) for y, cf in enumerate(flows))
    cf, year = flows[-1], len(flows)
    for i in range(1, fade_years + 1):
        year += 1
        cf *= 1 + g_last + (terminal_g - g_last) * i / fade_years
        pv += cf / (1 + coe) ** year
    return pv + cf * (1 + terminal_g) / (coe - terminal_g) / (1 + coe) ** year


def reference_value(base_cf, path, coe, terminal_g, shares, fade_years=FADE_YEARS):
    """Per-share value of `path`, then a linear fade to terminal_g, at coe, Gordon terminal."""
    if not (base_cf and base_cf > 0 and shares and shares > 0 and coe and coe > terminal_g):
        return None
    flows, cf = [], float(base_cf)
    for g in path:
        cf *= 1 + g
        flows.append(cf)
    return _pv(flows, path[-1], coe, terminal_g, fade_years) / shares


def consensus_eps_levels(estimates):
    """(EPS current FY, EPS next FY) consensus averages, or None. Next FY must be positive."""
    out = []
    for key in ("0y", "+1y"):
        eps = ((estimates or {}).get(key) or {}).get("eps") or {}
        if not eps.get("analysts") or not isinstance(eps.get("avg"), (int, float)):
            return None
        out.append(float(eps["avg"]))
    return (out[0], out[1]) if out[1] > 0 else None


def reference_value_levels(flow1, flow2, path35, coe, terminal_g, shares, fade_years=FADE_YEARS):
    """Years 1-2 given as cash-flow LEVELS, years 3-5 growing from year 2 along path35."""
    if not (flow2 and flow2 > 0 and shares and shares > 0 and coe and coe > terminal_g):
        return None
    flows, cf = [float(flow1), float(flow2)], float(flow2)
    for g in path35:
        cf *= 1 + g
        flows.append(cf)
    return _pv(flows, path35[-1], coe, terminal_g, fade_years) / shares


def build(base_cf, estimates, coe, terminal_g, shares, median_5y, da=None, capex=None):
    """Everything the pack prints: {'value', 'method', 'path', 'flows', 'c1', 'c2', 'reason'}.
    method "growth": years 1-2 at consensus EPS growth on the owner-earnings base.
    method "levels": consensus EPS growth unusable, so years 1-2 are consensus EPS x diluted
    shares + D&A - capex. `value` is None, with a reason, when neither can be computed."""
    c1, c2, why = consensus_earnings_growth(estimates)
    out = {"value": None, "method": None, "path": None, "flows": None, "c1": c1, "c2": c2,
           "reason": None, "growth_unusable": why}
    missing = [n for n, v in (("cost-of-equity anchor", coe), ("terminal-growth anchor", terminal_g),
                              ("diluted shares", shares), ("growth base-rate median", median_5y))
               if v is None]
    if missing:
        out["reason"] = f"{', '.join(missing)} missing"
        return out
    rev_g2 = revenue_growth_next_fy(estimates)
    if why is None:
        if base_cf is None:
            out["reason"] = "owner-earnings base missing"
        elif base_cf <= 0:
            out["reason"] = "owner-earnings base is not positive"
        else:
            out["path"] = reference_path(c1, c2, rev_g2, median_5y)
            out["method"] = "growth"
            out["value"] = reference_value(base_cf, out["path"], coe, terminal_g, shares)
            if out["value"] is None:
                out["reason"] = "cost of equity not above terminal growth"
        return out
    levels = consensus_eps_levels(estimates)
    if levels is None or da is None or capex is None:
        out["reason"] = why + ("" if levels else "; no positive next-FY EPS level") + \
            ("" if da is not None and capex is not None else "; D&A or capex missing")
        return out
    flows = (levels[0] * shares + da - capex, levels[1] * shares + da - capex)
    path35 = _fade35(rev_g2 if rev_g2 is not None else median_5y, median_5y)
    out.update(method="levels", flows=flows, path=[None, None] + path35,
               value=reference_value_levels(flows[0], flows[1], path35, coe, terminal_g, shares))
    if out["value"] is None:
        out["reason"] = why + "; next-FY cash flow from EPS levels is not positive"
    return out


def pack_line(ref, base_cf, coe, terminal_g, fmt_b):
    """SECTION 8's line. The prefix is fixed: the harness parses it (consensus_valuation)."""
    if ref.get("value") is None:
        return f"- CONSENSUS-IMPLIED VALUE: not available \u2014 {ref.get('reason')}"
    head = (f"- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): ${ref['value']:,.2f} "
            f"per share \u2014 the analysts' own earnings path at our discount rate. ")
    tail = (f"; then a 5-year fade to the terminal-growth anchor {terminal_g * 100:.2f}%; discounted at "
            f"the COE ANCHOR {coe * 100:.2f}%. A Base IV more than a quarter away from it (below 0.75x "
            f"or above 1.33x) needs guidance_deviation_reason.")
    if ref["method"] == "growth":
        path = " / ".join(f"{g * 100:+.1f}%" for g in ref["path"])
        return (head + f"Owner-earnings base {fmt_b(base_cf)}; cash-flow growth years 1-5 {path} "
                f"(years 1-2 = consensus EPS growth; from year 3, next-FY revenue growth fading to the "
                f"GROWTH BASE RATES median)" + tail)
    g35 = " / ".join(f"{g * 100:+.1f}%" for g in ref["path"][2:])
    return (head + f"Consensus EPS growth is unusable ({ref['growth_unusable']}), so years 1-2 are "
            f"consensus EPS x diluted shares + D&A - capex: {fmt_b(ref['flows'][0])}, "
            f"{fmt_b(ref['flows'][1])}; years 3-5 growth {g35} (next-FY revenue growth fading to the "
            f"GROWTH BASE RATES median)" + tail)
