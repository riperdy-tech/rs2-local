"""baselines.py - the pass-1 baselines of SPEC_rebuild Addendum AE.3, from the quarters known at T only. No outcome is read.

    python -m rebuild_harness.gate2.baselines --state-dir DIR [--workers N]      writes <state>/baselines/baselines.json once (exclusive creation)

THE TARGET of G1 and of the R3a diagnostic is the year-on-year statistic of q1, the first quarter reported after T (Addendum O 2): revenue growth (operating), the
operating-margin change (operating), the annualised ROTE change on tangible book at T (financial).  Each baseline forecasts that statistic from the quarters a company
had reported by 16:00 ET on T, through the very source and eligibility rule of the pack's section Q (`PitQuarterSource`, `documents.eligibility`):
  persistence     the statistic of the latest quarter known at T;
  t4q             the mean of the statistic over the latest four quarters known at T (all four needed, else None);
  pop_median      the cross-sectional median of `persistence` over the gate universe of the date, per family (commodity is out of scope, V3).
A missing input is None, never 0.  The ROTE change of a quarter is 4 x (net income - net income a year earlier) / tangible book at the base fiscal year end known at T,
the stated approximation of outcome_extract.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from . import config

FIELDS = ("revenue", "operating_income", "net_income")
MEASURES = {"operating": ("growth", "margin"), "financial": ("margin",)}      # "margin" is the ROTE change for financials (outcome_extract, scoring._outcome_value)


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def quarter_stats(row: Mapping, family: str, tbv: Optional[float]) -> Dict[str, Optional[float]]:
    v, p = row.get("values") or {}, row.get("prior_year") or {}
    rev, rev0, oi, oi0, ni, ni0 = v.get("revenue"), p.get("revenue"), v.get("operating_income"), p.get("operating_income"), v.get("net_income"), p.get("net_income")
    growth = (rev / rev0 - 1.0) if (_num(rev) and _num(rev0) and rev0 > 0) else None
    if family == "financial":
        margin = (4.0 * (ni - ni0) / tbv) if (_num(ni) and _num(ni0) and _num(tbv) and tbv > 0) else None
    else:
        m1 = (oi / rev) if (_num(oi) and _num(rev) and rev > 0) else None
        m0 = (oi0 / rev0) if (_num(oi0) and _num(rev0) and rev0 > 0) else None
        margin = (m1 - m0) if (m1 is not None and m0 is not None) else None
    return {"growth": growth, "margin": margin}


def company_baselines(rows: List[Mapping], family: str, tbv: Optional[float]) -> dict:
    """{measure: {"persistence", "t4q", "latest_quarter"}} from the eligible rows sorted by period end."""
    rows = sorted(rows, key=lambda r: r["period_end"])
    out = {}
    for m in MEASURES.get(family, ()):
        vals = [quarter_stats(r, family, tbv)[m] for r in rows]
        last4 = vals[-4:]
        out[m] = {"persistence": vals[-1] if vals else None,
                  "t4q": (sum(last4) / 4.0) if (len(last4) == 4 and all(x is not None for x in last4)) else None,
                  "latest_quarter": rows[-1]["period_end"] if rows else None}
    return out


def population_medians(per_company: Mapping[str, dict]) -> Dict[str, Dict[str, Dict[str, Optional[float]]]]:
    """{date: {family: {measure: median of persistence}}} over the companies of each date."""
    acc: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
    for rec in per_company.values():
        for m, b in rec["baselines"].items():
            if b["persistence"] is not None:
                acc.setdefault(rec["date"], {}).setdefault(rec["family"], {}).setdefault(m, []).append(b["persistence"])
    return {d: {f: {m: (statistics.median(v) if v else None) for m, v in ms.items()} for f, ms in fs.items()} for d, fs in acc.items()}


def build(pit, universe: Mapping[str, List[Mapping]], eligibility, tbv_of) -> dict:
    """`universe` = {date: [{cik, family, ticker}]}; `eligibility(accepted_at, filed, asof) -> "ok" | ...`; `tbv_of(cik, date, ticker)`."""
    per: Dict[str, dict] = {}
    for d, comps in sorted(universe.items()):
        for c in comps:
            fam = c["family"]
            if fam in config.OUT_OF_SCOPE_FAMILIES or fam not in MEASURES:
                continue
            cik = str(c["cik"]).zfill(10)
            try:
                rows = pit.quarterly_rows(cik, d, FIELDS, 6) or []
            except Exception as e:                                     # recorded as itself, never a fabricated baseline
                per[f"{d}_{cik}"] = {"date": d, "cik": cik, "family": fam, "baselines": {}, "error": f"{type(e).__name__}: {str(e)[:120]}"}
                continue
            rows = [r for r in rows if eligibility(r.get("accepted_at"), r["filed"], d) == "ok"]
            tbv = tbv_of(cik, d, c.get("ticker")) if fam == "financial" else None
            per[f"{d}_{cik}"] = {"date": d, "cik": cik, "family": fam, "baselines": company_baselines(rows, fam, tbv), "n_quarters": len(rows)}
    return {"companies": per, "pop_median": population_medians(per),
            "rule": "SPEC_rebuild Addendum AE.3: persistence = latest quarter known at T; t4q = mean of the latest four; pop_median = cross-sectional median of persistence "
                    "per date and family over the gate universe; quarters by the pack's own source and eligibility rule"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    from . import env as env_mod
    from valuation.common import build_state
    from valuation.muse.documents import eligibility
    paths = config.state_paths(a.state_dir)
    out = paths["root"] / "baselines" / "baselines.json"
    if out.exists():
        print(f"REFUSED: {out} exists (written once)")
        return 5
    g = env_mod._g1r()
    cfg = env_mod._cfg(state_dir=a.state_dir, rf={}, n_draws=g.gate1.N_DRAWS, store=g.DEFAULT_STORE, id_map=g.DEFAULT_IDMAP,
                       prices_daily=config.WORKSPACE / "data" / "prices_daily", prices_monthly=g.DEFAULT_PRICES, headers=None, crosswalk=None, sic=g.DEFAULT_SIC,
                       priors_dir=None, strict_classification=False)
    g._init(cfg)
    pit = g._ENV["pit"]

    def tbv_of(cik, d, ticker):
        try:
            pc = pit.company_pit(cik, d, ticker)
            return None if pc is None else build_state(pc).get("tbv")
        except Exception:
            return None
    universe = {}
    for d in config.DATES:
        u = json.loads((paths["ctx"] / f"universe_{d}.json").read_text(encoding="utf-8"))
        universe[d] = u["companies"]
    rep = build(pit, universe, eligibility, tbv_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as fh:
        json.dump(rep, fh, default=str)
    n = len(rep["companies"])
    print(json.dumps({"written": str(out), "n_company_dates": n, "errors": sum(1 for r in rep["companies"].values() if r.get("error")), "pop_median": rep["pop_median"]},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
