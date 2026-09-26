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
- The base is the LAST FULL FISCAL YEAR's owner earnings, the same period consensus growth is
  measured from (Phase 4 E18). Years 1-2 grow at consensus EPS growth, so margins move as
  analysts expect, and the year-1 and year-2 cash-flow LEVELS are printed: they, not the rates,
  are what the analyst's base case is anchored to.
- From year 3, growth follows revenue again as margins settle. It fades linearly from next-FY
  consensus revenue growth toward the growth base rate median by year 5 (the conditional median
  for the growth just delivered, else the size-bucket 5y median), never above next-FY revenue
  growth: a fade that rises is a forecast the consensus does not make (E15 pre-registration).
- Years 6-10 fade linearly to the terminal-growth anchor.
- Discounting is at the COE anchor, with a Gordon terminal value, per diluted share, valued at the
  fiscal year end and rolled forward to today at the same rate. This is the desk's stage-1 +
  stage-2 + Gordon arithmetic, with no exit multiple.
- When consensus EPS growth is unusable (a trough or a negative base) but the EPS levels exist,
  years 1-2 are consensus EPS x diluted shares + D&A - capex (MU and LIND on 2026-09-24).

E18 (ADI (b) joint review, 2026-09-25): the reference applied full current-FY growth to a TTM base
that already held part of that fiscal year, overstating the year-1 flow by about (1+g1)^(q/4):
+29% on ADI, +35% on AMD, +26% on APH, +9% on LAMR. Fable's E10 ruling that this and end-of-year
discounting "roughly cancel" was wrong for fast growers. Consensus EPS growth is adjusted (non-GAAP)
while the base is filed owner earnings, stock pay expensed and the base year's one-offs included.
The whole-book test (2026-09-26) measured that gap: for about a third of names the printed year-2
level sits more than 20% below the analysts' own path, so the reference is more conservative than
the street's there. That is the E10 design, not an error; D&A does not absorb it.

The whole-book test of E18 (2026-09-26, 176 names) failed, and Fable ruled:
- The period comes from the consensus VINTAGE, not the calendar. The vendor's year-ago revenue for
  the current year names the fiscal year its estimates start from (EPAC, PSMT and MU: the filed year
  to the dollar, 12.9 months after it ended). A failed or unknown test means "not verified", never
  "the vendor has rolled" (review ruling, 2026-09-27): vendor revenue for ZTO, ATAT and VIPS is 6.99x
  ours, for RNW 116x. History older than 15 months is "stale", not a reference.
- A fiscal-year base that is not positive (LIVN) goes to the EPS levels, as LIND does. Vendor EPS
  LEVELS meet filed D&A and capex only when the vintage test passes (`levels_block` otherwise); the
  growth method and the range levels use ratios of the vendor's own figures and are exempt.
- The E18/old ratio followed the base WINDOW (rank correlation 0.975), not the period: net-income
  one-offs and capex swings land in the fiscal year or in the TTM. Neither window is right for every
  name (GOOG's TTM holds equity mark-ups, BMRN's an acquired-IPR&D charge), so when the TTM differs
  from the fiscal-year base grown by consensus for the quarters between them by more than 15%, both
  references are printed and the analyst names the window; nothing is chosen by rule.
