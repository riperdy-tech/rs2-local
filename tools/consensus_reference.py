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

Revision 17 (brief B, the through-cycle package). The window no longer changes the Base's
arithmetic (the desk holds years 1-2 at the fiscal-year levels); the BASE WINDOW CHECK stays as
information. The reference now values the long run from the company's own record
(tools/throughcycle_record.py):
- An earnings path (X = net income before acquired-intangible amortization, revenue) runs beside the
  owner-earnings path. Years 1-5 cash flow is
  owner earnings less the working capital the revenue growth ties up (the record's median NWC /
  revenue). From year 6, growth is paid for: cash flow = earnings x (1 - g / max(r, RONIC)), where
  RONIC fades from the record's blended return on new capital (r_blend) toward the return on new
  investment the record supports (RONIC_T), and the earnings margin moves toward the company's own median
  operating margin by the fraction brief E measured (`margin_rule`, brief F). Terminal growth is the
  company's own revenue trend held between breakeven inflation and the anchor (`terminal_growth_default`).
- A one-time gain in the base year was removed when the vendor's year-ago EPS showed it (`base_year_cap`); revision 18
  removed the cap's action (the function stays below, unused, as the record of what revision 17 did).
- With RONIC_T = +inf, no cycle and no working capital the arithmetic reduces to revision 16's
  (`reference_value`, kept for that test): the long-run arithmetic is `long_run_value`, the one copy
  the desk (financial_model_tool) also uses.

Revision 18 (brief rev18 design, section 1; the structure the backtest tested):
- Returns: RONIC_0 = max(r, R_tc) and RONIC_T = r + p x max(0, R_tc - r) (+inf when R_tc is +inf), from the record
  (throughcycle_record.analyse); no blend and no caps.
- Margins: the long-run operating margin is max(0, om_trend), the record's trend level, reached linearly over years 6-10
  (`margin_rule`); the peak/trough cells, the loss cell and the calibration file are gone.
- Cash at face for non-financial companies (`cash_term`, `build(cash=...)`): the after-tax interest on cash and short-term
  investments is taken out of the earnings the long run capitalises, and the cash itself is added at face, per share.
