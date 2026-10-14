"""same_filing.py - outcomes measured inside ONE filing, and the eligibility rules for a forecast target (SPEC_rebuild AK.27-AK.31, AK.37).

WHY.  A growth (or margin change) built from two separately first-filed figures can compare two different bases: a recast (a sold business re-reported
as discontinued; Dollar Tree -38% against its own +12%) or a tag seam (one period on `Revenues`, the other on the contract-revenue tag).  Every report
restates the comparative period on its own current basis, under one tag; measuring both legs from that one report is like for like.  Ported unchanged
in logic from `scratch/rev23/gate2_audit/tag_consistent.py`, which measured gate 2's version of record (AK.35) and passed the 20-of-20 hand check
against the filed documents (AK.36); `tests/test_same_filing.py` holds the cases, and an equivalence test against that run gates its use.

RULES.
  * One accession, one taxonomy, one tag, one unit for both legs.
  * Revenue: among the ladder's tags present for both periods, the largest current-period value within one unit (USD when present): a total is never
    smaller than a line within it (AK.28, AK.29).  Operating income and net income: the first ladder tag present for both periods.
  * A quarter: the 3-month pair in its own filing; failing that, a derived Q4 (fiscal year minus nine months, both years) with one tag across the 10-K
    and the third-quarter 10-Q, and NOT across a recast (the 10-K's prior-year figure must equal the one first filed for that year, within 0.5%).
  * The annual target: the year-1 annual report's own comparative column for the base year.
  * Each measure stands on its own pair (a bank has no revenue line; its net income still measures).
ELIGIBILITY (AK.37; reads the pack manifest the runner writes, never an outcome):
  * a quarter is NOT a forecast when an earnings release filed after its end was in the pack, or when it ended more than 120 days before T;
  * a fiscal year is NOT a forecast when its annual report, or an earnings release filed after its end, was in the pack before T.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

TAXOS = ("us-gaap", "ifrs-full")
LADDER = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "Revenue", "RevenueFromContractsWithCustomers"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
}
Q3M, Q9M, QFY = (80, 100), (250, 290), (350, 380)
RECAST_TOL = 0.005
STALE_DAYS = 120


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def _days(a, b) -> int:
    return (_d(b) - _d(a)).days


def merged(facts: Optional[Mapping], qfacts: Optional[Mapping]) -> dict:
    """The store keeps annual-report facts and quarterly-report facts apart; one {taxo: {tag: {unit: rows}}}, each raw row once."""
    out: dict = {}
    for src in (facts or {}, qfacts or {}):
        for taxo, tg in src.items():
            for tag, units in tg.items():
                for unit, rows in units.items():
                    have = out.setdefault(taxo, {}).setdefault(tag, {}).setdefault(unit, [])
                    seen = {tuple(r[:6]) for r in have}
                    have.extend(r for r in rows if tuple(r[:6]) not in seen)
    return out


def rows_of(facts: Mapping, field: str) -> List[dict]:
    out = []
    for taxo in TAXOS:
        tg = (facts or {}).get(taxo) or {}
        for tag in LADDER[field]:
            for unit, rows in (tg.get(tag) or {}).items():
                for r in rows:
                    start, end, val, accn, filed, form = r[0], r[1], r[2], r[3], r[4], r[5]
                    if start is None or end is None or val is None:
                        continue
                    out.append({"taxo": taxo, "tag": tag, "unit": unit, "start": str(start)[:10], "end": str(end)[:10], "val": float(val),
                                "accn": accn, "filed": str(filed)[:10], "form": form})
    return out


def _cls(r, rng) -> bool:
    return rng[0] <= _days(r["start"], r["end"]) <= rng[1]


def pairs_in_filing(rows, accn, end, rng, prior_end=None) -> Dict[tuple, Tuple[float, float]]:
    pe0 = _d(prior_end) if prior_end else _d(end) - timedelta(days=365)
    cur, pri = {}, {}
    for r in rows:
        if r["accn"] != accn or not _cls(r, rng):
            continue
        k = (r["taxo"], r["tag"], r["unit"])
        if abs(_days(end, r["end"])) <= 3:
            cur.setdefault(k, r["val"])
        elif abs((_d(r["end"]) - pe0).days) <= 12:
            pri.setdefault(k, r["val"])
    return {k: (cur[k], pri[k]) for k in cur if k in pri}


def choose(pairs, field):
    """(key, (cur, prior), note) by the rule above, or (None, None, None)."""
    if not pairs:
        return None, None, None
    units = {k[2] for k in pairs}
    unit = "USD" if "USD" in units else sorted(units, key=lambda u: min(LADDER[field].index(k[1]) for k in pairs if k[2] == u))[0]
    cands = {k: v for k, v in pairs.items() if k[2] == unit}
    if field == "revenue":
        key = sorted(cands, key=lambda k: (-cands[k][0], LADDER[field].index(k[1])))[0]
        gr = {k[1]: (v[0] / v[1] - 1.0) if v[1] > 0 else None for k, v in cands.items()}
        vals = [g for g in gr.values() if g is not None]
        return key, cands[key], {"tags": gr, "disagree_over_1pt": (max(vals) - min(vals) > 0.01) if len(vals) > 1 else False}
    key = sorted(cands, key=lambda k: LADDER[field].index(k[1]))[0]
    return key, cands[key], None


def derived_q4(rows, accn_k, end) -> Dict[tuple, Tuple[float, float]]:
    fy = pairs_in_filing(rows, accn_k, end, QFY)
    out: dict = {}
    if not fy:
        return out
    end9 = None
    for r in rows:
        if r["form"].startswith("10-Q") and _cls(r, Q9M) and 80 <= _days(r["end"], end) <= 100:
            end9 = r["end"]
            break
    if end9 is None:
        return out
    accns = sorted({r["accn"] for r in rows if r["end"] == end9 and _cls(r, Q9M) and r["form"].startswith("10-Q")})
    pe0 = _d(end) - timedelta(days=365)
    for a in accns:
        nine = pairs_in_filing(rows, a, end9, Q9M)
        for k, (c, p) in fy.items():
            if k in nine and k not in out:
                first = sorted((r for r in rows if (r["taxo"], r["tag"], r["unit"]) == k and _cls(r, QFY) and abs((_d(r["end"]) - pe0).days) <= 12),
                               key=lambda r: (r["filed"], r["accn"]))
                if first and p and abs(first[0]["val"] / p - 1.0) > RECAST_TOL:
                    continue
                out[k] = (c - nine[k][0], p - nine[k][1])
    return out


def quarter_measures(facts, accession, period_end, family, tbv) -> dict:
    """{revenue_growth, operating_margin_change, rote_change_annualised_on_tbv_at_T, status, kinds, tags, revenue_tags} for one quarter."""
    if not accession or not period_end:
        return {"status": "no_quarter"}
    got, kinds = {}, {}
    for f in ("revenue", "operating_income", "net_income"):
        rs = rows_of(facts, f)
        p, kinds[f] = pairs_in_filing(rs, accession, period_end, Q3M), "reported_3m"
        if not p:
            p, kinds[f] = derived_q4(rs, accession, period_end), "derived_q4"
        got[f] = choose(p, f)
    out = {"kinds": kinds, "tags": {f: (None if got[f][0] is None else "/".join(got[f][0])) for f in got}, "revenue_tags": got["revenue"][2],
           "revenue_growth": None, "operating_margin_change": None, "rote_change_annualised_on_tbv_at_T": None}
    rk, rv, _ = got["revenue"]
    if rk is not None:
        r1, r0 = rv
        out["revenue_growth"] = (r1 / r0 - 1.0) if r0 > 0 else None
        ok, ov, _ = got["operating_income"]
        if ok is not None and ok[2] == rk[2] and r1 > 0 and r0 > 0:
            out["operating_margin_change"] = ov[0] / r1 - ov[1] / r0
    nk, nv, _ = got["net_income"]
    if family == "financial" and nk is not None and tbv and tbv > 0:
        out["rote_change_annualised_on_tbv_at_T"] = 4.0 * (nv[0] - nv[1]) / tbv
    out["status"] = "ok" if any(out[m] is not None for m in ("revenue_growth", "operating_margin_change", "rote_change_annualised_on_tbv_at_T")) \
        else "no_same_filing_pair"
    return out


def annual_measures(facts, year1_filed, year1_period, base_period) -> dict:
    """Year-1 revenue growth and margin change from the year-1 annual report's own comparative column; plus the net-income pair for the ROTE check."""
    if not (year1_filed and year1_period and base_period):
        return {"status": "no_year1"}
    got = {}
    for f in ("revenue", "operating_income", "net_income"):
        rs = rows_of(facts, f)
        accns = sorted({r["accn"] for r in rs if r["filed"] == str(year1_filed)[:10] and r["form"].startswith(("10-K", "20-F", "40-F"))
                        and abs(_days(year1_period, r["end"])) <= 3})
        p: dict = {}
        for ac in accns:
            for k, v in pairs_in_filing(rs, ac, year1_period, QFY, prior_end=base_period).items():
                p.setdefault(k, v)
        got[f] = choose(p, f)
    out = {"tags": {f: (None if got[f][0] is None else "/".join(got[f][0])) for f in got}, "revenue_tags": got["revenue"][2],
           "revenue_growth": None, "operating_margin_change": None,
           "net_income_pair": None if got["net_income"][0] is None else list(got["net_income"][1])}
    rk, rv, _ = got["revenue"]
    if rk is not None:
        r1, r0 = rv
        out["revenue_growth"] = (r1 / r0 - 1.0) if r0 > 0 else None
        ok, ov, _ = got["operating_income"]
        if ok is not None and ok[2] == rk[2] and r1 > 0 and r0 > 0:
            out["operating_margin_change"] = ov[0] / r1 - ov[1] / r0
    out["status"] = "ok" if (out["revenue_growth"] is not None or out["net_income_pair"] is not None) else "no_same_filing_pair"
    return out


