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
import contextlib
import io
import json
import os
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
import depth_membership     # noqa: E402

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
# Cross-process mutex for the screener-repo publish. The local sweep here and a concurrent cloud
# publish (api_llm/publish_cloud_verdicts.py, which calls publish_overlay) both drive the SAME
# dedicated publish clone. Serialising the git critical section is half the 2026-08-26 race fix;
# the other half is publish_overlay's reset-to-origin + JSON-validate + rebase/abort (see it).
PUBLISH_LOCK = HERE / "cache" / "screener_publish.lock"
PROGRESS = HERE / "cache" / "depth_progress.json"   # this sweep's queue + position, for status.py
# Cloud verdict bundles are authored here by api_llm/publish_cloud_verdicts.py — their content lives
# only in the cloud run dirs, so build_report_bundles (which reads local ab_reports/consensus) cannot
# regenerate them. Staged OUTSIDE the publish clone so publish_overlay's `checkout -B main origin/main`
# reset cannot clobber them; publish_overlay copies them in and clears them only after a good push.
PENDING_REPORTS = HERE / "cache" / "cloud_pending_reports"

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


@contextlib.contextmanager
def _publish_lock(timeout=200):
    """Serialise the screener-repo git critical section across processes. O_EXCL lockfile; a lock
    older than `timeout` is stale (each git call caps at 120s, so a healthy publish finishes well
    inside it) and gets taken over. If it still cannot be acquired we proceed best-effort rather
    than wedge the pipeline — the merge/push retry below is safe on its own, the lock only removes
    the interleave that made two publishers race."""
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
        log("publish: screener lock not acquired in time — proceeding best-effort")
    try:
        yield
    finally:
        if got:
            try:
                PUBLISH_LOCK.unlink()
            except OSError:
                pass


def publish_overlay():
    """Copy the local overlay + report bundles into the DEDICATED screener-publish clone and push.

    Operator-approved 2026-08-21; hardened per SWEEP_AUTOMATION_FIX_20260826.md, dedicated-clone
    design chosen by the operator 2026-08-27. Target is CONFIG['screener_publish_repo'] — a clone of
    the screener repo used ONLY by the sweep, never the shared dev tree (publishing from the shared
    tree was the whole 2026-08-26 incident: a `stash`/`pop`/`rebase` dance over another process's
    uncommitted work committed conflict markers into depth_overlay.json AND rebased a later sweep
    over a real fix, dropping 131 conviction bundles).

    Invariants enforced here (the doc's acceptance criteria):
      1. Start from exactly what is published — reset the clone to origin/main each run. The clone is
         sweep-only, so there is never foreign uncommitted work to protect and no reason to stash.
      2. Validate every artifact parses as JSON BEFORE staging — a bad overlay/bundle never commits.
      3. Never commit conflict markers — `git diff --cached --check` gates the commit.
      4. Reconcile with fetch + rebase that PRESERVES every remote commit; on ANY conflict abort and
         alert. Never `-X ours`/`-X theirs`/force — those silently drop the other publisher's side.
      5. Every abort/failure is LOUD (ops.notify_telegram), never a silent no-op that leaves main broken.

    Two producers call this one function (this sweep and api_llm/publish_cloud_verdicts.py); the
    cross-process _publish_lock serialises the git critical section so only one runs git at a time,
    which is also why a rebase conflict is rare rather than a per-cycle event.
    """
    repo = Path(str(CONFIG.get("screener_publish_repo") or "")).expanduser()

    def abort(msg):
        log(f"publish ABORT: {msg}")
        try:
            ops.notify_telegram(f"[sweep] publish aborted: {msg}")
        except Exception:
            pass

    # The sweep must NEVER publish from the shared screener dev tree. Require a configured, valid,
    # sweep-only clone or refuse to publish — a missing clone is a loud abort, not a silent fallback.
    if not str(repo) or not (repo / ".git").exists():
        abort(f"screener_publish_repo is not a git clone: {repo!s}")
        return

    def g(*a):
        return subprocess.run(["git", "-C", str(repo)] + list(a),
                              capture_output=True, text=True, timeout=120)

    # Confirm the clone points at the screener origin — never push the sweep somewhere unexpected.
    origin = g("remote", "get-url", "origin").stdout.strip()
    if "stock-screener" not in origin:
        abort(f"publish clone origin is not stock-screener: {origin!r}")
        return

    pub_data = repo / "public" / "data"
    dst = pub_data / "depth_overlay.json"
    reports_dir = pub_data / "depth_reports"

    try:
        with _publish_lock():
            if g("fetch", "origin", "main").returncode != 0:
                abort("git fetch origin main failed")
                return

            # 1. Refuse to run on a tree dirtied by anything other than our own outputs. In a
            #    dedicated clone this is always clean; the guard catches a broken/co-opted clone.
            dirty = g("status", "--porcelain", "--",
                      ":!public/data/depth_overlay.json", ":!public/data/depth_reports").stdout.strip()
            if dirty:
                abort("publish clone has unexpected local changes — investigate, not stashing over")
                return

            # Start from exactly what is published. Discards any prior committed-but-unpushed sweep
            # commit; harmless because the artifacts below are regenerated fresh from the ledger.
            if g("checkout", "-B", "main", "origin/main").returncode != 0:
                abort("could not reset publish clone to origin/main")
                return

            # 2. Regenerate the artifacts into the clone (producer's existing step).
            reports_dir.mkdir(parents=True, exist_ok=True)
            dst.write_text(OVERLAY.read_text(encoding="utf-8"), encoding="utf-8")
            changed = build_report_bundles(reports_dir)
            if changed:
                log(f"report bundles updated: {', '.join(changed[:6])}"
                    + (f" (+{len(changed) - 6} more)" if len(changed) > 6 else ""))

            # Pull in any cloud bundles staged out-of-tree (see PENDING_REPORTS). Copied AFTER the
            # reset so they survive it; cleared only once the push that carries them succeeds.
            pending = sorted(PENDING_REPORTS.glob("*.json")) if PENDING_REPORTS.exists() else []
            for pf in pending:
                (reports_dir / pf.name).write_text(pf.read_text(encoding="utf-8"), encoding="utf-8")
            if pending:
                log(f"cloud bundles staged in: {len(pending)}")

            # 3. Validate BEFORE staging — a bad artifact never reaches a commit (AC#3).
            bad = []
            for f in [dst, *sorted(reports_dir.glob("*.json"))]:
                try:
                    json.loads(f.read_text(encoding="utf-8"))
                except Exception as e:
                    bad.append(f"{f.name}: {str(e)[:60]}")
            if bad:
                abort(f"invalid JSON in {len(bad)} file(s): {bad[0]}")
                return

            g("add", str(dst))
            g("add", str(reports_dir))

            # 4. Never commit conflict markers or corruption (AC#1/#3).
            if g("diff", "--cached", "--check").returncode != 0:
                abort("conflict markers / corruption in staged content — not committing")
                return
            if g("diff", "--cached", "--quiet").returncode == 0:
                log("publish: overlay unchanged — nothing to push")
                return

            c = g("-c", "commit.gpgsign=false", "commit", "-m",
                  "depth_overlay.json: sweep update (band_direction_v1)")
            if c.returncode != 0:
                abort(f"commit failed: {(c.stderr or c.stdout).strip()[:80]}")
                return

            # 5. Push with a race-safe retry that PRESERVES remote commits; abort on conflict (AC#2/#4).
            for attempt in (1, 2, 3, 4, 5):
                g("fetch", "origin", "main")
                if g("rebase", "origin/main").returncode != 0:
                    g("rebase", "--abort")
                    abort(f"rebase conflict against origin/main (attempt {attempt}) — main left unchanged")
                    return
                if g("push", "origin", "main").returncode == 0:
                    for pf in pending:      # committed + pushed — safe to drop the staged copies
                        try:
                            pf.unlink()
                        except OSError:
                            pass
                    log("publish: depth_overlay.json pushed to screener repo")
                    return
                log(f"publish: push attempt {attempt} rejected — re-syncing")
                time.sleep(4)
            abort("push failed after 5 attempts — main unchanged, next sweep will retry")
    except Exception as e:
        abort(f"unexpected error: {str(e)[:100]}")


