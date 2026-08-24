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
import depth_triggers       # noqa: E402

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
# rotation cadence lives in depth_triggers (depth_rotation_days, default 90);
# depth_refresh_days is retired - triggers decide re-runs now.


DEPTH_LOG = HERE / "cache" / "depth_orchestrate.log"


def log(msg):
    line = f"[depth-orch {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    # persistent tail for status.py's live-activity section; append-only, best-effort
    try:
        with DEPTH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


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
    """Universe = the quant screener's research_now + watchlist (factor_scores.json, refreshed
    weekly by the cloud) UNION every name already carrying a depth verdict (a demoted name keeps
    refreshing until the operator retires it). CORRECTED 2026-08-21: the first version read the
    FROZEN llm_overlay.json - the dead pipeline's last snapshot - so new research_now entrants
    would never have been analyzed."""
    fs = (rs2_data.load_json(SD / "factor_scores.json") or {}).get("tickers", {})
    book = {t.upper() for t, e in fs.items()
            if (e or {}).get("fct_band") in ("research_now", "watchlist")}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                book.add(json.loads(line)["ticker"])
            except Exception:
                continue
    return sorted(book)


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
        changed = build_report_bundles()
        if changed:
            log(f"report bundles updated: {', '.join(changed[:6])}")
        g("stash")
        g("pull", "--rebase", "origin", "main")
        g("stash", "pop")
        g("add", str(dst))
        g("add", str(SD / "depth_reports"))
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


def build_report_bundles():
    """One JSON per ticker with the newest run's three sample REPORTS (the deliverable prose;
    thinking traces stay local - they are internal reasoning and ~80KB each). Written into the
    screener repo at public/data/depth_reports/{T}.json for the site's depth panel."""
    out_dir = SD / "depth_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    newest = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                newest[v["ticker"]] = v
            except Exception:
                continue
    written = []
    for t, v in newest.items():
        cd = HERE / "ab_reports" / "consensus" / v.get("consensus_dir", "")
        cj = cd / "consensus.json"
        if not cj.exists():
            continue
        dst = out_dir / f"{t}.json"
        try:
            doc = json.loads(cj.read_text(encoding="utf-8"))
            samples = []
            for r in doc.get("runs", []):
                rep = ""
                sp = cd / f"sample{r['sample']}.md"
                if sp.exists():
                    rep = sp.read_text(encoding="utf-8", errors="replace")
                samples.append({"sample": r["sample"], "iv": r.get("iv"),
                                "plausible": r.get("plausible"),
                                "reasons": r.get("reasons") or [],
                                "truncated": r.get("truncated"),
                                "secs": r.get("secs"), "report": rep})
            bundle = {"ticker": t, "run": v.get("consensus_dir"), "verdict": v,
                      "samples": samples}
            txt = json.dumps(bundle)
            if not dst.exists() or dst.read_text(encoding="utf-8") != txt:
                dst.write_text(txt, encoding="utf-8")
                written.append(t)
        except Exception as e:
            log(f"report bundle {t} failed (non-fatal): {str(e)[:100]}")
    return written


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


def data_health_scan(book):
    """Report provable filed-series corruption in THIS book at sweep start. WARNS, never blocks.

    The dropped orchestrator gated on `data_health --gate-live`, which exits non-zero only when a
    corrupt value reaches a live `base_cf`. This pipeline computes no base_cf, so that gate would
    report CLEAR while corrupt cells went straight into the pack: measured 2026-08-24, it cleared
    all 12 known 1000x breaks, 3 of them inside this book, and INCY's published verdict was formed
    on a pack stating $19.094B of long-term debt for FY2018 against a true figure near $19M.

    So the scope is the book and the whole printed series, not one derived quantity. It warns
    rather than blocks because build_pack now prints an integrity alert on exactly these names -
    the model is told, and a handful of bad cells is not a reason to refuse to analyse 171
    companies. This exists so the operator sees the count without reading every pack.
    """
    try:
        import data_health
        hist = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers", {})
        breaks = data_health.audit_series_breaks(book, hist)
    except Exception as e:
        log(f"data-health scan did not run (non-fatal): {str(e)[:120]}")
        return
    if not breaks:
        log("data-health scan: no provable scale corruption in the book.")
        return
    names = sorted({b["ticker"] for b in breaks})
    log(f"data-health scan: {len(breaks)} provable 1000x scale break(s) in {len(names)} book "
        f"name(s) — {', '.join(names)}. Their packs carry an integrity alert; NOT blocking.")
    for b in breaks:
        log(f"   {b['ticker']} {b['field']}: FY{b['from_year']} {b['from']:,} -> "
            f"FY{b['to_year']} {b['to']:,}")


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
    data_health_scan(book)

    # TRIGGER-DRIVEN QUEUE (operator, 2026-08-21). Deterministic detection, model judgment:
    # depth_triggers checks 8-K / new 10-Q-10-K / big price move / 90d rotation against each
    # name's newest verdict. Priority contract: TRIGGERED names first, then names with no
    # verdict yet (the baseline pass), then rotation - and only when no triggered work remains
    # does rotation run, because triggers ARE in the map and sort ahead by construction.
    # Within each class: research_now -> watchlist -> rest, then alphabetical.
    trig = depth_triggers.trigger_map(book)
    verdicts = depth_triggers.newest_verdicts()

    def due(t):
        rec = st.get(t) or {}
        if rec and not rec.get("ok"):
            return rec.get("retries", 0) < MAX_RETRIES      # failed: retry budget decides
        kinds = [k for k, _ in trig.get(t, []) if k != "filing_pending"]
        if t not in verdicts:
            return True                                     # baseline: never analysed
        return bool(kinds)                                  # verdict exists: only ACTIONABLE triggers

    def _class(t):
        kinds = [k for k, _ in trig.get(t, [])]
        if any(k in ("8k", "filing", "move") for k in kinds):    # filing_pending excluded by name
            return 0                                        # event-triggered
        if t not in verdicts:
            return 1                                        # baseline pass
        return 2                                            # rotation (staleness cap)

    queue = [t for t in book if due(t)]
    fs = (rs2_data.load_json(SD / "factor_scores.json") or {}).get("tickers", {})
    rank = {"research_now": 0, "watchlist": 1}
    queue.sort(key=lambda t: (_class(t), rank.get((fs.get(t) or {}).get("fct_band"), 2), t))
    for t in queue[:20]:
        why = ", ".join(f"{k}:{d}" for k, d in trig.get(t, [])) or               ("baseline" if t not in verdicts else "rotation")
        log(f"   queued {t}: {why[:110]}")
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
            # publish per completion (2026-08-21): at ~2h/ticker a sweep runs for days, and
            # sweep-end-only publishing left fresh verdicts invisible on the site the whole
            # time. One small commit per ticker is the lesser cost.
            if ok:
                publish_overlay()
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
