"""Check 6 (continued): the accessions not in headers_raw.csv, looked up in the FSDS sub.txt files (accepted time, Eastern wall clock); and the direction of the store-vs-header filing-date differences."""
import zipfile, io, csv, json
import pandas as pd
from datetime import datetime, timedelta
from leak_audit import lib
from valuation import pit_data as pdm
d = pd.read_pickle(lib.OUT / "a14_fundamentals_asof.pkl")
miss = d[~d.in_headers].drop_duplicates("accn")
need = set(miss.accn)
found = {}
fs = lib.WS / "data" / "sec_bulk" / "fsds"
for q in sorted(fs.glob("20*q*.zip")):
    if q.name[:4] < "2019": continue
    with zipfile.ZipFile(q) as z:
        with z.open("sub.txt") as fh:
            rd = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter="\t")
            for r in rd:
                if r["adsh"] in need:
                    found[r["adsh"]] = (r["accepted"], r["filed"])
print("needed", len(need), "found in FSDS", len(found))
bad = 0; worst = None
for _, r in miss.iterrows():
    f = found.get(r.accn)
    if not f: continue
    acc = datetime.strptime(f[0][:19], "%Y-%m-%d %H:%M:%S")                 # Eastern wall clock
    cut = datetime.strptime(r.date, "%Y-%m-%d") + timedelta(hours=16)
    if acc > cut: bad += 1
    m = (cut - acc).total_seconds() / 3600
    worst = m if worst is None else min(worst, m)
print("accepted after 16:00 ET on T:", bad, " min hours before cut:", worst)
# direction of store filed vs header filed
g = d[d.in_headers & d.hdr_filed.notna()].drop_duplicates(["date", "cik", "accn"])
g = g[g.hdr_filed != g.filed]
delta = (pd.to_datetime(g.filed) - pd.to_datetime(g.hdr_filed)).dt.days
print("filed differs:", len(g), delta.value_counts().head(8).to_dict())
lib.dump({"needed": len(need), "found_in_fsds": len(found), "accepted_after_cut": bad, "min_hours_before_cut": worst, "filed_diff_days_store_minus_header": delta.value_counts().to_dict()}, "a14b_fsds_fill.json")
