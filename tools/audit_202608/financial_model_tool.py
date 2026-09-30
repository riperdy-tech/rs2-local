#!/usr/bin/env python3
"""financial_model_tool.py — Deterministic Financial Modeling Analyst Desk.

Provides exact arithmetic mid-stream for RS2 depth underwritings:
1. unbundled_dcf: DCF with separate installed-base service annuity streams (avoids double-counting).
2. reverse_dcf_expectations_gap: Solves for market-implied growth at T0 price vs demonstrated CAGR.
3. continuous_multi_outcome_kelly: Multi-scenario log-wealth optimization (strictly 0.0% if edge <= 0).
4. calculate_payoff_skew: Mathematical upside/downside ratio.
5. blend: Weighted combination of named desk valuation legs.
6. execute_financial_model: Master dispatcher and formatter for LLM function calling.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure STOCKS_ROOT has fallback to C:\Users\riper\stocks if not in environment
os.environ.setdefault("STOCKS_ROOT", r"C:\Users\riper\stocks")

# Ensure repository root is on sys.path for rate_engine
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# consensus_reference.py (LEVEL_TOL/FAR_LOW/FAR_HIGH, the long-run arithmetic) lives at repo_root/tools
_REPO_TOOLS = _REPO_ROOT / "tools"
if str(_REPO_TOOLS) not in sys.path:
    sys.path.insert(0, str(_REPO_TOOLS))

import rate_engine
import consensus_reference

# Revision 17 (brief B 4i): the unit rule for sbc_dilution.
SBC_DILUTION_UNIT_MESSAGE = "sbc_dilution is a fraction below 1 (0.02 = 2%) or a whole number of new shares"


def _normalize_cash_flow_life(val):
    """S3 3.4 V1: normalise cash_flow_life to 'perpetual' or int 1-60 (whole-number float or digit
    string accepted). Anything else is returned as given. Moved here from
    consensus_valuation.py (revision 12) so the desk's own V1 check and the harness's flag use one
    copy; consensus_valuation imports it back."""
    if val is None or type(val) is bool:
        return val
    if isinstance(val, str):
        s = val.strip()
        if s.lower() == "perpetual":
            return "perpetual"
        try:
            f = float(s)
            if f.is_integer() and 1 <= int(f) <= 60:
                return int(f)
        except (ValueError, TypeError):
            pass
        return val
    if isinstance(val, (int, float)):
        try:
            f = float(val)
            if f.is_integer() and 1 <= int(f) <= 60:
                return int(f)
        except (ValueError, TypeError):
            pass
        return val
    return val


def _validate_required_dcf_inputs(
    terminal_g: Any,
    shares_diluted: Any,
    fade_years: Any,
    sbc_treatment: Any,
    sbc_dilution: Any = None,
) -> Optional[Dict[str, Any]]:
    """Validate required DCF inputs per Phase 4 (no silent defaults)."""
    missing = []
    if terminal_g is None:
        missing.append("terminal_g")

    if shares_diluted is None:
        missing.append("shares_diluted")
    else:
        try:
            sd = float(shares_diluted)
            if sd <= 0 or math.isnan(sd):
                missing.append("shares_diluted")
        except (ValueError, TypeError):
            missing.append("shares_diluted")

    if fade_years is None or type(fade_years) is bool:
        missing.append("fade_years")
    elif not isinstance(fade_years, int) or fade_years < 0:
        missing.append("fade_years")

    if sbc_treatment is None:
        missing.append("sbc_treatment")
    else:
        sbc_norm = str(sbc_treatment).strip().lower()
        if sbc_norm not in ("deducted_in_cf", "dilution", "add_back_dilution"):
            missing.append("sbc_treatment")
        elif sbc_norm in ("dilution", "add_back_dilution"):
            if sbc_dilution is None:
                missing.append("sbc_dilution")
            else:
                try:
                    s_dil = float(sbc_dilution)
                    if s_dil <= 0 or math.isnan(s_dil):
                        missing.append("sbc_dilution")
                except (ValueError, TypeError):
                    missing.append("sbc_dilution")

    if missing:
        comma_list = ", ".join(missing)
        term_phrase = " (terminal_g is required)" if "terminal_g" in missing else ""
        return {
            "error": f"missing required inputs: {comma_list}{term_phrase} (no silent defaults since Phase 4)",
            "missing": missing,
            "validation_error": True,
        }
    return None


def applied_years_1_to_5(
    rates: Optional[List[float]],
    terminal_g: Optional[float] = None,
    fade_years: Optional[int] = None,
    finite_life_years: Optional[int] = None,
) -> List[float]:
    """Applied growth of each of years 1-5 as unbundled_dcf applies it, unrounded:
    - first the explicit rates as given;
    - then the linear fade from the last explicit rate to terminal_g over fade_years, using the same formula;
    - then terminal_g for any later year, including years that fall inside the terminal value;
    - the list stops at finite_life_years when one is given.
    """
    if not rates:
        return []
    max_years = 5
    if finite_life_years is not None:
        try:
            fly = int(finite_life_years)
            if fly < max_years:
                max_years = fly
        except (ValueError, TypeError):
            pass

    applied: List[float] = []
    for g in rates:
        if len(applied) >= max_years:
            break
        applied.append(float(g))

    tg = float(terminal_g) if terminal_g is not None else 0.0
    fy = int(fade_years) if fade_years is not None else 0

    if len(applied) < max_years and fy > 0 and rates:
        g_last = float(rates[-1])
        for i in range(1, fy + 1):
            if len(applied) >= max_years:
                break
            g_t = g_last + (tg - g_last) * (i / fy)
            applied.append(g_t)

    while len(applied) < max_years:
        applied.append(tg)

    return applied


def _five_and_fade(rates, terminal_g, fade_years):
    """The five annual growth rates of years 1-5 and the long-run fade in years, as the desk applies
    them. Fewer than five rates: years n+1..5 continue the linear fade from the last rate toward
    terminal_g (`applied_years_1_to_5`), and the fade left for years 6 on is shortened by the years
    already used. This is the old three-stage path unchanged: a fade of F years starting after year n
    is the same line whether it is read as years n+1..n+F or as years n+1..5 then 6..n+F."""
    n = len(rates)
    five = applied_years_1_to_5(rates, terminal_g, fade_years)
    left = max(0, int(fade_years) - (5 - n)) if n < 5 else int(fade_years)
    return five, left


def _json_ronic(x):
    """A return on new investment for a JSON result: the number, or "unlimited" for +inf."""
    return "unlimited" if x is not None and math.isinf(x) else x


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _long_run_inputs(long_run, oe5, ronic_t_in, r):
    """What the long run needs, from the pack's facts and the scenario's own inputs (brief B 4e).
    Returns (e5, margin_ratio, ronic0, ronic_t, stamps).

    E5 of the scenario = the reference's year-5 earnings plus the change in owner earnings the
    scenario makes (one for one). Without a reference in the facts (no consensus): owner earnings scaled by the
    base window's earnings before acquired-intangible amortization / owner earnings (`x_over_oe`, present when
    the base year's amortization is known: stamp `long_run_base_ratio_x`), else by its net income / owner earnings
    (`ni_over_oe`: `long_run_base_ratio_ni`), each when positive, else owner earnings themselves - labelled
    fallbacks (never a refusal). The margin factor needs the reference's m5 and the record's cycle.
    RONIC_0 = max(r, R_tc); RONIC_T is the scenario's terminal_ronic, else the facts', else r (a
    record the pack did not carry: growth earns only its cost)."""
    lr = long_run or {}
    stamps = []
    e5f, oe5f = lr.get("e5"), lr.get("oe5")
    margin_ratio = None
    if _is_num(e5f) and _is_num(oe5f):
        e5 = e5f + (oe5 - oe5f)
        m5, m_tc = lr.get("m5"), lr.get("m_tc")
        if lr.get("cycle") is True and _is_num(m5) and m5 > 0 and _is_num(m_tc):
            margin_ratio = m_tc / m5
    else:
        ratio_x, ratio_ni = lr.get("x_over_oe"), lr.get("ni_over_oe")
        if _is_num(ratio_x) and ratio_x > 0 and oe5 > 0:
            e5 = oe5 * ratio_x
            stamps.append("long_run_base_ratio_x")
        elif _is_num(ratio_ni) and ratio_ni > 0 and oe5 > 0:
            e5 = oe5 * ratio_ni
            stamps.append("long_run_base_ratio_ni")
        else:
            e5 = oe5
            stamps.append("long_run_on_owner_earnings")
    r_tc = lr.get("r_tc")
    ronic0 = r if not _is_num(r_tc) else max(r, r_tc)
    if _is_num(ronic_t_in):
        ronic_t = float(ronic_t_in)
    else:
        ronic_t = r
        stamps.append("terminal_ronic_at_cost_of_equity")
    return e5, margin_ratio, ronic0, ronic_t, stamps


def unbundled_dcf(
    base_cf: float,
    growth_rates: Optional[List[float]] = None,
    wacc: Optional[float] = None,
    terminal_g: Optional[float] = None,
    annuity_flow: float = 0.0,
    annuity_cap_rate: Optional[float] = None,
    net_debt: Optional[float] = None,
    shares_diluted: Optional[float] = None,
    fade_years: Optional[int] = None,
    explicit_growth: Optional[List[float]] = None,
    discount_rate: Optional[float] = None,
    valuation_frame: str = "equity",
    rate_type: Optional[str] = None,
    sector_multiple_band: Optional[Dict[str, Any]] = None,
    sbc_treatment: Optional[str] = None,
    sbc_dilution: Optional[float] = None,
    finite_life_years: Optional[int] = None,
    terminal_ronic: Optional[float] = None,
    long_run: Optional[Dict[str, Any]] = None,
    working_capital: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Revision 17 (brief B): a funded-growth DCF. Years 1-5 are the explicit cash flows (owner
    earnings less the pack's working-capital schedule, when there is one); from year 6 growth is
    paid for, at the return on new investment the company's record supports.

    - Years 1-5: base_cf grown by the five explicit rates (fewer than five: the fade continues, see
      `_five_and_fade`; more than five are refused: years 6 on follow terminal_g, terminal_ronic and
      fade_years). Each year's flow is base_cf's path less `working_capital[t]` ($B, five values).
    - Years 6..5+F (F = fade_years): growth fades linearly to terminal_g; earnings E_t start from the
      scenario's year-5 earnings (`long_run` facts, `_long_run_inputs`); cash flow_t = E_t (1 -
      g_{t+1} / max(r, RONIC_t)); the margin reverts toward the record's median when the record shows a
      cycle. The terminal is E_{N+1} (1 - g / max(r, RONIC_T)) / (r - g): the value-driver form of
      Gordon growth, the only terminal there is (the exit multiple left the desk in revision 17).
      A negative long-run value is floored at 0 (`long_run_floor`). `terminal_ronic` (a fraction) is
      the scenario's RONIC_T; None takes the cost of equity. The long-run arithmetic is
      consensus_reference.long_run_value, the copy the pack's reference uses.
    - Valued at the base fiscal year end and rolled forward by (1 + r)^(long_run["stub_months"]/12),
      so the desk and the reference agree on identical inputs (the pack's stub, no roll without one).
    - Optional finite_life_years (1-60): discrete flows for N years with no terminal value, on the
      owner-earnings path as before (no working capital, no roll): stamped finite_life_owner_earnings.
    - Valuation frame gating (equity refuses nonzero net_debt; firm requires net_debt and shares_diluted).
      The firm frame applies the same long run, an approximation (the return on new investment is measured on
      tangible invested capital before interest and applied to equity earnings: conservative for a levered company).
    - rate_engine.check_pairing wired with FrameMismatch structured refusal
    - SBC treatment single declaration; double deduction refused
    - Implied terminal EV/FCF multiple and reconciliation against sector_multiple_band
    """
    if finite_life_years is not None:
        # a whole-number float (15.0) or a digit string ("15") is that integer; anything else is refused
        if isinstance(finite_life_years, float) and finite_life_years.is_integer():
            finite_life_years = int(finite_life_years)
        elif isinstance(finite_life_years, str) and finite_life_years.strip().isdigit():
            finite_life_years = int(finite_life_years.strip())
        if type(finite_life_years) is bool or not isinstance(finite_life_years, int) or finite_life_years < 1 or finite_life_years > 60:
            return {
                "error": f"invalid finite_life_years: must be an integer between 1 and 60 (got {finite_life_years})",
                "missing": ["finite_life_years"],
                "validation_error": True,
            }

    v_err = _validate_required_dcf_inputs(
        terminal_g=terminal_g,
        shares_diluted=shares_diluted,
        fade_years=fade_years,
        sbc_treatment=sbc_treatment,
        sbc_dilution=sbc_dilution,
    )
    if v_err is not None:
        return v_err

    terminal_g = float(terminal_g)
    fade_years = int(fade_years)
    effective_shares = float(shares_diluted)
    sbc_norm = str(sbc_treatment).strip().lower()

    # Resolve rates
    rates = explicit_growth if explicit_growth is not None else growth_rates
    if not rates or len(rates) == 0:
        return {"error": "explicit_growth (or growth_rates) must be a non-empty list of growth rates",
                "validation_error": True}
    if finite_life_years is None and len(rates) > 5:
        return {"error": (f"explicit_growth holds the annual growth of years 1-5 (got {len(rates)} rates); "
                          f"years 6 onward follow terminal_g, terminal_ronic and fade_years"),
                "validation_error": True}

    # Resolve discount rate
    effective_rate = wacc if wacc is not None else discount_rate
    if effective_rate is None or effective_rate <= 0:
        return {"error": "wacc (or discount_rate) must be positive", "validation_error": True}
    rate = float(effective_rate)

    if base_cf <= 0:
        return {"error": "base_cf must be positive for standard DCF", "validation_error": True}

    # Valuation frame enforcement (D1)
    frame = str(valuation_frame or "equity").strip().lower()
    if frame == "equity":
        frame_enum = rate_engine.RS2_EQUITY_FRAME
        claim_enum = rate_engine.CLAIM_EQUITY
        if net_debt is not None and abs(float(net_debt)) > 1e-9:
            return {"error": f"valuation_frame 'equity' refuses nonzero net_debt ({net_debt}); cash flows are levered (FCFE) and directly yield equity value",
                    "validation_error": True}
        effective_net_debt = 0.0
        if rate_type is None:
            rate_type_norm = rate_engine.COST_OF_EQUITY
        else:
            rate_type_norm = str(rate_type).strip().upper()
    elif frame == "firm":
        frame_enum = rate_engine.FIRM_FCFF_FRAME
        claim_enum = rate_engine.CLAIM_FIRM
        if net_debt is None:
            return {"error": "valuation_frame 'firm' requires net_debt to bridge enterprise value to equity value",
                    "validation_error": True}
        if effective_shares <= 0:
            return {"error": "valuation_frame 'firm' requires positive shares_diluted", "validation_error": True}
        effective_net_debt = float(net_debt)
        if rate_type is None:
            rate_type_norm = rate_engine.TRUE_WACC
        else:
            rate_type_norm = str(rate_type).strip().upper()
    else:
        return {"error": f"unknown valuation_frame '{valuation_frame}'; allowed frames are 'equity' and 'firm'",
                "validation_error": True}

    # Rate pairing check
    try:
        rate_engine.check_pairing(frame_enum, claim_enum, rate_type_norm)
    except rate_engine.FrameMismatch as exc:
        return {"error": f"FrameMismatch: {str(exc)}", "validation_error": True}

    # SBC treatment (D1)
    if sbc_norm == "deducted_in_cf":
        if sbc_dilution is not None and float(sbc_dilution) != 0.0:
            return {"error": "double deduction refused: sbc_treatment is 'deducted_in_cf', so sbc_dilution may not also be passed",
                    "validation_error": True}
    elif sbc_norm in ("dilution", "add_back_dilution"):
        sd = float(sbc_dilution)
        if sd < 1.0:
            effective_shares = effective_shares * (1.0 + sd)
        elif sd >= 1_000_000:
            # a whole count of new shares; the shares above are in billions
            effective_shares = effective_shares + sd / 1e9
        else:
            return {"error": SBC_DILUTION_UNIT_MESSAGE, "validation_error": True}

    if finite_life_years is None and rate <= terminal_g:
        return {"error": f"wacc ({rate}) must be greater than terminal_g ({terminal_g})", "validation_error": True}

    if finite_life_years is not None:
        return _finite_life_dcf(base_cf, rates, rate, terminal_g, fade_years, finite_life_years,
                                annuity_flow, annuity_cap_rate, effective_net_debt, effective_shares,
                                frame, rate_type_norm, sbc_treatment, sbc_dilution)

    # ---- years 1-5: owner earnings less working capital --------------------------------------------
    five, fade_left = _five_and_fade(rates, terminal_g, fade_years)
    oe, cf = [], float(base_cf)
    for g in five:
        cf *= 1.0 + g
        oe.append(cf)
    wc = [float(x) for x in working_capital] if working_capital else None
    if wc is not None and len(wc) != 5:
        return {"error": "working_capital holds the five deductions of years 1-5", "validation_error": True}
    flows15 = [oe[t] - (wc[t] if wc else 0.0) for t in range(5)]

    # ---- years 6 on: growth paid for at the record's return ---------------------------------------
    e5, margin_ratio, ronic0, ronic_t, stamps = _long_run_inputs(long_run, oe[4], terminal_ronic, rate)
    lr = consensus_reference.long_run_value(e5, five[4], terminal_g, rate, ronic0, ronic_t,
                                            margin_ratio, fade_left)
    stub = (long_run or {}).get("stub_months")
    roll = (1.0 + rate) ** (float(stub) / 12.0) if _is_num(stub) and stub else 1.0
    if lr["floor"]:
        stamps.append("long_run_floor")
    if wc is not None:
        stamps.append("working_capital_deducted")

    n_years = lr["n_years"]
    yearly = flows15 + ([] if lr["floor"] else lr["flows"])
    pv_each = [roll * f / (1.0 + rate) ** (t + 1) for t, f in enumerate(yearly)]
    growth_applied = list(five) + ([] if lr["floor"] else lr["growth"])
    dcf_pv = sum(pv_each)
    tv_pv = 0.0 if lr["floor"] else roll * lr["tv_pv"]
    tv_nominal = 0.0 if lr["floor"] else lr["tv"]

    annuity_pv = 0.0
    if annuity_flow and float(annuity_flow) > 0:
        cap_rate = float(annuity_cap_rate) if (annuity_cap_rate and float(annuity_cap_rate) > 0) else max(0.04, rate - 0.01)
        annuity_pv = float(annuity_flow) / cap_rate

    ev = dcf_pv + tv_pv + annuity_pv
    eq = ev - effective_net_debt
    per_share_iv = eq / effective_shares
    final_cf = (flows15[-1] if lr["floor"] or not lr["flows"] else lr["flows"][-1])
    implied_multiple = (lr["tv"] / final_cf) if (not lr["floor"] and final_cf > 0) else None
    tv_share = (tv_pv / ev) if ev > 0 else 0.0

    gordon_in_band = None
    if sector_multiple_band and isinstance(sector_multiple_band, dict) and implied_multiple is not None:
        band_low = float(sector_multiple_band.get("low", float("-inf")))
        band_high = float(sector_multiple_band.get("high", float("inf")))
        gordon_in_band = (band_low <= implied_multiple <= band_high)

    res: Dict[str, Any] = {
        "per_share_iv": round(per_share_iv, 2),
        "per_share_iv_gordon": round(per_share_iv, 2),
        "enterprise_value": round(ev, 2),
        "equity_value": round(eq, 2),
        "dcf_pv": round(dcf_pv, 2),
        "terminal_value_nominal": round(tv_nominal, 2),
        "terminal_value_pv": round(tv_pv, 2),
        "terminal_method": (f"Gordon growth @ {terminal_g * 100:.1f}% on funded earnings, "
                            f"terminal return on new investment "
                            f"{'unlimited' if math.isinf(ronic_t) else f'{ronic_t * 100:.1f}%'}"),
        "terminal_share_of_value": round(tv_share, 4),
        "implied_terminal_ev_fcf_gordon": round(implied_multiple, 2) if implied_multiple is not None else None,
        "annuity_pv": round(annuity_pv, 2),
        "projected_cfs": [round(x, 4) for x in yearly],
        "pv_cfs": [round(x, 4) for x in pv_each],
        "growth_rates_applied": [round(g, 4) for g in growth_applied],
        "explicit_growth": [round(float(g), 4) for g in rates],
        "fade_years": fade_years,
        "terminal_g": terminal_g,
        "terminal_ronic": _json_ronic(ronic_t),
        "ronic_start": _json_ronic(ronic0),
        "net_debt": round(effective_net_debt, 2),
        "shares_diluted": round(effective_shares, 4),
        "valuation_frame": frame,
        "rate_type": rate_type_norm,
        "discount_rate_applied": round(rate, 4),
        "valued_at": "base fiscal year end, rolled forward" if roll != 1.0 else "base fiscal year end",
        "roll_forward_factor": round(roll, 6),
        "working_capital_deducted": [round(x, 4) for x in wc] if wc is not None else None,
        "long_run": {"years": n_years, "year5_earnings": round(e5, 4),
                     "margin_ratio": round(margin_ratio, 4) if margin_ratio is not None else None,
                     "floored": lr["floor"]},
        "stamps": stamps,
        "gordon_terminal": {
            "per_share_iv": round(per_share_iv, 2),
            "terminal_value_nominal": round(tv_nominal, 2),
            "terminal_value_pv": round(tv_pv, 2),
            "enterprise_value": round(ev, 2),
            "equity_value": round(eq, 2),
            "terminal_share_of_value": round(tv_share, 4),
            "implied_terminal_multiple": round(implied_multiple, 2) if implied_multiple is not None else None,
            "in_band": gordon_in_band,
        },
    }

    if sector_multiple_band is not None:
        # Phase 4 window fix: echo the band and a short label only; in_band used the full band above
        res["sector_multiple_band"] = (
            {k: (str(v)[:80] if k == "metric" else v) for k, v in sector_multiple_band.items()
             if k in ("low", "mid", "high", "metric")}
            if isinstance(sector_multiple_band, dict) else sector_multiple_band)
        res["multiple_in_band_gordon"] = gordon_in_band

    if sbc_treatment is not None:
        res["sbc_treatment"] = sbc_treatment
        res["sbc_dilution"] = sbc_dilution

    return res


