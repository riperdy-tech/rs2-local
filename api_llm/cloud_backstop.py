"""Depth cloud continuity arm — run by .github/workflows/depth-cloud-backstop.yml
on ubuntu-latest while the PC heartbeat is dead (see the workflow preflight).

OPERATOR DECISION 2026-09-07: the cloud arm serves the SAME queue the PC serves
— DEPTH_ORCHESTRATOR_CADENCE_20260825.md §3/§5 via orchestrate_depth.build_queue
— so the spec's homework (8-K / filing / move / pack / exit-review / baseline /
re-entry / rotation, in that priority) keeps getting done when the PC is off.
It replaces the earlier "oldest-verdict-first" backstop, which was not the
agreed cadence. DeepSeek OFF-PEAK ONLY (api_llm/deepseek_offpeak.py).

Degraded mode by design: no local research brief (published with
--include-no-brief), CI SearXNG only, no sec_facts verification. Rows are
stamped arm=cloud_api for provenance only: operator decision 2026-09-07, local
and cloud verdicts are the same kind of result and the newest one wins, whichever
arm produced it.

Flow:
  1. snapshot the ledger line-set (seeded from rs2-state by the workflow)
  2. record today's RN+WL membership row (mem.snapshot) — the dwell clocks
     advance one row per sweep-day, cloud or PC
  3. queue = orchestrate_depth.build_queue(...) on the seeded state, exactly
     as the PC computes it; take the first BACKSTOP_MAX_TICKERS
  4. run deep_api_run.py T --fresh sequentially, each only if its whole
     worst-case runtime is off-peak; update depth_state.json ok/fail+retries
     exactly like the PC does
  5. publish_cloud_verdicts.py --include-no-brief (no --push):
     ledger append + pending bundles + overlay rebuild
  6. overlay-count guard: rebuilt overlay must not shrink vs the published one
  7. PC-alive TOCTOU re-check, then orchestrate_depth.publish_overlay()
  8. hand state back to rs2-state: new ledger lines appended to
     cloud_pending/depth_ledger_delta.jsonl, plus cache/depth_membership.jsonl
     and cache/depth_state.json; commit + push (the PC merges via sync_state.py)
  9. Telegram summary

  python api_llm/cloud_backstop.py --dry-run     # print the queue, run nothing
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from deepseek_offpeak import run_window_ok

API_DIR = Path(__file__).resolve().parent
ROOT = API_DIR.parent
sys.path.insert(0, str(ROOT))

LEDGER = ROOT / "cache" / "depth_ledger.jsonl"
OVERLAY = ROOT / "cache" / "depth_overlay.json"
MEMBERSHIP = ROOT / "cache" / "depth_membership.jsonl"
STATE = ROOT / "cache" / "depth_state.json"
# 45 min/ticker (median 21, historic max 35): 6 tickers worst-case 270 min +
# overhead stays under the job's 340-min timeout — 3600 did not (6h of ticker
# work alone would be killed mid-flight with spend incurred and no alert).
PER_TICKER_TIMEOUT_S = 2700
# Same threshold the workflow preflight uses. The preflight's verdict is up to
# ~5h old by publish time (6 tickers x 45 min); the publish lock is PC-LOCAL, so
# nothing but this re-check stops a woken PC and this job publishing over
# each other.
HB_ALIVE_MAX_MIN = 90


def _read_lines(p: Path) -> list:
    try:
        return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []


def compute_delta(before_lines: list, after_lines: list) -> list:
    before = set(before_lines)
    return [ln for ln in after_lines if ln not in before]


def _overlay_count(path: Path) -> int:
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("tickers", {}))
    except (OSError, ValueError):
        return 0


def _published_overlay_count(repo: Path) -> int:
    """Ticker count of origin/main's overlay — fetched NOW, so the guard
    baseline is what publish_overlay will actually overwrite (the working
    tree can be stale if the PC published since checkout)."""
    fetch = subprocess.run(["git", "-C", str(repo), "fetch", "origin", "main"],
                           capture_output=True, text=True, timeout=120)
    if fetch.returncode != 0:
        # git show would silently read the STALE clone-time ref — the exact
        # baseline this function exists to eliminate. 0 -> fail-closed abort.
        return 0
    r = subprocess.run(
        ["git", "-C", str(repo), "show", "origin/main:public/data/depth_overlay.json"],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return 0
    try:
        return len(json.loads(r.stdout).get("tickers", {}))
    except ValueError:
        return 0


def _hb_age_min(rows: list, now: datetime):
    """Age in minutes of the rs2-pc heartbeat row. None = readable but ABSENT
    (which is 'dead', not 'unknown' — the row is created on first heartbeat).
    Raises on a malformed/absent updated_at; the caller maps that to unreadable."""
    if not rows:
        return None
    hb = datetime.fromisoformat(str(rows[0]["updated_at"]).replace("Z", "+00:00"))
    if hb.tzinfo is None:  # Supabase stamps tz-aware; be explicit anyway
        hb = hb.replace(tzinfo=timezone.utc)
    return (now - hb).total_seconds() / 60


def _fetch_hb_rows() -> list:
    """Thin stdlib fetch of the rs2-pc heartbeat row (seam for _hb_age_min)."""
    url = (os.environ["RS2_SUPABASE_URL"].rstrip("/")
           + "/rest/v1/control_heartbeat?id=eq.rs2-pc&select=updated_at")
    key = os.environ["RS2_SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(url, headers={
        "apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _pc_alive_recheck() -> str:
    """TOCTOU re-check of the preflight's PC-dead verdict, immediately before
    publishing. -> "alive" | "dead" | "unreadable"."""
    try:
        rows = _fetch_hb_rows()
    except Exception as e:  # noqa: BLE001 — any transport/env failure is 'blind'
        print(f"interlock re-check: heartbeat read FAILED ({e})")
        return "unreadable"
    try:
        age = _hb_age_min(rows, datetime.now(timezone.utc))
    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"interlock re-check: heartbeat unparseable ({e})")
        return "unreadable"
    if age is None:
        print("interlock re-check: no heartbeat row — PC dead")
        return "dead"
    print(f"interlock re-check: heartbeat age {age:.0f}m")
    return "alive" if age < HB_ALIVE_MAX_MIN else "dead"


def _synced_with_remote(repo: Path) -> bool:
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "-C", str(repo), "ls-remote", "origin",
                             "-h", "refs/heads/main"],
                            capture_output=True, text=True).stdout.split()
    return bool(head) and bool(remote) and remote[0] == head


def _handback_state(state_dir: Path, delta: list, ts: str) -> str:
    """Hand this run's state back to rs2-state so the PC (sync_state.py) and the
    next cloud run both continue from it: ledger delta rows (append), the
    membership log and depth_state.json (whole files — the PC merges them by
    date / by ticker). Returns "" on success, else the failing git step's message.
    Every hop checked: a silent failure here means verdicts live on the site
    but absent from the PC ledger — the next PC sweep would then quietly revert
    them — and dwell days recorded here would vanish from every count."""
    if delta:
        pending = state_dir / "cloud_pending"
        pending.mkdir(parents=True, exist_ok=True)
        with (pending / "depth_ledger_delta.jsonl").open("a", encoding="utf-8") as f:
            for ln in delta:
                f.write(ln + "\n")
    (state_dir / "cache").mkdir(parents=True, exist_ok=True)
    for src in (MEMBERSHIP, STATE):
        if src.exists():
            shutil.copy2(src, state_dir / "cache" / src.name)
    if not subprocess.run(["git", "-C", str(state_dir), "status", "--porcelain"],
                          capture_output=True, text=True, timeout=60).stdout.strip():
        return ""                                   # nothing new to hand back
    for args in (["add", "-A"], ["commit", "-m", f"cloud continuity {ts}"],
                 ["pull", "--rebase"], ["push"]):
        r = subprocess.run(["git", "-C", str(state_dir), *args],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return f"rs2-state '{' '.join(args)}' FAILED: " + (r.stderr or r.stdout).strip()[:200]
    return ""


def main() -> int:
    dry = "--dry-run" in sys.argv
    max_tickers = int(os.environ.get("BACKSTOP_MAX_TICKERS", "6"))
    state_dir = Path(os.environ["RS2_STATE_DIR"]) if not dry else None

    import ops  # noqa: E402  (lazy: keeps unit tests hermetic)
    import orchestrate_depth as od  # noqa: E402
    import depth_triggers  # noqa: E402
    import depth_membership as mem  # noqa: E402
    import rs2_data  # noqa: E402

    before = _read_lines(LEDGER)
    if not before:
        ops.notify_telegram("depth continuity ABORT: seeded ledger is empty — "
                            "publishing would wipe the live overlay")
        return 1

    # Today's RN+WL membership row FIRST, exactly where the PC records it: the
    # dwell clocks (spec §4) count sweep-days, and a PC-off day the cloud sweeps
    # is a sweep-day. Handed back to rs2-state below so it survives.
    sd_date, sd_n = mem.snapshot()
    rows = mem.snapshots_recorded()
    print(f"membership snapshot {sd_date}: {sd_n} in RN+WL | {rows} daily rows on record")
    if sd_n == 0:
        # FAIL CLOSED: RN+WL is never empty (170 names). An empty row means the
        # screener checkout is unreadable; handing it back would put every name
        # "out" for a day and fire exit-review across the book. Not handed back.
        ops.notify_telegram("depth continuity ABORT: membership snapshot empty — "
                            "factor_scores.json unreadable on the runner")
        return 1

    # THE PC's QUEUE, computed by the PC's function on the PC's (seeded) state.
    st = od.load_state()
    book = od.live_book()
    trig = depth_triggers.trigger_map(book)
    verdicts = depth_triggers.newest_verdicts()
    fs = (rs2_data.load_json(od.SD / "factor_scores.json") or {}).get("tickers", {})
    ordered = od.build_queue(book, st, trig, verdicts, fs, dwell_in=mem.dwell_in,
                             held=mem.held_names(), rows=rows)
    for t, c, why in ordered:
        print(f"   queued {t:6} class {c}: {why[:110]}")
    due = [t for t, _, _ in ordered][:max_tickers]
    print(f"book {len(book)} | due {len(ordered)} | this run: {due}")
    if dry:
        print("--dry-run: nothing run, nothing written.")
        return 0
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    if not due:
        print("nothing due")
        err = _handback_state(state_dir, [], ts)      # the membership row still counts
        if err:
            ops.notify_telegram("depth continuity: " + err)
        return 1 if err else 0

    # OFF-PEAK ONLY (operator, 2026-09-07): a ticker starts only if its whole
    # worst-case runtime stays inside DeepSeek's off-peak window. The preflight
    # checks the same thing at t=0; this re-check matters because 6 tickers can
    # span 4.5h and GitHub's cron drift can land the job late in the window.
    ran, failed, deferred = [], [], []
    for i, t in enumerate(due):
        if not run_window_ok(datetime.now(timezone.utc), PER_TICKER_TIMEOUT_S):
            deferred = due[i:]
            print(f"peak-rate window reached — {len(deferred)} ticker(s) deferred "
                  f"to the next off-peak run: {deferred}")
            break
        try:
            r = subprocess.run(
                [sys.executable, str(API_DIR / "deep_api_run.py"), t, "--fresh"],
                cwd=str(ROOT), timeout=PER_TICKER_TIMEOUT_S)
            ok, why = r.returncode == 0, f"exit_{r.returncode}"
        except subprocess.TimeoutExpired:
            ok, why = False, "watchdog_timeout"
        (ran if ok else failed).append(t)
        # Same state record the PC writes (orchestrate_depth.main), so a name
        # that fails here spends the SAME retry budget it would spend there.
        rec = st.get(t) or {}
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        st[t] = ({"ok": True, "finished_at": datetime.now().timestamp(), "date": stamp,
                  "arm": "cloud_api"} if ok else
                 {"ok": False, "why": why, "retries": rec.get("retries", 0) + 1,
                  "date": stamp, "arm": "cloud_api"})
        od.save_state(st)

    if not ran:
        if deferred and not failed:
            # Nothing billed, nothing to publish: an expected outcome, not a failure.
            ops.notify_telegram(f"depth continuity: peak-rate window — 0 run, "
                                f"{len(deferred)} deferred ({deferred})")
        else:
            ops.notify_telegram(f"depth continuity: all {len(failed)} runs failed "
                                f"({failed}) — nothing to publish")
        err = _handback_state(state_dir, [], ts)      # membership row + retry counts
        if err:
            ops.notify_telegram("depth continuity: " + err)
        return 0 if (deferred and not failed and not err) else 1

    pub = subprocess.run(
        [sys.executable, str(API_DIR / "publish_cloud_verdicts.py"), "--include-no-brief"],
        cwd=str(ROOT), timeout=600)
    if pub.returncode != 0:
        ops.notify_telegram("depth continuity ABORT: publish_cloud_verdicts failed "
                            f"(rc={pub.returncode})")
        return 1

    publish_repo = Path(od.CONFIG["screener_publish_repo"])
    old_count = _published_overlay_count(publish_repo)
    new_count = _overlay_count(OVERLAY)
    # FAIL CLOSED: a live published overlay is never empty (182 tickers today).
    # old_count == 0 means the guard is blind (unreadable/missing overlay) —
    # publishing blind is exactly the wipe this guard exists to prevent.
    if old_count == 0:
        ops.notify_telegram("depth continuity ABORT: cannot read published overlay "
                            "count — guard blind, NOT publishing")
        return 1
    if new_count < old_count:
        ops.notify_telegram(f"depth continuity ABORT: rebuilt overlay {new_count} "
                            f"tickers < published {old_count} — ledger seed "
                            "incomplete, NOT publishing")
        return 1

    # TOCTOU: the preflight proved the PC dead hours ago. If it woke since,
    # its own sweep owns the overlay and the (PC-local) publish lock cannot see
    # this runner — abort rather than race. Unreadable proceeds on purpose:
    # the preflight already proved the heartbeat readable at t=0, so a second
    # failure here is the unlikely case and aborting would burn the whole run.
    alive = _pc_alive_recheck()
    if alive == "alive":
        ops.notify_telegram("depth continuity ABORT: PC came alive mid-run — "
                            "not publishing (its sweep owns the overlay)")
        return 1
    if alive == "unreadable":
        print("WARNING: heartbeat unreadable at publish time — proceeding "
              "(preflight proved it readable at t=0)")

    od.publish_overlay()
    pushed = _synced_with_remote(publish_repo)

    delta = compute_delta(before, _read_lines(LEDGER))
    err = _handback_state(state_dir, delta, ts)
    if err:
        ops.notify_telegram(f"depth continuity: {err} — state NOT delivered to PC "
                            "(site has rows the PC ledger lacks)")

    ops.notify_telegram(
        f"depth cloud continuity: ran {ran}, failed {failed}, "
        + (f"deferred (peak window) {deferred}, " if deferred else "")
        + f"push {'ok' if pushed else 'ABORTED (see prior alert)'}, "
        f"{len(delta)} delta rows + membership/state to rs2-state"
        + ("" if not err else " (HANDBACK FAILED)"))
    return 0 if (pushed and not err) else 1


if __name__ == "__main__":
    sys.exit(main())
