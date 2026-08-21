#!/usr/bin/env python3
"""orchestrate_depth.py — sweep the live book through the depth-tier pipeline.

Successor to orchestrate.py for the REPLACEMENT pipeline (production dropped by operator order,
2026-08-21). One depth_pipeline.py child at a time; the old overlay is never touched — verdicts
accumulate in cache/depth_ledger.jsonl and the newest-per-ticker view is rebuilt after every
completion into cache/depth_overlay.json (LOCAL ONLY: nothing here pushes anywhere; the site
switches over only on explicit operator action after the shadow run is inspected).

Safety carried over from the old orchestrator, because the incidents that earned them are
model-agnostic: the PAUSED file (one red button for both pipelines), a pid lock, a per-ticker
wall-clock watchdog with TREE kill + model unload, MAX_RETRIES, atomic state writes.

  python orchestrate_depth.py --dry-run
  python orchestrate_depth.py --tickers GOOG,PM --limit 2      # shadow-style bounded run
  python orchestrate_depth.py --limit 20                        # the 20-name shadow
"""
import io
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import ops                  # noqa: E402
import rs2_data             # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
STATE = HERE / "cache" / "depth_state.json"
LOCK = HERE / "cache" / "orchestrate_depth.lock"
# DECOUPLED 2026-08-21: the old pipeline is DROPPED and cache/PAUSED must stay in place
# FOREVER to hold its still-enabled 08:00 scheduled task down. Depth therefore gets its own
# red button — create cache/DEPTH_PAUSED to stop this orchestrator at the next boundary.
PAUSED = HERE / "cache" / "DEPTH_PAUSED"
LEDGER = HERE / "cache" / "depth_ledger.jsonl"
OVERLAY = HERE / "cache" / "depth_overlay.json"

MAX_RETRIES = 2
# Per-ticker budget. Measured: research <=900s (bounded) + 3 tool-enabled samples. Non-tools
# samples ran 23-31 min; tools samples run longer (search round-trips). 150 min = research cap
# + 3 x ~40 min + audit slack. A healthy non-tools ticker finishes in ~80; revisit with real
# tools timings from the shadow run.
TIMEOUT_MIN = int(CONFIG.get("depth_ticker_timeout_min", 150))
REFRESH_DAYS = float(CONFIG.get("depth_refresh_days", 7))


def log(msg):
    print(f"[depth-orch {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def live_book():
    ov = rs2_data.load_json(SD / "llm_overlay.json") or {}
    return sorted((ov.get("tickers") or {}).keys())


def rebuild_overlay():
    """Newest verdict per ticker from the append-only ledger -> cache/depth_overlay.json.
    LOCAL artifact. The site is switched to it by the operator, never by this script."""
    newest = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                newest[v["ticker"]] = v
            except Exception:
                continue
    OVERLAY.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(), "scheme": "band_direction_v1",
         "count": len(newest), "tickers": newest}, indent=1), encoding="utf-8")
    return len(newest)


def publish_overlay():
    """Copy the local overlay into the screener repo and push. Operator-approved 2026-08-21
    ("verdict emission and new overlay - approved and push to github"). The stash dance is the
    standing procedure for that repo: the cloud pushes daily feeds, so always stash -> rebase ->
    push -> pop. No site component reads this file yet; hosting it is not a display change."""
    dst = SD / "depth_overlay.json"
    try:
        dst.write_text(OVERLAY.read_text(encoding="utf-8"), encoding="utf-8")
        repo = SD.parent.parent
        def g(*a):
            return subprocess.run(["git", "-C", str(repo)] + list(a),
                                  capture_output=True, text=True, timeout=120)
        g("stash")
        g("pull", "--rebase", "origin", "main")
        g("stash", "pop")
        g("add", str(dst))
        c = g("-c", "commit.gpgsign=false", "commit", "-m",
              "depth_overlay.json: sweep update (band_direction_v1)")
        if "nothing to commit" in (c.stdout + c.stderr):
            log("publish: overlay unchanged — nothing to push")
            return
        r = g("push", "origin", "main")
        if r.returncode == 0:
            log("publish: depth_overlay.json pushed to screener repo")
        else:
            log(f"publish ::PUSH FAILED:: {(r.stderr or '')[:150]} — overlay committed locally, "
                f"push manually")
    except Exception as e:
        log(f"publish failed (non-fatal): {str(e)[:120]}")


