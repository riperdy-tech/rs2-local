"""k2_run.py - K2-3/K2-4 (K2 v0.2): the packets and valuations of the K2 pool at T 2025-10-01.

    python tools/archival_k2/k2_run.py packets
    python tools/archival_k2/k2_run.py run [--limit N] [--ticker X] [--continue-from <commit>]

Pool: <books>/m3o/value/archival_2025-10-01/pool.json (pool_k2.py); the census is its names that passed every stage. Index: runs.json
beside it (packets) and slots.json (valuations), J2's schemas.
- packets: one archival_sec_only_v1 packet per pool name (builder v9: the pool's S0 row, the name's CIK; SEC online under the standing
  approval). A refusal is recorded with its reason and that name gets no valuation. Only after PREREG amendment 5 is frozen.
- run: J2's runner unchanged (tools/archival_j2/j2_run.run: seeds 1000 and 3000, a clean tree, the commit of the first valuation,
  a stop on any crash, engine_defect or unpinned cost of equity), pointed at this directory, with J2's pinned cost-of-equity set copied
  here as coe_pinned/ (K2 v0.2 ruling 3; coe.py checks it against its manifest on every call). GPU: only inside a window agreed with
  the "F03 benchmark workflows" session; cache/j2_yield.flag stops the pass at the next slot.
"""
import argparse
import hashlib
import json
import shutil
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

DIR = book_paths.books() / "m3o" / "value" / "archival_2025-10-01"
J2_COE = book_paths.books() / "m3o" / "value" / "archival_2025-12-31" / "coe_pinned"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def census(raw):
    """J2's pool shape: the names that passed every stage, with cik, sector, market_cap, family and the S0 row."""
    body = json.loads(raw)
    return {"T": body["T"], "pool": [n for n in body["names"] if n.get("stage") is None]}


def packets(pool, idx):
    for n in pool["pool"]:
        t = n["ticker"]
        if t in idx["packets"]:
            continue
        try:
            pk = packet.build(t, pool["T"], None, online=True, regime=packet.REGIME_SEC_ONLY, cik=n["cik"], s0_row=n["s0_row"])
            path = packet.save(pk)
            idx["packets"][t] = {"packet": str(path), "packet_sha256": sha(path.read_bytes()), "annotations": pk.get("annotations")}
        except (packet.PacketRefused, packet.PacketError, sec_store.StoreError) as e:
            if isinstance(e, sec_store.StoreError) and "larger than" not in str(e):
                raise                                   # a network failure stops the pass (resumable); only the size cap is final (J2's CRI)
            idx["packets"][t] = {"packet": None, "refused": f"{type(e).__name__}: {e}"[:600]}
        J.save(DIR / "runs.json", idx)
        print(t, "packet" if idx["packets"][t]["packet"] else "refused", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("packets", "run"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
    ap.add_argument("--continue-from")
    a = ap.parse_args()
    raw = (DIR / "pool.json").read_bytes()
    pool = census(raw)
    path = DIR / "runs.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"pool_sha256": sha(raw), "packets": {}, "slots": {}, "git": None}
    if idx["pool_sha256"] != sha(raw):
        sys.exit("STOP: pool.json changed since the index began")
    if not (DIR / "coe_pinned").exists():
        shutil.copytree(J2_COE, DIR / "coe_pinned")
    if a.phase == "packets":
        return packets(pool, idx)
    J.DIR = DIR
    return J.run(pool, a.limit, a.ticker, a.continue_from)


if __name__ == "__main__":
    sys.exit(main())