"""

EPS_GROWTH_MAX = 1.5   # above +150% an EPS growth rate is a recovery off a trough, not a cash-flow rate
FADE_YEARS = 5         # years 6-10
NEAR_LOW, NEAR_HIGH = 0.75, 1.33    # years 1-2 tolerance vs consensus earnings (x (1+c1)(1+c2))
FAR_LOW, FAR_HIGH = NEAR_LOW, NEAR_HIGH   # one rule: more than a quarter away from consensus needs a reason
LEVEL_TOL = 0.15       # E18: a year-2 cash flow more than 15% from the printed level needs a reason
RANGE_MIN_ANALYSTS = 3  # E12 F1: fewer analysts give no range (high = low = average)
WINDOW_TOL = 0.15       # whole-book test: FY and TTM windows further apart than this print both references
STALE_MONTHS = 15       # whole-book test: history older than this builds no reference
VINTAGE_TOL = 0.02      # the vendor's year-ago revenue against the filed fiscal year


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
    """Years 1-5 growth: consensus EPS growth, then a fade from next-FY revenue growth toward the
    base-rate median, never above next-FY revenue growth. With no revenue estimate the fade starts
    AT the median (Fable check: falling back to EPS growth made the reference more generous exactly
    when data was thinner)."""
    return [c1, c2] + _years35(rev_g2, median_5y)


def _years35(rev_g2, median_5y):
    if rev_g2 is None:
        return _fade35(median_5y, median_5y)
    return _fade35(rev_g2, min(median_5y, rev_g2))


def _fade35(start, target):
    return [start + (target - start) / 3, start + (target - start) * 2 / 3, target]


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


def range_levels(estimates, flow2):
    """E18: Bull and Bear year-2 cash-flow levels at the next-FY EPS high and low, scaled from the
    year-2 level, or None when there is no consensus range (fewer than 3 analysts, or high = low)."""
    eps = ((estimates or {}).get("+1y") or {}).get("eps") or {}
    hi, lo, avg, n = eps.get("high"), eps.get("low"), eps.get("avg"), eps.get("analysts") or 0
    if not (flow2 and n >= RANGE_MIN_ANALYSTS and all(isinstance(x, (int, float)) for x in (hi, lo, avg))
            and avg > 0 and hi != lo):
        return None
    return flow2 * hi / avg, flow2 * lo / avg, int(n)


def vintage_aligned(estimates, fy_revenue):
    """True when the vendor's current-year estimates start from the filed fiscal year (its year-ago
    revenue is that year's revenue), False when they start from a later year, None if unknown."""
    ya = (((estimates or {}).get("0y") or {}).get("revenue") or {}).get("year_ago")
    if not (isinstance(ya, (int, float)) and isinstance(fy_revenue, (int, float)) and fy_revenue > 0):
        return None
    return abs(ya / fy_revenue - 1) <= VINTAGE_TOL


def build(base_cf, estimates, coe, terminal_g, shares, median_5y, da=None, capex=None,
          stub_months=None, base_label=None, levels_reason=None, levels_block=None):
    """Everything the pack prints: {'value', 'method', 'path', 'flows', 'c1', 'c2', 'reason',
    'levels', 'range', 'stub_months', 'base_label', 'levels_reason'}.
    method "growth": years 1-2 at consensus EPS growth on the owner-earnings base.
    method "levels": years 1-2 are consensus EPS x diluted shares + D&A - capex, when consensus EPS
    growth is unusable, when the base is not positive, or when `levels_reason` says why the base
    cannot carry the consensus rates. `value` is None, with a reason, when neither can be computed.
    `levels_block` (review B1): why the vendor's EPS levels may not be combined with the filed D&A
    and capex for this company (the vintage test failed or could not run); the levels method is then
    not available.
    E18: with `stub_months` (months since the base fiscal year ended), the value is taken at that
    fiscal year end and rolled forward to today at coe."""
    c1, c2, why = consensus_earnings_growth(estimates)
    out = {"value": None, "method": None, "path": None, "flows": None, "c1": c1, "c2": c2,
           "reason": None, "growth_unusable": why, "levels": None, "range": None,
           "stub_months": stub_months, "base_label": base_label, "levels_reason": None}
    missing = [n for n, v in (("cost-of-equity anchor", coe), ("terminal-growth anchor", terminal_g),
                              ("diluted shares", shares), ("growth base-rate median", median_5y))
               if v is None]
    if missing:
        out["reason"] = f"{', '.join(missing)} missing"
        return out
    rev_g2 = revenue_growth_next_fy(estimates)
    roll = (1 + coe) ** (stub_months / 12) if stub_months else 1.0
    if why is None and levels_reason is None and base_cf is None:
        out["reason"] = "owner-earnings base missing"
        return out
    if why is None and levels_reason is None and base_cf <= 0:
        # whole-book test (LIVN): a loss year cannot carry growth rates; the EPS levels can
        levels_reason = "the fiscal-year owner-earnings base is not positive"
    if why is None and levels_reason is None:
        out["path"] = reference_path(c1, c2, rev_g2, median_5y)
        out["method"] = "growth"
        v = reference_value(base_cf, out["path"], coe, terminal_g, shares)
        if v is None:
            out["reason"] = "cost of equity not above terminal growth"
        else:
            out["value"] = v * roll
            f1 = base_cf * (1 + c1)
            out["levels"] = (f1, f1 * (1 + c2))
            out["range"] = range_levels(estimates, out["levels"][1])
        return out
    out["levels_reason"] = levels_reason
    why = why or levels_reason
    if levels_block:
        out["reason"] = f"{why}; the EPS levels are not used: {levels_block}"
        return out
    levels = consensus_eps_levels(estimates)
    if levels is None or da is None or capex is None:
        out["reason"] = why + ("" if levels else "; no positive next-FY EPS level") + \
            ("" if da is not None and capex is not None else "; D&A or capex missing")
        return out
    flows = (levels[0] * shares + da - capex, levels[1] * shares + da - capex)
    path35 = _years35(rev_g2, median_5y)
    v = reference_value_levels(flows[0], flows[1], path35, coe, terminal_g, shares)
    out.update(method="levels", flows=flows, path=[None, None] + path35, levels=flows,
               value=v * roll if v is not None else None,
               range=range_levels(estimates, flows[1]))
    if out["value"] is None:
        out["reason"] = why + "; next-FY cash flow from EPS levels is not positive"
    return out


