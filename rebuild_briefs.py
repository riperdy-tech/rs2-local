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
Before every ticker it probes the live search engine, so a mid-run block cannot quietly refill
the disk with fresh garbage. What counts as unhealthy is RESULTS, not unanimity:
  * too few results             -> the failure mode that caused this mess; back off and retry
  * ALL serving engines blocked -> nothing left to research with; back off and retry
  * ONE serving engine blocked  -> warn and continue; losing yep while bing still returns 10+
    results is survivable, and treating it as fatal stopped the first run at 15/126 for a rate
    limit that had expired by the time anyone looked
Backoff is 1/2/4/8/16/32 min (~1h) because these are expiring RATE LIMITS, not bans. If it does
give up it says so on Telegram — a silent abort is indistinguishable from a hung job, which is
exactly how the first run looked for three hours.

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

import ops
import rs2_data
import run_rs2

CONFIG = rs2_data.CONFIG
HERE = Path(__file__).resolve().parent
RESEARCH_DIR = Path(CONFIG["out_research_dir"])
LOG = Path(CONFIG["out_reports_dir"]) / "_rebuild_briefs.log"

# Engines this instance relies on — read from config so this and deep_research.preflight cannot
# drift apart. yep/duckduckgo are deliberately excluded there: both are chronically blocked and
# recover on their own, so listing them would warn on nearly every probe until it was ignored.
SERVING_ENGINES = tuple(CONFIG.get("searxng_serving_engines", ["bing", "yep"]))
MIN_HEALTHY_RESULTS = int(CONFIG.get("searxng_min_probe_results", 10))
THROTTLE_SEC = 8               # between tickers — keeps concurrency low enough not to trip blocks
# Engine blocks here are RATE LIMITS, which expire; they are not permanent bans. The first run
# aborted after 3 tries / ~7 minutes when yep returned "Suspended: access denied" -- and yep was
# serving again well before anyone looked. Be patient enough to ride out a throttle: 6 attempts
# backing off 1/2/4/8/16/32 min ~= an hour before giving up.
MAX_CONSECUTIVE_UNHEALTHY = 6
BACKOFF_BASE_SEC = 60
# A hung LDR call would otherwise block forever: subprocess.run has no default timeout. A brief
# takes ~5 min, so 20 is generous while still bounded.
TICKER_TIMEOUT_SEC = 20 * 60
# Outcome guard: if most briefs are FAILING the run is pointless no matter how healthy the
# engine probe looks. 10 tickers is enough signal to act on without tripping over a bad patch.
FAILURE_CHECK_AFTER = 10
FAILURE_RATE_ABORT = 0.5

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

    def last_idx(pred):
        for i in range(len(lines) - 1, -1, -1):
            if pred(lines[i]):
                return i
        return -1

    bar_i = last_idx(lambda l: "ETA" in l and "/" in l)
    evt_i = last_idx(lambda l: re.search(r"\[\d+/\d+\]", l))
    done_i = last_idx(lambda l: l.strip().endswith("remaining on disk"))

    print(f"uncited briefs on disk right now: {len(uncited_tickers())}")
    if evt_i >= 0:
        print(f"last ticker event : {lines[evt_i]}")
    if bar_i >= 0:
        print(f"last progress     : {lines[bar_i]}")
    # The log is APPEND-ONLY across runs, so an old completion line sits above the current run's
    # events. Compare positions, not mere presence, or a fresh job reports itself FINISHED using
    # the previous run's summary.
    if done_i > evt_i:
        print(f"FINISHED          : {lines[done_i]}")
    elif evt_i >= 0:
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
    """Briefs that must be rebuilt: UNCITED, or researched from a BARE TICKER.

    Two distinct defects, both invisible to the citation guard in different ways:

    * uncited      -> fluent model recall with no sources. The guard rejects these on read, so
                      they are inert, but they never self-heal until re-researched.
    * ticker-only  -> the header reads "BRIEF — (EW)" with no company name, meaning the query
                      was literally "EW competitive position, market share, moat durability".
                      EW matched Entertainment Weekly and DOCU matched dictionary definitions of
                      "document". These are FULLY CITED, so the guard passes them and the
                      wrong-company research flows straight into the valuation. Strictly more
                      dangerous than the uncited kind.

    A ticker-only brief only counts if a name is resolvable NOW — otherwise a genuinely
    nameless ticker would be queued for rebuild on every single run, forever.
    """
    out = []
    for f in sorted(RESEARCH_DIR.glob("*.md")):
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if citations(txt) == 0:
            out.append(f.stem)
            continue
        m = re.match(r"# DEEP RESEARCH BRIEF — (.*)\(", txt.split("\n", 1)[0])
        if m and not m.group(1).strip():
            try:
                if run_rs2.resolve_name(f.stem):
                    out.append(f.stem)
            except Exception:
                pass
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
    """Probe, backing off exponentially. False => give up.

    Healthy means ENOUGH RESULTS, not every engine happy. The first run aborted at 15/126 because
    yep was rate-limited, while bing was still returning 10+ results and research could have
    continued perfectly well — losing one of two serving engines is survivable, losing the
    results is not. Only a genuine result shortfall (or every serving engine down) stops the run;
    a single blocked engine is logged as a warning and pressed through.
    """
    for attempt in range(MAX_CONSECUTIVE_UNHEALTHY):
        n, blocked, note = engine_health(PROBES[probe_idx % len(PROBES)])
        all_down = len(blocked) >= len(SERVING_ENGINES)
        if n >= MIN_HEALTHY_RESULTS and not all_down:
            if blocked:
                log(f"  [health] WARNING: {note} — but {n} results still coming, continuing")
            return True
        why = (f"only {n} results" if n < MIN_HEALTHY_RESULTS else "") + \
              (f" | ALL SERVING ENGINES BLOCKED {note}" if all_down else "")
        wait = BACKOFF_BASE_SEC * (2 ** attempt)
        log(f"  [health] DEGRADED ({why.strip()}) — backing off {wait}s "
            f"(attempt {attempt + 1}/{MAX_CONSECUTIVE_UNHEALTHY})")
        time.sleep(wait)
        probe_idx += 1
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tickers", default=None,
                    help="comma-separated tickers to rebuild REGARDLESS of citation count — for "
                         "briefs that are cited but wrong (e.g. built while only one engine was "
                         "serving, where EW pulled Entertainment Weekly and DOCU pulled "
                         "dictionary definitions). The citation guard cannot catch those.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="print progress of a running/finished rebuild and exit (read-only)")
    args = ap.parse_args()

    if args.status:
        show_status()
        return

    if args.tickers:
        todo = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        # Explicit list: delete the existing brief so deep_research cannot serve it from cache.
        # These are CITED (the guard passes them), so nothing else would force a refresh.
        for t in todo:
            f = RESEARCH_DIR / f"{t}.md"
            if f.exists():
                f.unlink()
        log(f"forced rebuild of {len(todo)} ticker(s); stale briefs deleted")
    else:
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
    if n < MIN_HEALTHY_RESULTS or len(blocked) >= len(SERVING_ENGINES):
        log("ABORT: search engine is not healthy at start — fix it before rebuilding, or the "
            "rebuild just writes fresh garbage")
        sys.exit(2)

    ok = failed = 0
    started = time.time()
    log(f"ETA at a nominal 4.5min/brief: ~{_hm(len(todo) * 270)} — the bar below re-estimates "
        f"from the measured average as it goes")
    for i, t in enumerate(todo, 1):
        if not wait_for_healthy(i):
            msg = (f"rebuild_briefs ABORTED after {i - 1}/{len(todo)} ticker(s): search engine "
                   f"did not recover. {len(uncited_tickers())} uncited briefs remain. Re-run "
                   f"`python rebuild_briefs.py` when search is healthy — it resumes.")
            log("ABORT — " + msg)
            # A silent abort is how a 10-hour job "hangs": the first run stopped at 15/126 and
            # simply went quiet, and it read as a stuck process for hours. Say so out loud.
            try:
                ops.notify_telegram("[RS2 ops] " + msg)
                log("  (Telegram alert sent)")
            except Exception as e:
                log(f"  (Telegram alert failed: {str(e)[:80]})")
            break
        # Resolve via run_rs2, which falls back to yfinance when financials/{T}.json has no Name
        # -- and only 33% of them do. Doing the lookup inline here (as this script used to) sent
        # a BARE TICKER as the research subject, so the query was literally "EW competitive
        # position, market share, moat durability" with nothing to disambiguate it. That is how
        # EW cited Entertainment Weekly and DOCU cited dictionary definitions of "document".
        name = None
        try:
            name = run_rs2.resolve_name(t) or None
        except Exception as e:
            log(f"  [name] resolve failed for {t}: {str(e)[:60]}")
        if not name:
            log(f"  [name] WARNING: no company name for {t} — query will be ticker-only "
                f"and is liable to match the wrong entity")
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
                               encoding="utf-8", errors="replace",
                               timeout=TICKER_TIMEOUT_SEC)
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
        except subprocess.TimeoutExpired:
            failed += 1
            log(f"[{i}/{len(todo)}] {t} TIMED OUT after {TICKER_TIMEOUT_SEC//60}min — skipping")
        except Exception as e:
            failed += 1
            log(f"[{i}/{len(todo)}] {t} FAILED — {type(e).__name__}: {str(e)[:120]}")
        log(progress(i, len(todo), started, ok, failed))

        # OUTCOME sanity check, distinct from the engine probe above. The engine can look
        # perfectly healthy while every brief still fails — that is exactly what a preflight bug
        # did: 44 consecutive tickers exited 3 in ~9s each, and because failing is FAST the ETA
        # collapsed from 9h27m to 39min and the bar raced to 44%, which reads as progress. A
        # human spotted it; nothing in this script did. Stop early instead.
        if i >= FAILURE_CHECK_AFTER and failed > ok and failed / i >= FAILURE_RATE_ABORT:
            msg = (f"rebuild_briefs ABORTED at {i}/{len(todo)}: {failed} failures vs {ok} "
                   f"successes ({100*failed/i:.0f}% failing). The engine probe is passing, so "
                   f"this is NOT a search outage — check deep_research/ollama before resuming.")
            log("ABORT — " + msg)
            try:
                ops.notify_telegram("[RS2 ops] " + msg)
                log("  (Telegram alert sent)")
            except Exception as e:
                log(f"  (Telegram alert failed: {str(e)[:80]})")
            break
        time.sleep(THROTTLE_SEC)

    log(f"done: {ok} rebuilt, {failed} still failing, "
        f"{len(uncited_tickers())} uncited brief(s) remaining on disk")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