# ---- eligibility (AK.37) ----------------------------------------------------------------------------------------------------------------------------

def manifest_entries(manifest: Mapping) -> List[dict]:
    out: List[dict] = []

    def walk(x):
        if isinstance(x, dict):
            if "form" in x and "filed" in x:
                out.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(manifest or {})
    return out


def _releases_after(entries: Iterable[Mapping], period_end) -> List[dict]:
    return [e for e in entries if str(e.get("form", "")).startswith("8-K") and e.get("kind") == "earnings_release"
            and str(e.get("filed"))[:10] > str(period_end)[:10]]


def quarter_eligibility(entries, period_end, asof) -> dict:
    """Is a quarter a forecast at `asof`?  Not when its earnings release was in the pack, nor when it ended more than STALE_DAYS before `asof`."""
    reasons = []
    rel = _releases_after(entries, period_end)
    if rel:
        reasons.append(f"earnings release in the pack: {sorted({str(e['filed'])[:10] for e in rel})[0]}")
    if _days(period_end, asof) > STALE_DAYS:
        reasons.append(f"quarter ended {_days(period_end, asof)} days before T")
    return {"eligible": not reasons, "reasons": reasons}


def year_eligibility(entries, year1_period, asof, year1_filed=None) -> dict:
    """Is fiscal year 1 a forecast at `asof`?  Not when its annual report was filed on or before `asof` (AK.34), nor when that report, or an
    earnings release filed after the year's end, was in the pack."""
    reasons = []
    if year1_filed is not None and str(year1_filed)[:10] <= str(asof)[:10]:
        reasons.append(f"annual report filed on or before T: {str(year1_filed)[:10]}")
    for e in entries:
        if str(e.get("form", "")).startswith(("10-K", "20-F", "40-F")) and str(year1_period)[:10] in str(e.get("period", "")):
            reasons.append(f"annual report in the pack: {str(e['filed'])[:10]}")
            break
    rel = _releases_after(entries, year1_period)
    if rel:
        reasons.append(f"earnings release after the year end in the pack: {sorted({str(e['filed'])[:10] for e in rel})[0]}")
    return {"eligible": not reasons, "reasons": reasons}
