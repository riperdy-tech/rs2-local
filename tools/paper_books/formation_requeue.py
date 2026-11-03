"""formation_requeue.py - WO_O2 step 5: re-queue a formation whose decision run changed (a later verified run before the fill open).

    python tools/paper_books/formation_requeue.py 2026-10-30

Run check_new_runs.py first, and launch this detached (Start-Process), not as a child of a session. Nothing is deleted or
overwritten (CROSS_CHECK_Q7 4, 12; Q7b 1, 2):
1. A fresh start needs forward_ledger.decision_for to give a verified run different from the map's, with a check_new_runs record
   (formation_decide.check_file); otherwise nothing changes.
2. preempt.flag (cache/paper_books/formation/) is written, so a retrospective or E3 pass yields the GPU after its current run (formation_run.formation_waiting), and
   the runner lock is awaited (up to WAIT_S).
3. Holding the lock throughout, in this process (formation_decide and formation_packets are called in-process, so the lock's pid is the one doing
   the work): the current map is moved aside as formation_<T>_superseded_<run_id>.json, the finished flag (if any) becomes
   finished_<T>_superseded_<run_id>.flag, formation_decide writes the new map and formation_packets builds its packets.
4. The preempt flag is removed only when no name is left to_build; the lock is then released.
A rerun after an interruption resumes: a map with to_build names gets its packets; a missing map beside any superseded map
gets formation_decide (at the current decision) then its packets; a complete map is compared with the decision again (moved aside if it is still the old run). A stop leaves the preempt flag, so nothing else takes the GPU
before a human looks.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forward_ledger as FL  # noqa: E402
import formation_decide  # noqa: E402
import formation_packets  # noqa: E402
import formation_run as R  # noqa: E402

WAIT_S = 4 * 3600                                                         # a retrospective run can take 8 tasks x 30 min (Q7b 11)


def call(mod, T):
    argv, sys.argv = sys.argv, [mod.__file__, T]
    try:
        rc = mod.main()
    except SystemExit as e:
        rc = e.code
    finally:
        sys.argv = argv
    if rc not in (0, None):
        sys.exit(f"STOP: {mod.__name__} stopped: {rc}; preempt.flag stays")


def to_build(path):
    return path.exists() and any(n["state"] == "to_build" for n in json.loads(path.read_text(encoding="utf-8"))["names"].values())


def main():
    T = sys.argv[1]
    path = R.INPUTS / f"formation_{T}.json"
    pre = R.STATE / "preempt.flag"
    superseded = sorted(R.INPUTS.glob(f"formation_{T}_superseded_*.json"))
    move = False
    if path.exists() and not to_build(path):
        old = json.loads(path.read_text(encoding="utf-8"))
        res, _, err = FL.decision_for(date.fromisoformat(T), FL.scoring_runs())
        if err:
            sys.exit(f"STOP: {err}")
        if res["run_id"] == old["run_id"]:
            if pre.exists():
                pre.unlink()                                              # an earlier pass finished the work
            print(f"unchanged: the decision run is {old['run_id']}; nothing to re-queue")
            return 0
        if formation_decide.check_file(res["output_commit"]) is None:
            sys.exit(f"STOP: no check_new_runs record verifies {res['output_commit']}; run check_new_runs.py first")
        move = True
    elif not path.exists() and not superseded:
        sys.exit(f"STOP: no {path.name} and no superseded map; recover by hand")   # a missing map beside any superseded one is resumed
    R.STATE.mkdir(parents=True, exist_ok=True)
    if not pre.exists():
        pre.write_text(f"formation_requeue {T}")
    t0 = time.time()
    while not R.take_lock():
        if time.time() - t0 > WAIT_S:
            sys.exit("STOP: the runner lock was not free within WAIT_S; preempt.flag stays")
        print("waiting for the runner lock", flush=True)
        time.sleep(60)
    try:
        if move:                                                          # Q7c 1: re-read under the lock
            old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            if old is not None and old["run_id"] == res["run_id"]:
                move = False                                              # another pass already re-queued to this run
        if move:
            aside = path.with_name(f"formation_{T}_superseded_{old['run_id']}.json")
            if aside.exists():
                sys.exit(f"STOP: {aside.name} exists")
            flag = R.STATE / f"finished_{T}.flag"
            if flag.exists():                                             # Q7c 2: the flag first, so a kill never strands it
                flag.rename(R.STATE / f"finished_{T}_superseded_{old['run_id']}.flag")
            path.rename(aside)
            print("moved aside:", aside.name, flush=True)
        if not path.exists():
            call(formation_decide, T)
        call(formation_packets, T)
        new = json.loads(path.read_text(encoding="utf-8"))
        if to_build(path):
            sys.exit("STOP: names are still to_build after formation_packets; preempt.flag stays")
        if (R.STATE / f"finished_{T}.flag").exists() and any(n["state"] in ("to_run", "pending") for n in new["names"].values()):
            (R.STATE / f"finished_{T}.flag").rename(R.STATE / f"finished_{T}_stale_{new['run_id']}.flag")   # Q7c 2: never strand a batch
        olds = sorted(R.INPUTS.glob(f"formation_{T}_superseded_*.json"))
        print(json.dumps({"superseded": [o.name for o in olds], "run": new["run_id"], "T": new["decision_time_utc"],
                          "states": {s: sum(n["state"] == s for n in new["names"].values()) for s in {n["state"] for n in new["names"].values()}}}))
        pre.unlink()                                                      # our own marker file, not data
    finally:
        R.release_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
