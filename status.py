#!/usr/bin/env python3
"""status.py — DEPTH-tier orchestrator dashboard + graceful pause / stop / resume.

    python status.py            # live dashboard (type a letter, press ENTER; see footer)
    python status.py --once     # one-shot snapshot, no live UI
    python status.py start|pause|resume|stop   # one action, non-interactive

Controls the DEPTH pipeline (orchestrate_depth.py / the RS2-Depth-Orchestrator scheduled task).

PAUSE and STOP are GRACEFUL by design: they NEVER kill or freeze a sample mid-run. They set
cache/DEPTH_PAUSED, and the running sweep stops at the next TICKER boundary — after the in-flight
name has finished all its samples and written its verdict. A half-analysed ticker has no verdict,
so the ticker is the clean unit to stop on. RESUME clears the flag and relaunches.

  * start — launch a sweep now (e.g. after the daily data fetch, before the 02:00 run). Refuses
            if paused or already running.
  * pause — halt after the current ticker; auto-runs blocked until resume. (Come back soon.)
  * stop  — same graceful halt, and free the GPU: models unload once the pipeline is idle
            (immediately if nothing is running). (Done for a while / want the GPU to game.)
  * resume — clear the flag and relaunch the sweep (it re-queues due names from state + triggers).

The old production-orchestrator dashboard (orchestrate.py / RS2-Orchestrator) was removed
2026-08-25: that pipeline is dropped and its task stays disabled via cache/PAUSED.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
SD = Path(CONFIG["screener_data_dir"])
DEPTH_STATE = HERE / "cache" / "depth_state.json"
DEPTH_PROGRESS = HERE / "cache" / "depth_progress.json"
DEPTH_LOCK = HERE / "cache" / "orchestrate_depth.lock"
DEPTH_PAUSE = HERE / "cache" / "DEPTH_PAUSED"
LEDGER = HERE / "cache" / "depth_ledger.jsonl"
DEPTH_LOG = HERE / "cache" / "depth_orchestrate.log"
DEPTH_TASK = "RS2-Depth-Orchestrator"
DEPTH_MODEL = CONFIG.get("depth_model", "rs2-analyst-deep")
RESEARCH_MODEL = CONFIG.get("research_model", "rs2-research")


def load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))   # tolerate BOM (state-wipe trap)
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
    """PIDs of live depth CHILD procs (a ticker actually being worked): depth_pipeline /
    deep_research / consensus_valuation. PowerShell-backed, so used only for the one-shot stop
    decision — never in the refresh loop."""
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
    """True if a sweep is running OR a ticker child is live — i.e. the models may be in use, so it
    is NOT safe to unload. Only a fully idle pipeline (no orchestrator, no child) can free the GPU."""
    return _sweep_running() or bool(_child_pids())


def _unload_models():
    """keep_alive:0 on the depth + research models to release VRAM. Call ONLY when idle — unloading
    while a ticker is mid-sample would break that run."""
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
    """(state, next_run, last_run) for RS2-Depth-Orchestrator; (None,...) if not registered.
    Cached 60s so the refresh loop doesn't spawn PowerShell every tick."""
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
    """Spawn orchestrate_depth.py DETACHED (its lockfile prevents a duplicate). Output appended to
    the depth log via a cmd redirect so child output is inherited into the log rather than lost to
    a fresh console (same reasoning as the scheduled task)."""
    try:
        if os.name == "nt":
            flags = 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW
            line = f'""{sys.executable}" "{HERE / "orchestrate_depth.py"}" >> "{DEPTH_LOG}" 2>&1"'
            subprocess.Popen(f'cmd.exe /c {line}', cwd=str(HERE),
                             creationflags=flags, close_fds=True)
            return True
        logf = open(DEPTH_LOG, "a", encoding="utf-8")
        subprocess.Popen([sys.executable, str(HERE / "orchestrate_depth.py")],
                         stdout=logf, stderr=subprocess.STDOUT, cwd=str(HERE), close_fds=True)
        return True
    except Exception as e:
        print(f"  launch failed: {e}", flush=True)
        return False


# ---------------------------------------------------------------- controls (all graceful) --------


