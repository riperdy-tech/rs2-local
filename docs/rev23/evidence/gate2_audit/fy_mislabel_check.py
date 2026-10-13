"""Audit 1 item (fork 2's AL.10-AL.11, PROBLEM_REPORT_fiscal_year_mislabel.md): the fiscal-year mislabel's reach into gate-2's INPUTS.  Reads only data
known at each T (the packs' store); no outcome.

`CompanyPit.accessions()` gives an annual report the latest end among ANY of its fiscal-year-length duration facts, so a forward-looking fact (Boeing's
2018 statutory tax rate in its FY2017 10-K) relabels the report a year ahead.  The signature: a report whose assigned period ends AFTER its own filing
date.  For each of the 600 sample company-dates:
  * mislabelled_any   an annual accession filed before T with assigned period > filed date
  * mislabelled_last  that accession is the latest annual report filed before T (the base year the engines and Muse saw can be a year stale)
  * base_year_gap     T minus the base year end the engines used (`company_pit(...).annual_reports`), reported for the mislabelled_last rows

    python fy_mislabel_check.py --state-dir RUN2 --out FILE
"""
import argparse
import json
import sys
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
from rebuild_harness import gate1_run as g  # noqa: E402
from rebuild_harness.gate2 import sample as sample_mod  # noqa: E402
from valuation.pit_data import PitData  # noqa: E402

ANNUAL = ("10-K", "10-K405", "10-KT", "20-F", "40-F")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    pit = PitData(g.DEFAULT_STORE)
    smp = sample_mod.load_verified(sample_mod.sample_path(a.state_dir))
    res = {"n": 0, "in_store": 0, "mislabelled_any": 0, "mislabelled_last": 0, "rows": []}
    for j in sample_mod.jobs(smp):
        cik, T = str(j["cik"]).zfill(10), j["date"]
        res["n"] += 1
        c = pit.company(cik)
        if c is None:
            continue
        res["in_store"] += 1
        acc = {k: v for k, v in c.accessions().items() if str(v["filed"])[:10] < T and str(v["form"]).split("/")[0] in ANNUAL}
        if not acc:
            continue
        bad = {k: v for k, v in acc.items() if str(v["period"])[:10] > str(v["filed"])[:10]}
        if not bad:
            continue
        res["mislabelled_any"] += 1
        last = max(acc, key=lambda k: (str(acc[k]["filed"])[:10], k))
        row = {"key": f"{T}_{cik}", "ticker": j.get("ticker"), "family": j.get("family"),
               "mislabelled": {k: {"filed": str(v["filed"])[:10], "assigned_period": str(v["period"])[:10], "form": v["form"]} for k, v in bad.items()},
               "latest_annual_accession": last, "latest_is_mislabelled": last in bad}
        if last in bad:
            res["mislabelled_last"] += 1
            try:
                pc = pit.company_pit(cik, T, j.get("ticker"))
                ends = sorted(str(r[0])[:10] for r in (pc.annual_reports if pc is not None else []))
                row["base_year_end_used"] = ends[-1] if ends else None
            except Exception as e:
                row["base_year_end_used"] = f"error: {type(e).__name__}"
        res["rows"].append(row)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for r in res["rows"]:
        if r["latest_is_mislabelled"]:
            print(r["key"], r["ticker"], r["mislabelled"], "base used:", r.get("base_year_end_used"))


if __name__ == "__main__":
    main()
