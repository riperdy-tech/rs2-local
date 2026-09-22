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
    return sc.get("base_iv") or sc.get("median_iv")


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
    if price and price > 0 and bull_iv is not None and bear_iv is not None:
        downside = price - bear_iv
        upside = bull_iv - price
        if downside <= 0:
            skew = 99.9 if upside > 0 else 0.0
        else:
            skew = round(upside / downside, 2)

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

    return True, card, issues
