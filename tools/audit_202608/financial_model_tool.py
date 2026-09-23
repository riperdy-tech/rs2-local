#!/usr/bin/env python3
"""financial_model_tool.py — Deterministic Financial Modeling Analyst Desk.

Provides exact arithmetic mid-stream for RS2 depth underwritings:
1. unbundled_dcf: DCF with separate installed-base service annuity streams (avoids double-counting).
2. reverse_dcf_expectations_gap: Solves for market-implied growth at T0 price vs demonstrated CAGR.
3. continuous_multi_outcome_kelly: Multi-scenario log-wealth optimization (strictly 0.0% if edge <= 0).
4. calculate_payoff_skew: Mathematical upside/downside ratio.
5. execute_financial_model: Master dispatcher and formatter for LLM function calling.
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

import rate_engine


def unbundled_dcf(
    base_cf: float,
    growth_rates: Optional[List[float]] = None,
    wacc: Optional[float] = None,
    terminal_g: Optional[float] = None,
    terminal_exit_multiple: Optional[float] = None,
    annuity_flow: float = 0.0,
    annuity_cap_rate: Optional[float] = None,
    net_debt: Optional[float] = None,
    shares_diluted: float = 1.0,
    fade_years: int = 0,
    explicit_growth: Optional[List[float]] = None,
    discount_rate: Optional[float] = None,
    valuation_frame: str = "equity",
    rate_type: Optional[str] = None,
    sector_multiple_band: Optional[Dict[str, Any]] = None,
    sbc_treatment: Optional[str] = None,
    sbc_dilution: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate three-stage DCF per Phase 4 Decision D1:
    - Explicit growth (Stage 1)
    - Linear fade to terminal_g over fade_years (Stage 2)
    - Dual terminal valuation: Gordon growth and exit multiple (when given), both discounted to t=0
    - Valuation frame gating (equity refuses nonzero net_debt; firm requires net_debt and shares_diluted)
    - rate_engine.check_pairing wired with FrameMismatch structured refusal
    - SBC treatment single declaration; double deduction refused
    - Implied terminal EV/FCF multiple and reconciliation against sector_multiple_band
    """
    if terminal_g is None:
        return {"error": "terminal_g is required (the silent default was removed in Phase 4)"}
    terminal_g = float(terminal_g)

    # Resolve rates
    rates = explicit_growth if explicit_growth is not None else growth_rates
    if not rates or len(rates) == 0:
        return {"error": "explicit_growth (or growth_rates) must be a non-empty list of growth rates"}

    # Resolve discount rate
    effective_rate = wacc if wacc is not None else discount_rate
    if effective_rate is None or effective_rate <= 0:
        return {"error": "wacc (or discount_rate) must be positive"}
    rate = float(effective_rate)

    if base_cf <= 0:
        return {"error": "base_cf must be positive for standard DCF"}

    if fade_years is None:
        fade_years = 0
    if not isinstance(fade_years, int) or fade_years < 0:
        return {"error": "fade_years must be an integer >= 0"}

    # Valuation frame enforcement (D1)
    frame = str(valuation_frame or "equity").strip().lower()
    if frame == "equity":
        frame_enum = rate_engine.RS2_EQUITY_FRAME
        claim_enum = rate_engine.CLAIM_EQUITY
        if net_debt is not None and abs(float(net_debt)) > 1e-9:
            return {"error": f"valuation_frame 'equity' refuses nonzero net_debt ({net_debt}); cash flows are levered (FCFE) and directly yield equity value"}
        effective_net_debt = 0.0
        if rate_type is None:
            rate_type_norm = rate_engine.COST_OF_EQUITY
        else:
            rate_type_norm = str(rate_type).strip().upper()
    elif frame == "firm":
        frame_enum = rate_engine.FIRM_FCFF_FRAME
        claim_enum = rate_engine.CLAIM_FIRM
        if net_debt is None:
            return {"error": "valuation_frame 'firm' requires net_debt to bridge enterprise value to equity value"}
        if shares_diluted is None or float(shares_diluted) <= 0:
            return {"error": "valuation_frame 'firm' requires positive shares_diluted"}
        effective_net_debt = float(net_debt)
        if rate_type is None:
            rate_type_norm = rate_engine.TRUE_WACC
        else:
            rate_type_norm = str(rate_type).strip().upper()
    else:
        return {"error": f"unknown valuation_frame '{valuation_frame}'; allowed frames are 'equity' and 'firm'"}

    # Rate pairing check
    try:
        rate_engine.check_pairing(frame_enum, claim_enum, rate_type_norm)
    except rate_engine.FrameMismatch as exc:
        return {"error": f"FrameMismatch: {str(exc)}"}

    # SBC treatment (D1)
    if sbc_treatment is not None:
        sbc_norm = str(sbc_treatment).strip().lower()
        if sbc_norm not in ("deducted_in_cf", "add_back_dilution"):
            return {"error": f"unknown sbc_treatment '{sbc_treatment}'; allowed values are 'deducted_in_cf' and 'add_back_dilution'"}
        if sbc_norm == "deducted_in_cf":
            if sbc_dilution is not None and sbc_dilution != 0.0:
                return {"error": "double deduction refused: sbc_treatment is 'deducted_in_cf', so sbc_dilution may not also be passed"}

    effective_shares = float(shares_diluted) if shares_diluted is not None else 1.0
    if effective_shares <= 0:
        return {"error": "shares_diluted must be positive"}

    if sbc_treatment is not None and str(sbc_treatment).strip().lower() == "add_back_dilution":
        if sbc_dilution is not None and float(sbc_dilution) > 0:
            sd = float(sbc_dilution)
            if sd < 1.0:
                effective_shares = effective_shares * (1.0 + sd)
            else:
                effective_shares = effective_shares + sd

    if rate <= terminal_g:
        return {"error": f"wacc ({rate}) must be greater than terminal_g ({terminal_g})"}

    # Project discrete cash flows: Stage 1 (explicit) + Stage 2 (linear fade)
    cf = float(base_cf)
    yearly_cfs = []
    pv_cfs = []
    growth_applied = []
    year = 0

    for g in rates:
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
            year += 1
            g_t = g_last + (terminal_g - g_last) * (i / fade_years)
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
    else:
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

    # Primary terminal leg: exit multiple if provided by caller, else Gordon
    if has_exit:
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
            "in_band": exit_in_band,
        }

    if sector_multiple_band is not None:
        res["sector_multiple_band"] = sector_multiple_band
        res["multiple_in_band_gordon"] = gordon_in_band
        if has_exit:
            res["multiple_in_band_exit"] = exit_in_band

    if sbc_treatment is not None:
        res["sbc_treatment"] = sbc_treatment
        res["sbc_dilution"] = sbc_dilution

    return res


