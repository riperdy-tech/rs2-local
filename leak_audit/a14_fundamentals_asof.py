"""Check 6: fundamentals as known at T.  Sample 200 random + 100 'at risk' (a periodic report filed within 10 days before T) name-dates of the registered universe.  For each, rebuild the engine's
CompanyPIT with the registered layer (`PitData.company_pit`, no price source needed) and take EVERY accession behind an input (annual-report list, every series cell, every concept, the cover
share count).  For each accession: filing date < T (the layer's rule) and the EDGAR acceptance time (headers_raw.csv accepted_index, UTC; FSDS sub.txt behind it) <= 16:00 ET on T."""
import csv, gzip, json, random, zipfile, io, sys
from datetime import date, datetime, timezone
import numpy as np, pandas as pd
from leak_audit import lib, store
from valuation import pit_data as pdm

panel = lib.load_panel()
ins = panel[(panel.family != "commodity")]
rng = random.Random(20261009)
keys = list(zip(ins.date, ins.cik))
sample = rng.sample(keys, 200)
# headers: accession -> accepted UTC
hdr = {}
with open(lib.WS / "data" / "sec_bulk" / "headers" / "headers_raw.csv", encoding="utf-8", newline="") as fh:
    for r in csv.DictReader(fh):
        hdr[r["accession"]] = (r["accepted_index"], r["accepted_header"], r["filed"], r["form"])
print("headers rows", len(hdr), flush=True)
pit = pdm.PitData(store.STORE)
def acc_of(obj):
    out = []   # (kind, field, period, accession, filed, form)
    for f, per in obj.series.items():
        for pe, x in per.items():
            out.append(("series", f, pe, x.accession, x.filed, x.form))
    for n, per in obj.concepts.items():
        for pe, x in per.items():
            out.append(("concept", n, pe, x.accession, x.filed, x.form))
    for (pe, filed, accn, form) in obj.annual_reports:
        out.append(("annual_report", "", pe, accn, filed, form))
    if obj.shares_outstanding is not None:
        s = obj.shares_outstanding
        out.append(("cover_shares", "", s.period_end if hasattr(s, "period_end") else "", s.accession, s.filed, s.form))
    return out
def at_risk(cik, T):
    c = pit.company(cik)
    if c is None: return False
    asof = pdm.to_date(T)
    for accn, a in c.accessions().items():
        if 0 < (asof - pdm.to_date(a["filed"])).days <= 10 and a["form"].startswith(("10-K", "10-Q", "20-F", "40-F")):
            return True
    return False
risk = []
pool = keys[:]
rng.shuffle(pool)
for k in pool:
    if len(risk) >= 100: break
    if k in sample: continue
    if at_risk(k[1], k[0]):
        risk.append(k)
    pit.evict(k[1])
print("at risk found", len(risk), flush=True)
res = {"sample": {}, "at_risk": {}}
miss_acc = set()
rows = []
for lab, ks in (("sample", sample), ("at_risk", risk)):
    for (T, cik) in ks:
        obj = pit.company_pit(cik, T)
        if obj is None: continue
        cut = pdm.decision_time_utc(T)
        for kind, f, pe, accn, filed, form in acc_of(obj):
            h = hdr.get(accn)
            acc = pdm.parse_accepted(h[0]) if h else None
            rows.append({"set": lab, "date": T, "cik": cik, "kind": kind, "field": f, "period": pe, "accn": accn, "filed": filed, "form": form, "filed_lt_T": filed < T,
                         "accepted_utc": acc.isoformat() if acc else None, "in_headers": h is not None, "accepted_le_cut": (acc <= cut) if acc else None,
                         "accepted_before_T_midnight": (acc.date().isoformat() < T) if acc else None, "hdr_filed": h[2] if h else None})
        pit.evict(cik)
d = pd.DataFrame(rows)
d.to_pickle(lib.OUT / "a14_fundamentals_asof.pkl")
summ = {}
for lab, g in d.groupby("set"):
    u = g.drop_duplicates(["date", "cik", "accn"])
    summ[lab] = {"name_dates": int(g[["date", "cik"]].drop_duplicates().shape[0]), "input_rows": int(len(g)), "distinct_name_date_accessions": int(len(u)),
                 "filed_lt_T_all": bool(g.filed_lt_T.all()), "n_filed_not_lt_T": int((~g.filed_lt_T).sum()),
                 "accessions_found_in_headers": int(u.in_headers.sum()), "share_in_headers": float(u.in_headers.mean()),
                 "n_accepted_after_16h_ET_on_T": int((u.accepted_le_cut == False).sum()), "n_accepted_on_T_or_later_calendar_day_UTC": int((u.accepted_before_T_midnight == False).sum()),
                 "hdr_filed_differs_from_store_filed": int(((u.hdr_filed.notna()) & (u.hdr_filed != u.filed)).sum())}
print(json.dumps(summ, indent=1))
# the latest acceptance relative to the cut among rows with headers
g = d[d.accepted_utc.notna()].copy()
g["margin_h"] = [(pdm.decision_time_utc(T) - pd.Timestamp(a).to_pydatetime()).total_seconds() / 3600 for T, a in zip(g.date, g.accepted_utc)]
summ["min_hours_between_acceptance_and_decision_time"] = float(g.margin_h.min())
summ["share_within_24h_of_cut"] = float((g.margin_h < 24).mean())
print("min margin hours", summ["min_hours_between_acceptance_and_decision_time"])
miss = d[~d.in_headers].drop_duplicates(["accn"])
summ["not_in_headers_by_kind_form"] = miss.groupby("form").size().sort_values(ascending=False).head(10).to_dict()
print(summ["not_in_headers_by_kind_form"])
lib.dump(summ, "a14_fundamentals_asof.json")
