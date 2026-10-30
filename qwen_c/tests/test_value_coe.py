"""SPEC_m3q §2: qwen_c/value/coe.py, the code-owned cost of equity, with the anchor accessors stubbed."""
from datetime import datetime, timezone

import pytest

from qwen_c.value import coe, desk

T = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def anchors(monkeypatch):
    def set_(rf=0.05, ga=0.0375, load=(1.25, 1.375), erp=(0.0417, "2026-10-04", None), rf_src="(x,2026-10-29)"):
        monkeypatch.setattr(coe.rs2_data, "anchor_risk_free_rate", lambda: (rf, rf_src))
        monkeypatch.setattr(coe.rs2_data, "anchor_terminal_g", lambda: (ga, "anchor_long_run_growth(2026-10-29)"))
        monkeypatch.setattr(coe.rs2_data, "coe_loading", lambda s: load)
        monkeypatch.setattr(coe.rs2_data, "reference_closure", lambda p=None: erp)
    return set_


def test_formula_and_provenance(anchors):
    anchors()
    r, prov = coe.cost_of_equity("Technology", T, closure="x")
    assert r == pytest.approx(max(0.05, 0.0375) + 1.25 * 0.0417)
    assert prov["closure_asof"] == "2026-10-04" and prov["stamps"] == ["coe_leg_undated:loading"]


def test_growth_anchor_above_rf_is_the_floor(anchors):
    anchors(rf=0.03, ga=0.0375)
    assert coe.cost_of_equity("X", T, closure="x")[0] == pytest.approx(0.0375 + 1.25 * 0.0417)


def test_missing_leg_is_refused_never_substituted(anchors):
    anchors(erp=(None, None, "no_reference_closure_artifact"))
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("X", T, closure="x")
    assert e.value.code == "coe_unavailable" and "no_reference_closure_artifact" in str(e.value)


def test_anchor_after_T_refused_unless_allowed_and_then_stamped(anchors):
    anchors(rf_src="(x,2026-11-02)")
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("X", T, closure="x")
    assert e.value.code == "coe_anchor_after_T"
    assert "anchor_after_T" in coe.cost_of_equity("X", T, closure="x", allow_after_T=True)[1]["stamps"]


def test_closure_path_is_the_main_checkouts_cache():
    p = coe.closure_path()
    assert p.name == "reference_closure.json" and p.parent.name == "cache"