def _two_stage_dcf_for_reverse(
    base_cf: float,
    g: float,
    wacc: float,
    terminal_g: float = 0.025,
    stage1_years: int = 5,
    fade_years: int = 5,
) -> Optional[float]:
    """Two-stage DCF value used for expectations gap bisection."""
    if wacc <= terminal_g:
        return None
    pv = 0.0
    cf = base_cf
    year = 0
    for _ in range(stage1_years):
        year += 1
        cf *= (1.0 + g)
        pv += cf / ((1.0 + wacc) ** year)
    for i in range(1, fade_years + 1):
        year += 1
        g_t = g + (terminal_g - g) * (i / fade_years)
        cf *= (1.0 + g_t)
        pv += cf / ((1.0 + wacc) ** year)
    terminal_cf = cf * (1.0 + terminal_g)
    terminal_val = terminal_cf / (wacc - terminal_g)
    pv += terminal_val / ((1.0 + wacc) ** year)
    return pv


def reverse_dcf_expectations_gap(
    current_price: float,
    shares_diluted: float,
    base_cf: float,
    wacc: float,
    terminal_g: float = 0.025,
    demonstrated_cagr_5y: Optional[float] = None,
) -> Dict[str, Any]:
    """Solve for 5-year growth implied by current market cap and compare to demonstrated history."""
    if current_price <= 0 or shares_diluted <= 0 or base_cf <= 0 or wacc <= terminal_g:
        return {"error": "Invalid inputs for reverse DCF (price, shares, base_cf, and wacc must be positive)"}

    target_mcap = current_price * shares_diluted

    # Bisection search between -50% and +150% growth
    lo, hi = -0.50, 1.50
    implied_g = None
    
    val_lo = _two_stage_dcf_for_reverse(base_cf, lo, wacc, terminal_g)
    val_hi = _two_stage_dcf_for_reverse(base_cf, hi, wacc, terminal_g)
    
    if val_lo is not None and target_mcap < val_lo:
        implied_g = lo
    elif val_hi is not None and target_mcap > val_hi:
        implied_g = hi
    else:
        for _ in range(60):
            mid = (lo + hi) / 2.0
            val_mid = _two_stage_dcf_for_reverse(base_cf, mid, wacc, terminal_g)
            if val_mid is None:
                break
            if abs(val_mid - target_mcap) < 0.01 * target_mcap:
                implied_g = mid
                break
            if val_mid < target_mcap:
                lo = mid
            else:
                hi = mid
        if implied_g is None:
            implied_g = (lo + hi) / 2.0

    implied_g_pct = round(implied_g * 100.0, 2)
    res: Dict[str, Any] = {
        "target_market_cap": round(target_mcap, 2),
        "implied_growth_next_5y_pct": implied_g_pct,
        "assumed_wacc_pct": round(wacc * 100.0, 2),
        "terminal_growth_pct": round(terminal_g * 100.0, 2),
    }

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


