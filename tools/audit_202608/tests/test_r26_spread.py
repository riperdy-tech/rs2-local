"""Revision 26, S3 spread attribution (tools/r26_spread.py). Synthetic value functions over the forecast fields, so every expected figure is exact."""
import copy
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import r26_spread as rs  # noqa: E402

APPROX = dict(rel=1e-12, abs=1e-12)


def _sc(prob, lr=0.12, tr="linear"):
    sc = {"near_term": {"rev_growth": [0.05, 0.06], "op_margin": [0.10, 0.11], "fact_ids": ["F1"]},
          "normalized": {"year": 5, "rev_growth": 0.04, "baseline": "median", "delta_pts": 1.0, "fact_ids": ["F2"], "reason": "r"},
          "transition": tr, "long_run_margin_op": lr, "terminal_g": 0.03, "terminal_ronic": 0.15, "fade_years": 5, "prob": prob}
    if tr != "linear":
        sc["transition_year"] = 4
    return sc


def _fc(dr=0.09, lr=0.12):
    return {"discount_rate": dr, "frame": "equity", "scenarios": {"Base": _sc(0.5, lr), "Bull": _sc(0.25, lr + 0.02), "Bear": _sc(0.25, lr - 0.02)}}


def additive(fc):
    """No interaction between groups: 100 + 1000 x Base long-run margin - 500 x discount rate."""
    return 100.0 + 1000.0 * fc["scenarios"]["Base"]["long_run_margin_op"] - 500.0 * fc["discount_rate"]


def multiplicative(fc):
    """A strong interaction: long-run margin over the discount rate."""
    return 1000.0 * fc["scenarios"]["Base"]["long_run_margin_op"] / fc["discount_rate"]


def test_only_discount_differs():
    samples = [_fc(dr=0.08), _fc(dr=0.09), _fc(dr=0.10)]
    vals = [additive(s) for s in samples]                       # 180, 175, 170 -> reference index 1
    out = rs.attribute_spread(samples, additive)
    assert out["status"] == "ok" and out["reference_index"] == 1
    assert out["base_values"] == pytest.approx(vals, **APPROX)
    assert out["spread"] == pytest.approx((180.0 - 170.0) / 175.0, **APPROX)
    assert out["dominant_group"] == "discount"
    g = out["groups"]["discount"]
    assert g["spread_if_only_G_differs"] == pytest.approx(out["spread"], **APPROX)
    assert g["swap_in"] == pytest.approx(5.0 / 175.0, **APPROX) and g["swap_out"] == pytest.approx(5.0 / 175.0, **APPROX)
    for name in ("near_term", "normalized", "long_run_margin", "terminal", "probabilities"):
        assert out["groups"][name]["swap_in"] == 0.0 and out["groups"][name]["swap_out"] == 0.0     # 0.0 is a value
        assert out["groups"][name]["spread_if_only_G_differs"] == 0.0
    assert out["interaction_note"] is None
    assert all(c["matches_sample_value"] for c in out["coverage"])


def test_two_groups_differ_additive():
    # sample 0: lr 0.10, dr 0.09 -> 155; sample 1: lr 0.12, dr 0.09 -> 175 (reference); sample 2: lr 0.12, dr 0.07 -> 185
    samples = [_fc(dr=0.09, lr=0.10), _fc(dr=0.09, lr=0.12), _fc(dr=0.07, lr=0.12)]
    out = rs.attribute_spread(samples, additive)
    assert out["reference_index"] == 1
    lr, dc = out["groups"]["long_run_margin"], out["groups"]["discount"]
    assert lr["swap_in"] == pytest.approx((20.0 + 0.0) / 2 / 175.0, **APPROX)
    assert lr["swap_out"] == pytest.approx((20.0 + 0.0) / 2 / 175.0, **APPROX)
    assert dc["swap_in"] == pytest.approx((0.0 + 10.0) / 2 / 175.0, **APPROX)
    assert lr["spread_if_only_G_differs"] == pytest.approx(20.0 / 175.0, **APPROX)     # values 155, 175, 175
    assert dc["spread_if_only_G_differs"] == pytest.approx(10.0 / 175.0, **APPROX)     # values 175, 175, 185
    assert out["groups"]["near_term"]["spread_if_only_G_differs"] == 0.0
    assert out["spread"] == pytest.approx(30.0 / 175.0, **APPROX)
    assert out["dominant_group"] == "long_run_margin" and "dominant_group_tied" not in out["stamps"]
    assert out["interaction_note"] is None                       # additive: single effects add to the total exactly


