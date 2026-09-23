"""P4.9/C1 — size_hint = min(dispersion, mos, conviction, risk).

`mos_bucket`, `conviction_bucket`, `risk_bucket`/`risk_flag_active`, `_min_bucket` are pure
(risk_bucket excepted — it reads the shock register off disk, monkeypatched here) so the bucket
logic is unit-tested directly; `band_verdict` integration tests exercise the composite end to
end. The repo-root conftest.py's autouse fixture defaults every test's `risk_bucket()` to
('full', None) — tests here that care about the risk component override it explicitly.
"""
import json

import pytest

import depth_pipeline as dp
from depth_pipeline import band_verdict

# Captured at import time (module collection), before the repo-root conftest.py's autouse
# fixture monkeypatches `dp.risk_bucket` to a fixed ('full', None) for every test — a direct
# reference to the SAME function object, so it stays testable regardless. Its bare internal
# call to `risk_flag_active()` still resolves through depth_pipeline's module namespace at call
# time, so monkeypatching `dp.risk_flag_active` still reaches it correctly.
_real_risk_bucket = dp.risk_bucket

# P4.4 — a minimal, checkable invalidation_rules pair, so band_verdict's fiduciary gate does not
# clamp Kelly to zero (and force size_hint to "zero") for an unrelated reason in these fixtures.
VALID_INVALIDATION_RULES = [
    {"metric": "mom_12_1", "comparator": "<", "threshold": -20.0,
     "window": "next reported quarter", "source": "momentum_state.json"},
    {"metric": "revenue_yoy_pct", "comparator": "<", "threshold": 0.0,
     "window": "next reported quarter", "source": "fundamentals_quarterly.json"},
]


# ---- mos_bucket -----------------------------------------------------------------------------

def test_mos_bucket_thresholds():
    assert dp.mos_bucket(30.0) == "full"
    assert dp.mos_bucket(25.0) == "full"          # inclusive
    assert dp.mos_bucket(24.9) == "half"
    assert dp.mos_bucket(10.0) == "half"           # inclusive
    assert dp.mos_bucket(9.9) == "quarter"
    assert dp.mos_bucket(-50.0) == "quarter"
    assert dp.mos_bucket(0.0) == "quarter"         # 0.0 is a value, evaluated normally


def test_mos_bucket_none_is_conservative_not_a_crash():
    assert dp.mos_bucket(None) == "quarter"


# ---- conviction_bucket ------------------------------------------------------------------------

def test_conviction_bucket_thresholds():
    assert dp.conviction_bucket(15.0) == "full"
    assert dp.conviction_bucket(11.0) == "full"    # inclusive
    assert dp.conviction_bucket(10.9) == "half"
    assert dp.conviction_bucket(8.0) == "half"     # inclusive
    assert dp.conviction_bucket(7.9) == "quarter"
    assert dp.conviction_bucket(0.0) == "quarter"


def test_conviction_bucket_none_is_conservative_not_a_crash():
    assert dp.conviction_bucket(None) == "quarter"


# ---- _min_bucket ------------------------------------------------------------------------------

def test_min_bucket_picks_the_most_conservative():
    assert dp._min_bucket("full", "half", "quarter") == "quarter"
    assert dp._min_bucket("full", "full", "full") == "full"
    assert dp._min_bucket("half", "full") == "half"


def test_min_bucket_ignores_none_components():
    assert dp._min_bucket("full", "full", None) == "full"
    assert dp._min_bucket("quarter", None, None) == "quarter"


def test_min_bucket_none_when_every_component_is_none():
    assert dp._min_bucket(None, None) is None


# ---- risk_flag_active / risk_bucket — real filesystem read, monkeypatched -------------------

def test_risk_flag_active_none_when_register_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(dp.CONFIG, "mri_outputs_dir", str(tmp_path / "nope"))
    assert dp.risk_flag_active() is None


def test_risk_flag_active_none_when_flag_not_published(tmp_path, monkeypatch):
    monkeypatch.setitem(dp.CONFIG, "mri_outputs_dir", str(tmp_path))
    (tmp_path / "shock_register.json").write_text(
        json.dumps({"asof": "2026-09-24", "shocks": [], "risk_flags": []}), encoding="utf-8")
    assert dp.risk_flag_active() is None


def test_risk_flag_active_true_when_active(tmp_path, monkeypatch):
    monkeypatch.setitem(dp.CONFIG, "mri_outputs_dir", str(tmp_path))
    (tmp_path / "shock_register.json").write_text(json.dumps({
        "asof": "2026-09-24", "shocks": [],
        "risk_flags": [{"id": "elevated_volatility_ahead", "active": True,
                        "meaning": "forward 3m realised vol elevated"}],
    }), encoding="utf-8")
    assert dp.risk_flag_active() is True


