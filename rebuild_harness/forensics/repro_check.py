"""Reproduction of the stored holdout records: compare the forensic run's records of a 2023-2024 date with the holdout run's (`gate1_holdout/run`), name by name.

    python -m rebuild_harness.forensics.repro_check FORENSIC_RUN_DIR DATE [DATE ...]

Compared per company (cik): status, family, price, market cap, the registered score (median IV / price), the P10..P90 of the IV per share, the five yardsticks, the 12-month excess return and its three bounds.
Exact equality is required (floats compared with ==, as the draws are seeded and the arithmetic is the same code); differences are listed."""
import gzip
import json
import sys
from pathlib import Path

HOLD = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\gate1_holdout\run")


def load(p):
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out[r["cik"]] = r
    return out


def key_fields(r):
    v = r.get("val") or {}
    iv = (v.get("iv_ps") or {})
    return {"status": r["status"], "family": r.get("family"), "price": r.get("price"), "market_cap": r.get("market_cap"), "score": (r.get("score") or {}),
            "iv_ps": {k: iv.get(k) for k in ("p10", "p25", "p50", "p75", "p90")}, "x12": (r.get("excess") or {}).get("12"), "b12": (r.get("bounds") or {}).get("12"),
            "survivor": r.get("survivorship") is not None}


def compare(run_dir, date):
    a, b = load(HOLD / f"records_{date}.jsonl.gz"), load(Path(run_dir) / f"records_{date}.jsonl.gz")
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    diffs = {}
    same = 0
    for c in sorted(set(a) & set(b)):
        ka, kb = key_fields(a[c]), key_fields(b[c])
        bad = [k for k in ka if ka[k] != kb[k]]
        if bad:
            diffs[c] = bad
        else:
            same += 1
    return {"date": date, "stored": len(a), "forensic": len(b), "identical": same, "only_in_stored": len(only_a), "only_in_forensic": len(only_b), "different": len(diffs),
            "different_fields": {k: sum(1 for v in diffs.values() if k in v) for k in sorted({k for v in diffs.values() for k in v})}, "examples": dict(list(diffs.items())[:5])}


if __name__ == "__main__":
    for d in sys.argv[2:]:
        print(json.dumps(compare(sys.argv[1], d), indent=1))
