"""tests/test_screener_refresh.py — screener_refresh.refresh_screener_data() (P4.-1).

A real local git origin/clone (same pattern as tests/test_sync_state.py and
tests/test_publish_overlay_outcomes.py) rather than mocked git calls: the guard sequence (origin
check, dirty check, fetch, reset) is easiest to trust by actually running it against a throwaway
repo, never the real screener-publish clone.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import screener_refresh as sr  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_publish_clone(tmp_path):
    # Named with "stock-screener" in the path: refresh_screener_data() refuses any origin whose
    # URL doesn't contain that substring, same guard publish_overlay() makes.
    origin = tmp_path / "stock-screener.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "screener-publish-clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@test")
    _git(clone, "config", "user.name", "test")
    (clone / "public" / "data").mkdir(parents=True)
    (clone / "public" / "data" / "factor_scores.json").write_text("{}", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "init")
    _git(clone, "branch", "-M", "main")
    _git(clone, "push", "-u", "origin", "main")
    return origin, clone


def _isolate(monkeypatch, tmp_path, clone):
    monkeypatch.setitem(sr.CONFIG, "screener_publish_repo", str(clone))
    monkeypatch.setattr(sr, "PUBLISH_LOCK", tmp_path / "screener_publish.lock")
    monkeypatch.setattr(sr, "LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(sr.ops, "notify_telegram", lambda *a, **k: None)


def test_refresh_fetches_and_resets_to_the_new_upstream_commit(tmp_path, monkeypatch):
    origin, clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)

    # A second clone of the SAME origin pushes a new commit — simulates another session (or the
    # cloud arm) advancing origin/main since this clone last looked.
    other = tmp_path / "other-clone"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "test@test")
    _git(other, "config", "user.name", "test")
    # The bare origin's symbolic HEAD may still point at this machine's init.defaultBranch
    # (often "master"), which was never pushed — clone then leaves an empty working tree. "main"
    # exists as a remote-tracking ref regardless; check it out explicitly.
    _git(other, "checkout", "main")
    (other / "public" / "data" / "factor_scores.json").write_text(
        '{"engine": "dual_door_dynamic_macro_v2_cluster_guarded"}', encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "new snapshot")
    _git(other, "push", "origin", "main")
    expected_sha = subprocess.run(["git", "-C", str(other), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()

    ok, sha = sr.refresh_screener_data()

    assert ok is True
    assert sha == expected_sha
    # the clone's working tree now carries the new commit's content, not what it had at clone time
    assert json.loads((clone / "public" / "data" / "factor_scores.json").read_text(
        encoding="utf-8"))["engine"] == "dual_door_dynamic_macro_v2_cluster_guarded"
    head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    assert head == expected_sha


def test_refresh_is_a_noop_sha_when_nothing_changed(tmp_path, monkeypatch):
    _, clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    before = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True).stdout.strip()

    ok, sha = sr.refresh_screener_data()

    assert ok is True
    assert sha == before


def test_refresh_refuses_a_dirty_non_publish_path(tmp_path, monkeypatch):
    """A file outside publish_overlay's own output paths must never be reset over silently."""
    _, clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    (clone / "public" / "data" / "some_other_file.json").write_text("{}", encoding="utf-8")

    notified = []
    monkeypatch.setattr(sr.ops, "notify_telegram", lambda msg: notified.append(msg))

    ok, reason = sr.refresh_screener_data()

    assert ok is False
    assert "unexpected local changes" in reason
    assert len(notified) == 1
    assert "REFUSED" in notified[0]


def test_refresh_tolerates_dirty_publish_owned_paths(tmp_path, monkeypatch):
    """The SAME exclusion list publish_overlay's own dirty-check uses — its own output files
    (depth_overlay.json etc.) sitting uncommitted must never block a refresh."""
    _, clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    (clone / "public" / "data" / "depth_overlay.json").write_text("{}", encoding="utf-8")

    ok, sha = sr.refresh_screener_data()

    assert ok is True


def test_refresh_refuses_on_fetch_failure(tmp_path, monkeypatch):
    _, clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    # Point origin at a URL that cannot be fetched — the origin URL text must still contain
    # "stock-screener" to pass the earlier guard, but the remote itself must not exist.
    _git(clone, "remote", "set-url", "origin",
        str(tmp_path / "stock-screener-does-not-exist.git"))

    ok, reason = sr.refresh_screener_data()

    assert ok is False
    assert "fetch" in reason


def test_refresh_refuses_when_repo_is_not_a_git_clone(tmp_path, monkeypatch):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    monkeypatch.setitem(sr.CONFIG, "screener_publish_repo", str(not_a_repo))
    monkeypatch.setattr(sr, "PUBLISH_LOCK", tmp_path / "screener_publish.lock")
    monkeypatch.setattr(sr, "LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(sr.ops, "notify_telegram", lambda *a, **k: None)

    ok, reason = sr.refresh_screener_data()

    assert ok is False
    assert "not a git clone" in reason


def test_refresh_refuses_when_origin_is_not_stock_screener(tmp_path, monkeypatch):
    """Never fetch/reset a clone pointed somewhere unexpected — same guard publish_overlay makes
    before it ever pushes."""
    origin = tmp_path / "some-other-repo.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _isolate(monkeypatch, tmp_path, clone)

    ok, reason = sr.refresh_screener_data()

    assert ok is False
    assert "not stock-screener" in reason


def test_refresh_discards_an_unpushed_local_commit(tmp_path, monkeypatch):
    """checkout -B main origin/main, not a rebase/merge: refresh always wants exactly what
    origin has. A stray local commit (e.g. a previous run's crash mid-publish) is discarded, not
    preserved — harmless, because publish_overlay regenerates its artifacts fresh every run."""
    _, clone = _make_publish_clone(tmp_path)
    _isolate(monkeypatch, tmp_path, clone)
    (clone / "public" / "data" / "depth_overlay.json").write_text('{"stray": true}',
                                                                   encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "stray unpushed commit")
    stray_sha = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
    origin_sha = subprocess.run(["git", "-C", str(clone), "rev-parse", "origin/main"],
                                check=True, capture_output=True, text=True).stdout.strip()
    assert stray_sha != origin_sha

    ok, sha = sr.refresh_screener_data()

    assert ok is True
    assert sha == origin_sha
    assert not (clone / "public" / "data" / "depth_overlay.json").exists()