def _finite_life_dcf(base_cf, rates, rate, terminal_g, fade_years, finite_life_years, annuity_flow,
                     annuity_cap_rate, effective_net_debt, effective_shares, frame, rate_type_norm,
                     sbc_treatment, sbc_dilution):
    """A finite cash-flow life: today's arithmetic, kept as it was (brief B 4g): the owner-earnings
    path for N years (explicit rates, then the linear fade, then terminal_g), no terminal value, no
    working-capital deduction, no roll-forward. Stamped finite_life_owner_earnings."""
    cf = float(base_cf)
    yearly_cfs = []
    pv_cfs = []
    growth_applied = []
    year = 0
    max_years = finite_life_years

    for g in rates:
        if year >= max_years:
            break
        year += 1
        g_val = float(g)
        cf = cf * (1.0 + g_val)
        pv = cf / ((1.0 + rate) ** year)
        yearly_cfs.append(round(cf, 4))
        pv_cfs.append(round(pv, 4))
        growth_applied.append(round(g_val, 4))

    g_last = float(rates[-1])
    if fade_years > 0:
        for i in range(1, fade_years + 1):
            if year >= max_years:
                break
            year += 1
            g_t = g_last + (terminal_g - g_last) * (i / fade_years)
            cf = cf * (1.0 + g_t)
            pv = cf / ((1.0 + rate) ** year)
            yearly_cfs.append(round(cf, 4))
            pv_cfs.append(round(pv, 4))
            growth_applied.append(round(g_t, 4))

    while year < max_years:
        year += 1
        g_t = terminal_g
        cf = cf * (1.0 + g_t)
        pv = cf / ((1.0 + rate) ** year)
        yearly_cfs.append(round(cf, 4))
        pv_cfs.append(round(pv, 4))
        growth_applied.append(round(g_t, 4))

    dcf_pv = sum(pv_cfs)
    annuity_pv = 0.0
    if annuity_flow and float(annuity_flow) > 0:
        cap_rate = float(annuity_cap_rate) if (annuity_cap_rate and float(annuity_cap_rate) > 0) else max(0.04, rate - 0.01)
        annuity_pv = float(annuity_flow) / cap_rate

    ev = dcf_pv + annuity_pv
    eq = ev - effective_net_debt
    per_share_iv = eq / effective_shares

    res: Dict[str, Any] = {
        "per_share_iv": round(per_share_iv, 2),
        "enterprise_value": round(ev, 2),
        "equity_value": round(eq, 2),
        "dcf_pv": round(dcf_pv, 2),
        "terminal_value_nominal": 0,
        "terminal_value_pv": 0,
        "terminal_method": f"finite life {finite_life_years} years",
        "terminal_share_of_value": 0,
        "finite_life_years": finite_life_years,
        "annuity_pv": round(annuity_pv, 2),
        "projected_cfs": yearly_cfs,
        "pv_cfs": pv_cfs,
        "growth_rates_applied": growth_applied,
        "explicit_growth": [round(float(g), 4) for g in rates],
        "fade_years": fade_years,
        "terminal_g": terminal_g,
        "net_debt": round(effective_net_debt, 2),
        "shares_diluted": round(effective_shares, 4),
        "valuation_frame": frame,
        "rate_type": rate_type_norm,
        "discount_rate_applied": round(rate, 4),
        "stamps": ["finite_life_owner_earnings"],
    }
    if sbc_treatment is not None:
        res["sbc_treatment"] = sbc_treatment
        res["sbc_dilution"] = sbc_dilution
    return res


