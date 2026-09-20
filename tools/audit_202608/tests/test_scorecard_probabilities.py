"""The model's scenario probabilities must survive extraction and be used honestly.

The chain, verified end to end on 2026-09-20:

  * `capability_test.py:895-897` instructs the model to emit `base_probability`,
    `bull_probability`, `bear_probability` in the ```json:underwriting block, and GEV's sample 2
    really did emit 0.4 / 0.35 / 0.25.
  * `extract_scorecard` copied **only the keys already in its own 9-key card** (`for k in card`),
    so all three were discarded unrecoverably - `parsed` goes out of scope and the function's
    only return is that whitelist.
  * `select_medoid_scorecard`'s summary never carried them, so `CONTRACT_PASSTHROUGH`'s three
    probability entries in `depth_pipeline` were dead code.
  * `has_probs` in `fiduciary_gate` was therefore ALWAYS False, routing every production
    contract into hardcoded `0.50 / 0.30 / 0.20`.

So the validator enforced a simplex over numbers it invented, and a Kelly clamp could be
justified in published `reason` text by an expected return the model never produced.

Two further defects in that branch, both measured by executing it:

  * `card.get(k) or 0.50` treats a legitimately supplied `0.0` as missing.
  * Supplying SOME probabilities and defaulting the rest blends the two: base 0.7 + bull 0.2 +
    defaulted bear 0.2 sums to **1.1**, and 0.6 + 0.9 + 0.2 sums to **1.7** - a fabricated
    +111.0% expected return - while `issues` stays empty.
"""
import json

import pytest

from tools.audit_202608.consensus_valuation import extract_scorecard, select_medoid_scorecard
from tools.audit_202608.fiduciary_gate import validate_fiduciary_contract


# ---- extraction ------------------------------------------------------------------------

def _report(with_probs=True):
    card = {
        "base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
        "conviction_score": 12.0, "business_quality_moat": 4.0, "kelly_fraction_pct": 10.0,
        "reentry_tranches": {"tranche_1_starter": 95.0, "tranche_2_core": 80.0},
        "thesis_invalidation_trigger": "Backlog declines for two quarters.",
    }
    if with_probs:
        card.update({"base_probability": 0.4, "bull_probability": 0.35, "bear_probability": 0.25})
    return "```json:underwriting\n" + json.dumps(card) + "\n```\n"


def test_extract_scorecard_carries_the_models_probabilities():
    card = extract_scorecard(_report(), 100.0)
    assert card["base_probability"] == 0.4
    assert card["bull_probability"] == 0.35
    assert card["bear_probability"] == 0.25


def test_extract_scorecard_reports_absent_probabilities_as_none():
    # Present-and-None, so a consumer can tell "absent" from "key never existed".
    card = extract_scorecard(_report(with_probs=False), 100.0)
    assert card["base_probability"] is None
    assert card["bull_probability"] is None
    assert card["bear_probability"] is None


def _runs():
    def run(n, iv, probs):
        sc = {"base_iv": iv, "bull_iv": iv * 1.4, "bear_iv": iv * 0.7,
              "business_quality_moat": 4.0, "kelly_fraction_pct": 10.0,
              "reentry_tranches": {"tranche_1_starter": iv * 0.9, "tranche_2_core": iv * 0.8},
              "thesis_invalidation_trigger": f"Trigger {n}"}
        sc.update(probs)
        return {"sample": n, "iv": iv, "plausible": True, "truncated": False, "scorecard": sc}
    return [run(1, 100.0, {"base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2}),
            run(2, 102.0, {"base_probability": 0.4, "bull_probability": 0.35, "bear_probability": 0.25}),
            run(3, 101.0, {"base_probability": 0.4, "bull_probability": 0.35, "bear_probability": 0.25})]


def test_medoid_summary_carries_the_probabilities_not_just_the_ivs():
    _, summary = select_medoid_scorecard(_runs(), 100.0)
    assert summary["base_probability"] is not None
    assert summary["bull_probability"] is not None
    assert summary["bear_probability"] is not None
    assert summary["base_probability"] + summary["bull_probability"] + summary["bear_probability"] \
        == pytest.approx(1.0, abs=0.01)


def test_medoid_summary_marks_defaulted_when_the_model_supplied_none():
    runs = _runs()
    for r in runs:
        for k in ("base_probability", "bull_probability", "bear_probability"):
            r["scorecard"].pop(k, None)
    _, summary = select_medoid_scorecard(runs, 100.0)
    assert summary["probabilities_defaulted"] is True
    assert summary["base_probability"] is None


# ---- the gate: a legal simplex, or no probabilities at all ------------------------------

def test_complete_probabilities_are_normalised_to_one():
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
            "base_probability": 0.6, "bull_probability": 0.9, "bear_probability": 0.2}
    ok, san, issues = validate_fiduciary_contract(card, 100.0)
    assert ok is True
    assert san["base_probability"] + san["bull_probability"] + san["bear_probability"] \
        == pytest.approx(1.0, abs=0.001)
    assert san["probabilities_defaulted"] is False


def test_partial_probabilities_never_yield_a_simplex_above_one():
    # Measured before the fix: 0.7 / 0.2 / defaulted 0.2 summed to 1.1 with issues == [].
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
            "base_probability": 0.7, "bull_probability": 0.2}
    ok, san, issues = validate_fiduciary_contract(card, 100.0)
    assert ok is True
    assert san["probabilities_defaulted"] is True
    assert san["base_probability"] is None
    assert san["bull_probability"] is None
    assert san["bear_probability"] is None
    assert any("probabilit" in i.lower() for i in issues)


