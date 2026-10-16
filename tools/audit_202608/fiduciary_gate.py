#!/usr/bin/env python3
"""fiduciary_gate.py — Deterministic Fiduciary Contract Validator.

Validates and sanitizes Section 12 Machine Underwriting Contracts before
they can be admitted into consensus aggregation or the production ledger.
Enforces:
1. Scenario monotonicity: Bear IV <= Base IV <= Bull IV.
2. Probability simplex normalization (sum to 1.0) - for a COMPLETE set of weights only.
   Supplying some and defaulting the rest is REFUSED rather than blended, because the blend
   produced vectors summing above 1; see step 3 in the body.
3. Non-negative mathematical edge before capital allocation (Kelly = 0.0% if edge <= 0).
   The expected-return leg runs ONLY on weights the model actually supplied. When they are
   absent or unusable the deterministic Base-vs-Price leg governs, and the clamp text says the
   probability-weighted test was skipped. Fail-closed either way; it never quotes an invented
   expected return.
4. Dollar-cost-averaging tranche monotonicity (Starter >= Core).
5. Exact recalculation of asymmetric payoff skew.
"""
from typing import Dict, Any, Tuple, List, Optional
import copy
import sys
from pathlib import Path

# P4.4 — the `invalidation_rules` / `momentum_break_rule` / `momentum_flip_condition` metric
# vocabulary has ONE owner: capability_test.py's MOMENTUM_METRICS/FINANCIAL_METRICS, which TASK's
# printed text is itself built from (P4.4). Imported, never restated, so the prompt and this
# validator can never drift apart. The sys.path bootstrap is self-contained so this module keeps
# working regardless of how IT was imported (bare `fiduciary_gate` from depth_pipeline.py/
# status.py after their own sys.path insert, or package-qualified `tools.audit_202608.
# fiduciary_gate` from a test that only put the repo root on sys.path).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import capability_test as _cap  # noqa: E402

MOMENTUM_METRICS = _cap.MOMENTUM_METRICS
FINANCIAL_METRICS = _cap.FINANCIAL_METRICS
_METRIC_VOCABULARY = set(MOMENTUM_METRICS) | set(FINANCIAL_METRICS)
_COMPARATORS = ("<", "<=", ">", ">=")
_ENTRY_TIMINGS = ("buy_now", "wait_for_momentum", "avoid")


def contract_base(scorecard):
    """The IV that owns BOTH MoS and Kelly sizing — they are one step in RS2.txt (4-4/5).

    `base_iv` is the medoid sample's own base case (published from 2026-09-20). `median_iv` is
    the cross-sample DISPERSION statistic and is consulted only as a fallback for verdicts that
    predate the contract base. Reading the median as the base flagged every coherent contract
    whose median sat the other side of the price — precisely GEV's shape, where the medoid's
    base was $1,037.88 and the median $934.54.

    THIS FUNCTION IS THE SINGLE OWNER of that rule. `depth_pipeline` and `depth_sanity` both
    import it; neither may restate it. They previously resolved the base independently and
    disagreed — `depth_sanity` carried an extra `or lo` fallback the pipeline lacked, so the two
    held different policies for a scorecard with no IV at all. A second definition is a second
    policy, and an auditor that re-implements the rule it audits is checking a near-copy.
    """
    sc = scorecard or {}
    base = sc.get("base_iv")
    # 0.0 is a value: a contract base of 0.0 is the base (and the gate refuses it), never a reason to
    # read the median instead.
    return base if base is not None else sc.get("median_iv")


def payoff_skew(
    bull_iv: Optional[float],
    bear_iv: Optional[float],
    price: Optional[float]
) -> Optional[float]:
    """Calculates asymmetric payoff skew: upside / downside.

    Returns None when price is missing or not positive, or bull_iv or bear_iv is None.
    A downside <= 0 gives 99.9 when upside > 0, else 0.0;
    otherwise round(upside / downside, 2).
    """
    if price is None or price <= 0 or bull_iv is None or bear_iv is None:
        return None
    downside = price - bear_iv
    upside = bull_iv - price
    if downside <= 0:
        return 99.9 if upside > 0 else 0.0
    return round(upside / downside, 2)


