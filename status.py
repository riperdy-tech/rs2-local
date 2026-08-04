#!/usr/bin/env python3
"""status.py — orchestrator progress dashboard. Run anytime (even days into a backfill):

    python status.py            # one-shot snapshot
    python status.py --watch    # refresh every 30s

Reads analysis_state.json (updated after every ticker), orchestrate_progress.json (live current
ticker + ETA), factor_scores.json (the current RN/WL denominator) and the lockfile. No progress
bar in a background job — this is it.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
SD = Path(CONFIG["screener_data_dir"])
STATE = HERE / "cache" / "analysis_state.json"
PROGRESS = HERE / "cache" / "orchestrate_progress.json"
LOCK = HERE / "cache" / "orchestrate.lock"
PAUSE = HERE / "cache" / "PAUSED"
OVERLAY = SD / "llm_overlay.json"
REPORTS = Path(CONFIG["out_reports_dir"])
HEARTBEAT = HERE / "cache" / "heartbeat.json"
TASK = "RS2-Orchestrator"


def log_tail(n=8):
    """Last n non-blank lines of the freshest orchestrate log (scheduled task -> _orchestrate.log,
    manual nohup -> _pathB_orchestrate.log) so the LIVE stage progress (S1..S6) is visible."""
    logs = sorted(REPORTS.glob("*orchestrate*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return []
    try:
        lines = logs[0].read_text(encoding="utf-8", errors="ignore").splitlines()
        return [ln for ln in lines[-60:] if ln.strip()][-n:]
    except Exception:
        return []


def _age_str(iso):
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        h = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
        return f"  ({h:.0f}h ago)" if h >= 1 else "  (<1h ago)"
    except Exception:
        return ""


def _kill_pipeline():
    """Kill any running run_rs2 / deep_research / orchestrate procs and unload the models,
    freeing the GPU (e.g. to play games). analysis_state preserves progress -> resumable."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
          "'run_rs2\\.py|deep_research\\.py|orchestrate\\.py|keepawake\\.py' } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=30,
                       capture_output=True)
    except Exception:
        pass
    for m in ("rs2-analyst", "rs2-research"):
        try:
            ep = CONFIG["ollama_endpoint"].replace("/api/chat", "/api/generate")
            req = urllib.request.Request(ep, data=json.dumps({"model": m, "keep_alive": 0}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:
            pass


_TASK_CACHE = {"t": 0.0, "v": (None, None, None)}


def _task_info():
    """(state, next_run, last_run) for the Windows scheduled task, or (None, ...) if not registered.
    Cached 60s so the interactive loop doesn't spawn PowerShell on every refresh."""
    if time.time() - _TASK_CACHE["t"] < 60:
        return _TASK_CACHE["v"]
    val = (None, None, None)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$i=Get-ScheduledTaskInfo -TaskName '{TASK}' -ErrorAction Stop; "
             f"$t=Get-ScheduledTask -TaskName '{TASK}'; "
             "Write-Output ($t.State); Write-Output $i.NextRunTime; Write-Output $i.LastRunTime"],
            capture_output=True, text=True, timeout=20)
        out = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
        if len(out) >= 2:
            val = (out[0], out[1], (out[2] if len(out) > 2 else "—"))
    except Exception:
        pass
    _TASK_CACHE["t"] = time.time()
    _TASK_CACHE["v"] = val
    return val


def load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))   # tolerate BOM (state-wipe trap)
    except Exception:
        return d


def _lock_pid_alive():
    """True/False if the PID in the lockfile is live/dead; None if unreadable or PID-less. A lock whose
    PID is DEAD is a crashed run masquerading as RUNNING (the 2026-07-30 ghost) — report it as STALLED,
    not RUNNING. Cheap OpenProcess check — no PowerShell, safe to call every refresh in --watch."""
    try:
        parts = LOCK.read_text(encoding="utf-8").strip().split()
        pid = int(parts[0]) if parts and parts[0].isdigit() else None
    except Exception:
        return None
    if pid is None:
        return None
    if os.name != "nt":
        return True
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False


