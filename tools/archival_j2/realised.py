"""realised.py - J2-3: the realised year 1 of one company, measured inside its year-1 annual filing (J2 v0.2 section 3; PREREG addendum
draft v0.2 archival_test.realised; operator rulings AK.30 and AK.37 v2).

    realised(cf, subs, fy0, by="2026-10-31") -> {"status", "year1", "revenue", "growth_same", "margin", "first_filed", "growth_first",
                                                  "base_move", "growth_gap_points", "restated_base", "scope", ...}

cf, subs: SEC's companyfacts and submissions JSON for the company; fy0: the base fiscal year's end (ISO date; at T 2025-12-31 the FY2024 end).

THE RULES.
1. Year 1's annual filing: in the submissions, the earliest-filed (filingDate, then accession) 10-K, 20-F or 40-F whose report date lies
   350-380 days after fy0 (J2's duration rule) and that was filed on or before `by`. Only when no original exists is an amendment
   (10-K/A, 20-F/A, 40-F/A) used, stamped `year1_from_amendment`. None: status `no_year1_annual_filing` (counted, never imputed).
2. Same filing (gate 2's same_filing.py, ported unchanged): both legs from that one accession, one taxonomy, one tag, one unit; the
   year-1 leg ends within 3 days of the report date, the base leg within 12 days of fy0, each a 350-380-day duration. Revenue: among the
   ladder's tags present for both years, the largest current value within one unit (USD when present), a near-tie (0.5%) going to the
   largest prior (AK.28, AK.29, AK.41). growth_same = FY1 revenue / the FY0 comparative printed in that filing - 1.
   No pair: status `no_same_filing_revenue_pair`; a comparative <= 0: status `base_not_positive` (no growth).
3. Margin: FY1 operating income / FY1 revenue, the operating income being the first ladder tag with both years in the same filing and the
   revenue's unit; FY1 revenue must be > 0. Otherwise margin is None with `margin_absent`.
4. First-filed, reported beside it and never judged: the FY0 revenue in the EARLIEST annual-form filing (filed, accession) reporting a
   350-380-day FY0 revenue ending within 3 days of fy0, under the same taxonomy, tag and unit as the same-filing choice; where that filing
   lacks the tag, its largest value in the same unit, stamped `first_filed_tag_differs`. growth_first = FY1 revenue / it - 1.
5. A restated base is recorded: base_move = the same-filing comparative / the first-filed value - 1; restated_base = |base_move| > 0.5%
   (same_filing.RECAST_TOL); growth_gap_points = growth_same - growth_first (J2 section 7 item 7: "1 point" is a growth point).
6. Total revenue (AK.37 v2 item 2): same_filing.revenue_scope on the year-1 filing's fiscal-year pair: `dominance` (largest of >= 2 tags),
   `closure`, `closure_fail` (the measure abstains) or `unverified` (scored, flagged).
"""
from datetime import date, timedelta

import same_filing as sf

REALISED_VERSION = "j2.realised.v1"
BY = "2026-10-31"
ANNUAL = ("10-K", "20-F", "40-F")
ANNUAL_AMENDED = ("10-K/A", "20-F/A", "40-F/A")
YEAR1_DAYS = sf.QFY                                   # (350, 380): days from fy0 to year 1's report date
BASE_END_TOL = 3                                      # days the first-filed FY0 leg's end may differ from fy0


def store_facts(cf):
    """SEC companyfacts -> same_filing's {taxo: {tag: {unit: [[start, end, val, accn, filed, form], ...]}}} for the ladder's tags."""
    tags = {t for v in sf.LADDER.values() for t in v}
    out = {}
    for taxo in sf.TAXOS:
        for tag, d in (((cf or {}).get("facts") or {}).get(taxo) or {}).items():
            if tag not in tags:
                continue
            for unit, rows in (d.get("units") or {}).items():
                out.setdefault(taxo, {}).setdefault(tag, {})[unit] = [
                    [r.get("start"), r.get("end"), r.get("val"), r.get("accn"), r.get("filed"), r.get("form")] for r in rows]
    return out


def _recent(subs):
    """[{form, accession, filed, report_date}] of the submissions' recent filings."""
    rec = ((subs or {}).get("filings") or {}).get("recent") or {}
    n = len(rec.get("form") or [])

    def col(name, i):
        v = rec.get(name) or []
        return v[i] if i < len(v) else None
    return [{"form": col("form", i), "accession": col("accessionNumber", i), "filed": str(col("filingDate", i) or "")[:10],
             "report_date": str(col("reportDate", i) or "")[:10] or None} for i in range(n)]


