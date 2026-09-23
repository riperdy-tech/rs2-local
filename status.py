#!/usr/bin/env python3
"""status.py — DEPTH-tier orchestrator dashboard + graceful pause / stop / resume.

    python status.py            # live interactive dashboard (type command, press ENTER)
    python status.py --once     # one-shot snapshot, no live UI
    python status.py start|pause|resume|stop   # non-interactive single command

Controls the DEPTH pipeline (orchestrate_depth.py / the RS2-Depth-Orchestrator scheduled task).

PAUSE and STOP are GRACEFUL by design: they NEVER kill or freeze a sample mid-run. They set
cache/DEPTH_PAUSED, and the running sweep stops at the next TICKER boundary — after the in-flight
name has finished all its samples and written its verdict. A half-analysed ticker has no verdict,
so the ticker is the clean unit to stop on. RESUME clears the flag and relaunches.

  * start — launch a sweep now. Refuses if paused or already running.
  * pause — halt after current ticker finishes its verdict; auto-runs blocked until resume.
  * stop  — same graceful halt, and free the GPU: models unload once idle.
  * resume — clear DEPTH_PAUSED and relaunch the sweep (re-queues due names from state + triggers).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import paths

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
from fiduciary_gate import contract_base  # noqa: E402

CONFIG = paths.load_config()   # STOCKS_ROOT contract: paths.py owns the peer-repo locations
SD = Path(CONFIG["screener_data_dir"])
DEPTH_STATE = HERE / "cache" / "depth_state.json"
DEPTH_PROGRESS = HERE / "cache" / "depth_progress.json"
DEPTH_LOCK = HERE / "cache" / "orchestrate_depth.lock"
DEPTH_PAUSE = HERE / "cache" / "DEPTH_PAUSED"
LEDGER = HERE / "cache" / "depth_ledger.jsonl"
DEPTH_LOG = HERE / "cache" / "depth_orchestrate.log"
DEPTH_TASK = "RS2-Depth-Orchestrator"
DEPTH_MODEL = CONFIG.get("depth_model", "rs2-analyst-deep-mtp5")
RESEARCH_MODEL = CONFIG.get("research_model", "rs2-research")
DEPTH_CTX = CONFIG.get("depth_ctx", 81920)


def load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d


def _proc_alive(pid):
    """Cheap OpenProcess liveness check (no PowerShell) — safe to call every refresh."""
    if not pid:
        return False
    if os.name != "nt":
        return True
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False


def _lock_pid():
    try:
        return int((json.loads(DEPTH_LOCK.read_text()) or {}).get("pid", 0))
    except Exception:
        return 0


def _sweep_running():
    """True if the orchestrate_depth process named in the lockfile is alive."""
    return _proc_alive(_lock_pid())


def _child_pids():
    """PIDs of live depth CHILD procs (a ticker actually being worked)."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
          "'depth_pipeline\\.py|deep_research\\.py|consensus_valuation\\.py' } | "
          "ForEach-Object { $_.ProcessId }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=30)
        return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]
    except Exception:
        return []


def _depth_active():
    """True if a sweep is running OR a ticker child is live."""
    return _sweep_running() or bool(_child_pids())


def _unload_models():
    """keep_alive:0 on the depth + research models to release VRAM. Call ONLY when idle."""
    import urllib.request
    ep = CONFIG["ollama_endpoint"].replace("/api/chat", "/api/generate")
    for m in (DEPTH_MODEL, RESEARCH_MODEL):
        try:
            req = urllib.request.Request(
                ep, data=json.dumps({"model": m, "keep_alive": 0}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:
            pass


_TASK_CACHE = {"t": 0.0, "v": (None, None, None)}


def _task_info():
    """(state, next_run, last_run) for RS2-Depth-Orchestrator; cached 60s."""
    if time.time() - _TASK_CACHE["t"] < 60:
        return _TASK_CACHE["v"]
    val = (None, None, None)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$i=Get-ScheduledTaskInfo -TaskName '{DEPTH_TASK}' -ErrorAction Stop; "
             f"$t=Get-ScheduledTask -TaskName '{DEPTH_TASK}'; "
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


def _launch_depth():
    """Spawn orchestrate_depth.py DETACHED."""
    try:
        logf = open(DEPTH_LOG, "a", encoding="utf-8")
        flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, str(HERE / "orchestrate_depth.py")],
                         cwd=str(HERE), stdout=logf, stderr=subprocess.STDOUT,
                         creationflags=flags, close_fds=True)
        return True
    except Exception as e:
        print(f"  launch failed: {e}", flush=True)
        return False