def validate_fiduciary_contract(
    scorecard: Dict[str, Any],
    price: float
) -> Tuple[bool, Dict[str, Any], List[str]]:
    """Validate and sanitize a Section 12 machine underwriting contract.

    Returns:
        (is_valid, sanitized_card, issues)
        - is_valid: True if contract is economically and mathematically coherent.
                    False if fatal unrecoverable defects exist (e.g. inverted scenarios).
        - sanitized_card: Cleaned, repaired copy of the contract.
        - issues: List of explanations for any rejections, clamps, or repairs.
    """
    if not isinstance(scorecard, dict):
        return False, {}, ["Scorecard is not a valid dictionary"]

    card = copy.deepcopy(scorecard)
    issues: List[str] = []

    base_iv = card.get("base_iv")
    bull_iv = card.get("bull_iv")
    bear_iv = card.get("bear_iv")

    # 1. Base IV must exist and be a positive number
    if base_iv is None:
        return False, card, ["Fatal: base_iv is missing"]
    try:
        base_iv = float(base_iv)
        card["base_iv"] = base_iv
    except (ValueError, TypeError):
        return False, card, ["Fatal: base_iv is not a valid number"]

    if base_iv <= 0:
        return False, card, ["Fatal: base_iv must be strictly positive"]

    if price and price > 0:
        if base_iv < 0.01 * price or base_iv > 15.0 * price:
            return False, card, [f"Fatal: base_iv ${base_iv:.2f} is outside plausible envelope (0.01x-15x price ${price:.2f})"]

    # 2. Scenario Monotonicity Validation (Bear <= Base <= Bull)
    if bull_iv is not None:
        try:
            bull_iv = float(bull_iv)
            card["bull_iv"] = bull_iv
        except (ValueError, TypeError):
            bull_iv = None

    if bear_iv is not None:
        try:
            bear_iv = float(bear_iv)
            card["bear_iv"] = bear_iv
        except (ValueError, TypeError):
            bear_iv = None

    # Check for inverted scenarios
    if bull_iv is not None and bull_iv < (base_iv - 0.05):
        return False, card, [f"Fatal: Scenario monotonicity violated — Bull IV (${bull_iv:.2f}) < Base IV (${base_iv:.2f})"]

    if bear_iv is not None and bear_iv > (base_iv + 0.05):
        return False, card, [f"Fatal: Scenario monotonicity violated — Bear IV (${bear_iv:.2f}) > Base IV (${base_iv:.2f})"]

    if bull_iv is not None and bear_iv is not None and bear_iv > bull_iv:
        return False, card, [f"Fatal: Scenario monotonicity violated — Bear IV (${bear_iv:.2f}) > Bull IV (${bull_iv:.2f})"]

    # 3. Scenario Probability Simplex
    # `is None`, never `or`: a model that states base_probability 0.0 has stated a VALUE, and
    # `card.get(k) or 0.50` silently replaced it with the default.
    p_base = card.get("base_probability")
    p_bull = card.get("bull_probability")
    p_bear = card.get("bear_probability")
    supplied = [p for p in (p_base, p_bull, p_bear) if p is not None]

    probs_ok = False
    if len(supplied) == 3:
        try:
            pb, pu, pr = float(p_base), float(p_bull), float(p_bear)
            total_p = pb + pu + pr
            if pb >= 0.0 and pu >= 0.0 and pr >= 0.0 and total_p > 0.0:
                card["base_probability"] = round(pb / total_p, 4)
                card["bull_probability"] = round(pu / total_p, 4)
                card["bear_probability"] = round(pr / total_p, 4)
                probs_ok = True
                if abs(total_p - 1.0) > 0.05:
                    issues.append(f"Normalized scenario probabilities (original sum was {total_p:.2f})")
        except (ValueError, TypeError):
            probs_ok = False

    card["probabilities_defaulted"] = not probs_ok
    if not probs_ok:
        # A PARTIAL set must never be topped up from constants. Supplying some probabilities and
        # defaulting the rest blends the two into a vector that can sum ABOVE 1 - measured
        # 0.7/0.2/defaulted-0.2 = 1.1 and 0.6/0.9/defaulted-0.2 = 1.7, the second printing a
        # fabricated +111.0% expected return while `issues` stayed EMPTY. The docstring above
        # claims a simplex is enforced; on a partial set it was not.
        #
        # Instead every probability is CLEARED, so "the model gave us no usable probabilities" is
        # carried by the ABSENCE of the values rather than by a second flag that could drift away
        # from them. The expected-return leg then cannot run, and the clamp text says so instead
        # of quoting a number nobody produced.
        if supplied:
            issues.append("Scenario probabilities unusable (incomplete or invalid) - the "
                          "probability-weighted edge test was SKIPPED; the deterministic "
                          "Base-vs-Price test governs")
        card["base_probability"] = None
        card["bull_probability"] = None
        card["bear_probability"] = None

    # 4. Mathematical Edge & Strict Kelly Clamping
    # Expected intrinsic value exists ONLY when the model actually supplied the weights. An
    # `expected_iv` built from invented priors is an estimate dressed as a measurement.
    expected_iv, expected_return = None, None
    if probs_ok:
        eff_bull = bull_iv if bull_iv is not None else base_iv
        eff_bear = bear_iv if bear_iv is not None else base_iv
        expected_iv = (
            float(card["base_probability"]) * base_iv +
            float(card["bull_probability"]) * eff_bull +
            float(card["bear_probability"]) * eff_bear
        )
    card["expected_iv"] = round(expected_iv, 2) if expected_iv is not None else None

    kelly_pct = card.get("kelly_fraction_pct")
    if kelly_pct is not None:
        try:
            kelly_pct = float(kelly_pct)
        except (ValueError, TypeError):
            kelly_pct = 0.0

    if price and price > 0:
        if probs_ok:
            expected_return = (expected_iv - price) / price
            card["expected_return_pct"] = round(expected_return * 100.0, 2)
        else:
            card["expected_return_pct"] = None

        # STRICT FIDUCIARY FAIL-CLOSED PRINCIPLE:
        # If expected return <= 0 OR Base IV < Price (no margin of safety on baseline),
        # Kelly allocation MUST be 0.0%. Never allocate real capital on negative expected edge.
        #
        # The expected-return leg runs ONLY on weights the model supplied. Running it on invented
        # ones is what put a fabricated figure into published `reason` text. The Base-vs-Price leg
        # is deterministic and fires either way, so fail-closed behaviour is unchanged.
        edge_negative = bool(probs_ok and expected_return <= 0.0001)
        if (edge_negative or base_iv <= price) and (kelly_pct and kelly_pct > 0):
            why = []
            if edge_negative:
                why.append(f"expected return {expected_return*100:+.1f}%")
            if base_iv <= price:
                why.append(f"Base IV ${base_iv:.2f} vs Price ${price:.2f}")
            if not probs_ok:
                why.append("no scenario probabilities supplied, so the probability-weighted "
                           "edge test was SKIPPED")
            issues.append(f"Clamped Kelly fraction from {kelly_pct:.1f}% to 0.0% due to "
                          f"non-positive edge ({'; '.join(why)})")
            card["kelly_fraction_pct"] = 0.0
        elif kelly_pct is not None:
            # Enforce 25.0% institutional position cap
            card["kelly_fraction_pct"] = round(min(25.0, max(0.0, kelly_pct)), 2)
    else:
        if kelly_pct is not None:
            card["kelly_fraction_pct"] = round(min(25.0, max(0.0, kelly_pct)), 2)

    # 5. Payoff Skew Recalculation
    skew = payoff_skew(bull_iv, bear_iv, price)
    if skew is not None:
        old_skew = card.get("asymmetric_payoff_skew")
        if old_skew is None or abs(float(old_skew) - skew) > 0.1:
            if old_skew is not None:
                issues.append(f"Corrected asymmetric payoff skew from {old_skew}x to {skew}x")
            card["asymmetric_payoff_skew"] = skew

    # 6. Re-entry Tranches Monotonicity (Starter >= Core)
    tranches = card.get("reentry_tranches")
    if isinstance(tranches, dict):
        t1 = tranches.get("tranche_1_starter")
        t2 = tranches.get("tranche_2_core")
        if t1 is not None and t2 is not None:
            try:
                t1, t2 = float(t1), float(t2)
                if t1 < t2:
                    # Inversion: starter < core -> swap them to enforce dollar-cost averaging down
                    tranches["tranche_1_starter"] = t2
                    tranches["tranche_2_core"] = t1
                    issues.append(f"Repaired inverted re-entry tranches: set starter to ${t2:.2f}, core to ${t1:.2f}")
                else:
                    tranches["tranche_1_starter"] = t1
                    tranches["tranche_2_core"] = t2
            except (ValueError, TypeError):
                pass
        card["reentry_tranches"] = tranches

    # 7. Scores Clamping (Moat: 1-5, Conviction: 1-15)
    if card.get("business_quality_moat") is not None:
        try:
            card["business_quality_moat"] = round(min(5.0, max(1.0, float(card["business_quality_moat"]))), 1)
        except (ValueError, TypeError):
            pass

    if card.get("conviction_score") is not None:
        try:
            card["conviction_score"] = round(min(15.0, max(1.0, float(card["conviction_score"]))), 1)
        except (ValueError, TypeError):
            pass

    # 8. P4.4 — invalidation_rules must be a structured, checkable list. `checkable` means the
    # rule's `metric` is in the metric vocabulary (MOMENTUM_METRICS | FINANCIAL_METRICS, the
    # single source imported above); a rule missing any of the four required keys, or whose
    # comparator is not one of `_COMPARATORS`, cannot be evaluated and is dropped from the
    # sanitized list. Some (but not all) uncheckable is annotated `invalidation_partially_checkable`,
    # never silently dropped.
    #
    # THE CONTRACT IS FAIL when none of the supplied rules are checkable, when momentum_break_rule
    # / momentum_flip_condition name a metric outside SCR-10, or when entry_timing is outside its
    # three values — a thesis nobody can falsify, or a momentum rule that cannot be evaluated, is
    # an incomplete underwriting proposal. This is the SAME "fail closed" mechanism as the Kelly
    # edge clamp above (`is_valid` stays True — these are contract-QUALITY defects, not structural
    # ones like an inverted scenario, and must not pull an otherwise-coherent sample out of medoid
    # candidacy): Kelly is force-clamped to 0.0% and the issue text is recognised by
    # `depth_pipeline.fiduciary_verdict_gate`'s `"Clamped Kelly" in i` test, which turns it into a
    # violation and publishes `fiduciary_verdict: FAIL` — loud, capital sized to zero.
    raw_rules = card.get("invalidation_rules")
    rules_not_a_list = raw_rules is not None and not isinstance(raw_rules, list)
    rules = raw_rules if isinstance(raw_rules, list) else []

    sanitized_rules, checkable_count, uncheckable_count = [], 0, 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        has_shape = (
            rule.get("metric") is not None
            and rule.get("comparator") in _COMPARATORS
            and rule.get("threshold") is not None
            and rule.get("window") is not None
            and rule.get("source") is not None
        )
        if not has_shape:
            continue
        if rule["metric"] in _METRIC_VOCABULARY:
            checkable_count += 1
        else:
            uncheckable_count += 1
        sanitized_rules.append(dict(rule))
    card["invalidation_rules"] = sanitized_rules
    card["invalidation_partially_checkable"] = uncheckable_count > 0
    if uncheckable_count > 0:
        issues.append(f"invalidation_partially_checkable: {uncheckable_count} of "
                      f"{len(sanitized_rules)} rule(s) use a metric outside the vocabulary")

    thesis_defects = []
    if rules_not_a_list:
        thesis_defects.append("invalidation_rules is not a list")
    if checkable_count == 0:
        thesis_defects.append("zero checkable invalidation_rules — a thesis that cannot be "
                              "falsified is an incomplete underwriting proposal")
    # momentum_break_rule / momentum_flip_condition must name an SCR-10 (momentum) metric when
    # supplied — checked only when present; P4.2 requiring the field is a pack/TASK concern, not
    # this validator's.
    for field_name in ("momentum_break_rule", "momentum_flip_condition"):
        rule = card.get(field_name)
        if isinstance(rule, dict) and rule.get("metric") is not None:
            if rule["metric"] not in MOMENTUM_METRICS:
                thesis_defects.append(f"{field_name}.metric {rule['metric']!r} is not an "
                                      f"SCR-10 momentum metric")

    entry_timing = card.get("entry_timing")
    if entry_timing is not None and entry_timing not in _ENTRY_TIMINGS:
        thesis_defects.append(f"entry_timing {entry_timing!r} is not one of {_ENTRY_TIMINGS}")

    if thesis_defects:
        why = "; ".join(thesis_defects)
        prior_kelly = card.get("kelly_fraction_pct")
        issues.append(f"Clamped Kelly fraction from {prior_kelly}% to 0.0% — contract FAIL "
                      f"({why})")
        card["kelly_fraction_pct"] = 0.0

    return True, card, issues


