"""formation_run_cloud.py - the month-end formation read by the cloud reader (plan M5, WO_formation_cloud_reader 2026-11-20): the same map, packets and
bookkeeping as formation_run.py, with Gemini (Claude Sonnet when Gemini's allowance is under its floor) answering in Qwen's place.

    python tools/paper_books/formation_run_cloud.py [--map <formation_<T>.json>] [--limit N] [--dry-run]

Per name in state `to_run` or `pending` (ticker order) one qwen_c run of the `material_events` task ONLY (the book rule reads nothing else; ruling 2),
seed base 1000, thinking high (the runner enforces it), into cache/m3m_formation/ (its own run root and ledger: no site-worker cleanup touches it;
never delete it). The model call is swapped in this process exactly as the site worker does (gemini_ondemand.swap); the arm is chosen per name by
the worker's own rule (gemini_ondemand.choose_arm). A run with the task ok is `complete` (the runner's status is `complete`, so no partial_analysis);
any other is retried once (formation_run.settle, MAX_ATTEMPTS 2), then `analysis_incomplete`. Each name records `reader` (the model) and each
`runs` entry too; the run's manifest holds it in model.tag.
No GPU, no ollama. Takes the site worker's lock (cache/gemini_site/worker.lock), so it never runs beside a worker read. Exit 0 done (or the lock is
held); 3 allowance under its floor (both arms), the unread names are left as they were and a later start resumes. The finished flag
(cache/paper_books/formation/finished_<T>.flag, as formation_run) is written when no limit was given and no name is left.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "site"))
import formation_run as FR  # noqa: E402
import gemini_ondemand as G  # noqa: E402
from qwen_c import runner  # noqa: E402

RUNS = ROOT / "cache" / "m3m_formation"                                  # the cloud formation's own run root (gitignored cache)
TASK = "material_events"
SEED = 1000
HOME = "gemini"


class AllowanceStop(BaseException):
    """Not an Exception: the runner turns any Exception in a task into an infra_error status, and a stop is no result."""


def newest_map():
    """The live map of the newest formation: formation_<date>.json, not frozen, not retrospective (as formation_waiting reads the live maps)."""
    live = []
    for f in sorted(FR.INPUTS.glob("formation_*.json")):
        if re.fullmatch(r"formation_\d{4}-\d{2}-\d{2}\.json", f.name) and not f.with_name(f"{f.stem}.frozen.json").exists():
            if json.loads(f.read_text(encoding="utf-8")).get("label") != "retrospective":
                live.append(f)
    if not live:
        raise SystemExit(f"STOP: no live formation map in {FR.INPUTS}")
    return live[-1]


def to_read(m, limit):
    return [t for t, n in sorted(m["names"].items()) if n["state"] in ("to_run", "pending")][:limit]


def stop_at_floor():
    """Stands in for gemini_ondemand.wait_for_quota in this process: after a failed call the worker would sleep to the reset; here the read stops."""
    if G.quota_low():
        raise AllowanceStop("allowance under its floor after a failed call")


def read(t, n):
    """One name's material_events read through the swapped runner; (result dict or {}, error text)."""
    G.swap()                                                                  # per name: the model tag in the manifest follows the arm
    runner.M3M_DIR = RUNS                                                     # swap points a non-gemini arm at cache/m3m_<arm>
    G.STATE["label"] = f"{t}:formation"
    try:
        return runner.run(n["packet"], seed=SEED, task_ids=[TASK]), ""
    except runner.RunRefused as e:
        return {}, f"RunRefused: {e}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    path = a.map or newest_map()
    m = json.loads(path.read_text(encoding="utf-8"))
    if a.dry_run:
        names = to_read(m, a.limit)
        print(f"{path.name}: {len(names)} name(s) would be read ({TASK} only, seed {SEED}, run root {RUNS}): " + ", ".join(names), flush=True)
        return 0
    FR.STATE.mkdir(parents=True, exist_ok=True)
    G.set_arm(HOME)
    if not G.take_lock():
        print("another worker holds the lock", flush=True)
        return 0
    lock = G.LOCK
    saved = G.wait_for_quota
    G.wait_for_quota = stop_at_floor
    try:
        n_run = 0
        for t in to_read(m, None):
            n = m["names"][t]
            if a.limit is not None and n_run >= a.limit:
                break
            G.choose_arm(HOME)
            if G.quota_low():
                print("allowance under its floor on both arms: stopping, a later start resumes", flush=True)
                return 3
            reader = G.GEM_MODEL
            n_run += 1
            t0 = time.time()
            try:
                res, err = read(t, n)
            except AllowanceStop as e:
                print(f"{t}: {e}: stopping, the name is left unread", flush=True)
                return 3
            FR.settle(n, res, 0 if res else 1, time.time() - t0, err)
            n["reader"] = n["runs"][-1]["reader"] = reader
            FR.save(path, m)
            print(t, n["state"], n["runs"][-1]["seconds"], reader, flush=True)
        if a.limit is None and not FR.names_left(m):
            (FR.STATE / f"finished_{m['formation_T']}.flag").write_text("done")
        return 0
    finally:
        G.wait_for_quota = saved
        try:
            if lock.read_text().strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
