"""r26_forecast.py - revision 26 (SPEC_rev26_staged_analyst.md sections 2 and 3): the stage-2 forecast, as pure functions.

What is here, in the order the spec uses it:
  validate_forecast   structure only: fields, finiteness, enums, fact IDs present in the dossier. Numbers are never bounded.
  build_path          years of revenue growth and operating margin from the model's near term, its normalized state and its transition.
  bridge_to_x         the operating margin of each year on the desk's X basis (net income + after-tax amortization, over revenue), as a table
                      with its inputs; invert_bridge goes back (the operating-basis equivalent of an X margin, for the consensus).
  value_forecast      feeds the X-margin path and revenue to the existing desk (execute_financial_model, desk schema 25.2). Nothing of the DCF
                      is re-implemented here, and no existing desk code is touched: every existing desk result is unchanged by this module.
  alt_paths           the alternative path after a fact's evidence expires (SPEC section 2, step 4). Reported, never substituted.
  aggregate           the K = 3 samples: the median index (Base value), spread = (max - min) / median.
  direction_split     whether the samples straddle the verdict boundary, by the existing band rule.
  pull_ratio          stage 3's movement toward the revealed consensus.

Rules kept throughout: no model, no I/O, no clock, no random; a missing figure is stated, never defaulted; 0.0 is a value (no `or` on a number);
nothing is clamped or refused on its size; every assumption is stamped on the result that used it.

Units. Margins and growth rates are decimals (0.12 = 12%). `delta_pts` is in PERCENTAGE POINTS (2.5 = +0.025), as its name says; DELTA_PTS_SCALE is
the one place that converts. Dollar quantities (revenue, net interest, amortization) share one unit, whatever it is.

The forecast object:
  {"discount_rate": r, "frame": "equity" | "firm",
   "scenarios": {"Base": SC, "Bull": SC, "Bear": SC}}
  SC = {"near_term": {"rev_growth": [g1, g2], "op_margin": [m1, m2], "fact_ids": [...]},
        "normalized": {"year": N, "rev_growth": gN, "baseline": "min|p25|median|p75|max|last", "delta_pts": d, "fact_ids": [...], "reason": "..."},
        "transition": "linear" | "step_at_year" | "hold_then_linear", "transition_year": k,
        "long_run_margin_op": L, "terminal_g": gT, "terminal_ronic": ronic, "fade_years": F, "prob": p,
        "long_run_fact_ids": [...]}                 # optional: the facts behind long_run_margin_op (SPEC step 4 names them; see alt_paths)
The operating-margin bar: {"min", "p25", "median", "p75", "max", "last"} as decimals (SPEC section 5), plus anything else it carries.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Sequence

BASELINES = ("min", "p25", "median", "p75", "max", "last")
TRANSITIONS = ("linear", "step_at_year", "hold_then_linear")
FRAMES = ("equity", "firm")
SCENARIOS = ("Base", "Bull", "Bear")
DELTA_PTS_SCALE = 0.01                  # delta_pts is in percentage points
NEAR_TERM_YEARS = 2
MAX_REASON_WORDS = 60                   # SPEC section 2: "reason": "<= 60 words>"
HORIZON = 5                             # the desk's explicit years (25.2 path arithmetic: five years, then the fade)
DESK_SCHEMA = "25.2"
BRIDGE_OK = "ok"
UNAVAILABLE_TAX = "bridge_unavailable_tax"
UNAVAILABLE_INTEREST = "bridge_unavailable_net_interest"
UNAVAILABLE_AMORTIZATION = "bridge_unavailable_amortization"
UNAVAILABLE_REVENUE = "bridge_unavailable_revenue"


def _num(v: Any) -> bool:
    """A finite number that is not a bool. 0.0 is a number."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v: Any) -> bool:
    return _num(v) and float(v).is_integer()


# ---- 1. validation: structure only ---------------------------------------------------------------------------------------------------------------

def dossier_fact_ids(dossier: Optional[Dict[str, Any]]) -> set:
    """Every fact ID in the dossier (usable or not: a fact that exists is citable; its status is shown to the model, and nothing here gates on it)."""
    return {f.get("fact_id") for f in ((dossier or {}).get("facts") or []) if isinstance(f, dict) and isinstance(f.get("fact_id"), str)}


def _fact_ids_problems(where: str, v: Any, known: Optional[set], out: List[Dict[str, str]]) -> None:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        out.append({"field": where, "problem": "not_a_list_of_fact_ids"})
        return
    if known is not None:
        missing = [x for x in v if x not in known]
        if missing:
            out.append({"field": where, "problem": "fact_id_not_in_dossier", "detail": ", ".join(missing)})