# ---- revision 24 step 2b: the plausibility gate on the implied trajectory (BRIEF_R24_S2b_ranges_gate.md item 5) ---------------------------------
#
# Computed from the answer run's Base (the desk's `implied` block, financial_model_tool.implied_trajectory) and the pack's population ranges
# (tools/population_ranges.gate_bounds: the cohort's P5 and P95). Mathematics first: terminal growth at or above the discount rate is rejected
# (`terminal_growth_not_below_rate`). Then each implied metric against its cohort's P5-P95: inside passes; outside passes only with an
# input_rationale citation that resolves and is annotated `implausible_supported_<metric>`; outside without one is rejected,
# `implausible_unsupported_<metric>`. A metric with no measured cohort, or that the trajectory cannot compute, is annotated
# (`plausibility_not_measured:<metric>`, `plausibility_not_computable:<metric>`) and never rejected. Nothing is clamped and there is no other cap.
#
# Step 2c (PHASE_4_AMENDMENTS.md "Revision 24 step 2b", rulings 1, 2, 5-8 and 18; BRIEF_R24_S2c_ranges_fix.md items 1-6 and 9):
#   * the long-run margin is compared with the earnings-margin P5-P95 of the rebuilt range (ruling 2); terminal_ronic with the ROIC level five years on
#     (ruling 6; annotated only from step 2d, ANNOTATED_ONLY); the revenue CAGR to year 10 with the 10-year revenue CAGR (ruling 5);
#   * terminal_g has no population range (ruling 5): above the pack's printed long-run growth anchor (`terminal_g_anchor`, DEFAULTS and DATA 1.5) it
#     is an outlier needing an outlier-level citation (`implausible_supported_terminal_g` / `implausible_unsupported_terminal_g`); no anchor printed
#     is annotated `terminal_g_anchor_not_available`;
#   * a family the tables do not measure is annotated `no_population_cohort` (ruling 7) and the gate still runs the mathematics and the anchor check;
#   * cross-check 19, ruling B: the long-run margin's range is measured five years out while long_run_margin is the margin at the end of the fade, so
#     outside its P5-P95 it is ANNOTATED, never rejected: `implausible_supported_long_run_margin` with a citation that resolves,
#     `long_run_margin_outside_year5_range_unsupported` without one (within_p10_p90 is still computed against it for the citation level);
#   * cross-check 19, ruling C: a shrinking business - the record's 8-year ln-revenue OLS slope below 0 (the terminal table's own shrinking test), or
#     growth_trajectory classified shrinking - makes any terminal_g above 0 an outlier needing an outlier-level citation, as above the anchor;
#   * a citation resolves by crux_check's own acceptance rule (ruling 8): `crux_check.evidence_failure`, the one rule for both levels;
#   * the three classifications are checked against their allowed values (`invalid_classification_<name>`), and within_p10_p90 is computed from the
#     printed range: the analyst's declaration is kept, a mismatch is annotated (`within_p10_p90_mismatch:<input>`), and the citation level follows
#     the code's value - an input outside its printed P10-P90 without a citation that resolves is annotated `outlier_citation_missing:<input>`
#     (ruling 18; an annotation, never a rejection: the rejections are the P5-P95 and mathematics checks above).

