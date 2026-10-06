"""build_vintage.py - the observation table of one vintage (cut at Dec 31 of year Y), written to data/priors/<Y>/obs.csv.gz.

    python -m valuation.priors_build.build_vintage 2016 2020 2022 2024 2025 [--workers 12] [--limit N]

Offline.  Reads the compact companyfacts store (valuation.pit_data) and runs, per company, the layer's first-filed extraction cut at the vintage date.
Every company in the store is kept (delisted ones included); a company with no annual report before the cut has no observations.  An exception in one
company is recorded in errors.json with its CIK, never swallowed.
"""
import argparse
import hashlib
import json
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.pit_data import PitData
from valuation.priors_build import config as C
from valuation.priors_build.obs import company_observations

_PIT = None
_SIC = None


def _init():
    global _PIT, _SIC
    _PIT = PitData(C.STORE_DIR)
    _SIC = json.loads((C.INPUTS_DIR / "sic_by_cik.json").read_text(encoding="utf-8"))["map"]


def _work(args):
    ciks, cut = args
    rows, errs = [], []
    for cik in ciks:
        try:
            c = _PIT.company(cik)
            if c is None:
                continue
            s = _SIC.get(cik)
            rows += company_observations(c, cut, s["sic"] if s else None)
        except Exception:
            errs.append({"cik": cik, "error": traceback.format_exc(limit=3)})
        if len(_PIT._cache) > 50:
            _PIT.drop_cache()
    return pd.DataFrame(rows), errs


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def store_fingerprint():
    """sha256 over 'name:size' of every member of the store: names the data the vintage was built from."""
    h = hashlib.sha256()
    n = 0
    for p in sorted(C.STORE_DIR.glob("*.json.gz")):
        h.update(f"{p.name}:{p.stat().st_size}\n".encode())
        n += 1
    return h.hexdigest(), n


def build(year, workers, limit=None):
    t0 = time.time()
    cut = C.cut_date(year)
    ciks = sorted(p.name[:10] for p in C.STORE_DIR.glob("*.json.gz"))
    if limit:
        ciks = ciks[:limit]
    chunks = [(ciks[i:i + 100], cut) for i in range(0, len(ciks), 100)]
    parts, errs = [], []
    with Pool(workers, initializer=_init) as p:
        for df, e in p.imap_unordered(_work, chunks):
            parts.append(df)
            errs += e
    df = pd.concat([x for x in parts if len(x)], ignore_index=True).sort_values(["cik", "fye"]).reset_index(drop=True)
    d = C.vintage_dir(year)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "obs.csv.gz"
    df.to_csv(path, index=False, compression="gzip", float_format="%.10g")
    fp, nstore = store_fingerprint()
    meta = {"vintage": year, "cut_date": cut, "rule": "fiscal years whose own annual report was filed strictly before the cut date; first-filed values",
            "observations": int(len(df)), "companies": int(df["cik"].nunique()), "store_members": nstore, "store_fingerprint_sha256": fp,
            "obs_sha256": sha256_file(path), "errors": len(errs), "priors_version": C.PRIORS_VERSION, "seconds": round(time.time() - t0)}
    (d / "obs_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if errs:
        (d / "errors.json").write_text(json.dumps(errs[:200], indent=1), encoding="utf-8")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("years", nargs="+", type=int)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    for y in a.years:
        print(build(y, a.workers, a.limit), flush=True)
