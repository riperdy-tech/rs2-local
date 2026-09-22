import json
import subprocess
import sys
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


def test_sync_noop_when_unchanged(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    sync_state.main(repo_dir=clone)
    meta = clone / "meta" / "last_pc_sync.json"
    stamp_after_first = meta.read_text(encoding="utf-8")
    out = sync_state.main(repo_dir=clone)
    assert out == "no changes"
    # the meta stamp is change-gated: an unchanged run must not rewrite it
    assert meta.read_text(encoding="utf-8") == stamp_after_first


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


def test_recovers_from_cloud_race_and_dirty_index(tmp_path, monkeypatch):
    """The wedge the disposable-clone reset exists to prevent.

    PC and cloud BOTH write cloud_pending/ (the PC truncates the delta it
    imported), so a cloud push racing an unpushed truncation used to conflict
    under `pull --rebase` and strand the clone mid-rebase; a run killed between
    `add -A` and commit left a dirty index that `pull --rebase` also refuses.
    Both states must now self-heal on the next run.
    """
    clone = _make_repos(tmp_path)
    origin = tmp_path / "origin.git"
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text('{"run": "X1"}\n', encoding="utf-8")
    pending = clone / "cloud_pending"
    pending.mkdir()
    (pending / "depth_ledger_delta.jsonl").write_text(
        '{"run": "X1"}\n{"run": "X2"}\n', encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "cloud delta")
    _git(clone, "push")
    monkeypatch.setattr(sync_state, "CACHE", cache)

    # State a prior run left behind: it imported X2 and truncated the delta,
    # committed, then LOST THE PUSH. Built with git directly rather than by
    # calling main(), so the fixture does not depend on the code under test.
    (cache / "depth_ledger.jsonl").write_text(
        '{"run": "X1"}\n{"run": "X2"}\n', encoding="utf-8")
    (pending / "depth_ledger_delta.jsonl").write_text("", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "state sync (push lost)")

    # meanwhile the cloud, still seeing the un-truncated delta, appends a new
    # verdict row and pushes — same file the unpushed local commit rewrote
    cloud = tmp_path / "cloud"
    subprocess.run(["git", "clone", str(origin), str(cloud)], check=True, capture_output=True)
    _git(cloud, "config", "user.email", "cloud@test")
    _git(cloud, "config", "user.name", "cloud")
    (cloud / "cloud_pending" / "depth_ledger_delta.jsonl").write_text(
        '{"run": "X1"}\n{"run": "X2"}\n{"run": "Y1"}\n', encoding="utf-8")
    _git(cloud, "add", "-A")
    _git(cloud, "commit", "-m", "cloud verdicts")
    _git(cloud, "push")

    # a prior PC run killed between `add -A` and commit: staged, uncommitted
    (clone / "cache").mkdir(exist_ok=True)
    (clone / "cache" / "junk.tmp").write_text("killed mid-run", encoding="utf-8")
    _git(clone, "add", "-A")

    out = sync_state.main(repo_dir=clone)
    assert not out.startswith("error"), out
    assert (cache / "depth_ledger.jsonl").read_text(encoding="utf-8").splitlines() == [
        '{"run": "X1"}', '{"run": "X2"}', '{"run": "Y1"}']  # only Y1 added; X1/X2 deduped
    assert "import 1 cloud rows" in out
    assert not (clone / "cache" / "junk.tmp").exists()  # reset discarded the dirty index
    assert (pending / "depth_ledger_delta.jsonl").read_text(encoding="utf-8") == ""
    pushed = subprocess.run(
        ["git", "-C", str(clone), "show", "@{u}:cloud_pending/depth_ledger_delta.jsonl"],
        capture_output=True, text=True, check=True).stdout
    assert pushed == ""  # truncation reached the remote


def test_cloud_membership_merged_by_date_local_wins(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text("x\n", encoding="utf-8")
    # local record: 09-05 and 09-06 (PC then went off)
    (cache / "depth_membership.jsonl").write_text(
        '{"date": "2026-09-05", "in": ["AAA"]}\n{"date": "2026-09-06", "in": ["AAA", "LOCAL"]}\n',
        encoding="utf-8")
    # cloud record handed back: its copy of 09-06 (different, must LOSE) + 09-07 + 09-08 it swept
    (clone / "cache").mkdir()
    (clone / "cache" / "depth_membership.jsonl").write_text(
        '{"date": "2026-09-06", "in": ["AAA", "CLOUD"]}\n{"date": "2026-09-07", "in": ["AAA"]}\n'
        '{"date": "2026-09-08", "in": ["BBB"]}\n', encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-m", "cloud continuity"); _git(clone, "push")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    out = sync_state.main(repo_dir=clone)
    assert "merge 2 cloud membership day(s)" in out
    merged = [json.loads(l) for l in (cache / "depth_membership.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert [r["date"] for r in merged] == ["2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08"]
    assert merged[1]["in"] == ["AAA", "LOCAL"]          # same date: local row wins
    # and the merged file is what went back up, so the cloud days are not lost on the next seed
    up = subprocess.run(["git", "-C", str(clone), "show", "@{u}:cache/depth_membership.jsonl"],
                        capture_output=True, text=True, check=True).stdout
    assert up == (cache / "depth_membership.jsonl").read_text(encoding="utf-8")


def test_cloud_state_rows_taken_only_when_cloud_stamped_and_newer(tmp_path, monkeypatch):
    clone = _make_repos(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_ledger.jsonl").write_text("x\n", encoding="utf-8")
    (cache / "depth_state.json").write_text(json.dumps({
        "AAA": {"ok": False, "retries": 1, "date": "2026-09-05 10:00"},   # PC failed it
        "BBB": {"ok": True, "date": "2026-09-06 12:00"},
        "CCC": {"ok": True, "date": "2026-09-06 12:00"}}), encoding="utf-8")
    (clone / "cache").mkdir()
    (clone / "cache" / "depth_state.json").write_text(json.dumps({
        "AAA": {"ok": True, "date": "2026-09-07 18:30", "arm": "cloud_api"},   # cloud completed it
        "BBB": {"ok": False, "retries": 1, "date": "2026-09-01 00:00", "arm": "cloud_api"},  # older
        "CCC": {"ok": False, "date": "2026-09-08 00:00"},                      # not cloud-stamped
        "DDD": {"ok": False, "retries": 1, "date": "2026-09-07 19:00", "arm": "cloud_api"}}),
        encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-m", "cloud continuity"); _git(clone, "push")
    monkeypatch.setattr(sync_state, "CACHE", cache)
    out = sync_state.main(repo_dir=clone)
    assert "take 2 cloud state row(s)" in out
    st = json.loads((cache / "depth_state.json").read_text(encoding="utf-8"))
    assert st["AAA"] == {"ok": True, "date": "2026-09-07 18:30", "arm": "cloud_api"}
    assert st["BBB"]["ok"] is True                       # older cloud row ignored
    assert st["CCC"]["ok"] is True                       # PC's own row copied through: ignored
    assert st["DDD"]["retries"] == 1                     # cloud failure spends the shared budget