# ---------------------------------------------------------------- controls (all graceful) --------


def do_pause():
    """GRACEFUL pause: set DEPTH_PAUSED. A running sweep finishes the CURRENT ticker."""
    DEPTH_PAUSE.parent.mkdir(exist_ok=True)
    DEPTH_PAUSE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    if _depth_active():
        return ("PAUSE REQUESTED — the sweep will finish the current ticker (all samples), write "
                "its verdict, then halt at the boundary. Auto-runs blocked until resume.")
    return "PAUSED — flag set (no sweep active). Scheduled and manual runs blocked until you resume."


def do_stop():
    """GRACEFUL stop + free the GPU."""
    DEPTH_PAUSE.parent.mkdir(exist_ok=True)
    DEPTH_PAUSE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    if _depth_active():
        return ("STOP REQUESTED — the sweep will finish the current ticker then exit; the GPU "
                "frees when that ticker ends. Auto-runs blocked until resume.")
    _unload_models()
    return "STOPPED — pipeline was idle; models unloaded, GPU VRAM free. Auto-runs blocked."


def do_resume():
    """Clear DEPTH_PAUSED and continue."""
    DEPTH_PAUSE.unlink(missing_ok=True)
    if _sweep_running():
        return "RESUMED — flag cleared; a sweep is still running and will continue."
    ok = _launch_depth()
    return ("RESUMED — depth sweep relaunched (detached); re-queues due names and continues. "
            if ok else "Flag cleared but relaunch FAILED — run `python orchestrate_depth.py` manually.")


def do_start():
    """Manually launch a sweep NOW."""
    if DEPTH_PAUSE.exists():
        return ("NOT STARTED — DEPTH_PAUSED is set. Use `resume` to clear the pause flag and launch.")
    if _sweep_running():
        return "ALREADY RUNNING — a sweep is active (lockfile PID alive); not starting a second."
    ok = _launch_depth()
    return ("STARTED — depth sweep launched (detached). Monitoring active." if ok else
            "START FAILED — run `python orchestrate_depth.py` manually.")


# ---------------------------------------------------------------- dashboard ----------------------


def _sweep_progress():
    """This sweep's position + what's pending."""
    p = load(DEPTH_PROGRESS)
    if p and p.get("total") is not None:
        idx = int(p.get("idx") or 0)
        q = p.get("queue") or []
        pending_names = [e.get("t") for e in q[idx:] if isinstance(e, dict) and e.get("t")]
        return {"total": int(p["total"]), "idx": idx, "current": p.get("current"),
                "pending": pending_names, "queue_detail": q, "active": bool(p.get("active"))}
    if not DEPTH_LOG.exists():
        return None
    text = DEPTH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    anchor = max((i for i, ln in enumerate(text) if "membership snapshot" in ln), default=None)
    if anchor is None:
        anchor = max((i for i, ln in enumerate(text) if re.search(r"\| due \d+", ln)), default=None)
    if anchor is None:
        return None
    seg = text[anchor:]
    queued = [m.group(1) for ln in seg if (m := re.search(r"queued (\S+):", ln))]
    idxs = [(int(m.group(1)), int(m.group(2)), m.group(3))
            for ln in seg if (m := re.search(r"\[(\d+)/(\d+)\]\s+(\S+)\s*$", ln))]
    if not idxs:
        return None
    idx, total, current = idxs[-1]
    return {"total": total, "idx": idx, "current": current,
            "pending": queued[idx:], "queue_detail": [], "active": _sweep_running()}


def _draw_bar(current, total, width=28):
    if total <= 0:
        return "░" * width
    ratio = min(1.0, max(0.0, current / total))
    filled = int(round(width * ratio))
    return "█" * filled + "░" * (width - filled)


