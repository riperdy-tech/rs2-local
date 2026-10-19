"""r26_forecast.py - revision 26 (SPEC_rev26_staged_analyst.md sections 2 and 3): the stage-2 forecast, as pure functions.

What is here, in the order the spec uses it:
  validate_forecast   structure and four domain rules: fields, finiteness, enums, usable fact IDs, probabilities, non-negative revenue, discount rate above terminal_g,
                      positive terminal_ronic (cross-check 23). A margin is never bounded.
  build_path          years of revenue growth and operating margin from the model's near term, its normalized state and its transition.
  bridge_to_x         the operating margin of each year on the desk's X basis (net income + after-tax amortization, over revenue; calibrated to the filed base year), as a table
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
the one place that converts. Dollar quantities (revenue, operating income, X-basis earnings, K_0) share one unit, whatever it is.

The forecast object:
  {"discount_rate": r, "frame": "equity",
   "scenarios": {"Base": SC, "Bull": SC, "Bear": SC}}
  SC = {"near_term": {"rev_growth": [g1, g2], "op_margin": [m1, m2], "fact_ids": [...]},
        "normalized": {"year": N, "rev_growth": gN, "baseline": "min|p25|median|p75|max|last", "delta_pts": d, "fact_ids": [...], "reason": "..."},
        "transition": "linear" | "step_at_year" | "hold_then_linear", "transition_year": k,
        "long_run_margin_op": L, "terminal_g": gT, "terminal_ronic": ronic, "fade_years": F, "prob": p,
        "long_run_fact_ids": [...],                 # the usable facts behind long_run_margin_op (SPEC step 4 names them; see alt_paths) ...
        "no_duration_matched_evidence": "..."}      # ... or, instead, this sentence saying that no usable fact speaks for as long as the long run (one of the two is required)
The operating-margin bar: {"min", "p25", "median", "p75", "max", "last"} as decimals (SPEC section 5), plus anything else it carries.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Sequence

BASELINES = ("min", "p25", "median", "p75", "max", "last")
TRANSITIONS = ("linear", "step_at_year", "hold_then_linear")
FRAMES = ("equity",)                    # ruling 2026-10-19 (cross-check 23, item 1): the frame is equity only for r26
SCENARIOS = ("Base", "Bull", "Bear")
DELTA_PTS_SCALE = 0.01                  # delta_pts is in percentage points
NEAR_TERM_YEARS = 2
MAX_REASON_WORDS = 60                   # SPEC section 2: "reason": "<= 60 words>"
HORIZON = 5                             # the desk's explicit years (25.2 path arithmetic: five years, then the fade)
DESK_SCHEMA = "25.2"
BRIDGE_OK = "ok"
UNAVAILABLE_TAX = "bridge_unavailable_tax"
UNAVAILABLE_OPERATING_INCOME = "bridge_unavailable_operating_income"
UNAVAILABLE_X0 = "bridge_unavailable_x_0"
CALIBRATED_STAMP = "bridge_calibrated_to_base_year"
UNAVAILABLE_REVENUE = "bridge_unavailable_revenue"
PROB_SUM_TOLERANCE = 0.01               # item 6: the three probabilities add to 1 +- 0.01
EARLY_FADE_STRESS = "early_fade_stress"                          # item 15
EXPIRY_ALT = "alt_path_after_evidence_expiry"
TAX_CLIPPED_STAMP = "tax_rate_clipped"                           # item 8
DELTA_SCALE_STAMP = "delta_pts_scale_suspect"                    # item 11
DELTA_PTS_SUSPECT_LOW, DELTA_PTS_SUSPECT_HIGH = 0.05, 50.0


def _num(v: Any) -> bool:
    """A finite number that is not a bool. 0.0 is a number."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v: Any) -> bool:
    return _num(v) and float(v).is_integer()


# ---- 1. validation: structure only ---------------------------------------------------------------------------------------------------------------

