"""formation_run.py - WO_O2 step 4: one full qwen_c run (all tasks, seed base 1000) per packet of a formation map, through the qwen_c runner (python -m qwen_c.runner, run from this repository's root).

    python tools/paper_books/formation_run.py 2026-10-30 [--limit N] [--ticker X]

Names in state `to_run` (or `pending` after a failed first attempt) are run in ticker order. A run whose `material_events` task is ok
is `complete` (with `partial_analysis` when another task failed: SPEC_m3o A1S); any other run is retried once (MAX_ATTEMPTS 2, as
n5_run.py), and after the second it is `analysis_incomplete`. The runner's own gpu_busy refusal stops the script
(exit 3) without counting an attempt, and the scheduled task tries again. One instance at a time (cache/paper_books/formation/runner.lock). The map is rewritten
after each run; the runs' own records are qwen_c's (cache/m3m/runs, ledger.jsonl), never edited here. cache/paper_books/formation/finished_<T>.flag is written
when no name is left to run.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402

ROOT = HERE.parents[1]                                                    # the rs2-local repo root: qwen_c runs from here
PY = sys.executable
INPUTS = book_paths.books() / "m3o" / "inputs"
STATE = ROOT / "cache" / "paper_books" / "formation"                      # runner lock, flags, logs (gitignored cache)
LOCK = STATE / "runner.lock"
MAX_ATTEMPTS = 2


def ollama_up():
    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=10).read()
        return True
    except Exception:  # noqa: BLE001
        return False


def pid_alive(pid):
    """Whether a process with this pid is running. Not os.kill(pid, 0): on Windows that TERMINATES the process (found by WO_P2's builder;
    copied from m3p_monitor.pid_alive)."""
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, int(pid))                         # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5                            # access denied: it exists
    code = ctypes.c_uint32()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259                              # STILL_ACTIVE


def take_lock():
    """A single-instance lock holding the pid; a lock whose pid is gone is taken over."""
    if LOCK.exists():
        try:
            if pid_alive(int(LOCK.read_text().strip())):
                return False
        except ValueError:
            pass
    LOCK.write_text(str(os.getpid()))
    return True


def formation_waiting(exclude=None):
    """True when a contemporaneous formation map (not retrospective, not superseded, not frozen) has a name still to build, run or
    retry, or preempt.flag exists in the state folder: a lower-priority pass (WO_O3, E3) then yields the GPU (CROSS_CHECK_Q7 10)."""
    import re
    if (STATE / "preempt.flag").exists():
        print("yield: preempt.flag", flush=True)
        return True
    for f in INPUTS.glob("formation_*.json"):
        if f == exclude or not re.fullmatch(r"formation_\d{4}-\d{2}-\d{2}\.json", f.name):     # Q7b 11: live maps only
            continue
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"yield: {f.name} unreadable (being rewritten)", flush=True)
            return True
        if m.get("label") == "retrospective":
            continue
        if any(n.get("state") in ("to_build", "to_run", "pending") for n in m.get("names", {}).values()):
            print(f"yield: {f.name} has work left", flush=True)
            return True
    return False


def save(path, m):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    for i in range(20):                                                   # Q7c 7: a reader can block a replace on Windows
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.5)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("formation_T")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
    a = ap.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    path = INPUTS / f"formation_{a.formation_T}.json"
    if not take_lock():
        print("another runner holds the lock", flush=True)
        return 0
    if not ollama_up():
        print("ollama is not reachable: exiting, the scheduled task retries", flush=True)
        return 4
    m = json.loads(path.read_text(encoding="utf-8"))
    retro = m.get("label") == "retrospective"
    n_run = 0
    for t, n in sorted(m["names"].items()):
        if n["state"] not in ("to_run", "pending") or (a.ticker and t != a.ticker):
            continue
        if a.limit is not None and n_run >= a.limit:
            break
        if retro and formation_waiting(exclude=path):                     # CROSS_CHECK_Q7 10: the formation goes first
            print("a contemporaneous formation has work left: yielding the GPU", flush=True)
            return 5
        n_run += 1
        t0 = time.time()
        r = subprocess.run([PY, "-m", "qwen_c.runner", n["packet"], "--seed-base", "1000"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if "gpu_busy" in (r.stderr + r.stdout):
            print("GPU busy: stopping", flush=True)
            return 3
        try:
            res = json.loads(r.stdout[r.stdout.index("{"):])          # the runner prints its result as indented JSON
        except ValueError:
            res = {}
        n["attempts"] += 1
        n.setdefault("runs", []).append({"run_id": res.get("run_id"), "run_dir": res.get("run_dir"), "status": res.get("status"),
                                         "exit": r.returncode, "seconds": round(time.time() - t0, 1),
                                         "incomplete_tasks": res.get("incomplete_tasks"), "stderr_tail": r.stderr[-400:]})
        me_ok = res.get("status") == "analysis_incomplete" and "material_events" not in (res.get("incomplete_tasks") or {})
        if res.get("status") == "complete":
            n.update(state="complete", run_dir=res["run_dir"])
        elif me_ok:                       # SPEC_m3o A1S: material_events ok is complete (flagged partial_analysis); no GPU retry
            n.update(state="complete", run_dir=res["run_dir"], partial_analysis=True)
        elif n["attempts"] >= MAX_ATTEMPTS:
            n.update(state="analysis_incomplete", reason="runner_attempts", run_dir=res.get("run_dir"))
        else:
            n["state"] = "pending"
        save(path, m)
        print(t, n["state"], n["runs"][-1]["seconds"], flush=True)
    if not a.ticker and a.limit is None and not any(n["state"] in ("to_build", "to_run", "pending") for n in m["names"].values()):   # Q7 4
        (STATE / f"finished_{a.formation_T}.flag").write_text("done")
    return 0


def release_lock():
    """Remove the lock if this process holds it, so a later launch never meets a stale pid (Windows reuses pids)."""
    import os
    try:
        if LOCK is not None and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        release_lock()
    sys.exit(rc)
