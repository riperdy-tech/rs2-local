"""prep_inputs.py - two small inputs of the priors build.

1. sic_by_cik.json: the SIC code of a company from Damodaran's `indname` (January 2026, Exchange:Ticker -> SIC) through the screener's current ticker -> CIK map.
   BOTH are current-dated labels (SEC publishes only the current SIC; Addendum C 7 wants the SIC as filed at T, which needs filing headers this build does
   not hold).  Companies that no longer trade have no current ticker and therefore no SIC here: their family comes from the balance-sheet tests only.
2. company_status.csv.gz: per CIK in the store, the first and last annual-report and periodic-report filing dates, whether it ever reports in a
   non-dollar currency, and the hindsight label `ceased` (no periodic filing in the CEASED_MONTHS before the newest filing in the archive).  `ceased` is a
   REPORTING label for the survivorship shares; no prior ever reads it.
"""
import csv
import gzip
import json
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.priors_build import config as C

US_EXCHANGES = {"NYSE", "NasdaqGS", "NasdaqGM", "NasdaqCM", "NYSEAM", "NYSE MKT", "NYSEArca", "AMEX", "OTCPK", "OTCQB", "OTCQX", "NasdaqGS ", "BATS", "Nasdaq"}


def build_sic_map():
    m = json.load(open(C.CIK_MAP, encoding="utf-8-sig"))["map"]
    df = pd.read_csv(C.INDNAME_CSV, encoding="latin-1", dtype=str)
    df = df.rename(columns={"Exchange:Ticker": "xt", "SIC Code": "sic", "Industry Group": "industry"})
    ex = df["xt"].str.split(":", n=1, expand=True)
    df["exchange"], df["ticker"] = ex[0], ex[1]
    us = df[df["exchange"].isin(US_EXCHANGES)]
    votes = {}
    for _, r in us.iterrows():
        cik = m.get(r["ticker"])
        if cik is None or not isinstance(r["sic"], str) or not r["sic"].strip().isdigit():
            continue
        votes.setdefault(str(cik).zfill(10), Counter())[(r["sic"].strip(), r["industry"])] += 1
    out = {c: {"sic": v.most_common(1)[0][0][0], "industry": v.most_common(1)[0][0][1]} for c, v in votes.items()}
    return out, {"us_rows": int(len(us)), "ciks_with_sic": len(out), "source": "damodaran datasets_indname.xls 2026-01 (current-dated) via screener cik_map (current tickers)"}


def _status(path):
    try:
        doc = json.load(gzip.open(path, "rt", encoding="utf-8"))
    except Exception as e:                                           # an unreadable member is reported, not skipped silently
        return {"cik": Path(path).name[:10], "error": str(e)}
    ann, per, usd, other = [], [], 0, Counter()
    for taxo, tags in doc["facts"].items():
        for tag, units in tags.items():
            for unit, rows in units.items():
                if taxo == "dei":
                    per += [r[4] for r in rows]
                    continue
                for r in rows:
                    ann.append(r[4])
                if unit == "USD":
                    usd += 1
                elif "/" not in unit and unit not in ("shares", "pure"):
                    other[unit] += 1
    allf = ann + per
    return {"cik": Path(path).name[:10], "name": doc.get("name"), "first_filed": min(allf) if allf else None, "last_annual_filed": max(ann) if ann else None,
            "last_periodic_filed": max(allf) if allf else None, "usd_facts": usd, "other_currency": max(other, key=other.get) if other else None}


def build_status(workers=12):
    files = sorted(C.STORE_DIR.glob("*.json.gz"))
    with Pool(workers) as p:
        rows = p.map(_status, files, chunksize=100)
    df = pd.DataFrame(rows)
    newest = df["last_periodic_filed"].dropna().max()
    cut = (pd.Timestamp(newest) - pd.DateOffset(months=C.CEASED_MONTHS)).date().isoformat()
    df["ceased"] = df["last_periodic_filed"].fillna("0000-00-00") < cut
    return df, {"newest_filing_in_archive": newest, "ceased_cutoff": cut, "ceased_months": C.CEASED_MONTHS, "ciks": int(len(df)),
                "ceased": int(df["ceased"].sum()), "read_errors": int(df["error"].notna().sum()) if "error" in df else 0}


if __name__ == "__main__":
    t0 = time.time()
    inp = C.INPUTS_DIR
    inp.mkdir(parents=True, exist_ok=True)
    sic, meta = build_sic_map()
    (inp / "sic_by_cik.json").write_text(json.dumps({"meta": meta, "map": sic}, separators=(",", ":")), encoding="utf-8")
    print("sic", meta, f"{time.time() - t0:.0f}s", flush=True)
    st, meta2 = build_status()
    st.to_csv(inp / "company_status.csv.gz", index=False, compression="gzip")
    (inp / "company_status_meta.json").write_text(json.dumps(meta2, indent=1), encoding="utf-8")
    print("status", meta2, f"{time.time() - t0:.0f}s")
