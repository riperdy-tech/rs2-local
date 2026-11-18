"""PREREG B3b v1.0 with amendment 1 (stocks-workspace docs/review_2026-11-03/PREREG_flags_b3b_v1.0.md and ..._amendment1.md): the
material_events read of every selected name of the four archival cohorts, one run per packet, into its own root cache/m3m_flags_high
(amendment 3: at high thinking, runner.THINK; the live cache/m3m gains no archival run).

    python tools/archival_flags/flags_run.py run [--limit N]     the reads, cohort after cohort; resumable
    python tools/archival_flags/flags_run.py status              slots by state, counted from the runs themselves
    python tools/archival_flags/flags_run.py reread              after the pass: the one re-read of a slot cut twice at the allowance

Reads only each cohort's pool.json (the names whose `stage` is null) and its packet cache/m3m/packets/<TICKER>_<T>.json; no file of the
cohort valuation run is opened. A name is a SLOT (ticker, T). Its state comes from its newest finished run's material_events status
(the run's manifest; with one requested task the run status is only `complete` or `failed`):
  ok                           a read
  malformed, context_overflow  no_read: the model answered and the answer cannot be used. Never read again (same seeds, same answer)
  timeout, infra_error         not a read (the server or the connection): the pass STOPS, exit 7, and the slot is read again next pass
A crashed run (no finished manifest) is read again. The pass also stops when the tree of qwen_c/ at HEAD changes under it (exit 6), when
cache/flags_stop.flag exists (exit 5), or when another pass holds the root's run.lock (exit 4). Before each slot it waits while the
holdings monitor could have the GPU (05:40 to 10:30 local, or its executor lock is held by a live process), while a live formation waits
(formation_run.formation_waiting), and through a runner refusal such as gpu_busy (up to an hour). Paper research only.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
import book_paths  # noqa: E402
import formation_run as FR  # noqa: E402
from qwen_c import runner  # noqa: E402

COHORTS = ("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
TASK = "material_events"
SEED = 1000
OUT = ROOT / "cache" / "m3m_flags_high"      # amendment 3 (2026-11-19): the pass is read at high thinking into a fresh root; cache/m3m_flags holds the
#                                             240 reads made at medium before the level was fixed: void, kept, never scored
PACKETS = ROOT / "cache" / "m3m" / "packets"
STOP = ROOT / "cache" / "flags_stop.flag"
LOCK = OUT / "run.lock"
FINAL = {"ok": "read", "malformed": "no_read", "context_overflow": "no_read"}       # a task status not here is not final: read again
QUIET = ((5, 40), (10, 30))                    # local time: the holdings monitor's morning run (it ended 10:10 and 10:17 on its first days)
REFUSAL_WAIT_S, REFUSAL_TRIES = 300, 12
INFRA_TRIES = 3                                # amendment 3: a slot stopped by the server or the clock this many times is a no_read


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def slots():
    """[(T, ticker, packet path or None)] in cohort order, then pool order."""
    out = []
    for d in COHORTS:
        pool = json.loads((book_paths.books() / "m3o" / "value" / f"archival_cohort_{d}" / "pool.json").read_text(encoding="utf-8"))
        stamp = pool["T"].replace("-", "").replace(":", "")
        for n in pool["names"]:
            if n.get("stage") is None:
                p = PACKETS / f"{n['ticker']}_{stamp}.json"
                out.append((pool["T"], n["ticker"], p if p.exists() else None))
    return out


def task_status(run_id):
    """The material_events status in a finished run's manifest; None when it cannot be read."""
    try:
        man = json.loads((OUT / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (man.get("options") or {}).get("think") != runner.THINK:
        return None                             # amendment 3: a run at another thinking level is no read of this pass
    return ((man.get("tasks") or {}).get(TASK) or {}).get("status")


def final_runs():
    """{(ticker, T): (state, run_id)}, state "read" | "no_read", for the slots with a final run (the newest in ledger order).
    runner.read_ledger: a torn ledger line or a run the ledger does not list is handled there; a crashed run leaves the slot open. A
    slot whose runs ended timeout or infra_error INFRA_TRIES times and that has no final run is a no_read (amendment 3: it cannot hold
    the scoring open for ever); its run_id is the last such run."""
    out, fails = {}, {}
    for r in runner.read_ledger(OUT):
        if r.get("run_id") and r.get("status") in ("complete", "failed"):
            key, raw = (r["ticker"], r["T"]), task_status(r["run_id"])
            if FINAL.get(raw):
                out[key] = (FINAL[raw], r["run_id"])
            elif raw in ("timeout", "infra_error"):
                fails.setdefault(key, []).append(r["run_id"])
    for key, runs in fails.items():
        if key not in out and len(runs) >= INFRA_TRIES:
            out[key] = ("no_read", runs[-1])
    return out


def states():
    """{(ticker, T): "read" | "no_read"} for the slots with a final run (final_runs)."""
    return {k: v[0] for k, v in final_runs().items()}


def qwen_tree():
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD:qwen_c"], capture_output=True, text=True).stdout.strip()


def monitor_has_gpu():
    t = datetime.now()
    if QUIET[0] <= (t.hour, t.minute) < QUIET[1]:
        return True
    lock = book_paths.books() / "monitor" / "state" / "executor.lock"
    try:
        return FR.pid_alive(int(lock.read_text().strip()))
    except (OSError, ValueError):
        return False


def take_lock():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        if FR.pid_alive(int(LOCK.read_text().strip())):
            return False
    except (OSError, ValueError):
        pass
    LOCK.write_text(str(os.getpid()))
    return True


def status():
    st, all_ = states(), slots()
    have = [(T, t) for T, t, p in all_ if p is not None]
    print(json.dumps({"slots": len(all_), "no_packet": [f"{t}@{T[:10]}" for T, t, p in all_ if p is None],
                      "read": sum(st.get((t, T)) == "read" for T, t in have), "no_read": sum(st.get((t, T)) == "no_read" for T, t in have),
                      "left": sum((t, T) not in st for T, t in have)}, indent=1))
    return 0


def run(limit):
    if not take_lock():
        log("another pass holds the lock")
        return 4
    try:
        runner.M3M_DIR = OUT
        tree, done, n = qwen_tree(), states(), 0
        log(f"pass start: qwen_c tree {tree[:12]}, {len(done)} slots final")
        for T, ticker, packet in slots():
            if packet is None or (ticker, T) in done:
                continue
            if limit is not None and n >= limit:
                break
            if STOP.exists():
                log("stop flag: the pass ends")
                return 5
            while monitor_has_gpu() or FR.formation_waiting():
                time.sleep(300)
            if qwen_tree() != tree:
                log("qwen_c changed at HEAD under this pass: the pass stops; start it again to read at the new code")
                return 6
            t0, res = time.time(), None
            for _ in range(REFUSAL_TRIES):
                try:
                    res = runner.run(str(packet), seed=SEED, task_ids=[TASK])
                    break
                except runner.RunRefused as e:
                    log(f"{ticker} {T[:10]} refused by the runner: {e}; waiting")
                    time.sleep(REFUSAL_WAIT_S)
            if res is None:
                log("the runner refused for an hour: the pass stops")
                return 7
            n += 1
            ts = task_status(res["run_id"])
            log(f"{ticker} {T[:10]} {FINAL.get(ts, 'NOT FINAL')} ({ts}) {round(time.time() - t0)} s {res['run_id']}")
            if ts not in FINAL:
                log("the server or the connection failed, no reply to judge: the pass stops; this slot is read again on the next pass")
                return 7
        log(f"pass done: {n} run")
        return 0
    finally:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()


def cut_twice(run_id):
    """The rendered prompt's characters when the run made two attempts and each was cut at the allowance (malformed, done_reason
    length); else None. Decided by done_reason alone (amendment 3, section B)."""
    d = OUT / "runs" / run_id
    raws = sorted((d / "raw").glob(f"{TASK}_*.json"))
    if len(raws) < 2:
        return None
    for f in raws:
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("outcome") != "malformed" or (r.get("response") or {}).get("done_reason") != "length":
            return None
    return max(len(f.read_text(encoding="utf-8")) for f in (d / "prompts").glob(f"{TASK}*.txt"))


def reread():
    """Amendment 3, section B: after the pass, each no_read slot whose final run was cut at the allowance on both attempts is read once
    more with the allowance the context leaves (num_ctx - ceil(prompt characters / CHARS_PER_TOKEN) - 2048). A slot that already has a
    run at another allowance is not read again. Run before any flag is computed."""
    if not take_lock():
        log("another pass holds the lock")
        return 4
    try:
        runner.M3M_DIR = OUT
        packets, tried = {(t, T): p for T, t, p in slots()}, set()
        for r in runner.read_ledger(OUT):
            try:
                man = json.loads((OUT / "runs" / r["run_id"] / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                continue
            if (man.get("options") or {}).get("num_predict") != runner.NUM_PREDICT:
                tried.add((r["ticker"], r["T"]))
        n = 0
        for key, (state, run_id) in sorted(final_runs().items()):
            chars = cut_twice(run_id) if state == "no_read" and key not in tried else None
            if chars is None:
                continue
            allow = runner.NUM_CTX - math.ceil(chars / runner.CHARS_PER_TOKEN) - 2048
            while monitor_has_gpu() or FR.formation_waiting():
                time.sleep(300)
            res = runner.run(str(packets[key]), seed=SEED, task_ids=[TASK], num_predict=allow)
            n += 1
            log(f"{key[0]} {key[1][:10]} re-read at allowance {allow}: {task_status(res['run_id'])} {res['run_id']}")
        log(f"re-read done: {n} run")
        return 0
    finally:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int)
    sub.add_parser("status")
    sub.add_parser("reread")
    a = ap.parse_args()
    sys.exit(status() if a.cmd == "status" else reread() if a.cmd == "reread" else run(a.limit))
