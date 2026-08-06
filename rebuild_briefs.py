#!/usr/bin/env python3
"""rebuild_briefs.py — deliberately rebuild research briefs that have ZERO source citations.

WHY THIS EXISTS
129 of 257 briefs on disk were written while SearXNG was silently returning zero results for
every query (all default engines CAPTCHA'd or rate-limited). They are fluent, confident, and
entirely model recall — the POWL bundle asserted a plant fire and a $500M lawsuit for a
net-cash company. deep_research.build() already refuses to serve them from cache, so they are
inert, but each one triggers a fresh research pass the next time its ticker runs. Doing that
lazily spreads ~128 rebuilds across a normal sweep, at whatever concurrency the orchestrator
happens to apply — and burst concurrency is exactly what CAPTCHA-blocks the engines. Rebuilding
here instead is serial, throttled, and watched.

SANITY CHECKS (the point of doing it this way)
Before every ticker it probes the live search engine and refuses to continue into a degraded
one, so a mid-run CAPTCHA block cannot quietly refill the disk with fresh garbage:
  * zero results            -> the failure mode that caused this mess; back off and retry
  * a SERVING engine blocked -> bing/yep going CAPTCHA or rate-limited is the real warning
    (duckduckgo is already blocked and is tolerated; it is not in the serving set)
Backoff is exponential and the run aborts rather than grinding if the engine does not recover.

RESUMABLE. Re-run it freely: anything already carrying citations is skipped, so an interrupted
run costs nothing. Progress is appended to reports/_rebuild_briefs.log.

Usage:
    python rebuild_briefs.py              # rebuild all uncited briefs
    python rebuild_briefs.py --limit 10   # first 10 only (a cautious first pass)
    python rebuild_briefs.py --dry-run    # list what would be rebuilt, touch nothing
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import subprocess

import rs2_data

CONFIG = rs2_data.CONFIG
HERE = Path(__file__).resolve().parent
RESEARCH_DIR = Path(CONFIG["out_research_dir"])
LOG = Path(CONFIG["out_reports_dir"]) / "_rebuild_briefs.log"

# Engines this instance actually relies on. duckduckgo is deliberately NOT here: it is already
# CAPTCHA-blocked and serves nothing, so alerting on it would fire every single probe.
SERVING_ENGINES = ("bing", "yep")
MIN_HEALTHY_RESULTS = 5        # a real query returns ~30; single digits means something is wrong
THROTTLE_SEC = 8               # between tickers — keeps concurrency low enough not to trip blocks
MAX_CONSECUTIVE_UNHEALTHY = 3  # give up rather than hammer a blocked engine

PROBES = ["realty income dividend 2026", "micron memory pricing outlook",
          "apple iphone demand 2026", "bunge farm products outlook"]


def _hm(seconds):
    """Compact duration: 4.6min / 1h12m / 3d4h."""
    s = max(0, int(seconds))
    if s < 3600:
        return f"{s/60:.1f}min"
    if s < 86400:
        return f"{s//3600}h{(s % 3600)//60:02d}m"
    return f"{s//86400}d{(s % 86400)//3600:02d}h"


def progress(done, total, started, ok, failed, width=30):
    """One-line bar with elapsed / ETA, sized from the measured average so far."""
    frac = done / total if total else 0
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    elapsed = time.time() - started
    avg = elapsed / done if done else 0
    eta = avg * (total - done)
    return (f"[{bar}] {done}/{total} {frac*100:3.0f}%  "
            f"elapsed {_hm(elapsed)}  ETA {_hm(eta)}  avg {_hm(avg)}/brief  "
            f"ok {ok} fail {failed}")


def show_status():
    """Read the log and report where a running (or finished) rebuild stands. Safe to call at
    any time from another shell — it only reads."""
    if not LOG.exists():
        print("no rebuild log yet — nothing has been run")
        return
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    last_bar = next((l for l in reversed(lines) if "] " in l and "/" in l and "ETA" in l), None)
    last_evt = next((l for l in reversed(lines) if re.search(r"\[\d+/\d+\]", l)), None)
    done = next((l for l in reversed(lines) if l.strip().endswith("remaining on disk")), None)
    print(f"uncited briefs on disk right now: {len(uncited_tickers())}")
    if last_evt:
        print(f"last ticker event : {last_evt}")
    if last_bar:
        print(f"last progress     : {last_bar}")
    if done:
        print(f"FINISHED          : {done}")
    elif last_evt:
        print("status            : RUNNING (or interrupted — re-run to resume)")


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def citations(text):
    return len(re.findall(r"^- https?://", text, re.M))


def uncited_tickers():
    out = []
    for f in sorted(RESEARCH_DIR.glob("*.md")):
        try:
            if citations(f.read_text(encoding="utf-8", errors="replace")) == 0:
                out.append(f.stem)
        except Exception:
            continue
    return out


def engine_health(probe):
    """(n_results, [blocked serving engines], note). Never raises."""
    url = (CONFIG["searxng_url"].rstrip("/") + "/search?"
           + urllib.parse.urlencode({"q": probe, "format": "json"}))
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return 0, list(SERVING_ENGINES), f"probe failed: {str(e)[:60]}"
    unresp = {name: msg for name, msg in (d.get("unresponsive_engines") or [])}
    blocked = [e for e in SERVING_ENGINES if e in unresp]
    note = "; ".join(f"{e}:{unresp[e][:28]}" for e in blocked) if blocked else ""
    return len(d.get("results") or []), blocked, note


def wait_for_healthy(probe_idx):
    """Probe, backing off exponentially. False => give up."""
    for attempt in range(MAX_CONSECUTIVE_UNHEALTHY):
        n, blocked, note = engine_health(PROBES[probe_idx % len(PROBES)])
        if n >= MIN_HEALTHY_RESULTS and not blocked:
            return True
        why = (f"only {n} results" if n < MIN_HEALTHY_RESULTS else "") + \
              (f" | SERVING ENGINE BLOCKED {note}" if blocked else "")
        wait = 60 * (2 ** attempt)
        log(f"  [health] DEGRADED ({why.strip()}) — backing off {wait}s "
            f"(attempt {attempt + 1}/{MAX_CONSECUTIVE_UNHEALTHY})")
        time.sleep(wait)
        probe_idx += 1
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="print progress of a running/finished rebuild and exit (read-only)")
    args = ap.parse_args()

    if args.status:
        show_status()
        return

    todo = uncited_tickers()
    if args.limit:
        todo = todo[:args.limit]
    log(f"rebuild_briefs: {len(todo)} uncited brief(s) to rebuild")
    if args.dry_run:
        print(", ".join(todo))
        return

    rv_py = Path(CONFIG["research_venv_python"])
    if not rv_py.exists():
        log(f"ABORT: research venv python not found at {rv_py} — LDR lives there, not in this "
            f"interpreter, and without it every topic fails with ModuleNotFoundError")
        sys.exit(2)

    n, blocked, note = engine_health(PROBES[0])
    log(f"start health: {n} results, blocked serving engines: {blocked or 'none'} {note}")
    if n < MIN_HEALTHY_RESULTS or blocked:
        log("ABORT: search engine is not healthy at start — fix it before rebuilding, or the "
            "rebuild just writes fresh garbage")
        sys.exit(2)

    ok = failed = 0
    started = time.time()
    log(f"ETA at a nominal 4.5min/brief: ~{_hm(len(todo) * 270)} — the bar below re-estimates "
        f"from the measured average as it goes")
    for i, t in enumerate(todo, 1):
        if not wait_for_healthy(i):
            log(f"ABORT after {i - 1} ticker(s): engine did not recover. Remaining briefs are "
                f"untouched; re-run this script when search is healthy again.")
            break
        name = None
        try:
            fin = rs2_data.load_json(Path(CONFIG["screener_data_dir"]) / "financials" / f"{t}.json") or {}
            name = (fin.get("Name") or "").strip() or None
        except Exception:
            pass
        log(f"[{i}/{len(todo)}] {t} — rebuilding")
        try:
            # Spawn deep_research.py under research-venv, exactly as run_rs2.run_research does.
            # LDR (local_deep_research) is installed ONLY in that venv, so importing
            # deep_research in this interpreter fails every topic with ModuleNotFoundError --
            # which is how the first version of this script "rebuilt" three briefs into
            # nothing. Explicit utf-8/replace for the same reason run_rs2 does it: text=True
            # alone decodes the child's utf-8 through cp1252 on Windows.
            cmd = [str(rv_py), str(HERE / "deep_research.py"), t] + ([name] if name else [])
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            for line in (r.stdout or "").splitlines():
                if "[deep_research]" in line:
                    log("    " + line.strip())
            p = RESEARCH_DIR / f"{t}.md"
            c = citations(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else 0
            if r.returncode == 0 and c:
                ok += 1
                log(f"[{i}/{len(todo)}] {t} OK — {c} citations")
            else:
                failed += 1
                log(f"[{i}/{len(todo)}] {t} STILL UNCITED (exit {r.returncode}, {c} citations) "
                    f"— left for a later run")
        except Exception as e:
            failed += 1
            log(f"[{i}/{len(todo)}] {t} FAILED — {type(e).__name__}: {str(e)[:120]}")
        log(progress(i, len(todo), started, ok, failed))
        time.sleep(THROTTLE_SEC)

    log(f"done: {ok} rebuilt, {failed} still failing, "
        f"{len(uncited_tickers())} uncited brief(s) remaining on disk")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