def execute_financial_model(params: Dict[str, Any]) -> Dict[str, Any]:
    """Master tool dispatcher called by Qwen or automation harness.
    Supports single DCF or batch multi-scenario DCF in a single round trip."""
    price = float(params.get("price") or 0)
    result: Dict[str, Any] = {"price": price}

    val_frame = params.get("valuation_frame", "equity")
    rate_type = params.get("rate_type")
    fade_years = int(params.get("fade_years", 0))
    sector_multiple_band = params.get("sector_multiple_band")
    sbc_treatment = params.get("sbc_treatment")
    sbc_dilution = params.get("sbc_dilution")

    top_net_debt = float(params["net_debt"]) if params.get("net_debt") is not None else (0.0 if val_frame == "equity" else None)
    top_shares = float(params.get("shares_diluted", 1.0))

    scenarios = params.get("scenarios") or []
    scenario_dcfs = []

    # 1. Batch Scenario DCF Execution (if scenarios provide DCF parameters)
    if scenarios:
        for sc in scenarios:
            s_cf = sc.get("base_cf")
            s_gr = sc.get("explicit_growth") if sc.get("explicit_growth") is not None else sc.get("growth_rates")
            s_wacc = sc.get("wacc") if sc.get("wacc") is not None else sc.get("discount_rate")
            s_term_g = sc.get("terminal_g") if sc.get("terminal_g") is not None else params.get("terminal_g")
            if s_cf is not None and s_gr and s_wacc is not None:
                if s_term_g is None:
                    return {"error": "terminal_g is required for all DCF scenarios (the silent default was removed in Phase 4)"}
                sc_frame = sc.get("valuation_frame", val_frame)
                sc_net_debt = float(sc["net_debt"]) if sc.get("net_debt") is not None else top_net_debt
                dcf_res = unbundled_dcf(
                    base_cf=float(s_cf),
                    growth_rates=[float(g) for g in s_gr],
                    wacc=float(s_wacc),
                    terminal_g=float(s_term_g),
                    terminal_exit_multiple=float(sc["terminal_exit_multiple"]) if sc.get("terminal_exit_multiple") else (float(params["terminal_exit_multiple"]) if params.get("terminal_exit_multiple") else None),
                    annuity_flow=float(sc.get("annuity_flow", params.get("annuity_flow", 0.0))),
                    annuity_cap_rate=float(sc["annuity_cap_rate"]) if sc.get("annuity_cap_rate") else (float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None),
                    net_debt=sc_net_debt,
                    shares_diluted=float(sc.get("shares_diluted", top_shares)),
                    fade_years=int(sc.get("fade_years", fade_years)),
                    valuation_frame=sc_frame,
                    rate_type=sc.get("rate_type", rate_type),
                    sector_multiple_band=sc.get("sector_multiple_band", sector_multiple_band),
                    sbc_treatment=sc.get("sbc_treatment", sbc_treatment),
                    sbc_dilution=sc.get("sbc_dilution", sbc_dilution),
                )
                if not dcf_res.get("error"):
                    sc["iv"] = dcf_res["per_share_iv"]
                    sc["dcf_details"] = dcf_res
                    scenario_dcfs.append({"name": sc.get("name"), "dcf": dcf_res})
                else:
                    return {"error": f"scenario '{sc.get('name')}' DCF error: {dcf_res['error']}"}

    if scenario_dcfs:
        result["scenario_dcfs"] = scenario_dcfs

    # 2. Single DCF projection (if top-level parameters supplied)
    base_cf = params.get("base_cf")
    growth_rates = params.get("explicit_growth") if params.get("explicit_growth") is not None else params.get("growth_rates")
    wacc = params.get("wacc") if params.get("wacc") is not None else params.get("discount_rate")
    if base_cf is not None and growth_rates and wacc is not None:
        if params.get("terminal_g") is None:
            return {"error": "terminal_g is required (the silent default was removed in Phase 4)"}
        result["dcf_model"] = unbundled_dcf(
            base_cf=float(base_cf),
            growth_rates=[float(g) for g in growth_rates],
            wacc=float(wacc),
            terminal_g=float(params["terminal_g"]),
            terminal_exit_multiple=float(params["terminal_exit_multiple"]) if params.get("terminal_exit_multiple") else None,
            annuity_flow=float(params.get("annuity_flow", 0.0)),
            annuity_cap_rate=float(params["annuity_cap_rate"]) if params.get("annuity_cap_rate") else None,
            net_debt=top_net_debt,
            shares_diluted=top_shares,
            fade_years=fade_years,
            valuation_frame=val_frame,
            rate_type=rate_type,
            sector_multiple_band=sector_multiple_band,
            sbc_treatment=sbc_treatment,
            sbc_dilution=sbc_dilution,
        )
        if result["dcf_model"].get("error"):
            return {"error": result["dcf_model"]["error"]}

    # 3. Reverse DCF expectations gap if parameters supplied (or inferred from Base scenario)
    rev_cf = base_cf or (scenarios[0].get("base_cf") if scenarios else None)
    rev_wacc = wacc or (scenarios[0].get("wacc") if scenarios else None)
    if price > 0 and top_shares > 0 and rev_cf is not None and rev_wacc is not None:
        term_g = params.get("terminal_g") or (scenarios[0].get("terminal_g") if scenarios else None)
        if term_g is not None:
            result["reverse_dcf"] = reverse_dcf_expectations_gap(
                current_price=price,
                shares_diluted=top_shares,
                base_cf=float(rev_cf),
                wacc=float(rev_wacc),
                terminal_g=float(term_g),
                demonstrated_cagr_5y=float(params["demonstrated_cagr_5y"]) if params.get("demonstrated_cagr_5y") is not None else None,
            )

    # 4. Continuous Kelly sizing and Payoff Skew if scenarios have valid IVs and probs
    valid_scenarios = [s for s in scenarios if s.get("iv") is not None and s.get("prob") is not None]
    if price > 0 and valid_scenarios:
        result["kelly_sizing"] = continuous_multi_outcome_kelly(
            price=price,
            outcomes=valid_scenarios,
            position_cap_pct=float(params.get("position_cap_pct", 25.0)),
        )
        base_iv = next((s["iv"] for s in valid_scenarios if "base" in str(s.get("name", "")).lower()), None)
        bull_iv = next((s["iv"] for s in valid_scenarios if "bull" in str(s.get("name", "")).lower()), None)
        bear_iv = next((s["iv"] for s in valid_scenarios if "bear" in str(s.get("name", "")).lower()), None)
        if base_iv is not None and bull_iv is not None and bear_iv is not None:
            result["payoff_skew"] = calculate_payoff_skew(float(base_iv), float(bull_iv), float(bear_iv), price)

    return result


