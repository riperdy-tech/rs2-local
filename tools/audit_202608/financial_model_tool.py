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
# consensus_reference.py (the R10 window choice, LEVEL_TOL/FAR_LOW/FAR_HIGH) lives at repo_root/tools
_REPO_TOOLS = _REPO_ROOT / "tools"
if str(_REPO_TOOLS) not in sys.path:
    sys.path.insert(0, str(_REPO_TOOLS))

import rate_engine
import consensus_reference


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


def unbundled_dcf(
    base_cf: float,
    growth_rates: Optional[List[float]] = None,
    wacc: Optional[float] = None,
    terminal_g: Optional[float] = None,
    terminal_exit_multiple: Optional[float] = None,
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
    terminal_leg: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate three-stage DCF per Phase 4 Decision D1:
    - Explicit growth (Stage 1)
    - Linear fade to terminal_g over fade_years (Stage 2)
    - Dual terminal valuation: Gordon growth and exit multiple (when given), both discounted to t=0
    - Optional finite_life_years (1-60): discrete flows for N years with no terminal value
    - Valuation frame gating (equity refuses nonzero net_debt; firm requires net_debt and shares_diluted)
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
        else:
            effective_shares = effective_shares + sd

    if finite_life_years is None and rate <= terminal_g:
        return {"error": f"wacc ({rate}) must be greater than terminal_g ({terminal_g})", "validation_error": True}

    # Project discrete cash flows: Stage 1 (explicit) + Stage 2 (linear fade)
    cf = float(base_cf)
    yearly_cfs = []
    pv_cfs = []
    growth_applied = []
    year = 0

    max_years = finite_life_years if finite_life_years is not None else None

    for g in rates:
        if max_years is not None and year >= max_years:
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
            if max_years is not None and year >= max_years:
                break
            year += 1
            g_t = g_last + (terminal_g - g_last) * (i / fade_years)
            cf = cf * (1.0 + g_t)
            pv = cf / ((1.0 + rate) ** year)
            yearly_cfs.append(round(cf, 4))
            pv_cfs.append(round(pv, 4))
            growth_applied.append(round(g_t, 4))

    if max_years is not None:
        while year < max_years:
            year += 1
            g_t = terminal_g
            cf = cf * (1.0 + g_t)
            pv = cf / ((1.0 + rate) ** year)
            yearly_cfs.append(round(cf, 4))
            pv_cfs.append(round(pv, 4))
            growth_applied.append(round(g_t, 4))

    dcf_pv = sum(pv_cfs)
    n_years = year
    final_cf = cf

    # Annuity flow capitalization (unbundled service stream)
    annuity_pv = 0.0
    if annuity_flow and float(annuity_flow) > 0:
        cap_rate = float(annuity_cap_rate) if (annuity_cap_rate and float(annuity_cap_rate) > 0) else max(0.04, rate - 0.01)
        annuity_pv = float(annuity_flow) / cap_rate

    # Finite life handling: no terminal value (neither Gordon nor exit multiple)
    if finite_life_years is not None:
        has_exit = terminal_exit_multiple is not None and float(terminal_exit_multiple) > 0
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
        }
        if has_exit:
            res["note"] = "exit multiple ignored: finite life"
        if sbc_treatment is not None:
            res["sbc_treatment"] = sbc_treatment
            res["sbc_dilution"] = sbc_dilution
        return res

    # Stage 3: Terminal Value calculation — BOTH Gordon and exit multiple (when given)
    # Gordon terminal leg
    cf_n1_gordon = final_cf * (1.0 + terminal_g)
    tv_nominal_gordon = cf_n1_gordon / (rate - terminal_g)
    tv_pv_gordon = tv_nominal_gordon / ((1.0 + rate) ** n_years)
    implied_terminal_ev_fcf_gordon = tv_nominal_gordon / final_cf
    ev_gordon = dcf_pv + tv_pv_gordon + annuity_pv
    eq_gordon = ev_gordon - effective_net_debt
    per_share_iv_gordon = eq_gordon / effective_shares
    tv_share_gordon = (tv_pv_gordon / ev_gordon) if ev_gordon > 0 else 0.0

    # Exit multiple leg
    has_exit = terminal_exit_multiple is not None and float(terminal_exit_multiple) > 0
    if has_exit:
        exit_mult = float(terminal_exit_multiple)
        tv_nominal_exit = final_cf * exit_mult
        tv_pv_exit = tv_nominal_exit / ((1.0 + rate) ** n_years)
        ev_exit = dcf_pv + tv_pv_exit + annuity_pv
        eq_exit = ev_exit - effective_net_debt
        per_share_iv_exit = eq_exit / effective_shares
        tv_share_exit = (tv_pv_exit / ev_exit) if ev_exit > 0 else 0.0
        implied_terminal_ev_fcf_exit = exit_mult
        # Phase 4 E13: the terminal growth this multiple asserts at this rate, g = (M*r - 1) / (M + 1).
        # The flow has already faded to terminal_g, so any other multiple states another growth
        # (FIX s2: 16x at 8.98% implies 2.57% against the 3.75% anchor).
        exit_implied_terminal_g = (exit_mult * rate - 1.0) / (exit_mult + 1.0)
    else:
        exit_implied_terminal_g = None
        exit_mult = None
        tv_nominal_exit = None
        tv_pv_exit = None
        ev_exit = None
        eq_exit = None
        per_share_iv_exit = None
        tv_share_exit = None
        implied_terminal_ev_fcf_exit = None

    # Sector multiple band reconciliation check
    gordon_in_band = None
    exit_in_band = None
    if sector_multiple_band and isinstance(sector_multiple_band, dict):
        band_low = float(sector_multiple_band.get("low", float("-inf")))
        band_high = float(sector_multiple_band.get("high", float("inf")))
        gordon_in_band = (band_low <= implied_terminal_ev_fcf_gordon <= band_high)
        if exit_mult is not None:
            exit_in_band = (band_low <= exit_mult <= band_high)

    # Primary (published) terminal leg. S3 3.6: with an exit multiple, terminal_leg=None (or
    # "exit") means exit, today's leg; "gordon" publishes the Gordon leg instead. With no exit
    # multiple only Gordon exists, regardless of terminal_leg.
    published_leg = "gordon" if (not has_exit or terminal_leg == "gordon") else "exit"
    if published_leg == "exit":
        primary_tv_nominal = tv_nominal_exit
        primary_tv_pv = tv_pv_exit
        primary_ev = ev_exit
        primary_eq = eq_exit
        primary_iv = per_share_iv_exit
        primary_tv_method = f"{exit_mult:.1f}x exit multiple"
        primary_tv_share = tv_share_exit
    else:
        primary_tv_nominal = tv_nominal_gordon
        primary_tv_pv = tv_pv_gordon
        primary_ev = ev_gordon
        primary_eq = eq_gordon
        primary_iv = per_share_iv_gordon
        primary_tv_method = f"Gordon growth @ {terminal_g * 100:.1f}%"
        primary_tv_share = tv_share_gordon

    res: Dict[str, Any] = {
        "per_share_iv": round(primary_iv, 2),
        "per_share_iv_gordon": round(per_share_iv_gordon, 2),
        "enterprise_value": round(primary_ev, 2),
        "equity_value": round(primary_eq, 2),
        "dcf_pv": round(dcf_pv, 2),
        "terminal_value_nominal": round(primary_tv_nominal, 2),
        "terminal_value_pv": round(primary_tv_pv, 2),
        "terminal_method": primary_tv_method,
        "terminal_share_of_value": round(primary_tv_share, 4),
        "implied_terminal_ev_fcf_gordon": round(implied_terminal_ev_fcf_gordon, 2),
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
        "terminal_leg": published_leg,
        "gordon_terminal": {
            "per_share_iv": round(per_share_iv_gordon, 2),
            "terminal_value_nominal": round(tv_nominal_gordon, 2),
            "terminal_value_pv": round(tv_pv_gordon, 2),
            "enterprise_value": round(ev_gordon, 2),
            "equity_value": round(eq_gordon, 2),
            "terminal_share_of_value": round(tv_share_gordon, 4),
            "implied_terminal_multiple": round(implied_terminal_ev_fcf_gordon, 2),
            "in_band": gordon_in_band,
        },
    }

    if has_exit:
        res["per_share_iv_exit"] = round(per_share_iv_exit, 2)
        res["terminal_share_of_value_exit"] = round(tv_share_exit, 4)
        res["exit_multiple_terminal"] = {
            "per_share_iv": round(per_share_iv_exit, 2),
            "terminal_value_nominal": round(tv_nominal_exit, 2),
            "terminal_value_pv": round(tv_pv_exit, 2),
            "enterprise_value": round(ev_exit, 2),
            "equity_value": round(eq_exit, 2),
            "terminal_share_of_value": round(tv_share_exit, 4),
            "exit_multiple": exit_mult,
            "implied_terminal_g": round(exit_implied_terminal_g, 4),
            "in_band": exit_in_band,
        }
        res["exit_implied_terminal_g"] = round(exit_implied_terminal_g, 4)

    if sector_multiple_band is not None:
        # Phase 4 window fix: echo the band and a short label only; in_band used the full band above
        res["sector_multiple_band"] = (
            {k: (str(v)[:80] if k == "metric" else v) for k, v in sector_multiple_band.items()
             if k in ("low", "mid", "high", "metric")}
            if isinstance(sector_multiple_band, dict) else sector_multiple_band)
        res["multiple_in_band_gordon"] = gordon_in_band
        if has_exit:
            res["multiple_in_band_exit"] = exit_in_band

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
    terminal_exit_multiple: Optional[float] = None,
    net_debt: float = 0.0,
    valuation_frame: str = "equity",
    annuity_flow: float = 0.0,
    annuity_cap_rate: Optional[float] = None,
    coe_anchor: Optional[float] = None,
    terminal_g_anchor: Optional[float] = None,
    base_rate_table: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Solve for market-implied growth per Phase 4 Decision D2:
    (a) under caller's own structure (solve constant stage-1 growth equating IV to price, holding fade/terminal/rate)
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
            terminal_exit_multiple=terminal_exit_multiple,
            annuity_flow=annuity_flow,
            annuity_cap_rate=annuity_cap_rate,
            net_debt=net_debt,
            shares_diluted=shares_diluted,
            fade_years=fade_years,
            valuation_frame=valuation_frame,
            sbc_treatment="deducted_in_cf",
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
    if explicit is not None:
        return explicit
    if top_shares is not None:
        return top_shares
    return ctx_default_b