def build_report_bundles(out_dir):
    """One JSON per ticker with the newest run's three sample REPORTS (the deliverable prose;
    thinking traces stay local - they are internal reasoning and ~80KB each). Written into `out_dir`
    (the screener-publish clone's public/data/depth_reports) as {T}.json for the site's depth panel."""
    out_dir = Path(out_dir)
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
    # Record today's RN+WL membership FIRST, so the boundary-dwell clocks (re-entry / exit-review /
    # retire — DEPTH_ORCHESTRATOR_CADENCE_20260825.md) advance one day on every sweep. Additive and
    # non-destructive; the dwell triggers stay dormant until enough daily rows accumulate.
    try:
        sd_date, sd_n = depth_membership.snapshot()
        log(f"membership snapshot {sd_date}: {sd_n} in RN+WL | "
            f"{depth_membership.snapshots_recorded()} daily rows on record")
    except Exception as e:
        log(f"membership snapshot failed (non-fatal): {str(e)[:120]}")
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
        # Priority (DEPTH_ORCHESTRATOR_CADENCE_20260825.md §5): events + exit-review first, then
        # baseline, then re-entry/promotion, then rotation. filing_pending is excluded by name.
        if any(k in ("8k", "filing", "move", "exit_review") for k in kinds):
            return 0                                        # event-triggered + exit-review
        if t not in verdicts:
            return 1                                        # baseline pass
        if "reentry" in kinds:
            return 2                                        # re-entry / promotion
        return 3                                            # rotation (staleness cap)

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

    # Sweep progress for status.py: the FULL due queue with per-name reasons, plus the position,
    # updated per ticker. status reads this to show what's pending instead of guessing from the log.
    def _why(t):
        return (", ".join(f"{k}:{d}" for k, d in trig.get(t, [])) or
                ("baseline" if t not in verdicts else "rotation"))
    queue_why = [{"t": t, "class": _class(t), "why": _why(t)[:120]} for t in queue]

    def write_progress(idx, current, active):
        try:
            PROGRESS.write_text(json.dumps({
                "active": active, "total": len(queue), "idx": idx, "current": current,
                "queue": queue_why, "updated": datetime.now().isoformat()}, indent=1),
                encoding="utf-8")
        except OSError:
            pass

    if dry or not queue:
        write_progress(0, None, False)
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
            write_progress(done + 1, t, True)
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
        write_progress(done, None, False)   # sweep ended (finished or paused) — mark inactive
    if done:
        publish_overlay()
    log(f"sweep done: {done} processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
