"""eligible_outcomes.py - the outcome set of record for S5's fit and for gate 2b (SPEC_rebuild AK.37 v2, approved AK.42; REGISTRATION_gate2b section
3's amendment; SPEC_S5 section 4's amendment).

From a registered outcomes file (it fixes WHICH quarter is q1/q2 and which company-dates were scored) it builds, per company-date:
  * the measures, from one filing's own comparative columns (`same_filing`): q1/q2 revenue growth, operating-margin change, the quarterly ROTE change;
    the annual (fiscal-year-1) revenue growth and margin change, year 1 chosen by `outcome_extract.annual_outcomes` on the CURRENT pit_data (with the
    fiscal-year fix, AL.17/AL.18); the annual ROTE change keeps `build_state`'s definition, with a same-filing net-income check reported beside it;
  * total-revenue verification (`same_filing.revenue_scope`): a closure failure ABSTAINS the revenue-based measures; an untestable figure is flagged;
  * eligibility, identical for every arm (`same_filing.quarter_eligibility` / `year_eligibility` / `item_202_public`): a target whose result was
    public before the T cutoff (SEC Item 2.02, the pack, or the annual report on or before T), or a quarter ended over 120 days before T, leaves the
    scored set;
  * the register: every exclusion with company, T, target, period, metric(s), source, timestamp and reason; original and eligible counts.
It reads raw facts, SEC's companyfacts zip (closure) and submissions zip (Item 2.02), and each run's pack manifest; it reads no forecast.

    python -m rebuild_harness.gate2.eligible_outcomes --state-dir RUN --registered OUTCOMES.jsonl --store STORE --companyfacts ZIP
        --submissions ZIP --scoring-date D --out DIR
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Mapping, Optional

from . import same_filing as sf

REVENUE_MEASURES = ("revenue_growth", "operating_margin_change")
Q_MEASURES = ("revenue_growth", "operating_margin_change", "rote_change_annualised_on_tbv_at_T")


class Sources:
    """Lazy per-company access to the store, the raw companyfacts and the submissions (one company in memory at a time)."""

    def __init__(self, store, companyfacts_zip, submissions_zip):
        from valuation.pit_data import PitData
        self.pit = PitData(store)
        self.cf = zipfile.ZipFile(companyfacts_zip)
        self.sub = zipfile.ZipFile(submissions_zip)
        self._cf_names, self._sub_names = set(self.cf.namelist()), set(self.sub.namelist())

    def facts(self, cik):
        c = self.pit.company(str(cik).zfill(10))
        return sf.merged(c.facts, c.qfacts) if c else {}

    def companyfacts(self, cik):
        n = f"CIK{str(cik).zfill(10)}.json"
        return json.loads(self.cf.read(n)) if n in self._cf_names else {}

    def submissions(self, cik):
        n = f"CIK{str(cik).zfill(10)}.json"
        return json.loads(self.sub.read(n)) if n in self._sub_names else {}


def run_record(state_dir, key):
    """(tbv_0 at T, pack manifest entries) from the run's own files."""
    for line in (Path(state_dir) / "progress.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["key"] == key and r.get("run_dir"):
            rd = Path(state_dir) / r["run_dir"]
            res = json.loads((rd / "result.json").read_text(encoding="utf-8")) if (rd / "result.json").exists() else {}
            tbv = (((res.get("code_only") or {}).get("result") or {}).get("at_median_inputs") or {}).get("tbv_0")
            man = json.loads((rd / "pack.json").read_text(encoding="utf-8")).get("manifest", {}) if (rd / "pack.json").exists() else {}
            return tbv, sf.manifest_entries(man)
    return None, []


def _scope(src, cik, t, accession, end):
    tag = (t.get("tags") or {}).get("revenue")
    if not tag:
        return {"status": "no_revenue"}
    _x, rtag, unit = tag.split("/")
    return sf.revenue_scope(src.companyfacts(cik), rtag, unit, len(((t.get("revenue_tags") or {}).get("tags") or {})), accession, end,
                            (t.get("kinds") or {}).get("revenue", "reported_3m"))


def quarter(src, o, qn, tbv, entries, register):
    q = ((o.get("quarters") or {}).get(qn)) or None
    if not q or not q.get("accession"):
        return None, {"status": "no_registered_quarter"}
    T = o["key"][:10]
    m = sf.quarter_measures(src.facts(o["cik"]), q["accession"], q["period_end"], o.get("family"), tbv)
    scope = _scope(src, o["cik"], m, q["accession"], q["period_end"]) if m.get("revenue_growth") is not None else {"status": "no_revenue"}
    elig = sf.quarter_eligibility(entries, q["period_end"], T)
    pub = sf.item_202_public(src.submissions(o["cik"]), q["period_end"], T)
    if pub:
        elig = {"eligible": False, "reasons": elig["reasons"] + [f"SEC Item 2.02 8-K accepted {pub['accepted'] or pub['filed']} ({pub['accession']})"]}
    out = {k: m.get(k) for k in Q_MEASURES}
    out.update(period_end=q["period_end"], filed=q.get("filed"), accession=q["accession"])
    detail = {"measure": {k: m.get(k) for k in ("status", "kinds", "tags", "revenue_tags")}, "scope": scope, "eligibility": elig}
    if scope.get("status") == "closure_fail":
        for k in REVENUE_MEASURES:
            out[k] = None
        register.append({"key": o["key"], "cik": o["cik"], "T": T, "target": qn, "period": q["period_end"], "metrics": list(REVENUE_MEASURES),
                         "source": "same-filing closure test", "timestamp": None, "reason": f"revenue is not verified total: {scope.get('tests')}"})
    if not elig["eligible"]:
        register.append({"key": o["key"], "cik": o["cik"], "T": T, "target": qn, "period": q["period_end"], "metrics": list(Q_MEASURES),
                         "source": "; ".join(elig["reasons"]), "timestamp": (pub or {}).get("accepted"), "reason": "result public before the T cutoff"
                         if any("release" in r or "Item 2.02" in r for r in elig["reasons"]) else "stale quarter (over 120 days before T)"})
        out = dict(out, **{k: None for k in Q_MEASURES})
    return out, detail


def annual(src, o, entries, scoring_date, register):
    from valuation.common import build_state
    from .outcome_extract import annual_outcomes
    cik, T = str(o["cik"]).zfill(10), o["key"][:10]
    a = annual_outcomes(lambda c, d: src.pit.company_pit(c, d, o.get("ticker")), build_state, cik, T, scoring_date)
    if a.get("status") != "ok":
        return {"status": a.get("status"), "rote_change": None, "revenue_growth": None, "operating_margin_change": None}, {"identity": a}
    m = sf.annual_measures(src.facts(cik), a["year1_filed"], a["year1_period"], a["base_period"])
    t_acc = None                                                       # the year-1 report's accession, for the closure test
    for r in sf.rows_of(src.facts(cik), "revenue"):
        if r["filed"] == str(a["year1_filed"])[:10] and abs(sf._days(a["year1_period"], r["end"])) <= 3 and r["form"].startswith(("10-K", "20-F", "40-F")):
            t_acc = r["accn"]
            break
    scope = _scope(src, cik, dict(m, kinds={"revenue": "annual"}), t_acc, a["year1_period"]) if (m.get("revenue_growth") is not None and t_acc) \
        else {"status": "no_revenue"}
    elig = sf.year_eligibility(entries, a["year1_period"], T, a["year1_filed"])
    pub = sf.item_202_public(src.submissions(cik), a["year1_period"], T)
    if pub:
        elig = {"eligible": False, "reasons": elig["reasons"] + [f"SEC Item 2.02 8-K accepted {pub['accepted'] or pub['filed']} ({pub['accession']})"]}
    out = {"status": "ok", "base_period": a["base_period"], "year1_period": a["year1_period"], "year1_filed": a["year1_filed"],
           "revenue_growth": m.get("revenue_growth"), "operating_margin_change": m.get("operating_margin_change"), "rote_change": a.get("rote_change")}
    ni = m.get("net_income_pair")
    detail = {"identity": {k: a[k] for k in ("base_period", "year1_period", "year1_filed")}, "measure": {k: m.get(k) for k in ("status", "tags", "revenue_tags")},
              "scope": scope, "eligibility": elig, "net_income_same_filing": ni}
    if scope.get("status") == "closure_fail":
        out.update(revenue_growth=None, operating_margin_change=None)
        register.append({"key": o["key"], "cik": cik, "T": T, "target": "annual", "period": a["year1_period"], "metrics": list(REVENUE_MEASURES),
                         "source": "same-filing closure test", "timestamp": None, "reason": f"revenue is not verified total: {scope.get('tests')}"})
    if not elig["eligible"]:
        register.append({"key": o["key"], "cik": cik, "T": T, "target": "annual", "period": a["year1_period"],
                         "metrics": ["revenue_growth", "operating_margin_change", "rote_change"], "source": "; ".join(elig["reasons"]),
                         "timestamp": (pub or {}).get("accepted"), "reason": "year-1 result public before the T cutoff"})
        out.update(status="ineligible_public_at_T", revenue_growth=None, operating_margin_change=None, rote_change=None)
    return out, detail


def build(state_dir, registered, src: Sources, scoring_date, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    register, counts = [], {"rows": 0, "q1": {"original": 0, "eligible": 0}, "annual": {"original": 0, "eligible": 0},
                            "scope_q1": {}, "scope_annual": {}}
    with open(out_dir / f"outcomes_eligible_{scoring_date}.jsonl", "x", encoding="utf-8") as fo:
        for line in Path(registered).read_text(encoding="utf-8").splitlines():
            o = json.loads(line)
            counts["rows"] += 1
            tbv, entries = run_record(state_dir, o["key"])
            tbv = tbv if o.get("family") == "financial" else None
            new = {k: o.get(k) for k in ("key", "date", "cik", "ticker", "sample_ticker", "family", "returns")}
            new["quarters"], detail = {}, {}
            for qn in ("q1", "q2"):
                q, d = quarter(src, o, qn, tbv, entries, register)
                new["quarters"][qn], detail[qn] = q, d
            if (o.get("quarters") or {}).get("q1"):
                counts["q1"]["original"] += 1
                s = detail["q1"].get("scope", {}).get("status")
                counts["scope_q1"][s] = counts["scope_q1"].get(s, 0) + 1
                counts["q1"]["eligible"] += bool(detail["q1"].get("eligibility", {}).get("eligible"))
            new["annual"], detail["annual"] = annual(src, o, entries, scoring_date, register)
            if detail["annual"].get("eligibility") is not None:
                counts["annual"]["original"] += 1
                counts["annual"]["eligible"] += bool(detail["annual"]["eligibility"].get("eligible"))
                s = detail["annual"].get("scope", {}).get("status")
                counts["scope_annual"][s] = counts["scope_annual"].get(s, 0) + 1
            new["registered"] = {"quarters": o.get("quarters"), "annual": o.get("annual")}
            new["detail"] = detail
            fo.write(json.dumps(new, default=str) + "\n")
    with open(out_dir / f"register_{scoring_date}.jsonl", "x", encoding="utf-8") as fr:
        for r in register:
            fr.write(json.dumps(r, default=str) + "\n")
    counts["register_entries"] = len(register)
    (out_dir / f"summary_{scoring_date}.json").write_text(json.dumps(counts, indent=1), encoding="utf-8")
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--registered", type=Path, required=True)
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--companyfacts", type=Path, required=True)
    ap.add_argument("--submissions", type=Path, required=True)
    ap.add_argument("--scoring-date", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    res = build(a.state_dir, a.registered, Sources(a.store, a.companyfacts, a.submissions), a.scoring_date, a.out)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
