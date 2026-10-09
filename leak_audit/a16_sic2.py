"""Check 11: classification.  Industry neutralisation (B1's industry effects, B2's neutral quintiles) replaced by the 2-digit SIC as filed at T (the strict resolver's SIC, recorded on each record), and by date effects only."""
import sys, gzip, json
import pandas as pd
from leak_audit import lib
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
panel = lib.load_panel()
rows = lib.load_rows(panel)
sic = {}
for d in lib.DATES:
    with gzip.open(lib.RUN / f"records_{d}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["status"] == "valued":
                sic[(d, r["cik"])] = r.get("sic")
miss = sum(1 for r in rows if not sic.get(r["_k"]))
print("rows without sic", miss, "of", len(rows))
sc = lib.key_map(panel, "s_cfg"); fn = lambda r: sc.get(r["_k"])
out = {"rows_without_sic": miss}
def regroup(rs, key):
    new = []
    for r in rs:
        r2 = dict(r)
        r2["industry"] = key(r)
        r2["sector"] = key(r)
        new.append(r2)
    return new
sic2 = lambda r: ("SIC2:" + str(sic.get(r["_k"]))[:2]) if sic.get(r["_k"]) else "SIC2:unknown"
sic3 = lambda r: ("SIC3:" + str(sic.get(r["_k"]))[:3]) if sic.get(r["_k"]) else "SIC3:unknown"
for lab, rs in (("registered (Damodaran industry via 2026 crosswalk)", rows), ("2-digit SIC as filed (B1 effects and B2 groups)", regroup(rows, sic2)), ("3-digit SIC as filed", regroup(rows, sic3)),
                ("date effects only (one group)", regroup(rows, lambda r: "all"))):
    res = lib.bars(rs, fn, n_boot=nb if "date effects" not in lab else 0)
    out[lab] = res
    print(f"{lab:55s} {lib.fmt(res)}", flush=True)
out["n_sic2_groups"] = len({sic2(r) for r in rows}); out["n_industries"] = len({r["industry"] for r in rows})
lib.dump(out, "a16_sic2.json")