def _numbers_problem(where: str, v: Any, n: int, out: List[Dict[str, str]]) -> None:
    if not (isinstance(v, (list, tuple)) and len(v) == n):
        out.append({"field": where, "problem": f"not_a_list_of_{n}_numbers"})
    elif not all(_num(x) for x in v):
        out.append({"field": where, "problem": "not_finite_numbers"})


def validate_scenario(sc: Any, label: str, known: Optional[set]) -> List[Dict[str, str]]:
    """The structure problems of one scenario, each {"field", "problem"[, "detail"]}. Empty means structurally valid."""
    out: List[Dict[str, str]] = []
    if not isinstance(sc, dict):
        return [{"field": label, "problem": "missing_or_not_an_object"}]
    p = f"{label}."
    nt = sc.get("near_term")
    if not isinstance(nt, dict):
        out.append({"field": p + "near_term", "problem": "missing_or_not_an_object"})
    else:
        _numbers_problem(p + "near_term.rev_growth", nt.get("rev_growth"), NEAR_TERM_YEARS, out)
        _numbers_problem(p + "near_term.op_margin", nt.get("op_margin"), NEAR_TERM_YEARS, out)
        _fact_ids_problems(p + "near_term.fact_ids", nt.get("fact_ids"), known, out)
    F = sc.get("fade_years")
    if not (_int(F) and F >= 0):
        out.append({"field": p + "fade_years", "problem": "not_a_whole_number_of_years"})
    nm = sc.get("normalized")
    N = None
    if not isinstance(nm, dict):
        out.append({"field": p + "normalized", "problem": "missing_or_not_an_object"})
    else:
        N = nm.get("year")
        if not _int(N):
            out.append({"field": p + "normalized.year", "problem": "not_a_whole_number"})
            N = None
        elif N < 3 or (_int(F) and F >= 0 and N > 5 + F):          # SPEC: N is 3..5+F (a year index, not a bounded estimate)
            out.append({"field": p + "normalized.year", "problem": "year_outside_3_to_5_plus_fade_years"})
        for k in ("rev_growth", "delta_pts"):
            if not _num(nm.get(k)):
                out.append({"field": p + f"normalized.{k}", "problem": "not_a_finite_number"})
        if nm.get("baseline") not in BASELINES:
            out.append({"field": p + "normalized.baseline", "problem": "not_one_of_" + "|".join(BASELINES)})
        _fact_ids_problems(p + "normalized.fact_ids", nm.get("fact_ids"), known, out)
        r = nm.get("reason")
        if not (isinstance(r, str) and r.strip()):
            out.append({"field": p + "normalized.reason", "problem": "missing_text"})
        elif len(r.split()) > MAX_REASON_WORDS:
            out.append({"field": p + "normalized.reason", "problem": f"more_than_{MAX_REASON_WORDS}_words"})
    tr = sc.get("transition")
    if tr not in TRANSITIONS:
        out.append({"field": p + "transition", "problem": "not_one_of_" + "|".join(TRANSITIONS)})
    elif tr in ("step_at_year", "hold_then_linear"):
        k = sc.get("transition_year")
        if not _int(k):
            out.append({"field": p + "transition_year", "problem": "required_whole_number_for_" + tr})
        elif k < 3 or (N is not None and k > N):
            out.append({"field": p + "transition_year", "problem": "year_outside_3_to_normalized_year"})
    for k in ("long_run_margin_op", "terminal_g", "terminal_ronic", "prob"):
        if not _num(sc.get(k)):
            out.append({"field": p + k, "problem": "not_a_finite_number"})
    if sc.get("long_run_fact_ids") is not None:
        _fact_ids_problems(p + "long_run_fact_ids", sc.get("long_run_fact_ids"), known, out)
    return out