def year1_filing(subs, fy0, by=BY):
    """Rule 1: the year-1 annual filing's {form, accession, filed, report_date, stamp}, or None."""
    lo, hi = (date.fromisoformat(fy0) + timedelta(days=d) for d in YEAR1_DAYS)
    rows = [r for r in _recent(subs) if r["accession"] and r["report_date"] and r["filed"] and r["filed"] <= str(by)[:10]
            and lo <= date.fromisoformat(r["report_date"]) <= hi]
    for forms, stamp in ((ANNUAL, None), (ANNUAL_AMENDED, "year1_from_amendment")):
        c = sorted((r for r in rows if r["form"] in forms), key=lambda r: (r["filed"], r["accession"]))
        if c:
            return dict(c[0], stamp=stamp)
    return None


def first_filed_base(fx, key, fy0):
    """Rule 4: {accession, filed, form, tag, value, stamp} of FY0's first-filed revenue, or None. key: (taxo, tag, unit)."""
    rows = [r for r in sf.rows_of(fx, "revenue") if r["form"] in ANNUAL + ANNUAL_AMENDED and sf._cls(r, sf.QFY)
            and abs(sf._days(fy0, r["end"])) <= BASE_END_TOL]
    if not rows:
        return None
    first = min((r["filed"], r["accn"]) for r in rows)
    inf = [r for r in rows if (r["filed"], r["accn"]) == first]
    same = [r for r in inf if (r["taxo"], r["tag"], r["unit"]) == tuple(key)]
    stamp = None
    if not same:
        same = [r for r in inf if r["unit"] == key[2]]
        stamp = "first_filed_tag_differs"
    if not same:
        return None
    pick = max(same, key=lambda r: r["val"])
    if len({r["val"] for r in same}) > 1:
        stamp = ";".join(s for s in (stamp, "first_filed_largest_of_values") if s)
    return {"accession": pick["accn"], "filed": pick["filed"], "form": pick["form"], "taxo": pick["taxo"], "tag": pick["tag"],
            "unit": pick["unit"], "value": pick["val"], "stamp": stamp}


def realised(cf, subs, fy0, *, by=BY):
    """The realised year 1 of one company by the rules in the module docstring."""
    out = {"version": REALISED_VERSION, "fy0": fy0, "by": str(by)[:10], "status": None, "year1": None, "growth_same": None,
           "margin": None, "margin_absent": None, "first_filed": None, "growth_first": None, "base_move": None,
           "growth_gap_points": None, "restated_base": None, "scope": None}
    k = year1_filing(subs, fy0, by)
    if k is None:
        return dict(out, status="no_year1_annual_filing")
    out["year1"] = k
    fx = store_facts(cf)
    got = {f: sf.choose(sf.pairs_in_filing(sf.rows_of(fx, f), k["accession"], k["report_date"], sf.QFY, prior_end=fy0), f)
           for f in ("revenue", "operating_income")}
    rk, rv, note = got["revenue"]
    if rk is None:
        return dict(out, status="no_same_filing_revenue_pair")
    r1, r0 = rv
    out["revenue"] = {"taxo": rk[0], "tag": rk[1], "unit": rk[2], "current": r1, "prior_same_filing": r0, "tags": note}
    out["scope"] = sf.revenue_scope(cf, rk[1], rk[2], len((note or {}).get("tags") or {}), k["accession"], k["report_date"], "annual")
    ok, ov, _ = got["operating_income"]
    if ok is None:
        out["margin_absent"] = "no same-filing operating income pair"
    elif ok[2] != rk[2]:
        out["margin_absent"] = f"operating income unit {ok[2]} is not the revenue unit {rk[2]}"
    elif not r1 > 0:
        out["margin_absent"] = "year-1 revenue not positive"
    else:
        out.update(margin=ov[0] / r1, operating_income={"taxo": ok[0], "tag": ok[1], "unit": ok[2], "current": ov[0], "prior_same_filing": ov[1]})
    if not r0 > 0:
        return dict(out, status="base_not_positive")
    out.update(status="ok", growth_same=r1 / r0 - 1.0)
    ff = first_filed_base(fx, rk, fy0)
    out["first_filed"] = ff
    if ff is not None and ff["value"] > 0:
        out.update(growth_first=r1 / ff["value"] - 1.0, base_move=r0 / ff["value"] - 1.0)
        out.update(growth_gap_points=out["growth_same"] - out["growth_first"], restated_base=abs(out["base_move"]) > sf.RECAST_TOL)
    return out
