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
