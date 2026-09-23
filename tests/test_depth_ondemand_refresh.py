"""tests/test_depth_ondemand_refresh.py — P4.-1: depth_ondemand.drain() refreshes
screener_publish_repo (screener_refresh.refresh_screener_data()) before draining the queue, and
refuses (releasing the lock, leaving queued requests untouched) if that refresh fails. The sha is
threaded into every spawned depth_pipeline.py --ondemand child's env (_run_one).

screener_refresh.refresh_screener_data() itself is covered by tests/test_screener_refresh.py
against a throwaway repo; stubbed throughout here.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import depth_ondemand as od  # noqa: E402


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "ORCH_LOCK", tmp_path / "orchestrate_depth.lock")
    monkeypatch.setattr(od, "QUEUE", tmp_path / "depth_ondemand.jsonl")
    monkeypatch.setattr(od, "QLOCK", tmp_path / "depth_ondemand.queue.lock")
    monkeypatch.setattr(od, "PAUSED", tmp_path / "DEPTH_PAUSED_nonexistent")
    monkeypatch.setattr(od, "LOG", tmp_path / "depth_ondemand.log")
    monkeypatch.setattr(od, "SCREENER_DATA_COMMIT", None)
    monkeypatch.setattr(od, "_lock_alive", lambda: None)
    monkeypatch.setattr(od.ops, "job_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(od.ops, "job_done", lambda *a, **k: None)
    monkeypatch.setattr(od.ops, "notify_telegram", lambda *a, **k: None)


def test_drain_refuses_and_releases_the_lock_on_refresh_failure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    od.QUEUE.parent.mkdir(exist_ok=True)
    od.QUEUE.write_text(json.dumps({"ticker": "AAPL", "requested_at": "2026-09-24 00:00:00",
                                    "source": "cli"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (False, "dirty clone"))
    ran = []
    monkeypatch.setattr(od, "_run_one", lambda t: ran.append(t) or (True, "ok"))

    rc = od.drain()

    assert rc == 1
    assert ran == []                       # never touched the queue
    assert not od.ORCH_LOCK.exists()       # lock released, not left held
    assert len(od.pending()) == 1          # the request survives — take_next() never popped it


def test_drain_sets_the_module_level_commit_on_success(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (True, "abc1234"))
    monkeypatch.setattr(od, "_run_one", lambda t: (True, "ok"))
    monkeypatch.setattr(od, "take_next", lambda: None)   # empty queue — drain exits the loop

    rc = od.drain()

    assert rc == 0
    assert od.SCREENER_DATA_COMMIT == "abc1234"


def test_run_one_threads_the_commit_sha_into_the_child_env(monkeypatch):
    monkeypatch.setattr(od, "SCREENER_DATA_COMMIT", "deadbeef")
    captured = {}

    def fake_popen(*args, **kw):
        captured["env"] = kw.get("env")
        proc = MagicMock()
        proc.wait.return_value = 0
        return proc
    monkeypatch.setattr(od.subprocess, "Popen", fake_popen)

    ok, why = od._run_one("AAPL")

    assert ok
    assert captured["env"]["RS2_SCREENER_DATA_COMMIT"] == "deadbeef"


def test_run_one_omits_the_commit_key_when_none(monkeypatch):
    monkeypatch.setattr(od, "SCREENER_DATA_COMMIT", None)
    captured = {}

    def fake_popen(*args, **kw):
        captured["env"] = kw.get("env")
        proc = MagicMock()
        proc.wait.return_value = 0
        return proc
    monkeypatch.setattr(od.subprocess, "Popen", fake_popen)

    od._run_one("AAPL")

    assert "RS2_SCREENER_DATA_COMMIT" not in captured["env"]
