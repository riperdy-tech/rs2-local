"""depth_gates.assess() — the single-owner `actionable` gate (P1.3), plus an overlay-rebuild
test proving orchestrate_depth.rebuild_overlay() publishes it correctly on a 3-row fixture.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import depth_gates as dg  # noqa: E402

GV = dg.GATE_VERSION


def _clean(**over):
    """A verdict that trips NO gate on its own — every test overrides just the field(s) under
    test, so a passing baseline proves the other fields are inert rather than coincidentally
    also failing."""
    base = {"direction": "hold", "gate_version": GV, "n_basis": 2,
            "fiduciary_verdict": "PASS", "kelly_fraction_pct": 0.0, "spread_pct": 5.0,
            "run_source": "orchestrator",
            "producer_class": {"status": "ok", "depleting": False, "sector": "Technology",
                               "industry": "Software - Infrastructure", "source": "stocks.csv@test"},
            "consensus_data_status": "ok",
            "street_fence": {"low": 10.0, "high": 20.0}}
    base.update(over)
    return base


# ---- baseline: nothing fires --------------------------------------------------------------

def test_clean_verdict_is_actionable():
    actionable, reasons = dg.assess(_clean())
    assert actionable is True
    assert reasons == []


# ---- one case per reason, in assess()'s evaluation order -----------------------------------

def test_not_usable_direction():
    actionable, reasons = dg.assess(_clean(direction="NOT_USABLE"))
    assert actionable is False
    assert reasons == ["not_usable"]


def test_not_usable_on_missing_direction():
    actionable, reasons = dg.assess(_clean(direction=None))
    assert actionable is False
    assert "not_usable" in reasons


def test_pre_v31_gates_on_missing_gate_version():
    v = _clean()
    del v["gate_version"]
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["pre_v3.1_gates"]


def test_pre_v31_gates_on_older_gate_version():
    actionable, reasons = dg.assess(_clean(gate_version=GV - 1))
    assert actionable is False
    assert reasons == ["pre_v3.1_gates"]


def test_single_sample_is_no_longer_a_gate_reason():
    # operator ruling 2026-10-06: one-sample verdicts are no longer blocked for that alone
    actionable, reasons = dg.assess(_clean(n_basis=1))
    assert actionable is True
    assert reasons == []


def test_fiduciary_fail():
    actionable, reasons = dg.assess(_clean(fiduciary_verdict="FAIL"))
    assert actionable is False
    assert reasons == ["fiduciary_fail"]


def test_kelly_on_overvalued():
    actionable, reasons = dg.assess(_clean(direction="overvalued", kelly_fraction_pct=8.5))
    assert actionable is False
    assert reasons == ["kelly_on_overvalued"]


def test_zero_kelly_on_overvalued_does_not_fire():
    """0.0 is a value, not an absence — Kelly exactly zero on an overvalued call is not the
    'positive Kelly on a sell' contradiction this reason exists to catch."""
    actionable, reasons = dg.assess(_clean(direction="overvalued", kelly_fraction_pct=0.0))
    assert actionable is True
    assert reasons == []


def test_high_dispersion():
    actionable, reasons = dg.assess(_clean(direction="undervalued", spread_pct=30.0))
    assert actionable is False
    assert reasons == ["high_dispersion"]


def test_high_dispersion_fires_on_overvalued_too():
    """P4.8 — symmetric dispersion: an overvalued call under the identical model disagreement
    that would quarantine an undervalued one must not publish actionable unguarded."""
    actionable, reasons = dg.assess(_clean(direction="overvalued", spread_pct=90.0))
    assert actionable is False
    assert reasons == ["high_dispersion"]


def test_high_dispersion_does_not_fire_on_hold():
    actionable, reasons = dg.assess(_clean(direction="hold", spread_pct=90.0))
    assert actionable is True
    assert reasons == []


def test_mode_instability():
    v = _clean(instability={"prior_iv": 934.535, "current_iv": 517.745, "delta_pct": -44.6,
                            "unstable": True})
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["mode_instability"]


def test_mode_instability_does_not_fire_when_stable():
    v = _clean(instability={"prior_iv": 100.0, "current_iv": 105.0, "delta_pct": 5.0,
                            "unstable": False})
    actionable, reasons = dg.assess(v)
    assert actionable is True
    assert reasons == []


def test_mode_instability_does_not_fire_when_absent():
    """No prior to compare (first-ever analysis) — `instability` is None, not a defect."""
    actionable, reasons = dg.assess(_clean(instability=None))
    assert actionable is True
    assert reasons == []


def test_non_production_row_manual():
    actionable, reasons = dg.assess(_clean(run_source="manual"))
    assert actionable is False
    assert reasons == ["non_production_row"]


def test_non_production_row_test():
    actionable, reasons = dg.assess(_clean(run_source="test"))
    assert actionable is False
    assert reasons == ["non_production_row"]


def test_non_production_row_gate_test():
    """B4 (Phase 4 amendments): the Phase 4 gate run (RS2_RUN_SOURCE=gate_test) must never be
    actionable, even if a copy of its row ever reached the production ledger by some other path."""
    actionable, reasons = dg.assess(_clean(run_source="gate_test"))
    assert actionable is False
    assert reasons == ["non_production_row"]


# ---- multiple reasons compound, in the fixed order ------------------------------------------

def test_reasons_compound_in_order():
    v = _clean(fiduciary_verdict="FAIL")
    del v["gate_version"]
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["pre_v3.1_gates", "fiduciary_fail"]


# ---- never raises on a sparse/legacy verdict --------------------------------------------------

def test_empty_verdict_does_not_raise():
    actionable, reasons = dg.assess({})
    assert actionable is False
    assert "not_usable" in reasons
    assert "pre_v3.1_gates" in reasons


def test_none_verdict_does_not_raise():
    actionable, reasons = dg.assess(None)
    assert actionable is False


# ================================================================================================
# overlay rebuild — orchestrate_depth.rebuild_overlay() on a 3-row fixture ledger
# ================================================================================================

# orchestrate_depth re-wraps sys.stdout at import (utf-8 console on Windows). Under pytest that
# wraps the capture buffer, and letting the wrapper be garbage-collected would close it — same
# hazard api_llm/publish_cloud_verdicts.py guards with _STDOUT_KEEPALIVE (tests/test_depth_queue.py
# does the same dance).
_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT

FIXTURE_ROWS = [
    # AAA: clean, actionable.
    {"ticker": "AAA", "direction": "hold", "gate_version": GV, "n_basis": 2,
     "fiduciary_verdict": "PASS", "kelly_fraction_pct": 0.0, "spread_pct": 5.0,
     "run_source": "orchestrator", "date": "2026-09-22",
     "producer_class": {"status": "ok", "depleting": False, "sector": "Technology",
                        "industry": "Software - Infrastructure", "source": "stocks.csv@test"},
     "consensus_data_status": "ok",
     "street_fence": {"low": 10.0, "high": 20.0}},
    # BBB: pre-v3.1 (no gate_version) AND single-sample — reasons compound.
    {"ticker": "BBB", "direction": "undervalued", "n_basis": 1, "spread_pct": 5.0,
     "run_source": "orchestrator", "date": "2026-09-18"},
    # CCC: the band_verdict() malfunction sentinel — must publish direction: null, status:
    # not_usable, and be excluded from actionable_count.
    {"ticker": "CCC", "direction": "NOT_USABLE", "gate_version": GV, "n_basis": 0,
     "run_source": "orchestrator", "date": "2026-09-20"},
]


def test_rebuild_overlay_on_3row_fixture(tmp_path, monkeypatch):
    ledger = tmp_path / "depth_ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(r) for r in FIXTURE_ROWS) + "\n", encoding="utf-8")
    overlay = tmp_path / "depth_overlay.json"
    monkeypatch.setattr(od, "LEDGER", ledger)
    monkeypatch.setattr(od, "OVERLAY", overlay)
    # P4.5/DEP-13: rebuild_overlay() now reads cache/depth_thesis.json too — isolate from the
    # real one (a nonexistent path here means every thesis field publishes explicit None).
    monkeypatch.setattr(od, "THESIS_CACHE", tmp_path / "depth_thesis.json")

    count = od.rebuild_overlay()
    assert count == 3

    published = json.loads(overlay.read_text(encoding="utf-8"))
    assert published["count"] == 3
    assert published["actionable_count"] == 1
    assert published["gate_version"] == GV

    aaa = published["tickers"]["AAA"]
    assert aaa["actionable"] is True
    assert aaa["actionable_reasons"] == []
    assert aaa["status"] == "ok"
    assert aaa["direction"] == "hold"

    bbb = published["tickers"]["BBB"]
    assert bbb["actionable"] is False
    assert bbb["actionable_reasons"] == ["pre_v3.1_gates", "no_street_fence"]   # n_basis 1 no longer gates (2026-10-06)
    assert bbb["status"] == "ok"          # a real direction, just not actionable
    assert bbb["direction"] == "undervalued"

    ccc = published["tickers"]["CCC"]
    assert ccc["actionable"] is False
    assert "not_usable" in ccc["actionable_reasons"]
    assert ccc["status"] == "not_usable"
    assert ccc["direction"] is None       # the sentinel string never reaches the published row

    # P4.5/DEP-13: with no cache/depth_thesis.json record for any of these tickers, every thesis
    # field publishes as an explicit None — present, never silently omitted.
    for row in (aaa, bbb, ccc):
        assert row["thesis_status"] is None
        assert row["thesis_checks"] is None
        assert row["entry_timing_now"] is None
        assert row["thesis_asof"] is None
        assert row["momentum_exit"] is None
        assert row["momentum_exit_reason"] is None


def test_rebuild_overlay_merges_momentum_exit(tmp_path, monkeypatch):
    ledger = tmp_path / "depth_ledger.jsonl"
    ledger.write_text(json.dumps({
        "ticker": "MMM", "direction": "hold", "gate_version": GV, "n_basis": 2,
        "fiduciary_verdict": "PASS", "position_basis": "momentum", "run_source": "orchestrator",
        "date": "2026-09-22"}) + "\n", encoding="utf-8")
    overlay = tmp_path / "depth_overlay.json"
    thesis = tmp_path / "depth_thesis.json"
    thesis.write_text(json.dumps({
        "asof": "2026-09-24",
        "tickers": {"MMM": {
            "thesis_status": "intact", "checks": [], "entry_timing_now": "avoid",
            "momentum_flip_met": False, "momentum_exit": True,
            "momentum_exit_reason": "mom_6m < 0 (-0.02)"}}}), encoding="utf-8")
    monkeypatch.setattr(od, "LEDGER", ledger)
    monkeypatch.setattr(od, "OVERLAY", overlay)
    monkeypatch.setattr(od, "THESIS_CACHE", thesis)

    count = od.rebuild_overlay()
    assert count == 1
    published = json.loads(overlay.read_text(encoding="utf-8"))
    mmm = published["tickers"]["MMM"]
    assert mmm["momentum_exit"] is True
    assert mmm["momentum_exit_reason"] == "mom_6m < 0 (-0.02)"
    assert mmm["entry_timing_now"] == "avoid"



# ---- B3 (Phase 4 amendment): pre_valid_analyst reason, gated on FIRST_VALID_PACK_REVISION ----

def test_pre_valid_analyst_inert_while_first_valid_pack_revision_is_none(monkeypatch):
    """Behaviour must be UNCHANGED while the ruling has not happened yet — every row would
    otherwise become non-actionable the instant this reason existed, before any gate ran."""
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", None)
    v = _clean(pack_revision=5)
    actionable, reasons = dg.assess(v)
    assert actionable is True
    assert reasons == []


def test_pre_valid_analyst_fires_below_the_ruled_floor(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    v = _clean(pack_revision=4)   # below the floor -> not analyst_valid
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["pre_valid_analyst"]


def test_pre_valid_analyst_silent_at_or_above_the_ruled_floor(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    v = _clean(pack_revision=5)
    actionable, reasons = dg.assess(v)
    assert actionable is True
    assert reasons == []


def test_pre_valid_analyst_fires_on_a_row_with_no_pack_revision_at_all(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    v = _clean()
    assert "pack_revision" not in v
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["pre_valid_analyst"]


def test_pre_valid_analyst_compounds_with_other_reasons(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    v = _clean(pack_revision=4, fiduciary_verdict="FAIL")
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["fiduciary_fail", "pre_valid_analyst"]


# ---- analyst_valid() — P2-fix B2: keyed on FIRST_VALID_PACK_REVISION, not gate_version alone ----

def test_analyst_valid_false_while_first_valid_pack_revision_is_none(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", None)
    v = {"pack_revision": 5, "gate_version": GV}   # today's real depth_pipeline stamp
    assert dg.analyst_valid(v) is False


def test_analyst_valid_true_at_or_above_the_ruled_floor(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    assert dg.analyst_valid({"pack_revision": 5, "gate_version": GV}) is True
    assert dg.analyst_valid({"pack_revision": 6, "gate_version": GV}) is True


def test_analyst_valid_false_below_the_ruled_floor(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    assert dg.analyst_valid({"pack_revision": 4, "gate_version": GV}) is False


def test_analyst_valid_false_below_current_gate_version(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    assert dg.analyst_valid({"pack_revision": 5, "gate_version": GV - 1}) is False


def test_analyst_valid_false_on_missing_or_non_int_values(monkeypatch):
    monkeypatch.setattr(dg, "FIRST_VALID_PACK_REVISION", 5)
    assert dg.analyst_valid({"pack_revision": None, "gate_version": GV}) is False
    assert dg.analyst_valid({"pack_revision": 5, "gate_version": None}) is False
    assert dg.analyst_valid({"gate_version": GV}) is False
    assert dg.analyst_valid({"pack_revision": 5}) is False
    assert dg.analyst_valid({"pack_revision": "5", "gate_version": GV}) is False
    assert dg.analyst_valid({}) is False
    assert dg.analyst_valid(None) is False