def _need(reasons_needed, reason_name, given, triggered, why):
    """S3 3.5: record that `reason_name` is needed, the first time it is triggered without
    already being given. `reasons_needed` is an ordered dict of reason name -> why text."""
    if triggered and not given:
        reasons_needed.setdefault(reason_name, why)


def _refusal(missing, needs_reasons, order=None):
    """S3 3.7's refusal format."""
    detail_bits = []
    if order is not None:
        detail_bits.append(f"the published values are not Bear <= Base <= Bull (Bear {order['bear']:.2f}, "
                           f"Base {order['base']:.2f}, Bull {order['bull']:.2f}); no reason overrides the "
                           f"order: change an input with dated evidence")
    if missing:
        detail_bits.append("missing " + ", ".join(missing))
    if needs_reasons:
        detail_bits.append("; ".join(f"{n['reason']} needed: {n['why']}" for n in needs_reasons))
    detail = "; ".join(detail_bits)
    msg = ("Not accepted as a desk run; it does not use one of your desk runs. " + detail +
           ". Call again with the same inputs and these reasons, or change an input with dated evidence.")
    out: Dict[str, Any] = {
        "error": msg,
        "validation_error": True,
        "missing": list(missing),
        "needs_reasons": list(needs_reasons),
    }
    if order is not None:
        out["order"] = order
    return out


