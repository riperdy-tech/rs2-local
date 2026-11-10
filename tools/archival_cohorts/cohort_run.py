"""cohort_run.py - the packets and valuations of one PREREG_cohorts_nextq cohort.

    python tools/archival_cohorts/cohort_run.py packets --t T
    python tools/archival_cohorts/cohort_run.py run --t T [--limit N] [--ticker X] [--continue-from <commit>]

Directory: <books>/m3o/value/archival_cohort_<T>/ (pool.json from pool_cohort.py; coe_pinned/ from pin_coe.py). Index: runs.json there
(packets) and slots.json (valuations), J2's schemas.
- packets: one archival_sec_only_v1 packet per pool name that passed every stage, as K2's (SEC online under the standing approval).
  A name already packed by K2 at the same T (archival_2025-10-01/runs.json) reuses K2's packet entry, which is checked against its
  sha256 (PREREG section 5 item 2). packet.save never overwrites a packet with other bytes; that is recorded as refused.
- run: J2's runner unchanged (j2_run.run: a clean tree, one commit, a stop on any crash, engine_defect or unpinned cost of
  equity, cache/j2_yield.flag between slots) at SEEDS (1200, 3200). Those seeds are new: the runner moves an existing run
  directory aside, and S1b's seeds 1000/3000 and the greedy check's 1100/3100 runs are recorded by path. A commit to rs2-local
  during a run stops it at the next slot (j2_run compares each result's commit with HEAD).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "tools" / "archival_j2"), str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import j2_run as J  # noqa: E402
from qwen_c import packet, sec_store  # noqa: E402

SEEDS = (1200, 3200)
VALUE = book_paths.books() / "m3o" / "value"
K2_RUNS = VALUE / "archival_2025-10-01" / "runs.json"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def census(raw):
    body = json.loads(raw)
    return {"T": body["T"], "pool": [n for n in body["names"] if n.get("stage") is None]}


def k2_entry(t, T):
    """K2's packet entry for ticker t when K2 packed it at the same T and its bytes still recompute; else None."""
    if not K2_RUNS.exists():
        return None
    e = (json.loads(K2_RUNS.read_text(encoding="utf-8"))["packets"]).get(t) or {}
    if not e.get("packet"):
        return None
    src = Path(e["packet"]).read_bytes()
    if sha(src) != e["packet_sha256"] or json.loads(src.decode("utf-8"))["decision_time_utc"][:10] != T[:10]:
        return None
    return dict(e, reused_from="archival_2025-10-01")


def packets(d, pool, idx):
    for n in pool["pool"]:
        t = n["ticker"]
        if t in idx["packets"]:
            continue
        e = k2_entry(t, pool["T"])
        if e is None:
            try:
                pk = packet.build(t, pool["T"], None, online=True, regime=packet.REGIME_SEC_ONLY, cik=n["cik"], s0_row=n["s0_row"])
                path = packet.save(pk)
                e = {"packet": str(path), "packet_sha256": sha(path.read_bytes()), "annotations": pk.get("annotations")}
            except (packet.PacketRefused, packet.PacketError, sec_store.StoreError) as ex:
                if isinstance(ex, sec_store.StoreError) and "larger than" not in str(ex):
                    raise                               # a network failure stops the pass (resumable); only the size cap is final
                e = {"packet": None, "refused": f"{type(ex).__name__}: {ex}"[:600]}
        idx["packets"][t] = e
        J.save(d / "runs.json", idx)
        print(t, "reused" if e.get("reused_from") else ("packet" if e.get("packet") else "refused"), flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("phase", choices=("packets", "run"))
    ap.add_argument("--t", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
    ap.add_argument("--continue-from")
    a = ap.parse_args(argv)
    d = VALUE / f"archival_cohort_{a.t}"
    raw = (d / "pool.json").read_bytes()
    pool = census(raw)
    if pool["T"][:10] != a.t:
        sys.exit(f"STOP: {d / 'pool.json'} is for T {pool['T']}, not {a.t}")
    if not (d / "coe_pinned" / "manifest.json").exists():
        sys.exit(f"STOP: no pinned cost of equity in {d / 'coe_pinned'}")
    path = d / "runs.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"pool_sha256": sha(raw), "packets": {}, "slots": {}, "git": None}
    if idx["pool_sha256"] != sha(raw):
        sys.exit("STOP: pool.json changed since the index began")
    if a.phase == "packets":
        return packets(d, pool, idx)
    J.DIR, J.SEEDS = d, SEEDS
    return J.run(pool, a.limit, a.ticker, a.continue_from)


if __name__ == "__main__":
    sys.exit(main())
