"""tests/test_monitor_mode.py — P4.5/DEP-13 `orchestrate_depth.py --monitor` mode.

`run_monitor()` and the `--monitor` branch of `main()` are exercised directly, with
thesis_monitor.run/rebuild_overlay/publish_overlay stubbed so nothing here touches the real
cache/, screener data, GPU or site. B4's `--no-publish` flag on the normal (non-monitor) sweep is
covered separately in tests/test_gate_no_publish.py.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


SUMMARY = {"evaluated": 3, "breached": 1, "intact": 1, "unknown": 1}


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(od, "STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(od, "LOCK", tmp_path / "depth_lock.json")
    monkeypatch.setattr(od, "PAUSED", tmp_path / "DEPTH_PAUSED_nonexistent")
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))


# ================================================================================================
# run_monitor() directly
# ================================================================================================

def test_run_monitor_normal_path_rebuilds_and_publishes(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    calls = []
    monkeypatch.setattr(od.thesis_monitor, "run", lambda: dict(SUMMARY))
    monkeypatch.setattr(od, "rebuild_overlay", lambda: calls.append("rebuild") or 3)
    monkeypatch.setattr(od, "publish_overlay", lambda: calls.append("publish"))

    rc = od.run_monitor(no_publish=False, paused_bypass=False)

    assert rc == 0
    assert calls == ["rebuild", "publish"]


def test_run_monitor_no_publish_rebuilds_but_skips_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    calls = []
    monkeypatch.setattr(od.thesis_monitor, "run", lambda: dict(SUMMARY))
    monkeypatch.setattr(od, "rebuild_overlay", lambda: calls.append("rebuild") or 3)
    monkeypatch.setattr(od, "publish_overlay", lambda: calls.append("publish"))

    rc = od.run_monitor(no_publish=True, paused_bypass=False)

    assert rc == 0
    assert calls == ["rebuild"]


def test_run_monitor_paused_bypass_only_runs_the_monitor(tmp_path, monkeypatch):
    """PAUSED + --no-publish: writes cache/depth_thesis.json only — no overlay rebuild, no
    publish, whether or not no_publish itself is honoured elsewhere."""
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    calls = []
    monkeypatch.setattr(od.thesis_monitor, "run", lambda: calls.append("monitor") or dict(SUMMARY))
    monkeypatch.setattr(od, "rebuild_overlay", lambda: calls.append("rebuild") or 0)
    monkeypatch.setattr(od, "publish_overlay", lambda: calls.append("publish"))

    rc = od.run_monitor(no_publish=True, paused_bypass=True)

    assert rc == 0
    assert calls == ["monitor"]


# ================================================================================================
# main() --monitor: PAUSED gate + bypass
# ================================================================================================

def test_main_monitor_refuses_while_paused(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    paused = tmp_path / "DEPTH_PAUSED"
    paused.write_text("", encoding="utf-8")
    monkeypatch.setattr(od, "PAUSED", paused)
    ran = []
    monkeypatch.setattr(od, "run_monitor", lambda **kw: ran.append(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--monitor"])

    rc = od.main()

    assert rc == 0
    assert ran == []   # run_monitor never called


def test_main_monitor_no_publish_bypasses_pause(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    paused = tmp_path / "DEPTH_PAUSED"
    paused.write_text("", encoding="utf-8")
    monkeypatch.setattr(od, "PAUSED", paused)
    ran = []
    monkeypatch.setattr(od, "run_monitor", lambda **kw: ran.append(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--monitor", "--no-publish"])

    rc = od.main()

    assert rc == 0
    assert len(ran) == 1
    assert ran[0]["no_publish"] is True
    assert ran[0]["paused_bypass"] is True


def test_main_monitor_runs_normally_when_not_paused(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    ran = []
    monkeypatch.setattr(od, "run_monitor", lambda **kw: ran.append(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--monitor"])

    rc = od.main()

    assert rc == 0
    assert len(ran) == 1
    assert ran[0]["no_publish"] is False
    assert ran[0]["paused_bypass"] is False


def test_main_monitor_refuses_on_screener_refresh_failure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (False, "dirty clone"))
    ran = []
    monkeypatch.setattr(od, "run_monitor", lambda **kw: ran.append(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--monitor"])

    rc = od.main()

    assert rc == 1
    assert ran == []