PLAUSIBILITY_METRICS = ("long_run_margin", "revenue_cagr_10y", "terminal_ronic", "earnings_ratio_10y", "terminal_g")
# the metrics whose range is measured at another horizon than the input: outside P5-P95 without a resolving citation they are annotated
# (<metric>_<status>), never rejected - the long-run margin (cross-check 19 ruling B) and, from step 2d (the cross-check 19 follow-up), terminal_ronic
# against the ROIC level five years out. within_p10_p90 is still computed against their ranges for the citation level. The rejecting checks are the
# revenue CAGR to year 10, terminal_g (anchor and shrinking rule) and terminal growth at or above the rate.
ANNOTATED_ONLY = {"long_run_margin": "outside_year5_range_unsupported", "terminal_ronic": "outside_roic5_range_unsupported"}
# the input_rationale entries whose citation can support an outlier of each metric: the long-run margin by long_run_margin; the revenue growth to
# year 10 by the growth path (years 3-5) or the fade; the terminal return by terminal_ronic; terminal growth by terminal_g; year-10 earnings over
# base earnings (no measured cohort) by any of the margin and the growth path
RATIONALE_FOR = {"long_run_margin": ("long_run_margin",), "revenue_cagr_10y": ("growth_years_3_5", "fade_years"),
                 "terminal_ronic": ("terminal_ronic",), "earnings_ratio_10y": ("long_run_margin", "growth_years_3_5", "fade_years"),
                 "terminal_g": ("terminal_g",)}