def _neutral_reference_dcf(
    base_cf: float,
    g: float,
    coe_anchor: float,
    terminal_g_anchor: float,
    net_debt: float = 0.0,
    shares_diluted: float = 1.0,
) -> Tuple[float, float, float]:
    """Calculate DCF under the neutral reference structure:
    - Initial growth rate g
    - 10-year linear fade from g to terminal_g_anchor:
      year i (1..10): g_i = g + (terminal_g_anchor - g) * (i / 10.0)
    - Discount rate: coe_anchor
    - Terminal Gordon growth at terminal_g_anchor discounted to t=0
    Returns (per_share_iv, final_cf_10, implied_10y_cagr).
    """
    if coe_anchor <= terminal_g_anchor:
        return 0.0, 0.0, 0.0
    cf = float(base_cf)
    pv_total = 0.0
    for i in range(1, 11):
        g_i = g + (terminal_g_anchor - g) * (i / 10.0)
        cf *= (1.0 + g_i)
        pv_total += cf / ((1.0 + coe_anchor) ** i)
    cf_10 = cf
    cf_11 = cf_10 * (1.0 + terminal_g_anchor)
    tv_nominal = cf_11 / (coe_anchor - terminal_g_anchor)
    tv_pv = tv_nominal / ((1.0 + coe_anchor) ** 10)
    ev = pv_total + tv_pv
    eq = ev - net_debt
    per_share_iv = eq / shares_diluted
    cagr_10y = ((cf_10 / float(base_cf)) ** (1.0 / 10.0)) - 1.0
    return per_share_iv, cf_10, cagr_10y


