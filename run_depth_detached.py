#!/usr/bin/env python3
"""run_depth_detached.py — start the depth sweep as a process that OUTLIVES its launcher.

Why this exists: the sweep is a multi-day job, and until now it ran as a child of whatever
terminal or agent session started it. Closing that session, or cancelling the background task,
killed the sweep mid-ticker (this happened twice on 2026-08-24). A 140-ticker run must not depend
on a chat window staying open.

DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP means the child gets no console and no process-group
membership, so neither closing the parent nor Ctrl-C in it reaches the sweep. Output goes to
reports/_depth_sweep.log; the orchestrator's own cache/depth_orchestrate.log keeps working too.

CONTROL, unchanged and deliberately file-based so it works from anywhere without finding a PID:
    stop   ->  create  cache/DEPTH_PAUSED      (halts cleanly at the next ticker boundary)
    resume ->  delete it, then run this again
    status ->  python status.py
    kill   ->  python run_depth_detached.py --stop      (pause + wait, the graceful path)

  python run_depth_detached.py            start detached
  python run_depth_detached.py --status   is it running?
  python run_depth_detached.py --stop     ask it to stop at the next boundary
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = HERE / "cache" / "orchestrate_depth.lock"
PAUSED = HERE / "cache" / "DEPTH_PAUSED"
LOG = HERE / "reports" / "_depth_sweep.log"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def lock_pid():
    try:
        return int(json.loads(LOCK.read_text()).get("pid", 0))
    except Exception:
        return None


def alive(pid):
    if not pid:
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                         capture_output=True, text=True).stdout
    return str(pid) in out


def status():
    pid = lock_pid()
    if LOCK.exists() and alive(pid):
        print(f"RUNNING detached, pid {pid}")
    elif LOCK.exists():
        print(f"STALE LOCK — pid {pid} is dead. Safe to start; the lock will be taken over.")
    else:
        print("not running")
    if PAUSED.exists():
        print(f"DEPTH_PAUSED is set — it will stop at the next ticker boundary "
              f"({PAUSED.read_text(encoding='utf-8', errors='replace').strip()[:60]})")
    print(f"log: {LOG}")
    return 0


def stop():
    """Graceful: ask for a boundary stop and wait, rather than killing mid-ticker. A kill would
    waste the ~40-70 min already spent on the current name and leave a half-written run dir."""
    PAUSED.write_text(f"stopped via run_depth_detached at "
                      f"{datetime.now():%Y-%m-%d %H:%M}\n", encoding="utf-8")
    pid = lock_pid()
    print("DEPTH_PAUSED set — waiting for the current ticker to finish "
          "(this can take up to ~70 min; the run in flight is not discarded).")
    for _ in range(300):                      # up to ~50 min of polling
        if not alive(pid):
            print("sweep exited cleanly.")
            return 0
        time.sleep(10)
    print(f"still running after the wait; pid {pid} — leave DEPTH_PAUSED in place, it will exit "
          f"at the boundary.")
    return 1


def start():
    pid = lock_pid()
    if LOCK.exists() and alive(pid):
        print(f"already running, pid {pid} — nothing to do. Use --stop first if you want to "
              f"restart it.")
        return 1
    if PAUSED.exists():
        PAUSED.unlink()
        print("cleared DEPTH_PAUSED")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    fh = LOG.open("a", encoding="utf-8", errors="replace")
    fh.write(f"\n{'='*70}\n[launcher] detached start {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    fh.flush()
    p = subprocess.Popen(
        [sys.executable, str(HERE / "orchestrate_depth.py")],
        stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(HERE),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True)
    print(f"started detached, pid {p.pid}")
    print(f"  log    : {LOG}")
    print(f"  stop   : python run_depth_detached.py --stop")
    print(f"  status : python status.py")
    print("This process now survives closing this session.")
    return 0


if __name__ == "__main__":
    if "--status" in sys.argv:
        sys.exit(status())
    if "--stop" in sys.argv:
        sys.exit(stop())
    sys.exit(start())
