import sys
from datetime import datetime, timedelta, timezone
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


# ---- heartbeat failure policy ------------------------------------------------

def _quiet_pass(monkeypatch, snapshot=None):
    """Stub everything in main() except the heartbeat path. No subprocess, no network."""
    monkeypatch.setattr(control_agent, "collect_snapshot",
                        lambda: snapshot if snapshot is not None else {"ts": "t"})
    monkeypatch.setattr(control_agent.control_bus, "fetch_pending_commands", lambda: [])
    monkeypatch.setattr(control_agent, "maybe_sync_state", lambda: None)


def _fail_push(monkeypatch):
    def boom(*a):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(control_agent.control_bus, "push_heartbeat", boom)


def _hbfail_count(cache):
    return (control_agent._read_json(cache / "control_agent_hbfail.json") or {}).get("count")


def test_main_survives_heartbeat_push_raise(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    _quiet_pass(monkeypatch)
    _fail_push(monkeypatch)
    control_agent.main()  # must not raise
    assert _hbfail_count(cache) == 1


def test_alert_fires_only_on_third_consecutive_failure(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    _quiet_pass(monkeypatch)
    _fail_push(monkeypatch)
    alerts = []
    monkeypatch.setattr(control_agent.ops, "notify_telegram", lambda text: alerts.append(text))
    counts = []
    for _ in range(4):
        control_agent.main()
        counts.append(_hbfail_count(cache))
    assert counts == [1, 2, 3, 4]
    assert len(alerts) == 1  # exactly one alert, sent on pass 3
    assert "3 consecutive heartbeat failures" in alerts[0]


def test_successful_push_clears_failure_marker(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    (cache / "control_agent_hbfail.json").write_text('{"count": 2}', encoding="utf-8")
    _quiet_pass(monkeypatch)
    monkeypatch.setattr(control_agent.control_bus, "push_heartbeat", lambda *a: None)
    control_agent.main()
    assert not (cache / "control_agent_hbfail.json").exists()


def test_alert_send_failure_keeps_counter_below_threshold(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    _quiet_pass(monkeypatch)
    _fail_push(monkeypatch)
    attempts = []

    def flaky_notify(text):
        attempts.append(text)
        if len(attempts) == 1:
            raise RuntimeError("telegram down")

    monkeypatch.setattr(control_agent.ops, "notify_telegram", flaky_notify)
    control_agent.main()
    control_agent.main()
    control_agent.main()  # 3rd failure: alert attempted, send raises -> counter held at 2
    assert len(attempts) == 1
    assert _hbfail_count(cache) == 2
    control_agent.main()  # next failure re-reaches 3 -> alert retried, this time it lands
    assert len(attempts) == 2
    assert _hbfail_count(cache) == 3


def test_snapshot_failure_pushes_degraded_payload(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("wmi exploded")

    monkeypatch.setattr(control_agent, "collect_snapshot", boom)
    monkeypatch.setattr(control_agent.control_bus, "fetch_pending_commands", lambda: [])
    monkeypatch.setattr(control_agent, "maybe_sync_state", lambda: None)
    pushed = []
    monkeypatch.setattr(control_agent.control_bus, "push_heartbeat",
                        lambda hb_id, payload: pushed.append((hb_id, payload)))
    control_agent.main()
    assert len(pushed) == 1, "heartbeat must still go out when the snapshot breaks"
    hb_id, payload = pushed[0]
    assert hb_id == "rs2-pc"
    assert "wmi exploded" in payload["snapshot_error"]
    assert payload["ts"].endswith("+00:00") or payload["ts"].endswith("Z")
    assert "host" in payload
    assert not (cache / "control_agent_hbfail.json").exists()  # the push itself succeeded


# ---- command + sync policy ---------------------------------------------------

def test_sdf_dispatch_rejects_bad_runner(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    try:
        control_agent.run_command({"id": 4, "command": "sdf_dispatch",
                                   "args": {"runner": "attacker-controlled"}})
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "bad runner" in str(e)


def test_maybe_sync_state_hourly_gate(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(control_agent, "_cmd_state_sync", lambda args: calls.append(args))
    marker = cache / "state_sync_last.json"

    fresh = datetime.now(timezone.utc).isoformat()
    marker.write_text(f'{{"ts": "{fresh}", "result": "no changes"}}', encoding="utf-8")
    control_agent.maybe_sync_state()
    assert calls == [], "sync must be gated while the marker is fresh"

    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    marker.write_text(f'{{"ts": "{stale}", "result": "no changes"}}', encoding="utf-8")
    control_agent.maybe_sync_state()
    assert len(calls) == 1, "sync must run once the marker is older than the interval"


def test_state_sync_stamps_marker_even_when_sync_raises(monkeypatch, tmp_path):
    cache = _redirect_cache(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise OSError("git vanished")

    monkeypatch.setattr(control_agent.sync_state, "main", boom)
    try:
        control_agent._cmd_state_sync({})
        raise AssertionError("should have raised")
    except OSError as e:
        assert "git vanished" in str(e)
    marker = control_agent._read_json(cache / "state_sync_last.json")
    assert marker["result"] == "raised", "a raising sync must still stamp the hourly gate"
    assert marker["ts"]