def validate_forecast(obj: Any, dossier: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """SPEC section 2, 'Validation is structure only': the list of named problems ([] when the forecast is structurally valid).

    Checked: the fields exist and have their types; every number is finite (NaN, infinity and booleans are refused, 0.0 is accepted); the enums
    (`baseline`, `transition`, `frame`); whole-number year fields; the word count of `reason`; and, when `dossier` is given, that every cited fact ID
    exists in it. Never checked: how large or small a number is. A margin of 400% is structurally valid."""
    if not isinstance(obj, dict):
        return [{"field": "forecast", "problem": "not_an_object"}]
    out: List[Dict[str, str]] = []
    if not _num(obj.get("discount_rate")):
        out.append({"field": "discount_rate", "problem": "not_a_finite_number"})
    if obj.get("frame") not in FRAMES:
        out.append({"field": "frame", "problem": "not_one_of_" + "|".join(FRAMES)})
    scs = obj.get("scenarios")
    if not isinstance(scs, dict):
        return out + [{"field": "scenarios", "problem": "missing_or_not_an_object"}]
    known = dossier_fact_ids(dossier) if dossier is not None else None
    for name in SCENARIOS:
        out += validate_scenario(scs.get(name), name, known)
    extra = sorted(set(scs) - set(SCENARIOS))
    if extra:
        out.append({"field": "scenarios", "problem": "unknown_scenario", "detail": ", ".join(map(str, extra))})
    return out


# ---- 2. the path ---------------------------------------------------------------------------------------------------------------------------------

def normalized_margin(normalized: Dict[str, Any], op_margin_bar: Dict[str, Any]) -> Dict[str, Any]:
    """The normalized operating margin is code's sum: bar[baseline] + delta_pts x DELTA_PTS_SCALE. The model never types the result.
    {"baseline", "baseline_value", "delta", "value"} or {"status": "baseline_not_in_bar", ...} when the bar does not hold that statistic.

    Example: bar median 0.10, baseline "median", delta_pts 2.5 -> value 0.125. A delta_pts of 0.0 gives the baseline itself."""
    b = normalized.get("baseline")
    bv = (op_margin_bar or {}).get(b)
    if not _num(bv) or not _num(normalized.get("delta_pts")):
        return {"status": "baseline_not_in_bar", "baseline": b, "baseline_value": None, "delta": None, "value": None}
    d = float(normalized["delta_pts"]) * DELTA_PTS_SCALE
    return {"status": BRIDGE_OK, "baseline": b, "baseline_value": float(bv), "delta": d, "value": float(bv) + d}


def _blend(start: float, target: float, t: int, n: int, transition: str, k: Optional[int]) -> float:
    """The value in year t (t >= 3) moving from the year-2 value `start` to `target`, which is reached in year n.

    linear           start + (target - start) x (t - 2) / (n - 2)
    step_at_year k   start for t < k, target for t >= k
    hold_then_linear start through year k, then linear so that year n is the target: start + (target - start) x (t - k) / (n - k)
    A year at or after n is the target in every transition (years after N hold normalized)."""
    if t >= n:
        return target
    if transition == "linear":
        return start + (target - start) * (t - 2) / (n - 2)
    if transition == "step_at_year":
        return target if t >= int(k) else start
    if transition == "hold_then_linear":
        return start if t <= int(k) else start + (target - start) * (t - int(k)) / (n - int(k))
    raise ValueError(f"unknown transition {transition!r}")


def build_path(forecast: Dict[str, Any], op_margin_bar: Dict[str, Any], rev0: float, years: int = HORIZON) -> Dict[str, Any]:
    """Years 1..`years` of one scenario: revenue growth, operating margin and revenue. `forecast` is one scenario (SC); `rev0` the filed base-year revenue.

    Years 1 and 2 are the model's near term. Years 3..N move from the year-2 value to the normalized value (the margin to the code's normalized margin,
    the growth to the model's `normalized.rev_growth`) by the transition; years after N hold the normalized value. Growth moves exactly as the margin does.
    N may be beyond `years` (up to 5 + fade_years); the path then ends mid-transition and says so (`normalized_year_beyond_path`).

    Worked examples (year-2 margin 0.10, normalized 0.16, N = 5):
      linear                 years 3, 4, 5 -> 0.12, 0.14, 0.16   (a third of the way each year)
      step_at_year k = 4     years 3, 4, 5 -> 0.10, 0.16, 0.16   (held until the step year, then the normalized value)
      hold_then_linear k = 3 years 3, 4, 5 -> 0.10, 0.13, 0.16   (held through year 3, then linear to year 5)
    Returns {"years": [{"year", "rev_growth", "op_margin", "revenue"}], "normalized": normalized_margin(...), "normalized_year", "transition",
    "transition_year", "rev0", "stamps": [...]}; "status" is "ok", or the normalized margin's status when the baseline is not in the bar."""
    nm = forecast["normalized"]
    nrm = normalized_margin(nm, op_margin_bar)
    out: Dict[str, Any] = {"status": nrm["status"], "years": [], "normalized": nrm, "normalized_year": int(nm["year"]),
                           "transition": forecast["transition"], "transition_year": forecast.get("transition_year"), "rev0": float(rev0), "stamps": []}
    if nrm["status"] != BRIDGE_OK:
        return out
    N, tr, k = int(nm["year"]), forecast["transition"], forecast.get("transition_year")
    g = [float(x) for x in forecast["near_term"]["rev_growth"]]
    m = [float(x) for x in forecast["near_term"]["op_margin"]]
    gN, mN = float(nm["rev_growth"]), float(nrm["value"])
    rev = float(rev0)
    for t in range(1, int(years) + 1):
        if t <= NEAR_TERM_YEARS:
            gt, mt = g[t - 1], m[t - 1]
        else:
            gt = _blend(g[-1], gN, t, N, tr, k)
            mt = _blend(m[-1], mN, t, N, tr, k)
        rev = rev * (1.0 + gt)
        out["years"].append({"year": t, "rev_growth": gt, "op_margin": mt, "revenue": rev})
    if N > int(years):
        out["stamps"].append("normalized_year_beyond_path")
    return out


# ---- 3. the bridge from the operating basis to the X basis ---------------------------------------------------------------------------------------------

def _tax_ok(tau: Any) -> bool:
    return _num(tau) and tau < 1.0


def _amortization_for(year: int, facts: Dict[str, Any]) -> Dict[str, Any]:
    """A_t: the filed schedule's value for `year` when it holds one, else A_0 held (stamped). {"value", "source"} or {"value": None, "source": None}."""
    sched = facts.get("amortization_schedule")
    v = None
    if isinstance(sched, dict):
        v = sched.get(year, sched.get(str(year)))
    elif isinstance(sched, (list, tuple)) and 1 <= year <= len(sched):
        v = sched[year - 1]
    if _num(v):
        return {"value": float(v), "source": "filed_schedule"}
    a0 = facts.get("amortization_0")
    if _num(a0):
        return {"value": float(a0), "source": "base_year_held"}
    return {"value": None, "source": None}


def _bridge_inputs(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The scenario-independent inputs of the bridge, or the status naming what is not held.
    facts: {"family": "operating" | "financial", "net_interest": base-year filed net interest expense (positive = expense), "other_nonop": optional,
    "tax_rate": the record's MEASURED tax rate or None (not the record's 0.21 fallback), "amortization_schedule": {year: A} | [A_1, ...] | None,
    "amortization_0": the base-year filed amortization of acquired intangibles}."""
    if facts.get("family") == "financial":
        return {"status": BRIDGE_OK, "financial": True}
    tau = facts.get("tax_rate")
    if not _tax_ok(tau):
        return {"status": UNAVAILABLE_TAX}
    ni = facts.get("net_interest")
    if not _num(ni):
        return {"status": UNAVAILABLE_INTEREST}
    if not _num(facts.get("amortization_0")):
        return {"status": UNAVAILABLE_AMORTIZATION}
    other = facts.get("other_nonop")
    return {"status": BRIDGE_OK, "financial": False, "tau": float(tau), "net_interest": float(ni),
            "other_nonop": float(other) if _num(other) else 0.0, "other_assumed": not _num(other)}


def _x_of_op(op_margin: float, revenue: float, year: int, facts: Dict[str, Any], inp: Dict[str, Any]) -> Dict[str, Any]:
    """One year: X = (op - NI/R - O/R)(1 - tau) + (1 - tau) A/R. The row with every input."""
    if inp.get("financial"):
        return {"year": year, "revenue": revenue, "op_margin": op_margin, "x_margin": op_margin, "identity": True}
    a = _amortization_for(year, facts)
    R, tau = float(revenue), inp["tau"]
    ni_pct, o_pct, a_pct = inp["net_interest"] / R, inp["other_nonop"] / R, a["value"] / R
    x = (op_margin - ni_pct - o_pct) * (1.0 - tau) + (1.0 - tau) * a_pct
    return {"year": year, "revenue": R, "op_margin": op_margin, "net_interest": inp["net_interest"], "net_interest_pct": ni_pct,
            "other_nonop": inp["other_nonop"], "other_nonop_pct": o_pct, "tax_rate": tau, "amortization": a["value"], "amortization_source": a["source"],
            "amortization_pct": a_pct, "x_margin": x}


def _assumptions(facts: Dict[str, Any], inp: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> List[str]:
    if inp.get("financial"):
        return ["financial_family_identity: margins are already on the X basis, no conversion"]
    a = ["net_interest_base_year_filed_dollars_held"]
    if inp["other_assumed"]:
        a.append("other_nonop_assumed_zero")
    held = [r["year"] for r in rows if r.get("amortization_source") == "base_year_held"]
    a.append("amortization_filed_schedule" if rows and not held else
             ("amortization_base_year_held_all_years" if rows and len(held) == len(rows) else
              "amortization_base_year_held_years:" + "/".join(map(str, held))))
    a.append("tax_rate_measured")
    return a


def bridge_to_x(path: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """The per-year X margin of a path, by the SPEC formula, as a table with its inputs:

        X_t = (op_t - NI/R_t - O/R_t) x (1 - tau) + (1 - tau) x A_t / R_t

    NI is the base-year filed net interest in dollars, held flat; O (other non-operating) is 0, stamped `other_nonop_assumed_zero`; tau is the record's
    measured tax rate, and when it is not measured the result is `bridge_unavailable_tax` with no table (that sample is not valued); A_t is the filed
    amortization schedule's value, else A_0 held (the row says which). The financial family is an identity (its margins are on the X basis already).

    Worked example (MSGE-like): R = 100, op = 0.10, NI = 5, O = 0, tau = 0.25, A = 4 -> (0.10 - 0.05) x 0.75 + 0.75 x 0.04 = 0.0375 + 0.03 = 0.0675.

    Returns {"status", "rows": [...], "assumptions": [...], "family", "stamps"}; `status` is "ok" or the name of what is not held."""
    inp = _bridge_inputs(facts)
    fam = "financial" if facts.get("family") == "financial" else "operating"
    out: Dict[str, Any] = {"status": inp["status"], "family": fam, "rows": [], "assumptions": [], "stamps": []}
    if inp["status"] != BRIDGE_OK:
        out["stamps"].append(inp["status"])
        return out
    for y in path.get("years") or []:
        if not (_num(y.get("revenue")) and y["revenue"] > 0):
            out.update(status=UNAVAILABLE_REVENUE, rows=[])
            out["stamps"].append(UNAVAILABLE_REVENUE)
            return out
        out["rows"].append(_x_of_op(float(y["op_margin"]), float(y["revenue"]), int(y["year"]), facts, inp))
    out["assumptions"] = _assumptions(facts, inp, out["rows"])
    out["stamps"] = [a for a in out["assumptions"] if a == "other_nonop_assumed_zero" or a.startswith("amortization_base_year_held")]
    return out


def bridge_margin(op_margin: float, year: int, revenue: float, facts: Dict[str, Any]) -> Dict[str, Any]:
    """The bridge for a single margin at one year's level of revenue (used for long_run_margin at the final year's levels).
    {"status", "x_margin", "row"}; status is bridge_to_x's."""
    inp = _bridge_inputs(facts)
    if inp["status"] != BRIDGE_OK:
        return {"status": inp["status"], "x_margin": None, "row": None}
    if not (_num(revenue) and revenue > 0):
        return {"status": UNAVAILABLE_REVENUE, "x_margin": None, "row": None}
    row = _x_of_op(float(op_margin), float(revenue), int(year), facts, inp)
    return {"status": BRIDGE_OK, "x_margin": row["x_margin"], "row": row}


