"""The tag-consistent gate-2 outcomes (SPEC_rebuild AK.27-AK.30; operator 2026-10-13: "tag-consistent governs").

Every growth and margin change is measured inside ONE filing: the filing that first reported the outcome period also reports the comparative period,
and both are taken under one XBRL tag and one unit.  So a revenue series can never be joined across two tags (AL.7).  Rules, fixed before any outcome
was read:
  * q1 (and q2): the quarter's own filing (`accession` of the registered outcome).  A 3-month pair (the quarter, and the quarter ending about a year
    earlier) in that filing, same taxonomy, tag and unit.  If the filing has none (a fourth quarter, filed in a 10-K), a derived Q4: fiscal year minus
    nine months for both years, with ONE tag present for both periods in both filings (the 10-K and the third-quarter 10-Q).
  * the annual target: the year-1 10-K (filed on `year1_filed`, period `year1_period`) and its own comparative column for year 0.
  * revenue: among the ladder's tags present for both periods, the LARGEST current-period value within one unit (a total is never smaller than a line
    within it, AK.28; one unit only, AK.29); USD when present.  Operating income and net income: the first ladder tag present for both periods.
  * ROTE (financials, quarterly): 4 x (net income - net income a year earlier) / tangible book at T (`tbv_0` of the run's own result, the registered
    denominator), the registered approximation with a tag-consistent numerator.  The ANNUAL ROTE change is not rebuilt (it rests on equity instants,
    not the revenue seam); the registered value is kept and flagged.
  * a row without a tag-consistent figure is listed with its reason; it is excluded from the governing version only (AK.30).
Reads raw facts only (the store's `company(cik).facts`, or the refreshed companyfacts in it); none of the extractor's tag-choice logic.  The tag lists are
copied from `pit_data.quarter_fields()` and a test checks they still agree.  Writes nothing into the run's state.

    python tag_consistent.py rescore  --state-dir RUN2 --outcomes OUTCOMES.jsonl --store NEW_STORE --baselines FILE --out DIR
    python tag_consistent.py drytest  --state-dir RUN2 --store PACKS_STORE --out DIR [--limit N]      (quarters filed BEFORE T only: reads no outcome)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
TAXOS = ("us-gaap", "ifrs-full")
LADDER = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "Revenue", "RevenueFromContractsWithCustomers"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
}
Q3M, Q9M, QFY = (80, 100), (250, 290), (350, 380)


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _days(a, b):
    return (_d(b) - _d(a)).days


def rows_of(facts, field):
    """Raw duration rows of `field`'s ladder tags: dicts with taxo, tag, unit, start, end, val, accn, filed, form."""
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


def _cls(r, rng):
    d = _days(r["start"], r["end"])
    return rng[0] <= d <= rng[1]


def pairs_in_filing(rows, accn, end, rng, prior_end=None):
    """{(taxo, tag, unit): (current value, prior value)} from ONE filing: the period of length class `rng` ending at `end` (+-3 days) and the one
    ending about a year earlier (+-12 days, or at `prior_end`), both in `accn`."""
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
    """(key, (cur, prior)) by the AK.28/AK.29 rule, or (None, None); plus the revenue disagreement note."""
    if not pairs:
        return None, None, None
    units = {k[2] for k in pairs}
    unit = "USD" if "USD" in units else sorted(units, key=lambda u: min(LADDER[field].index(k[1]) for k in pairs if k[2] == u))[0]
    cands = {k: v for k, v in pairs.items() if k[2] == unit}
    if field == "revenue":
        key = sorted(cands, key=lambda k: (-cands[k][0], LADDER[field].index(k[1])))[0]
        gr = {k[1]: (v[0] / v[1] - 1.0) if v[1] > 0 else None for k, v in cands.items()}
        vals = [g for g in gr.values() if g is not None]
        note = {"tags": gr, "disagree_over_1pt": (max(vals) - min(vals) > 0.01) if len(vals) > 1 else False}
        return key, cands[key], note
    key = sorted(cands, key=lambda k: LADDER[field].index(k[1]))[0]
    return key, cands[key], None


