"""Z item 1, step 1: every merger-related filing of every audited company, from the LOCAL SEC submissions archive (no download).  One process, read only.
Forms kept: 8-K / 8-K/A with Item 1.01 or 2.01; the target-side merger forms DEFM14A, PREM14A, DEFM14C, PREM14C, SC 14D9 (+/A), SC TO-T (+/A), SC TO-C, SC 13E3 (+/A), SC14D9, SC 14D1; and S-4 / 425 (both sides).
Output: leak_audit_z/z01_ma_filings.pkl  (cik, form, filed, items, accession)."""
import json
import time
import zipfile

import pandas as pd

from leak_audit import libz

KEEP = {"DEFM14A", "PREM14A", "DEFM14C", "PREM14C", "SC 14D9", "SC 14D9/A", "SC14D9", "SC TO-T", "SC TO-T/A", "SC TO-C", "SC 13E3", "SC 13E3/A", "SC 14D1", "SC 14D1/A", "S-4", "S-4/A", "425", "SC TO-I", "SC TO-I/A"}
t0 = time.time()
ciks = sorted(set(libz.load_hold().cik) | set(libz.load_dev().cik))
print(len(ciks), "ciks")
z = zipfile.ZipFile(libz.SUBMISSIONS)
files = {}
for n in z.namelist():
    if n.startswith("CIK") and n.endswith(".json") and n[3:13] in set(ciks):
        files.setdefault(n[3:13], []).append(n)
print("have files for", len(files), time.time() - t0, flush=True)
rows = []
allforms = {}
for i, c in enumerate(ciks):
    for n in files.get(c, []):
        b = json.loads(z.read(n))
        r = (b.get("filings") or {}).get("recent") if "filings" in b else b
        r = r or {}
        m = len(r.get("form") or [])
        it = r.get("items") or [""] * m
        for k in range(m):
            f = r["form"][k]
            its = str(it[k] or "")
            s = {x.strip() for x in its.split(",") if x.strip()}
            if (f in ("8-K", "8-K/A") and (s & {"1.01", "2.01"})) or f in KEEP:
                rows.append((c, f, r["filingDate"][k], its, r["accessionNumber"][k]))
    if i % 300 == 0:
        print(i, len(rows), time.time() - t0, flush=True)
df = pd.DataFrame(rows, columns=["cik", "form", "filed", "items", "accession"]).drop_duplicates(["cik", "accession", "form"])
df.to_pickle(libz.OUT / "z01_ma_filings.pkl")
print(df.shape, df.form.value_counts().to_dict(), time.time() - t0)
print("ciks without a submissions file:", [c for c in ciks if c not in files][:10], len([c for c in ciks if c not in files]))
