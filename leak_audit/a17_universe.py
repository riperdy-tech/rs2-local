"""Check 12: universe survivorship.  Companies that had a public float >= $300M on a 10-K cover filed in the 21 months before T (the SEC cover index) and are in NEITHER the run's records of the date (the
id-map companies, valued or refused, which is D5 + today's tickers) NOR the census.  Split by what became of them (a periodic report after T+12 months or not) and by SIC (REIT / blank check / pool /
ABS are out of scope by family anyway)."""
import csv, gzip, json, collections
from datetime import date, timedelta
import numpy as np, pandas as pd
from leak_audit import lib
from rebuild_harness import survivorship as sv
ci = sv.CoverIndex(lib.WS / "data" / "survivorship_cover")
# SIC by cik from the headers (latest header filed before T)
hdr = collections.defaultdict(list)
with open(lib.WS / "data" / "sec_bulk" / "headers" / "headers_raw.csv", encoding="utf-8", newline="") as fh:
    for r in csv.DictReader(fh):
        hdr[r["cik"]].append((r["filed"], r["sic"], r["name"], r["form"]))
for k in hdr: hdr[k].sort()
def sic_at(cik, T):
    L = [x for x in hdr.get(cik, []) if x[0] < T]
    return (L[-1][1], L[-1][2]) if L else (None, None)
EVENTS = collections.defaultdict(list)
for e in json.load(open(lib.WS / "data" / "sec_bulk" / "index_P4b" / "events_all.json")):
    EVENTS[e["cik"]].append((e["date"], e["class"]))
SKIP_SIC = {"6798": "REIT", "6770": "blank check", "6221": "commodity pool", "6189": "ABS", "6199": None}
out = {"by_date": {}}
allm = []
for T in lib.DATES:
    recs = {}
    with gzip.open(lib.RUN / f"records_{T}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            recs[r["cik"]] = (r["status"], r.get("mcap_group"), r.get("survivorship") is not None, (r.get("reasons") or [None])[0], r.get("price"))
    Td = date.fromisoformat(T)
    n_float, n_in, miss = 0, 0, []
    for cik, row in ci.by_cik.items():
        it = ci.latest(cik, T)
        if it is None or it["public_float"] < 300e6:
            continue
        if not it["end"] or date.fromisoformat(it["end"]) < Td - timedelta(days=21 * 30.4):
            continue                                              # a float older than 21 months (a Dec-FY company's newest 10-K float before its next 10-K is up to 19 months old): not an active filer at T
        n_float += 1
        if cik in recs:
            n_in += 1
            continue
        last_sh = max((x[3] for x in row["sh"]), default=None)
        sic, nm = sic_at(cik, T)
        evs = sorted(EVENTS.get(cik, []))
        after = [x for x in evs if x[0] > T and x[1] != "exit_record_still_reporting"]
        before = [x for x in evs if x[0] <= T and x[1] != "exit_record_still_reporting"]
        ev_cat = ("event_after_T:" + after[0][1]) if after else ("event_before_T:" + before[-1][1] if before else "no_D1_exit_event")
        alive_after = bool(last_sh and last_sh >= (Td + timedelta(days=365)).isoformat())
        miss.append({"date": T, "cik": cik, "name": row.get("name"), "float": it["public_float"], "float_end": it["end"], "last_cover_filed": last_sh, "ev_cat": ev_cat, "ev_date": (after[0][0] if after else None), "alive_filing_after_T+12m": alive_after, "sic": sic,
                     "skip": SKIP_SIC.get(sic) if sic in SKIP_SIC else None})
    m = pd.DataFrame(miss)
    out["by_date"][T] = {"float_ge_300M_active": n_float, "in_records": n_in, "missing_from_records": len(m), "missing_gone_before_T+12m": int((~m["alive_filing_after_T+12m"]).sum()) if len(m) else 0}
    # records: how many of the in_records are valued>=300M
    allm.append(m)
    print(T, out["by_date"][T], flush=True)
M = pd.concat(allm)
M.to_pickle(lib.OUT / "a17_missing.pkl")
Mg = M[~M["alive_filing_after_T+12m"]]
Mg_scope = Mg[Mg.skip.isna()]
out["total_missing_name_dates"] = int(len(M)); out["gone_name_dates"] = int(len(Mg)); out["gone_in_scope_name_dates"] = int(len(Mg_scope))
out["gone_in_scope_distinct_ciks"] = int(Mg_scope.cik.nunique())
out["gone_in_scope_per_date_mean"] = float(len(Mg_scope) / 9)
out["gone_by_sic_skip"] = Mg.skip.fillna("operating/financial").value_counts().to_dict()
out["alive_untracked_per_date_mean"] = float(((M["alive_filing_after_T+12m"]) & M.skip.isna()).sum() / 9)
cat = M.groupby("ev_cat").size().sort_values(ascending=False)
out["by_event_category_name_dates"] = cat.to_dict()
S_ = M[M.skip.isna()]
out["in_scope_by_event_category"] = S_.groupby("ev_cat").size().sort_values(ascending=False).to_dict()
out["in_scope_event_after_T_per_date"] = S_[S_.ev_cat.str.startswith("event_after_T")].groupby("date").size().to_dict()
out["in_scope_no_event_gone_per_date"] = S_[(S_.ev_cat == "no_D1_exit_event") & (~S_["alive_filing_after_T+12m"])].groupby("date").size().to_dict()
out["in_scope_alive_untracked_per_date"] = S_[(S_.ev_cat == "no_D1_exit_event") & (S_["alive_filing_after_T+12m"])].groupby("date").size().to_dict()
print({k: v for k, v in out.items() if k != "by_date"})
print(Mg_scope.sort_values("float", ascending=False).drop_duplicates("cik").head(25)[["name", "float", "float_end", "last_cover_filed", "sic"]].to_string())
lib.dump(out, "a17_universe.json")