def derived_q4(rows, accn_k, end):
    """{key: (cur Q4, prior Q4)}: FY minus 9M for both years, one tag across the 10-K (`accn_k`) and a 10-Q holding the 9M pair."""
    fy = pairs_in_filing(rows, accn_k, end, QFY)
    out = {}
    if not fy:
        return out
    end9 = None
    for r in rows:                                                      # the 9-month period ending about a quarter before the year end
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
                # RECAST GUARD (AK.31): the two legs come from two filings.  If the 10-K's prior-year figure differs from the one first filed for that
                # year under the same tag, the company recast in between and the 10-Q's nine months are on the old basis: no like-for-like Q4.
                first = sorted((r for r in rows if (r["taxo"], r["tag"], r["unit"]) == k and _cls(r, QFY) and abs((_d(r["end"]) - pe0).days) <= 12),
                               key=lambda r: (r["filed"], r["accn"]))
                if first and p and abs(first[0]["val"] / p - 1.0) > 0.005:
                    continue
                out[k] = (c - nine[k][0], p - nine[k][1])
    return out


def quarter_tc(facts, q, family, tbv):
    """The tag-consistent measures of one registered quarter outcome `q` (period_end, accession), or a reason."""
    if not q or not q.get("accession") or not q.get("period_end"):
        return {"status": "no_registered_quarter"}
    accn, end = q["accession"], q["period_end"]
    got, kind = {}, "reported_3m"
    for f in ("revenue", "operating_income", "net_income"):
        rs = rows_of(facts, f)
        p = pairs_in_filing(rs, accn, end, Q3M)
        if not p:
            p, kind = derived_q4(rs, accn, end), "derived_q4"
        got[f] = choose(p, f)
    out = {"status": "ok", "kind": kind, "tags": {f: (None if got[f][0] is None else "/".join(got[f][0])) for f in got}, "revenue_tags": got["revenue"][2]}
    rk, rv, _n = got["revenue"]
    if rk is None:
        return dict(out, status="no_same_filing_revenue_pair")
    r1, r0 = rv
    out["revenue_growth"] = (r1 / r0 - 1.0) if r0 > 0 else None
    ok, ov, _ = got["operating_income"]
    if ok is not None and ok[2] == rk[2] and r1 > 0 and r0 > 0:
        out["operating_margin_change"] = ov[0] / r1 - ov[1] / r0
    else:
        out["operating_margin_change"] = None
    nk, nv, _ = got["net_income"]
    out["rote_change_annualised_on_tbv_at_T"] = (4.0 * (nv[0] - nv[1]) / tbv) if (family == "financial" and nk is not None and tbv and tbv > 0) else None
    return out


def annual_tc(facts, a):
    """Tag-consistent fiscal-year-1 revenue growth and margin change from the year-1 10-K's own comparative column."""
    if not a or a.get("status") != "ok" or not a.get("year1_filed") or not a.get("year1_period") or not a.get("base_period"):
        return {"status": "registered_not_ok"}
    got = {}
    for f in ("revenue", "operating_income"):
        rs = rows_of(facts, f)
        accns = sorted({r["accn"] for r in rs if r["filed"] == a["year1_filed"] and r["form"].startswith("10-K") and abs(_days(a["year1_period"], r["end"])) <= 3})
        p = {}
        for ac in accns:
            for k, v in pairs_in_filing(rs, ac, a["year1_period"], QFY, prior_end=a["base_period"]).items():
                p.setdefault(k, v)
        got[f] = choose(p, f)
    rk, rv, note = got["revenue"]
    if rk is None:
        return {"status": "no_same_filing_revenue_pair"}
    r1, r0 = rv
    out = {"status": "ok", "tags": {f: (None if got[f][0] is None else "/".join(got[f][0])) for f in got}, "revenue_tags": note,
           "revenue_growth": (r1 / r0 - 1.0) if r0 > 0 else None}
    ok, ov, _ = got["operating_income"]
    out["operating_margin_change"] = (ov[0] / r1 - ov[1] / r0) if (ok is not None and ok[2] == rk[2] and r1 > 0 and r0 > 0) else None
    return out