def format_model_results_markdown(res: Dict[str, Any]) -> str:
    """Format the financial model calculation into a clean markdown table for Qwen."""
    lines = ["### FINANCIAL MODELING DESK REPORT (Deterministic Python Verification)\n"]
    price = res.get("price", 0.0)

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
        if "per_share_iv_exit" in d and d.get("per_share_iv_exit") is not None:
            lines.append(f"  * Gordon Terminal Leg: **${d.get('per_share_iv_gordon')}** (implied terminal multiple: {d.get('implied_terminal_ev_fcf_gordon')}x EV/FCF, TV share: {d.get('gordon_terminal', {}).get('terminal_share_of_value', 0)*100:.1f}%)")
            lines.append(f"  * Exit Multiple Leg: **${d.get('per_share_iv_exit')}** ({d.get('terminal_method')}, TV share: {d.get('terminal_share_of_value_exit', 0)*100:.1f}%)")
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

    if "reverse_dcf" in res and not res["reverse_dcf"].get("error"):
        r = res["reverse_dcf"]
        lines.append("**Reverse DCF Expectations Gap (What's Priced in at T0):**")
        lines.append(f"- Implied 5-Year Growth: **{r['implied_growth_next_5y_pct']:+.1f}%**")
        if "expectations_gap_pts" in r:
            lines.append(f"- Demonstrated 5Y Historical CAGR: {r['demonstrated_cagr_5y_pct']:+.1f}% -> Expectations Gap: **{r['expectations_gap_pts']:+.1f} points**")
            lines.append(f"- Assessment: *{r['assessment']}*\n")

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
