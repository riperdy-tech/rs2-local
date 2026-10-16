#!/usr/bin/env python3
"""bridge_checks.py - the deterministic checks of the revision 25 normalization bridge (desk schema 25.1).

Spec: stocks-workspace/docs/review_2026-09-22/rev23/SPEC_rev25_normalization_bridge.md section 5 (Stage 0.3).

Every check is a pure function of plain numbers, lists and strings. None writes to an input, none clamps, overwrites or re-labels a
declared value, and none reads a tolerance from anywhere but BRIDGE_TOLERANCES below. Every tolerance comparison allows EPS (1e-12)
so a deviation equal to a tolerance written in decimals passes, as the coordinator's reference checks do (Stage 0.3 audit). Each returns
    {"id", "status": "pass" | "fail" | "not_computable", "declared", "derived", "horizon", "tolerance"}
(plus a "note" saying why a check is not computable or what failed). The desk turns a fail into a reason request
(`bridge_<id>_reason`, financial_model_tool) and annotates the result `reason_given`; it never changes the value.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

# FROZEN 2026-10-16 (Stage 0.4 step 5): the values below are registered and may not change after Stage 1 starts. Chosen by the rule in
# scratch/rev23/r25_synth/CALIBRATION_PROTOCOL.md (sha256 acb2619c...), fixed before the pilot labels (PILOT_LABELS.md, 095e22d5...): every labelled
# pilot company was coherent at a C1 gap of 0, so the pilot did not bound tau_m and the registered prior decides; tau_R and tau_b are priors (the pilot
# holds no revenue or basis declarations). The level is validated only on Kohl's, Heritage and the sealed Stage 2 names, never retuned before Stage 2.
BRIDGE_TOLERANCES: Dict[str, float] = {
    "tau_m_y1_5": 0.03,      # margin points, years 1-5 (C1, C1b, C2 mid)
    "tau_m_y6_10": 0.03,     # margin points, years 6-10 (one value with years 1-5: no evidence separates the bands)
    "tau_m_y11_plus": 0.03,  # margin points, years after 10 (a fade longer than 5 years)
    "tau_R_T5": 0.10,        # relative revenue gap at T = 5 (C3): about 2 points of annual growth over five years
    "tau_R_TH": 0.10,        # relative revenue gap at T = H, 1 <= H <= 4, cyclical revenue (C3)
    "tau_b": 0.01,           # margin points, the basis test (C5)
    "tau_g": 0.02,           # growth-rate change, the K1 steady band: a registered prior, frozen with spec v1.2 (no pilot fitting)
}

EPS = 1e-12                # the float allowance on every tolerance comparison (a tie passes)
KNOWN_FLAGS = ("cyclical", "structural_growth", "structural_decline", "turnaround")
CHECK_IDS = ("C1", "C1b", "C2", "C3", "C4", "C5")
CLASS_CHECK_IDS = ("K1", "K2", "K3", "K4")
GROWTH_TRAJECTORIES = ("accelerating", "steady", "decelerating", "shrinking")
CYCLE_POSITIONS = ("peak", "mid", "trough", "not_cyclical")
MARGIN_PERSISTENCES = ("structural", "partly_structural", "transient")


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
        if gap > tol + EPS:
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
    return _res("C1b", "fail" if abs(long_run_margin - m_N) > tol + EPS else "pass", m_N, long_run_margin, T, tol)


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
        return _res("C2", "pass" if abs(m_N - m_0) <= tol + EPS else "fail", m_N, m_0, 0, tol, "mid: m_N within tolerance of today's margin")
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
        if gap > tol + EPS:
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
        near_op = [k for k, f in ops.items() if abs(v - f) <= tol + EPS]
        if near_op and all(abs(v - f) > tol + EPS for f in xs.values()):
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
    # C5 reads the two normalization margins only (the Stage 0.3 audit, ruling 2 of 0.4 step 3): a near-term margin that sits on an operating
    # figure is not a basis claim, and reading m_1..m_5 raised the question on coherent paths
    declared_margins = {"normalized_margin": m_N, "long_run_margin": long_run_margin}
    return [check_c1(path[:5] if fade_years == 0 else path, m_N, H), check_c1b(long_run_margin, m_N, fade_years),
            check_c2(cycle_position, m_N, m_0), check_c3(revenue, R_N0, g_S, H),
            check_c4(flags, g_S, g_rev, m_N, m_0, H, cycle_evidence),
            check_c5(declared_margins, operating_facts or {}, x_facts or {})]


# ---- Stage 0.5 classification checks K1-K4 (spec v1.2). Pure; they read labels and numbers and never change a label. K2 and K3 reuse tau_m_y1_5.
def _lab(v: Any) -> Optional[str]:
    return v.strip().lower() if isinstance(v, str) else None


def check_k1(growth_trajectory: Any, revenue: Sequence[float]) -> Dict[str, Any]:
    """K1: growth_trajectory against delta = mean(g4, g5) - mean(g1, g2), g_t = R_t / R_(t-1) - 1; accelerating: delta > tau_g; decelerating:
    delta < -tau_g; steady: |delta| <= tau_g; shrinking: the 5-year revenue CAGR < 0. `revenue` is R_0..R_5."""
    declared = {"growth_trajectory": growth_trajectory}
    lab = _lab(growth_trajectory)
    if lab is None or lab not in GROWTH_TRAJECTORIES:
        return _nc("K1", declared, "no valid growth_trajectory was declared in the desk call")
    if not (len(revenue) == 6 and all(_num(x) for x in revenue) and all(x > 0 for x in revenue)):
        return _nc("K1", declared, "the revenue path R_0..R_5 is not positive numbers")
    tol = BRIDGE_TOLERANCES["tau_g"]
    g = [revenue[t] / revenue[t - 1] - 1.0 for t in range(1, 6)]
    delta = (g[3] + g[4]) / 2.0 - (g[0] + g[1]) / 2.0
    cagr = (revenue[5] / revenue[0]) ** 0.2 - 1.0
    if lab == "shrinking":
        return _res("K1", "pass" if cagr < 0 else "fail", lab, cagr, 5, None, f"shrinking: the 5-year revenue CAGR {cagr:.4f} must be below 0")
    if lab == "accelerating":
        ok = delta > tol + EPS
    elif lab == "decelerating":
        ok = delta < -tol - EPS
    else:
        ok = abs(delta) <= tol + EPS
    return _res("K1", "pass" if ok else "fail", lab, delta, 5, tol, f"growth change {delta:+.4f} (mean g4,g5 less mean g1,g2); 5-year CAGR {cagr:.4f}")


def check_k2(cycle_position: Any, m_0: Any, m_tc: Any) -> Dict[str, Any]:
    """K2: cycle_position against d = m_0 - m_tc (today's margin less the record's through-cycle margin); peak: d >= tau_m; trough: d <= -tau_m;
    mid: |d| <= tau_m; not_cyclical: no rule. Margins only."""
    declared = {"cycle_position": cycle_position}
    lab = _lab(cycle_position)
    if lab is None or lab not in CYCLE_POSITIONS:
        return _nc("K2", declared, "no valid cycle_position was declared in the desk call")
    if lab == "not_cyclical":
        return _nc("K2", declared, "cycle_position not_cyclical: the check has no rule")
    if not (_num(m_0) and _num(m_tc)):
        return _nc("K2", declared, "today's margin or the record's through-cycle margin (m_tc) is not in the facts")
    tol, d = BRIDGE_TOLERANCES["tau_m_y1_5"], m_0 - m_tc
    ok = d >= tol - EPS if lab == "peak" else (d <= -tol + EPS if lab == "trough" else abs(d) <= tol + EPS)
    return _res("K2", "pass" if ok else "fail", lab, d, 0, tol, f"m_0 {m_0:.4f} less m_tc {m_tc:.4f} = {d:+.4f}")


def check_k3(margin_persistence: Any, long_run_margin: Any, m_0: Any, m_tc: Any) -> Dict[str, Any]:
    """K3: margin_persistence against L = long_run_margin relative to m_0 and m_tc. |m_0 - m_tc| <= tau_m: not distinguishable, a pass. structural:
    |L - m_0| <= |L - m_tc| + tau_m; transient: |L - m_tc| <= |L - m_0| + tau_m; partly_structural: L between m_tc and m_0, tau_m allowed at each end."""
    declared = {"margin_persistence": margin_persistence}
    lab = _lab(margin_persistence)
    if lab is None or lab not in MARGIN_PERSISTENCES:
        return _nc("K3", declared, "no valid margin_persistence was declared in the desk call")
    if not (_num(long_run_margin) and _num(m_0) and _num(m_tc)):
        return _nc("K3", declared, "long_run_margin, today's margin or the record's through-cycle margin (m_tc) is not a number")
    tol, L = BRIDGE_TOLERANCES["tau_m_y1_5"], long_run_margin
    if abs(m_0 - m_tc) <= tol + EPS:
        return _res("K3", "pass", lab, L, 0, tol, "not distinguishable: today's margin is within tolerance of the record's through-cycle margin")
    if lab == "structural":
        ok = abs(L - m_0) <= abs(L - m_tc) + tol + EPS
    elif lab == "transient":
        ok = abs(L - m_tc) <= abs(L - m_0) + tol + EPS
    else:
        ok = min(m_0, m_tc) - tol - EPS <= L <= max(m_0, m_tc) + tol + EPS
    return _res("K3", "pass" if ok else "fail", lab, L, 0, tol, f"L {L:.4f}, m_0 {m_0:.4f}, m_tc {m_tc:.4f}")


def check_k4(growth_trajectory: Any, terminal_g: Any, g_S: Any) -> Dict[str, Any]:
    """K4: growth_trajectory shrinking => terminal_g <= 0 and structural_growth < 0; each breach is reported separately."""
    declared = {"growth_trajectory": growth_trajectory, "terminal_g": terminal_g, "structural_growth": g_S}
    lab = _lab(growth_trajectory)
    if lab is None or lab not in GROWTH_TRAJECTORIES:
        return _nc("K4", declared, "no valid growth_trajectory was declared in the desk call")
    if lab != "shrinking":
        return _nc("K4", declared, "growth_trajectory is not shrinking: the check has no rule")
    breaches, unknown = [], []
    if not _num(terminal_g):
        unknown.append("terminal_g is not a number")
    elif not terminal_g <= 0:
        breaches.append(f"shrinking needs terminal_g at or below 0, got {terminal_g:.4f}")
    if not _num(g_S):
        unknown.append("structural_growth is not a number")
    elif not g_S < 0:
        breaches.append(f"shrinking needs structural_growth below 0, got {g_S:.4f}")
    status = "fail" if breaches else ("not_computable" if unknown else "pass")
    return _res("K4", status, declared, {"breaches": breaches, "not_computable": unknown}, 0, None, "; ".join(breaches or unknown) or None)


def run_class_checks(*, growth_trajectory=None, cycle_position=None, margin_persistence=None, revenue, long_run_margin, m_0, m_tc,
                     terminal_g=None, g_S=None) -> List[Dict[str, Any]]:
    """K1-K4 for the Base, in that order. A sibling of run_checks (the class checks read the Base only). Reads its arguments only."""
    return [check_k1(growth_trajectory, revenue), check_k2(cycle_position, m_0, m_tc),
            check_k3(margin_persistence, long_run_margin, m_0, m_tc), check_k4(growth_trajectory, terminal_g, g_S)]
