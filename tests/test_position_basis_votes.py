"""APH (b): position_basis is resolved from the VALID declarations of every basis sample (majority,
the medoid breaking a tie), not from the medoid's declaration alone.

APH s2, the medoid, declared `value` at hold, which is invalid, so the basis became `none` and s1's
valid `momentum` declaration was ignored: published hold + none at quarter size, where the design
gives hold + momentum at half size.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_ORIG_STDOUT = sys.stdout
import depth_pipeline as dp  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT
import momentum_basis as mb  # noqa: E402

BREAK = {"metric": "mom_6m", "comparator": "<", "threshold": 0, "window_days": 180}
# the two APH (b) contracts, basis fields as recorded
APH_S1 = {"position_basis": "momentum", "momentum_view": "contradicting", "entry_timing": "buy_now",
          "momentum_evidence": "8-K 2026-07-29: record Q2, orders $10.7B, book-to-bill 1.23x",
          "momentum_break_rule": BREAK,
          "momentum_flip_condition": {"metric": "high_52w_distance", "comparator": "<=",
                                      "threshold": -25, "window_days": 365},
          "verdict_label": "hold", "base_iv": 88.15}
APH_S2 = {"position_basis": "value", "momentum_view": "confirming", "entry_timing": "buy_now",
          "momentum_evidence": None, "momentum_break_rule": BREAK,
          "momentum_flip_condition": {"metric": "high_52w_distance", "comparator": "<",
                                      "threshold": -15, "window_days": 30},
          "verdict_label": "undervalued", "base_iv": 88.13}
APH_STATE = {"price_asof": "2026-09-17 18:47", "mom_12_1": 0.2882, "mom_6m": 0.3103,
             "high_52w_distance": -0.0625, "regime_shift_down": False, "mom_z_universe": 0.535}


def _aph_doc():
    summary = dict(APH_S2, median_iv=88.14, medoid_sample=2, median_conviction_score=9)
    return {"ticker": "APH", "price": 83.08, "samples_run": 2, "converged": True, "spread_pct": 0.0,
            "median_iv": 88.14, "early_stop": False,
            "runs": [{"sample": 1, "iv": 88.15, "plausible": True, "truncated": False,
                      "basis": True, "scorecard": APH_S1},
                     {"sample": 2, "iv": 88.13, "plausible": True, "truncated": False,
                      "basis": True, "scorecard": APH_S2}],
            "position_basis_votes": {"momentum": 1, "value": 1},
            "scorecard": summary, "momentum_state": APH_STATE}


def test_aph_resolves_to_momentum_from_the_valid_vote(monkeypatch):
    monkeypatch.setattr(mb, "revenue_ttm_yoy", lambda t: 0.20)
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("full", None))
    # the fixture carries the basis fields only; the recorded APH contract passed the fiduciary gate
    monkeypatch.setattr(dp, "validate_fiduciary_contract", lambda card, price: (True, card, []))
    v = dp.band_verdict(_aph_doc())
    assert v["direction"] == "hold"
    assert v["position_basis"] == "momentum" and v["position_basis_source_sample"] == 1
    assert v["position_basis_declared"] == "value"                   # the medoid's, as recorded
    assert "position_basis_mismatch:value_requires_undervalued" in v["flags"]
    # the break rule and flip condition travel with the basis they belong to
    assert v["momentum_break_rule"] == BREAK
    assert v["momentum_flip_condition"]["window_days"] == 365
    assert v["momentum_eligibility"]["eligible"] is True
    assert v["size_hint"] == "half" and v["size_components"]["basis"]["bucket"] == "half"


def _run(sample, iv, sc):
    return {"sample": sample, "iv": iv, "scorecard": sc}


MOM = {"position_basis": "momentum", "entry_timing": "buy_now", "momentum_evidence": "e",
       "momentum_break_rule": BREAK}
NONE = {"position_basis": None}
VALUE = {"position_basis": "value"}


def test_the_majority_wins():
    runs = [_run(1, 100, MOM), _run(2, 101, MOM), _run(3, 102, NONE)]
    basis, source, invalid = dp.resolve_position_basis(runs, 3, "hold")
    assert basis == "momentum" and source["sample"] == 2 and invalid == []   # nearest the medoid


@pytest.mark.parametrize("medoid, expected", [(1, "momentum"), (2, "none")])
def test_the_medoid_breaks_a_tie(medoid, expected):
    runs = [_run(1, 100, MOM), _run(2, 101, NONE)]
    assert dp.resolve_position_basis(runs, medoid, "hold")[0] == expected


def test_a_tie_the_medoid_cannot_break_is_none():
    runs = [_run(1, 100, MOM), _run(2, 101, NONE), _run(3, 102, VALUE)]
    basis, _, invalid = dp.resolve_position_basis(runs, 3, "hold")
    assert basis == "none" and invalid == [(3, "value_requires_undervalued")]


def test_value_is_valid_only_on_an_undervalued_call():
    runs = [_run(1, 100, VALUE), _run(2, 101, VALUE)]
    assert dp.resolve_position_basis(runs, 1, "undervalued")[0] == "value"
    basis, source, invalid = dp.resolve_position_basis(runs, 1, "hold")
    assert basis == "none" and source is None and len(invalid) == 2


@pytest.mark.parametrize("field, value, unmet", [
    ("entry_timing", "wait", "entry_timing"),
    ("momentum_evidence", " ", "momentum_evidence"),
    ("momentum_break_rule", {"comparator": "<"}, "momentum_break_rule")])
def test_each_momentum_requirement_is_checked_per_sample(field, value, unmet):
    runs = [_run(1, 100, dict(MOM, **{field: value})), _run(2, 101, MOM)]
    basis, source, invalid = dp.resolve_position_basis(runs, 1, "hold")
    assert basis == "momentum" and source["sample"] == 2 and invalid == [(1, unmet)]
    assert dp.resolve_position_basis(runs, 1, "undervalued")[2] == [(1, "direction"), (2, "direction")]
