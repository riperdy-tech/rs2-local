import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_state  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "rs2-state"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@test")
    _git(clone, "config", "user.name", "test")
    _git(clone, "commit", "--allow-empty", "-m", "init")
    _git(clone, "push", "-u", "origin", "master")
    return clone


def test_sync_copies_state_and_pushes(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text('{"t": "AAA"}\n', encoding="utf-8")
    (cache / "depth_state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    out = sync_state.main(repo_dir=clone)
    assert "synced" in out
    assert (clone / "cache" / "depth_ledger.jsonl").read_text(encoding="utf-8") == '{"t": "AAA"}\n'
    assert json.loads((clone / "meta" / "last_pc_sync.json").read_text(encoding="utf-8"))["ts"]
    log = subprocess.run(["git", "-C", str(clone), "log", "--oneline"],
                         capture_output=True, text=True, check=True).stdout
    assert "state sync" in log


class _FrozenDatetime(datetime):
    """datetime stand-in whose now() never advances, so the meta timestamp is
    byte-identical across two runs and the 'no changes' branch is reachable."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 8, 30, 12, 0, 0, tzinfo=tz or timezone.utc)


def test_sync_noop_when_unchanged(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    monkeypatch.setattr(sync_state, "datetime", _FrozenDatetime)
    sync_state.main(repo_dir=clone)
    out = sync_state.main(repo_dir=clone)
    assert out == "no changes"


def test_cloud_delta_imported_and_truncated(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text('{"run": "AAA_1"}\n', encoding="utf-8")
    pending = clone / "cloud_pending"
    pending.mkdir()
    (pending / "depth_ledger_delta.jsonl").write_text(
        '{"run": "AAA_1"}\n{"run": "BBB_2"}\n', encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "cloud delta")
    _git(clone, "push")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    out = sync_state.main(repo_dir=clone)
    local = (cache / "depth_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert local == ['{"run": "AAA_1"}', '{"run": "BBB_2"}']  # deduped append
    assert (pending / "depth_ledger_delta.jsonl").read_text(encoding="utf-8") == ""
    assert "import 1 cloud rows" in out
