#!/usr/bin/env python3
"""depth_ondemand.py — analyse ANY universe ticker on request, without touching the book.

WHY THIS EXISTS (operator order 2026-08-30): the depth sweep only ever analyses names that
pass the quant screen. The operator wants a verdict on an arbitrary ticker — including
quant-screen fails — on demand: immediately when the GPU is idle, or at the next ticker
boundary when a sweep is mid-run.

WHY THE SEPARATE LEDGER IS THE WHOLE DESIGN: a row in cache/depth_ledger.jsonl is not just a
record — live_book() unions ledger tickers into the book FOREVER, rebuild_overlay publishes
the newest row per ticker UNFILTERED to the screener site, track_paper_portfolios puts any
undervalued overlay row into the rn_depth paper book (no band filter — test-asserted), and
rotation re-queues ledgered names every 90 days. One ad-hoc row would therefore publish an
off-screen name to the site, trade it in the tracked AI portfolio, and re-analyse it
quarterly forever. On-demand verdicts go to cache/depth_ondemand_ledger.jsonl: one-shot,
invisible to the overlay/book/paper machinery by construction. They DO publish to the site's
DEDICATED on-demand section (public/data/ondemand_index.json + ondemand_reports/ — operator
order 2026-08-30, rendered at /ondemand), which none of the book consumers read.
(api_llm/publish_cloud_verdicts.py refuses off-book rows for exactly this reason.)

FLOW: request (CLI here, or /analyze via telegram_status_bot) -> precheck (universe + price;
a name with no financials/{T}.json price is a GUARANTEED NOT_USABLE after ~2h of GPU, because
the consensus envelope test needs price) -> queue cache/depth_ondemand.jsonl -> drained by
whichever is running: orchestrate_depth at each ticker boundary (jumps the remaining sweep
queue), or the detached idle runner spawned here. DEPTH_PAUSED wins over pending requests —
the red button exists to free the GPU, so requests wait for resume.

LOCK: the idle runner takes cache/orchestrate_depth.lock (same JSON shape). A scheduled
sweep firing mid-run sees a live lock and exits cleanly; its 4h cadence retries. A second
lock would just mean a second check in orchestrate and a GPU double-load on any miss.

CLAIM-BEFORE-RUN, NO RETRY: a runner crash after claiming a request loses it (the failure is
telegram-alerted; re-request). One-shot semantics — no retry debt, no state rows.

    python depth_ondemand.py NVDA        # enqueue (runs now if idle)
    python depth_ondemand.py --status    # pending queue + recent on-demand verdicts
    python depth_ondemand.py --run       # foreground drain (normally spawned detached)
"""
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ops                  # noqa: E402
import rs2_data             # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
QUEUE = HERE / "cache" / "depth_ondemand.jsonl"
QLOCK = HERE / "cache" / "depth_ondemand.queue.lock"
OD_LEDGER = HERE / "cache" / "depth_ondemand_ledger.jsonl"
ORCH_LOCK = HERE / "cache" / "orchestrate_depth.lock"
PAUSED = HERE / "cache" / "DEPTH_PAUSED"
PROGRESS = HERE / "cache" / "depth_progress.json"
LOG = HERE / "cache" / "depth_ondemand.log"
TIMEOUT_MIN = int(CONFIG.get("depth_ticker_timeout_min", 150))

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


