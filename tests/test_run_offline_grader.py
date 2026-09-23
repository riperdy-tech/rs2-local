"""tests/test_run_offline_grader.py — TRK-06 (P2.1): orchestrate_depth.run_offline_grader(),
called at the end of every sweep in main(). Must be non-fatal and logged only — a grading hiccup
must never raise out of a sweep that already completed.
"""
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


@pytest.fixture(autouse=True)
def _redirect_depth_log(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")


def test_run_offline_grader_logs_success(monkeypatch, capsys):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, stdout="Written: outcomes, report\n", stderr="")
    monkeypatch.setattr(od.subprocess, "run", fake_run)
    od.run_offline_grader()
    out = capsys.readouterr().out
    assert "offline grader rc=0" in out


def test_run_offline_grader_logs_nonzero_rc_without_raising(monkeypatch, capsys):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="Traceback: boom\n")
    monkeypatch.setattr(od.subprocess, "run", fake_run)
    od.run_offline_grader()      # must not raise
    out = capsys.readouterr().out
    assert "offline grader rc=1" in out


def test_run_offline_grader_survives_exception(monkeypatch, capsys):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="grade_depth_verdicts.py", timeout=300)
    monkeypatch.setattr(od.subprocess, "run", fake_run)
    od.run_offline_grader()      # must not raise
    out = capsys.readouterr().out
    assert "offline grader did not run (non-fatal)" in out


def test_run_offline_grader_invokes_the_right_script_with_offline_flag(monkeypatch):
    captured = {}

    def fake_run(cmd, **k):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(od.subprocess, "run", fake_run)
    od.run_offline_grader()
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1].endswith(str(Path("tools") / "grade_depth_verdicts.py"))
    assert captured["cmd"][2] == "--offline"


# ═══════════════════════════════════════════════════════════════════════════════════════════
# C5 (Phase 2 approval review): run_offline_grader() must run BEFORE the final publish_overlay()
# in main(), only when that publish actually runs, so the site's depth_outcomes.json carries
# this sweep's fresh verdicts instead of lagging a cycle behind.
# ═══════════════════════════════════════════════════════════════════════════════════════════

def test_orchestrate_depth_main_runs_grader_before_final_publish(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(od, "PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(od, "STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(od, "LOCK", tmp_path / "depth_lock.json")
    monkeypatch.setattr(od, "PAUSED", tmp_path / "DEPTH_PAUSED_nonexistent")
    monkeypatch.setattr(od, "LEDGER", tmp_path / "no_ledger.jsonl")
    monkeypatch.setattr(od, "OVERLAY", tmp_path / "depth_overlay.json")
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(od.depth_membership, "LOG", tmp_path / "depth_membership.jsonl")

    monkeypatch.setattr(od.depth_triggers, "trigger_map", lambda book: {})
    monkeypatch.setattr(od.depth_triggers, "newest_verdicts", lambda: {})
    monkeypatch.setattr(od, "data_health_scan", lambda book: None)
    # Bypass the due-queue business logic entirely — this test is about call ORDER, not
    # membership/trigger rules, which are covered elsewhere (tests/test_depth_queue.py etc.).
    monkeypatch.setattr(od, "build_queue", lambda *a, **k: [("FAKE1", "triggered", "test")])
    monkeypatch.setattr(od, "run_one", lambda t, ondemand=False: (True, ""))
    monkeypatch.setattr(od.depth_ondemand, "pending", lambda: [])
    monkeypatch.setattr(od.depth_ondemand, "take_next", lambda: None)
    monkeypatch.setattr(od.ops, "notify_telegram", lambda *a, **k: None)
    monkeypatch.setattr(od, "run_offline_grader", lambda: order.append("grader"))
    monkeypatch.setattr(od, "publish_overlay", lambda: order.append("publish"))

    monkeypatch.setattr(sys, "argv",
                        ["orchestrate_depth.py", "--ignore-factor-guard", "--tickers", "FAKE1"])
    rc = od.main()
    assert rc == 0
    # publish_overlay() also runs once per completed ticker inside the sweep loop (unrelated to
    # C5) — what matters here is that the grader runs immediately before the FINAL publish.
    assert order[-2:] == ["grader", "publish"]
