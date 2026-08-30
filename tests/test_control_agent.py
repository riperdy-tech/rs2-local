import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_agent  # noqa: E402


def _redirect_cache(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(control_agent, "CACHE", cache)
    return cache


def test_snapshot_reflects_flags(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    (cache / "DEPTH_PAUSED").write_text("x", encoding="utf-8")
    (cache / "depth_progress.json").write_text('{"ticker": "CEG"}', encoding="utf-8")
    (cache / "depth_ondemand.jsonl").write_text("a\nb\n", encoding="utf-8")
    monkeypatch.setattr(control_agent, "_task_info", lambda name: None)
    monkeypatch.setattr(control_agent, "_bot_pids", lambda: [123])
    snap = control_agent.collect_snapshot()
    assert snap["depth"]["paused"] is True
    assert snap["depth"]["lock"] is False
    assert snap["depth"]["progress"]["ticker"] == "CEG"
    assert snap["ondemand"]["queue_lines"] == 2
    assert snap["bot"]["alive"] is True
    assert snap["ts"].endswith("+00:00") or snap["ts"].endswith("Z")


def test_pause_resume_commands(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    out = control_agent.run_command({"id": 1, "command": "depth_pause", "args": {}})
    assert (cache / "DEPTH_PAUSED").exists() and "paused" in out
    out = control_agent.run_command({"id": 2, "command": "depth_resume", "args": {}})
    assert not (cache / "DEPTH_PAUSED").exists() and "resumed" in out


def test_unknown_command_rejected(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    try:
        control_agent.run_command({"id": 3, "command": "rm_rf_everything", "args": {}})
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "unknown command" in str(e)


def test_main_marks_commands_done(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    marked = []
    monkeypatch.setattr(control_agent, "collect_snapshot", lambda: {"ts": "t"})
    monkeypatch.setattr(control_agent.control_bus, "push_heartbeat", lambda *a: None)
    monkeypatch.setattr(control_agent.control_bus, "fetch_pending_commands",
                        lambda: [{"id": 9, "command": "depth_pause", "args": {}}])
    monkeypatch.setattr(control_agent.control_bus, "mark_command",
                        lambda cid, status, result="": marked.append((cid, status)))
    monkeypatch.setattr(control_agent, "maybe_sync_state", lambda: None)
    control_agent.main()
    assert ("9", "running") not in marked  # ids stay ints
    assert (9, "running") in marked and (9, "done") in marked