# ruling 18: the allowed values of the three classifications (the TASK's and Section 12's)
CLASSIFICATIONS = {"margin_persistence": ("structural", "partly_structural", "transient"),
                   "cycle_position": ("trough", "mid", "peak", "not_cyclical"),
                   "growth_trajectory": ("accelerating", "steady", "decelerating", "shrinking")}
# the long-run inputs of input_rationale, and where the printed range each is read against comes from
RATIONALE_INPUTS = ("long_run_margin", "growth_years_3_5", "fade_years", "terminal_g", "terminal_ronic")


def _as_number(v):
    if v == "unlimited":
        return float("inf")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _citations_of(input_rationale, names):
    """The citations the analyst's input_rationale gives for `names`: each entry's `citation`, an object or a list of objects."""
    out = []
    ir = input_rationale if isinstance(input_rationale, dict) else {}
    for n in names:
        c = (ir.get(n) or {}).get("citation") if isinstance(ir.get(n), dict) else None
        if isinstance(c, dict):
            out.append(c)
        elif isinstance(c, list):
            out.extend(x for x in c if isinstance(x, dict))
    return out


def citation_resolves(citations, pack_text, calls, company, ticker):
    """(resolved, records): whether the citations pass crux_check's own acceptance rule for a crux entry (ruling 8 of step 2b: one rule for both
    levels) - at least one is company evidence, class pack_company (PRIMARY P#, DATA 3-6 or GUIDANCE) or fetched_page_naming_company (a page fetched
    in this sample that names the company), with its quote found verbatim - and crux_check's per-citation records."""
    import crux_check
    if not citations:
        return False, []
    recs = crux_check.classify_citations(citations, crux_check.pack_sources(pack_text), crux_check.fetched_texts(calls), company, ticker,
                                         crux_check.primary_items(pack_text))
    return crux_check.evidence_failure(recs) is None, recs