def bar(done, total, w=22):
    total = max(total, 1)
    f = int(round(w * min(done, total) / total))
    return "[" + "#" * f + "·" * (w - f) + f"] {done}/{total} ({100*done//total}%)"


def verdict_of(rep):
    if not rep:
        return {}
    return load(REPORTS / rep / "verdict.json", {}) or {}


def snapshot():
    fs = (load(SD / "factor_scores.json", {}) or {}).get("tickers", {})
    cur = {t.upper(): e.get("fct_band") for t, e in fs.items()
           if e.get("fct_band") in ("research_now", "watchlist")}
    rn = {t for t, b in cur.items() if b == "research_now"}
    wl = {t for t, b in cur.items() if b == "watchlist"}
    state = load(STATE, {}) or {}
    prog = load(PROGRESS, {}) or {}

    analyzed = {t for t, s in state.items() if s.get("last_analyzed") and s.get("ok")}
    rn_done = len(rn & analyzed)
    wl_done = len(wl & analyzed)
    total_done = len((rn | wl) & analyzed)
    fails = [t for t, s in state.items() if s.get("last_analyzed") and not s.get("ok")]

    L = []
    L.append(f"RS2 ORCHESTRATOR STATUS   ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    L.append("=" * 60)
    # running?
    running = LOCK.exists()
    lock_alive = _lock_pid_alive() if running else None
    if PAUSE.exists():
        frozen = bool(_pipeline_pids())   # procs still alive => paused/frozen; none => stopped/killed
        how = "FROZEN in place (paused)" if frozen else "STOPPED (killed, GPU free)"
        L.append(f"⏸  HALTED — {how}; auto-runs blocked. "
                 "Resume: `python status.py resume` (unfreezes a pause / relaunches a stop).")
    elif running and lock_alive is False:
        # lockfile present but its orchestrator PID is DEAD -> a crashed run, NOT a live one. Do not
        # let the stale progress snapshot masquerade as RUNNING (the 2026-07-30 ghost-status incident).
        L.append(f"⚠  STALLED — lock present but orchestrator PID is DEAD (previous run crashed"
                 + (f", died on {prog['current']}" if prog.get("current") else "") + "). "
                 "GPU is not being used. The next scheduled run self-heals the lock + resumes; "
                 "or run `python status.py resume` now to continue immediately.")
    elif running and prog.get("current"):
        L.append(f"RUNNING — now: {prog['current']} ({prog.get('current_band','')} · "
                 f"{prog.get('reason','?')}, started {prog.get('current_started','?')})")
        if prog.get("idx") and prog.get("queue_total"):
            L.append(f"  this run: {prog['idx']}/{prog['queue_total']}"
                     + (f"  avg {prog['avg_sec_per_ticker']}s/ticker" if prog.get("avg_sec_per_ticker") else "")
                     + (f"  ETA finish {prog['eta_finish']}" if prog.get("eta_finish") else ""))
    elif running:
        L.append("RUNNING — (between tickers)")
    else:
        L.append(f"idle — last progress update: {prog.get('updated','never')}")
    # Windows scheduled-task timer (the "cron" that auto-runs the orchestrator)
    tstate, tnext, tlast = _task_info()
    if tstate is None:
        L.append("schedule: RS2-Orchestrator task NOT registered "
                 "(run register_orchestrator_task.ps1). Auto-runs are OFF.")
    elif PAUSE.exists():
        L.append(f"schedule: task {tstate} but PAUSED — the 6am/at-logon run will exit immediately "
                 "until you resume.")
    else:
        last_disp = "never" if (tlast and "1999" in tlast) else (tlast or "—")
        L.append(f"schedule: task {tstate} | next auto-run {tnext or '—'} | last run {last_disp}")
    # last completed-run status (from the heartbeat) so a silent failure is visible at a glance
    hb = load(HEARTBEAT, {})
    if hb:
        extra = (f" — ran {hb.get('ran')}, failed {hb.get('failed')}, push {hb.get('push')}"
                 if hb.get("status") == "ok" else "")
        L.append(f"last completed run: {hb.get('status','?')}{_age_str(hb.get('ts'))}{extra}")
    L.append("")
    L.append("live activity (log tail — is it progressing through S1..S6 or hung?):")
    tail = log_tail(8)
    for ln in tail:
        L.append("  " + ln[:98])
    if not tail:
        L.append("  (no orchestrate log found in reports/)")
    L.append("")
    # recent completions (last 6 by last_analyzed + report mtime)
    done_list = [(t, s) for t, s in state.items() if s.get("report")]
    done_list.sort(key=lambda kv: (REPORTS / kv[1]["report"]).stat().st_mtime
                   if (REPORTS / kv[1]["report"]).exists() else 0, reverse=True)
    L.append("recent done:")
    for t, s in done_list[:6]:
        v = verdict_of(s.get("report"))
        L.append(f"  {t:6} {str(s.get('band','')):12} {str(v.get('method','?'))[:12]:12} "
                 f"stance={str(v.get('stance','-')):11} {str(v.get('action','-'))[:22]:22} "
                 f"conv={v.get('conviction','-')}")
    if not done_list:
        L.append("  (none yet)")
    L.append("")
    if fails:
        L.append(f"failures ({len(fails)}, re-run next pass): " + " ".join(sorted(fails)))
    ov = load(OVERLAY, {})
    if ov:
        gen = ov.get("generated_at", "?")
        L.append(f"overlay: {ov.get('count','?')} tickers | generated {gen}{_age_str(gen)}")
    else:
        L.append("overlay: not written yet")
    return "\n".join(L)


def _pipeline_pids():
    """PIDs of the live orchestrate/run_rs2/deep_research procs (leave keepawake alone)."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
          "'orchestrate\\.py|run_rs2\\.py|deep_research\\.py' } | ForEach-Object { $_.ProcessId }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=30)
        return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]
    except Exception:
        return []


def _suspend_pipeline(suspend):
    """FREEZE (suspend) / UNFREEZE (resume) the running pipeline via NtSuspendProcess/NtResumeProcess —
    a TRUE pause: frozen in place (progress + loaded models intact), not killed. Returns count affected."""
    if os.name != "nt":
        return 0
    import ctypes
    nt, k32 = ctypes.windll.ntdll, ctypes.windll.kernel32
    fn = nt.NtSuspendProcess if suspend else nt.NtResumeProcess
    n = 0
    for pid in _pipeline_pids():
        h = k32.OpenProcess(0x0800, False, pid)   # PROCESS_SUSPEND_RESUME
        if h:
            try:
                fn(h); n += 1
            finally:
                k32.CloseHandle(h)
    return n


def do_pause():
    """PAUSE = FREEZE the running pipeline in place (NOT kill — that's [s] stop). Progress and the
    loaded models stay resident; resume continues the exact ticker. Sets the flag so a scheduled run
    won't start a second instance while frozen."""
    PAUSE.parent.mkdir(exist_ok=True)
    PAUSE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    n = _suspend_pipeline(True)
    return (f"PAUSED — froze {n} process(es) in place (not killed; resume continues the same ticker). "
            "GPU/VRAM stays held — use [s] stop to kill + free it." if n else
            "PAUSED — flag set (no active run to freeze). A scheduled run will wait until you resume.")


def _launch_orchestrator():
    """Spawn orchestrate.py DETACHED so it keeps running after status.py exits (its lockfile prevents a
    duplicate). Output appended to reports/_orchestrate.log."""
    try:
        flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0   # DETACHED_PROCESS | NO_WINDOW
        logf = open(REPORTS / "_orchestrate.log", "a", encoding="utf-8")
        subprocess.Popen([sys.executable, str(HERE / "orchestrate.py")],
                         stdout=logf, stderr=subprocess.STDOUT, cwd=str(HERE),
                         creationflags=flags, close_fds=True)
        return True
    except Exception as e:
        print(f"  launch failed: {e}", flush=True)
        return False


def do_resume():
    """RESUME = continue the work, however it was halted:
       - after PAUSE (freeze)      -> UNFREEZE the same processes (continues the exact ticker)
       - after STOP  (kill+unload) -> RELAUNCH the orchestrator (continues from saved analysis_state)."""
    PAUSE.unlink(missing_ok=True)
    n = _suspend_pipeline(False)                       # was it frozen? unfreeze
    if n:
        return f"RESUMED — unfroze {n} process(es); continuing the same ticker."
    if LOCK.exists():
        return "A run is already active — continuing. (pause flag cleared)"
    ok = _launch_orchestrator()                        # it was stopped/killed -> relaunch from state
    return ("RESUMED — orchestrator relaunched (detached); reloads models + continues from where it "
            "left off (analysis_state). Watch the live activity above."
            if ok else "Flag cleared but relaunch FAILED — run `python orchestrate.py` manually.")


def do_stop():
    """STOP (for gaming) = KILL the run + unload the models (frees the GPU/VRAM) AND block scheduled
    auto-runs so nothing restarts mid-game. Progress is saved -> `resume` relaunches from where it left
    off. (Pause, by contrast, freezes without freeing the GPU.)"""
    PAUSE.parent.mkdir(exist_ok=True)
    PAUSE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")   # block auto-runs
    _kill_pipeline()                 # kill procs + unload models -> GPU free
    LOCK.unlink(missing_ok=True)
    return ("STOPPED — run killed, models unloaded, GPU FREE to game. Auto-runs blocked. "
            "Press r to resume (relaunches + continues from saved progress).")


FOOTER = "  keys:   [p] pause (freeze)    [r] resume (unfreeze)    [s] stop (kill+free GPU)    [f] refresh    [q] quit"


def interactive(refresh=15):
    """Live dashboard with single-key control. p/r/s act immediately; auto-refreshes every `refresh`s."""
    try:
        import msvcrt
    except ImportError:
        print(snapshot())
        print("\n(interactive hotkeys are Windows-only — use: python status.py pause|resume|stop)")
        return
    msg = ""

    def render():
        os.system("cls" if os.name == "nt" else "clear")
        print(snapshot())
        print()
        if msg:
            print(f"  » {msg}\n")
        print(FOOTER)

    render()
    last = time.time()
    while True:
        if msvcrt.kbhit():
            raw = msvcrt.getch()
            if raw in (b"\x00", b"\xe0"):     # arrow / function key -> discard the 2nd byte, ignore
                msvcrt.getch()
                ch = ""
            else:
                ch = raw.decode("utf-8", "ignore").lower()
            if ch == "q":
                break
            elif ch == "p":
                print("\n  working: pausing + unloading models (a few seconds)...", flush=True)
                msg = do_pause(); render(); last = time.time()
            elif ch == "r":
                msg = do_resume(); render(); last = time.time()
            elif ch == "s":
                print("\n  working: stopping current run...", flush=True)
                msg = do_stop(); render(); last = time.time()
            elif ch == "f":
                msg = ""; render(); last = time.time()
        elif time.time() - last >= refresh:
            msg = ""; render(); last = time.time()
        time.sleep(0.12)


def main():
    ap = argparse.ArgumentParser(description="RS2 orchestrator live dashboard + pause/resume/stop control.")
    ap.add_argument("cmd", nargs="?", choices=["status", "pause", "resume", "stop"], default="status",
                    help="no arg = live dashboard (press p/r/s inside it); or run one action non-interactively")
    ap.add_argument("--once", action="store_true", help="print one snapshot and exit (no live UI)")
    ap.add_argument("--refresh", type=int, default=15, help="live-dashboard auto-refresh seconds (default 15)")
    args = ap.parse_args()
    if args.cmd == "pause":
        print(do_pause()); return
    if args.cmd == "resume":
        print(do_resume()); return
    if args.cmd == "stop":
        print(do_stop()); return
    if args.once or not sys.stdin.isatty():
        print(snapshot()); return
    interactive(args.refresh)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