def execute_financial_model(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Master tool dispatcher called by Qwen or automation harness.
    Supports single DCF, batch multi-scenario DCF, or blend mode in a single round trip.

    S3 3.2-3.7: `context` (the harness's desk_context) supplies today's price, the pack's share
    default, the anchors, the base-rate table and the reverse-DCF inputs; the model supplies its
    decisions and, where they depart from a default, the named reason. A call the desk cannot use,
    or whose published legs fail a reason check, is refused (3.4, 3.5) and does not use a desk run.
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

    is_finite = cfl_valid and cfl_norm != "perpetual"

    # V4: terminal_leg
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        nm = sc.get("name") or "scenario"
        tl = sc.get("terminal_leg")
        if tl is None:
            continue
        if tl not in ("exit", "gordon"):
            missing.append(f"terminal_leg in {nm} (must be \"exit\" or \"gordon\")")
        elif is_finite:
            missing.append(f"terminal_leg in {nm} (a finite life has no terminal leg)")
        elif tl == "exit" and sc.get("terminal_exit_multiple") is None and params.get("terminal_exit_multiple") is None:
            missing.append(f"terminal_leg in {nm} (\"exit\" needs an exit multiple)")

    # V5: every scenario needs prob >= 0; Base+Bull+Bear sum to 0.99-1.01 when all three are present
    if scenarios:
        for sc in scenarios:
            nm = sc.get("name") if isinstance(sc, dict) else "scenario"
            p = sc.get("prob") if isinstance(sc, dict) else None
            if not isinstance(p, (int, float)) or type(p) is bool or p < 0:
                missing.append(f"prob in {nm}")
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

    capped_dcfs: List[Dict[str, Any]] = []
    kept_names: List[str] = []
    scenario_dcfs = []
    compute_errors: List[str] = []

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
        s_exit_mult = sc.get("terminal_exit_multiple") if sc.get("terminal_exit_multiple") is not None else params.get("terminal_exit_multiple")
        s_terminal_leg = sc.get("terminal_leg")

        dcf_res = unbundled_dcf(
            base_cf=float(s_cf),
            growth_rates=[float(g) for g in s_gr],
            wacc=float(s_wacc),
            terminal_g=float(s_term_g) if s_term_g is not None else None,
            terminal_exit_multiple=float(s_exit_mult) if s_exit_mult else None,
            annuity_flow=float(sc.get("annuity_flow", params.get("annuity_flow", 0.0))),
            annuity_cap_rate=float(sc["annuity_cap_rate"]) if sc.get("annuity_cap_rate") else (float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None),
            net_debt=sc_net_debt,
            shares_diluted=s_shares,
            fade_years=s_fade,
            valuation_frame=sc_frame,
            rate_type=sc.get("rate_type", rate_type),
            sbc_treatment=s_sbc,
            sbc_dilution=s_sbc_dil,
            finite_life_years=desk_finite_life_years,
            terminal_leg=s_terminal_leg,
        )
        if dcf_res.get("error"):
            compute_errors.append(f"{sc_name}: {dcf_res['error']}")
            continue

        is_base = _role_of(sc_name) == "base"
        if is_base and cap is not None:
            app_years = applied_years_1_to_5(s_gr, s_term_g, s_fade, desk_finite_life_years)
            y35 = app_years[2:]
            if any(g > cap + 1e-12 for g in y35):
                if reason:
                    kept_names.append(sc_name)
                else:
                    n = len(s_gr)
                    new_fade = max(0, int(s_fade) - (5 - n)) if n < 5 and s_fade is not None else (int(s_fade) if s_fade is not None else None)
                    new_explicit_growth = app_years[:2] + [min(g, cap) for g in y35] + [float(g) for g in s_gr[5:]]
                    new_dcf_res = unbundled_dcf(
                        base_cf=float(s_cf),
                        growth_rates=None,
                        explicit_growth=new_explicit_growth,
                        wacc=float(s_wacc),
                        terminal_g=float(s_term_g) if s_term_g is not None else None,
                        terminal_exit_multiple=float(s_exit_mult) if s_exit_mult else None,
                        annuity_flow=float(sc.get("annuity_flow", params.get("annuity_flow", 0.0))),
                        annuity_cap_rate=float(sc["annuity_cap_rate"]) if sc.get("annuity_cap_rate") else (float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None),
                        net_debt=sc_net_debt,
                        shares_diluted=s_shares,
                        fade_years=new_fade,
                        valuation_frame=sc_frame,
                        rate_type=sc.get("rate_type", rate_type),
                        sbc_treatment=s_sbc,
                        sbc_dilution=s_sbc_dil,
                        finite_life_years=desk_finite_life_years,
                        terminal_leg=s_terminal_leg,
                    )
                    if new_dcf_res.get("error"):
                        compute_errors.append(f"{sc_name}: {new_dcf_res['error']}")
                        continue
                    new_dcf_res["years35_capped"] = True
                    capped_dcfs.append({
                        "name": sc_name,
                        "requested_years35": [round(g, 4) for g in y35],
                        "applied_years35": [round(min(g, cap), 4) for g in y35],
                        "requested_per_share_iv": round(dcf_res["per_share_iv"], 2),
                        "applied_per_share_iv": round(new_dcf_res["per_share_iv"], 2),
                        "requested_fade_years": int(s_fade) if s_fade is not None else None,
                        "applied_fade_years": new_fade,
                    })
                    dcf_res = new_dcf_res

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
        dcf_single = unbundled_dcf(
            base_cf=float(base_cf),
            growth_rates=[float(g) for g in growth_rates],
            wacc=float(wacc),
            terminal_g=float(params["terminal_g"]) if params.get("terminal_g") is not None else None,
            terminal_exit_multiple=float(params["terminal_exit_multiple"]) if params.get("terminal_exit_multiple") else None,
            annuity_flow=float(params.get("annuity_flow", 0.0)),
            annuity_cap_rate=float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None,
            net_debt=top_net_debt,
            shares_diluted=top_shares,
            fade_years=fade_years,
            valuation_frame=val_frame,
            rate_type=rate_type,
            sbc_treatment=sbc_treatment,
            sbc_dilution=sbc_dilution,
            finite_life_years=desk_finite_life_years,
        )
        if dcf_single.get("error"):
            compute_errors.append(f"top-level: {dcf_single['error']}")
            dcf_single = None
        else:
            if cap is not None:
                app_years = applied_years_1_to_5(growth_rates, params.get("terminal_g"), fade_years, desk_finite_life_years)
                y35 = app_years[2:]
                if any(g > cap + 1e-12 for g in y35):
                    if reason:
                        kept_names.append("top-level")
                    else:
                        n = len(growth_rates)
                        new_fade = max(0, int(fade_years) - (5 - n)) if n < 5 and fade_years is not None else (int(fade_years) if fade_years is not None else None)
                        new_explicit_growth = app_years[:2] + [min(g, cap) for g in y35] + [float(g) for g in growth_rates[5:]]
                        new_dcf_single = unbundled_dcf(
                            base_cf=float(base_cf),
                            growth_rates=None,
                            explicit_growth=new_explicit_growth,
                            wacc=float(wacc),
                            terminal_g=float(params["terminal_g"]) if params.get("terminal_g") is not None else None,
                            terminal_exit_multiple=float(params["terminal_exit_multiple"]) if params.get("terminal_exit_multiple") else None,
                            annuity_flow=float(params.get("annuity_flow", 0.0)),
                            annuity_cap_rate=float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None,
                            net_debt=top_net_debt,
                            shares_diluted=top_shares,
                            fade_years=new_fade,
                            valuation_frame=val_frame,
                            rate_type=rate_type,
                            sbc_treatment=sbc_treatment,
                            sbc_dilution=sbc_dilution,
                            finite_life_years=desk_finite_life_years,
                        )
                        if new_dcf_single.get("error"):
                            compute_errors.append(f"top-level: {new_dcf_single['error']}")
                            dcf_single = None
                        else:
                            new_dcf_single["years35_capped"] = True
                            capped_dcfs.append({
                                "name": "top-level",
                                "requested_years35": [round(g, 4) for g in y35],
                                "applied_years35": [round(min(g, cap), 4) for g in y35],
                                "requested_per_share_iv": round(dcf_single["per_share_iv"], 2),
                                "applied_per_share_iv": round(new_dcf_single["per_share_iv"], 2),
                                "requested_fade_years": int(fade_years) if fade_years is not None else None,
                                "applied_fade_years": new_fade,
                            })
                            dcf_single = new_dcf_single
            if dcf_single is not None:
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

        # R2 + R3 (Base, base_cf_reason)
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
        base_window = ctx.get("base_window") or {}
        if base_window:
            _need(reasons_needed, "base_cf_reason", base_cf_reason_given, True,
                  f"the pack prints a BASE WINDOW CHECK (gap {base_window.get('gap')})")

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

        # R5 + R6 (Base terminal_g / exit-implied terminal g vs terminal_g_default)
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
            if base_entry["dcf"].get("terminal_leg") == "exit":
                m_x = (base_entry["dcf"].get("exit_multiple_terminal") or {}).get("exit_multiple")
                r_x = base_entry["dcf"].get("discount_rate_applied")
                if m_x is not None and r_x is not None:
                    implied_g = (float(m_x) * float(r_x) - 1.0) / (float(m_x) + 1.0)
                    gap_bp = round((implied_g - tg_default) * 10000)
                    if abs(gap_bp) > 50:
                        _need(reasons_needed, "terminal_reason", terminal_reason_given, True,
                              f"Base exit multiple implies terminal growth {implied_g * 100:.2f}%, "
                              f"{abs(gap_bp) / 100:.2f} points from terminal_g_default {tg_default * 100:.2f}%")

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

        # R10 (Base vs the reference window)
        guidance_reason_given = _reason_given(params.get("guidance_deviation_reason"))
        if base_entry is not None:
            civ = ctx.get("consensus_implied_value")
            levels = ctx.get("levels") or {}
            y2_level = levels.get("year2")
            base_iv = base_entry["dcf"].get("per_share_iv")
            ref_val, ref_level, _win = consensus_reference.choose_reference_window(
                civ, y2_level, base_window.get("ttm_value"), base_window.get("ttm_year2"), base_iv)
            base_cf_val = _to_b(base_entry["sc"].get("base_cf"))
            g_path = base_entry["dcf"].get("growth_rates_applied") or []
            if ref_level and base_cf_val is not None and len(g_path) >= 2:
                y2_flow = base_cf_val * (1 + g_path[0]) * (1 + g_path[1])
                gap = abs(y2_flow - ref_level) / abs(ref_level)
                if gap > consensus_reference.LEVEL_TOL:
                    _need(reasons_needed, "guidance_deviation_reason", guidance_reason_given, True,
                          f"Base year-2 cash flow {y2_flow:.4f}B is {gap * 100:.1f}% from the "
                          f"reference year-2 level {ref_level:.4f}B")
            if ref_val and base_iv is not None:
                ratio = base_iv / ref_val
                if not (consensus_reference.FAR_LOW <= ratio <= consensus_reference.FAR_HIGH):
                    _need(reasons_needed, "guidance_deviation_reason", guidance_reason_given, True,
                          f"the Base value is {ratio:.2f}x the reference (outside "
                          f"{consensus_reference.FAR_LOW}-{consensus_reference.FAR_HIGH})")

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

        if reasons_needed or order_violation is not None:
            needs_reasons_list = [{"reason": k, "why": v} for k, v in reasons_needed.items()]
            return _refusal(missing=[], needs_reasons=needs_reasons_list, order=order_violation)

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
                    terminal_exit_multiple=float(params["terminal_exit_multiple"]) if params.get("terminal_exit_multiple") else None,
                    net_debt=top_net_debt if top_net_debt is not None else 0.0,
                    valuation_frame=val_frame,
                    demonstrated_cagr_5y=float(rev_cagr) if rev_cagr is not None else None,
                    coe_anchor=float(rev_coe_anchor) if rev_coe_anchor is not None else None,
                    terminal_g_anchor=float(rev_term_anchor) if rev_term_anchor is not None else None,
                    base_rate_table=rev_base_rates,
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
        # Phase 4 E13: what each exit multiple asserts about terminal growth, next to the Gordon leg
        for item in res["scenario_dcfs"]:
            d = item.get("dcf", {})
            if d.get("exit_implied_terminal_g") is not None:
                lines.append(f"- {item.get('name', 'Scenario')}: {d.get('terminal_method')} implies terminal g "
                             f"{d['exit_implied_terminal_g'] * 100:.2f}% vs {d.get('terminal_g', 0) * 100:.2f}% in the "
                             f"Gordon leg (Gordon ${d.get('per_share_iv_gordon')}, implied multiple "
                             f"{d.get('implied_terminal_ev_fcf_gordon')}x)")
        lines.append("")

    # Single DCF Output
    elif "dcf_model" in res and not res["dcf_model"].get("error"):
        d = res["dcf_model"]
        lines.append(f"**Unbundled DCF Valuation (Frame: {d.get('valuation_frame', 'equity')}, Rate Type: {d.get('rate_type')}):**")
        lines.append(f"- Intrinsic Value: **${d['per_share_iv']}** per share")
        if d.get("finite_life_years"):
            lines.append(f"  * Terminal Value: None ({d.get('terminal_method')})")
        elif "per_share_iv_exit" in d and d.get("per_share_iv_exit") is not None:
            lines.append(f"  * Gordon Terminal Leg: **${d.get('per_share_iv_gordon')}** (implied terminal multiple: {d.get('implied_terminal_ev_fcf_gordon')}x EV/FCF, TV share: {d.get('gordon_terminal', {}).get('terminal_share_of_value', 0)*100:.1f}%)")
            _g_exit = d.get("exit_implied_terminal_g")
            _g_note = (f", implies terminal g {_g_exit * 100:.2f}% vs {d.get('terminal_g', 0) * 100:.2f}% in the Gordon leg"
                       if _g_exit is not None else "")
            lines.append(f"  * Exit Multiple Leg: **${d.get('per_share_iv_exit')}** ({d.get('terminal_method')}{_g_note}, TV share: {d.get('terminal_share_of_value_exit', 0)*100:.1f}%)")
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