def _base_input(dcf, name):
    """The Base's own value of a long-run input, as the desk applied it (None when the desk output does not carry it)."""
    if name == "long_run_margin":
        return _as_number((dcf.get("long_run") or {}).get("long_run_margin"))
    if name in ("terminal_g", "terminal_ronic"):
        return _as_number(dcf.get(name))
    return None


def classification_check(classifications):
    """{name: {"value", "valid"}} and the annotations `invalid_classification_<name>` (ruling 18): a value is valid when, stripped and in lower
    case, it is one of CLASSIFICATIONS[name]; a missing value is not one of them."""
    recs, notes = {}, []
    c = classifications if isinstance(classifications, dict) else {}
    for name, allowed in CLASSIFICATIONS.items():
        v = c.get(name)
        norm = v.strip().lower() if isinstance(v, str) else v
        ok = isinstance(norm, str) and norm in allowed
        recs[name] = {"value": v, "valid": ok}
        if not ok:
            notes.append(f"invalid_classification_{name}")
    return recs, notes


def _shrinking(ranges, classifications):
    """(shrinking, basis) for cross-check 19 ruling C: the record's 8-year revenue trend below 0, or growth_trajectory classified shrinking."""
    tr = (ranges or {}).get("revenue_trend8") if isinstance(ranges, dict) else None
    gt = (classifications or {}).get("growth_trajectory") if isinstance(classifications, dict) else None
    gt = gt.strip().lower() if isinstance(gt, str) else gt
    basis = []
    if isinstance(tr, (int, float)) and not isinstance(tr, bool) and tr < 0:
        basis.append(f"the record's 8-year revenue trend {tr:+.4f} is below 0")
    if gt == "shrinking":
        basis.append("growth_trajectory is classified shrinking")
    return bool(basis), basis


