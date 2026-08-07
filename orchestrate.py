#!/usr/bin/env python3
"""orchestrate.py — drive the local RS2 engine across the screener's Research-Now + Watchlist
names, keep them current, and feed verdicts back to the website as public/data/llm_overlay.json.

Loop (designed to run unattended via Windows Task Scheduler, daily + at-logon):
  1. lockfile + keep-awake + Ollama health-check (exit cleanly if prereqs are down).
  2. git pull the screener repo (fresh factor_scores.json) — stale-tolerant.
  3. Build a PRIORITY QUEUE from factor_scores.json x analysis_state.json:
        new RN -> due RN (>refresh_rn_days) -> new WL -> due WL (>refresh_wl_days).
     Names that left RN/WL -> status:inactive (kept, not re-run).
  4. Run each via run_rs2.py <T>, updating analysis_state.json after each (resumable).
  5. Aggregate every ACTIVE verdict.json -> public/data/llm_overlay.json.
  6. git add/commit/push ONLY llm_overlay.json (Vercel auto-redeploys).

The overlay is a strict no-op for the cloud pipeline when absent/empty, so this never breaks the
screener before verdicts exist. Flags: --dry-run --rn-only --no-pull --no-push --limit N
--refresh-rn-days --refresh-wl-days.
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

import ops               # shared telegram + verified VRAM unload barrier (stdlib-only)
import publish_reports

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
SD = Path(CONFIG["screener_data_dir"])
REPO = SD.parent.parent                      # .../Stock Screener/Stock Screener
FACTOR = SD / "factor_scores.json"
OVERLAY = SD / "llm_overlay.json"
STATE = HERE / "cache" / "analysis_state.json"
PROGRESS = HERE / "cache" / "orchestrate_progress.json"
REPORTS = Path(CONFIG["out_reports_dir"])
LOCK = HERE / "cache" / "orchestrate.lock"
PAUSE = HERE / "cache" / "PAUSED"        # `status.py pause` sets it; blocks new + in-flight runs
PY = sys.executable
RN_BAND, WL_BAND = "research_now", "watchlist"
MAX_FACTOR_AGE_H = 48        # refuse to run if the cloud factor_scores.json is older than this
MAX_RETRIES = 3             # re-run a FAILED ticker up to this many times before giving up (#1)
LOCK_MAX_AGE_H = 24         # a lock older than this (or whose PID is dead) is stale -> take over
HEARTBEAT = HERE / "cache" / "heartbeat.json"      # last-run status for monitoring (#7)
FIN_DIR = SD / "financials"                        # per-ticker financials (Next_Earnings_Date) (#3)


def log(m):
    print(f"[orch {datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def load(path, default=None):
    # utf-8-sig: reads plain utf-8 AND tolerates a BOM (the editor/PowerShell trap that once
    # silently emptied the whole state — BOM incident, 2026-07)
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save(path, obj):
    # atomic: write a sibling tmp then os.replace, so a crash/kill mid-write can never leave a
    # truncated file for load() to silently turn into "empty state" (torn-write door of the wipe)
    p = Path(path)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def ollama_up():
    try:
        ep = CONFIG["ollama_endpoint"].replace("/api/chat", "/api/version")
        urllib.request.urlopen(ep, timeout=8).read()
        return True
    except Exception:
        return False


def _pid_alive(pid):
    """True if a process with this PID exists. Windows via OpenProcess; falls back to 'assume alive'
    (safe — never steal a lock we can't prove is dead)."""
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFO
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    except Exception:
        return True


def lock_stale_reason():
    """Reason string if the lockfile is stale (PID dead, PID-less + old, or older than LOCK_MAX_AGE_H),
    else None — so a CRASHED run can't wedge every future run on a dead lock (the 2026-07-07 incident)."""
    try:
        txt = LOCK.read_text(encoding="utf-8").strip()
        parts = txt.split()
        pid = int(parts[0]) if parts and parts[0].isdigit() else None
        age_h = (datetime.now() - datetime.fromtimestamp(LOCK.stat().st_mtime)).total_seconds() / 3600
    except Exception:
        return "unreadable lock"
    if age_h > LOCK_MAX_AGE_H:
        return f"age {age_h:.0f}h > {LOCK_MAX_AGE_H}h"
    if pid is None:
        return f"legacy lock (no pid), age {age_h:.1f}h"   # old timestamp-only format -> treat stale
    if not _pid_alive(pid):
        return f"pid {pid} dead"
    return None


BAD_HEARTBEATS = {"ollama_down", "stale_factor_scores", "push_failed", "ticker_timeout"}


def notify_telegram(text):
    """Best-effort ops alert via the same Telegram bot as the KIS trade digests.
    Single implementation lives in ops.py so run_rs2 and deep_research (separate venv)
    alert through the identical path; silent no-op without creds — must never break a run."""
    ops.notify_telegram(text)


def heartbeat(status, **extra):
    """Write cache/heartbeat.json every terminal path so silent failsafes (ollama-down, stale-guard,
    push-fail) are inspectable — a monitor/status.py can flag 'no success in >24h'. (#7)
    Bad statuses additionally alert via Telegram (notify_telegram; no-op without creds)."""
    try:
        save(HEARTBEAT, {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "status": status, **extra})
    except Exception:
        pass
    if status in BAD_HEARTBEATS:
        notify_telegram(f"[RS2 ops] {status} — {extra or ''}".strip())


def next_earnings(t):
    """Next_Earnings_Date (ISO str) for a ticker, or None. Used to force a re-run + research refresh
    after a company reports, so a verdict isn't frozen on pre-earnings data for a whole cycle. (#3)"""
    return (load(FIN_DIR / f"{t.upper()}.json", {}) or {}).get("Next_Earnings_Date")


def earnings_reported(s):
    """True if this name reported earnings RECENTLY (0-10 days ago) AND our last analysis predates the
    report -> a fresh post-earnings re-run is due. One-shot: once last_analyzed >= the earnings date it
    stops firing; the 0-10d window ignores months-stale Next_Earnings_Date data (which would otherwise
    re-trigger every run forever, e.g. ELMD 2026-05-12). Takes a state entry dict."""
    ne, la = (s or {}).get("next_earnings"), (s or {}).get("last_analyzed")
    if not ne or not la:
        return False
    try:
        ed = date.fromisoformat(str(ne)[:10])
        lad = date.fromisoformat(str(la)[:10])
    except Exception:
        return False
    return 0 <= (date.today() - ed).days <= 10 and lad < ed


BIG_MOVE_PCT = 12.0     # price move since last analysis that forces an immediate re-review


def _price_now(t):
    ph = load(SD / "price_history.json", {}) or {}
    arr = (ph.get("prices") or {}).get(t.upper())
    return arr[-1] if isinstance(arr, list) and arr and isinstance(arr[-1], (int, float)) else None


def big_move(t, s):
    """True if price moved >= BIG_MOVE_PCT% since the last analysis (state's last_price,
    stored at verdict time). An anchored call must never sit through a real event waiting
    for its weekly slot; a move this size is 'material change' by the anchor's own rule."""
    if (s or {}).get("last_analyzed") == date.today().isoformat():
        return False    # analyzed today already — price_history is daily, a same-day re-fire can only loop
    p0 = (s or {}).get("last_price")
    p1 = _price_now(t)
    try:
        return bool(p0 and p1 and abs(p1 / p0 - 1) * 100 >= BIG_MOVE_PCT)
    except Exception:
        return False


def hard_vetoed(t):
    """True if the quant engine hard-vetoed the name (fct_veto set: forensic pair / heavy issuance /
    reverse reject) — a red-flagged name should be retired straight, not given a wasted RS2
    exit-review run. NOT the same as fct_percentile None: that also covers insufficient_factors
    (a data gap, ~200 names), which still deserves the exit review. (#9)"""
    e = ((load(FACTOR, {}) or {}).get("tickers", {}) or {}).get(t.upper())
    return bool(e) and e.get("fct_veto") is not None


def factor_age_hours():
    """Age in hours of FACTOR's content timestamp (generated_at), or None if missing/unparseable.
    Content freshness (not file mtime) — git checkout would reset mtime even on stale content."""
    ts = (load(FACTOR, {}) or {}).get("generated_at")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def days_since(iso):
    if not iso:
        return 1e9
    try:
        return (datetime.now() - datetime.strptime(iso[:10], "%Y-%m-%d")).days
    except Exception:
        return 1e9


def bands():
    """{ticker: band} for research_now / watchlist from factor_scores.json."""
    fs = (load(FACTOR, {}) or {}).get("tickers", {})
    out = {}
    for t, e in fs.items():
        b = e.get("fct_band")
        if b in (RN_BAND, WL_BAND):
            out[t.upper()] = b
    return out


def llm_research_set():
    """Tickers RS2 itself bands research_now (fct_band_llm). Used ONLY to accelerate re-review cadence
    for quant-WL names RS2 rates highly — NEVER to select the universe (that stays quant RN∪WL)."""
    fs = (load(FACTOR, {}) or {}).get("tickers", {})
    return {t.upper() for t, e in fs.items() if e.get("fct_band_llm") == RN_BAND}


def build_queue(cur, state, args, llm_rn=frozenset()):
    """Priority: new RN -> shift-into-RN -> due RN -> WL-that-RS2-ranks-RN(7d) -> new WL -> shift WL ->
    due WL(14d). Two accelerators over the plain quant cadence:
      * a quant band CHANGE (WL<->RN) or RE-ADD (name back after retirement) re-runs REGARDLESS of age
        (a signal event);
      * a name RS2 ITSELF bands research_now (fct_band_llm) is refreshed on the RN 7-day cadence even
        while quant only bands it WL — so RS2's own top picks never go stale-demoted (score_factors
        decays verdicts >14d, the max WL cadence) before a refresh. `llm_rn` drives cadence/priority
        ONLY, never the universe (still quant RN∪WL). Returns (queue, drops)."""
    today = date.today().isoformat()

    def due(t, days):
        return days_since((state.get(t) or {}).get("last_analyzed")) >= days

    def shifted(t):
        # quant band differs from what we last analyzed under, OR the name is back after retirement
        s = state.get(t)
        return bool(s) and (s.get("band") != cur.get(t) or s.get("status") == "inactive")

    def retrying(t):        # #1 failed last run, retries not exhausted -> re-run next run
        s = state.get(t)
        return bool(s) and not s.get("ok", True) and s.get("retries", 0) < MAX_RETRIES

    def force(t):           # re-run REGARDLESS of the age cadence (signal / broken / earnings / move)
        return (shifted(t) or retrying(t) or earnings_reported(state.get(t))
                or big_move(t, state.get(t)))

    rn = [t for t, b in cur.items() if b == RN_BAND]
    wl = [t for t, b in cur.items() if b == WL_BAND]
    new_rn = [t for t in rn if t not in state]
    force_rn = [t for t in rn if t in state and force(t)]                        # shift / retry / earnings
    due_rn = [t for t in rn if t in state and not force(t) and due(t, args.refresh_rn_days)]
    if args.rn_only:
        wl_fast = new_wl = force_wl = due_wl = []
    else:
        # quant-WL but RS2-RN -> RN (7-day) cadence + RN-tier priority
        wl_fast = [t for t in wl if t in llm_rn and t in state and not force(t) and due(t, args.refresh_rn_days)]
        new_wl = [t for t in wl if t not in state]
        force_wl = [t for t in wl if t in state and force(t)]                    # shift / retry / earnings
        due_wl = [t for t in wl if t not in llm_rn and t in state and not force(t) and due(t, args.refresh_wl_days)]
    q, seen = [], set()
    for group in (new_rn, force_rn, due_rn, wl_fast, new_wl, force_wl, due_wl):
        for t in group:
            if t not in seen:
                q.append(t); seen.add(t)
    drops = [t for t in state if t not in cur and state[t].get("status") == "active"]
    return q, drops


def latest_verdict(t):
    ds = sorted(REPORTS.glob(f"{t}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for d in ds:
        v = load(d / "verdict.json")
        if v:
            return v, d.name
    return None, None


def aggregate_overlay(state):
    """Every ACTIVE name's latest verdict.json -> llm_overlay.json. EXIT-REVIEWED names (left the
    quant list, holder may still own them) are included for EXIT_KEEP_DAYS with an exit_review flag
    so a SELL/TRIM call on a held name reaches the cockpit instead of dying in the report browser;
    conviction decay + the window age them out."""
    EXIT_KEEP_DAYS = 30
    tickers = {}
    for t, s in state.items():
        is_exit = bool(s.get("exit_reviewed")) and s.get("status") == "inactive"
        if s.get("status") != "active" and not (
                is_exit and days_since(s.get("last_analyzed")) <= EXIT_KEEP_DAYS):
            continue
        v, rep = latest_verdict(t)
        if not v:
            continue
        tickers[t] = {
            **({"exit_review": True} if is_exit else {}),
            "method": v.get("method"), "stance": v.get("stance"),
            "stance_score": v.get("stance_score"), "thesis_break": v.get("thesis_break"),
            "changed_because": v.get("changed_because"),
            "action": v.get("action"), "conviction": v.get("conviction"),
            "expectations_gap_pts": v.get("expectations_gap_pts"),
            "mos_pct": v.get("mos_pct"), "fair_value": v.get("fair_value"),
            "realistic_mos_pct": v.get("realistic_mos_pct"),
            "fair_value_method": v.get("fair_value_method"),
            "consensus_median": v.get("consensus_median"),
            "entry_timing": v.get("entry_timing"), "pullback_trigger": v.get("pullback_trigger"),
            "brake_applied": v.get("brake_applied"),
            "recommended_weight_pct": v.get("recommended_weight_pct"),
            "band_at_analysis": v.get("band_at_analysis"),
            "analyzed_date": v.get("date"), "report": rep,
        }
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(tickers), "tickers": tickers}


def git(args_list, tolerate=True):
    # explicit utf-8 (errors=replace): text=True alone decodes via the ANSI codepage (cp1252) on
    # Windows, mojibaking git's utf-8 output and able to raise UnicodeDecodeError on stray bytes
    r = subprocess.run(["git", "-C", str(REPO)] + args_list, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 and not tolerate:
        raise RuntimeError(r.stderr.strip())
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _unload_models():
    """Free VRAM NOW: force-unload both RS2 models (keep_alive 0). Called after a watchdog kill or when
    sweeping a dead predecessor, so a crashed/hung run never leaves the ~23GB engine pinned on the 24GB
    card (Ollama holds a model warm ~5 min by default — or indefinitely if a hung child keeps poking it).

    Uses the same verified barrier as run_rs2 (ops.wait_unloaded): it blocks until /api/ps
    and the driver both agree the VRAM is back, so the next ticker cannot start its load into
    a card that is still being torn down."""
    for m in (CONFIG.get("model"), CONFIG.get("research_model")):
        if not m:
            continue
        ok, detail = ops.wait_unloaded(
            CONFIG["ollama_endpoint"], m,
            need_free_mb=int(CONFIG.get("vram_free_required_mb", 20000)),
            timeout_s=int(CONFIG.get("vram_unload_timeout_s", 180)))
        log(f"   [vram] {m}: {'freed' if ok else 'NOT FREED'} — {detail}")


PARTIAL_GRACE_MIN = 90     # never touch a dir this new — the in-flight run has no verdict.json yet


def sweep_partial_reports(grace_min=PARTIAL_GRACE_MIN, dry_run=False):
    """Delete report dirs that hold no verdict.json — the debris a failed/killed run leaves behind.

    A run writes its stage files as it goes and verdict.json only at the very end, so a crash
    (final-assembly OOM, watchdog kill, status.py stop) leaves a dir that nothing will ever read:
    latest_verdict() skips it and publish_reports can't bundle it. They just accumulate — 228 of
    them, back to 2026-06-25, before this existed.

    TWO guards, because this deletes: (1) a dir newer than grace_min is NEVER touched — the
    currently-running ticker has no verdict.json yet and must not be swept out from under itself;
    (2) a dir referenced by analysis_state is never touched, even if unreadable."""
    try:
        state = load(STATE, {}) or {}
    except Exception:
        return 0, 0      # can't confirm what's referenced -> delete nothing
    referenced = {e.get("report") for e in state.values() if isinstance(e, dict)}
    cutoff = time.time() - grace_min * 60
    removed = freed = 0
    for d in REPORTS.iterdir():
        if not d.is_dir() or not re.match(r"^[A-Z][A-Z0-9.\-]*_\d{8}_\d{6}$", d.name):
            continue
        if (d / "verdict.json").exists() or d.name in referenced:
            continue
        try:
            if d.stat().st_mtime > cutoff:      # too new — may be the live run
                continue
            sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            if not dry_run:
                shutil.rmtree(d)
            removed += 1; freed += sz
        except Exception:
            continue
    return removed, freed


def _kill_tree(pid):
    """Kill a process AND all its descendants. run_rs2 spawns a research-venv deep_research grandchild;
    Popen.kill would reap only the direct child and orphan the rest. taskkill /T walks the whole tree."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
    except Exception:
        pass


def _sweep_orphans():
    """A CONFIRMED-DEAD predecessor (lock PID gone) can leave a half-dead run_rs2/deep_research child
    holding the GPU, or a keepawake pinning the box awake. Kill those orphans + unload the models before
    we start. Deliberately does NOT match orchestrate.py, so it can't touch a live sibling — and we only
    call it when the lock's PID is proven dead, never on a mere age-based takeover."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
          "'run_rs2\\.py|deep_research\\.py|keepawake\\.py' } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=30, capture_output=True)
    except Exception:
        pass
    _unload_models()
    log("swept dead predecessor's orphans + unloaded models (GPU freed).")


def run_one(t, exit_review=False, timeout_sec=0):
    """Full RS2 pipeline for one ticker (deep research + stages + verdict.json). exit_review frames
    the run as a holder's exit review (HOLD/TRIM/SELL in SECTION 12) and tags the verdict.
    Normal re-analyses run ANCHORED (continuity: maintain the prior call absent a named material
    change — audit 2026-07-21); exit reviews stay unanchored (a fresh HOLD/TRIM/SELL judgment is
    the whole point).

    WATCHDOG: if the child runs longer than timeout_sec it is killed TREE-AND-ALL and both models are
    unloaded, then we return False so the name is marked failed and retried next pass. This is the
    fail-safe against a hung run_rs2 (network stall in deep-research, a wedged Ollama read, or a
    fatal-error zombie) wedging the queue forever with the heavy engine pinned in VRAM. timeout_sec<=0
    disables the watchdog (unlimited — legacy behaviour)."""
    # UNANCHORED BASELINE. The continuity anchor injects the PREVIOUS verdict (action, conviction,
    # stance, weight, fair value, MoS) with "your DEFAULT is to MAINTAIN that call". That is right
    # for routine refreshes — it was added to stop borderline names re-rolling every review — but
    # it is exactly wrong when the previous call is known-invalid. Every verdict before 2026-08-07
    # was produced on fabricated research, a consensus-anchored MoS and the homogenizing prompt, so
    # anchoring a rebuild to it would RE-DERIVE the old book rather than replace it.
    # ORCH_UNANCHORED=1 (--unanchored) drops the anchor so each name is judged fresh. Turn it back
    # OFF once the baseline exists, so continuity resumes from the NEW calls.
    _unanchored = os.environ.get("ORCH_UNANCHORED") == "1"
    cmd = [PY, str(HERE / "run_rs2.py"), t] \
        + (["--exit-review"] if exit_review else ([] if _unanchored else ["--anchor"]))
    proc = subprocess.Popen(cmd, cwd=str(HERE))
    try:
        rc = proc.wait(timeout=timeout_sec if timeout_sec > 0 else None)
        if rc != 0:
            # 3 = deep_research refused to write an infra-poisoned brief; 6 = post-analysis
            # sanity check found an empty/error report. Both already alerted via Telegram at
            # the source; name them here so the log says why, not just "FAILED".
            why = {3: "research infra failure (brief not written)",
                   6: "post-analysis sanity check failed (empty/error report)",
                   7: "research model VRAM not released (refused to load analyst on top)"}.get(
                       rc, f"exit {rc}")
            log(f"   {t}: {why}")
        return rc == 0
    except subprocess.TimeoutExpired:
        mins = timeout_sec // 60
        log(f"::WATCHDOG:: {t} exceeded {mins} min with no exit — killing the run tree + unloading "
            "models (VRAM freed). Marking failed; it retries next pass.")
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=20)     # reap the now-killed tree so we don't leave a zombie
        except Exception:
            pass
        _unload_models()
        heartbeat("ticker_timeout", ticker=t, timeout_min=mins)   # alerts via Telegram (BAD_HEARTBEATS)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the queue, run nothing")
    ap.add_argument("--unanchored", action="store_true",
                    help="drop the continuity anchor for this sweep — judge every name fresh "
                         "instead of defaulting to its previous call. Use to establish a BASELINE "
                         "after a scoring change; leave OFF for routine refreshes, where the "
                         "anchor is what stops borderline names re-rolling every review.")
    ap.add_argument("--rn-only", action="store_true", help="Research-Now only (skip Watchlist)")
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--allow-stale", action="store_true",
                    help="skip the factor_scores freshness guard (offline / manual runs)")
    ap.add_argument("--limit", type=int, default=0, help="cap how many to run this pass (0 = all)")
    ap.add_argument("--max-hours", type=float, default=0,
                    help="soft runtime budget: stop cleanly after N hours (0 = unlimited, resumable)")
    ap.add_argument("--ticker-timeout-min", type=float, default=0,
                    help="watchdog: kill one run_rs2 child + unload the models if it runs longer than N "
                         "min, then mark it failed and retry (0 = use config.json ticker_timeout_min, "
                         "default 40). Stops a hung run from wedging the queue with the engine pinned.")
    ap.add_argument("--refresh-rn-days", type=int, default=7)
    ap.add_argument("--refresh-wl-days", type=int, default=14)
    ap.add_argument("--pull-every-min", type=int, default=120,
                    help="mid-run: re-pull screener bands this often so a NEW research_now name "
                         "preempts the Watchlist grind at the next ticker boundary (default 120)")
    ap.add_argument("--review-rn-drops", action=argparse.BooleanOptionalAction, default=True,
                    help="give a one-shot EXIT review to names that fell OUT of research_now "
                         "(you may hold them), then retire them; WL drops skip straight to inactive")
    args = ap.parse_args()

    if args.unanchored:
        os.environ["ORCH_UNANCHORED"] = "1"
        log("UNANCHORED sweep — the continuity anchor is OFF; every name is judged fresh. "
            "This is a BASELINE pass, not a routine refresh.")

    (HERE / "cache").mkdir(exist_ok=True)

    # watchdog budget for a single run_rs2 child (CLI > config > 40 min). <=0 disables it.
    _tt = args.ticker_timeout_min or CONFIG.get("ticker_timeout_min", 40)
    ticker_timeout_sec = int(_tt * 60) if _tt and _tt > 0 else 0

    # dry-run is a read-only preview of the priority order — no lock/keepawake/Ollama needed,
    # so you can inspect "what would preempt the WL grind" even while a run holds the lock.
    if args.dry_run:
        cur = bands()
        state = load(STATE, {}) or {}
        queue, drops = build_queue(cur, state, args, llm_research_set())
        log(f"RN={sum(1 for b in cur.values() if b==RN_BAND)} WL={sum(1 for b in cur.values() if b==WL_BAND)} "
            f"| queue={len(queue)} | drops={len(drops)}"
            + ("   [NOTE: another run holds the lock]" if LOCK.exists() else ""))
        exit_rev = [t for t in drops if args.review_rn_drops
                    and (state.get(t) or {}).get("band") == RN_BAND]
        retire = [t for t in drops if t not in exit_rev]
        log("DRY RUN — priority order:")
        n = 0
        for t in exit_rev:
            n += 1
            print(f"   {n:3}. {t:6} {'(was RN)':12} EXIT-REVIEW then retire")
        for t in queue:
            n += 1
            tag = "NEW" if t not in state else f"due({days_since(state[t].get('last_analyzed'))}d)"
            print(f"   {n:3}. {t:6} {cur[t]:12} {tag}")
        if retire:
            print("   retire -> inactive (no review):", " ".join(retire))
        return 0

    if PAUSE.exists():
        log("PAUSED (cache/PAUSED present) — run `python status.py resume` to continue. Exit."); return 0
    if LOCK.exists():
        stale = lock_stale_reason()
        if not stale:
            log(f"lock present ({LOCK}); another orchestrator is running — exit."); return 3
        log(f"stale lock ({stale}) — previous run died; taking over.")
        if "dead" in stale:          # PID proven dead -> safe to sweep its GPU-pinning leftovers
            _sweep_orphans()
    LOCK.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")   # pid + ts
    ka = subprocess.Popen([PY, str(HERE / "keepawake.py")])
    try:
        # Ollama auto-starts on login (Startup folder); the at-logon task can beat it by a few seconds
        # (post-reboot race -> the 2026-07-08 ollama_down failures). Wait up to ~3 min before giving up.
        if not ollama_up():
            log("Ollama not up yet — waiting up to 3 min (it auto-starts on login)...")
            for _ in range(12):
                time.sleep(15)
                if ollama_up():
                    break
            else:
                log("Ollama still DOWN after 3 min — exit.")
                heartbeat("ollama_down"); return 2
            log("Ollama came up — continuing.")
        if not args.no_pull:
            ok, msg = git(["pull", "--ff-only"])
            log(f"git pull: {'ok' if ok else 'skipped'} ({msg.splitlines()[-1] if msg else ''})")

        # FRESHNESS GUARD: bands come from the cloud-generated factor_scores.json. A tolerated pull
        # failure (dirty/diverged local screener clone) would otherwise leave us silently analyzing a
        # STALE RN/WL set. Abort if generated_at is older than MAX_FACTOR_AGE_H (or missing), unless
        # --allow-stale (intentional offline/manual runs).
        age_h = factor_age_hours()
        if not args.allow_stale and (age_h is None or age_h > MAX_FACTOR_AGE_H):
            log(f"STALE factor_scores.json (age {'unknown' if age_h is None else f'{age_h:.0f}h'} > "
                f"{MAX_FACTOR_AGE_H}h) — git pull likely failed; refusing to analyze a stale RN/WL set. "
                "Fix the screener-repo sync, or pass --allow-stale. Exit.")
            heartbeat("stale_factor_scores", age_h=round(age_h, 1) if age_h is not None else None); return 4
        if age_h is not None:
            log(f"factor_scores fresh ({age_h:.0f}h old).")

        cur = bands()
        # STATE is irreplaceable history: corrupt must ABORT, never silently become {} — an empty
        # state re-classifies the whole RN∪WL universe as NEW (multi-day re-run) and erases
        # retry/exit/baseline tracking. Missing file = legitimate fresh start; unparseable ≠ missing.
        if STATE.exists():
            try:
                state = json.loads(STATE.read_text(encoding="utf-8-sig")) or {}
            except Exception as e:
                log(f"::ERROR:: analysis_state.json exists but won't parse ({str(e)[:80]}) — refusing "
                    "to run with empty state. Restore it from backup, or delete it DELIBERATELY.")
                heartbeat("corrupt_state"); return 5
        else:
            state = {}
        queue, drops = build_queue(cur, state, args, llm_research_set())
        log(f"RN={sum(1 for b in cur.values() if b==RN_BAND)} WL={sum(1 for b in cur.values() if b==WL_BAND)} "
            f"| queue={len(queue)} | drops={len(drops)}")

        # Recalibrate the cross-sectional MoS percentiles ONCE per sweep, before any ticker runs.
        # ENTRY DISCIPLINE (the prompt) and _dont_chase_brake both rank a name's margin of safety
        # against the BOOK rather than an absolute bar, because the absolute cut fired on 80% of
        # names and produced the verdict homogenization. That ranking needs a current distribution:
        # when the cache goes stale the prompt says "no ranking available" and the brake skips MoS
        # tiering entirely — safe, but the differentiation silently stops contributing. Refreshing
        # here is what keeps it alive. Non-fatal: a failed calibration must not block the sweep.
        try:
            import valuation_backbone as _vb
            _uni = sorted({d.name.rsplit("_", 2)[0] for d in REPORTS.glob("*_*") if d.is_dir()})
            _md = _vb.build_mos_distribution(_uni)
            if _md:
                _p = _md["percentiles"]
                log(f"[mos] calibrated on {_md['n']} names — p33 {_p['33']}% p50 {_p['50']}% "
                    f"p75 {_p['75']}%")
            else:
                log("[mos] ::WARN:: too few valued names to calibrate — ENTRY DISCIPLINE and the "
                    "brake will fall back to 'no ranking available' this sweep")
        except Exception as e:
            log(f"[mos] ::WARN:: calibration failed ({str(e)[:100]}) — percentile ranking will be "
                f"skipped this sweep")

        done = failed = 0
        run_start = time.time()
        last_pull = time.time()          # we pulled just above (unless --no-pull)
        reviewed_drops = set()           # RN names already given a one-shot exit review this run
        # ROLLING QUEUE: re-derive priority before EVERY ticker. A new research_now entrant (or a
        # promoted WL name) that appears mid-run jumps ahead of the Watchlist grind at the next
        # ticker boundary (~15-20 min), then WL resumes automatically — same queue, remaining WL
        # names are still due. One GPU / 12GB RAM => cooperative, one model at a time (can't parallelize).
        while True:
            if PAUSE.exists():
                log(f"PAUSED after {done} — stopping cleanly (resumable). `status.py resume` to continue.")
                break
            if args.limit and done >= args.limit:
                log(f"--limit {args.limit} reached — stopping."); break
            if args.max_hours and (time.time() - run_start) >= args.max_hours * 3600:
                log(f"--max-hours {args.max_hours} budget reached — stopping cleanly (resumable)."); break
            # periodically pull the cloud's fresh bands so new RN entrants are actually SEEN mid-run
            if not args.no_pull and (time.time() - last_pull) >= args.pull_every_min * 60:
                ok, msg = git(["pull", "--ff-only"])
                log(f"mid-run pull: {'ok' if ok else 'skipped'} ({msg.splitlines()[-1] if msg else ''})")
                last_pull = time.time()

            cur = bands()
            queue, drops = build_queue(cur, state, args, llm_research_set())
            # RN names that fell OUT of the list -> one final EXIT review (you may hold them), then
            # retire. WL drops (bench) -> straight to inactive, no review.
            pending_exit = [t for t in drops if args.review_rn_drops
                            and state[t].get("band") == RN_BAND and t not in reviewed_drops
                            and not hard_vetoed(t)   # #9 red-flagged -> retire straight, skip wasted run
                            # a FAILED review may retry (same rolling-retry budget as normal runs);
                            # once retries exhaust it falls through to plain retirement below
                            and (state[t].get("ok", True) or state[t].get("retries", 0) < MAX_RETRIES)]
            for t in drops:
                if t not in pending_exit and t in state:
                    state[t]["status"] = "inactive"
            todo = pending_exit + queue   # exit-reviews first (time-sensitive: held name left RN)
            if not todo:
                break
            t = todo[0]
            is_exit = t in pending_exit
            band = state[t].get("band", "?") if is_exit else cur.get(t, "?")
            if is_exit:
                tag = "EXIT-REVIEW (left research_now)"
            elif t not in state:
                tag = "NEW"
            elif state[t].get("band") != cur.get(t):
                tag = f"SHIFT {state[t].get('band')}->{cur.get(t)}"
            elif state[t].get("status") == "inactive":
                tag = "RE-ADD (back in bands)"
            elif not state[t].get("ok", True):
                tag = f"RETRY (prev failed {state[t].get('retries', 0)}/{MAX_RETRIES})"
            elif earnings_reported(state.get(t)):
                tag = f"EARNINGS ({state[t].get('next_earnings')} passed)"
            elif big_move(t, state.get(t)):
                tag = f"BIGMOVE (>{BIG_MOVE_PCT:.0f}% since last analysis)"
            else:
                tag = f"due {days_since(state[t].get('last_analyzed'))}d"
            remaining = len(todo)
            log(f"[done {done} | {remaining} queued] run {t} ({band}) — {tag}")
            # live progress snapshot (status.py reads this) — written BEFORE the run starts
            elapsed = time.time() - run_start
            per = (elapsed / done) if done else 0
            save(PROGRESS, {
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current": t, "current_band": band, "current_started": datetime.now().strftime("%H:%M:%S"),
                "reason": tag,   # NEW/SHIFT/RE-ADD/RETRY/EARNINGS/due Xd/EXIT-REVIEW — which run category
                "idx": done + 1, "queue_total": done + remaining, "done_this_run": done, "failed_this_run": failed,
                "avg_sec_per_ticker": round(per) if per else None,
                "eta_finish": (datetime.fromtimestamp(time.time() + per * remaining).strftime("%Y-%m-%d %H:%M")
                               if per else None),
                "exit_review": is_exit,
            })
            # #3 company reported since last analysis -> bust the 7-day research cache so the re-run
            # reads POST-earnings news, not stale pre-earnings research.
            prev = state.get(t, {})
            ne_prev = prev.get("next_earnings")
            if not is_exit and earnings_reported(prev):
                rc = HERE / "research" / f"{t.upper()}.md"
                try:
                    if rc.exists():
                        rc.unlink(); log(f"   {t}: earnings {ne_prev} passed — busted research cache")
                except Exception:
                    pass
            ok = run_one(t, exit_review=is_exit, timeout_sec=ticker_timeout_sec)
            v, rep = latest_verdict(t)
            succeeded = ok and bool(v)
            # a FAILED exit review must NOT be stamped reviewed/inactive: the holder would get the
            # stale pre-drop verdict republished as a "completed" exit review and no retry would
            # ever fire. Keep it active + unreviewed so the retry path above picks it up.
            state[t] = {"last_analyzed": datetime.now().strftime("%Y-%m-%d"),
                        "band": band, "status": "inactive" if (is_exit and succeeded) else "active",
                        "report": rep, "ok": succeeded,
                        "retries": 0 if succeeded else prev.get("retries", 0) + 1,   # #1 retry tracking
                        "next_earnings": next_earnings(t),                            # #3 refresh stored date
                        # big-move baseline: MUST come from the same series big_move() compares against
                        # (price_history), not the verdict's financials-file price — a stale financials
                        # Price re-stamped every run kept the >12% gap alive forever (MU 2026-07-22).
                        "last_price": _price_now(t) or (v or {}).get("price"),
                        **({"exit_reviewed": True} if (is_exit and succeeded) else {})}
            save(STATE, state)          # resumable: persist after every ticker
            # RECOVERY alert: a failure alerts, so a fix must alert too — otherwise the last thing
            # you ever hear about a name is that it broke, and you have to go digging to learn it
            # came good. Only fires when this run followed at least one failed attempt.
            if succeeded and prev.get("retries", 0) > 0:
                nfail = prev.get("retries", 0)
                notify_telegram(f"[RS2 ops] recovered — {t} succeeded on attempt {nfail + 1} "
                                f"after {nfail} failed attempt(s). Verdict written ({rep}); "
                                f"no action needed.")
                log(f"   {t}: RECOVERED on attempt {nfail + 1} (after {nfail} failure(s))")
            if is_exit and succeeded:
                reviewed_drops.add(t)
            done += 1
            if not (ok and v):
                failed += 1
                log(f"   {t} FAILED (continuing)")
            time.sleep(15)
        save(PROGRESS, {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "current": None,
                        "idx": done, "queue_total": done, "done_this_run": done,
                        "failed_this_run": failed, "finished": True})

        # clear the debris failed/killed runs leave behind (dirs with no verdict.json) before
        # publishing, so it can't accumulate run after run
        swept, freed = sweep_partial_reports()
        if swept:
            log(f"swept {swept} partial report dir(s) with no verdict.json ({freed/1024/1024:.1f} MB)")

        overlay = aggregate_overlay(state)
        save(OVERLAY, overlay)
        log(f"overlay written: {overlay['count']} tickers -> {OVERLAY}")

        # publish the research + full outcomes for the website (index + bounded full-text bundles)
        try:
            pub = publish_reports.publish(verbose=False)
            log(f"rs2 reports published: {pub['count']} tickers -> {SD / 'rs2'}")
        except Exception as e:
            log(f"rs2 publish FAILED (non-fatal): {e}")

        push_status = "skipped"
        if not args.no_push:
            git(["add", str(OVERLAY), str(SD / "rs2")])
            committed, cmsg = git(["commit", "-m", f"chore(llm): RS2 overlay + reports {overlay['generated_at']} ({overlay['count']} names)"])
            if committed:
                push_status = "failed"
                for attempt in (1, 2, 3):     # #2 VERIFY the push; reconcile a diverged origin, don't fail silently
                    git(["fetch", "origin", "main"])
                    mok, _ = git(["merge", "-X", "ours", "--no-edit", "origin/main"])
                    if not mok:
                        git(["merge", "--abort"])
                    pok, msg = git(["push"])
                    if pok:
                        push_status = "ok"
                        log(f"git push: ok ({msg.splitlines()[-1] if msg else ''})"); break
                    log(f"git push attempt {attempt} FAILED — re-syncing...")
                    time.sleep(5)
                if push_status != "ok":
                    log("::ERROR:: git push FAILED after 3 attempts — SITE OVERLAY IS STALE. Fix the screener-repo sync.")
            elif "nothing to commit" in (cmsg or "").lower() or "nothing added to commit" in (cmsg or "").lower():
                push_status = "nothing"
                log("git commit: nothing to commit (overlay + reports unchanged)")
            else:
                # commit FAILURE (index.lock, unset identity, hook) is not "nothing to commit" —
                # conflating them shipped a stale site overlay under a green heartbeat
                push_status = "commit_failed"
                log(f"::ERROR:: git commit FAILED — SITE OVERLAY IS STALE: "
                    f"{(cmsg or 'unknown').splitlines()[-1]}")
        else:
            log("--no-push: overlay + reports written locally, NOT pushed (review, then push manually)")
        log(f"done: ran {done}, drops {len(drops)}")
        heartbeat("ok" if push_status in ("ok", "nothing", "skipped") else "push_failed",
                  ran=done, failed=failed, drops=len(drops), overlay_count=overlay["count"], push=push_status)
        return 0
    finally:
        if ka:
            ka.terminate()
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
