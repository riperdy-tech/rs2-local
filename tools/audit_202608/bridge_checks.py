#!/usr/bin/env python3
"""bridge_checks.py - the deterministic checks of the revision 25 normalization bridge (desk schema 25.1).

Spec: stocks-workspace/docs/review_2026-09-22/rev23/SPEC_rev25_normalization_bridge.md section 5 (Stage 0.3).

Every check is a pure function of plain numbers, lists and strings. None writes to an input, none clamps, overwrites or re-labels a
declared value, and none reads a tolerance from anywhere but BRIEF_TOLERANCES below. Each returns
    {"id", "status": "pass" | "fail" | "not_computable", "declared", "derived", "horizon", "tolerance"}
(plus a "note" saying why a check is not computable or what failed). The desk turns a fail into a reason request
(`bridge_<id>_reason`, financial_model_tool) and annotates the result `reason_given`; it never changes the value.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

# Stage 0.3 placeholders. Every value is UNCALIBRATED: Stage 0.4 replaces them, and nothing may read a tolerance from anywhere else.
BRIDGE_TOLERANCES: Dict[str, float] = {
    "tau_m_y1_5": 0.03,      # UNCALIBRATED: margin points, years 1-5 (C1, C1b, C2 mid)
    "tau_m_y6_10": 0.03,     # UNCALIBRATED: margin points, years 6-10
    "tau_m_y11_plus": 0.03,  # UNCALIBRATED: margin points, years after 10 (a fade longer than 5 years)
    "tau_R_T5": 0.10,        # UNCALIBRATED: relative revenue gap at T = 5 (C3)
    "tau_R_TH": 0.10,        # UNCALIBRATED: relative revenue gap at T = H, 1 <= H <= 4, cyclical revenue (C3)
    "tau_b": 0.01,           # UNCALIBRATED: margin points, the basis test (C5)
}

KNOWN_FLAGS = ("cyclical", "structural_growth", "structural_decline", "turnaround")
CHECK_IDS = ("C1", "C1b", "C2", "C3", "C4", "C5")


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def tau_m(t: int) -> float:
    """The margin tolerance at year t, by horizon band."""
    if t <= 5:
        return BRIDGE_TOLERANCES["tau_m_y1_5"]
    if t <= 10:
        return BRIDGE_TOLERANCES["tau_m_y6_10"]
    return BRIDGE_TOLERANCES["tau_m_y11_plus"]


def _res(cid: str, status: str, declared: Any, derived: Any, horizon: Any, tolerance: Any, note: Optional[str] = None) -> Dict[str, Any]:
    out = {"id": cid, "status": status, "declared": declared, "derived": derived, "horizon": horizon, "tolerance": tolerance}
    if note is not None:
        out["note"] = note
    return out


def _nc(cid: str, declared: Any, note: str) -> Dict[str, Any]:
    return _res(cid, "not_computable", declared, None, None, None, note)


def margin_path(margins_1_5: Sequence[float], long_run_margin: float, fade_years: int) -> List[float]:
    """m_1..m_5 as declared, then m_t = m_5 (1 + (margin_ratio - 1)(t - 5)/F) for t = 6..5+F, margin_ratio = long_run_margin / m_5
    (spec section 5). With F = 0 the path is the five declared margins."""
    m = [float(x) for x in margins_1_5]
    F = int(fade_years)
    if F > 0 and m[4] != 0:
        ratio = float(long_run_margin) / m[4]
        m += [m[4] * (1.0 + (ratio - 1.0) * (t - 5) / F) for t in range(6, 6 + F)]
    return m


def check_c1(path: Sequence[float], m_N: float, H: int) -> Dict[str, Any]:
    """C1 (primary): for each t from max(H, 1) to 5+F, |m_t - m_N| <= tau_m(t). `path` is the margin path m_1..m_{5+F}. The result
    reports the year with the largest gap in tolerance units."""
    declared = {"normalized_margin": m_N, "normalization_horizon": H}
    if not (_num(m_N) and isinstance(H, int) and not isinstance(H, bool) and path and all(_num(x) for x in path)):
        return _nc("C1", declared, "normalized_margin, normalization_horizon or the margin path is not a number")
    lo = max(H, 1)
    if lo > len(path):
        return _nc("C1", declared, "the normalization horizon is beyond the end of the margin path")
    worst_t, worst_ratio, worst_gap = None, -1.0, None
    fail = False
    for t in range(lo, len(path) + 1):
        gap = abs(path[t - 1] - m_N)
        tol = tau_m(t)
        if gap > tol:
            fail = True
        if gap / tol > worst_ratio:
            worst_t, worst_ratio, worst_gap = t, gap / tol, gap
    return _res("C1", "fail" if fail else "pass", m_N, path[worst_t - 1], worst_t, tau_m(worst_t),
                f"largest gap {worst_gap:.4f} at year {worst_t}, over years {lo}-{len(path)}")


def check_c1b(long_run_margin: float, m_N: float, fade_years: int) -> Dict[str, Any]:
    """C1b: |long_run_margin - m_N| <= tau_m(5+F); a fail asks why the margin moves again after normalizing."""
    declared = {"normalized_margin": m_N, "long_run_margin": long_run_margin}
    if not (_num(m_N) and _num(long_run_margin) and isinstance(fade_years, int) and not isinstance(fade_years, bool)):
        return _nc("C1b", declared, "normalized_margin, long_run_margin or fade_years is not a number")
    T = 5 + fade_years
    tol = tau_m(T)
    return _res("C1b", "fail" if abs(long_run_margin - m_N) > tol else "pass", m_N, long_run_margin, T, tol)


def check_c2(cycle_position: Any, m_N: float, m_0: float) -> Dict[str, Any]:
    """C2: peak => m_N <= m_0; trough => m_N >= m_0; mid => |m_N - m_0| <= tau_m(1). Other positions have no rule."""
    declared = {"cycle_position": cycle_position, "normalized_margin": m_N}
    if not (_num(m_N) and _num(m_0)):
        return _nc("C2", declared, "normalized_margin or the current margin is not a number")
    pos = cycle_position.strip().lower() if isinstance(cycle_position, str) else None
    if pos == "peak":
        return _res("C2", "pass" if m_N <= m_0 else "fail", m_N, m_0, 0, None, "peak: m_N must not exceed today's margin")
    if pos == "trough":
        return _res("C2", "pass" if m_N >= m_0 else "fail", m_N, m_0, 0, None, "trough: m_N must not be below today's margin")
    if pos == "mid":
        tol = tau_m(1)
        return _res("C2", "pass" if abs(m_N - m_0) <= tol else "fail", m_N, m_0, 0, tol, "mid: m_N within tolerance of today's margin")
    if pos == "not_cyclical":
        return _nc("C2", declared, "cycle_position not_cyclical: the check has no rule")
    return _nc("C2", declared, "no cycle_position was declared in the desk call")


def check_c3(revenue: Sequence[float], R_N0: Optional[float], g_S: float, H: int) -> Dict[str, Any]:
    """C3: at T = 5, and also at T = H when 1 <= H <= 4 and R_N0 != R_0: |R_T / (R_N0 (1+g_S)^T) - 1| <= tau_R(T). `revenue` is R_0..R_5;
    R_N0 None is R_0."""
    declared = {"structural_growth": g_S, "normalized_revenue_base": R_N0}
    if not (len(revenue) == 6 and all(_num(x) for x in revenue) and _num(g_S) and isinstance(H, int) and not isinstance(H, bool)):
        return _nc("C3", declared, "the revenue path, structural_growth or the horizon is not a number")
    base = float(revenue[0]) if R_N0 is None else R_N0
    if not (_num(base) and base > 0 and 1.0 + g_S > 0):
        return _nc("C3", declared, "normalized revenue base is not positive")
    points = [(5, BRIDGE_TOLERANCES["tau_R_T5"])]
    if 1 <= H <= 4 and base != revenue[0]:
        points.append((H, BRIDGE_TOLERANCES["tau_R_TH"]))
    fail, worst = False, None
    for T, tol in points:
        normal = base * (1.0 + g_S) ** T
        gap = abs(revenue[T] / normal - 1.0)
        if gap > tol:
            fail = True
        if worst is None or gap / tol > worst[3] / worst[2]:
            worst = (T, normal, tol, gap)
    T, normal, tol, gap = worst
    return _res("C3", "fail" if fail else "pass", normal, revenue[T], T, tol, f"largest relative gap {gap:.4f} at year {T}")


def _evidence_present(v: Any) -> bool:
    return v is not None and str(v).strip() != "" and str(v).strip().lower() not in ("null", "none")


def check_c4(flags: Any, g_S: float, g_rev: Optional[float], m_N: float, m_0: float, H: int, cycle_evidence: Any) -> Dict[str, Any]:
    """C4: the flags against the declarations. Exact, no tolerance. structural_decline => g_S < 0; structural_growth => g_S > g_rev;
    turnaround => m_N > m_0 and H >= 1; cyclical => cycle_evidence present; no flag => H = 0."""
    declared = {"flags": list(flags) if isinstance(flags, (list, tuple)) else flags, "structural_growth": g_S, "normalized_margin": m_N,
                "normalization_horizon": H}
    if not (isinstance(flags, (list, tuple)) and all(isinstance(f, str) for f in flags) and _num(g_S) and _num(m_N)
            and isinstance(H, int) and not isinstance(H, bool)):
        return _nc("C4", declared, "flags, structural_growth, normalized_margin or the horizon is not readable")
    fl = [f.strip().lower() for f in flags]
    violations, unknown = [], []
    if "structural_decline" in fl and not g_S < 0:
        violations.append("structural_decline needs structural_growth below 0")
    if "structural_growth" in fl:
        if _num(g_rev):
            if not g_S > g_rev:
                violations.append(f"structural_growth needs structural_growth above the record's revenue trend {g_rev:.4f}")
        else:
            unknown.append("the record's revenue trend (g_rev) is not in the facts")
    if "turnaround" in fl:
        if not _num(m_0):
            unknown.append("today's margin is not in the facts")
        elif not (m_N > m_0 and H >= 1):
            violations.append("turnaround needs normalized_margin above today's margin and normalization_horizon of 1 or more")
    if "cyclical" in fl and not _evidence_present(cycle_evidence):
        violations.append("cyclical needs cycle_evidence")
    if not fl and H != 0:
        violations.append("no flag, yet normalization_horizon is not 0")
    status = "fail" if violations else ("not_computable" if unknown else "pass")
    return _res("C4", status, declared, {"violations": violations, "not_computable": unknown}, H, None,
                "; ".join(violations or unknown) or None)


def check_c5(declared_margins: Dict[str, Any], operating_facts: Dict[str, Any], x_facts: Dict[str, Any]) -> Dict[str, Any]:
    """C5: a declared margin within tau_b of an operating-basis fact (om_tc, om_L, om_trend) and outside tau_b of every X-basis one (m_tc, x_L,
    m5) draws a basis question. Never a rejection. `declared_margins` maps a field name to its value."""
    tol = BRIDGE_TOLERANCES["tau_b"]
    ops = {k: v for k, v in operating_facts.items() if _num(v)}
    xs = {k: v for k, v in x_facts.items() if _num(v)}
    declared = {k: v for k, v in declared_margins.items() if _num(v)}
    if not declared or not ops or not xs:
        return _nc("C5", dict(declared_margins), "no declared margin, no operating-basis fact or no X-basis fact to compare")
    hits = []
    for name, v in declared.items():
        near_op = [k for k, f in ops.items() if abs(v - f) <= tol]
        if near_op and all(abs(v - f) > tol for f in xs.values()):
            nearest_x = min(xs.items(), key=lambda kv: abs(v - kv[1]))
            hits.append({"field": name, "value": v, "operating_fact": near_op[0], "operating_value": ops[near_op[0]],
                         "nearest_x_fact": nearest_x[0], "nearest_x_value": nearest_x[1]})
    return _res("C5", "fail" if hits else "pass", declared, hits, 0, tol,
                "; ".join(f"{h['field']} {h['value']:.4f} matches the operating-basis {h['operating_fact']} {h['operating_value']:.4f}, "
                          f"the X-basis {h['nearest_x_fact']} is {h['nearest_x_value']:.4f}" for h in hits) or None)


def run_checks(*, margins_1_5, long_run_margin, fade_years, m_N, H, m_0, revenue, R_N0, g_S, flags, g_rev=None, cycle_position=None,
               cycle_evidence=None, operating_facts=None, x_facts=None) -> List[Dict[str, Any]]:
    """C1, C1b, C2, C3, C4 and C5 for one scenario, in that order. Reads its arguments only."""
    path = margin_path(margins_1_5, long_run_margin, fade_years)
    declared_margins = {f"earnings_margin[{i + 1}]": v for i, v in enumerate(margins_1_5)}
    declared_margins["normalized_margin"] = m_N
    declared_margins["long_run_margin"] = long_run_margin
    return [check_c1(path[:5] if fade_years == 0 else path, m_N, H), check_c1b(long_run_margin, m_N, fade_years),
            check_c2(cycle_position, m_N, m_0), check_c3(revenue, R_N0, g_S, H),
            check_c4(flags, g_S, g_rev, m_N, m_0, H, cycle_evidence),
            check_c5(declared_margins, operating_facts or {}, x_facts or {})]
