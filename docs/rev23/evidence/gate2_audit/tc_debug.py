"""Debug one dry-test disagreement: the extractor's quarter records (with tags) against the same-filing pairs.  python tc_debug.py KEY"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
sys.path.insert(0, str(Path(__file__).parent))
import tag_consistent as tc  # noqa: E402
from rebuild_harness import gate1_run as g  # noqa: E402
from valuation.pit_data import PitData  # noqa: E402

key = sys.argv[1]
T, cik = key.split("_")
pit = PitData(g.DEFAULT_STORE)
r = pit.quarterly_rows(cik, T, ("revenue", "operating_income"), 1, "first_filed")[-1]
pe = r["period_end"]
print("extractor row:", pe, r["filed"], r["accession"], r["values"], r["prior_year"], r["kinds"])
recs = pit.quarterly(cik, T, ("revenue", "operating_income"), "first_filed")["records"]
pe0 = (date.fromisoformat(pe) - timedelta(days=365))
for x in recs:
    if x["period_end"] == pe or abs((date.fromisoformat(x["period_end"]) - pe0).days) <= 12:
        if 80 <= tc._days(x["period_start"], x["period_end"]) <= 100:
            print("  rec", x["field"], x["period_start"], x["period_end"], x["value"], x["tag"], x["kind"], x["accession"], x["filed"])
c = pit.company(cik)
f = tc.merged(c.facts, c.qfacts)
for fld in ("revenue", "operating_income"):
    rs = tc.rows_of(f, fld)
    p = tc.pairs_in_filing(rs, r["accession"], pe, tc.Q3M)
    if not p:
        p = tc.derived_q4(rs, r["accession"], pe)
    print(fld, "same-filing pairs:", {"/".join(k): v for k, v in p.items()})
    for x in sorted((x for x in rs if x["accn"] == r["accession"]), key=lambda x: (x["tag"], x["end"]))[:14]:
        print("   ", x["tag"][:40], x["unit"], x["start"], x["end"], x["val"])
