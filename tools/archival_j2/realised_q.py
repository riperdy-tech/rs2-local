"""realised_q.py - the realised next quarter of one company after a decision date T, measured inside the one filing that first reports it
(PREREG_cohorts_nextq v0.1 section 3, 2026-11-10).

    realised_q(cf, subs, T, by) -> {"status", "quarter", "revenue_growth", "kinds", "tags", "measures", ...}

cf, subs: SEC's companyfacts and submissions JSON for the company; T: the decision date (ISO); by: the last filing date allowed (ISO).

THE RULES.
1. The next quarter: among the submissions' 10-Q and 10-K filings (originals; an amendment only where no original reports that period)
   filed on or before `by`, the earliest report date after T. Its filing: the earliest filed (filingDate, then accession) for that report
   date. None: status `no_quarter_filed`.
2. A gap is not a next quarter: a report date more than MAX_GAP_DAYS after T means a quarter was skipped or not filed; status
   `quarter_gap` (counted, never imputed).
3. The measure is gate 2's same_filing.quarter_measures on that accession, unchanged: the 3-month pair in its own filing, else (a 10-K)
   a derived Q4 from the fiscal year minus nine months under one tag, refused across a recast. revenue_growth = this quarter / the same
   quarter one year earlier, both legs as printed in that one filing.
"""
from datetime import date, timedelta

import realised
import same_filing as sf

REALISED_Q_VERSION = "cohorts.realised_q.v1"
FORMS = ("10-Q", "10-K")
AMENDED = ("10-Q/A", "10-K/A")
MAX_GAP_DAYS = 100           # a fiscal quarter is 91 days; the first quarter ending after T ends within 92 days of it


def next_quarter_filing(subs, T, by):
    """Rules 1-2: ({form, accession, filed, report_date, stamp} or None, status)."""
    t = date.fromisoformat(str(T)[:10])
    rows = [r for r in realised._recent(subs) if r["accession"] and r["report_date"] and r["filed"] and r["filed"] <= str(by)[:10]
            and date.fromisoformat(r["report_date"]) > t and r["form"] in FORMS + AMENDED]
    if not rows:
        return None, "no_quarter_filed"
    first = min(r["report_date"] for r in rows)
    if (date.fromisoformat(first) - t).days > MAX_GAP_DAYS:
        return None, "quarter_gap"
    for forms, stamp in ((FORMS, None), (AMENDED, "from_amendment")):
        c = sorted((r for r in rows if r["report_date"] == first and r["form"] in forms), key=lambda r: (r["filed"], r["accession"]))
        if c:
            return dict(c[0], stamp=stamp), "ok"
    return None, "no_quarter_filed"


def realised_q(cf, subs, T, by, family="operating"):
    out = {"version": REALISED_Q_VERSION, "T": str(T)[:10], "by": str(by)[:10], "status": None, "quarter": None, "revenue_growth": None}
    q, st = next_quarter_filing(subs, T, by)
    if q is None:
        return dict(out, status=st)
    out["quarter"] = q
    m = sf.quarter_measures(realised.store_facts(cf), q["accession"], q["report_date"], family, None)
    out["measures"] = m
    out["revenue_growth"] = m.get("revenue_growth")
    out["status"] = "ok" if out["revenue_growth"] is not None else (m.get("status") or "no_same_filing_pair")
    return out