def depth_snapshot():
    """Status of the depth-tier pipeline with Section 12 telemetry and progress bar."""
    dstate = load(DEPTH_STATE, {}) or {}
    L = []
    
    # ── Header
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    L.append("╔" + "═" * 78 + "╗")
    L.append(f"║  RS2 INSTITUTIONAL DEPTH ORCHESTRATOR                {now_str}  ║")
    L.append(f"║  Engine: {DEPTH_MODEL:<24} | Ctx: {DEPTH_CTX:<6} | Think: high (deep)     ║")
    L.append(f"║  Consensus: Adaptive 2-Escalate (Early <=15%, Escalate n=3) | Tools: SearXNG  ║")
    L.append("╚" + "═" * 78 + "╝")

    alive = _sweep_running()
    paused = DEPTH_PAUSE.exists()
    lock_pid = _lock_pid()

    # ── Operational State Banner
    if paused and alive:
        L.append("  [⏳ PAUSE REQUESTED] Active sweep will finish current ticker, then halt.")
        L.append("                       Resume anytime via 'r' (resume).")
    elif paused:
        L.append("  [⏸  PAUSED] Halted via DEPTH_PAUSED. Auto-runs blocked.")
        L.append("              Press 'r' + ENTER to resume sweep.")
    elif alive:
        L.append(f"  [●  RUNNING] Sweep process ACTIVE (PID: {lock_pid}).")
    elif DEPTH_LOCK.exists() and not paused:
        L.append("  [⚠  STALLED] Stale lockfile detected but PID is dead. Run self-heals next fire.")
    else:
        L.append("  [○  IDLE] No sweep in progress. Press 'g' + ENTER to start.")

    # Scheduled Task state
    tstate, tnext, tlast = _task_info()
    if tstate is not None:
        L.append(f"  Task Schedule: {tstate} | Next: {tnext or '—'} | Last: {tlast or '—'}")

    # ── Ingestion & Verdict tallies
    verdicts = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                verdicts[v["ticker"]] = v
            except Exception:
                pass
    
    ok_count = len([t for t, r in dstate.items() if r.get("ok")])
    fail_count = len([t for t, r in dstate.items() if not r.get("ok")])
    L.append(f"  Ledger Status: {len(verdicts)} verified underwritings on file | State: {ok_count} ok, {fail_count} failed")
    L.append("─" * 80)

    # ── Active In-Flight Telemetry
    _dirpat = re.compile(r"^([A-Z0-9.\-]+)_(\d{8}_\d{6})$")
    cons_dir = HERE / "ab_reports" / "consensus"
    cdirs = []
    if cons_dir.exists():
        for d in cons_dir.glob("*_*"):
            if d.is_dir() and (m := _dirpat.match(d.name)):
                cdirs.append((m.group(1), m.group(2), d))
    cdirs.sort(key=lambda x: x[1], reverse=True)

    # Priority: If depth_progress.json specifies an active ticker, match that ticker's folder
    cur = None
    sp_curr = (load(DEPTH_PROGRESS) or {}).get("current")
    if sp_curr:
        cur = next(((t, d) for t, _ts, d in cdirs if t == sp_curr and not (d / "verdict_depth.json").exists()), None)
    if not cur:
        cur = next(((t, d) for t, _ts, d in cdirs if not (d / "verdict_depth.json").exists()), None)

    if alive and cur:
        t, d = cur
        # Filter strictly for formal sample files: sample1.md, sample2.md (exclude *_thinking.md)
        sample_files = sorted([f for f in d.glob("sample*.md") if re.match(r"^sample\d+\.md$", f.name)],
                              key=lambda f: int(re.search(r"\d+", f.name).group()))
        n_done = len(sample_files)

        # Ticker start time (directory creation or _pack.md mtime)
        t_start_ts = (d / "_pack.md").stat().st_mtime if (d / "_pack.md").exists() else d.stat().st_ctime
        t_start_dt = datetime.fromtimestamp(t_start_ts)
        mins_tot = max(0, int((datetime.now().timestamp() - t_start_ts) / 60))
        newest = max((f.stat().st_mtime for f in d.rglob("*") if f.is_file()), default=None)
        mins_last = f"{int((datetime.now().timestamp() - newest) / 60)}" if newest else "?"

        tool_queries = len(list(d.rglob("query_*.json")))
        tool_pages = len(list(d.rglob("page_*.html"))) + len(list(d.rglob("page_*.md")))

        # In-flight sample stage and duration
        if n_done == 0:
            s_curr_start_ts = t_start_ts
            curr_step = "Sample 1/2 (Adaptive)"
        elif n_done == 1:
            s_curr_start_ts = sample_files[0].stat().st_mtime
            curr_step = "Sample 2/2 (Adaptive)"
        elif n_done == 2:
            s_curr_start_ts = sample_files[1].stat().st_mtime
            curr_step = "Sample 3/3 (Escalated)"
        else:
            s_curr_start_ts = sample_files[-1].stat().st_mtime
            curr_step = "Consensus Aggregation & Stamping"

        s_curr_mins = max(0, int((datetime.now().timestamp() - s_curr_start_ts) / 60))
        s_curr_start_str = datetime.fromtimestamp(s_curr_start_ts).strftime("%H:%M")

        L.append(f"  ⚡ IN-FLIGHT WORK: {t}   [Started {t_start_dt.strftime('%H:%M:%S')} | Total: {mins_tot}m elapsed | Last artifact: {mins_last}m ago]")
        L.append(f"     ├── Stage: {curr_step} — RUNNING on GPU for {s_curr_mins}m (started {s_curr_start_str})")

        # Display completed samples with exact durations and timestamps
        cj_runs = {}
        if (d / "consensus.json").exists():
            try:
                cj = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
                for r in cj.get("runs", []):
                    cj_runs[r.get("sample")] = r
            except Exception:
                pass

        prev_finish_ts = t_start_ts
        for i, sf in enumerate(sample_files, start=1):
            finish_ts = sf.stat().st_mtime
            dur = max(1, int((finish_ts - prev_finish_ts) / 60))
            st_str = datetime.fromtimestamp(prev_finish_ts).strftime("%H:%M")
            fin_str = datetime.fromtimestamp(finish_ts).strftime("%H:%M")
            th_f = sf.with_name(f"{sf.stem}_thinking.md")
            th_str = f" [Thinking: {th_f.stat().st_size/1024:.0f} KB]" if th_f.exists() else ""

            run_meta = cj_runs.get(i)
            if run_meta:
                s_iv = f"${run_meta.get('iv'):.2f}" if run_meta.get('iv') else "?"
                sc = run_meta.get("scorecard") or {}
                s_conv = f"{sc.get('conviction_score')}/15" if sc.get('conviction_score') is not None else "n/a"
                s_moat = f"{sc.get('business_quality_moat')}/5.0" if sc.get('business_quality_moat') is not None else "n/a"
                L.append(f"     ├── Sample {i}: completed in {dur}m ({st_str} → {fin_str}) | IV {s_iv} | Conviction {s_conv} | Moat {s_moat}{th_str}")
            else:
                L.append(f"     ├── Sample {i}: completed in {dur}m ({st_str} → {fin_str}) | Report: {sf.stat().st_size/1024:.1f} KB{th_str}")
            prev_finish_ts = finish_ts

        L.append(f"     └── Live Research: {tool_queries} SearXNG queries, {tool_pages} source pages snapshotted")
        L.append("─" * 80)
    elif alive:
        briefs = sorted((HERE / "research").glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if briefs and (datetime.now().timestamp() - briefs[0].stat().st_mtime) < 3600:
            b_mins = int((datetime.now().timestamp() - briefs[0].stat().st_mtime) / 60)
            L.append(f"  ⚡ IN-FLIGHT WORK: {briefs[0].stem}   [Research / Enrich Phase ({b_mins}m ago)]")
            L.append("     └── Assembling fresh deep-research brief with live SEC & macro context")
            L.append("─" * 80)

    # ── Sweep Progress & Queue Breakdown
    sp = _sweep_progress()
    mins = []
    if DEPTH_LOG.exists():
        try:
            marks = re.findall(r"\[depth-orch (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+\[\d+/\d+\]",
                               DEPTH_LOG.read_text(encoding="utf-8", errors="replace"))
            for a, b in zip(marks, marks[1:]):
                try:
                    start = datetime.strptime(a, "%Y-%m-%d %H:%M:%S")
                    gap = (datetime.strptime(b, "%Y-%m-%d %H:%M:%S") - start).total_seconds() / 60
                    if 20 < gap < 240:
                        mins.append(gap)
                except Exception:
                    pass
        except Exception:
            pass
    mins.sort()
    rate = mins[len(mins) // 2] if len(mins) >= 3 else 48.0
    src = f"median of {len(mins)} runs" if len(mins) >= 3 else "measured adaptive baseline"

    if sp and sp["total"]:
        total = sp["total"]
        idx = sp["idx"]
        pending_n = max(0, total - idx)
        pct = (idx / total * 100) if total > 0 else 0.0
        bar = _draw_bar(idx, total, width=28)
        
        L.append(f"  SWEEP PROGRESS: [{bar}] {idx}/{total} ({pct:.1f}%) | {pending_n} Pending")
        
        # Categorized Queue
        q_detail = sp.get("queue_detail", [])[idx:]
        events = [e["t"] for e in q_detail if e.get("class") == 0]
        baseline = [e["t"] for e in q_detail if e.get("class") == 1]
        reentry = [e["t"] for e in q_detail if e.get("class") == 2]
        rotation = [e["t"] for e in q_detail if e.get("class") == 3]

        L.append(f"  Queue Breakdown: {len(events)} Event/Triggered | {len(baseline)} Baseline Underwritings | {len(reentry)} Re-entry | {len(rotation)} Rotation")
        
        # Show upcoming pending list
        shown = [e.get("t") for e in q_detail[:10]]
        if shown:
            L.append(f"  Next Up: {', '.join(shown)}" + (f"  (+{len(q_detail) - len(shown)} more)" if len(q_detail) > len(shown) else ""))

        gpu_hours = pending_n * rate / 60.0
        days = gpu_hours / 24.0
        est_finish = datetime.now() + timedelta(minutes=pending_n * rate)
        L.append(f"  ETA: ~{pending_n} tickers × {rate:.0f} min ({src}) = {gpu_hours:.1f} GPU-hours (~{days:.1f} days)")
        L.append(f"  Projected Completion: {est_finish.strftime('%Y-%m-%d %H:%M')}")
    else:
        L.append(f"  Sweep Queue: No active sweep queued (idle). {len(verdicts)} verified verdicts on file.")
        L.append(f"  Estimated Pace: ~{rate:.0f} min/name ({src}) under adaptive 2-escalate consensus.")

    L.append("─" * 80)

    # ── Recent Institutional Underwritings Table (Section 12 Contract)
    L.append("  RECENT INSTITUTIONAL UNDERWRITINGS (Charter v3.1 / Section 12):")
    if verdicts:
        recent = sorted(verdicts.values(), key=lambda v: v.get("consensus_dir", v.get("date", "")), reverse=True)[:6]
        header = f"  {'Ticker':<6} {'Verdict':<12} {'Completed':<10} {'Price':<9} {'Median IV':<9} {'Base IV':<9} {'Spread':<8} {'Moat':<7} {'Convict':<8} {'Kelly%':<8} {'Skew':<6}"
        L.append(header)
        L.append("  " + "-" * 88)
        for v in recent:
            t = v.get("ticker", "—")
            dir_str = v.get("direction", "—")
            cdir = v.get("consensus_dir", "")
            m_time = re.search(r"_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$", cdir)
            if m_time:
                done_time = f"{m_time.group(4)}:{m_time.group(5)}"
            else:
                done_time = v.get("date", "—")[-5:]
            px = f"${v.get('price'):.2f}" if v.get("price") is not None else "—"
            med_iv = f"${v.get('median_iv'):.2f}" if v.get("median_iv") is not None else "—"
            base_iv_val = contract_base(v.get("scorecard"))
            base_iv = f"${base_iv_val:.2f}" if base_iv_val is not None else "—"
            spread = f"{v.get('spread_pct'):.1f}%" if v.get("spread_pct") is not None else "single"
            moat = f"{v.get('business_quality_moat'):.1f}/5" if v.get("business_quality_moat") is not None else "—"
            conv = f"{v.get('conviction_score'):.0f}/15" if v.get("conviction_score") is not None else "—"
            kelly = f"{v.get('kelly_fraction_pct'):.1f}%" if v.get("kelly_fraction_pct") is not None else "—"
            skew = f"{v.get('asymmetric_payoff_skew'):.2f}x" if v.get("asymmetric_payoff_skew") is not None else "—"
            row = f"  {t:<6} {dir_str:<12} {done_time:<10} {px:<9} {med_iv:<9} {base_iv:<9} {spread:<8} {moat:<7} {conv:<8} {kelly:<8} {skew:<6}"
            L.append(row)
    else:
        L.append("  (No clean underwritings recorded in ledger yet)")

    L.append("")
    return "\n".join(L)


FOOTER = ("  COMMANDS:  g=start (run now)   p=pause (graceful)   r=resume   "
          "s=stop (free GPU)   f/ENTER=refresh   q=quit")


def interactive(refresh=15):
    """Live interactive dashboard with two-stage keystroke protection."""
    try:
        import msvcrt
    except ImportError:
        print(depth_snapshot())
        print("\n(Interactive input requires Windows — use: python status.py pause|resume|stop)")
        return
    msg = ""
    buf = ""

    def render():
        os.system("cls" if os.name == "nt" else "clear")
        print(depth_snapshot())
        if msg:
            print(f"  » {msg}\n")
        print(FOOTER)
        print(f"  command> {buf}", end="", flush=True)

    render()
    last = time.time()
    while True:
        if msvcrt.kbhit():
            raw = msvcrt.getch()
            if raw in (b"\x00", b"\xe0"):     # function / arrow key
                msvcrt.getch()
                continue
            if raw in (b"\r", b"\n"):
                cmd, buf = buf.strip().lower(), ""
                if cmd == "q":
                    print()
                    break
                elif cmd in ("g", "start"):
                    print("\n  working: launching sweep...", flush=True)
                    msg = do_start(); render(); last = time.time()
                elif cmd in ("p", "pause"):
                    print("\n  working: requesting graceful pause...", flush=True)
                    msg = do_pause(); render(); last = time.time()
                elif cmd in ("r", "resume"):
                    msg = do_resume(); render(); last = time.time()
                elif cmd in ("s", "stop"):
                    print("\n  working: requesting graceful stop...", flush=True)
                    msg = do_stop(); render(); last = time.time()
                elif cmd in ("", "f", "refresh"):
                    msg = ""; render(); last = time.time()
                else:
                    msg = f"Unknown command {cmd!r} — use g(start) / p(pause) / r(resume) / s(stop) / f(refresh) / q(quit)"
                    render(); last = time.time()
            elif raw == b"\x08":              # backspace
                buf = buf[:-1]
                print(f"\r  command> {buf} \b", end="", flush=True)
            else:
                ch = raw.decode("utf-8", "ignore")
                if ch.isprintable():
                    buf += ch
                    print(ch, end="", flush=True)
        elif time.time() - last >= refresh:
            msg = ""
            render(); last = time.time()
        time.sleep(0.12)


def main():
    ap = argparse.ArgumentParser(
        description="RS2 depth-tier dashboard + graceful pause/resume/stop control.")
    ap.add_argument("cmd", nargs="?", choices=["status", "start", "pause", "resume", "stop"],
                    default="status",
                    help="no arg = live dashboard (press g/p/r/s inside it); or one action non-interactively")
    ap.add_argument("--once", action="store_true", help="print one snapshot and exit (no live UI)")
    ap.add_argument("--refresh", type=int, default=15, help="live-dashboard auto-refresh seconds (default 15)")
    args = ap.parse_args()
    if args.cmd == "start":
        print(do_start()); return
    if args.cmd == "pause":
        print(do_pause()); return
    if args.cmd == "resume":
        print(do_resume()); return
    if args.cmd == "stop":
        print(do_stop()); return
    if args.once or not sys.stdin.isatty():
        print(depth_snapshot()); return
    interactive(args.refresh)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