def window_check(ref, fy_base, ttm_base, quarters):
    """The FY and TTM owner-earnings windows against each other, net of the consensus growth for
    the `quarters` of the current fiscal year the TTM holds: gap = TTM / (FY x (1+c1)^(q/4)) - 1.
    {'gap', 'quarters', 'expected_ttm', 'flag'}, plus the TTM window's reference and levels (the
    fiscal-year ones scaled by 1+gap: the same period, the other window's base) when flagged.
    None when the reference is not on the growth method or an input is missing."""
    if (ref.get("method") != "growth" or not ref.get("value") or not isinstance(fy_base, (int, float))
            or fy_base <= 0 or not isinstance(ttm_base, (int, float)) or quarters is None
            or not isinstance(ref.get("c1"), (int, float))):
        return None
    expected = fy_base * (1 + ref["c1"]) ** (quarters / 4)
    gap = ttm_base / expected - 1
    out = {"gap": gap, "quarters": quarters, "expected_ttm": expected, "flag": abs(gap) > WINDOW_TOL,
           "ttm_value": None, "ttm_levels": None}
    if out["flag"] and ttm_base > 0:
        out["ttm_value"] = ref["value"] * (1 + gap)
        out["ttm_levels"] = tuple(x * (1 + gap) for x in ref["levels"])
    return out


def fence_window(win, side, fence):
    """Review B2: a TTM-window value outside the street fence is withheld, as E15 withholds the
    fiscal-year one; the line then prints the side of the fence."""
    if not (win and win.get("ttm_value") is not None and side):
        return win
    return dict(win, ttm_value=None, ttm_levels=None, fence_side=side, fence=fence)