def dossier_fact_ids(dossier: Optional[Dict[str, Any]]) -> set:
    """Every fact ID in the dossier, usable or not (an unusable fact exists but cannot be cited: see usable_fact_ids)."""
    return {f.get("fact_id") for f in ((dossier or {}).get("facts") or []) if isinstance(f, dict) and isinstance(f.get("fact_id"), str)}


def usable_fact_ids(dossier: Optional[Dict[str, Any]]) -> set:
    """The IDs of the usable facts: the only ones a forecast may cite (cross-check 23, item 2)."""
    return {f.get("fact_id") for f in ((dossier or {}).get("facts") or []) if isinstance(f, dict) and isinstance(f.get("fact_id"), str) and f.get("usable")}


def _fact_ids_problems(where: str, v: Any, known: Optional[set], out: List[Dict[str, str]], usable: Optional[set] = None, required: bool = False) -> None:
    """The problems of a list of cited fact IDs. `known` is every ID of the dossier, `usable` the citable ones (None: the same as `known`, the old behaviour).
    With `required` and a dossier, an empty list is a problem (`fact_ids_empty`)."""
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        out.append({"field": where, "problem": "not_a_list_of_fact_ids"})
        return
    if known is None:
        return
    ok = known if usable is None else usable
    missing = [x for x in v if x not in known]
    if missing:
        out.append({"field": where, "problem": "fact_id_not_in_dossier", "detail": ", ".join(missing)})
    unusable = [x for x in v if x in known and x not in ok]
    if unusable:
        out.append({"field": where, "problem": "fact_id_not_usable", "detail": ", ".join(unusable)})
    if required and not v:
        out.append({"field": where, "problem": "fact_ids_empty"})


def _numbers_problem(where: str, v: Any, n: int, out: List[Dict[str, str]]) -> None:
    if not (isinstance(v, (list, tuple)) and len(v) == n):
        out.append({"field": where, "problem": f"not_a_list_of_{n}_numbers"})
    elif not all(_num(x) for x in v):
        out.append({"field": where, "problem": "not_finite_numbers"})


def _below_minus_one(where: str, v: Any, out: List[Dict[str, str]]) -> None:
    """Revenue never goes negative (item 6): a growth rate below -100% would make it so."""
    vals = v if isinstance(v, (list, tuple)) else []
    if any(_num(x) and x < -1.0 for x in vals):
        out.append({"field": where, "problem": "revenue_would_be_negative"})


def validate_scenario(sc: Any, label: str, known: Optional[set], usable: Optional[set] = None) -> List[Dict[str, str]]:
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
        _below_minus_one(p + "near_term.rev_growth", nt.get("rev_growth"), out)
        _fact_ids_problems(p + "near_term.fact_ids", nt.get("fact_ids"), known, out, usable, required=True)
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
        elif N < 3 or N > HORIZON:                                  # coordinator ruling: N is 3..5 (a year index, not a bounded estimate)
            out.append({"field": p + "normalized.year", "problem": "normalized_year_out_of_range"})
        for k in ("rev_growth", "delta_pts"):
            if not _num(nm.get(k)):
                out.append({"field": p + f"normalized.{k}", "problem": "not_a_finite_number"})
        _below_minus_one(p + "normalized.rev_growth", [nm.get("rev_growth")], out)
        if nm.get("baseline") not in BASELINES:
            out.append({"field": p + "normalized.baseline", "problem": "not_one_of_" + "|".join(BASELINES)})
        _fact_ids_problems(p + "normalized.fact_ids", nm.get("fact_ids"), known, out, usable, required=True)
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
    # domain checks (item 6): a probability is in [0, 1] (the three sum to 1 in validate_forecast) and the return on new investment is positive
    if _num(sc.get("prob")) and not 0.0 <= sc["prob"] <= 1.0:
        out.append({"field": p + "prob", "problem": "probability_outside_0_1"})
    if _num(sc.get("terminal_ronic")) and not sc["terminal_ronic"] > 0:
        out.append({"field": p + "terminal_ronic", "problem": "terminal_ronic_not_positive"})
    # the long run rests on facts, or says in words that no fact matches its duration (item 2)
    lr_ids, nd = sc.get("long_run_fact_ids"), sc.get("no_duration_matched_evidence")
    if lr_ids is not None:
        _fact_ids_problems(p + "long_run_fact_ids", lr_ids, known, out, usable)
    if nd is not None and not (isinstance(nd, str) and nd.strip()):
        out.append({"field": p + "no_duration_matched_evidence", "problem": "missing_text"})
    elif known is not None and not (isinstance(lr_ids, list) and lr_ids) and nd is None:
        out.append({"field": p + "long_run_fact_ids", "problem": "needs_fact_ids_or_no_duration_matched_evidence_with_a_reason"})
    return out