def reverse_dcf_expectations_gap(
    current_price: float,
    shares_diluted: float,
    base_cf: float,
    wacc: float,
    terminal_g: Optional[float] = None,
    demonstrated_cagr_5y: Optional[float] = None,
    fade_years: int = 0,
    stage1_years: int = 5,
    net_debt: float = 0.0,
    valuation_frame: str = "equity",
    annuity_flow: float = 0.0,
    annuity_cap_rate: Optional[float] = None,
    coe_anchor: Optional[float] = None,
    terminal_g_anchor: Optional[float] = None,
    base_rate_table: Optional[Dict[str, Any]] = None,
    terminal_ronic: Optional[float] = None,
    long_run: Optional[Dict[str, Any]] = None,
    working_capital: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Solve for market-implied growth per Phase 4 Decision D2:
    (a) under caller's own structure (solve constant stage-1 growth equating IV to price, holding fade/terminal/rate;
        revision 17: and the terminal return on new investment, the pack's long-run facts and working-capital
        schedule the forward value uses)
    (b) under neutral reference structure (rate = coe_anchor, 10-year linear fade to terminal_g_anchor) returning
        implied 10-year CAGR, and percentile band when base_rate_table is passed.
    """
    if terminal_g is None:
        return {"error": "terminal_g is required for reverse DCF (the silent default was removed in Phase 4)"}
    terminal_g = float(terminal_g)

    if current_price <= 0 or shares_diluted <= 0 or base_cf <= 0 or wacc <= 0:
        return {"error": "Invalid inputs for reverse DCF (price, shares, base_cf, and wacc must be positive)"}
    if wacc <= terminal_g:
        return {"error": f"wacc ({wacc}) must be greater than terminal_g ({terminal_g})"}

    target_mcap = current_price * shares_diluted

    # Structure (a): Own Structure solver
    def _eval_own(g: float) -> Optional[float]:
        r = unbundled_dcf(
            base_cf=base_cf,
            explicit_growth=[g] * stage1_years,
            wacc=wacc,
            terminal_g=terminal_g,
            annuity_flow=annuity_flow,
            annuity_cap_rate=annuity_cap_rate,
            net_debt=net_debt,
            shares_diluted=shares_diluted,
            fade_years=fade_years,
            valuation_frame=valuation_frame,
            sbc_treatment="deducted_in_cf",
            terminal_ronic=terminal_ronic,
            long_run=long_run,
            working_capital=working_capital,
        )
        if r.get("error"):
            return None
        return r.get("per_share_iv")

    lo, hi = -0.90, 2.00
    for _ in range(5):
        val_lo = _eval_own(lo)
        if val_lo is not None and val_lo > current_price:
            lo -= 0.50
        else:
            break
    for _ in range(10):
        val_hi = _eval_own(hi)
        if val_hi is not None and val_hi < current_price:
            hi += 1.00
        else:
            break

    implied_g = None
    for _ in range(70):
        mid = (lo + hi) / 2.0
        val_mid = _eval_own(mid)
        if val_mid is None:
            break
        if abs(val_mid - current_price) < 0.0001 * current_price:
            implied_g = mid
            break
        if val_mid < current_price:
            lo = mid
        else:
            hi = mid
    if implied_g is None:
        implied_g = (lo + hi) / 2.0

    implied_g_pct = round(implied_g * 100.0, 2)
    res: Dict[str, Any] = {
        "current_price": round(current_price, 2),
        "shares_diluted": shares_diluted,
        "target_market_cap": round(target_mcap, 2),
        "assumed_wacc_pct": round(wacc * 100.0, 2),
        "terminal_growth_pct": round(terminal_g * 100.0, 2),
        "own_structure": {
            "implied_stage1_growth_pct": implied_g_pct,
            "solved_growth_pct": implied_g_pct,
            "stage1_years": stage1_years,
            "fade_years": fade_years,
            "terminal_g_pct": round(terminal_g * 100.0, 2),
            "discount_rate_pct": round(wacc * 100.0, 2),
            "valuation_frame": valuation_frame,
        },
        "implied_growth_next_5y_pct": implied_g_pct,
    }

    # Structure (b): Neutral Reference Structure solver
    if coe_anchor is not None and terminal_g_anchor is not None:
        c_anchor = float(coe_anchor)
        g_anchor = float(terminal_g_anchor)
        if c_anchor <= g_anchor:
            res["neutral_reference_structure"] = {
                "error": f"coe_anchor ({c_anchor}) must be greater than terminal_g_anchor ({g_anchor})"
            }
        else:
            def _eval_neutral(g: float) -> float:
                iv, _, _ = _neutral_reference_dcf(
                    base_cf=base_cf,
                    g=g,
                    coe_anchor=c_anchor,
                    terminal_g_anchor=g_anchor,
                    net_debt=net_debt if valuation_frame == "firm" else 0.0,
                    shares_diluted=shares_diluted,
                )
                return iv

            n_lo, n_hi = -0.90, 2.00
            for _ in range(5):
                if _eval_neutral(n_lo) > current_price:
                    n_lo -= 0.50
                else:
                    break
            for _ in range(10):
                if _eval_neutral(n_hi) < current_price:
                    n_hi += 1.00
                else:
                    break

            neutral_g = None
            for _ in range(70):
                mid = (n_lo + n_hi) / 2.0
                val_mid = _eval_neutral(mid)
                if abs(val_mid - current_price) < 0.0001 * current_price:
                    neutral_g = mid
                    break
                if val_mid < current_price:
                    n_lo = mid
                else:
                    n_hi = mid
            if neutral_g is None:
                neutral_g = (n_lo + n_hi) / 2.0

            _, final_cf_10, cagr_10y = _neutral_reference_dcf(
                base_cf=base_cf,
                g=neutral_g,
                coe_anchor=c_anchor,
                terminal_g_anchor=g_anchor,
                net_debt=net_debt if valuation_frame == "firm" else 0.0,
                shares_diluted=shares_diluted,
            )
            cagr_10y_pct = round(cagr_10y * 100.0, 2)
            neutral_res: Dict[str, Any] = {
                "coe_anchor_pct": round(c_anchor * 100.0, 2),
                "terminal_g_anchor_pct": round(g_anchor * 100.0, 2),
                "fade_years": 10,
                "solved_initial_growth_pct": round(neutral_g * 100.0, 2),
                "implied_10y_cagr_pct": cagr_10y_pct,
            }

            # Base rate table percentile ranking
            if base_rate_table and isinstance(base_rate_table, dict):
                def _norm_pct(v):
                    if v is None:
                        return None
                    vf = float(v)
                    return vf * 100.0 if 0.0 < vf <= 1.0 else vf

                p50 = _norm_pct(base_rate_table.get("p50"))
                p90 = _norm_pct(base_rate_table.get("p90"))

                if p50 is not None and p90 is not None:
                    if cagr_10y_pct < p50:
                        band = "< p50"
                        band_desc = f"Below median (< {p50:.1f}%)"
                    elif cagr_10y_pct < p90:
                        band = "p50 - p90"
                        band_desc = f"Between median ({p50:.1f}%) and 90th percentile ({p90:.1f}%)"
                    else:
                        band = "> p90"
                        band_desc = f"Above 90th percentile (> {p90:.1f}%)"

                    neutral_res["percentile_band"] = band
                    neutral_res["percentile_band_desc"] = band_desc
                    neutral_res["base_rate_table"] = base_rate_table
                    res["percentile_band"] = band

            res["neutral_reference_structure"] = neutral_res

    if demonstrated_cagr_5y is not None:
        gap = round(implied_g_pct - demonstrated_cagr_5y, 2)
        res["demonstrated_cagr_5y_pct"] = round(demonstrated_cagr_5y, 2)
        res["expectations_gap_pts"] = gap
        if gap > 5.0:
            res["assessment"] = f"HIGH EXPECTATIONS GAP: Market prices in {gap:+.1f}pts faster growth than 5y historical track record."
        elif gap < -5.0:
            res["assessment"] = f"VALUE GAP: Market prices in {-gap:.1f}pts slower growth than company has demonstrated."
        else:
            res["assessment"] = "IN-LINE: Market prices in growth consistent with demonstrated track record."

    return res


def continuous_multi_outcome_kelly(
    price: float,
    outcomes: List[Dict[str, Any]],
    position_cap_pct: float = 25.0,
) -> Dict[str, Any]:
    """Multi-outcome continuous log-wealth Kelly criterion optimization.
    
    outcomes: list of dicts with 'name', 'iv', 'prob'.
    Strict fiduciary rule: if expected return <= 0, Kelly is forced to 0.0%.
    """
    if price <= 0 or not outcomes:
        return {"error": "Invalid price or empty outcomes"}

    total_prob = sum(float(o.get("prob", 0)) for o in outcomes)
    if total_prob <= 0:
        return {"error": "Outcome probabilities must sum to > 0"}

    # Normalize probabilities
    norm_outcomes = []
    expected_iv = 0.0
    for o in outcomes:
        p = float(o.get("prob", 0)) / total_prob
        iv = float(o.get("iv", 0))
        expected_iv += p * iv
        payoff = (iv - price) / price
        norm_outcomes.append({"name": o.get("name", "Scenario"), "iv": iv, "prob": p, "payoff": payoff})

    expected_return = (expected_iv - price) / price
    expected_return_pct = round(expected_return * 100.0, 2)

    # STRICT FAIL-CLOSED FIDUCIARY GATE:
    # If the mathematical edge is zero or negative, do not allocate capital.
    if expected_return <= 0.0001:
        return {
            "expected_iv": round(expected_iv, 2),
            "expected_return_pct": expected_return_pct,
            "full_kelly_pct": 0.0,
            "half_kelly_pct": 0.0,
            "quarter_kelly_pct": 0.0,
            "max_drawdown_risk_pct": round(min(o["payoff"] for o in norm_outcomes) * 100.0, 2),
            "recommendation": "NO_ALLOCATION",
            "reason": "Expected return <= 0; no mathematical edge justifies capital deployment.",
        }

    # Optimize f in [0, max_f] to maximize E[log(1 + f * payoff)]
    min_payoff = min(o["payoff"] for o in norm_outcomes)
    max_f = 0.99
    if min_payoff < 0:
        # Avoid ruin: 1 + f * min_payoff > 0 => f < -1 / min_payoff
        max_f = min(0.99, (-0.95 / min_payoff))

    def expected_log_wealth(f: float) -> float:
        val = 0.0
        for o in norm_outcomes:
            wealth = 1.0 + f * o["payoff"]
            if wealth <= 0.00001:
                return -1e9
            val += o["prob"] * math.log(wealth)
        return val

    # Golden section search on [0, max_f]
    a, b = 0.0, max_f
    invphi = (math.sqrt(5) - 1) / 2
    invphi2 = (3 - math.sqrt(5)) / 2

    c = a + invphi2 * (b - a)
    d = a + invphi * (b - a)
    yc = expected_log_wealth(c)
    yd = expected_log_wealth(d)

    for _ in range(50):
        if yc > yd:
            b = d
            d = c
            yd = yc
            c = a + invphi2 * (b - a)
            yc = expected_log_wealth(c)
        else:
            a = c
            c = d
            yc = yd
            d = a + invphi * (b - a)
            yd = expected_log_wealth(d)

    optimal_f = (a + b) / 2.0
    full_kelly_pct = max(0.0, optimal_f * 100.0)
    quarter_kelly_pct = min(position_cap_pct, full_kelly_pct / 4.0)

    return {
        "expected_iv": round(expected_iv, 2),
        "expected_return_pct": expected_return_pct,
        "full_kelly_pct": round(full_kelly_pct, 2),
        "half_kelly_pct": round(full_kelly_pct / 2.0, 2),
        "quarter_kelly_pct": round(quarter_kelly_pct, 2),
        "max_drawdown_risk_pct": round(min_payoff * 100.0, 2),
        "recommendation": "ALLOCATE",
        "reason": f"Positive edge detected ({expected_return_pct:+.1f}% expected return). Sizing scaled to quarter-Kelly.",
    }


def calculate_payoff_skew(
    base_iv: float,
    bull_iv: float,
    bear_iv: float,
    price: float,
) -> Optional[float]:
    """Calculate upside/downside skew: (Bull_IV - Price) / (Price - Bear_IV)."""
    downside = price - bear_iv
    upside = bull_iv - price
    if downside <= 0:
        return 99.9 if upside > 0 else 0.0
    return round(upside / downside, 2)


def blend(legs: List[Dict[str, Any]], price: Optional[float] = None) -> Dict[str, Any]:
    """Calculate weighted blend of named desk valuation legs per Phase 4 Decision D6.

    Takes named legs (each a prior desk result id or per-share value with its source)
    and weights summing to 1. Returns blended per-share IV and echoes the legs.
    """
    if not legs or not isinstance(legs, list):
        return {"error": "blend requires a non-empty list of leg dicts", "validation_error": True}

    total_weight = 0.0
    parsed_legs = []

    for idx, leg in enumerate(legs):
        if not isinstance(leg, dict):
            return {"error": f"Leg {idx} must be a dictionary", "validation_error": True}
        name = str(leg.get("name") or leg.get("label") or f"Leg {idx+1}")

        if "weight" not in leg or leg["weight"] is None:
            return {"error": f"Leg '{name}' missing required 'weight'", "validation_error": True}
        try:
            w = float(leg["weight"])
        except (ValueError, TypeError):
            return {"error": f"Leg '{name}' has non-numeric weight '{leg['weight']}'", "validation_error": True}
        if w < 0:
            return {"error": f"Leg '{name}' has negative weight {w}", "validation_error": True}

        val = leg.get("iv")
        if val is None:
            val = leg.get("per_share_iv")
        if val is None:
            val = leg.get("value")
        if val is None:
            return {"error": f"Leg '{name}' missing intrinsic value ('iv', 'per_share_iv', or 'value')",
                    "validation_error": True}
        try:
            v = float(val)
        except (ValueError, TypeError):
            return {"error": f"Leg '{name}' has non-numeric intrinsic value '{val}'", "validation_error": True}

        source = leg.get("source") or leg.get("result_id") or "desk"
        total_weight += w

        leg_rec: Dict[str, Any] = {
            "name": name,
            "weight": w,
            "weight_pct": round(w * 100.0, 2),
            "per_share_iv": round(v, 2),
            "source": str(source),
        }
        if "result_id" in leg:
            leg_rec["result_id"] = str(leg["result_id"])
        if "id" in leg:
            leg_rec["id"] = str(leg["id"])
        parsed_legs.append(leg_rec)

    if abs(total_weight - 1.0) > 0.001:
        return {"error": f"Blend weights must sum to 1.0 (got {total_weight:.4f})", "validation_error": True}

    blended_iv = sum(l["weight"] * l["per_share_iv"] for l in parsed_legs)
    blended_iv_rounded = round(blended_iv, 2)

    res: Dict[str, Any] = {
        "mode": "blend",
        "blended_per_share_iv": blended_iv_rounded,
        "per_share_iv": blended_iv_rounded,
        "weights_sum": round(total_weight, 4),
        "legs": parsed_legs,
    }

    if price is not None and float(price) > 0:
        p = float(price)
        res["price"] = round(p, 2)
        res["mos_pct"] = round(((blended_iv_rounded - p) / p) * 100.0, 2)

    return res


def _role_of(name):
    """S3 3.5: a name containing "bull" is Bull, one containing "bear" is Bear, and every other
    scenario is Base. The desk's own rule (shared by the years35-cap logic below and the R1-R14
    reason checks)."""
    n = str(name or "").lower()
    return "bull" if "bull" in n else ("bear" if "bear" in n else "base")


def _to_b(v):
    """A dollar or share figure in billions; raw counts/dollars are converted. Financial_model_tool
    cannot import consensus_valuation's _num_b (that would cycle: consensus_valuation imports this
    module's _normalize_cash_flow_life), so this is the desk's own copy of the same conversion."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 1e9 if abs(x) > 1e6 else x


def _reason_given(v):
    """S3 3.3: a reason counts as not given when it is absent, empty, or reads "null" or "none"
    (case-insensitive, after stripping). The harness's existing test."""
    if v is None:
        return False
    s = str(v).strip()
    return s != "" and s.lower() not in ("null", "none")


def _effective_net_debt(explicit, frame, ctx_default_b):
    if explicit is not None:
        return float(explicit)
    if frame == "equity":
        return 0.0
    return ctx_default_b


def _effective_shares(explicit, top_shares, ctx_default_b):
    """The share count the DCF divides by, in billions (the unit of its dollar figures). An explicit
    count goes through `_to_b`, the conversion the reason checks use, so 83,371,000 and 0.083371 value
    identically; `top_shares` and the context default are already in billions. A count `_to_b` cannot
    read is returned as given, and the DCF's own input check refuses it."""
    if explicit is not None:
        explicit_b = _to_b(explicit)
        return explicit if explicit_b is None else explicit_b
    if top_shares is not None:
        return top_shares
    return ctx_default_b


def _need(reasons_needed, reason_name, given, triggered, why):
    """S3 3.5: record that `reason_name` is needed, the first time it is triggered without
    already being given. `reasons_needed` is an ordered dict of reason name -> why text."""
    if triggered and not given:
        reasons_needed.setdefault(reason_name, why)


def _refusal(missing, needs_reasons, order=None, share_unit_note=None, advice=None):
    """S3 3.7's refusal format. `share_unit_note`, when given, is appended to the detail.

    Revision 17 (brief C6): `advice` maps a reason name to the sentences the desk computed for that rule (the
    DEFAULTS Bear or Bull and the ends of its band, `_band_advice`); they follow the reason's `why` in the text
    and are kept once more in `_audit_advice` (the harness does not show `_audit` keys to the model). A refusal
    that carries advice never ends with the generic "change an input" clause, which sent the model walking a
    Bear down and up across two rules (UGI's preview sample): the advice already names the way out."""
    advice = advice or {}
    detail_bits = []
    if order is not None:
        detail_bits.append(f"the published values are not Bear <= Base <= Bull (Bear {order['bear']:.2f}, "
                           f"Base {order['base']:.2f}, Bull {order['bull']:.2f}); no reason overrides the "
                           f"order: change an input with dated evidence")
    if missing:
        detail_bits.append("missing " + ", ".join(missing))
    if needs_reasons:
        detail_bits.append("; ".join(f"{n['reason']} needed: {n['why']}" + (f". {advice[n['reason']]}" if advice.get(n["reason"]) else "")
                                     for n in needs_reasons))
    if share_unit_note:
        detail_bits.append(share_unit_note)
    detail = "; ".join(detail_bits)
    advised = any(advice.get(n["reason"]) for n in needs_reasons)
    msg = ("Not accepted as a desk run; it does not use one of your desk runs. " + detail +
           ("" if detail.endswith(".") else ".") +
           (" Call again with the same inputs and these reasons." if advised else
            " Call again with the same inputs and these reasons, or change an input with dated evidence."))
    out: Dict[str, Any] = {
        "error": msg,
        "validation_error": True,
        "missing": list(missing),
        "needs_reasons": list(needs_reasons),
    }
    if order is not None:
        out["order"] = order
    if advice:
        out["_audit_advice"] = dict(advice)
    return out