def tbv_of_run(state_dir, key):
    """`tbv_0` at T from the run's own result (the registered ROTE denominator)."""
    prog = {}
    for line in (Path(state_dir) / "progress.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        prog[r["key"]] = r
    r = prog.get(key)
    if not r or not r.get("run_dir"):
        return None
    try:
        res = json.loads((Path(state_dir) / r["run_dir"] / "result.json").read_text(encoding="utf-8"))
        return ((res.get("code_only") or {}).get("result") or {}).get("at_median_inputs", {}).get("tbv_0")
    except (OSError, ValueError):
        return None


GROWTH_TOL, MARGIN_TOL = 0.01, 0.001


def rebuild(outcomes_path, state_dir, company_facts, out_path):
    """Write the tag-consistent outcomes file (same schema; measures replaced; the registered ones kept under `registered`), and return the counts."""
    counts = {"rows": 0, "q1_ok": 0, "q1_none": {}, "annual_ok": 0, "annual_none": {}, "differ": {}, "revenue_tags_disagree": 0}
    with open(out_path, "x", encoding="utf-8") as fo:
        for line in Path(outcomes_path).read_text(encoding="utf-8").splitlines():
            o = json.loads(line)
            counts["rows"] += 1
            facts = company_facts(o["cik"])
            tbv = tbv_of_run(state_dir, o["key"]) if o.get("family") == "financial" else None
            reg = {"quarters": json.loads(json.dumps(o.get("quarters"))), "annual": json.loads(json.dumps(o.get("annual")))}
            tc_detail = {}
            for qn in ("q1", "q2"):
                q = (o.get("quarters") or {}).get(qn)
                if not q:
                    continue
                t = quarter_tc(facts, q, o.get("family"), tbv)
                tc_detail[qn] = t
                for m, tol in (("revenue_growth", GROWTH_TOL), ("operating_margin_change", MARGIN_TOL), ("rote_change_annualised_on_tbv_at_T", MARGIN_TOL)):
                    new = t.get(m) if t.get("status") == "ok" else None
                    old = q.get(m)
                    if qn == "q1":
                        if old is not None and new is not None and abs(new - old) > tol:
                            counts["differ"][f"q1.{m}"] = counts["differ"].get(f"q1.{m}", 0) + 1
                        if old is not None and new is None:
                            counts["q1_none"][m] = counts["q1_none"].get(m, 0) + 1
                    q[m] = new
                if qn == "q1" and t.get("status") == "ok":
                    counts["q1_ok"] += 1
                    if (t.get("revenue_tags") or {}).get("disagree_over_1pt"):
                        counts["revenue_tags_disagree"] += 1
            a = o.get("annual")
            if a:
                t = annual_tc(facts, a)
                tc_detail["annual"] = t
                if t.get("status") == "ok":
                    counts["annual_ok"] += 1
                for m, tol in (("revenue_growth", GROWTH_TOL), ("operating_margin_change", MARGIN_TOL)):
                    new = t.get(m) if t.get("status") == "ok" else None
                    old = a.get(m)
                    if old is not None and new is not None and abs(new - old) > tol:
                        counts["differ"][f"annual.{m}"] = counts["differ"].get(f"annual.{m}", 0) + 1
                    if old is not None and new is None:
                        counts["annual_none"][m] = counts["annual_none"].get(m, 0) + 1
                    a[m] = new
                if a.get("rote_change") is not None:
                    tc_detail.setdefault("annual", {})["rote_change"] = "registered_kept_not_rebuilt"
            o["registered"] = reg
            o["tag_consistent"] = tc_detail
            fo.write(json.dumps(o, default=str) + "\n")
    return counts


def merged(facts, qfacts):
    """The store keeps annual-report facts (`facts`) and quarterly-report facts (`qfacts`) apart; both are raw rows of the same shape.  One
    {taxo: {tag: {unit: rows}}}, each row once."""
    out = {}
    for src in (facts or {}, qfacts or {}):
        for taxo, tg in src.items():
            for tag, units in tg.items():
                for unit, rows in units.items():
                    have = out.setdefault(taxo, {}).setdefault(tag, {}).setdefault(unit, [])
                    seen = {tuple(r[:6]) for r in have}
                    have.extend(r for r in rows if tuple(r[:6]) not in seen)
    return out


def _store_facts(store):
    sys.path.insert(0, str(DEV))
    from valuation.pit_data import PitData
    pit = PitData(store)
    cache = {}

    def get(cik):
        cik = str(cik).zfill(10)
        if cik not in cache:
            c = pit.company(cik)
            cache.clear()                                               # one company in memory at a time
            cache[cik] = None if c is None else merged(c.facts, getattr(c, "qfacts", None))
        return cache[cik]
    return get, pit


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("rescore", "drytest"))
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--outcomes", type=Path)
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--baselines", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--draws", type=int)
    a = ap.parse_args(argv)
    if (a.out.resolve() == a.state_dir.resolve()) or (a.state_dir.resolve() in a.out.resolve().parents):
        sys.exit("REFUSED: the audit writes nothing into the run's state")
    a.out.mkdir(parents=True, exist_ok=True)
    get, pit = _store_facts(a.store)
    if a.stage == "drytest":
        return drytest(a, get, pit)
    tc_path = a.out / "outcomes_tag_consistent.jsonl"
    counts = rebuild(a.outcomes, a.state_dir, get, tc_path)
    (a.out / "tag_consistent_counts.json").write_text(json.dumps(counts, indent=1), encoding="utf-8")
    print(json.dumps(counts, indent=1))
    sys.path.insert(0, str(DEV))
    from rebuild_harness.gate2 import config as gcfg, score_day
    res = score_day.run_stages(a.state_dir, tc_path, a.baselines, None, a.out / "scored",
                               {"mode": "SCORING, TAG-CONSISTENT OUTCOMES (AK.30: the version of record)", "scoring_date": a.outcomes.stem.split("_")[-1],
                                "registered_outcomes": str(a.outcomes), "counts": counts}, a.draws or gcfg.BOOT_DRAWS)
    print(json.dumps(res, indent=1))
    return 0 if res["mismatches"] == 0 else 1