def invert_bridge(x_margin: float, year: int, facts: Dict[str, Any], revenue: Optional[float] = None) -> Dict[str, Any]:
    """The operating-basis margin whose X margin at `year` is `x_margin` (for the consensus, SPEC section 5). Exact inverse of bridge_to_x:

        op = (X - (1 - tau) x A_t / R_t) / (1 - tau) + NI/R_t + O/R_t

    `revenue` is that year's revenue (the consensus revenue for a consensus margin); when omitted it is read from facts["revenue_by_year"][year].
    Returns {"status", "op_margin", "inputs"}; status is "ok" or what is not held. The financial family returns x_margin unchanged."""
    inp = _bridge_inputs(facts)
    if inp["status"] != BRIDGE_OK:
        return {"status": inp["status"], "op_margin": None, "inputs": None}
    if inp.get("financial"):
        return {"status": BRIDGE_OK, "op_margin": float(x_margin), "inputs": {"identity": True}}
    if revenue is None:
        revenue = (facts.get("revenue_by_year") or {}).get(year)
    if not (_num(revenue) and revenue > 0) or not _num(x_margin):
        return {"status": UNAVAILABLE_REVENUE, "op_margin": None, "inputs": None}
    a = _amortization_for(int(year), facts)
    R, tau = float(revenue), inp["tau"]
    op = (float(x_margin) - (1.0 - tau) * a["value"] / R) / (1.0 - tau) + inp["net_interest"] / R + inp["other_nonop"] / R
    return {"status": BRIDGE_OK, "op_margin": op,
            "inputs": {"revenue": R, "net_interest": inp["net_interest"], "other_nonop": inp["other_nonop"], "tax_rate": tau,
                       "amortization": a["value"], "amortization_source": a["source"]}}


