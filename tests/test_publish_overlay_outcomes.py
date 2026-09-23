"""tests/test_publish_overlay_outcomes.py — TRK-06 (P2.1) addition to orchestrate_depth.py:
publish_overlay() now copies cache/depth_outcomes.json into the publish clone alongside the
overlay, validates it as JSON before staging, and stages it — but only when it exists (a fresh
checkout or one that predates the grader's first run has none yet, and publishing must not fail
over that).

A real local git origin/clone (same pattern as tests/test_sync_state.py) rather than mocked git
calls: publish_overlay()'s own logic (dirty-check exclusions, git add, diff --cached --check,
commit, push) is easiest to trust by actually running it against a throwaway repo, never the real
screener-publish clone.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

# orchestrate_depth re-wraps sys.stdout at import (utf-8 console on Windows) — same dance as
# tests/test_depth_gates.py / tests/test_price_now.py.
_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_publish_clone(tmp_path):
    # Named with "stock-screener" in the path: publish_overlay() refuses any origin whose URL
    # doesn't contain that substring (never push the sweep somewhere unexpected).
    origin = tmp_path / "stock-screener.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "screener-publish-clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@test")
    _git(clone, "config", "user.name", "test")
    (clone / "public" / "data").mkdir(parents=True)
    (clone / "public" / "data" / ".gitkeep").write_text("", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "init")
    _git(clone, "branch", "-M", "main")
    _git(clone, "push", "-u", "origin", "main")
    return clone


def _isolate(monkeypatch, tmp_path, clone):
    monkeypatch.setitem(od.CONFIG, "screener_publish_repo", str(clone))
    monkeypatch.setattr(od, "PUBLISH_LOCK", tmp_path / "screener_publish.lock")
    monkeypatch.setattr(od, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(od, "PENDING_REPORTS", tmp_path / "cloud_pending_reports")
    monkeypatch.setattr(od, "LEDGER", tmp_path / "no_ledger.jsonl")
    monkeypatch.setattr(od, "OD_LEDGER", tmp_path / "no_od_ledger.jsonl")
    overlay = tmp_path / "depth_overlay.json"
    overlay.write_text(json.dumps({"generated_at": "now", "scheme": "band_direction_v1",
                                   "count": 0, "actionable_count": 0, "gate_version": 2,
                                   "tickers": {}}), encoding="utf-8")
    monkeypatch.setattr(od, "OVERLAY", overlay)
    monkeypatch.setattr(od, "ops", type("_ops", (), {"notify_telegram": staticmethod(lambda *a, **k: None)}))
    return overlay


def test_publish_overlay_copies_outcomes_when_present(tmp_path, monkeypatch):
    clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    outcomes = tmp_path / "depth_outcomes.json"
    outcomes.write_text(json.dumps({"graded_verdict_horizons": 4, "caveats": []}),
                        encoding="utf-8")
    monkeypatch.setattr(od, "OUTCOMES", outcomes)

    od.publish_overlay()

    dst = clone / "public" / "data" / "depth_outcomes.json"
    assert dst.exists()
    assert json.loads(dst.read_text(encoding="utf-8"))["graded_verdict_horizons"] == 4
    log = subprocess.run(["git", "-C", str(clone), "log", "--oneline"],
                         capture_output=True, text=True, check=True).stdout
    assert "depth artifacts" in log


def test_publish_overlay_skips_outcomes_when_absent(tmp_path, monkeypatch):
    """A fresh checkout / one that predates the grader's first run must publish fine without it —
    the addition is optional, never a hard dependency of publishing the overlay."""
    clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    monkeypatch.setattr(od, "OUTCOMES", tmp_path / "does_not_exist.json")

    od.publish_overlay()

    assert not (clone / "public" / "data" / "depth_outcomes.json").exists()
    assert (clone / "public" / "data" / "depth_overlay.json").exists()


def test_publish_overlay_aborts_on_invalid_outcomes_json(tmp_path, monkeypatch):
    """A corrupt depth_outcomes.json must abort the whole publish (AC#3: a bad artifact never
    reaches a commit) exactly like a corrupt overlay would — never partially publish."""
    clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    outcomes = tmp_path / "depth_outcomes.json"
    outcomes.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(od, "OUTCOMES", outcomes)

    od.publish_overlay()

    # Nothing committed: the only commit on main is still the throwaway "init" one.
    log = subprocess.run(["git", "-C", str(clone), "log", "--oneline"],
                         capture_output=True, text=True, check=True).stdout
    assert "depth artifacts" not in log
