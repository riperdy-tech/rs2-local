#!/usr/bin/env python3
"""valuation_engine.py — deterministic valuation primitives.

After the architecture inversion (AUDIT.md C2), the heavy lifting lives in
valuation_backbone.py (the reverse-DCF that owns base_cf/growth/WACC). This module is now
just the small shared math:

  - dcf_value     : two-stage FCF DCF (identical to lib/dcf.ts) — used by the backbone's
                    implied-growth solver.
  - engine2_cycle : normalized EPS × through-cycle multiple — for FINANCIALS the backbone
                    can't DCF (the model supplies the two numbers).
  - engine4_bridge: option bridge core + Σ(prob×value) − drag — for PRE-PROFIT / option-led
                    names with no earning power to capitalize (the model supplies the legs).

The old forward-DCF machinery (compute_valuation / scenario_iv / validate_scenario / engineN /
weight_scenarios / reconcile_to_band / consensus anchor) was REMOVED — it let the 3B model guess
base_cf/growth/WACC and bandaged the blow-ups with consensus. See AUDIT.md and git history.
"""


# ── two-stage FCF DCF (port of lib/dcf.ts dcfValue) ────────────────────────
def dcf_value(base_cf, growth, wacc, terminal_growth=0.025,
              stage1_years=5, fade_years=5):
    """PV of a two-stage FCF stream: stage-1 constant growth, linear fade to terminal,
    Gordon terminal value. Returns None when wacc <= terminal_growth."""
    if wacc <= terminal_growth:
        return None
    pv = 0.0
    cf = float(base_cf)
    year = 0
    for _ in range(stage1_years):
        year += 1
        cf *= 1 + growth
        pv += cf / (1 + wacc) ** year
    for i in range(1, fade_years + 1):
        year += 1
        g_t = growth + (terminal_growth - growth) * i / fade_years
        cf *= 1 + g_t
        pv += cf / (1 + wacc) ** year
    terminal = (cf * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv += terminal / (1 + wacc) ** year
    return pv


# ── Engine 2 — cycle / financial multiple (per share) ──────────────────────
def engine2_cycle(normalized_eps, normal_multiple, replacement_floor=None):
    """Normalized mid-cycle EPS × through-cycle multiple, optionally floored at an
    asset/replacement value. Per share. Used for FINANCIALS the backbone cannot DCF."""
    iv = float(normalized_eps) * float(normal_multiple)
    if replacement_floor is not None:
        iv = max(iv, float(replacement_floor))
    return iv


# ── Engine 4 — expectation-driven option bridge (per share) ────────────────
def engine4_bridge(core_value, options, drag=0.0):
    """IV = proven core ($/share) + Σ(success_prob × success_value/share) − execution drag.
    The model supplies the judgments; Python sums. For PRE-PROFIT / option-led names with no
    earning power to capitalize. prob clamped to [0,1]."""
    opt = 0.0
    for o in options or []:
        p = float(o.get("prob", 0))
        v = float(o.get("value", 0))
        opt += max(0.0, min(1.0, p)) * v
    return float(core_value) + opt - float(drag or 0.0)
