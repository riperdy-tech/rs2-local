"""Backtest registration C1, the whole-archive form: every member of every cut zip holds no fact filed after its T.

Streams each member's raw bytes and takes the latest `"filed":"YYYY-MM-DD"` value (no JSON parse); also checks the zip's CRC (testzip
equivalent per member) and counts members.  Offline; reads only the cut zips.

  python verify_cut.py --cut-dir <dir>
"""
import argparse
import json
import re
import zipfile
from multiprocessing import Pool
from pathlib import Path

FILED = re.compile(rb'"filed":"(\d{4}-\d{2}-\d{2})"')
NOFILED_PROBE = re.compile(rb'"end":"\d{4}-\d{2}-\d{2}","val":[^{}]*?\}')       # a fact object (informational only)


def scan(args):
    path, names = args
    z = zipfile.ZipFile(path)
    worst, n_facts = "", 0
    for n in names:
        data = z.read(n)                                  # raises BadZipFile on a CRC mismatch
        found = FILED.findall(data)
        n_facts += len(found)
        if found:
            worst = max(worst, max(found).decode())
    return worst, n_facts, len(names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut-dir", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=14)
    a = ap.parse_args()
    out = {}
    for zp in sorted(a.cut_dir.glob("cut_*.zip")):
        T = zp.stem[4:]
        names = [i.filename for i in zipfile.ZipFile(zp).infolist()]
        chunks = [(str(zp), names[i:i + 300]) for i in range(0, len(names), 300)]
        with Pool(a.workers) as pool:
            parts = pool.map(scan, chunks)
        worst = max(p[0] for p in parts)
        out[T] = {"members": sum(p[2] for p in parts), "filed_values_seen": sum(p[1] for p in parts), "latest_filed": worst, "pass": worst <= T}
        print(T, out[T], flush=True)
    (a.cut_dir / "verify_cut.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
