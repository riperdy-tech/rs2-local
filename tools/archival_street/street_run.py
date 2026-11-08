"""street_run.py - S1-3 (WO_street_S1_build deliverable 4): the packets and valuations of the S1 pool at T 2026-06-15.

    python tools/archival_street/street_run.py packets
    python tools/archival_street/street_run.py run [--limit N] [--ticker X] [--continue-from <commit>]

K2's k2_run.py pattern, pointed at <books>/m3o/value/archival_2026-06-15/: pool.json (pool_street.py; the census is its names that passed
every stage), runs.json (packets) and slots.json (valuations) beside it, J2's schemas.
- packets: one archival_sec_only_v1 packet per pool name (builder v9: the pool's S0 row, the name's CIK; SEC online under the standing
  approval). A refusal is recorded with its reason and that name gets no valuation; a network failure stops the pass (resumable).
- run: J2's runner unchanged (tools/archival_j2/j2_run.run: seeds 1000 and 3000, a clean tree, the commit of the first valuation, a stop
  on any crash, engine_defect or unpinned cost of equity), with RS2_ARCHIVAL_COE_DIR = this directory's coe_pinned/ (pin_coe.py: MRI's
  anchors as of T and the external premium; coe.py checks it against its manifest on every call). Nothing is copied into coe_pinned/
  here: without it the pass stops. GPU: only inside a window agreed with the "F03 benchmark workflows" session; cache/j2_yield.flag stops
  the pass at the next slot.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "tools" / "archival_k2"), str(ROOT / "tools" / "archival_j2"), str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402
import j2_run as J  # noqa: E402
import k2_run as K  # noqa: E402

DIR = book_paths.books() / "m3o" / "value" / "archival_2026-06-15"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("packets", "run"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
    ap.add_argument("--continue-from")
    ap.add_argument("--dir", help="another archival set under <books>/m3o/value (S1b, 2026-11-09: archival_2025-10-01_pit, K2's pool and "
                    "packets re-valued with the point-in-time cost of equity)")
    a = ap.parse_args(argv)
    DIR = book_paths.books() / "m3o" / "value" / a.dir if a.dir else globals()["DIR"]
    if not (DIR / "coe_pinned" / "manifest.json").exists():
        sys.exit(f"STOP: no pinned cost-of-equity set at {DIR / 'coe_pinned'} (tools/archival_street/pin_coe.py)")
    raw = (DIR / "pool.json").read_bytes()
    pool = K.census(raw)
    path = DIR / "runs.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"pool_sha256": K.sha(raw), "packets": {}, "slots": {}, "git": None}
    if idx["pool_sha256"] != K.sha(raw):
        sys.exit("STOP: pool.json changed since the index began")
    K.DIR = J.DIR = DIR                         # k2_run.packets saves runs.json under K.DIR; j2_run.run reads and writes under J.DIR
    if a.phase == "packets":
        return K.packets(pool, idx)
    return J.run(pool, a.limit, a.ticker, a.continue_from)


if __name__ == "__main__":
    sys.exit(main())