def test_two_groups_differ_with_interaction():
    # one sample moves both groups at once; the ratio makes the single effects not add up
    samples = [_fc(dr=0.09, lr=0.12), _fc(dr=0.10, lr=0.13), _fc(dr=0.05, lr=0.24)]
    out = rs.attribute_spread(samples, multiplicative)
    vals = [multiplicative(s) for s in samples]                 # 1333.3, 1300, 4800 -> reference index 0
    assert out["reference_index"] == 0
    assert out["base_values"] == pytest.approx(vals, **APPROX)
    v_ref = vals[0]
    j2 = next(p for p in out["groups"]["discount"]["per_sample"] if p["index"] == 2)
    assert j2["swap_in_value"] == pytest.approx(1000 * 0.12 / 0.05, **APPROX)
    assert j2["swap_in_change"] == pytest.approx((1000 * 0.12 / 0.05 - v_ref) / v_ref, **APPROX)
    assert j2["swap_out_value"] == pytest.approx(1000 * 0.24 / 0.09, **APPROX)
    assert out["interaction_note"] is not None and "sample 2" in out["interaction_note"]
    assert all(c["matches_sample_value"] for c in out["coverage"])


def test_swap_moves_transition_with_the_normalized_group():
    a, b = _fc(), _fc()
    for sc in b["scenarios"].values():
        sc["transition"], sc["transition_year"], sc["normalized"]["year"] = "hold_then_linear", 4, 4
    h = rs.swap_group(b, a, "normalized")
    for sc in h["scenarios"].values():
        assert sc["transition"] == "linear" and "transition_year" not in sc and sc["normalized"]["year"] == 5
    h2 = rs.swap_group(a, b, "normalized")
    assert all(sc["transition_year"] == 4 for sc in h2["scenarios"].values())
    assert a == _fc()                                            # the inputs are not mutated


def test_failed_valuation_is_recorded_not_defaulted():
    def fn(fc):                                                  # refuses a discount rate above 0.095 (like a desk refusal)
        return None if fc["discount_rate"] > 0.095 else additive(fc)

    samples = [_fc(dr=0.08), _fc(dr=0.09), _fc(dr=0.10), _fc(dr=0.085)]
    out = rs.attribute_spread(samples, fn)
    assert out["unvalued"] == [2] and out["base_values"][2] is None
    assert out["reference_index"] == 3                         # valued 180, 175, 177.5 -> median 177.5
    assert out["groups"]["discount"]["failed"] == []
    # a hybrid that fails: the reference given a refused discount rate
    samples = [{"forecast": _fc(dr=0.08, lr=0.13), "base_value": 190.0}, {"forecast": _fc(dr=0.09), "base_value": 175.0},
               {"forecast": _fc(dr=0.08, lr=0.10), "base_value": 159.0}]
    def fn2(fc):
        return None if fc["discount_rate"] == 0.09 and fc["scenarios"]["Base"]["long_run_margin_op"] != 0.12 else additive(fc)
    out = rs.attribute_spread(samples, fn2)
    assert out["reference_index"] == 1
    d = out["groups"]["discount"]
    assert {"index": 0, "direction": "swap_out"} in d["failed"] and {"index": 2, "direction": "swap_out"} in d["failed"]
    assert d["swap_out"] is None and "partial_failed_valuations" in d["stamps"]
    assert all(p["swap_out_value"] is None for p in d["per_sample"])
    assert any(x.get("status") == "not_checked_failed_valuations" for x in out["interaction"])
    assert out["stored_value_mismatch"] == [{"index": 2, "stored": 159.0, "value_fn": 160.0}]


def test_not_enough_samples():
    assert rs.attribute_spread([_fc()], additive)["status"] == "not_enough_samples"
    assert rs.attribute_spread([], additive)["status"] == "not_enough_samples"
    out = rs.attribute_spread([_fc(), _fc(dr=0.2)], lambda fc: None if fc["discount_rate"] > 0.1 else additive(fc))
    assert out["status"] == "not_enough_samples" and out["unvalued"] == [1]