@contextmanager
def _qlock(timeout=30):
    """Tiny O_CREAT|O_EXCL mutex around every queue read-modify-write, so an enqueue racing
    the boundary drain cannot lose a request. Stale after `timeout`s (holders do file I/O
    measured in milliseconds)."""
    QLOCK.parent.mkdir(exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(QLOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - QLOCK.stat().st_mtime > timeout or time.time() > deadline:
                    QLOCK.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            QLOCK.unlink()
        except OSError:
            pass


def _read_queue():
    out = []
    if QUEUE.exists():
        for line in QUEUE.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _write_queue(reqs):
    QUEUE.parent.mkdir(exist_ok=True)
    QUEUE.write_text("".join(json.dumps(r) + "\n" for r in reqs), encoding="utf-8")


def pending():
    with _qlock():
        return _read_queue()


def take_next():
    """Pop the oldest request (claim-before-run). None when empty."""
    with _qlock():
        reqs = _read_queue()
        if not reqs:
            return None
        first, rest = reqs[0], reqs[1:]
        _write_queue(rest)
        return first


def precheck(t):
    """(ok, reason). Universe + price gate: without a financials/{T}.json Price the consensus
    envelope test (consensus_valuation.extract_iv) rejects every sample and the run is a
    guaranteed NOT_USABLE after ~2h of GPU — refuse up front instead. Quant-screen fails are
    IN the universe files and pass this check; that is the point of the feature."""
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", t):
        return False, f"{t!r} does not look like a ticker"
    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    price = fin.get("Price")
    try:
        ok = float(price) > 0
    except (TypeError, ValueError):
        ok = False
    if not ok:
        return False, (f"{t}: no price on file ({SD / 'financials'}/{t}.json) — not in the "
                       f"screener universe. A full run would burn ~2h of GPU and end "
                       f"NOT_USABLE (the consensus envelope needs a price). Refusing.")
    return True, ""


def _lock_alive():
    """PID from orchestrate_depth.lock if that process is alive, else None."""
    try:
        pid = int(json.loads(ORCH_LOCK.read_text()).get("pid", 0))
    except Exception:
        return None
    if not pid:
        return None
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                         capture_output=True, text=True).stdout
    return pid if str(pid) in out else None


def request(t, source):
    """Single entry point for CLI and the Telegram bot. Enqueues (with precheck + dedupe) and
    returns one human-readable line saying what will happen."""
    t = t.upper().strip()
    ok, why = precheck(t)
    if not ok:
        return f"REFUSED — {why}"
    with _qlock():
        reqs = _read_queue()
        dup = next((r for r in reqs if r.get("ticker") == t), None)
        if dup:
            return (f"{t} already queued (requested {dup.get('requested_at')}, "
                    f"{dup.get('source')}) — no duplicate added.")
        reqs.append({"ticker": t, "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "source": source})
        _write_queue(reqs)
    cur = (rs2_data.load_json(PROGRESS) or {}).get("current") or ""
    if str(cur).split(" ")[0] == t:
        return f"{t} is being analysed RIGHT NOW by the sweep — request queued anyway (fresh re-run after it)."
    if PAUSED.exists():
        return (f"{t} queued — but DEPTH_PAUSED is set, so nothing runs until "
                f"`python status.py resume`. The request survives the pause.")
    if _lock_alive():
        return (f"{t} queued — a sweep/runner is active; it jumps the remaining queue at the "
                f"next ticker boundary (<= ~{TIMEOUT_MIN} min away). Verdict arrives on Telegram.")
    _spawn_drain()
    return f"{t} queued — GPU idle, starting now (detached). Verdict arrives on Telegram."


def _spawn_drain():
    """Detached runner, run_depth_detached.start() pattern — NOT status.py's cmd-redirect
    (its nested quoting demonstrably loses the child's log, observed 2026-08-29)."""
    LOG.parent.mkdir(exist_ok=True)
    fh = LOG.open("a", encoding="utf-8", errors="replace")
    fh.write(f"\n{'='*70}\n[ondemand] detached drain start {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    fh.flush()
    subprocess.Popen(
        [sys.executable, str(HERE / "depth_ondemand.py"), "--run"],
        stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(HERE),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True)


def _log(msg):
    print(f"[ondemand {datetime.now():%H:%M:%S}] {msg}", flush=True)


def _run_one(t):
    """One depth_pipeline --ondemand child, watchdogged. Local ~copy of
    orchestrate_depth.run_one, NOT an import: orchestrate_depth rebinds sys.stdout at import
    (the double-wrap 'I/O operation on closed file' trap depth_sanity documents), and its
    log() would interleave into the sweep log status.py parses. Returns (ok, why)."""
    proc = subprocess.Popen([sys.executable, str(HERE / "depth_pipeline.py"), t, "--ondemand"])
    try:
        rc = proc.wait(timeout=TIMEOUT_MIN * 60)
    except subprocess.TimeoutExpired:
        _log(f"::WATCHDOG:: {t} exceeded {TIMEOUT_MIN} min — killing tree + unloading models")
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        except Exception:
            pass
        for m in (CONFIG.get("depth_model", "rs2-analyst-deep"), CONFIG.get("research_model")):
            ops.wait_unloaded(CONFIG["ollama_endpoint"], m, need_free_mb=0, timeout_s=120)
        return False, "watchdog_timeout"
    if rc == 0:
        return True, "ok"
    return False, {3: "research_infra", 5: "consensus_failed", 7: "vram"}.get(rc, f"exit_{rc}")


def drain():
    """Idle runner: hold the orchestrator lock, work the queue serially, release. If a real
    sweep holds the lock we exit — its boundary drain owns the queue."""
    pid = _lock_alive()
    if pid:
        _log(f"sweep/runner already active (pid {pid}) — its boundary drain handles the queue.")
        return 0
    if ORCH_LOCK.exists():
        _log("stale orchestrator lock — taking over.")
    ORCH_LOCK.write_text(json.dumps({"pid": os.getpid(), "ts": datetime.now().isoformat(),
                                     "ondemand": True}), encoding="utf-8")
    done = 0
    try:
        while True:
            if PAUSED.exists():
                _log("DEPTH_PAUSED set — stopping; queued requests wait for resume.")
                break
            req = take_next()
            if not req:
                break
            t = req["ticker"]
            _log(f"{t} (requested {req['requested_at']}, {req['source']}; "
                 f"{len(pending())} more queued)")
            ops.job_heartbeat("depth_ondemand", f"{t} running ({len(pending())} more queued)")
            ok, why = _run_one(t)
            if ok:
                done += 1
                # Publish the verdict to the site's dedicated on-demand section. Subprocess,
                # not import — orchestrate_depth rebinds sys.stdout at import (see _run_one).
                # Best-effort: the verdict is already ledgered + telegramed; a publish
                # failure alerts via publish_overlay's own telegram path.
                try:
                    subprocess.run([sys.executable, str(HERE / "orchestrate_depth.py"),
                                    "--publish-only"], timeout=900)
                except Exception as e:
                    _log(f"publish-only failed (non-fatal): {str(e)[:80]}")
            else:
                _log(f"{t} FAILED ({why}) — request consumed (one-shot); re-request to retry.")
                try:
                    ops.notify_telegram(f"[RS2 on-demand] {t} FAILED ({why}). "
                                        f"Re-send the request to retry.")
                except Exception:
                    pass
    finally:
        try:
            ORCH_LOCK.unlink()
        except OSError:
            pass
        ops.job_done("depth_ondemand")
    _log(f"drain done: {done} verdict(s).")
    return 0


def show_status():
    reqs = pending()
    print(f"pending on-demand requests: {len(reqs)}")
    for r in reqs:
        print(f"   {r.get('ticker'):8s} requested {r.get('requested_at')} via {r.get('source')}")
    pid = _lock_alive()
    print(f"orchestrator lock: {'pid ' + str(pid) if pid else 'free'}"
          + (" | DEPTH_PAUSED set" if PAUSED.exists() else ""))
    if OD_LEDGER.exists():
        lines = OD_LEDGER.read_text(encoding="utf-8").splitlines()[-5:]
        print(f"recent on-demand verdicts ({len(lines)} shown):")
        for line in lines:
            try:
                v = json.loads(line)
                print(f"   {v['ticker']:8s} {v.get('date', '')} {v.get('direction'):12s} "
                      f"band {v.get('iv_band_low')}-{v.get('iv_band_high')} vs {v.get('price')}")
            except Exception:
                continue


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = [a for a in sys.argv[1:] if a.strip()]
    if "--status" in args:
        show_status()
        return 0
    if "--run" in args:
        return drain()
    if not args:
        print(__doc__.split("\n\n")[-1].strip())
        return 2
    print(request(args[0], "cli"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
