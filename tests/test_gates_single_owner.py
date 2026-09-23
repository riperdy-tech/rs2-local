"""tests/test_gates_single_owner.py — ITEM G: Single owner of gate rules (depth_gates.py).

Verifies:
1. depth_gates.py is the single owner of:
   - HIGH_DISPERSION_TOL_PCT (25.0)
   - GATE_VERSION (2)
   - assess(v)
2. depth_sanity and orchestrate_depth read from depth_gates (qualified — C1, Phase 1 approval
   review: depth_sanity's and status.py's bare `from depth_gates import assess, GATE_VERSION,
   HIGH_DISPERSION_TOL_PCT` re-exports were dead weight, confirmed unused by AST, and removed;
   depth_pipeline reads GATE_VERSION from depth_gates; status.py does not use gate rules at all).
3. depth_sanity.audit() dynamically respects depth_gates.HIGH_DISPERSION_TOL_PCT.
"""
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

_ORIG_STDOUT = sys.stdout
import depth_gates as dg
import depth_sanity as ds
import depth_pipeline as dp
import orchestrate_depth as od
import status
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


def test_single_owner_constants_and_functions():
    # depth_gates defines the canonical objects
    assert dg.GATE_VERSION == 2
    assert dg.HIGH_DISPERSION_TOL_PCT == 25.0
    assert callable(dg.assess)

    # depth_sanity reads depth_gates qualified (C1: the bare re-export was unused, removed)
    assert ds.depth_gates is dg
    assert ds.depth_gates.HIGH_DISPERSION_TOL_PCT is dg.HIGH_DISPERSION_TOL_PCT

    # status.py does not use gate rules at all (C1: assess/GATE_VERSION/HIGH_DISPERSION_TOL_PCT
    # were imported and never referenced — confirmed unused by AST and removed)
    assert not hasattr(status, "assess")
    assert not hasattr(status, "GATE_VERSION")
    assert not hasattr(status, "HIGH_DISPERSION_TOL_PCT")
    assert not hasattr(status, "depth_gates")

    # depth_pipeline reads GATE_VERSION from depth_gates
    assert dp.GATE_VERSION is dg.GATE_VERSION

    # orchestrate_depth imports depth_gates
    assert od.depth_gates is dg


def test_depth_sanity_uses_depth_gates_dispersion_threshold(monkeypatch):
    verdict = {
        "ticker": "TEST", "price": 100.0, "direction": "undervalued",
        "iv_band_low": 120.0, "iv_band_high": 150.0, "n_basis": 2,
        "spread_pct": 28.0, "run_source": "orchestrator",
    }
    # With default 25.0 tolerance, 28% spread fails
    level, lines = ds.audit("TEST", verdict)
    assert level == 2
    assert any("violates non-convergence gate" in l for l in lines)

    # Monkeypatching depth_gates threshold to 30.0 makes 28% pass the dispersion gate
    monkeypatch.setattr(dg, "HIGH_DISPERSION_TOL_PCT", 30.0)
    level2, lines2 = ds.audit("TEST", verdict)
    assert not any("violates non-convergence gate" in l for l in lines2)
