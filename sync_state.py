"""Back up local-only depth state to the private rs2-state repo, and import
cloud-backstop ledger deltas back into the local ledger.

cache/ is gitignored in rs2-local; losing it resets the whole depth queue.
The cloud depth backstop (rs2-local .github/workflows/depth-cloud-backstop.yml)
also needs this state to run while the PC is off, and hands its new verdict
rows back via cloud_pending/depth_ledger_delta.jsonl.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
STATE_REPO = Path("C:/Users/riper/Downloads/rs2-state")
STATE_FILES = [
    "depth_ledger.jsonl",
    "depth_ondemand_ledger.jsonl",
    "depth_state.json",
    "depth_membership.jsonl",
    "depth_overlay.json",
    "depth_ondemand.jsonl",
]
DELTA = Path("cloud_pending") / "depth_ledger_delta.jsonl"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=120)


def _import_cloud_delta(repo_dir: Path) -> int:
    """Append cloud-written ledger rows missing locally; truncate the delta."""
    delta_path = repo_dir / DELTA
    if not delta_path.exists():
        return 0
    delta_lines = [ln for ln in delta_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not delta_lines:
        return 0
    ledger = CACHE / "depth_ledger.jsonl"
    have = set()
    if ledger.exists():
        have = {ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()}
    new = [ln for ln in delta_lines if ln not in have]
    if new:
        with ledger.open("a", encoding="utf-8") as f:
            for ln in new:
                f.write(ln + "\n")
    delta_path.write_text("", encoding="utf-8")
    return len(new)


def main(repo_dir: Path | None = None) -> str:
    repo = Path(repo_dir) if repo_dir else STATE_REPO
    if not (repo / ".git").exists():
        return f"error: {repo} is not a git clone"
    # The state clone is DISPOSABLE: every PC-side file is regenerated from
    # CACHE each run, and the delta import is dedupe-idempotent (a discarded
    # unpushed truncation just re-imports 0 new rows and re-truncates). So we
    # never merge/rebase: clear any wedged rebase from a prior life, fetch, and
    # hard-reset to upstream. A lost push race returns an error and the next
    # run resets + retries — no state can wedge this permanently.
    _git(repo, "rebase", "--abort")  # harmless nonzero when no rebase in progress
    fetch = _git(repo, "fetch")
    if fetch.returncode != 0:
        return "error: fetch failed: " + (fetch.stderr or fetch.stdout).strip()[:300]
    reset = _git(repo, "reset", "--hard", "@{u}")
    if reset.returncode != 0:
        return "error: reset failed: " + (reset.stderr or reset.stdout).strip()[:300]

    imported = _import_cloud_delta(repo)

    (repo / "cache").mkdir(exist_ok=True)
    for name in STATE_FILES:
        src = CACHE / name
        if src.exists():
            shutil.copy2(src, repo / "cache" / name)

    _git(repo, "add", "-A")
    if not _git(repo, "status", "--porcelain").stdout.strip():
        return "no changes"

    # meta stamp only when something actually changed — a fresh timestamp every
    # run would force an hourly commit forever (unbounded repo growth).
    (repo / "meta").mkdir(exist_ok=True)
    (repo / "meta" / "last_pc_sync.json").write_text(
        json.dumps({"ts": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    _git(repo, "add", "-A")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    commit = _git(repo, "commit", "-m", f"state sync {ts}")
    if commit.returncode != 0:
        return "error: commit failed: " + (commit.stderr or commit.stdout).strip()[:300]
    push = _git(repo, "push")
    if push.returncode != 0:
        return "error: push failed (next run resets + retries): " + (push.stderr or push.stdout).strip()[:300]
    n = sum(1 for name in STATE_FILES if (CACHE / name).exists())
    msg = f"synced {n} files"
    if imported:
        msg += f", import {imported} cloud rows"
    return msg


if __name__ == "__main__":
    result = main()
    print(result)
    sys.exit(1 if result.startswith("error") else 0)
