"""PREREG B3b v1.0 (stocks-workspace docs/review_2026-11-03/PREREG_flags_b3b_v1.0.md): the material_events read of every selected name
of the four archival cohorts, one run per packet, into its own root cache/m3m_flags (the live cache/m3m gains no archival run).

    python tools/archival_flags/flags_run.py run [--limit N]     the reads, cohort after cohort; resumable
    python tools/archival_flags/flags_run.py status              slots done and left, counted from the ledger

Reads only each cohort's pool.json (the names whose `stage` is null) and its packet cache/m3m/packets/<TICKER>_<T>.json; no file of the
cohort valuation run is opened. A name is a SLOT (ticker, T). A slot whose run was judged (ledger status complete or
analysis_incomplete) is never read again; a `failed` run (a runner exception or the server: no reply was judged) STOPS the pass with exit 7
and that slot is read again on the next pass. cache/flags_stop.flag stops the pass after the current name (exit 5). Between 05:40 and
08:30 local the pass waits: the holdings monitor's morning run has the GPU. Paper research only.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
import book_paths  # noqa: E402
from qwen_c import runner  # noqa: E402

COHORTS = ("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
TASKS = ["material_events"]
SEED = 1000
OUT = ROOT / "cache" / "m3m_flags"
PACKETS = ROOT / "cache" / "m3m" / "packets"
STOP = ROOT / "cache" / "flags_stop.flag"
JUDGED = ("complete", "analysis_incomplete")
QUIET = ((5, 40), (8, 30))                     # local time: the holdings monitor's morning window


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


def judged():
    """{(ticker, T)} of the slots whose run was judged, from the ledger."""
    led = OUT / "ledger.jsonl"
    rows = [json.loads(x) for x in led.read_text(encoding="utf-8").splitlines() if x.strip()] if led.exists() else []
    return {(r["ticker"], r["T"]) for r in rows if r.get("status") in JUDGED}


def quiet_now():
    t = datetime.now()
    return QUIET[0] <= (t.hour, t.minute) < QUIET[1]


def status():
    done, all_ = judged(), slots()
    have = [s for s in all_ if s[2] is not None]
    print(json.dumps({"slots": len(all_), "no_packet": [f"{t}@{T[:10]}" for T, t, p in all_ if p is None],
                      "judged": sum((t, T) in done for T, t, _ in have), "left": sum((t, T) not in done for T, t, _ in have)}, indent=1))
    return 0


def run(limit):
    runner.M3M_DIR = OUT
    done, n = judged(), 0
    for T, ticker, packet in slots():
        if packet is None or (ticker, T) in done:
            continue
        if limit is not None and n >= limit:
            break
        if STOP.exists():
            log("stop flag: the pass ends")
            return 5
        while quiet_now():
            time.sleep(300)
        t0 = time.time()
        try:
            res = runner.run(str(packet), seed=SEED, task_ids=TASKS)
        except runner.RunRefused as e:
            log(f"{ticker} {T[:10]} REFUSED by the runner: {e}; the pass stops")
            return 7
        n += 1
        log(f"{ticker} {T[:10]} {res['status']} {round(time.time() - t0)} s {res['run_id']}")
        if res["status"] not in JUDGED:
            log("a run failed without a judged reply (code or server): the pass stops; this slot is read again on the next pass")
            return 7
    log(f"pass done: {n} read")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--limit", type=int)
    sub.add_parser("status")
    a = ap.parse_args()
    sys.exit(status() if a.cmd == "status" else run(a.limit))