# ---- 4. valuing: the existing desk, schema 25.2 ----------------------------------------------------------------------------------------------------

def _desk_role_iv(res: Dict[str, Any], role: str) -> Optional[float]:
    for item in res.get("scenario_dcfs") or []:
        if str(item.get("name", "")).lower().startswith(role.lower()):
            v = (item.get("dcf") or {}).get("per_share_iv_raw")
            return float(v) if _num(v) else None
    return None


def _scenario_spec(name: str, sc: Dict[str, Any], forecast: Dict[str, Any], op_margin_bar: Dict[str, Any], rev0: float, facts: Dict[str, Any],
                   base_cf: float, op_margins: Optional[List[float]] = None, long_run_op: Optional[float] = None,
                   path: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One scenario ready for the desk: its path, bridge and the desk entry. `op_margins` / `long_run_op` replace the path's margins and the model's
    long-run margin (the alternative paths use this; the revenue path is unchanged)."""
    path = path or build_path(sc, op_margin_bar, rev0)
    if path["status"] != BRIDGE_OK:
        return {"status": path["status"], "scenario": name, "path": path}
    if op_margins is not None:
        path = copy.deepcopy(path)
        for y, m in zip(path["years"], op_margins):
            y["op_margin"] = float(m)
    bridge = bridge_to_x(path, facts)
    if bridge["status"] != BRIDGE_OK:
        return {"status": bridge["status"], "scenario": name, "path": path, "bridge": bridge}
    last = path["years"][HORIZON - 1]
    lr_op = float(sc["long_run_margin_op"]) if long_run_op is None else float(long_run_op)
    lr = bridge_margin(lr_op, last["year"], last["revenue"], facts)
    if lr["status"] != BRIDGE_OK:
        return {"status": lr["status"], "scenario": name, "path": path, "bridge": bridge}
    entry = {"name": name, "prob": float(sc["prob"]), "base_cf": float(base_cf),
             "revenue_growth": [y["rev_growth"] for y in path["years"][:HORIZON]],
             "earnings_margin": [r["x_margin"] for r in bridge["rows"][:HORIZON]],
             "wacc": float(forecast["discount_rate"]), "terminal_g": float(sc["terminal_g"]), "fade_years": int(sc["fade_years"]),
             "long_run_margin": lr["x_margin"], "terminal_ronic": float(sc["terminal_ronic"])}
    return {"status": BRIDGE_OK, "scenario": name, "path": path, "bridge": bridge, "long_run": lr, "desk_entry": entry}


def value_forecast(forecast: Dict[str, Any], op_margin_bar: Dict[str, Any], rev0: float, facts: Dict[str, Any], *, base_cf: float,
                   desk_params: Dict[str, Any], desk_context: Dict[str, Any], replace: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Values the three scenarios with the existing desk (execute_financial_model, desk schema 25.2): each scenario's revenue growth and X-margin path
    go in as the schema's two lists, `long_run_margin` is the bridged long-run margin at the final (year-5) levels, and nothing of the DCF is
    re-implemented here.

    `base_cf` is the desk's base cash flow ($B); `desk_params` the scenario-independent call arguments the harness supplies (cash_flow_life,
    valuation_frame, sbc_treatment, the reasons ...); `desk_context` the harness's desk context (price, anchors, long_run with rev_L and x_L ...).
    The context's desk_schema is set to 25.2 here. `replace` ({"Base": {"op_margins": [...], "long_run_margin_op": L}}) values a scenario on other
    margins and leaves the others as forecast (the alternative paths).

    Returns {"status": "ok", "values": {"Base", "Bull", "Bear"}, "base_value", "scenarios": {name: spec}, "desk": the desk result, "stamps"}, or a
    status naming what stopped the valuation (a bridge_unavailable_* status, "baseline_not_in_bar", or "desk_error" with the desk's message). A sample
    that cannot be bridged is not valued and says why; nothing is defaulted."""
    specs: Dict[str, Dict[str, Any]] = {}
    for name in SCENARIOS:
        rp = (replace or {}).get(name) or {}
        specs[name] = _scenario_spec(name, forecast["scenarios"][name], forecast, op_margin_bar, rev0, facts, base_cf,
                                     op_margins=rp.get("op_margins"), long_run_op=rp.get("long_run_margin_op"))
        if specs[name]["status"] != BRIDGE_OK:
            return {"status": specs[name]["status"], "scenario": name, "values": None, "base_value": None, "scenarios": specs, "desk": None, "stamps": []}
    ctx = dict(desk_context)
    ctx["desk_schema"] = DESK_SCHEMA
    stamps: List[str] = []
    rev_L = (ctx.get("long_run") or {}).get("rev_L")
    if _num(rev_L) and _num(rev0) and abs(float(rev_L) - float(rev0)) > 1e-9 * max(1.0, abs(float(rev0))):
        stamps.append("rev0_differs_from_desk_rev_L")            # annotate: the desk grows rev_L, this module grew rev0
    params = dict(desk_params)
    params["scenarios"] = [specs[n]["desk_entry"] for n in SCENARIOS]
    params["valuation_frame"] = forecast.get("frame", params.get("valuation_frame", "equity"))
    import financial_model_tool as fmt                           # imported here: the module is pure until it values
    res = fmt.execute_financial_model(params, ctx)
    if res.get("error") or res.get("validation_error"):
        return {"status": "desk_error", "values": None, "base_value": None, "scenarios": specs, "desk": res, "stamps": stamps,
                "message": res.get("error") or res.get("missing")}
    values = {n: _desk_role_iv(res, n) for n in SCENARIOS}
    return {"status": BRIDGE_OK, "values": values, "base_value": values["Base"], "scenarios": specs, "desk": res, "stamps": stamps}


# ---- 5. the alternative paths --------------------------------------------------------------------------------------------------------------------

def alt_op_margins(op_margins: Sequence[float], duration: float, fade_years: int, baseline_value: float, years: int = HORIZON) -> List[float]:
    """The operating margins of years 1..`years` if the evidence behind the path expires after `duration` years: the path as forecast up to `duration`,
    then a linear fade to `baseline_value` (the normalized baseline with no delta) over `fade_years`.

    m(t) = path(t) for t <= duration; for t > duration: s + (baseline - s) x min(1, (t - duration) / fade_years), s = the path's level at `duration`
    (linear between years; before year 1 the year-1 level; after the last year of `op_margins` its last level). fade_years 0 is a step.

    Worked example (path 0.10, 0.10, 0.12, 0.14, 0.16, baseline 0.08, duration 4.7, fade 4): s = 0.14 + 0.7 x 0.02 = 0.154; year 5 =
    0.154 + (0.08 - 0.154) x 0.3 / 4 = 0.14845; years 1-4 are the path."""
    n = len(op_margins)

    def at(d: float) -> float:
        if d <= 1:
            return float(op_margins[0])
        if d >= n:
            return float(op_margins[-1])
        lo = int(math.floor(d))
        return float(op_margins[lo - 1]) + (d - lo) * (float(op_margins[lo]) - float(op_margins[lo - 1]))

    s = at(duration)
    out = []
    for t in range(1, int(years) + 1):
        if t <= duration:
            out.append(float(op_margins[min(t, n) - 1]))
        else:
            frac = 1.0 if fade_years <= 0 else min(1.0, (t - duration) / fade_years)
            out.append(s + (float(baseline_value) - s) * frac)
    return out


def alt_paths(forecast: Dict[str, Any], dossier: Dict[str, Any], op_margin_bar: Dict[str, Any], rev0: float, facts: Dict[str, Any], *, base_cf: float,
              desk_params: Dict[str, Any], desk_context: Dict[str, Any], scenario: str = "Base") -> List[Dict[str, Any]]:
    """SPEC section 2, step 4. For every fact cited in the scenario's `normalized.fact_ids` or behind its long-run margin (`long_run_fact_ids`) whose
    `duration_years` is a finite number, the path and value if that evidence expires: the margin fades linearly from the end of the duration to the
    normalized baseline (no delta) over the scenario's fade, and the long-run margin is that baseline. Reported as `alt_path_after_evidence_expiry`;
    NEVER substituted for the forecast's own value. A fact with duration "ongoing", null, or not a finite non-negative number gets no alternative.

    Each item: {"label": "alt_path_after_evidence_expiry", "fact_id", "duration_years", "op_margins", "x_margins", "long_run_margin_op", "value",
    "status", "stamps"}. A duration beyond the five explicit years leaves years 1-5 on the forecast's path and moves only the long run, so the
    desk's own fade (which starts at year 5) takes the margin to the baseline earlier than the fact says: stamped `evidence_outlasts_explicit_years`."""
    sc = forecast["scenarios"][scenario]
    cited = list((sc.get("normalized") or {}).get("fact_ids") or []) + list(sc.get("long_run_fact_ids") or [])
    by_id = {f.get("fact_id"): f for f in (dossier or {}).get("facts") or [] if isinstance(f, dict)}
    seen, out = set(), []
    for fid in cited:
        if fid in seen:
            continue
        seen.add(fid)
        d = (by_id.get(fid) or {}).get("duration_years")
        if not (_num(d) and d >= 0):
            continue
        nrm = normalized_margin(sc["normalized"], op_margin_bar)
        N = int(sc["normalized"]["year"])
        path = build_path(sc, op_margin_bar, rev0, years=max(HORIZON, int(math.ceil(d)), N))
        item: Dict[str, Any] = {"label": "alt_path_after_evidence_expiry", "fact_id": fid, "duration_years": float(d), "stamps": []}
        if path["status"] != BRIDGE_OK:
            item.update(status=path["status"], value=None)
            out.append(item)
            continue
        full = alt_op_margins([y["op_margin"] for y in path["years"]], float(d), int(sc["fade_years"]), nrm["baseline_value"], years=len(path["years"]))
        alt = full[:HORIZON]
        if d > HORIZON:
            item["stamps"].append("evidence_outlasts_explicit_years")
        res = value_forecast(forecast, op_margin_bar, rev0, facts, base_cf=base_cf, desk_params=desk_params, desk_context=desk_context,
                             replace={scenario: {"op_margins": alt, "long_run_margin_op": nrm["baseline_value"]}})
        br = (res["scenarios"].get(scenario) or {}).get("bridge")
        x_margins = [r["x_margin"] for r in br["rows"][:HORIZON]] if br and br.get("rows") else None
        item.update(status=res["status"], op_margins=alt, x_margins=x_margins, long_run_margin_op=nrm["baseline_value"],
                    value=res["values"][scenario] if res["values"] else None)
        out.append(item)
    return out


# ---- 6. aggregation of the K samples --------------------------------------------------------------------------------------------------------------

def _value_of(s: Any) -> Optional[float]:
    v = s.get("base_value") if isinstance(s, dict) else s
    return float(v) if _num(v) else None


def aggregate(samples: Sequence[Any]) -> Dict[str, Any]:
    """The K samples' Base values (a number, or a dict with `base_value`; None or a non-number is a dropped sample, e.g. forecast_invalid).

    {"n", "dropped": [indices], "median_index": index into `samples` of the median sample (Base value), "median", "min", "max", "spread"}.
    The median of an even count is the lower of the two middle values (an actual sample, so it has a forecast); equal values are ordered by index.
    spread = (max - min) / median, None (stamped `spread_median_not_positive`) when the median is not above 0: a ratio to a non-positive value
    means nothing. With no usable sample every field is None."""
    vals = [(i, _value_of(s)) for i, s in enumerate(samples)]
    kept = [(i, v) for i, v in vals if v is not None]
    out: Dict[str, Any] = {"n": len(kept), "dropped": [i for i, v in vals if v is None], "median_index": None, "median": None, "min": None,
                           "max": None, "spread": None, "stamps": []}
    if not kept:
        return out
    order = sorted(kept, key=lambda iv: (iv[1], iv[0]))
    mi, med = order[(len(order) - 1) // 2]
    lo, hi = order[0][1], order[-1][1]
    out.update(median_index=mi, median=med, min=lo, max=hi)
    if med > 0:
        out["spread"] = (hi - lo) / med
    else:
        out["stamps"].append("spread_median_not_positive")
    return out


def sample_directions(values: Sequence[Optional[float]], price: float, min_mos: Optional[float] = None) -> List[Optional[str]]:
    """Each value's verdict word against the price, by the band rule of depth_pipeline.band_verdict applied to one value: "undervalued" when
    (v - price) / price >= min_mos, "overvalued" when (price - v) / price >= min_mos, else "hold" (None for a dropped sample).
    `min_mos` defaults to depth_gates.MIN_MOS_FOR_DIRECTION, the constant the verdict itself reads."""
    if min_mos is None:
        import depth_gates
        min_mos = depth_gates.MIN_MOS_FOR_DIRECTION
    out: List[Optional[str]] = []
    for s in values:
        v = _value_of(s)
        if v is None or not (_num(price) and price > 0):
            out.append(None)
        elif (v - price) / price >= min_mos:
            out.append("undervalued")
        elif (price - v) / price >= min_mos:
            out.append("overvalued")
        else:
            out.append("hold")
    return out


def direction_split(samples: Sequence[Any], price_band: Any) -> bool:
    """True when the samples straddle the verdict boundary: at least one says undervalued and another overvalued, against the same band (SPEC section 3,
    'No call'). `price_band` is (price, min_mos) or {"price", "min_mos"}; a missing min_mos is the verdict's own constant. A "hold" sample is on neither
    side. Dropped samples are ignored."""
    if isinstance(price_band, dict):
        price, mos = price_band.get("price"), price_band.get("min_mos")
    else:
        price, mos = price_band[0], (price_band[1] if len(price_band) > 1 else None)
    d = set(sample_directions([_value_of(s) for s in samples], price, mos))
    return "undervalued" in d and "overvalued" in d


# ---- 7. the pull ratio -------------------------------------------------------------------------------------------------------------------------------

def pull_ratio(m_pre: Any, m_post: Any, m_consensus: Any) -> Optional[float]:
    """|m_post - m_pre| / |m_consensus - m_pre|: how far a revised margin moved toward (or past, or away from) the revealed consensus margin, as a share
    of the distance the reveal opened. None when the consensus margin is unavailable, or equals m_pre (no distance to move). 0.0 is a value: a margin
    that did not move has ratio 0.0, and a pre-reveal margin of 0.0 is a margin."""
    if not (_num(m_pre) and _num(m_post) and _num(m_consensus)):
        return None
    gap = abs(float(m_consensus) - float(m_pre))
    if gap == 0:
        return None
    return abs(float(m_post) - float(m_pre)) / gap
