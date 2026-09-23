#!/usr/bin/env python3
"""screener_refresh.py — refresh the DEDICATED screener-publish clone to origin/main.

P4.-1 (PHASE_4_AMENDMENTS.md A1, 2026-09-24 orchestrator review). Before this, `screener_data_dir`
pointed at the shared `stock-screener` dev checkout, which any other session can leave on a stale
branch with no signal to a reader — ~20 consumers (rs2_data, capability_test, depth_membership,
depth_triggers, grade_depth_verdicts, ...) silently read old files. `paths.py` now resolves
`screener_data_dir` to `<screener_publish_repo>/public/data` — the SAME dedicated clone
`orchestrate_depth.publish_overlay()` already writes to — so refreshing that one clone to
`origin/main` before reading is enough to make every consumer current.

`refresh_screener_data()` is the single function every entry point that reads screener data calls
first: `orchestrate_depth.main()`, `depth_ondemand.drain()`, and `depth_pipeline.main()` on a
standalone (non-spawned) invocation. It is a SEPARATE small module, not a function added to
`orchestrate_depth.py`, because `depth_pipeline.py` and `depth_ondemand.py` cannot import
`orchestrate_depth` (it re-wraps `sys.stdout` at import time — documented in
`depth_ondemand.py`'s `_run_one` — and its own `log()` writes into the sweep log `status.py`
parses, which a per-ticker child must not interleave into).

Guard and git sequence mirror `orchestrate_depth.publish_overlay()` exactly (same target repo, same
dirty-path exclusions, same "never push/reset an unexpected remote" check) because refreshing and
publishing are two critical sections over the SAME clone:
  1. the clone must be configured and be a real git repo, or refuse;
  2. its origin must be the screener repo, or refuse — never fetch/reset a clone pointed somewhere
     else;
  3. it must be clean except the paths `publish_overlay()` itself writes — a dirty clone is
     investigated, never reset over;
  4. `git fetch origin main`, then `git checkout -B main origin/main` — never a rebase or merge,
     because refresh always wants exactly what origin has, discarding any local commit that was
     never pushed (harmless: publish_overlay regenerates its artifacts fresh every run).
Steps 3-4 run under the SAME cross-process lock file `orchestrate_depth.PUBLISH_LOCK` uses
(`cache/screener_publish.lock`) — defined again here, not imported, for the reason above; the O_EXCL
lockfile itself is what serialises the two processes, not which module's context manager holds it.

On ANY failure the caller must refuse to run rather than analyse against data nobody has verified
is current (non-negotiable: real money). Returns (True, sha) on success, (False, reason) on
failure — the reason is already logged and Telegram-alerted here, exactly like a publish abort, so
callers need only decide whether to proceed.
"""
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import ops                  # noqa: E402
import rs2_data             # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = rs2_data.CONFIG

# SAME file orchestrate_depth._publish_lock() locks — the OS-level O_CREAT|O_EXCL lockfile is
# what provides cross-process mutual exclusion, independent of which module's context manager
# opened it. Two producers already share this file today (the sweep and
# api_llm/publish_cloud_verdicts.py, both via publish_overlay); this refresh is a third.
PUBLISH_LOCK = HERE / "cache" / "screener_publish.lock"
# Same persistent tail orchestrate_depth.DEPTH_LOG appends to, so a refresh line sits inline with
# the sweep log status.py already parses instead of scattering into a file nobody watches.
LOG = HERE / "cache" / "depth_orchestrate.log"


def _log(msg):
    line = f"[screener-refresh {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _abort(msg):
    _log(f"REFUSE: {msg}")
    try:
        ops.notify_telegram(f"[sweep] screener data refresh REFUSED: {msg}")
    except Exception:
        pass


@contextmanager
def _lock(timeout=200):
    """Byte-identical pattern to orchestrate_depth._publish_lock() — see the module docstring for
    why this is a second implementation of the same lock rather than an import."""
    got, deadline = False, time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(str(PUBLISH_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {datetime.now().isoformat()}".encode())
            os.close(fd)
            got = True
            break
        except FileExistsError:
            try:
                age = time.time() - PUBLISH_LOCK.stat().st_mtime
            except OSError:
                age = 0
            if age > timeout:
                try:
                    PUBLISH_LOCK.unlink()
                except OSError:
                    pass
                continue
            time.sleep(2)
    if not got:
        _log("screener lock not acquired in time — proceeding best-effort")
    try:
        yield
    finally:
        if got:
            try:
                PUBLISH_LOCK.unlink()
            except OSError:
                pass


def refresh_screener_data():
    """Reset CONFIG['screener_publish_repo'] to origin/main. Returns (True, sha) or (False, reason).

    `reason` on failure is already logged and Telegram-alerted (see `_abort`) — the caller's job is
    only to refuse to proceed, never to retry or fall back to whatever the clone already had on
    disk.
    """
    repo = Path(str(CONFIG.get("screener_publish_repo") or "")).expanduser()
    if not str(repo) or not (repo / ".git").exists():
        reason = f"screener_publish_repo is not a git clone: {repo!s}"
        _abort(reason)
        return False, reason

    def g(*a):
        return subprocess.run(["git", "-C", str(repo)] + list(a),
                              capture_output=True, text=True, timeout=120)

    # Never fetch/reset a clone pointed somewhere unexpected — same check publish_overlay makes.
    origin = g("remote", "get-url", "origin").stdout.strip()
    if "stock-screener" not in origin:
        reason = f"screener_publish_repo origin is not stock-screener: {origin!r}"
        _abort(reason)
        return False, reason

    try:
        with _lock():
            # Refuse a clone dirtied by anything other than publish_overlay's own output paths —
            # a `checkout -B main origin/main` over foreign uncommitted work would discard it
            # silently. Same exclusion list as publish_overlay's dirty-check.
            dirty = g("status", "--porcelain", "--",
                      ":!public/data/depth_overlay.json", ":!public/data/depth_outcomes.json",
                      ":!public/data/depth_reports",
                      ":!public/data/ondemand_index.json", ":!public/data/ondemand_reports").stdout.strip()
            if dirty:
                reason = "screener_publish_repo has unexpected local changes — investigate, not resetting over"
                _abort(reason)
                return False, reason

            if g("fetch", "origin", "main").returncode != 0:
                reason = "git fetch origin main failed on screener_publish_repo"
                _abort(reason)
                return False, reason

            if g("checkout", "-B", "main", "origin/main").returncode != 0:
                reason = "could not reset screener_publish_repo to origin/main"
                _abort(reason)
                return False, reason

            sha = g("rev-parse", "HEAD").stdout.strip()
            if not sha:
                reason = "could not read HEAD sha after resetting screener_publish_repo"
                _abort(reason)
                return False, reason
    except Exception as e:
        reason = f"unexpected error refreshing screener_publish_repo: {str(e)[:150]}"
        _abort(reason)
        return False, reason

    _log(f"screener data refreshed to {sha}")
    return True, sha