def do_pause():
    """GRACEFUL pause: set DEPTH_PAUSED. A running sweep finishes the CURRENT ticker (all its
    samples, never mid-sample), writes its verdict, then stops at the boundary and exits. Blocks
    scheduled auto-runs until resume. Nothing is killed or frozen."""
    DEPTH_PAUSE.parent.mkdir(exist_ok=True)
    DEPTH_PAUSE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    if _depth_active():
        return ("PAUSE REQUESTED — the sweep will finish the current ticker (never mid-sample), write "
                "its verdict, then stop at the boundary. Auto-runs blocked until resume.")
    return "PAUSED — flag set (no sweep active). Scheduled + manual runs wait until you resume."


def do_stop():
    """GRACEFUL stop + free the GPU. Same boundary-stop as pause (sets DEPTH_PAUSED, never kills a
    sample). If a ticker is in flight the models free when it finishes and the sweep exits; if the
    pipeline is already idle, unload the models now so VRAM is free immediately (e.g. to game)."""
    DEPTH_PAUSE.parent.mkdir(exist_ok=True)
    DEPTH_PAUSE.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    if _depth_active():
        return ("STOP REQUESTED — the sweep will finish the current ticker (never mid-sample) then "
                "exit; the GPU frees when that ticker's child ends. Auto-runs blocked until resume.")
    _unload_models()
    return "STOPPED — pipeline was idle; models unloaded, GPU free. Auto-runs blocked until resume."


def do_resume():
    """Clear DEPTH_PAUSED and continue. If a sweep is somehow still active, just clear the flag;
    otherwise relaunch orchestrate_depth (detached) so you don't wait for the next scheduled fire.
    The relaunched sweep re-queues due names from state + triggers and picks up where it left off."""
    DEPTH_PAUSE.unlink(missing_ok=True)
    if _sweep_running():
        return "RESUMED — flag cleared; a sweep is still running and will keep going."
    ok = _launch_depth()
    return ("RESUMED — depth sweep relaunched (detached); it re-queues due names and continues. "
            "Watch the live activity above." if ok else
            "Flag cleared but relaunch FAILED — run `python orchestrate_depth.py` manually.")


def do_start():
    """Manually launch a sweep NOW — e.g. after the daily data fetch lands and before the 02:00
    scheduled run, so the day's verdicts are ready earlier. Unlike resume it does NOT clear a
    pause: if DEPTH_PAUSED is set it refuses (a launched sweep would just exit at the flag), and it
    refuses to start a second sweep over a live one. The sweep itself snapshots membership, builds
    the trigger queue, and works the due names — identical to a scheduled fire."""
    if DEPTH_PAUSE.exists():
        return ("NOT STARTED — DEPTH_PAUSED is set, so a sweep would exit immediately. "
                "Use `resume` to clear the pause and launch.")
    if _sweep_running():
        return "already RUNNING — a sweep is active (lockfile PID alive); not starting a second."
    ok = _launch_depth()
    return ("STARTED — depth sweep launched (detached); snapshots membership, builds the trigger "
            "queue, works due names. Watch the live activity above." if ok else
            "start FAILED — run `python orchestrate_depth.py` manually.")


# ---------------------------------------------------------------- dashboard ----------------------


def _sweep_progress():
    """This sweep's position + what's pending. Prefers cache/depth_progress.json (written by the
    orchestrator per ticker); falls back to parsing the depth log for a sweep that started before
    the progress file existed. Returns {total, idx, current, pending:[names], active} or None."""
    p = load(DEPTH_PROGRESS)
    if p and p.get("total"):
        idx = int(p.get("idx") or 0)
        q = [e.get("t") for e in (p.get("queue") or [])]
        return {"total": int(p["total"]), "idx": idx, "current": p.get("current"),
                "pending": q[idx:], "active": bool(p.get("active"))}
    # fallback: parse the log for the newest "[i/N] TICKER", and the queued names after the last
    # "book … | due …" (only the first 20 are logged, so the named list may be partial).
    if not DEPTH_LOG.exists():
        return None
    text = DEPTH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    # anchor the segment at the sweep's START (its membership-snapshot line, else the book|due line)
    # so the `queued …` lines — logged just BEFORE book|due — are inside the segment.
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
            "pending": queued[idx:], "active": _sweep_running()}


