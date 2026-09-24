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
    start = rev_g2 if rev_g2 is not None else c2
    return [c1, c2,
            start + (median_5y - start) / 3,
            start + (median_5y - start) * 2 / 3,
            median_5y]


def reference_value(base_cf, path, coe, terminal_g, shares, fade_years=FADE_YEARS):
    """Per-share value of `path`, then a linear fade to terminal_g, at coe, Gordon terminal."""
    if not (base_cf and base_cf > 0 and shares and shares > 0 and coe and coe > terminal_g):
        return None
    cf, pv, year = float(base_cf), 0.0, 0
    for g in path:
        year += 1
        cf *= 1 + g
        pv += cf / (1 + coe) ** year
    g_last = path[-1]
    for i in range(1, fade_years + 1):
        year += 1
        cf *= 1 + g_last + (terminal_g - g_last) * i / fade_years
        pv += cf / (1 + coe) ** year
    tv = cf * (1 + terminal_g) / (coe - terminal_g) / (1 + coe) ** year
    return (pv + tv) / shares


def build(base_cf, estimates, coe, terminal_g, shares, median_5y):
    """Everything the pack prints: {'value', 'path', 'c1', 'c2', 'reason'}. `value` is None, with
    a reason, when the reference cannot be computed for this name."""
    c1, c2, why = consensus_earnings_growth(estimates)
    missing = [n for n, v in (("owner-earnings base", base_cf), ("cost-of-equity anchor", coe),
                              ("terminal-growth anchor", terminal_g), ("diluted shares", shares),
                              ("growth base-rate median", median_5y)) if v is None]
    if why or missing:
        return {"value": None, "path": None, "c1": c1, "c2": c2,
                "reason": why or f"{', '.join(missing)} missing"}
    if base_cf <= 0:
        return {"value": None, "path": None, "c1": c1, "c2": c2,
                "reason": "owner-earnings base is not positive"}
    path = reference_path(c1, c2, revenue_growth_next_fy(estimates), median_5y)
    value = reference_value(base_cf, path, coe, terminal_g, shares)
    return {"value": value, "path": path, "c1": c1, "c2": c2,
            "reason": None if value is not None else "cost of equity not above terminal growth"}