def test_partial_probabilities_do_not_fabricate_an_expected_return():
    # Measured before the fix: 0.6 / 0.9 / defaulted 0.2 gave +111.0% expected return.
    card = {"base_iv": 100.0, "bull_iv": 110.0, "bear_iv": 90.0,
            "base_probability": 0.6, "bull_probability": 0.9}
    ok, san, _ = validate_fiduciary_contract(card, 100.0)
    assert san["expected_iv"] is None
    assert san["expected_return_pct"] is None


def test_a_supplied_zero_probability_is_respected():
    # `card.get(k) or 0.50` silently replaced a legitimate 0.0 with the default.
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
            "base_probability": 0.0, "bull_probability": 0.5, "bear_probability": 0.5}
    ok, san, _ = validate_fiduciary_contract(card, 100.0)
    assert ok is True
    assert san["base_probability"] == 0.0
    assert san["probabilities_defaulted"] is False


def test_negative_probability_is_unusable_not_a_silent_default():
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
            "base_probability": -0.2, "bull_probability": 0.7, "bear_probability": 0.5}
    ok, san, issues = validate_fiduciary_contract(card, 100.0)
    assert san["probabilities_defaulted"] is True
    assert san["base_probability"] is None
    assert any("probabilit" in i.lower() for i in issues)


def test_non_numeric_probability_is_unusable():
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0,
            "base_probability": "high", "bull_probability": 0.3, "bear_probability": 0.2}
    ok, san, _ = validate_fiduciary_contract(card, 100.0)
    assert san["probabilities_defaulted"] is True
    assert san["base_probability"] is None


def test_absent_probabilities_are_defaulted_without_a_defect_issue():
    # No probabilities supplied at all is ordinary absence (legacy rows, callers that never had
    # them) - not a defect. The clamp message discloses the skipped leg where it matters.
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0}
    ok, san, issues = validate_fiduciary_contract(card, 100.0)
    assert san["probabilities_defaulted"] is True
    assert issues == []


# ---- the edge test ---------------------------------------------------------------------

def test_genuine_negative_edge_still_clamps_and_cites_the_return():
    card = {"base_iv": 90.0, "bull_iv": 110.0, "bear_iv": 50.0,
            "base_probability": 0.5, "bull_probability": 0.2, "bear_probability": 0.3,
            "kelly_fraction_pct": 8.0}
    ok, san, issues = validate_fiduciary_contract(card, 100.0)
    assert san["kelly_fraction_pct"] == 0.0
    msg = " ".join(issues)
    assert "clamped" in msg.lower()
    assert "expected return" in msg.lower()


def test_defaulted_priors_clamp_on_base_vs_price_without_quoting_an_invented_return():
    # Base < price on its own is deterministic and correct. What must NOT appear is a number
    # derived from probabilities the model never supplied - that is the Phase 9 defect.
    card = {"base_iv": 90.0, "bull_iv": 110.0, "bear_iv": 50.0, "kelly_fraction_pct": 8.0}
    ok, san, issues = validate_fiduciary_contract(card, 100.0)
    assert san["kelly_fraction_pct"] == 0.0
    msg = " ".join(issues)
    assert "clamped" in msg.lower()
    assert "expected return" not in msg.lower()
    assert "skipped" in msg.lower()


def test_defaulted_priors_do_not_clamp_when_the_base_has_margin_of_safety():
    # base 120 > price 100, so the deterministic leg does not fire. With no probabilities the
    # expected-return leg must not be able to invent a negative edge either way.
    card = {"base_iv": 120.0, "bull_iv": 160.0, "bear_iv": 80.0, "kelly_fraction_pct": 8.0}
    ok, san, _ = validate_fiduciary_contract(card, 100.0)
    assert san["kelly_fraction_pct"] == 8.0
