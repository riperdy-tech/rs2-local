"""depth_pipeline.py — run_source resolution, ledger routing, and provenance stamping (P1.2).

Exercises `_run_source()` and `stamp_and_route()` directly against synthetic verdicts/argv/env,
never the real research/consensus subprocesses or the real cache/ ledgers.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# depth_pipeline re-wraps sys.stdout at import (utf-8 console on Windows). Under pytest that
# wraps the capture buffer, and letting the wrapper be garbage-collected would close it — same
# hazard api_llm/publish_cloud_verdicts.py guards with _STDOUT_KEEPALIVE (and orchestrate_depth's
# own test, tests/test_depth_queue.py). Keep it, restore ours.
_ORIG_STDOUT = sys.stdout
import depth_pipeline as dp  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


# ---- _run_source(): --ondemand > RS2_RUN_SOURCE env > --production > manual -------------------

@pytest.mark.parametrize("argv, env, expected", [
    (["depth_pipeline.py", "AAPL", "--ondemand"], {}, "ondemand"),
    (["depth_pipeline.py", "AAPL"], {"RS2_RUN_SOURCE": "orchestrator"}, "orchestrator"),
    (["depth_pipeline.py", "AAPL"], {"RS2_RUN_SOURCE": "cloud"}, "cloud"),
    (["depth_pipeline.py", "AAPL", "--production"], {}, "manual_production"),
    (["depth_pipeline.py", "AAPL"], {}, "manual"),
    # --ondemand wins even with an env marker set (a spawner passing both is unambiguous: the
    # explicit CLI flag is the stronger signal).
    (["depth_pipeline.py", "AAPL", "--ondemand"], {"RS2_RUN_SOURCE": "orchestrator"}, "ondemand"),
    # an env value outside the recognised set is not honoured — falls through to --production
    # or manual, same as if it were unset.
    (["depth_pipeline.py", "AAPL"], {"RS2_RUN_SOURCE": "bogus"}, "manual"),
])
def test_run_source_resolution_order(monkeypatch, argv, env, expected):
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    assert dp._run_source() == expected


# ---- stamp_and_route(): ledger target + every new field present -------------------------------

def _synthetic_verdict():
    return {"ticker": "FLXS", "price": 100.0, "date": "2026-09-23", "direction": "hold"}


@pytest.mark.parametrize("run_source, expected_ledger", [
    ("ondemand", "OD_LEDGER"),
    ("orchestrator", "LEDGER"),
    ("cloud", "LEDGER"),
    ("manual_production", "LEDGER"),
    ("manual", "TEST_LEDGER"),
])
def test_stamp_and_route_targets_the_right_ledger(monkeypatch, tmp_path, run_source, expected_ledger):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    ledger, notice = dp.stamp_and_route(v, "FLXS", run_source)
    assert ledger == getattr(dp, expected_ledger)
    if run_source == "manual":
        assert notice is not None
        assert "NOT the production ledger" in notice
        assert "FLXS" in notice
    else:
        assert notice is None


NEW_FIELDS = ("run_source", "arm", "pack_source", "research_brief_asof",
              "research_brief_age_days", "price_asof", "price_source", "gate_version",
              "pipeline_commit")


def test_stamp_and_route_adds_every_new_field(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    for field in NEW_FIELDS:
        assert field in v, f"missing field: {field}"
    assert v["run_source"] == "orchestrator"
    assert v["arm"] == "local"
    assert v["pack_source"] == "fresh"
    assert v["gate_version"] == dp.GATE_VERSION


def test_price_asof_and_source_are_none_not_fabricated(monkeypatch, tmp_path):
    """P1.5 is not implemented yet — these must be explicit None with a reason, never a value."""
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    assert v["price_asof"] is None
    assert v["price_source"] is None
    assert v.get("price_asof_reason")  # a stated reason accompanies the absence


def test_research_brief_asof_absent_when_no_brief_on_disk(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    assert v["research_brief_asof"] is None
    assert v["research_brief_age_days"] is None


def test_research_brief_asof_present_when_brief_exists(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    (tmp_path / "FLXS.md").write_text("brief", encoding="utf-8")
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    assert v["research_brief_asof"] is not None
    assert v["research_brief_age_days"] is not None
    assert v["research_brief_age_days"] >= 0


# ---- GATE_VERSION is a real, importable single owner (P1.2; moves to depth_gates.py in P1.3) --

def test_gate_version_is_two():
    assert dp.GATE_VERSION == 2