def validate_forecast(obj: Any, dossier: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """SPEC section 2, 'Validation is structure only' as amended by cross-check 23 (items 1, 2 and 6): the list of named problems ([] when the forecast is valid).

    Checked: the fields exist and have their types; every number is finite (NaN, infinity and booleans are refused, 0.0 is accepted); the enums
    (`baseline`, `transition`, `frame`, which is equity); whole-number year fields; the word count of `reason`; and, when `dossier` is given, that every cited fact ID
    exists in it AND is usable, that near_term and normalized cite at least one, and that the long run cites facts or states `no_duration_matched_evidence` with a
    reason. The domain checks (item 6): each probability in [0, 1] and the three summing to 1 +- 0.01, revenue never negative (growth not below -100%), the discount
    rate above each terminal_g, terminal_ronic above zero. Never checked: how large or small a margin is. A margin of 400% is valid.

    The normalized year N must be a whole number 3..5 (`normalized_year_out_of_range`). A normalization that is reached after year 5 is not given
    as N: it is expressed through `long_run_margin_op` and `fade_years`, which the desk already fades to after year 5."""
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
    usable = usable_fact_ids(dossier) if dossier is not None else None
    for name in SCENARIOS:
        out += validate_scenario(scs.get(name), name, known, usable)
    dr = obj.get("discount_rate")
    for name in SCENARIOS:
        g = scs[name].get("terminal_g") if isinstance(scs.get(name), dict) else None
        if _num(dr) and _num(g) and not dr > g:
            out.append({"field": f"{name}.terminal_g", "problem": "terminal_g_not_below_discount_rate"})
    probs = [scs[n].get("prob") if isinstance(scs.get(n), dict) else None for n in SCENARIOS]
    if all(_num(x) for x in probs) and abs(sum(probs) - 1.0) > PROB_SUM_TOLERANCE + 1e-12:
        out.append({"field": "scenarios", "problem": "probabilities_do_not_sum_to_1", "detail": f"sum {sum(probs):g}"})
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


def delta_pts_scale_suspect(delta_pts: Any) -> bool:
    """Item 11 (annotate only): 0 < |delta_pts| < 0.05 reads like a fraction typed where percentage points were asked (0.02 for two points); |delta_pts| > 50 reads like
    basis points or a margin typed as a delta. Zero is a value and is never suspect."""
    if not _num(delta_pts):
        return False
    d = abs(float(delta_pts))
    return (0.0 < d < DELTA_PTS_SUSPECT_LOW) or d > DELTA_PTS_SUSPECT_HIGH


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
    N is 3..5 after validate_forecast; a direct caller may pass a later N, and the path then ends mid-transition and says so (`normalized_year_beyond_path`, defensive).

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
    if delta_pts_scale_suspect(nm.get("delta_pts")):
        out["stamps"].append(DELTA_SCALE_STAMP)
    return out


# ---- 3. the bridge from the operating basis to the X basis ---------------------------------------------------------------------------------------------
# Calibrated to the filed base year (coordinator ruling, 2026-10-19). K_0 = OI_0 - X_0 / (1 - tau) in dollars carries the base year's net interest, its other
# non-operating items and its acquired amortization together; per year X_margin_t = (op_margin_t - K_0 / R_t) x (1 - tau). At the base year the bridge returns X_0 exactly.

def _tax_ok(tau: Any) -> bool:
    return _num(tau) and tau < 1.0


def _bridge_inputs(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The scenario-independent inputs of the bridge, or the status naming what is not held.
    facts: {"family": "operating" | "financial", "tax_rate": the record's MEASURED tax rate or None (not the record's 0.21 fallback),
    "operating_income_0": the base year's filed operating income, "x_0": the base year's X-basis earnings (x_L x rev_L of the pack), both in the unit of the revenue
    the path carries ($B in the pipeline)}. K_0 = operating_income_0 - x_0 / (1 - tax_rate), in that same unit."""
    if facts.get("family") == "financial":
        return {"status": BRIDGE_OK, "financial": True}
    tau = facts.get("tax_rate")
    if not _tax_ok(tau):
        return {"status": UNAVAILABLE_TAX}
    oi0, x0 = facts.get("operating_income_0"), facts.get("x_0")
    if not _num(oi0):
        return {"status": UNAVAILABLE_OPERATING_INCOME}
    if not _num(x0):
        return {"status": UNAVAILABLE_X0}
    raw = facts.get("tax_rate_raw")
    raw = float(raw) if _num(raw) else None
    return {"status": BRIDGE_OK, "financial": False, "tau": float(tau), "tax_rate_raw": raw, "tax_rate_clipped": raw is not None and raw != float(tau),
            "operating_income_0": float(oi0), "x_0": float(x0), "k_0": float(oi0) - float(x0) / (1.0 - float(tau))}


def _x_of_op(op_margin: float, revenue: float, year: int, inp: Dict[str, Any]) -> Dict[str, Any]:
    """One year: X = (op - K_0 / R)(1 - tau). The row with every input."""
    if inp.get("financial"):
        return {"year": year, "revenue": revenue, "op_margin": op_margin, "x_margin": op_margin, "identity": True}
    R, tau = float(revenue), inp["tau"]
    k_pct = inp["k_0"] / R
    row = {"year": year, "revenue": R, "op_margin": op_margin, "k_0": inp["k_0"], "k_0_pct": k_pct, "tax_rate": tau, "x_margin": (op_margin - k_pct) * (1.0 - tau)}
    if inp.get("tax_rate_raw") is not None:
        row["tax_rate_raw"] = inp["tax_rate_raw"]               # item 8: the measured rate beside the applied one
        row["tax_rate_clipped"] = bool(inp["tax_rate_clipped"])
    return row


def _assumptions(inp: Dict[str, Any]) -> List[str]:
    if inp.get("financial"):
        return ["financial_family_identity: margins are already on the X basis, no conversion"]
    return ["bridge_calibrated_to_base_year: K_0 = filed operating income - X-basis earnings / (1 - tax rate), held in dollars",
            "k_0_carries_net_interest_other_nonoperating_and_acquired_amortization_all_held_flat_in_dollars",
            (f"tax_rate_clipped: measured {inp['tax_rate_raw']:.4f}, applied {inp['tau']:.4f} (clipped to [0, 0.35])" if inp.get("tax_rate_clipped") else "tax_rate_measured")]


def bridge_to_x(path: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """The per-year X margin of a path, calibrated to the filed base year, as a table with its inputs:

        X_t = (op_t - K_0 / R_t) x (1 - tau),     K_0 = OI_0 - X_0 / (1 - tau)

    K_0 is held in dollars and stamped `bridge_calibrated_to_base_year`; it carries the base year's net interest, other non-operating items and acquired
    amortization together (the held amortization is listed as an assumption, not refined by a schedule). tau is the record's measured tax rate. If tau, OI_0 or X_0
    is not held the result is `bridge_unavailable_tax` / `_operating_income` / `_x_0` with no table (that sample is not valued). The financial family is an identity.

    Worked example: OI_0 = 10, X_0 = 6, tau = 0.25 -> K_0 = 10 - 6 / 0.75 = 2. At R_0 = 100 and op = 0.10: X = (0.10 - 0.02) x 0.75 = 0.06 = X_0 / R_0 (exact).
    At R = 200 and op = 0.10: X = (0.10 - 0.01) x 0.75 = 0.0675.

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
        out["rows"].append(_x_of_op(float(y["op_margin"]), float(y["revenue"]), int(y["year"]), inp))
    out["assumptions"] = _assumptions(inp)
    out["stamps"] = [] if inp.get("financial") else [CALIBRATED_STAMP] + ([TAX_CLIPPED_STAMP] if inp.get("tax_rate_clipped") else [])
    return out


def bridge_margin(op_margin: float, year: int, revenue: float, facts: Dict[str, Any]) -> Dict[str, Any]:
    """The bridge for a single margin at one year's level of revenue (used for long_run_margin at the final year's levels).
    {"status", "x_margin", "row"}; status is bridge_to_x's."""
    inp = _bridge_inputs(facts)
    if inp["status"] != BRIDGE_OK:
        return {"status": inp["status"], "x_margin": None, "row": None}
    if not (_num(revenue) and revenue > 0):
        return {"status": UNAVAILABLE_REVENUE, "x_margin": None, "row": None}
    row = _x_of_op(float(op_margin), float(revenue), int(year), inp)
    return {"status": BRIDGE_OK, "x_margin": row["x_margin"], "row": row}


def invert_bridge(x_margin: float, year: int, facts: Dict[str, Any], revenue: Optional[float] = None) -> Dict[str, Any]:
    """The operating-basis margin whose X margin at `year` is `x_margin` (for the consensus, SPEC section 5). Exact inverse of bridge_to_x:

        op = X / (1 - tau) + K_0 / R_t

    `revenue` is that year's revenue in the unit of the facts' OI_0 and X_0 ($B in the pipeline; the consensus revenue for a consensus margin); when omitted it is read
    from facts["revenue_by_year"][year]. Returns {"status", "op_margin", "inputs"}; status is "ok" or what is not held. The financial family returns x_margin unchanged."""
    inp = _bridge_inputs(facts)
    if inp["status"] != BRIDGE_OK:
        return {"status": inp["status"], "op_margin": None, "inputs": None}
    if inp.get("financial"):
        return {"status": BRIDGE_OK, "op_margin": float(x_margin), "inputs": {"identity": True}}
    if revenue is None:
        revenue = (facts.get("revenue_by_year") or {}).get(year)
    if not (_num(revenue) and revenue > 0) or not _num(x_margin):
        return {"status": UNAVAILABLE_REVENUE, "op_margin": None, "inputs": None}
    R, tau = float(revenue), inp["tau"]
    op = float(x_margin) / (1.0 - tau) + inp["k_0"] / R
    return {"status": BRIDGE_OK, "op_margin": op, "inputs": {"revenue": R, "k_0": inp["k_0"], "tax_rate": tau}}


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
    normalized baseline (no delta) over the scenario's fade, and the long-run margin is that baseline. Reported as `alt_path_after_evidence_expiry`, or as `early_fade_stress` when the duration is beyond the five explicit years (item 15: the desk's own fade
    then starts at year 5, earlier than the fact says, so the figure is a stress and not an expiry path);
    NEVER substituted for the forecast's own value. A fact with duration "ongoing", null, or not a finite non-negative number gets no alternative.

    Each item: {"label": "alt_path_after_evidence_expiry" | "early_fade_stress", "fact_id", "duration_years", "op_margins", "x_margins", "long_run_margin_op", "value",
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
        item: Dict[str, Any] = {"label": EARLY_FADE_STRESS if d > HORIZON else EXPIRY_ALT, "fact_id": fid, "duration_years": float(d), "stamps": []}
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
