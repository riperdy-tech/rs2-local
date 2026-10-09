"""Check 5: priors vintages.  (i) the vintage recorded in every valued record of the nine dates; (ii) the observation files: every filing date used (own annual report and the k-years-ahead outcomes)
against the vintage's cut date; (iii) the same for the vintages 2023 and 2025 (spot check: 2025 must NOT be used for a 2025 date)."""
import gzip, json, collections
import pandas as pd
from leak_audit import lib
base = lib.WS / "data" / "priors_v3"
out = {}
cnt = collections.Counter()
for d in lib.DATES:
    with gzip.open(lib.RUN / f"records_{d}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            v = r.get("val") or {}
            pm = v.get("prior_meta") or {}
            if "vintage" in pm:
                cnt[(d[:4], pm["vintage"])] += 1
out["vintage_used_by_record_year"] = {f"{a}->{b}": n for (a, b), n in cnt.items()}
print(out["vintage_used_by_record_year"])
for vint in (2022, 2023, 2024, 2025):
    meta = json.load(open(base / str(vint) / "obs_meta.json"))
    df = pd.read_csv(base / str(vint) / "obs.csv.gz")
    fcols = ["own_filed"] + [c for c in df.columns if c.startswith("filed_")]
    mx = {c: df[c].dropna().max() for c in fcols}
    over = {c: int((df[c].dropna() >= meta["cut_date"]).sum()) for c in fcols}
    out[str(vint)] = {"cut_date": meta["cut_date"], "rule": meta["rule"], "n_obs": int(len(df)), "max_own_filed": mx["own_filed"], "max_filed_k": max(v for k, v in mx.items() if k != "own_filed"),
                      "n_filing_dates_on_or_after_cut": {c: n for c, n in over.items() if n}, "max_obs_date": df["obs_date"].dropna().max()}
    print(vint, out[str(vint)])
# which table the freeze hashed vs on disk
fz = json.load(open(lib.GATE / "gate1b_freeze.json"))
out["freeze_2024_table_sha256"] = fz["annotations"]["priors_vintages_used"]["tables_sha256"]["2024"]
out["disk_2024_tables_sha256_file"] = open(base / "2024" / "tables.sha256").read().strip()
lib.dump(out, "a13_priors.json")
