"""tests/test_screener_data_refresh_in_orchestrator.py — P4.-1: orchestrate_depth.main() refreshes
screener_publish_repo (screener_refresh.refresh_screener_data()) before anything else — before the
factor guard, before PAUSED/LOCK — and refuses the whole sweep loudly on failure. --publish-only is
the one mode that skips it (it touches no screener data). The sha is threaded into every spawned
depth_pipeline.py child's env (run_one) and into cache/depth_progress.json.

screener_refresh.refresh_screener_data() itself (the real git sequence) is covered by
tests/test_screener_refresh.py against a throwaway repo; this file only exercises the call site
and wiring inside orchestrate_depth, so refresh_screener_data is stubbed throughout.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
import depth_membership as dm  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(od, "STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(od, "SCREENER_DATA_COMMIT", None)


def _isolate_full_dry_run(monkeypatch, tmp_path):
    """Everything test_factor_guard.py's --ignore-factor-guard/--dry-run test mocks, plus the
    membership-snapshot seam — a --dry-run past the factor guard still runs the real book
    computation (membership snapshot, data-health scan, triggers), and every one of those must
    be isolated from the real cache/ and screener data or the repo-root conftest.py guard trips."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(dm, "check_factor_scores", lambda **kw: (True, None))
    monkeypatch.setattr(od.depth_membership, "snapshot", lambda **kw: ("2026-09-24", 0))
    monkeypatch.setattr(od.depth_membership, "snapshots_recorded", lambda: 0)
    monkeypatch.setattr(od.depth_membership, "dwell_in", lambda t: 0)
    monkeypatch.setattr(od.depth_membership, "held_names", lambda: frozenset())
    monkeypatch.setattr(od, "live_book", lambda: [])
    monkeypatch.setattr(od, "data_health_scan", lambda book: None)
    monkeypatch.setattr(od.depth_triggers, "trigger_map", lambda book: {})
    monkeypatch.setattr(od.depth_triggers, "newest_verdicts", lambda: {})
    monkeypatch.setattr(od.depth_ondemand, "pending", lambda: [])


def test_main_refuses_on_screener_refresh_failure_before_the_factor_guard(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (False, "dirty clone"))

    def _must_not_be_called(**kw):
        raise AssertionError("factor guard must not run — the refresh refusal happens first")
    monkeypatch.setattr(dm, "check_factor_scores", _must_not_be_called)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py"])

    rc = od.main()

    assert rc == 1
    prog = json.loads(od.PROGRESS.read_text(encoding="utf-8"))
    assert prog["active"] is False
    assert prog["blocked_reason"] == "screener_data_refresh: dirty clone"


def test_main_refuses_on_screener_refresh_failure_even_on_dry_run(tmp_path, monkeypatch):
    """A1/decision 3: dry-run also refreshes (it reads the same data) — a refusal must still
    stop it, not silently proceed into the dry-run's factor-guard report."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (False, "fetch failed"))
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--dry-run"])

    rc = od.main()

    assert rc == 1


def test_main_publish_only_skips_the_refresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: calls.append(1) or (True, "unused"))
    monkeypatch.setattr(od, "publish_overlay", lambda: None)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--publish-only"])

    rc = od.main()

    assert rc == 0
    assert calls == []


def test_main_sets_screener_data_commit_on_success(tmp_path, monkeypatch):
    _isolate_full_dry_run(monkeypatch, tmp_path)
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (True, "abc1234"))
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--dry-run"])

    rc = od.main()

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

    ok, why = od.run_one("AAPL")

    assert ok
    assert captured["env"]["RS2_SCREENER_DATA_COMMIT"] == "deadbeef"
    assert captured["env"]["RS2_RUN_SOURCE"] == "orchestrator"


def test_run_one_omits_the_commit_key_when_none(monkeypatch):
    """None until main() has actually refreshed (e.g. a stray call before main() runs) — the
    child must never receive a fabricated sha."""
    monkeypatch.setattr(od, "SCREENER_DATA_COMMIT", None)
    captured = {}

    def fake_popen(*args, **kw):
        captured["env"] = kw.get("env")
        proc = MagicMock()
        proc.wait.return_value = 0
        return proc
    monkeypatch.setattr(od.subprocess, "Popen", fake_popen)

    od.run_one("AAPL")

    assert "RS2_SCREENER_DATA_COMMIT" not in captured["env"]


def test_write_progress_stamps_screener_data_commit(tmp_path, monkeypatch):
    """C2/decision item 3: the sha also lands in cache/depth_progress.json, not only on
    verdicts — status.py and any other progress reader must see it too. --dry-run always calls
    write_progress(0, None, False) before returning, regardless of queue contents."""
    _isolate_full_dry_run(monkeypatch, tmp_path)
    monkeypatch.setattr(od.screener_refresh, "refresh_screener_data",
                        lambda: (True, "cafef00d"))
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--dry-run"])

    rc = od.main()

    assert rc == 0
    prog = json.loads(od.PROGRESS.read_text(encoding="utf-8"))
    assert prog["screener_data_commit"] == "cafef00d"