def test_risk_flag_active_false_when_confirmed_inactive(tmp_path, monkeypatch):
    monkeypatch.setitem(dp.CONFIG, "mri_outputs_dir", str(tmp_path))
    (tmp_path / "shock_register.json").write_text(json.dumps({
        "asof": "2026-09-24", "shocks": [],
        "risk_flags": [{"id": "elevated_volatility_ahead", "active": False}],
    }), encoding="utf-8")
    assert dp.risk_flag_active() is False


def test_risk_bucket_half_when_active(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "risk_flag_active", lambda flag_id="elevated_volatility_ahead": True)
    assert _real_risk_bucket() == ("half", None)


def test_risk_bucket_full_when_confirmed_inactive(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "risk_flag_active", lambda flag_id="elevated_volatility_ahead": False)
    assert _real_risk_bucket() == ("full", None)


def test_risk_bucket_none_not_full_when_unavailable(monkeypatch):
    monkeypatch.setattr(dp, "risk_flag_active", lambda flag_id="elevated_volatility_ahead": None)
    bucket, flag = _real_risk_bucket()
    assert bucket is None            # explicitly NOT "full" — never silently sizes up
    assert flag == "risk_flag_unavailable"


# ---- band_verdict integration ------------------------------------------------------------------

def _doc(price, iv_a, iv_b, conviction=None, moat=None):
    scorecard = {"base_iv": iv_a, "median_iv": (iv_a + iv_b) / 2,
                "invalidation_rules": VALID_INVALIDATION_RULES}
    if conviction is not None:
        scorecard["median_conviction_score"] = conviction
    if moat is not None:
        scorecard["median_quality_moat"] = moat
    return {
        "ticker": "SZC", "price": price, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": (iv_a + iv_b) / 2, "early_stop": True,
        "runs": [{"sample": 1, "iv": iv_a, "plausible": True, "truncated": False},
                 {"sample": 2, "iv": iv_b, "plausible": True, "truncated": False}],
        "scorecard": scorecard,
    }


def test_size_hint_is_the_minimum_of_all_four_components(monkeypatch):
    # Tight spread (dispersion "full"), MoS 30% (mos "full"), conviction 12 ("full"), but risk
    # active -> "half" is the binding constraint.
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("half", None))
    doc = _doc(price=100.0, iv_a=128.0, iv_b=132.0, conviction=12.0)   # MoS ~28-32%
    v = band_verdict(doc)
    assert v["size_components"]["dispersion"]["bucket"] == "full"
    assert v["size_components"]["mos"]["bucket"] == "full"
    assert v["size_components"]["conviction"]["bucket"] == "full"
    assert v["size_components"]["risk"]["bucket"] == "half"
    assert v["size_hint"] == "half"


def test_size_hint_capped_by_low_conviction_alone():
    doc = _doc(price=100.0, iv_a=128.0, iv_b=132.0, conviction=5.0)
    v = band_verdict(doc)
    assert v["size_components"]["conviction"]["bucket"] == "quarter"
    assert v["size_hint"] == "quarter"


def test_size_components_records_every_component_and_its_source():
    doc = _doc(price=100.0, iv_a=128.0, iv_b=132.0, conviction=12.0)
    v = band_verdict(doc)
    comps = v["size_components"]
    for key in ("dispersion", "mos", "conviction", "risk"):
        assert key in comps
        assert "bucket" in comps[key]
        assert "source" in comps[key]


def test_risk_flag_unavailable_adds_flag_and_excludes_risk_from_min(monkeypatch):
    monkeypatch.setattr(dp, "risk_bucket", lambda: (None, "risk_flag_unavailable"))
    doc = _doc(price=100.0, iv_a=128.0, iv_b=132.0, conviction=12.0)
    v = band_verdict(doc)
    assert v["size_components"]["risk"]["bucket"] is None
    assert "risk_flag_unavailable" in v["flags"]
    # Risk excluded from min(): dispersion/mos/conviction are all "full" -> size stays "full",
    # NOT dragged to "quarter" or "zero" by the missing data.
    assert v["size_hint"] == "full"


def test_size_components_none_on_not_usable_verdict():
    v = band_verdict({"ticker": "SZC", "price": 100.0, "runs": []})
    assert v["direction"] == "NOT_USABLE"
    assert v["size_components"] is None


def test_active_shocks_at_verdict_lands_on_the_verdict():
    """T3 stamps active_shocks_at_verdict into consensus.json; band_verdict must carry it onto
    the published verdict unchanged (C1)."""
    doc = _doc(price=100.0, iv_a=128.0, iv_b=132.0, conviction=12.0)
    doc["active_shocks_at_verdict"] = [
        {"shock_id": "volatility", "severity": 1, "direction": "up", "onset_date": "2026-09-01"}]
    v = band_verdict(doc)
    assert v["active_shocks_at_verdict"] == doc["active_shocks_at_verdict"]
