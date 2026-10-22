"""r26_spread.py - revision 26, S3 "spread attribution" (cross-check 25 ruling): which group of a stage-2 forecast's inputs makes the K blind samples disagree.

A code-only diagnostic. It values nothing itself: the caller's `value_fn(forecast) -> Base value or None` does (in the pipeline, r26_forecast.value_forecast through
the desk). No model, no I/O, no clock, no random; a failed valuation is recorded as None and never defaulted; 0.0 is a value.

THE GROUPS. Every input of a forecast that reaches the desk belongs to exactly one group, and a group is always applied to ALL THREE scenarios at once (so the
probabilities still add to 1 and a transition always travels with the normalized year it refers to):
  near_term        scenarios.*.near_term.rev_growth, .op_margin
  normalized       scenarios.*.normalized.year, .rev_growth, .baseline, .delta_pts; scenarios.*.transition, .transition_year
  long_run_margin  scenarios.*.long_run_margin_op
  terminal         scenarios.*.terminal_g, .terminal_ronic, .fade_years
  discount         discount_rate
  probabilities    scenarios.*.prob
Fact IDs, reasons and labels do not reach the desk and are not swapped. A key the donor does not hold (transition_year under "linear") is removed from the copy.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import r26_forecast as rf

SCENARIOS = rf.SCENARIOS
INTERACTION_TOLERANCE = 0.25            # the ruling's 25%: the single-group effects' sum against the total difference

# group -> the paths it replaces; a path starting with "*" is inside each of the three scenarios
GROUPS: Dict[str, List[tuple]] = {
    "near_term": [("*", "near_term", "rev_growth"), ("*", "near_term", "op_margin")],
    "normalized": [("*", "normalized", "year"), ("*", "normalized", "rev_growth"), ("*", "normalized", "baseline"), ("*", "normalized", "delta_pts"),
                   ("*", "transition"), ("*", "transition_year")],
    "long_run_margin": [("*", "long_run_margin_op")],
    "terminal": [("*", "terminal_g"), ("*", "terminal_ronic"), ("*", "fade_years")],
    "discount": [("discount_rate",)],
    "probabilities": [("*", "prob")],
}

METHOD = ("Reference = the median-value sample (r26_forecast.aggregate's rule: the lower middle, ties by index). For each other sample j and each group G: "
          "swap_in = mean over j of |v(reference with G taken from j) - v(reference)| / v(reference); swap_out = mean over j of |v(j) - v(j with G taken from the reference)| / v(reference). "
          "spread_if_only_G_differs = (max - min) / median over the reference and every 'reference with G from j' (the samples differing only in G). "
          "Each group is applied to all three scenarios at once. dominant_group = the largest mean of swap_in and swap_out. interaction_note is set when, for some j and "
          "either direction, the signed single-group effects add to a total that differs from v(j) - v(reference) by more than 25% of it. "
          "A failed valuation (None) is listed, never defaulted: a mean or spread over fewer samples than K-1 / K is stamped partial.")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _forecast_of(s: Any) -> Dict[str, Any]:
    """A sample is a forecast, or a stage-2 sample record that carries one under "forecast"."""
    return s["forecast"] if isinstance(s, dict) and isinstance(s.get("forecast"), dict) else s


def _get(obj: Dict[str, Any], path: Sequence[str]):
    cur: Any = obj
    for k in path:
        if not (isinstance(cur, dict) and k in cur):
            return False, None
        cur = cur[k]
    return True, cur


def swap_group(target: Dict[str, Any], donor: Dict[str, Any], group: str) -> Dict[str, Any]:
    """A deep copy of `target` with group `group` taken from `donor` (all three scenarios). A key the donor lacks is removed from the copy."""
    out = copy.deepcopy(target)
    for path in GROUPS[group]:
        paths = [("scenarios", sc) + tuple(path[1:]) for sc in SCENARIOS] if path[0] == "*" else [tuple(path)]
        for p in paths:
            held, val = _get(donor, p)
            parent_held, parent = _get(out, p[:-1])
            if not parent_held or not isinstance(parent, dict):
                continue                                    # the copy has no such scenario or block: nothing to replace
            if held:
                parent[p[-1]] = copy.deepcopy(val)
            else:
                parent.pop(p[-1], None)
    return out


def _value(value_fn: Callable[[Dict[str, Any]], Optional[float]], fc: Dict[str, Any]) -> Optional[float]:
    v = value_fn(fc)
    return float(v) if _num(v) else None


def _mean_abs(changes: List[Optional[float]]) -> Optional[float]:
    kept = [abs(c) for c in changes if c is not None]
    return sum(kept) / len(kept) if kept else None


def _spread(values: List[Optional[float]]) -> Optional[float]:
    kept = [v for v in values if v is not None]
    if len(kept) < 2:
        return None
    return rf.aggregate(kept)["spread"]


def attribute_spread(samples: Sequence[Any], value_fn: Callable[[Dict[str, Any]], Optional[float]]) -> Dict[str, Any]:
    """Attributes the spread of the samples' Base values to the six input groups (see the module docstring and METHOD).

    `samples`: forecasts, or stage-2 sample records holding one under "forecast". Every value used here, the samples' own included, comes from `value_fn`, so a
    hybrid and the sample it is compared with are valued by one function; a sample whose `value_fn` gives None is listed under "unvalued" and left out, and a stored
    "base_value" that differs from value_fn's is listed under "stored_value_mismatch" (annotated, not corrected). Fewer than 2 valued samples:
    {"status": "not_enough_samples", ...}.

    Returns {"status": "ok", "reference_index" (into `samples`), "base_values" (value_fn per sample, None where it failed), "spread", "groups": {G: {"swap_in",
    "swap_out", "spread_if_only_G_differs", "per_sample", "failed", "stamps"}}, "dominant_group", "interaction_note", "interaction", "coverage", "unvalued",
    "stored_value_mismatch", "stamps", "method"}. Changes are fractions of the reference value; with a reference value not above 0 they are None (stamped)."""
    forecasts = [_forecast_of(s) for s in samples]
    values = [_value(value_fn, fc) for fc in forecasts]
    valued = [i for i, v in enumerate(values) if v is not None]
    unvalued = [i for i, v in enumerate(values) if v is None]
    mismatch = []
    for i, s in enumerate(samples):
        if isinstance(s, dict) and "forecast" in s and _num(s.get("base_value")) and values[i] is not None:
            if abs(float(s["base_value"]) - values[i]) > 1e-9 * max(1.0, abs(values[i])):
                mismatch.append({"index": i, "stored": float(s["base_value"]), "value_fn": values[i]})
    if len(valued) < 2:
        return {"status": "not_enough_samples", "n_valued": len(valued), "base_values": values, "unvalued": unvalued, "method": METHOD}
    agg = rf.aggregate([values[i] for i in valued])
    ref = valued[agg["median_index"]]
    v_ref = values[ref]
    others = [j for j in valued if j != ref]
    stamps: List[str] = list(agg["stamps"])
    ref_ok = v_ref > 0
    if not ref_ok:
        stamps.append("reference_value_not_positive")

    def frac(d: Optional[float]) -> Optional[float]:
        return d / v_ref if (d is not None and ref_ok) else None

    groups: Dict[str, Any] = {}
    for g in GROUPS:
        per, failed = [], []
        for j in others:
            vin = _value(value_fn, swap_group(forecasts[ref], forecasts[j], g))
            vout = _value(value_fn, swap_group(forecasts[j], forecasts[ref], g))
            if vin is None:
                failed.append({"index": j, "direction": "swap_in"})
            if vout is None:
                failed.append({"index": j, "direction": "swap_out"})
            per.append({"index": j, "value": values[j], "swap_in_value": vin, "swap_out_value": vout,
                        "swap_in_change": frac(vin - v_ref if vin is not None else None),
                        "swap_out_change": frac(values[j] - vout if vout is not None else None)})
        only = [v_ref] + [p["swap_in_value"] for p in per]
        gst = []
        if failed:
            gst.append("partial_failed_valuations")
        groups[g] = {"swap_in": _mean_abs([p["swap_in_change"] for p in per]), "swap_out": _mean_abs([p["swap_out_change"] for p in per]),
                     "spread_if_only_G_differs": _spread(only), "per_sample": per, "failed": failed, "stamps": gst}

    def score(g: str) -> Optional[float]:
        xs = [x for x in (groups[g]["swap_in"], groups[g]["swap_out"]) if x is not None]
        return sum(xs) / len(xs) if xs else None

    scored = [(score(g), g) for g in GROUPS if score(g) is not None]
    dominant = max(scored, key=lambda sg: sg[0])[1] if scored else None
    if scored and sum(1 for s, _ in scored if s == max(scored)[0]) > 1:
        stamps.append("dominant_group_tied")

    # interactions: the signed single-group effects against the total difference, per other sample and direction
    interaction, notes = [], []
    for k, j in enumerate(others):
        total = values[j] - v_ref
        for direction, key in (("swap_in", "swap_in_value"), ("swap_out", "swap_out_value")):
            vals = [groups[g]["per_sample"][k][key] for g in GROUPS]
            if any(v is None for v in vals):
                interaction.append({"index": j, "direction": direction, "status": "not_checked_failed_valuations"})
                continue
            s = sum((v - v_ref) for v in vals) if direction == "swap_in" else sum((values[j] - v) for v in vals)
            exceeds = abs(s - total) > INTERACTION_TOLERANCE * abs(total)
            interaction.append({"index": j, "direction": direction, "total_difference": total, "sum_of_single_effects": s, "exceeds_tolerance": exceeds})
            if exceeds:
                notes.append(f"sample {j} {direction}: single-group effects sum to {s:.6g} against a total difference of {total:.6g}")
    interaction_note = ("interactions matter (beyond 25% of the total difference): " + "; ".join(notes)) if notes else None

    # coverage: the reference with EVERY group taken from j must value as j (the groups hold every desk input); a difference is stated, not hidden
    coverage = []
    for j in others:
        fc = forecasts[ref]
        for g in GROUPS:
            fc = swap_group(fc, forecasts[j], g)
        v = _value(value_fn, fc)
        ok = v is not None and abs(v - values[j]) <= 1e-9 * max(1.0, abs(values[j]))
        coverage.append({"index": j, "all_groups_swapped_value": v, "matches_sample_value": ok})
        if not ok:
            stamps.append(f"groups_do_not_reproduce_sample_{j}")

    return {"status": "ok", "reference_index": ref, "base_values": values, "spread": agg["spread"], "groups": groups, "dominant_group": dominant,
            "interaction_note": interaction_note, "interaction": interaction, "coverage": coverage, "unvalued": unvalued, "stored_value_mismatch": mismatch,
            "stamps": stamps, "method": METHOD}
