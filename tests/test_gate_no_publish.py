"""tests/test_gate_no_publish.py — B4 (Phase 4 amendments): `orchestrate_depth.py --no-publish`
on the normal (non-monitor) sweep. The gate's "one full production-style run" must never publish
the overlay or push to the site; every publish_overlay() call site in main()'s sweep loop is
suppressed by the flag, and everything else in the sweep runs exactly as normal.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(od, "STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(od, "LOCK", tmp_path / "depth_lock.json")
    monkeypatch.setattr(od, "PAUSED", tmp_path / "DEPTH_PAUSED_nonexistent")
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))
    monkeypatch.setattr(od, "LEDGER", tmp_path / "no_ledger.jsonl")
    monkeypatch.setattr(od, "OVERLAY", tmp_path / "depth_overlay.json")
    monkeypatch.setattr(od, "THESIS_CACHE", tmp_path / "depth_thesis.json")
    monkeypatch.setattr(od.depth_membership, "LOG", tmp_path / "depth_membership.jsonl")
    monkeypatch.setattr(od.thesis_monitor, "run",
                        lambda: {"evaluated": 0, "breached": 0, "intact": 0, "unknown": 0})
    monkeypatch.setattr(od.depth_triggers, "trigger_map", lambda book: {})
    monkeypatch.setattr(od.depth_triggers, "newest_verdicts", lambda: {})
    monkeypatch.setattr(od, "data_health_scan", lambda book: None)
    monkeypatch.setattr(od, "build_queue", lambda *a, **k: [("FAKE1", 0, "test")])
    monkeypatch.setattr(od, "run_one", lambda t, ondemand=False: (True, ""))
    monkeypatch.setattr(od.depth_ondemand, "pending", lambda: [])
    monkeypatch.setattr(od.depth_ondemand, "take_next", lambda: None)
    monkeypatch.setattr(od.ops, "notify_telegram", lambda *a, **k: None)
    monkeypatch.setattr(od, "run_offline_grader", lambda: None)


def test_main_sweep_no_publish_never_calls_publish_overlay(tmp_path, monkeypatch):
    """A gate-style run: --no-publish end to end through main()'s normal (non-monitor) sweep
    path. publish_overlay must never be called, per-ticker or at the end, even though the sweep
    otherwise completes and writes the local ledger/overlay as usual."""
    _isolate(monkeypatch, tmp_path)
    published = []
    monkeypatch.setattr(od, "publish_overlay", lambda: published.append(1))

    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--ignore-factor-guard",
                                      "--tickers", "FAKE1", "--no-publish"])
    rc = od.main()

    assert rc == 0
    assert published == []


def test_main_sweep_publishes_normally_without_the_flag(tmp_path, monkeypatch):
    """Regression guard: the SAME sweep, without --no-publish, still publishes — proves the
    suppression above is due to the flag, not some other change."""
    _isolate(monkeypatch, tmp_path)
    published = []
    monkeypatch.setattr(od, "publish_overlay", lambda: published.append(1))

    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--ignore-factor-guard",
                                      "--tickers", "FAKE1"])
    rc = od.main()

    assert rc == 0
    assert len(published) >= 1