def drytest(a, get, pit):
    """On quarters filed BEFORE T only (no outcome is read): for each sample company-date, the latest quarter known at T, measured by the extractor
    (`quarterly_rows`, first-filed) and by the same-filing rule; agreement and every disagreement listed with its tags."""
    sys.path.insert(0, str(DEV))
    from rebuild_harness.gate2 import sample as sample_mod
    smp = sample_mod.load_verified(sample_mod.sample_path(a.state_dir))
    jobs = sample_mod.jobs(smp)[: a.limit] if a.limit else sample_mod.jobs(smp)
    res = {"n": 0, "compared": 0, "agree_growth": 0, "agree_margin": 0, "no_pair": 0, "kinds": {}, "disagree": [], "revenue_tags_disagree": 0}
    for j in jobs:
        cik, T = str(j["cik"]).zfill(10), j["date"]
        res["n"] += 1
        try:
            rows = pit.quarterly_rows(cik, T, ("revenue", "operating_income", "net_income"), 1, "first_filed")
        except Exception as e:
            res.setdefault("errors", []).append(f"{cik} {T}: {type(e).__name__}")
            continue
        if not rows:
            continue
        r = rows[-1]
        if str(r["filed"])[:10] >= T:
            continue
        v, p = r["values"], r["prior_year"]
        ext_g = (v["revenue"] / p["revenue"] - 1.0) if (v.get("revenue") and p.get("revenue")) else None
        ext_m = (v["operating_income"] / v["revenue"] - p["operating_income"] / p["revenue"]) if all(
            x is not None for x in (v.get("operating_income"), v.get("revenue"), p.get("operating_income"), p.get("revenue"))) and v["revenue"] > 0 and p["revenue"] > 0 else None
        t = quarter_tc(get(cik), {"accession": r["accession"], "period_end": r["period_end"]}, j.get("family"), None)
        if t.get("status") != "ok":
            res["no_pair"] += 1
            continue
        res["kinds"][t["kind"]] = res["kinds"].get(t["kind"], 0) + 1
        if (t.get("revenue_tags") or {}).get("disagree_over_1pt"):
            res["revenue_tags_disagree"] += 1
        if ext_g is None or t.get("revenue_growth") is None:
            continue
        res["compared"] += 1
        g_ok = abs(ext_g - t["revenue_growth"]) <= GROWTH_TOL
        m_ok = ext_m is None or t.get("operating_margin_change") is None or abs(ext_m - t["operating_margin_change"]) <= MARGIN_TOL
        res["agree_growth"] += g_ok
        res["agree_margin"] += m_ok
        if not (g_ok and m_ok):
            res["disagree"].append({"key": f"{T}_{cik}", "period_end": r["period_end"], "accession": r["accession"], "extractor_growth": ext_g,
                                    "same_filing_growth": t["revenue_growth"], "extractor_margin_change": ext_m,
                                    "same_filing_margin_change": t.get("operating_margin_change"), "tags": t["tags"], "kind": t["kind"],
                                    "revenue_tags": t.get("revenue_tags")})
    (a.out / "drytest.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "disagree"}, indent=1), "\ndisagreements:", len(res["disagree"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
