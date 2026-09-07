"""Depth cloud backstop driver — run by .github/workflows/depth-cloud-backstop.yml
on ubuntu-latest when the PC has missed depth sweeps (see the workflow preflight).

Degraded mode by design: no local research brief (published with
--include-no-brief), CI SearXNG only, no sec_facts verification. Rows are
stamped arm=cloud_api and return to the local arm on the usual triggers.

Flow:
  1. snapshot the ledger line-set (seeded from rs2-state by the workflow)
  2. pick the N live_book tickers with the oldest newest-verdict
  3. run deep_api_run.py T --fresh sequentially
  4. publish_cloud_verdicts.py --include-no-brief (no --push):
     ledger append + pending bundles + overlay rebuild
  5. overlay-count guard: rebuilt overlay must not shrink vs the published one
  6. orchestrate_depth.publish_overlay()  (same engine + invariants as the PC)
  7. append new ledger lines to $RS2_STATE_DIR/cloud_pending/depth_ledger_delta.jsonl,
     commit + push rs2-state (the PC imports + truncates via sync_state.py)
  8. Telegram summary
"""
from __future__ import annotations

import json
import os
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


def newest_dates(rows: list) -> dict:
    out = {}
    for r in rows:
        t = r.get("ticker")
        d = str(r.get("date") or "")
        if t and d >= out.get(t, ""):
            out[t] = d
    return out


def select_due(book: set, rows: list, n: int) -> list:
    """Oldest newest-verdict first; never-ledgered names sort before everything."""
    newest = newest_dates(rows)
    return sorted(book, key=lambda t: (newest.get(t, ""), t))[:n]


def compute_delta(before_lines: list, after_lines: list) -> list:
    before = set(before_lines)
    return [ln for ln in after_lines if ln not in before]


def publishable_book(book: set, rows: list) -> set:
    """Drop tickers whose NEWEST ledger row is local (arm != cloud_api):
    publish_cloud_verdicts.protected_local() refuses to publish those, so
    running them is pure API spend (measured: 3 of the 6 oldest were
    protected). Never-ledgered names stay in."""
    newest: dict = {}
    for r in rows:
        t = r.get("ticker")
        d = str(r.get("date") or "")
        if t and d >= newest.get(t, ("", None))[0]:
            newest[t] = (d, r.get("arm"))
    return {t for t in book if t not in newest or newest[t][1] == "cloud_api"}


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


def main() -> int:
    max_tickers = int(os.environ.get("BACKSTOP_MAX_TICKERS", "6"))
    state_dir = Path(os.environ["RS2_STATE_DIR"])

    import ops  # noqa: E402  (lazy: keeps unit tests hermetic)
    import orchestrate_depth as od  # noqa: E402

    before = _read_lines(LEDGER)
    if not before:
        ops.notify_telegram("depth backstop ABORT: seeded ledger is empty — "
                            "publishing would wipe the live overlay")
        return 1
    rows = []
    for ln in before:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            pass

    due = select_due(publishable_book(set(od.live_book()), rows), rows, max_tickers)
    if not due:
        print("nothing due")
        return 0
    print(f"backstop running {len(due)} tickers: {due}")

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
        r = subprocess.run(
            [sys.executable, str(API_DIR / "deep_api_run.py"), t, "--fresh"],
            cwd=str(ROOT), timeout=PER_TICKER_TIMEOUT_S)
        (ran if r.returncode == 0 else failed).append(t)

    if not ran and deferred and not failed:
        # Nothing billed, nothing to publish: an expected outcome, not a failure.
        ops.notify_telegram(f"depth backstop: peak-rate window — 0 run, "
                            f"{len(deferred)} deferred ({deferred})")
        return 0
    if not ran:
        ops.notify_telegram(f"depth backstop: all {len(failed)} runs failed "
                            f"({failed}) — nothing to publish")
        return 1

    pub = subprocess.run(
        [sys.executable, str(API_DIR / "publish_cloud_verdicts.py"), "--include-no-brief"],
        cwd=str(ROOT), timeout=600)
    if pub.returncode != 0:
        ops.notify_telegram("depth backstop ABORT: publish_cloud_verdicts failed "
                            f"(rc={pub.returncode})")
        return 1

    publish_repo = Path(od.CONFIG["screener_publish_repo"])
    old_count = _published_overlay_count(publish_repo)
    new_count = _overlay_count(OVERLAY)
    # FAIL CLOSED: a live published overlay is never empty (182 tickers today).
    # old_count == 0 means the guard is blind (unreadable/missing overlay) —
    # publishing blind is exactly the wipe this guard exists to prevent.
    if old_count == 0:
        ops.notify_telegram("depth backstop ABORT: cannot read published overlay "
                            "count — guard blind, NOT publishing")
        return 1
    if new_count < old_count:
        ops.notify_telegram(f"depth backstop ABORT: rebuilt overlay {new_count} "
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
        ops.notify_telegram("depth backstop ABORT: PC came alive mid-run — "
                            "not publishing (its sweep owns the overlay)")
        return 1
    if alive == "unreadable":
        print("WARNING: heartbeat unreadable at publish time — proceeding "
              "(preflight proved it readable at t=0)")

    od.publish_overlay()
    pushed = _synced_with_remote(publish_repo)

    after = _read_lines(LEDGER)
    delta = compute_delta(before, after)
    delta_ok = True
    if delta:
        pending = state_dir / "cloud_pending"
        pending.mkdir(parents=True, exist_ok=True)
        with (pending / "depth_ledger_delta.jsonl").open("a", encoding="utf-8") as f:
            for ln in delta:
                f.write(ln + "\n")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        # Every hop checked: a silent failure here means verdicts live on the
        # site but absent from the PC ledger — the next PC sweep would then
        # quietly revert them.
        for args in (["add", "-A"], ["commit", "-m", f"cloud backstop delta {ts}"],
                     ["pull", "--rebase"], ["push"]):
            r = subprocess.run(["git", "-C", str(state_dir), *args],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                ops.notify_telegram(
                    f"depth backstop: rs2-state '{' '.join(args)}' FAILED — delta "
                    f"NOT delivered to PC (site has rows the PC ledger lacks): "
                    + (r.stderr or r.stdout).strip()[:200])
                delta_ok = False
                break

    ops.notify_telegram(
        f"depth cloud backstop: ran {ran}, failed {failed}, "
        + (f"deferred (peak window) {deferred}, " if deferred else "")
        + f"push {'ok' if pushed else 'ABORTED (see prior alert)'}, "
        f"{len(delta)} delta rows to rs2-state"
        + ("" if delta_ok else " (DELTA DELIVERY FAILED)"))
    return 0 if (pushed and delta_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
