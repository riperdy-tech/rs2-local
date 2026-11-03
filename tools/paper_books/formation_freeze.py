"""formation_freeze.py - WO_O2 step 5, before the fill open: freeze the formation map and write the one-line witness.

    python tools/paper_books/formation_freeze.py 2026-10-30

Copies <books>/m3o/inputs/formation_<T>.json byte for byte to formation_<T>.frozen.json (refuses if a frozen copy exists), and writes
<books>/m3o/witness/formation_<T>.txt: the frozen map's sha256, the run id, the decision time, and the count of complete,
pending (to_run: analysis_pending at the open) and incomplete names. The runner keeps working on the live map after the freeze;
the frozen copy is the state at the open. The line is also printed. Publishing the witness (a public commit and push) is done by hand
(scan first: the repo is public).
"""
import collections
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402

INPUTS = book_paths.books() / "m3o" / "inputs"
WITNESS = book_paths.books() / "m3o" / "witness"


def main():
    T = sys.argv[1]
    live, frozen = INPUTS / f"formation_{T}.json", INPUTS / f"formation_{T}.frozen.json"
    if frozen.exists():
        sys.exit(f"STOP: {frozen.name} exists")
    b = live.read_bytes()
    m = json.loads(b)
    frozen.write_bytes(b)
    sha = hashlib.sha256(b).hexdigest()
    c = collections.Counter(n["state"] for n in m["names"].values())
    line = (f"formation {T} map_sha256 {sha} run {m['run_id']} T {m['decision_time_utc']} complete {c.get('complete', 0)} "
            f"pending {c.get('to_run', 0)} incomplete {c.get('analysis_incomplete', 0)} operator_excluded {c.get('operator_excluded', 0)} "
            f"frozen_at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    WITNESS.mkdir(parents=True, exist_ok=True)
    (WITNESS / f"formation_{T}.txt").write_text(line + "\n", encoding="utf-8")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