def depth_snapshot():
    """Status of the depth-tier pipeline: the halt/schedule state, current ticker + within-ticker
    sample progress, recent verdicts, live artifacts, and a measured ETA for remaining names."""
    dstate = load(DEPTH_STATE, {}) or {}
    L = []
    L.append(f"RS2 DEPTH ORCHESTRATOR    ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    L.append("=" * 60)

    alive = _sweep_running()
    paused = DEPTH_PAUSE.exists()

    # halt / running state
    if paused and alive:
        L.append("PAUSE/STOP REQUESTED — halts at the next ticker boundary (current name finishes "
                 "its samples + verdict first). Resume: `python status.py resume`.")
    elif paused:
        L.append("HALTED — DEPTH_PAUSED set; auto-runs blocked. Resume: `python status.py resume`.")
    if alive:
        L.append("RUNNING — sweep active")
    elif DEPTH_LOCK.exists() and not paused:
        L.append("STALLED — depth lock present but orchestrator PID is dead (crashed run). "
                 "The next scheduled run self-heals the lock; or resume now.")
    elif not paused:
        L.append("idle — no sweep running")

    # scheduled-task timer
    tstate, tnext, tlast = _task_info()
    if tstate is None:
        L.append("schedule: RS2-Depth-Orchestrator NOT registered (run register_depth_task.ps1). "
                 "Auto-runs are OFF.")
    elif paused:
        L.append(f"schedule: task {tstate} but PAUSED — scheduled runs exit immediately until resume.")
    else:
        L.append(f"schedule: task {tstate} | next auto-run {tnext or '—'} | last run {tlast or '—'}")

    # verdict tallies
    ok = [t for t, r in dstate.items() if r.get("ok")]
    bad = [t for t, r in dstate.items() if not r.get("ok")]
    verdicts = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                verdicts[v["ticker"]] = v
            except Exception:
                pass
    L.append(f"   done {len(ok)} | failed {len(bad)} | verdicts on file {len(verdicts)}")
    if bad:
        L.append("   failed: " + ", ".join(
            f"{t}({dstate[t].get('why', '?')})" for t in bad[:6]))

    # current work: the newest validly-named consensus dir without a verdict; during research/enrich
    # no consensus dir exists yet, so fall back to the freshest research brief to name the ticker.
    _dirpat = re.compile(r"^([A-Z0-9.\-]+)_(\d{8}_\d{6})$")
    cdirs = [(m.group(1), m.group(2), d)
             for d in (HERE / "ab_reports" / "consensus").glob("*_*")
             if (m := _dirpat.match(d.name))]
    cdirs.sort(key=lambda x: x[1], reverse=True)
    cur = next(((t, d) for t, _ts, d in cdirs
                if not (d / "verdict_depth.json").exists()), None)
    if alive:
        if cur:
            t, d = cur
            n_done = len([f for f in d.glob("sample*.md")
                          if re.match(r"sample\d+\.md$", f.name)])
            newest = max((f.stat().st_mtime for f in d.rglob("*") if f.is_file()), default=None)
            mins = f"{int((datetime.now().timestamp() - newest) / 60)}" if newest else "?"
            L.append(f"   NOW: {t} - sample {min(n_done + 1, 3)}/3 on the GPU "
                     f"({mins} min since last artifact; ~36 min/sample with tools)")
        else:
            briefs = sorted((HERE / "research").glob("*.md"),
                            key=lambda f: f.stat().st_mtime, reverse=True)
            if briefs and (datetime.now().timestamp() - briefs[0].stat().st_mtime) < 3600:
                L.append(f"   NOW: {briefs[0].stem} - research/enrich phase "
                         f"(brief updated {int((datetime.now().timestamp() - briefs[0].stat().st_mtime)/60)} min ago)")
            else:
                L.append("   NOW: between tickers (no active consensus dir)")

    # live activity: newest artifacts across the depth working set — a true liveness signal,
    # independent of any log (works for a sweep started before the log file existed)
    events = []
    for t, _ts, d in cdirs[:6]:
        for f in d.rglob("*"):
            if f.is_file():
                events.append((f.stat().st_mtime, t, f.name))
    for f in (HERE / "research").glob("*.md"):
        events.append((f.stat().st_mtime, f.stem, "research brief"))
    events.sort(reverse=True)
    if events:
        L.append("   live activity (newest artifacts):")
        for mt, t, name in events[:6]:
            L.append(f"     {datetime.fromtimestamp(mt).strftime('%m-%d %H:%M')}  {t:6s} {name}")
    if DEPTH_LOG.exists():
        tail = DEPTH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-4:]
        L.append("   orchestrator log tail:")
        for ln in tail:
            L.append(f"     {ln[:100]}")

    recent = sorted(verdicts.values(), key=lambda v: v.get("date", ""), reverse=True)[:5]
    for v in recent:
        band = (f"${v['iv_band_low']}-${v['iv_band_high']}"
                if v.get("iv_band_low") is not None else "n/a")
        L.append(f"   {v['ticker']:6s} {v['direction']:12s} band {band:>16s} vs ${v.get('price')}"
                 f" | spread {v.get('spread_pct')}% | {v.get('size_hint')}")

    # THIS SWEEP's queue + what's pending (NOT book-minus-done — the book is trigger-driven now,
    # and most names already carry a verdict from the cloud baseline, so "book minus locally-run"
    # overstated the work by ~130. The real remaining number is the due queue.)
    sp = _sweep_progress()
    # per-ticker rate, MEASURED from the log (current model only), never hardcoded.
    MTP_SWITCH = datetime(2026, 8, 24, 9, 0)   # the switch nearly halved run times; don't pool eras
    mins = []
    if DEPTH_LOG.exists():
        marks = re.findall(r"\[depth-orch (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+\[\d+/\d+\]",
                           DEPTH_LOG.read_text(encoding="utf-8", errors="replace"))
        for a, b in zip(marks, marks[1:]):
            start = datetime.strptime(a, "%Y-%m-%d %H:%M:%S")
            gap = (datetime.strptime(b, "%Y-%m-%d %H:%M:%S") - start).total_seconds() / 60
            if 20 < gap < 240 and start >= MTP_SWITCH:   # exclude failures, idle gaps, old model
                mins.append(gap)
    mins.sort()
    rate = mins[len(mins) // 2] if len(mins) >= 3 else 70.0
    src = f"median of {len(mins)} runs" if len(mins) >= 3 else "estimate"
    if sp and sp["total"]:
        pending_n = max(0, sp["total"] - sp["idx"])
        L.append(f"   sweep: {sp['idx']}/{sp['total']}"
                 + (f" · now {sp['current']}" if sp.get("current") else "")
                 + f" · {pending_n} pending")
        if sp["pending"]:
            shown = sp["pending"][:12]
            L.append("   pending: " + ", ".join(shown)
                     + (f"  (+{pending_n - len(shown)} more)" if pending_n > len(shown) else ""))
        elif pending_n:
            L.append(f"   pending: {pending_n} names (list not in log — next sweep shows them)")
        L.append(f"   ETA this sweep: ~{pending_n} x {rate:.0f} min ({src}) = "
                 f"{pending_n * rate / 60:.1f} GPU-hours")
    else:
        L.append(f"   no sweep queued (idle). {len(verdicts)} verdicts on file; run `start` to "
                 f"build the due queue. [{rate:.0f} min/name, {src}]")
    L.append("")
    return chr(10).join(L)


FOOTER = ("  commands (type letter/word, press ENTER):   g=start(run now)   p=pause(graceful)   "
          "r=resume   s=stop(graceful + free GPU)   f or bare ENTER=refresh   q=quit")


def interactive(refresh=15):
    """Live dashboard. Commands are TWO-STAGE: type the letter, then press ENTER to execute — so a
    stray keystroke on the wrong window can't halt a run (operator report 2026-08-15). Auto-refresh
    every `refresh`s; a half-typed buffer survives the redraw."""
    try:
        import msvcrt
    except ImportError:
        print(depth_snapshot())
        print("\n(interactive input is Windows-only — use: python status.py pause|resume|stop)")
        return
    msg = ""
    buf = ""

    def render():
        os.system("cls" if os.name == "nt" else "clear")
        print(depth_snapshot())
        print()
        if msg:
            print(f"  » {msg}\n")
        print(FOOTER)
        print(f"  command> {buf}", end="", flush=True)

    render()
    last = time.time()
    while True:
        if msvcrt.kbhit():
            raw = msvcrt.getch()
            if raw in (b"\x00", b"\xe0"):     # arrow / function key -> discard 2nd byte, ignore
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
                elif cmd == "p":
                    print("\n  working: requesting graceful pause...", flush=True)
                    msg = do_pause(); render(); last = time.time()
                elif cmd == "r":
                    msg = do_resume(); render(); last = time.time()
                elif cmd == "s":
                    print("\n  working: requesting graceful stop...", flush=True)
                    msg = do_stop(); render(); last = time.time()
                elif cmd in ("", "f"):
                    msg = ""; render(); last = time.time()
                else:
                    msg = f"unknown command {cmd!r} — g / p / r / s / f / q, then ENTER"
                    render(); last = time.time()
            elif raw == b"\x08":              # backspace — edit the pending buffer
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