def window_line(win, ref, ttm_base, through, fmt_b):
    """SECTION 8's BASE WINDOW CHECK, printed only when the windows are more than WINDOW_TOL apart.
    The prefixes are fixed: the harness parses the gap, the TTM reference and its year-2 level."""
    if not (win and win["flag"]):
        return None
    if win.get("fence_side"):
        # review B2: the E15 fence applies to the TTM window's value too; its side, never its number
        lo, hi = win["fence"]
        alt = (f"On the TTM window the consensus path lands {win['fence_side']} the street fence "
               f"[${lo:,.2f}, ${hi:,.2f}], so its value is not shown: a Base on that window needs "
               f"guidance_deviation_reason")
    elif win["ttm_value"] is not None:
        alt = (f"On the TTM window the consensus path is worth ${win['ttm_value']:,.2f} per share, year-2 "
               f"cash-flow level {fmt_b(win['ttm_levels'][1])}")
    else:
        alt = "The TTM window's owner earnings are not positive"
    return (f"- [Arithmetic] BASE WINDOW CHECK: base_window_gap {win['gap'] * 100:+.0f}%. TTM owner earnings "
            f"(through {through}) are {fmt_b(ttm_base)}; the fiscal-year base grown by the consensus "
            f"current-FY EPS growth for the {win['quarters']} quarter(s) between them is "
            f"{fmt_b(win['expected_ttm'])}. One of the two windows holds items the other does not (a one-off "
            f"gain or charge, a capex swing). {alt}; on the fiscal-year window ${ref['value']:,.2f} (the "
            f"CONSENSUS-IMPLIED VALUE above). The BASE-YEAR CHECK shows the analysts' own year-ago EPS against "
            f"the filed year. Name in base_cf_reason the window you judge representative, and anchor to its "
            f"reference and year-2 level.")


def pack_line(ref, base_cf, coe, terminal_g, fmt_b):
    """SECTION 8's line. The prefixes are fixed: the harness parses the value and the levels
    (consensus_valuation)."""
    if ref.get("value") is None:
        return f"- CONSENSUS-IMPLIED VALUE: not available — {ref.get('reason')}"
    head = (f"- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): ${ref['value']:,.2f} "
            f"per share — the analysts' own earnings path at our discount rate. ")
    stub = ref.get("stub_months")
    roll = (f"; valued at the fiscal year end and rolled forward {stub:.0f} months to today"
            if stub else "")
    tail = (f"; then a 5-year fade to the terminal-growth anchor {terminal_g * 100:.2f}%; discounted at "
            f"the COE ANCHOR {coe * 100:.2f}%{roll}. A Base IV more than a quarter away from it (below 0.75x "
            f"or above 1.33x) needs guidance_deviation_reason.")
    lv = ref.get("levels")
    lv_txt = ""
    if lv:
        lv_txt = (f" Consensus cash-flow levels: year 1 {fmt_b(lv[0])}, year 2 {fmt_b(lv[1])} — your Base "
                  f"year-2 cash flow should land within 15% of the year-2 level from whatever base you declare")
        rng = ref.get("range")
        if rng:
            lv_txt += (f"; Bull year 2 {fmt_b(rng[0])} and Bear year 2 {fmt_b(rng[1])} at the next-FY EPS "
                       f"high and low ({rng[2]} analysts)")
        lv_txt += "."
    label = ref.get("base_label")
    if ref["method"] == "growth":
        path = " / ".join(f"{g * 100:+.1f}%" for g in ref["path"])
        base_txt = f"Owner-earnings base {fmt_b(base_cf)}" + (f" ({label})" if label else "")
        return (head + f"{base_txt}; cash-flow growth years 1-5 {path} (years 1-2 = consensus EPS "
                f"growth; from year 3, next-FY revenue growth fading toward the GROWTH BASE RATES median, "
                f"never above next-FY revenue growth)" + tail + lv_txt)
    g35 = " / ".join(f"{g * 100:+.1f}%" for g in ref["path"][2:])
    why = (f"Years 1-2 are consensus EPS x diluted shares + D&A - capex because {ref['levels_reason']}"
           if ref.get("levels_reason") else
           f"Consensus EPS growth is unusable ({ref['growth_unusable']}), so years 1-2 are "
           f"consensus EPS x diluted shares + D&A - capex")
    return (head + f"{why}: {fmt_b(ref['flows'][0])}, "
            f"{fmt_b(ref['flows'][1])}; years 3-5 growth {g35} (next-FY revenue growth fading toward the "
            f"GROWTH BASE RATES median, never above next-FY revenue growth)" + tail + lv_txt)
