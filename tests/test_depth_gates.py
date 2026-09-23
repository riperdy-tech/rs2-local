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
            "run_source": "orchestrator"}
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


def test_single_sample():
    actionable, reasons = dg.assess(_clean(n_basis=1))
    assert actionable is False
    assert reasons == ["single_sample"]


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


def test_high_dispersion_does_not_fire_on_overvalued():
    """Symmetric dispersion for overvalued is Phase 4 P4.8 — explicitly not added here."""
    actionable, reasons = dg.assess(_clean(direction="overvalued", spread_pct=90.0))
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


# ---- multiple reasons compound, in the fixed order ------------------------------------------

def test_reasons_compound_in_order():
    v = _clean(n_basis=1)
    del v["gate_version"]
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert reasons == ["pre_v3.1_gates", "single_sample"]


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
     "run_source": "orchestrator", "date": "2026-09-22"},
    # BBB: pre-v3.1 (no gate_version) AND single-sample — two reasons compound.
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
    assert bbb["actionable_reasons"] == ["pre_v3.1_gates", "single_sample"]
    assert bbb["status"] == "ok"          # a real direction, just not actionable
    assert bbb["direction"] == "undervalued"

    ccc = published["tickers"]["CCC"]
    assert ccc["actionable"] is False
    assert "not_usable" in ccc["actionable_reasons"]
    assert ccc["status"] == "not_usable"
    assert ccc["direction"] is None       # the sentinel string never reaches the published row
