"""tests/test_factor_guard.py — P1.4 factor guard tests.

Verifies:
1. Factor engine and freshness checks in depth_membership.check_factor_scores:
   - old engine -> refused
   - stale generated_at -> refused
   - missing / unparseable generated_at -> refused
   - good engine + fresh -> proceeds
2. depth_membership.snapshot() skips writing and returns (today, None) on guard failure.
3. orchestrate_depth.main() refuses wrong or stale book:
   - returns 1
   - logs reason
   - notifies telegram
   - writes cache/depth_progress.json with blocked_reason
   - --tickers does not bypass it
   - --ignore-factor-guard bypasses it
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od
import depth_membership as dm
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


@pytest.fixture
def make_factor_file(tmp_path):
    def _make(engine="dual_door_dynamic_macro_v2_cluster_guarded", age_hours=1.0, tickers=None):
        if tickers is None:
            tickers = {
                "AAPL": {"fct_band": "research_now"},
                "MSFT": {"fct_band": "watchlist"},
                "GOOG": {"fct_band": "neutral"},
            }
        gen_dt = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        content = {
            "engine": engine,
            "generated_at": gen_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tickers": tickers,
        }
        p = tmp_path / "factor_scores.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        return p
    return _make


def test_factor_guard_engine_mismatch(make_factor_file):
    p = make_factor_file(engine="factor_lab_v2_equal", age_hours=1.0)
    ok, reason = dm.check_factor_scores(factor_path=p, max_age_h=48)
    assert not ok
    assert "engine mismatch" in reason
    assert "factor_lab_v2_equal" in reason


def test_factor_guard_stale_generated_at(make_factor_file):
    p = make_factor_file(engine="dual_door_dynamic_macro_v2_cluster_guarded", age_hours=50.0)
    ok, reason = dm.check_factor_scores(factor_path=p, max_age_h=48)
    assert not ok
    assert "stale factor_scores.json" in reason
    assert "50." in reason


def test_factor_guard_missing_generated_at(tmp_path):
    p = tmp_path / "factor_scores.json"
    p.write_text(json.dumps({"engine": "dual_door_dynamic_macro_v2_cluster_guarded"}), encoding="utf-8")
    ok, reason = dm.check_factor_scores(factor_path=p, max_age_h=48)
    assert not ok
    assert "missing 'generated_at'" in reason


def test_factor_guard_good(make_factor_file):
    p = make_factor_file(engine="dual_door_dynamic_macro_v2_cluster_guarded", age_hours=5.0)
    ok, reason = dm.check_factor_scores(factor_path=p, max_age_h=48)
    assert ok
    assert reason is None


def test_snapshot_skips_writing_on_guard_failure(tmp_path, make_factor_file, monkeypatch):
    log_file = tmp_path / "depth_membership.jsonl"
    monkeypatch.setattr(dm, "LOG", log_file)
    p_bad = make_factor_file(engine="factor_lab_v2_equal")

    today, n = dm.snapshot(today="2026-09-23", factor_path=p_bad)
    assert today == "2026-09-23"
    assert n is None
    assert not log_file.exists()


def test_snapshot_proceeds_on_good_factor_scores(tmp_path, make_factor_file, monkeypatch):
    log_file = tmp_path / "depth_membership.jsonl"
    monkeypatch.setattr(dm, "LOG", log_file)
    p_good = make_factor_file(engine="dual_door_dynamic_macro_v2_cluster_guarded", age_hours=2.0)

    today, n = dm.snapshot(today="2026-09-23", factor_path=p_good)
    assert today == "2026-09-23"
    assert n == 2  # AAPL (RN) + MSFT (WL)
    assert log_file.exists()
    rows = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-09-23"
    assert rows[0]["in"] == ["AAPL", "MSFT"]


def test_snapshot_ignore_factor_guard_override(tmp_path, make_factor_file, monkeypatch):
    log_file = tmp_path / "depth_membership.jsonl"
    monkeypatch.setattr(dm, "LOG", log_file)
    p_bad = make_factor_file(engine="factor_lab_v2_equal")

    today, n = dm.snapshot(today="2026-09-23", factor_path=p_bad, ignore_factor_guard=True)
    assert today == "2026-09-23"
    assert n == 2
    assert log_file.exists()


def test_orchestrate_depth_main_refuses_bad_engine(tmp_path, monkeypatch):
    progress_file = tmp_path / "depth_progress.json"
    monkeypatch.setattr(od, "PROGRESS", progress_file)
    monkeypatch.setattr(dm, "check_factor_scores", lambda **kw: (False, "engine mismatch: test error"))
    notified = []
    monkeypatch.setattr(od.ops, "notify_telegram", lambda msg: notified.append(msg))
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--dry-run"])

    rc = od.main()
    assert rc == 1
    assert len(notified) == 1
    assert "test error" in notified[0]
    assert progress_file.exists()
    prog = json.loads(progress_file.read_text(encoding="utf-8"))
    assert prog["active"] is False
    assert prog["blocked_reason"] == "engine mismatch: test error"


def test_orchestrate_depth_main_tickers_does_not_bypass(tmp_path, monkeypatch):
    progress_file = tmp_path / "depth_progress.json"
    monkeypatch.setattr(od, "PROGRESS", progress_file)
    monkeypatch.setattr(dm, "check_factor_scores", lambda **kw: (False, "stale factor_scores: 55h > 48h"))
    monkeypatch.setattr(od.ops, "notify_telegram", lambda msg: None)
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--tickers", "AAPL", "--dry-run"])

    rc = od.main()
    assert rc == 1
    prog = json.loads(progress_file.read_text(encoding="utf-8"))
    assert prog["blocked_reason"] == "stale factor_scores: 55h > 48h"


def test_orchestrate_depth_main_ignore_factor_guard_bypasses(tmp_path, monkeypatch):
    progress_file = tmp_path / "depth_progress.json"
    monkeypatch.setattr(od, "PROGRESS", progress_file)
    monkeypatch.setattr(dm, "check_factor_scores", lambda **kw: (False, "should be ignored"))
    monkeypatch.setattr(sys, "argv", ["orchestrate_depth.py", "--ignore-factor-guard", "--dry-run"])

    rc = od.main()
    assert rc == 0