def plausibility_gate(dcf, ranges, input_rationale=None, pack_text=None, calls=None, company=None, ticker=None, growth_anchor=None,
                      classifications=None):
    """The gate on one sample's answer run. `dcf` is the Base's desk output (it carries `implied`), `ranges` the pack's population ranges
    (facts["population_ranges"]), `input_rationale` the sample's SECTION 12 field, `growth_anchor` the pack's printed long-run nominal growth anchor
    (facts["terminal_g_anchor"]), `classifications` {margin_persistence, cycle_position, growth_trajectory} from SECTION 12. Returns {"verdict":
    "pass" | "reject" | "not_applicable", "reasons": [the rejection names], "annotations": [...], "metrics": {metric: {"value", "p5", "p95", "cohort",
    "n", "status", "citation"}}, "within_p10_p90": {input: {...}}, "classifications": {...}}. `not_applicable` for a finite cash-flow life (no long run
    to check) or no Base; the classifications are checked whatever the verdict."""
    import population_ranges
    out = {"verdict": "not_applicable", "reasons": [], "annotations": [], "metrics": {}, "within_p10_p90": {}, "classifications": {}}
    out["classifications"], notes = classification_check(classifications)
    out["annotations"] += notes
    if not isinstance(dcf, dict) or dcf.get("per_share_iv") is None:
        out["annotations"].append("no_answer_run_base")
        return out
    if dcf.get("finite_life_years") is not None:
        out["annotations"].append("finite_life_no_long_run")
        return out
    imp = dcf.get("implied") if isinstance(dcf.get("implied"), dict) else {}
    rate, tg = _as_number(dcf.get("discount_rate_applied")), _as_number(dcf.get("terminal_g"))
    if rate is None or tg is None or not tg < rate:
        out["reasons"].append("terminal_growth_not_below_rate")
    bounds = population_ranges.gate_bounds(ranges)
    anchor = _as_number(growth_anchor)
    values = {"long_run_margin": _as_number(imp.get("long_run_margin")), "revenue_cagr_10y": _as_number(imp.get("revenue_cagr_10y")),
              "terminal_ronic": _as_number(imp.get("terminal_ronic") if imp.get("terminal_ronic") is not None else dcf.get("terminal_ronic")),
              "earnings_ratio_10y": _as_number(imp.get("earnings_ratio_10y")), "terminal_g": tg}
    unmeasured_family = False
    shrinking, shrink_basis = _shrinking(ranges, classifications)
    for m in PLAUSIBILITY_METRICS:
        v = values[m]
        if m == "terminal_g":
            # ruling 5: no population range; the anchor the pack prints is the outlier threshold (at or below it is an ordinary choice); cross-check
            # 19 ruling C: for a shrinking business any terminal_g above 0 is an outlier too
            rec = {"value": v, "anchor": anchor, "shrinking": shrink_basis, "status": None, "citation": None}
            out["metrics"][m] = rec
            if anchor is None:
                out["annotations"].append("terminal_g_anchor_not_available")
            if v is None:
                rec["status"] = "not_computable"
                out["annotations"].append(f"plausibility_not_computable:{m}")
                continue
            if anchor is None and not shrinking:
                rec["status"] = "not_measured"
                continue
            outside = (anchor is not None and v > anchor) or (shrinking and v > 0)
        else:
            b = bounds.get(m)
            rec = {"value": v, "p5": None if b is None else b["p5"], "p95": None if b is None else b["p95"],
                   "cohort": None if b is None else b.get("cohort"), "n": None if b is None else b.get("n"), "status": None, "citation": None}
            out["metrics"][m] = rec
            if b is None:
                rec["status"] = "not_measured"
                out["annotations"].append(f"plausibility_not_measured:{m}")
                unmeasured_family = unmeasured_family or population_ranges.family_unmeasured(ranges, m)
                continue
            if v is None:
                rec["status"] = "not_computable"
                out["annotations"].append(f"plausibility_not_computable:{m}")
                continue
            outside = not (b["p5"] <= v <= b["p95"])
        if not outside:
            rec["status"] = "within"
            continue
        ok, recs = citation_resolves(_citations_of(input_rationale, RATIONALE_FOR[m]), pack_text, calls, company, ticker)
        rec["citation"] = recs
        if ok:
            rec["status"] = "supported"
            out["annotations"].append(f"implausible_supported_{m}")
        elif m in ANNOTATED_ONLY:
            # cross-check 19 ruling B: a year-5 range does not bound the margin at the end of the fade; the cross-check 19 follow-up (step 2d): the
            # ROIC level five years out does not bound the return on new investment in perpetuity either - annotated, never rejected
            rec["status"] = ANNOTATED_ONLY[m]
            out["annotations"].append(f"{m}_{ANNOTATED_ONLY[m]}")
        else:
            rec["status"] = "unsupported"
            out["reasons"].append(f"implausible_unsupported_{m}")
    if unmeasured_family:
        out["annotations"].append("no_population_cohort")
    # ruling 18: within_p10_p90 by code, from the printed range of each input (long_run_margin: the earnings-margin P10-P90; terminal_ronic: the ROIC
    # level's; terminal_g: at or below the growth anchor; the growth path and the fade have no printed P10-P90, so the in-range rationale applies)
    ir = input_rationale if isinstance(input_rationale, dict) else {}
    for name in RATIONALE_INPUTS:
        entry = ir.get(name) if isinstance(ir.get(name), dict) else {}
        declared = entry.get("within_p10_p90")
        declared = declared if isinstance(declared, bool) else None
        value, computed, basis = _base_input(dcf, name), None, None
        if name in ("long_run_margin", "terminal_ronic"):
            b = bounds.get(name)
            if b is not None and value is not None:
                computed, basis = (b["p10"] <= value <= b["p90"]), f"the printed P10-P90 {b['p10']:.4f} to {b['p90']:.4f}"
            else:
                basis = "no printed P10-P90" if b is None else "the Base carries no value"
        elif name == "terminal_g":
            if value is not None and (anchor is not None or shrinking):
                computed = (anchor is None or value <= anchor) and not (shrinking and value > 0)
                basis = "; ".join(([f"the long-run growth anchor {anchor:.4f}"] if anchor is not None else [])
                                  + ([f"above 0 for a shrinking business ({', '.join(shrink_basis)})"] if shrinking else []))
            else:
                basis = "no growth anchor printed" if anchor is None else "the Base carries no value"
        else:
            basis = "no printed P10-P90"
        level = "outlier" if computed is False else "in_range"
        rec = {"value": value, "declared": declared, "computed": computed, "basis": basis, "citation_level": level, "citation_resolves": None}
        if declared is not None and computed is not None and declared != computed:
            out["annotations"].append(f"within_p10_p90_mismatch:{name}")
        if level == "outlier":
            ok, _recs = citation_resolves(_citations_of(ir, (name,)), pack_text, calls, company, ticker)
            rec["citation_resolves"] = ok
            if not ok:
                out["annotations"].append(f"outlier_citation_missing:{name}")
        out["within_p10_p90"][name] = rec
    out["verdict"] = "reject" if out["reasons"] else "pass"
    return out