def _levels_hold(base_b, five, levels):
    """Brief B 4c: (g1, g2, year-2 flow, gap) that hold a Base's years 1-2 at the fiscal-year levels
    when its year-2 flow is more than LEVELS_HOLD_TOL from levels.year2, else None. g1 = year1 / base_cf
    - 1 and g2 = year2 / year1 - 1. None when a level or the base is missing, or year 1 is exactly 0
    (no growth rate reaches year 2 from it)."""
    y1, y2 = (levels or {}).get("year1"), (levels or {}).get("year2")
    if not (_is_num(y1) and _is_num(y2) and _is_num(base_b) and base_b > 0 and y2 != 0 and y1 != 0):
        return None
    flow2 = base_b * (1.0 + five[0]) * (1.0 + five[1])
    gap = abs(flow2 - y2) / abs(y2)
    if gap <= consensus_reference.LEVELS_HOLD_TOL + 1e-6:
        return None
    return y1 / base_b - 1.0, y2 / y1 - 1.0, flow2, gap


def _pct_txt(x):
    return "unlimited" if x is not None and math.isinf(x) else f"{x * 100:.2f}%"


def execute_financial_model(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Master tool dispatcher called by Qwen or automation harness.
    Supports single DCF, batch multi-scenario DCF, or blend mode in a single round trip.

    S3 3.2-3.7: `context` (the harness's desk_context) supplies today's price, the pack's share
    default, the anchors, the base-rate table and the reverse-DCF inputs; the model supplies its
    decisions and, where they depart from a default, the named reason. A call the desk cannot use,
    or whose published legs fail a reason check, is refused (3.4, 3.5) and does not use a desk run.

    Revision 17 (brief B 4): the context also carries terminal_ronic, long_run, working_capital,
    cash_basis_b and levels; the desk holds the Base's years 1-2 at the fiscal-year levels when its
    year 2 is more than 5% away and no guidance_deviation_reason is given (`years12_held_by_desk`),
    deducts the pack's working-capital schedule in years 1-5 (unless the base already carries it,
    `wc_in_base`), and values the long run with the pack's record.
    """
    ctx = context or {}
    price = ctx.get("price")

    scenarios = params.get("scenarios") or []
    base_cf = params.get("base_cf")

    # ---- 0. Blend mode: unchecked (3.5); price still comes from the harness ------------------
    if params.get("mode") == "blend" or ("legs" in params and not scenarios and not base_cf):
        legs = params.get("legs")
        if not legs:
            return {"error": "mode 'blend' requires non-empty 'legs' list", "validation_error": True}
        blend_res = blend(legs=legs, price=price if price and price > 0 else None)
        if blend_res.get("error"):
            return blend_res
        result: Dict[str, Any] = {"price": price}
        result.update(blend_res)
        return result

    result = {"price": price}
    if params.get("price") is not None:
        result["price_note"] = f"today's price is supplied by the harness: {price}"

    if "legs" in params and params["legs"]:
        blend_res = blend(legs=params["legs"], price=price if price and price > 0 else None)
        if not blend_res.get("error"):
            result["blend"] = blend_res

    # ---- 3.4 Refusals before computing --------------------------------------------------------
    missing: List[str] = []
    if price is None:
        missing.append("price (harness)")

    cfl_raw = params.get("cash_flow_life")
    cfl_norm = _normalize_cash_flow_life(cfl_raw) if cfl_raw is not None else None
    cfl_valid = (cfl_norm == "perpetual") or (
        isinstance(cfl_norm, int) and type(cfl_norm) is not bool and 1 <= cfl_norm <= 60)
    if not cfl_valid:                                                                     # V1
        missing.append("cash_flow_life")
    if not _reason_given(params.get("cash_flow_life_reason")):                            # V2
        missing.append("cash_flow_life_reason")

    # V3: finite_life_years leaves the schema; cash_flow_life applies to every scenario instead.
    if params.get("finite_life_years") is not None:
        missing.append("finite_life_years (use cash_flow_life, which applies to every scenario)")
    for sc in scenarios:
        if isinstance(sc, dict) and sc.get("finite_life_years") is not None:
            missing.append(f"finite_life_years in {sc.get('name') or 'scenario'} "
                           f"(use cash_flow_life, which applies to every scenario)")

    # V4 (revision 17): the exit multiple and the terminal leg left the desk; a call that sends
    # either is refused by name, never silently ignored
    for holder, label in [(params, "")] + [(sc, f" in {sc.get('name') or 'scenario'}")
                                           for sc in scenarios if isinstance(sc, dict)]:
        for gone in ("terminal_exit_multiple", "terminal_leg"):
            if holder.get(gone) is not None:
                missing.append(f"{gone}{label} (removed in revision 17: the terminal is always the funded "
                               f"growth value, set with terminal_g and terminal_ronic)")
        # a terminal_ronic the desk cannot read is refused, never replaced by the default
        tr = holder.get("terminal_ronic")
        if tr is not None and (isinstance(tr, bool) or not isinstance(tr, (int, float)) or math.isnan(tr)):
            missing.append(f"terminal_ronic{label} (a number, for example 0.12)")

    # V5: every scenario needs prob >= 0; Base+Bull+Bear sum to 0.99-1.01 when all three are present
    if scenarios:
        for sc in scenarios:
            nm = sc.get("name") if isinstance(sc, dict) else "scenario"
            p = sc.get("prob") if isinstance(sc, dict) else None
            if not isinstance(p, (int, float)) or type(p) is bool or p < 0:
                missing.append(f"prob in {nm}")
        # exactly one Base, one Bull and one Bear: with two, the sum check below never ran and Kelly
        # sized outcomes whose probabilities summed to 0.55
        names_by_role: Dict[str, List[str]] = {"base": [], "bull": [], "bear": []}
        for sc in scenarios:
            if isinstance(sc, dict):
                names_by_role[_role_of(sc.get("name"))].append(str(sc.get("name") or "Scenario"))
        for role, names in names_by_role.items():
            if not names:
                missing.append(f"scenarios: no {role.capitalize()} entry (send exactly three, one each with "
                               f"role Base, Bull and Bear)")
            elif len(names) > 1:
                missing.append(f"scenarios: {len(names)} {role.capitalize()} entries ({', '.join(names)}); "
                               f"send exactly three, one each with role Base, Bull and Bear (a name with "
                               f"\"bull\" is Bull, one with \"bear\" is Bear, any other name is Base)")
        # every entry needs what the desk values it with: an entry without them is skipped below, so a
        # three-entry call could still size fewer than three roles
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            growth = sc.get("explicit_growth") if sc.get("explicit_growth") is not None else sc.get("growth_rates")
            lacks = [f for f, absent in (("base_cf", sc.get("base_cf") is None),
                                         ("explicit_growth", not growth),
                                         ("wacc", sc.get("wacc") is None and sc.get("discount_rate") is None))
                     if absent]
            if lacks:
                missing.append(f"scenarios: the {_role_of(sc.get('name')).capitalize()} entry "
                               f"({sc.get('name') or 'Scenario'}) lacks {', '.join(lacks)} (each entry needs "
                               f"base_cf, explicit_growth and wacc)")
        roles_present = {_role_of(sc.get("name")) for sc in scenarios if isinstance(sc, dict)}
        if {"base", "bull", "bear"} <= roles_present:
            probs = [sc.get("prob") for sc in scenarios if isinstance(sc, dict)]
            if all(isinstance(p, (int, float)) and type(p) is not bool for p in probs):
                total = sum(float(p) for p in probs)
                if not (0.99 <= total <= 1.01):
                    missing.append("scenarios[].prob (Base, Bull and Bear must sum to 0.99-1.01)")

    if missing:
        return _refusal(missing=missing, needs_reasons=[])

    # ---- Context defaults used while computing -------------------------------------------------
    ctx_shares_default_b = ctx.get("shares_default_b")
    ctx_net_debt_default_b = ctx.get("net_debt_default_b")

    val_frame = params.get("valuation_frame", "equity")
    rate_type = params.get("rate_type")
    fade_years = params.get("fade_years")
    sbc_treatment = params.get("sbc_treatment")
    sbc_dilution = params.get("sbc_dilution")

    top_net_debt_explicit = params.get("net_debt")
    top_net_debt = _effective_net_debt(top_net_debt_explicit, val_frame, ctx_net_debt_default_b)
    top_shares = _effective_shares(params.get("shares_diluted"), None, ctx_shares_default_b)
    desk_finite_life_years = cfl_norm if isinstance(cfl_norm, int) else None

    raw_cap = ctx.get("years35_cap")
    cap = float(raw_cap) if raw_cap is not None else None
    reason = params.get("guidance_deviation_reason") if _reason_given(params.get("guidance_deviation_reason")) else ""

    long_run_ctx = ctx.get("long_run")
    wc_ctx = ctx.get("working_capital")
    cash_basis_b = ctx.get("cash_basis_b")
    levels_ctx = ctx.get("levels") or {}
    ronic_default = ctx.get("terminal_ronic")

    capped_dcfs: List[Dict[str, Any]] = []
    held_dcfs: List[Dict[str, Any]] = []
    kept_names: List[str] = []
    scenario_dcfs = []
    compute_errors: List[str] = []
    base_inputs: Dict[str, Any] = {}     # the Base's effective inputs, for the reverse DCF
    base_final: Dict[str, Any] = {}      # Base name -> (explicit growth, terminal_g, fade_years) as valued, for C6
    value_args: Dict[str, Any] = {}      # scenario name -> the arguments its value was computed with, for C6

    def _value(name, cf_in, gr_in, wacc_in, tg_in, shares_in, fade_in, sbc_in, sbc_dil_in, frame_in,
               net_debt_in, rate_type_in, annuity_in, annuity_cap_in, ronic_in):
        """One scenario's value, with the Base-only years-3-5 cap and years-1-2 hold. Returns the dcf
        dict, or None after recording a compute error."""
        base_b = _to_b(cf_in)
        wc_in_base = (wc_ctx is not None and _is_num(cash_basis_b) and cash_basis_b != 0 and base_b is not None
                      and abs(base_b - cash_basis_b) / abs(cash_basis_b) <= 0.020001)
        wc_use = None if (wc_in_base or not wc_ctx) else wc_ctx

        def run(growth, fade):
            res = unbundled_dcf(
                base_cf=float(cf_in),
                growth_rates=None,
                explicit_growth=[float(g) for g in growth],
                wacc=float(wacc_in),
                terminal_g=float(tg_in) if tg_in is not None else None,
                annuity_flow=annuity_in,
                annuity_cap_rate=annuity_cap_in,
                net_debt=net_debt_in,
                shares_diluted=shares_in,
                fade_years=fade,
                valuation_frame=frame_in,
                rate_type=rate_type_in,
                sbc_treatment=sbc_in,
                sbc_dilution=sbc_dil_in,
                finite_life_years=desk_finite_life_years,
                terminal_ronic=ronic_in,
                long_run=long_run_ctx,
                working_capital=wc_use,
            )
            if not res.get("error"):
                if wc_in_base:
                    res.setdefault("stamps", []).append("wc_in_base")
            return res

        dcf_res = run(gr_in, fade_in)
        if dcf_res.get("error"):
            compute_errors.append(f"{name}: {dcf_res['error']}")
            return None

        if _role_of(name) != "base":
            return dcf_res
        requested_iv = dcf_res["per_share_iv"]
        growth_now, fade_now = list(gr_in), fade_in

        # years 3-5 above next-FY consensus revenue growth (S3 3.5, review J6)
        if cap is not None:
            app_years = applied_years_1_to_5(gr_in, tg_in, fade_in, desk_finite_life_years)
            y35 = app_years[2:]
            if any(g > cap + 1e-12 for g in y35):
                if reason:
                    kept_names.append(name)
                else:
                    n = len(gr_in)
                    new_fade = max(0, int(fade_in) - (5 - n)) if n < 5 and fade_in is not None else (int(fade_in) if fade_in is not None else None)
                    new_growth = app_years[:2] + [min(g, cap) for g in y35] + [float(g) for g in gr_in[5:]]
                    new_res = run(new_growth, new_fade)
                    if new_res.get("error"):
                        compute_errors.append(f"{name}: {new_res['error']}")
                        return None
                    new_res["years35_capped"] = True
                    capped_dcfs.append({
                        "name": name,
                        "requested_years35": [round(g, 4) for g in y35],
                        "applied_years35": [round(min(g, cap), 4) for g in y35],
                        "requested_per_share_iv": round(dcf_res["per_share_iv"], 2),
                        "applied_per_share_iv": round(new_res["per_share_iv"], 2),
                        "requested_fade_years": int(fade_in) if fade_in is not None else None,
                        "applied_fade_years": new_fade,
                    })
                    dcf_res, growth_now, fade_now = new_res, new_growth, new_fade

        # years 1-2 held at the fiscal-year levels (brief B 4c; replaces the refusal for the Base)
        if not reason and levels_ctx and base_b is not None:
            five_now, fade_left = _five_and_fade(growth_now, tg_in, fade_now)
            hold = _levels_hold(base_b, five_now, levels_ctx)
            if hold is not None:
                g1, g2, flow2, gap = hold
                held_growth = [g1, g2] + list(five_now[2:])
                held_res = run(held_growth, fade_left)
                if held_res.get("error"):
                    compute_errors.append(f"{name}: {held_res['error']}")
                    return None
                held_res["years12_held"] = True
                held_res.setdefault("stamps", []).append("years12_held_by_desk")
                held_dcfs.append({
                    "name": name,
                    "requested_year2_flow": round(flow2, 4),
                    "requested_gap_pct": round(gap * 100.0, 1),
                    "held_year1": levels_ctx.get("year1"),
                    "held_year2": levels_ctx.get("year2"),
                    "held_growth_years12": [round(g1, 4), round(g2, 4)],
                    "requested_per_share_iv": round(requested_iv, 2),
                    "applied_per_share_iv": round(held_res["per_share_iv"], 2),
                })
                growth_now, fade_now = held_growth, fade_left
                dcf_res = held_res
        base_final[name] = (list(growth_now), tg_in, fade_now)
        return dcf_res

    # ---- 1. Batch scenario DCF execution -------------------------------------------------------
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sc_name = str(sc.get("name") or "Scenario")
        s_cf = sc.get("base_cf")
        s_gr = sc.get("explicit_growth") if sc.get("explicit_growth") is not None else sc.get("growth_rates")
        s_wacc = sc.get("wacc") if sc.get("wacc") is not None else sc.get("discount_rate")
        s_term_g = sc.get("terminal_g") if sc.get("terminal_g") is not None else params.get("terminal_g")
        if s_cf is None or not s_gr or s_wacc is None:
            continue
        s_shares = _effective_shares(sc.get("shares_diluted"), top_shares, ctx_shares_default_b)
        s_fade = sc.get("fade_years") if sc.get("fade_years") is not None else fade_years
        s_sbc = sc.get("sbc_treatment") if sc.get("sbc_treatment") is not None else sbc_treatment
        s_sbc_dil = sc.get("sbc_dilution") if sc.get("sbc_dilution") is not None else sbc_dilution
        sc_frame = sc.get("valuation_frame", val_frame)
        # a scenario's own net_debt, else the top level's explicit net_debt, else the frame default
        sc_net_debt_explicit = sc.get("net_debt") if sc.get("net_debt") is not None else top_net_debt_explicit
        sc_net_debt = _effective_net_debt(sc_net_debt_explicit, sc_frame, ctx_net_debt_default_b)
        s_ronic = (sc.get("terminal_ronic") if sc.get("terminal_ronic") is not None
                   else params.get("terminal_ronic") if params.get("terminal_ronic") is not None
                   else ronic_default)
        s_annuity = float(sc.get("annuity_flow", params.get("annuity_flow", 0.0)))
        s_annuity_cap = (float(sc["annuity_cap_rate"]) if sc.get("annuity_cap_rate")
                         else (float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None))

        value_args[sc_name] = {"cf": s_cf, "wacc": s_wacc, "tg": s_term_g, "shares": s_shares, "sbc": s_sbc,
                               "sbc_dil": s_sbc_dil, "frame": sc_frame, "net_debt": sc_net_debt,
                               "rate_type": sc.get("rate_type", rate_type), "annuity": s_annuity,
                               "annuity_cap": s_annuity_cap}
        dcf_res = _value(sc_name, s_cf, [float(g) for g in s_gr], s_wacc, s_term_g, s_shares, s_fade, s_sbc,
                         s_sbc_dil, sc_frame, sc_net_debt, sc.get("rate_type", rate_type), s_annuity,
                         s_annuity_cap, s_ronic)
        if dcf_res is None:
            continue
        if _role_of(sc_name) == "base":
            base_inputs = {"ronic": s_ronic, "cf": s_cf, "wc_in_base": "wc_in_base" in dcf_res.get("stamps", [])}
        sc["iv"] = dcf_res["per_share_iv"]
        sc["dcf_details"] = dcf_res
        scenario_dcfs.append({"name": sc.get("name"), "dcf": dcf_res})

    if scenario_dcfs:
        result["scenario_dcfs"] = scenario_dcfs

    # ---- 2. Single (top-level) DCF projection --------------------------------------------------
    growth_rates = params.get("explicit_growth") if params.get("explicit_growth") is not None else params.get("growth_rates")
    wacc = params.get("wacc") if params.get("wacc") is not None else params.get("discount_rate")
    dcf_single = None
    if base_cf is not None and growth_rates and wacc is not None:
        top_ronic = params.get("terminal_ronic") if params.get("terminal_ronic") is not None else ronic_default
        top_annuity = float(params.get("annuity_flow", 0.0))
        top_annuity_cap = float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None
        dcf_single = _value("top-level", base_cf, [float(g) for g in growth_rates], wacc, params.get("terminal_g"),
                            top_shares, fade_years, sbc_treatment, sbc_dilution, val_frame, top_net_debt,
                            rate_type, top_annuity, top_annuity_cap, top_ronic)
        if dcf_single is not None:
            if not base_inputs:
                base_inputs = {"ronic": top_ronic, "cf": base_cf,
                               "wc_in_base": "wc_in_base" in dcf_single.get("stamps", [])}
            result["dcf_model"] = dcf_single

    if compute_errors:
        return _refusal(missing=compute_errors, needs_reasons=[])

    if cap is not None:
        if reason:
            if kept_names:
                result["years35_cap"] = {"cap": cap, "reason": reason, "kept": kept_names}
        else:
            if capped_dcfs:
                result["years35_cap"] = {"cap": cap, "reason": None, "dcfs": capped_dcfs}
    if held_dcfs:
        result["years12_held"] = {"levels": {"year1": levels_ctx.get("year1"), "year2": levels_ctx.get("year2")},
                                  "reason_field": "guidance_deviation_reason", "dcfs": held_dcfs}

    # ---- 3.5 Reason checks, on the published legs ----------------------------------------------
    checked: List[Dict[str, Any]] = []
    if scenario_dcfs:
        for item in scenario_dcfs:
            nm = item["name"]
            sc = next((s for s in scenarios if isinstance(s, dict) and s.get("name") == nm), {})
            checked.append({"role": _role_of(nm), "name": nm, "sc": sc, "dcf": item["dcf"],
                            "shares_b": _to_b(_effective_shares(sc.get("shares_diluted"), top_shares,
                                                                ctx_shares_default_b))})
    elif dcf_single is not None:
        checked.append({"role": "base", "name": "top-level", "sc": params, "dcf": dcf_single,
                        "shares_b": _to_b(top_shares)})

    if checked:
        base_entry = next((e for e in checked if e["role"] == "base"), None)
        bull_entry = next((e for e in checked if e["role"] == "bull"), None)
        bear_entry = next((e for e in checked if e["role"] == "bear"), None)

        reasons_needed: Dict[str, str] = {}
        order_violation = None
        share_unit_note = None

        # R1 + R1b
        shares_reason_given = _reason_given(params.get("shares_reason"))
        if ctx_shares_default_b:
            for e in checked:
                applied = e.get("shares_b")
                if applied is not None:
                    # the harness's rule (shares_off_pack_without_reason): ratio rounded to 3 decimals,
                    # |ratio - 1| more than 0.01. The dcf echo is rounded to 4 decimals of a billion, which
                    # misstates a small count by more than 1%, so the unrounded input count is used.
                    ratio = round(applied / ctx_shares_default_b, 3)
                    if abs(ratio - 1) > 0.010001:          # "more than 1%": exactly 1% passes
                        _need(reasons_needed, "shares_reason", shares_reason_given, True,
                              f"{e['name']}'s share count is {abs(ratio - 1) * 100:.1f}% from the default "
                              f"count {ctx_shares_default_b:.6f}B")
        if ctx.get("shares_warning"):
            _need(reasons_needed, "shares_reason", shares_reason_given, True,
                  f"the pack carries a shares_warning: {ctx['shares_warning']}")

        # R2 + R3 (Base, base_cf_reason). Revision 17: the pack's BASE WINDOW CHECK no longer needs a
        # reason (the window does not change the Base's arithmetic; the line stays as information).
        base_cf_reason_given = _reason_given(params.get("base_cf_reason"))
        oe_default = ctx.get("owner_earnings_default_b")
        if base_entry is not None:
            base_cf_val = _to_b(base_entry["sc"].get("base_cf"))
            if oe_default is None:
                _need(reasons_needed, "base_cf_reason", base_cf_reason_given, True,
                      "the DEFAULTS owner earnings (owner_earnings_default_b) is not available")
            elif base_cf_val is not None:
                diff = abs(base_cf_val - oe_default) / abs(oe_default) if oe_default else None
                if diff is not None and diff > 0.020001:
                    _need(reasons_needed, "base_cf_reason", base_cf_reason_given, True,
                          f"Base base_cf {base_cf_val:.4f}B is {diff * 100:.1f}% from the DEFAULTS "
                          f"owner earnings {oe_default:.4f}B")

        # R4 (Base rate vs COE ANCHOR)
        coe_adj_reason_given = _reason_given(params.get("coe_adjustment_reason"))
        coe_anchor = ctx.get("coe_anchor")
        if base_entry is not None and coe_anchor is not None:
            applied_rate = base_entry["dcf"].get("discount_rate_applied")
            if applied_rate is not None:
                gap = abs(applied_rate - coe_anchor)
                if gap > 0.015001:
                    _need(reasons_needed, "coe_adjustment_reason", coe_adj_reason_given, True,
                          f"Base rate {applied_rate * 100:.2f}% is {gap * 100:.2f} points from "
                          f"the COE ANCHOR {coe_anchor * 100:.2f}%")

        # R5 + R6 (Base terminal_g and terminal_ronic vs their defaults)
        terminal_reason_given = _reason_given(params.get("terminal_reason"))
        tg_default = ctx.get("terminal_g_default")
        if base_entry is not None and tg_default is not None:
            applied_tg = base_entry["dcf"].get("terminal_g")
            if applied_tg is not None:
                gap_bp = round((float(applied_tg) - tg_default) * 10000)
                if abs(gap_bp) > 50:
                    _need(reasons_needed, "terminal_reason", terminal_reason_given, True,
                          f"Base terminal_g {float(applied_tg) * 100:.2f}% is {abs(gap_bp) / 100:.2f} points "
                          f"from terminal_g_default {tg_default * 100:.2f}%")
        if base_entry is not None and _is_num(ronic_default):
            base_sc = base_entry["sc"]
            base_ronic = (base_sc.get("terminal_ronic") if base_sc.get("terminal_ronic") is not None
                          else params.get("terminal_ronic"))
            if _is_num(base_ronic):
                gap_pts = abs(float(base_ronic) - ronic_default)
                if gap_pts > 0.020001:
                    gap_txt = "infinitely" if math.isinf(gap_pts) else f"{gap_pts * 100:.2f} points"
                    _need(reasons_needed, "terminal_reason", terminal_reason_given, True,
                          f"Base terminal_ronic {_pct_txt(float(base_ronic))} is {gap_txt} from the DEFAULTS "
                          f"terminal_ronic {_pct_txt(ronic_default)}")

        # R7 + R8 (firm frame: interest_addback, wacc_reason)
        any_firm = any(e["dcf"].get("valuation_frame") == "firm" for e in checked)
        if any_firm:
            iab = _to_b(params.get("interest_addback")) if params.get("interest_addback") is not None else None
            if iab is None or iab <= 0:
                _need(reasons_needed, "interest_addback", False, True,
                      "the firm frame needs a positive interest_addback")
            if not _reason_given(params.get("wacc_reason")):
                _need(reasons_needed, "wacc_reason", False, True, "the firm frame needs wacc_reason")

        # R9 (firm frame, net_debt off default)
        net_debt_default = ctx.get("net_debt_default_b")
        if any_firm and net_debt_default is not None:
            explicit_nd = params.get("net_debt")
            if explicit_nd is None:
                explicit_nd = next((sc.get("net_debt") for sc in scenarios
                                    if isinstance(sc, dict) and sc.get("net_debt") is not None), None)
            if explicit_nd is not None:
                nd = float(explicit_nd)
                tol = max(0.1, 0.05 * abs(net_debt_default))
                if abs(nd - net_debt_default) > tol:
                    _need(reasons_needed, "net_debt_reason", _reason_given(params.get("net_debt_reason")), True,
                          f"net_debt {nd:.4f}B is more than {tol:.4f}B from net_debt_default_b "
                          f"{net_debt_default:.4f}B")

        # R10 (Base value vs the fiscal-year reference). Revision 17: the Base's years 1-2 are held at
        # the levels by the desk (above), so only the value check remains, against the fiscal-year
        # reference alone (the window choice is gone).
        guidance_reason_given = _reason_given(params.get("guidance_deviation_reason"))
        if base_entry is not None:
            ref_val = ctx.get("consensus_implied_value")
            base_iv = base_entry["dcf"].get("per_share_iv")
            if ref_val and base_iv is not None:
                ratio = base_iv / ref_val
                if not (consensus_reference.FAR_LOW <= ratio <= consensus_reference.FAR_HIGH):
                    _need(reasons_needed, "guidance_deviation_reason", guidance_reason_given, True,
                          f"the Base value is {ratio:.2f}x the reference (outside "
                          f"{consensus_reference.FAR_LOW}-{consensus_reference.FAR_HIGH})")
            # A Base value under 0.01x or over 100x the reference is not a valuation difference; the usual
            # cause is a share count in the wrong unit, so a refusal says so. The reference is the one above,
            # else today's price; a negative value is not a unit error. A refusal carries no per-share value
            # (S3 3.5, except the order refusal and, from revision 17, the R13/R14 advice), so the note gives the
            # ratio and the pack's share count only.
            unit_ref = ref_val if ref_val is not None and ref_val > 0 else price
            if unit_ref is not None and unit_ref > 0 and base_iv is not None and base_iv >= 0:
                unit_ratio = base_iv / unit_ref
                if unit_ratio < 0.01 or unit_ratio > 100:
                    default_bit = (f" (the pack's default is {ctx_shares_default_b * 1e9:,.0f}, or "
                                   f"{ctx_shares_default_b:.6f} in billions)" if ctx_shares_default_b else "")
                    share_unit_note = (f"the Base value is {unit_ratio:.4f}x the reference, too far to be a "
                                       f"valuation difference; the likely cause is the share unit: shares_diluted "
                                       f"is a whole share count or that count in billions, never thousands or "
                                       f"millions{default_bit}")

        # R11 (Bull/Bear year-2 cash flow vs the DEFAULTS bull2/bear2 level)
        scenario_dev_given = _reason_given(params.get("scenario_deviation_reason"))
        levels = ctx.get("levels") or {}
        for role, e in (("bull", bull_entry), ("bear", bear_entry)):
            if e is None:
                continue
            lvl = levels.get(f"{role}2")
            if not lvl:
                continue
            cf_val = _to_b(e["sc"].get("base_cf"))
            g_path = e["dcf"].get("growth_rates_applied") or []
            if cf_val is not None and len(g_path) >= 2:
                y2_flow = cf_val * (1 + g_path[0]) * (1 + g_path[1])
                gap = abs(y2_flow - lvl) / abs(lvl)
                if gap > consensus_reference.LEVEL_TOL:
                    _need(reasons_needed, "scenario_deviation_reason", scenario_dev_given, True,
                          f"{role.capitalize()} year-2 cash flow {y2_flow:.4f}B is {gap * 100:.1f}% "
                          f"from the DEFAULTS {role}2 level {lvl:.4f}B")

        # R12 (scenario order: Bear <= Base <= Bull)
        if base_entry and bull_entry and bear_entry:
            bv = base_entry["dcf"].get("per_share_iv")
            bu = bull_entry["dcf"].get("per_share_iv")
            be = bear_entry["dcf"].get("per_share_iv")
            if None not in (bv, bu, be) and not (be <= bv <= bu):
                order_violation = {"bear": be, "base": bv, "bull": bu}

        # R13 + R14 (Bull below price / Bear above price)
        if bull_entry is not None and price is not None:
            biv = bull_entry["dcf"].get("per_share_iv")
            if biv is not None and biv < price:
                _need(reasons_needed, "bull_below_price_reason",
                      _reason_given(params.get("bull_below_price_reason")), True,
                      f"the Bull value is {(1 - biv / price) * 100:.1f}% below today's price")
        if bear_entry is not None and price is not None:
            beiv = bear_entry["dcf"].get("per_share_iv")
            if beiv is not None and beiv > price:
                _need(reasons_needed, "bear_above_price_reason",
                      _reason_given(params.get("bear_above_price_reason")), True,
                      f"the Bear value is {(beiv / price - 1) * 100:.1f}% above today's price")

        # Revision 17 (brief C6): before refusing on R13/R14, what the DEFAULTS Bull or Bear is worth and where the
        # ends of its 15% band land, so the refusal names the way out instead of inviting a walk across two rules.
        # The DEFAULTS scenario is this scenario's own call with its path at the printed level: year 1 at the Base's
        # level, year 2 at bear2 or bull2, years 3-5 the Base's as valued, the fade the Base's, and the default long
        # run (terminal_g_default and the DEFAULTS terminal_ronic). The edge is the same with year 2 at bear2 x 0.85
        # or bull2 x 1.15. Needs the printed levels; without them there is nothing computed to say.
        def _band_advice(role):
            entry = bear_entry if role == "bear" else bull_entry
            va = value_args.get(entry["name"])
            bf = base_final.get(base_entry["name"]) if base_entry is not None else None
            lvl, y1 = levels_ctx.get(f"{role}2"), levels_ctx.get("year1")
            cf_b = _to_b(va["cf"]) if va else None
            if not (va and bf and _is_num(lvl) and _is_num(y1) and lvl > 0 and y1 > 0 and cf_b is not None and cf_b > 0):
                return None
            five, left = _five_and_fade(bf[0], bf[1], bf[2])
            tg = ctx["terminal_g_default"] if _is_num(ctx.get("terminal_g_default")) else va["tg"]

            def worth(level):
                n_errors = len(compute_errors)
                dcf = _value(entry["name"], va["cf"], [y1 / cf_b - 1.0, level / y1 - 1.0] + list(five[2:]), va["wacc"],
                             tg, va["shares"], left, va["sbc"], va["sbc_dil"], va["frame"], va["net_debt"],
                             va["rate_type"], va["annuity"], va["annuity_cap"], ronic_default)
                del compute_errors[n_errors:]         # advice never refuses; a value it cannot compute is left out
                return None if dcf is None else dcf["per_share_iv"]

            tol = consensus_reference.LEVEL_TOL
            at_levels = worth(lvl)
            at_edge = worth(lvl * (1.0 - tol if role == "bear" else 1.0 + tol))
            if at_levels is None or at_edge is None:
                return None
            band = f"{tol * 100:.0f}%"
            p = f"${price:,.2f}"
            if role == "bear":
                out = []
                if at_levels > price:
                    out.append(f"The DEFAULTS Bear for this name is ${at_levels:,.2f}, above today's price {p}: keep the "
                               f"defaults and give bear_above_price_reason (why the downside is limited), or build a "
                               f"deeper Bear outside the band with scenario_deviation_reason and dated evidence.")
                if at_edge > price:
                    out.append(f"No Bear within {band} of bear2 lands below {p} (the band's lowest is ${at_edge:,.2f}); "
                               f"lowering it further needs scenario_deviation_reason as well.")
                else:
                    out.append(f"Lowering the Bear to ${at_edge:,.2f} or below within the band clears this without "
                               f"another reason.")
                return " ".join(out)
            out = []
            if at_levels < price:
                out.append(f"The DEFAULTS Bull for this name is ${at_levels:,.2f}, below today's price {p}: keep the "
                           f"defaults and give bull_below_price_reason (why the upside is limited), or build a "
                           f"higher Bull outside the band with scenario_deviation_reason and dated evidence.")
            if at_edge < price:
                out.append(f"No Bull within {band} of bull2 lands above {p} (the band's highest is ${at_edge:,.2f}); "
                           f"raising it further needs scenario_deviation_reason as well.")
            else:
                out.append(f"Raising the Bull to ${at_edge:,.2f} or above within the band clears this without "
                           f"another reason.")
            return " ".join(out)

        advice = {}
        for role, reason_name in (("bull", "bull_below_price_reason"), ("bear", "bear_above_price_reason")):
            if reason_name in reasons_needed:
                text = _band_advice(role)
                if text:
                    advice[reason_name] = text

        if reasons_needed or order_violation is not None:
            needs_reasons_list = [{"reason": k, "why": v} for k, v in reasons_needed.items()]
            return _refusal(missing=[], needs_reasons=needs_reasons_list, order=order_violation,
                            share_unit_note=share_unit_note, advice=advice)

    # ---- 3. Reverse DCF expectations gap (own structure + neutral reference from context) -----
    base_role_sc = next((s for s in scenarios if isinstance(s, dict) and _role_of(s.get("name")) == "base"), None)
    rev_cf = base_cf if base_cf is not None else (base_role_sc.get("base_cf") if base_role_sc else None)
    rev_wacc = wacc if wacc is not None else (base_role_sc.get("wacc") if base_role_sc else None)
    rev_shares = None
    if top_shares is not None:
        try:
            s_val = float(top_shares)
            if s_val > 0:
                rev_shares = s_val
        except (ValueError, TypeError):
            rev_shares = None
    elif base_role_sc is not None:
        s_base = _effective_shares(base_role_sc.get("shares_diluted"), None, ctx_shares_default_b)
        if s_base is not None:
            try:
                s_val = float(s_base)
                if s_val > 0:
                    rev_shares = s_val
            except (ValueError, TypeError):
                rev_shares = None

    if price and price > 0 and rev_cf is not None and rev_wacc is not None:
        term_g = params.get("terminal_g") if params.get("terminal_g") is not None else (
            base_role_sc.get("terminal_g") if base_role_sc else None)
        if term_g is not None:
            if rev_shares is None:
                result["reverse_dcf"] = {
                    "skipped": True,
                    "note": "reverse DCF skipped: explicit shares_diluted required (no defaulted share count since Phase 4)",
                }
            else:
                rev_coe_anchor = ctx.get("coe_anchor")
                rev_term_anchor = ctx.get("terminal_g_anchor")
                rev_base_rates = ctx.get("base_rate_table")
                rev_cagr = ctx.get("revenue_cagr_5y_pct")
                rev_fade = int(fade_years) if fade_years is not None else 0
                result["reverse_dcf"] = reverse_dcf_expectations_gap(
                    current_price=float(price),
                    shares_diluted=rev_shares,
                    base_cf=float(rev_cf),
                    wacc=float(rev_wacc),
                    terminal_g=float(term_g),
                    fade_years=rev_fade,
                    stage1_years=len(growth_rates) if growth_rates else 5,
                    net_debt=top_net_debt if top_net_debt is not None else 0.0,
                    valuation_frame=val_frame,
                    demonstrated_cagr_5y=float(rev_cagr) if rev_cagr is not None else None,
                    coe_anchor=float(rev_coe_anchor) if rev_coe_anchor is not None else None,
                    terminal_g_anchor=float(rev_term_anchor) if rev_term_anchor is not None else None,
                    base_rate_table=rev_base_rates,
                    terminal_ronic=base_inputs.get("ronic") if base_inputs else ronic_default,
                    long_run=long_run_ctx,
                    working_capital=(None if (not wc_ctx or base_inputs.get("wc_in_base")) else wc_ctx),
                )

    # ---- 4. Continuous Kelly sizing and Payoff Skew --------------------------------------------
    valid_scenarios = [s for s in scenarios if isinstance(s, dict) and s.get("iv") is not None and s.get("prob") is not None]
    if price and price > 0 and valid_scenarios:
        result["kelly_sizing"] = continuous_multi_outcome_kelly(
            price=price,
            outcomes=valid_scenarios,
            position_cap_pct=float(params.get("position_cap_pct", 25.0)),
        )
        base_iv = next((s["iv"] for s in valid_scenarios if _role_of(s.get("name")) == "base"), None)
        bull_iv = next((s["iv"] for s in valid_scenarios if _role_of(s.get("name")) == "bull"), None)
        bear_iv = next((s["iv"] for s in valid_scenarios if _role_of(s.get("name")) == "bear"), None)
        if base_iv is not None and bull_iv is not None and bear_iv is not None:
            result["payoff_skew"] = calculate_payoff_skew(float(base_iv), float(bull_iv), float(bear_iv), price)

    return result


def format_model_results_markdown(res: Dict[str, Any]) -> str:
    """Format the financial model calculation into a clean markdown table for Qwen."""
    lines = ["### FINANCIAL MODELING DESK REPORT (Deterministic Python Verification)\n"]
    price = res.get("price", 0.0)

    # Blend Valuation Output
    b = res.get("blend") if "blend" in res else (res if res.get("mode") == "blend" else None)
    if b and not b.get("error"):
        lines.append("**Valuation Blend Summary (Deterministic Weighted Desk Legs):**")
        lines.append("| Leg Name | Weight | Per-Share IV | Source |")
        lines.append("|---|---|---|---|")
        for leg in b.get("legs", []):
            lines.append(f"| **{leg.get('name')}** | {leg.get('weight_pct', 0.0):.1f}% | ${leg.get('per_share_iv', 0.0):.2f} | {leg.get('source')} |")
        lines.append(f"\n- Blended Intrinsic Value: **${b.get('blended_per_share_iv', 0.0):.2f}** per share")
        if "mos_pct" in b:
            lines.append(f"- Margin of Safety vs Price (${b.get('price'):.2f}): **{b.get('mos_pct'):+.1f}%**")
        lines.append("")

    # Scenario DCF Summary Table
    if "scenario_dcfs" in res and res["scenario_dcfs"]:
        lines.append("**Batch Scenario DCF Valuation Table:**")
        lines.append("| Scenario | Intrinsic Value | MoS vs Price | Enterprise Value | Equity Value | Terminal Method |")
        lines.append("|---|---|---|---|---|---|")
        for item in res["scenario_dcfs"]:
            name = item.get("name", "Scenario")
            d = item.get("dcf", {})
            iv = d.get("per_share_iv", 0.0)
            mos_str = f"{((iv - price) / price) * 100.0:+.1f}%" if price > 0 else "N/A"
            lines.append(f"| **{name}** | **${iv}** | {mos_str} | ${d.get('enterprise_value')}B | ${d.get('equity_value')}B | {d.get('terminal_method')} |")
        lines.append("")

    # Single DCF Output
    elif "dcf_model" in res and not res["dcf_model"].get("error"):
        d = res["dcf_model"]
        lines.append(f"**Unbundled DCF Valuation (Frame: {d.get('valuation_frame', 'equity')}, Rate Type: {d.get('rate_type')}):**")
        lines.append(f"- Intrinsic Value: **${d['per_share_iv']}** per share")
        if d.get("finite_life_years"):
            lines.append(f"  * Terminal Value: None ({d.get('terminal_method')})")
        else:
            lines.append(f"  * Gordon Terminal Value PV: ${d['terminal_value_pv']}B ({d['terminal_method']}, implied terminal multiple: {d.get('implied_terminal_ev_fcf_gordon')}x EV/FCF, TV share: {d.get('terminal_share_of_value', 0)*100:.1f}%)")
        if d.get("sector_multiple_band"):
            b = d["sector_multiple_band"]
            band_str = f"[{b.get('low')}, {b.get('high')}] {b.get('metric', '')}"
            in_g = "INSIDE" if d.get("multiple_in_band_gordon") else "OUTSIDE"
            lines.append(f"  * Reconciliation vs Sector Band ({band_str}): Gordon leg is **{in_g}** band")
        lines.append(f"- DCF Discrete Cash Flows PV: ${d['dcf_pv']}B (Stage 1: {len(d.get('explicit_growth', []))}y, Fade: {d.get('fade_years', 0)}y)")
        if d.get("annuity_pv", 0) > 0:
            lines.append(f"- Separate Installed-Base Annuity PV: **${d['annuity_pv']}B** (Unbundled from transactional DCF)")
        lines.append(f"- Enterprise Value: ${d['enterprise_value']}B | Net Debt: ${d['net_debt']}B -> Equity Value: ${d['equity_value']}B")
        if d.get("sbc_treatment"):
            lines.append(f"- SBC Policy: `{d.get('sbc_treatment')}`")
        lines.append("")

    yc = res.get("years35_cap")
    if isinstance(yc, dict):
        cap_val = yc.get("cap")
        if cap_val is not None:
            if yc.get("reason"):
                reason_str = str(yc["reason"])[:200]
                lines.append(
                    f"**Base years 3-5 above next-FY consensus revenue growth ({cap_val:+.1%}, DATA 8), kept on your guidance_deviation_reason:** "
                    f'"{reason_str}". The contract\'s guidance_deviation_reason must carry it.'
                )
                lines.append("")
            elif "dcfs" in yc and isinstance(yc["dcfs"], list):
                for cd in yc["dcfs"]:
                    name = cd.get("name", "Base")
                    app_rates = cd.get("applied_years35", [])
                    req_rates = cd.get("requested_years35", [])
                    applied_str = " / ".join(f"{g:+.1%}" for g in app_rates)
                    requested_str = " / ".join(f"{g:+.1%}" for g in req_rates)
                    if cd.get("applied_fade_years") != cd.get("requested_fade_years"):
                        applied_str += f"; fade_years {cd.get('applied_fade_years')}"
                    applied_iv = cd.get("applied_per_share_iv")
                    requested_iv = cd.get("requested_per_share_iv")
                    lines.append(
                        f"**Base years 3-5 held at next-FY consensus revenue growth ({cap_val:+.1%}, DATA 8):** "
                        f"no guidance_deviation_reason was given, so the desk valued {name} on years 3-5 "
                        f"{applied_str} instead of your {requested_str}: ${applied_iv}. "
                        f"Your path would give ${requested_iv}; that is not a desk value and cannot be your base_iv. "
                        f"Your contract's stage1_growth_path is the path the desk valued. "
                        f"To keep your path, run the desk again with guidance_deviation_reason citing dated evidence, "
                        f"and give the same reason in the contract."
                    )
                    lines.append("")

    yh = res.get("years12_held")
    if isinstance(yh, dict):
        lv = yh.get("levels") or {}
        for hd in yh.get("dcfs", []):
            g1, g2 = (hd.get("held_growth_years12") or [None, None])[:2]
            lines.append(
                f"**Base years 1-2 held at the fiscal-year consensus cash-flow levels (year 1 ${lv.get('year1')}B, "
                f"year 2 ${lv.get('year2')}B, DATA 8):** your {hd.get('name', 'Base')}'s year-2 cash flow was "
                f"${hd.get('requested_year2_flow')}B, {hd.get('requested_gap_pct')}% away, and no "
                f"guidance_deviation_reason was given, so the desk valued it on years 1-2 growth "
                f"{g1:+.1%} / {g2:+.1%} (years 3-5 as you sent them): ${hd.get('applied_per_share_iv')}. "
                f"Your path would give ${hd.get('requested_per_share_iv')}; that is not a desk value and cannot be "
                f"your base_iv. Your contract's stage1_growth_path is the path the desk valued. "
                f"To keep your own years 1-2, run the desk again with guidance_deviation_reason citing dated "
                f"evidence, and give the same reason in the contract."
            )
            lines.append("")

    if "reverse_dcf" in res and not res["reverse_dcf"].get("error"):
        r = res["reverse_dcf"]
        if r.get("skipped"):
            lines.append(f"**Reverse DCF:** {r.get('note', 'Skipped')}\n")
        else:
            lines.append("**Reverse DCF Expectations Gap (What's Priced in at T0):**")
            lines.append(f"- Structure (a) [Own Assumptions]: Implied Stage-1 Growth: **{r.get('implied_growth_next_5y_pct', 0.0):+.1f}%**")
        if "expectations_gap_pts" in r:
            lines.append(f"  * Demonstrated 5Y Historical CAGR: {r['demonstrated_cagr_5y_pct']:+.1f}% -> Expectations Gap: **{r['expectations_gap_pts']:+.1f} points**")
            lines.append(f"  * Assessment: *{r['assessment']}*")
        if "neutral_reference_structure" in r and not r["neutral_reference_structure"].get("error"):
            nr = r["neutral_reference_structure"]
            lines.append(f"- Structure (b) [Neutral Reference]: CoE Anchor: {nr['coe_anchor_pct']:.1f}% | Terminal g Anchor: {nr['terminal_g_anchor_pct']:.1f}% | 10-Year Linear Fade")
            lines.append(f"  * Solved Initial Growth: **{nr['solved_initial_growth_pct']:+.1f}%** -> Implied 10-Year CAGR: **{nr['implied_10y_cagr_pct']:+.1f}%**")
            if "percentile_band" in nr:
                lines.append(f"  * Base Rate Distribution: **{nr['percentile_band']}** ({nr.get('percentile_band_desc', '')})")
        lines.append("")

    if "kelly_sizing" in res and not res["kelly_sizing"].get("error"):
        k = res["kelly_sizing"]
        lines.append("**Mathematical Kelly Sizing (Continuous Multi-Outcome Log-Wealth):**")
        lines.append(f"- Expected Value: **${k['expected_iv']}** ({k['expected_return_pct']:+.2f}% expected return)")
        lines.append(f"- Recommendation: **{k['recommendation']}** ({k['reason']})")
        lines.append(f"- Full Kelly: {k['full_kelly_pct']:.2f}% | **Recommended Quarter-Kelly: {k['quarter_kelly_pct']:.2f}%**")
        if "payoff_skew" in res:
            lines.append(f"- Asymmetric Payoff Skew: **{res['payoff_skew']}x** (Upside / Downside)")
        lines.append("")

    return "\n".join(lines)