def _kill_tree(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def run_one(t):
    """One depth_pipeline child, watchdogged. Returns (ok, why)."""
    proc = subprocess.Popen([sys.executable, str(HERE / "depth_pipeline.py"), t])
    try:
        rc = proc.wait(timeout=TIMEOUT_MIN * 60)
    except subprocess.TimeoutExpired:
        log(f"::WATCHDOG:: {t} exceeded {TIMEOUT_MIN} min — killing tree + unloading models")
        _kill_tree(proc.pid)
        for m in (CONFIG.get("depth_model", "rs2-analyst-deep"), CONFIG.get("research_model")):
            ops.wait_unloaded(CONFIG["ollama_endpoint"], m,
                              need_free_mb=0, timeout_s=120)
        return False, "watchdog_timeout"
    if rc == 0:
        return True, "ok"
    return False, {3: "research_infra", 5: "consensus_failed", 7: "vram"}.get(rc, f"exit_{rc}")


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    only = (args[args.index("--tickers") + 1].upper().split(",")
            if "--tickers" in args else None)

    if PAUSED.exists() and not dry:
        log(f"PAUSED file present ({PAUSED}) — exiting. Remove it to run.")
        return 0
    if LOCK.exists() and not dry:
        try:
            pid = int(json.loads(LOCK.read_text()).get("pid", 0))
            alive = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                   capture_output=True, text=True).stdout
            if str(pid) in alive:
                log(f"live lock (pid {pid}) — refusing to double-start.")
                return 1
        except Exception:
            pass
        log("stale lock — taking over.")
    st = load_state()
    book = only or live_book()
    now = time.time()

    def due(t):
        rec = st.get(t) or {}
        if not rec.get("ok"):
            return rec.get("retries", 0) < MAX_RETRIES if rec else True
        return (now - rec.get("finished_at", 0)) > REFRESH_DAYS * 86400

    queue = [t for t in book if due(t)]
    # PRIORITY (operator, 2026-08-21): research_now first, then watchlist, then the rest —
    # bands from factor_scores.json fct_band, same source the old orchestrator used.
    fs = (rs2_data.load_json(SD / "factor_scores.json") or {}).get("tickers", {})
    rank = {"research_now": 0, "watchlist": 1}
    queue.sort(key=lambda t: (rank.get((fs.get(t) or {}).get("fct_band"), 2), t))
    if limit:
        queue = queue[:limit]
    log(f"book {len(book)} | due {len(queue)}"
        + (f" | first: {', '.join(queue[:8])}{'...' if len(queue) > 8 else ''}" if queue else ""))
    if dry or not queue:
        return 0

    LOCK.write_text(json.dumps({"pid": subprocess.os.getpid(),
                                "ts": datetime.now().isoformat()}), encoding="utf-8")
    try:
        done = 0
        for t in queue:
            if PAUSED.exists():
                log("PAUSED appeared — stopping cleanly at the ticker boundary.")
                break
            log(f"[{done+1}/{len(queue)}] {t}")
            ok, why = run_one(t)
            rec = st.get(t) or {}
            if ok:
                st[t] = {"ok": True, "finished_at": time.time(),
                         "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
            else:
                st[t] = {"ok": False, "why": why,
                         "retries": rec.get("retries", 0) + 1,
                         "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
                log(f"   {t} FAILED ({why}) — retries {st[t]['retries']}/{MAX_RETRIES}")
                if st[t]["retries"] >= MAX_RETRIES:
                    try:
                        ops.notify_telegram(f"[RS2 depth] {t} failed {MAX_RETRIES}x ({why}) — "
                                            f"giving up this sweep.")
                    except Exception:
                        pass
            save_state(st)
            n = rebuild_overlay()
            log(f"   overlay: {n} verdicts (local cache/depth_overlay.json)")
            done += 1
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass
    if done:
        publish_overlay()
    log(f"sweep done: {done} processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