- The base-year cap no longer acts.
"""

import math

import throughcycle_record

EPS_GROWTH_MAX = 1.5   # above +150% an EPS growth rate is a recovery off a trough, not a cash-flow rate
FADE_YEARS = 5         # years 6-10
NEAR_LOW, NEAR_HIGH = 0.75, 1.33    # years 1-2 tolerance vs consensus earnings (x (1+c1)(1+c2))
FAR_LOW, FAR_HIGH = NEAR_LOW, NEAR_HIGH   # one rule: more than a quarter away from consensus needs a reason
LEVEL_TOL = 0.15       # E18: a year-2 cash flow more than 15% from the printed level needs a reason
RANGE_MIN_ANALYSTS = 3  # E12 F1: fewer analysts give no range (high = low = average)
WINDOW_TOL = 0.15       # whole-book test: FY and TTM windows further apart than this print both references
STALE_MONTHS = 15       # whole-book test: history older than this builds no reference
VINTAGE_TOL = 0.02      # the vendor's year-ago revenue against the filed fiscal year
BASE_CAP_TOL = 0.02     # rev 17: filed EPS above the vendor's year-ago EPS by more than this was capped (revision 18: unused)
FINANCIAL_SECTORS = ("Financial Services", "Real Estate")    # rev 18: no cash term (cash is an operating asset there)
OUTSIDE_FENCE = ("outside_fence_above", "outside_fence_below")   # rev 18: reference_status values of a value printed but fenced
LEVELS_HOLD_TOL = 0.05  # rev 17: the desk holds Base years 1-2 at the levels when year 2 is further off than this


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


def terminal_default(anchor, breakeven, rev_g2, median_5y):
    """Pure helper for Phase 4 T1: per-name terminal-growth default.
    When rev_g2 is known and below anchor, default is min(anchor, max(breakeven, y5)),
    where y5 is the reference path's year-5 growth.
    If breakeven is unavailable, default is anchor with a reason saying the floor is not available.
    Returns (value, reason).
    """
    if anchor is None:
        return None, None
    if rev_g2 is None or not (isinstance(rev_g2, (int, float)) and rev_g2 < anchor):
        return anchor, None
    if breakeven is None:
        return anchor, "the 10-year breakeven inflation floor is not available"

    if median_5y is not None:
        y5 = _years35(rev_g2, median_5y)[-1]
    else:
        y5 = rev_g2
    val = min(anchor, max(breakeven, y5))
    if val == anchor:
        return anchor, None
    reason = f"next-FY consensus revenue growth ({rev_g2 * 100:.1f}%) is below the anchor"
    return val, reason


def terminal_growth_default(anchor, breakeven, g_rev, rev_g2, median_5y):
    """Revision 17, brief B section 3: (value, basis, reason). The company's own revenue trend (the
    Theil-Sen growth of its record, `g_rev`) held between breakeven inflation and the anchor:
    min(anchor, max(breakeven, g_rev)), basis "revenue_trend". With no trend (a short record) or no
    breakeven the rule of revision 16 applies (`terminal_default`), basis "consensus_fallback".
    None values when the anchor is missing."""
    if anchor is None:
        return None, None, None
    if g_rev is not None and breakeven is not None:
        return min(anchor, max(breakeven, g_rev)), "revenue_trend", None
    val, reason = terminal_default(anchor, breakeven, rev_g2, median_5y)
    return val, "consensus_fallback", reason


def reference_in_force(status):
    """Revision 18 (brief 1.5): True when a printed reference value may drive a band, a departure reason or a desk refusal.
    A value outside the street-target fence is printed with its status and is annotation only; a status of None (an older
    block or a hand-built facts dict that carries a value without a status) reads as in force, as it did before."""
    return status not in OUTSIDE_FENCE


def classify_status(value, fence_side):
    """The reference's status, one rule for the pack and the ledger (revision 18): no value is "not_available"; a value of zero
    or less as printed to the cent is "not_meaningful" (the fence is not evaluated for it); otherwise "outside_fence_above" /
    "outside_fence_below" when `fence_side()` says so, else "used". `fence_side` is a zero-argument callable returning
    "above", "below" or None, called only when the fence applies."""
    if value is None:
        return "not_available"
    if float(f"{value:.2f}") <= 0:
        return "not_meaningful"
    side = fence_side()
    return f"outside_fence_{side}" if side else "used"


def base_year_cap(filed_ni, filed_shares, vendor_eps):
    """Revision 17, brief B section 2a (revision 18: no caller acts on it any more; kept as the record of that rule): a one-time gain in the base year (LAMR's Vistar gain), seen
    as the filed EPS above the vendor's year-ago EPS. None unless filed EPS exceeds the vendor's by
    more than BASE_CAP_TOL; never raised (filed EPS below the vendor's is kept, E10's
    conservatism). Otherwise {'eps_filed', 'eps_vendor', 'ni_filed', 'ni_capped', 'removed'}: the
    base net income becomes the vendor's EPS x the filed diluted shares, and `removed` is what the
    owner-earnings base is reduced by. The caller decides when this may run (the BASE-YEAR CHECK
    printed its numbers: vintage aligned, share counts within 15%)."""
    if not (isinstance(filed_ni, (int, float)) and isinstance(filed_shares, (int, float)) and filed_shares > 0
            and isinstance(vendor_eps, (int, float)) and vendor_eps > 0):
        return None
    eps_filed = filed_ni / filed_shares
    if not eps_filed > vendor_eps * (1 + BASE_CAP_TOL):
        return None
    capped = vendor_eps * filed_shares
    return {"eps_filed": eps_filed, "eps_vendor": float(vendor_eps), "ni_filed": float(filed_ni),
            "ni_capped": capped, "removed": filed_ni - capped}


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def cash_term(row, bill_rate, sector):
    """Revision 18 (brief 1.3): cash at face for a non-financial company. `row` is the base fiscal year's row; `bill_rate`
    the mean 3-month bill rate over the 12 months to that year's end, as a fraction (None when it is not available); `sector`
    the screener sector. Returns {"applies", "financial", "cash", "interest", "stamps"}:
      financial sector ("Financial Services", "Real Estate"): applies False, cash 0.0, interest 0.0, no stamp;
      cash missing: applies False, stamp `cash_term_not_available`; no bill rate: applies False, stamp
      `cash_term_not_available_no_bill_rate` (cash None, interest 0.0 in both);
      else C_L = cash + short-term investments (a null short-term figure counts 0) and i_L = C_L x bill_rate x (1 - tax_L),
      tax_L = throughcycle_record.tax_rate(row)."""
    if sector in FINANCIAL_SECTORS:
        return {"applies": False, "financial": True, "cash": 0.0, "interest": 0.0, "stamps": []}
    cash, sti = row.get("cash"), row.get("st_investments")
    if not _finite(cash):
        return {"applies": False, "financial": False, "cash": None, "interest": 0.0, "stamps": ["cash_term_not_available"]}
    c = float(cash) + (float(sti) if _finite(sti) else 0.0)
    if not _finite(bill_rate):
        return {"applies": False, "financial": False, "cash": None, "interest": 0.0,
                "stamps": ["cash_term_not_available_no_bill_rate"]}
    return {"applies": True, "financial": False, "cash": c, "interest": c * bill_rate * (1.0 - throughcycle_record.tax_rate(row)),
            "stamps": []}


def vendor_revenue(estimates):
    """[current-FY, next-FY] revenue averages of the vendor's estimates, or None unless both exist
    with analysts behind them."""
    out = []
    for key in ("0y", "+1y"):
        rev = (((estimates or {}).get(key) or {}).get("revenue")) or {}
        avg = rev.get("avg")
        if not (rev.get("analysts") and isinstance(avg, (int, float)) and avg > 0):
            return None
        out.append(float(avg))
    return out


def margin_rule(rec, m5):
    """Revision 18: the margin moves all the way to the record's trend level by year 10.

    With m5 the consensus's year-5 earnings margin and the record's om_L, x_L, tax_L, om_trend (throughcycle_record: the
    trend level a + b x L of the margin series it chose):
      OM_5 = om_L + (m5 - x_L) / (1 - tax_L)  (x_L undefined: OM_5 = om_L, stamp `margin_rule_filed_anchor`);
      target = max(0, om_trend); OM_long = target;
      m_long = max(0, m5 + (1 - tax_L) x (target - OM_5)); ratio = m_long / m5.
    No rule (ratio None: the margin is held at m5, `reason` says why and a stamp records it) when m5 is not positive, when
    the record has no trend level (its own stamp `margin_record_not_available`, or the older
    `operating_margin_record_not_available`), or when OM_5 <= 0 (`margin_rule_unmeasured_current_loss`: a margin that is
    still a loss at year 5 is outside the cases the rule was built for, and it must not lift it above m5). The record's
    series is the operating margin, or the pre-tax margin where the company files no operating line (the record's
    om_basis starts with "pretax"; the arithmetic is the same and the text names the series, "series"). Returns
    {"om_trend", "om_tc", "om_L", "om_shape", "series", "om_5", "target", "m_long", "ratio", "reason", "stamps"}."""
    om_trend, om_L = rec.get("om_trend"), rec.get("om_L")
    name = throughcycle_record.margin_series_name(rec.get("om_basis"))
    out = {"om_trend": om_trend, "om_tc": rec.get("om_tc"), "om_L": om_L, "om_shape": rec.get("om_shape"), "series": name,
           "om_5": None, "target": None, "m_long": None, "ratio": None, "reason": None, "stamps": []}
    if not m5 > 0:
        out["reason"] = "the consensus's year-5 earnings margin is not positive"
        out["stamps"].append("margin_rule_year5_margin_not_positive")
        return out
    if om_trend is None or om_L is None:
        out["reason"] = "your record holds too few years of operating or pre-tax margin to measure its trend level"
        return out
    x_L, tax_L = rec.get("x_L"), rec.get("tax_L")
    if x_L is None:
        om_5 = om_L
        out["stamps"].append("margin_rule_filed_anchor")
    else:
        om_5 = om_L + (m5 - x_L) / (1.0 - tax_L)
    out["om_5"] = om_5
    if om_5 <= 0:
        trend_is = "is a loss and" if om_trend <= 0 else "is positive but"
        article = "an" if name == "operating" else "a"
        out["reason"] = (f"this company's 8-year trend-level {name} margin {trend_is} the consensus implies "
                         f"{article} {name} loss at year 5, which the rule does not cover")
        out["stamps"].append("margin_rule_unmeasured_current_loss")
        return out
    out["target"] = max(0.0, om_trend)
    out["m_long"] = max(0.0, m5 + (1.0 - tax_L) * (out["target"] - om_5))
    out["ratio"] = out["m_long"] / m5
    return out


def ronic_at(ronic0, ronic_t, frac):
    """RONIC of a long-run year: RONIC_0 + (RONIC_T - RONIC_0) x frac, frac = (t - 5) / fade years
    (RONIC_T from frac 1 on). With an infinite end point (a return on negative tangible equity) the
    interpolation is not defined: the start holds until frac reaches 1."""
    if frac >= 1:
        return ronic_t
    if frac <= 0 or ronic0 == ronic_t or math.isinf(ronic0) or math.isinf(ronic_t):
        return ronic0
    return ronic0 + (ronic_t - ronic0) * frac


def long_run_value(e5, g5, gt, r, ronic0, ronic_t, margin_ratio=None, fade_years=FADE_YEARS):
    """Revision 17, brief B section 2d-2e: the value, at the base fiscal year end, of everything after
    year 5. The one copy of this arithmetic; the reference and the desk both call it.

    e5: year-5 earnings; g5: the year-5 growth; gt: terminal growth; r: the discount rate.
    Years t = 6..5+F (F = fade_years): g_t = g5 + (gt - g5)(t-5)/F; earnings E_t = e5 x prod(1+g) x k_t,
    where the margin factor k_t = 1 + (margin_ratio - 1) x min(1, (t-5)/F) (margin_ratio = m_tc / m5;
    None = margin held); RONIC_t from `ronic_at`; cash flow_t = E_t (1 - g_{t+1} / max(r, RONIC_t)) with
    g_{N+1} = gt (an infinite RONIC charges nothing). Terminal: E_{N+1} = E_N (1+gt), TV = E_{N+1}
    (1 - gt / max(r, RONIC_T)) / (r - gt), discounted N years. F = 0 has no long-run years and no
    margin fade. A negative long-run value is floored at 0 (`floor`).

    None when r does not exceed gt. Else a dict: n_years, growth, earnings, margin_factor, ronic,
    flows (cash flows of years 6..N), pv_flows, e_terminal, tv, tv_pv, value_raw, value, floor."""
    if not r > gt:
        return None
    F = int(fade_years)
    n = 5 + F

    def g_at(t):
        return gt if (F == 0 or t > n) else g5 + (gt - g5) * (t - 5) / F

    growth, earnings, kfs, ronics, flows = [], [], [], [], []
    cum, pv_flows = 1.0, 0.0
    for t in range(6, n + 1):
        frac = (t - 5) / F
        g = g_at(t)
        cum *= 1 + g
        k = 1.0 if margin_ratio is None else 1 + (margin_ratio - 1) * min(1.0, frac)
        e = e5 * cum * k
        ron = ronic_at(ronic0, ronic_t, frac)
        cf = e * (1 - g_at(t + 1) / max(r, ron))
        growth.append(g)
        earnings.append(e)
        kfs.append(k)
        ronics.append(ron)
        flows.append(cf)
        pv_flows += cf / (1 + r) ** t
    k_end = 1.0 if (margin_ratio is None or F == 0) else margin_ratio
    e_terminal = e5 * cum * k_end * (1 + gt)
    tv = e_terminal * (1 - gt / max(r, ronic_t)) / (r - gt)
    tv_pv = tv / (1 + r) ** n
    raw = pv_flows + tv_pv
    return {"n_years": n, "growth": growth, "earnings": earnings, "margin_factor": kfs, "ronic": ronics,
            "flows": flows, "pv_flows": pv_flows, "e_terminal": e_terminal, "tv": tv, "tv_pv": tv_pv,
            "value_raw": raw, "value": max(0.0, raw), "floor": raw < 0}


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


def _compound(base, growth):
    """[base x (1+g1), base x (1+g1)(1+g2), ...]."""
    out, x = [], float(base)
    for g in growth:
        x *= 1 + g
        out.append(x)
    return out


def build(base_cf, estimates, coe, terminal_g, shares, median_5y, da=None, capex=None,
          stub_months=None, base_label=None, levels_reason=None, levels_block=None,
          anchor=None, record=None, base_ni=None, base_revenue=None, cash=None):
    """Everything the pack prints: {'value', 'method', 'path', 'flows', 'c1', 'c2', 'reason',
    'levels', 'range', 'stub_months', 'base_label', 'levels_reason'}, and (revision 17) 'earnings',
    'revenue', 'wc', 'nwc_intensity', 'long_run', 'long_run_path', 'terminal_ronic', 'ronic0',
    'base_cf', 'cash', 'interest_removed', 'stamps'.
    method "growth": years 1-2 at consensus EPS growth on the owner-earnings base.
    method "levels": years 1-2 are consensus EPS x diluted shares + D&A - capex, when consensus EPS
    growth is unusable, when the base is not positive, or when `levels_reason` says why the base
    cannot carry the consensus rates. `value` is None, with a reason, when neither can be computed.
    `levels_block` (review B1): why the vendor's EPS levels may not be combined with the filed D&A
    and capex for this company (the vintage test failed or could not run); the levels method is then
    not available, and the vendor's revenue is not combined with the filed revenue either.
    E18: with `stub_months` (months since the base fiscal year ended), the value is taken at that
    fiscal year end and rolled forward to today at coe.

    Revision 17 inputs: `record` (throughcycle_record.analyse's dict, computed at r = coe: r_blend,
    ronic_t, the operating-margin record om_tc / om_L / om_shape / x_L / tax_L, nwc_intensity; None = no
    record, stamped record_not_available with RONIC_T = coe); `base_ni` (X of the filed base year - net income plus acquired-intangible amortization after
    tax, throughcycle_record.adjusted_earnings - the earnings path's base in the growth method; the
    levels method's earnings are consensus EPS x shares, stamped levels_eps_basis); `base_revenue` (the
    filed base-year revenue).

    Revision 18 inputs: `record` carries R_tc (RONIC_0 = max(coe, R_tc); None = no return record), ronic_t and om_trend (the
    margin rule's target; None = margin held); `cash` (`cash_term`'s dict; None = no cash term). With a cash term that
    applies, the after-tax interest on the cash (i_L) is taken out of the earnings the long run capitalises: the growth
    method's base becomes base_cf - i_L and base_ni - i_L (and the record's x_L becomes (X_L - i_L) / revenue_L, so the margin
    rule does not add it back), the levels method's two cash-flow and two earnings levels each lose i_L, and the value gains
    cash / shares at face (not rolled forward). When the operating base (or the year-2 level) is no longer positive after i_L,
    the value is cash / shares, method "cash_only", stamp `operating_base_not_positive`. `shares` is the pack's share-count
    default."""
    c1, c2, why = consensus_earnings_growth(estimates)
    is_default = (anchor is not None and terminal_g is not None and abs(terminal_g - anchor) > 1e-6)
    out = {"value": None, "method": None, "path": None, "flows": None, "c1": c1, "c2": c2,
           "reason": None, "growth_unusable": why, "levels": None, "range": None,
           "stub_months": stub_months, "base_label": base_label, "levels_reason": None,
           "terminal_g_is_default": is_default,
           "earnings": None, "revenue": None, "wc": None, "long_run": None, "long_run_path": None,
           "terminal_ronic": None, "ronic0": None, "nwc_intensity": None, "base_cf": None,
           "cash": None, "interest_removed": None, "stamps": [],
           "margin": None, "om_5": None, "m_long": None,
           "margin_ratio": None}
    out["cash_term"] = ("applies" if (cash and cash.get("applies")) else "financial" if (cash and cash.get("financial"))
                        else "not_available" if cash else None)
    cash_on = bool(cash and cash.get("applies"))
    c_l = float(cash["cash"]) if cash_on else 0.0
    i_l = float(cash["interest"]) if cash_on else 0.0
    if cash:
        out["stamps"] += list(cash.get("stamps") or [])
    if cash_on:
        out["cash"], out["interest_removed"] = c_l, i_l
    missing = [n for n, v in (("cost-of-equity anchor", coe), ("terminal-growth anchor", terminal_g),
                              ("diluted shares", shares), ("growth base-rate median", median_5y))
               if v is None]
    if missing:
        out["reason"] = f"{', '.join(missing)} missing"
        return out
    if cash_on and why is None and levels_reason is None and base_cf is not None and base_cf > 0:
        # a name valued by the GROWTH method (usable consensus EPS growth, a positive base): the interest on the cash comes off
        # the base and off X. A name the levels method values is tested on its year-2 level below (a turnaround with a loss year
        # and positive consensus EPS is not worth only its cash), and one with no consensus has no reference at all.
        ni_after = None if base_ni is None else base_ni - i_l
        if base_cf - i_l <= 0 or (ni_after is not None and ni_after <= 0):
            return _cash_only(out, c_l, shares)
    rev_g2 = revenue_growth_next_fy(estimates)
    roll = (1 + coe) ** (stub_months / 12) if stub_months else 1.0
    if why is None and levels_reason is None and base_cf is None:
        out["reason"] = "owner-earnings base missing"
        return out
    if why is None and levels_reason is None and base_cf <= 0:
        # whole-book test (LIVN): a loss year cannot carry growth rates; the EPS levels can
        levels_reason = "the fiscal-year owner-earnings base is not positive"
    base = ni_base = None
    if why is None and levels_reason is None:
        # base_ni is X of the base year (net income before acquired-intangible amortization); with a cash term both the
        # owner-earnings base and X lose the after-tax interest on the cash
        base = base_cf - i_l
        ni_base = None if base_ni is None else base_ni - i_l
        if ni_base is None:
            out["reason"] = "base-year net income missing"
            return out
    if why is None and levels_reason is None:
        out["path"] = reference_path(c1, c2, rev_g2, median_5y)
        out["method"] = "growth"
        oe = _compound(base, out["path"])
        ni = _compound(ni_base, out["path"])
        out["base_cf"] = base
        out["levels"] = (oe[0], oe[1])
        out["range"] = range_levels(estimates, out["levels"][1])
    else:
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
        # the vendor's EPS basis (adjusted or GAAP) is unknown, so the levels method's earnings are not X
        out["stamps"].append("levels_eps_basis")
        if not flows[1] > 0:
            out.update(method="levels", flows=flows, path=[None, None] + path35, levels=flows,
                       range=range_levels(estimates, flows[1]))
            out["reason"] = why + "; next-FY cash flow from EPS levels is not positive"
            return out
        if cash_on:
            # revision 18: the vendor's EPS holds the interest on the cash; both levels of both series lose it
            flows = (flows[0] - i_l, flows[1] - i_l)
            if not flows[1] > 0:
                return _cash_only(out, c_l, shares)
        out.update(method="levels", flows=flows, path=[None, None] + path35, levels=flows,
                   range=range_levels(estimates, flows[1]))
        oe = list(flows) + _compound(flows[1], path35)
        ni = [levels[0] * shares - i_l, levels[1] * shares - i_l] + _compound(levels[1] * shares - i_l, path35)
    out["earnings"] = ni
    g5 = out["path"][-1]
    if coe <= terminal_g:
        out["reason"] = "cost of equity not above terminal growth"
        return out

    # revenue path: filed base-year revenue, the vendor's two revenue averages, then the years 3-5 growth
    revenue = None
    vr = vendor_revenue(estimates)
    if not levels_block and vr and isinstance(base_revenue, (int, float)) and base_revenue > 0:
        revenue = [float(base_revenue), vr[0], vr[1]] + _compound(vr[1], out["path"][2:])
    out["revenue"] = revenue

    # the record: return on new investment, cycle, margin, working capital
    rec = dict(record or {})
    r_tc, ronic_t = rec.get("R_tc"), rec.get("ronic_t")
    if ronic_t is None:
        ronic_t = coe
        out["stamps"].append("record_not_available")
    elif "record_not_available" in (rec.get("stamps") or []):
        out["stamps"].append("record_not_available")
    # brief F: the record's operating-margin stamps ride on the reference too
    out["stamps"] += [s for s in (rec.get("stamps") or []) if s.startswith(("operating_margin", "margin_record"))]
    ronic0 = coe if r_tc is None else max(coe, r_tc)
    if cash_on and rec.get("x_L") is not None and base_ni is not None and isinstance(base_revenue, (int, float)) and base_revenue > 0:
        # without this the margin rule would read the removed interest as an operating-margin change and add it back
        rec["x_L"] = (base_ni - i_l) / base_revenue
    out["terminal_ronic"], out["ronic0"] = ronic_t, ronic0

    # years 1-5 cash flow: owner earnings less the working capital the revenue growth ties up
    nwc = rec.get("nwc_intensity")
    wc = None
    if revenue is not None and nwc is not None:
        wc = [nwc * (revenue[t] - revenue[t - 1]) for t in range(1, 6)]
    elif revenue is not None:
        out["stamps"].append("working_capital_not_available")
    out["wc"], out["nwc_intensity"] = wc, nwc
    cash = [oe[t] - (wc[t] if wc else 0.0) for t in range(5)]
    pv15 = sum(cf / (1 + coe) ** (t + 1) for t, cf in enumerate(cash))

    # the long run
    e5, oe5, m5, margin_ratio = ni[4], oe[4], None, None
    if revenue is not None:
        out["long_run_path"] = "revenue"
        m5 = e5 / revenue[5]
        rule = margin_rule(rec, m5)
        margin_ratio = rule["ratio"]
        out["stamps"] += rule["stamps"]
        out["margin"] = rule
        out.update(om_5=rule["om_5"], m_long=rule["m_long"], margin_ratio=margin_ratio)
    else:
        out["long_run_path"] = "owner_earnings_ratio"
        if not (e5 > 0 and oe5 > 0):
            out["reason"] = ("no revenue path (the vendor's revenue is missing or not on the filed basis) and "
                             "year-5 earnings or owner earnings is not positive")
            return out
    lr = long_run_value(e5, g5, terminal_g, coe, ronic0, ronic_t, margin_ratio)
    if lr["floor"]:
        out["stamps"].append("long_run_floor")
    out["long_run"] = dict(lr, e5=e5, oe5=oe5, m5=m5, margin_ratio=margin_ratio, g5=g5)
    out["value"] = (pv15 + lr["value"]) / shares * roll + c_l / shares
    return out


def _cash_only(out, c_l, shares):
    """The operating base is not positive once the interest on the cash is taken out: the operating business is worth
    nothing and the value is the cash at face per share (stamp `operating_base_not_positive`)."""
    out["method"] = "cash_only"
    out["stamps"].append("operating_base_not_positive")
    out["value"] = c_l / shares
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


# S3 5.6 (2026-09-28): both functions below are rewritten as typed, pipe-separated clauses; the
# instruction clauses that named a *_reason field are gone (those rules now live in the DEFAULTS
# block, 5.2, and the desk's own refusals, 3.4-3.5). Every number and the gap stay. `fmt_b` is now
# called with a bare-number formatter (capability_test._bn, S3 5.7) rather than `_b`, so a $B
# quantity here carries no unit of its own — the per-share values keep their literal "$" since
# they are prices, not the $B `fmt_b` covers.


def window_line(win, ref, ttm_base, through, fmt_b, base_year_check=True):
    """SECTION 8's BASE WINDOW CHECK, printed only when the windows are more than WINDOW_TOL apart.
    The prefixes are fixed: the harness parses the gap, the TTM reference and its year-2 level."""
    if not (win and win["flag"]):
        return None
    if win.get("fence_side"):
        # review B2: the E15 fence applies to the TTM window's value too; its side, never its number
        lo, hi = win["fence"]
        alt = (f"on the TTM window the consensus path lands {win['fence_side']} the street fence "
               f"[${lo:,.2f}, ${hi:,.2f}], not shown")
    elif win["ttm_value"] is not None:
        alt = (f"on the TTM window the consensus path is worth ${win['ttm_value']:,.2f} per share, "
               f"year-2 cash-flow level {fmt_b(win['ttm_levels'][1])}")
    else:
        alt = "the TTM window's owner earnings are not positive"
    clauses = [f"[Arithmetic] BASE WINDOW CHECK: base_window_gap {win['gap'] * 100:+.0f}%",
              f"TTM owner earnings (through {through}) {fmt_b(ttm_base)}",
              f"the fiscal-year base grown by the consensus current-FY EPS growth for "
              f"{win['quarters']} quarter(s) between them is {fmt_b(win['expected_ttm'])} "
              f"(one of the two windows holds items the other does not: a one-off gain or "
              f"charge, a capex swing)",
              alt,
              f"on the fiscal-year window ${ref['value']:,.2f} (the CONSENSUS-IMPLIED VALUE above)"]
    # review R7: point to the BASE-YEAR CHECK only where it printed its numbers
    if base_year_check:
        clauses.append("the BASE-YEAR CHECK shows the analysts' own year-ago EPS against the "
                       "filed year")
    return "- " + " | ".join(clauses)


def _return_txt(x):
    """A return on new investment as a percent; infinite = growth on negative tangible equity."""
    return "unlimited" if x is not None and math.isinf(x) else f"{x * 100:.1f}%"


def _margin_clause(rule, m5):
    """Brief F2, revision 18: how the earnings margin moves from year 5 to year 10, or why it is held (`margin_rule`'s dict)."""
    if rule["ratio"] is None:
        return f"earnings margin held at {m5 * 100:.1f}%: {rule['reason']}"
    head = f"earnings margin moving from {m5 * 100:.1f}% to {rule['m_long'] * 100:.1f}% by year 10: "
    return (head + f"the {rule['series']} margin moves to the trend level of your 8-year record ({rule['target'] * 100:.1f}%) "
            f"by year 10 (the consensus implies {rule['om_5'] * 100:.1f}% at year 5)")


def _long_run_clause(ref):
    """Revision 17: the one clause that states how the long run (year 6 on) is valued. None when the
    reference has no long run (levels reasons that stop before it)."""
    lr = ref.get("long_run")
    if not lr:
        return None
    if "record_not_available" in ref.get("stamps", []):
        pay = ("from year 6 growth is paid for at the cost of equity (your record is not available, so "
               "new investment earns no more than its cost)")
    else:
        r0, rt = ref["ronic0"], ref["terminal_ronic"]
        pay = (f"from year 6 growth is paid for at the median return on tangible capital your record shows "
               f"({_return_txt(r0)} in year 5, {_return_txt(rt)} from year 10)")
    if ref.get("long_run_path") == "revenue":
        m = _margin_clause(ref["margin"], lr["m5"])
    else:
        m = ("no revenue path (the vendor's revenue is missing or not on the filed basis), so earnings follow "
             "owner earnings at the year-5 ratio of earnings to owner earnings")
    out = f"{pay}; {m}"
    if lr.get("floor"):
        out += "; the long-run value is negative and is floored at zero"
    return out


def _working_capital_clause(ref, fmt_b):
    """Revision 17: the working capital deducted from years 1-5, or why there is none. None when the
    reference has no revenue path (the long-run clause says so)."""
    if ref.get("revenue") is None:
        return None
    wc = ref.get("wc")
    if wc is None:
        return "working capital: not deducted (your record holds no classified balance sheet for it)"
    return (f"working capital deducted in years 1-5: {' / '.join(fmt_b(x) for x in wc)} "
            f"({ref['nwc_intensity'] * 100:.1f}% of each year's revenue change)")


def _cash_clause(ref, fmt_b):
    """Revision 18 (brief 3.1, Cash): what the reference does with the cash. None when the reference carries no cash-term state
    (a caller that passed no cash term at all)."""
    state = ref.get("cash_term")
    if state == "applies":
        return (f"plus excess cash ${fmt_b(ref['cash'])}B at face (after-tax interest on it removed from earnings)")
    if state == "financial":
        return "no excess-cash term (financial company)"
    if state == "not_available":
        why = ", ".join(s for s in (ref.get("stamps") or []) if s.startswith("cash_term")) or "cash_term_not_available"
        return f"no excess-cash term (not available: {why})"
    return None


def not_meaningful_line(ref):
    """Brief F5: SECTION 8's line for a reference whose value is zero or less. It prints no number, only that there is no
    positive value and the reference's own reason or stamps."""
    why = "; ".join(x for x in (ref.get("reason"), ", ".join(ref.get("stamps") or [])) if x)
    return ("- CONSENSUS-IMPLIED VALUE: not meaningful — the consensus path and this company's record give no "
            "positive value" + (f" ({why})" if why else ""))


ANCHOR_ROLE = ("— a calibrated level anchor, not a buy signal: on point-in-time data (valuation dates 2017–2023, returns to 2026) this method valued stocks that went on to earn an average return within ±15% of their price, but it ranked stocks only weakly, and its 'worth 30% more than the price' calls beat the S&P only about 2 points more often than an average stock in 2019–2023, and less often in 2017–2018.")


def pack_line(ref, base_cf, coe, terminal_g, fmt_b, anchor=None, closure_asof=None):
    """SECTION 8's line. The prefixes are fixed: the harness parses the value and the levels
    (consensus_valuation). Revision 18: the label's value is followed by the anchor-role sentence (`ANCHOR_ROLE`); `closure_asof`
    (the closure premium's date) completes the discount clause."""
    if ref.get("value") is None:
        return f"- CONSENSUS-IMPLIED VALUE: not available — {ref.get('reason')}"
    clauses = [f"[Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): "
              f"${ref['value']:,.2f} per share, the analysts' own earnings path at our discount rate " + ANCHOR_ROLE]

    label = ref.get("base_label")
    if ref["method"] == "cash_only":
        # revision 18: the interest on the cash leaves no positive operating base
        return "- " + " | ".join(clauses + [
            f"base: owner earnings {fmt_b(base_cf)} less the after-tax interest on excess cash "
            f"{fmt_b(ref['interest_removed'])} is not positive, so the operating business is valued at zero and the value is "
            f"the excess cash {fmt_b(ref['cash'])} at face (operating_base_not_positive)"])
    if ref["method"] == "growth":
        if ref.get("interest_removed"):
            # revision 18: the base printed is the one the long run capitalises, the cash term's interest already out
            base_cf = ref.get("base_cf") if ref.get("base_cf") is not None else base_cf
        clauses.append(f"base: owner earnings {fmt_b(base_cf)}" + (f" ({label})" if label else ""))
        path = " / ".join(f"{g * 100:+.1f}%" for g in ref["path"])
        clauses.append(f"cash-flow growth years 1-5: {path} (years 1-2 consensus EPS growth; "
                       f"from year 3, next-FY revenue growth fading toward the base-rate median, "
                       f"never above next-FY revenue growth)")
    else:
        why = (f"years 1-2 are consensus EPS x diluted shares + D&A - capex because "
               f"{ref['levels_reason']}" if ref.get("levels_reason") else
               f"consensus EPS growth is unusable ({ref['growth_unusable']}), so years 1-2 are "
               f"consensus EPS x diluted shares + D&A - capex")
        clauses.append(f"base: {why}: {fmt_b(ref['flows'][0])}, {fmt_b(ref['flows'][1])}"
                       + (f" ({label})" if label else ""))
        g35 = " / ".join(f"{g * 100:+.1f}%" for g in ref["path"][2:])
        clauses.append(f"years 3-5 growth {g35} (next-FY revenue growth fading toward the "
                       f"base-rate median, never above next-FY revenue growth)")

    differs = (anchor is not None and abs(terminal_g - anchor) > 1e-6) or bool(ref.get("terminal_g_is_default"))
    tg_label = "terminal-growth default" if differs else "terminal-growth anchor"
    clauses.append(f"then a 5-year fade to the {tg_label} {terminal_g * 100:.2f}%")
    lr_clause = _long_run_clause(ref)
    if lr_clause:
        clauses.append(lr_clause)
    wc_clause = _working_capital_clause(ref, fmt_b)
    if wc_clause:
        clauses.append(wc_clause)
    cash_clause = _cash_clause(ref, fmt_b)
    if cash_clause:
        clauses.append(cash_clause)
    if closure_asof:
        clauses.append(f"discounted at the COE ANCHOR {coe * 100:.2f}%, built from the market-consistent premium "
                       f"(rs2 closure, as of {closure_asof})")
    else:
        clauses.append(f"discounted at the COE ANCHOR {coe * 100:.2f}%")
    stub = ref.get("stub_months")
    if stub:
        clauses.append(f"valued at the fiscal year end, rolled forward {stub:.0f} months")

    lv = ref.get("levels")
    if lv:
        lv_clause = f"levels: year 1 {fmt_b(lv[0])}, year 2 {fmt_b(lv[1])}"
        rng = ref.get("range")
        if rng:
            lv_clause += (f"; Bull year 2 {fmt_b(rng[0])}, Bear year 2 {fmt_b(rng[1])} (next-FY "
                          f"EPS high and low, {rng[2]} analysts)")
        clauses.append(lv_clause)

    return "- " + " | ".join(clauses)
