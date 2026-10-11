"""baselines.py - the pass-1 baselines of SPEC_rebuild Addendum AE.3, from the quarters known at T only. No outcome is read.

    python -m rebuild_harness.gate2.baselines --state-dir DIR [--workers N]      writes <state>/baselines/baselines_v2.json once (exclusive creation)

THE TARGET of G1 and of the R3a diagnostic is the year-on-year statistic of q1, the first quarter reported after T (Addendum O 2): revenue growth (operating), the
operating-margin change (operating), the annualised ROTE change on tangible book at T (financial).  Each baseline forecasts that statistic from the quarters a company
had reported by 16:00 ET on T, through the very source and eligibility rule of the pack's section Q (`PitQuarterSource`, `documents.eligibility`):
  persistence     the statistic of the latest quarter known at T;
  t4q             the mean of the statistic over the latest four quarters known at T (all four needed, else None);
  pop_median      the cross-sectional median of `persistence` over the gate universe of the date, per family (commodity is out of scope, V3).
A missing input is None, never 0.  The ROTE change of a quarter is 4 x (net income - net income a year earlier) / tangible book at the base fiscal year end known at T,
the stated approximation of outcome_extract.

THE ANNUAL-CONVENTION RUN-RATE (Addendum AH, the approved C1 fix): the engines forecast fiscal year 1, so the fair base rate forecasts the same annual quantity:
  runrate             from the latest four contiguous quarters known at T (each period end 80-100 days after the one before): growth = their revenue over the same
                      quarters a year earlier - 1; margin change = their operating income / revenue - the base-year operating margin; ROTE change (financial) =
                      their net income / the base-year ROTE denominator of `build_state` - `rote_latest` (the same denominator, so the change has no basis bias);
  pop_median_runrate  the cross-sectional median of `runrate` per date and family.
The base-year figures come from the engines' own `build_state` at T, the very `base_year` the Muse arms are measured from.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import date
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from . import config

FIELDS = ("revenue", "operating_income", "net_income")
BASELINES_FILE = "baselines_v2.json"                                           # v2 adds the run-rate (Addendum AH); v1 (AE.3 only) is kept as written
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


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days


def _rote_denominator(st: Mapping) -> Optional[float]:
    """The denominator `build_state` divides base-year net income by for `rote_latest`: base-year tangible book, averaged with the year before when filed."""
    ts, pe = st.get("tbv_series") or {}, st.get("base_period")
    if pe not in ts:
        return None
    tp = sorted(ts)
    i = tp.index(pe)
    return ts[pe] if i == 0 else 0.5 * (ts[pe] + ts[tp[i - 1]])


def runrate(rows: List[Mapping], family: str, st: Optional[Mapping]) -> Dict[str, Optional[float]]:
    """{measure: the annual-convention run-rate forecast of the measure's year-1 change} from the eligible rows (see the module docstring)."""
    out: Dict[str, Optional[float]] = {m: None for m in MEASURES.get(family, ())}
    rows = sorted(rows, key=lambda r: r["period_end"])[-4:]
    if len(rows) < 4 or any(not (80 <= _days(a["period_end"], b["period_end"]) <= 100) for a, b in zip(rows, rows[1:])):
        return out

    def tot(key, f):
        xs = [(r.get(key) or {}).get(f) for r in rows]
        return sum(xs) if all(_num(x) for x in xs) else None
    st = st or {}
    rev, rev0, oi, ni = tot("values", "revenue"), tot("prior_year", "revenue"), tot("values", "operating_income"), tot("values", "net_income")
    if family == "financial":
        den, base = _rote_denominator(st), st.get("rote_latest")
        out["margin"] = (ni / den - base) if (ni is not None and _num(den) and den > 0 and _num(base)) else None
        return out
    out["growth"] = (rev / rev0 - 1.0) if (rev is not None and rev0 is not None and rev0 > 0) else None
    base = st.get("op_margin")
    out["margin"] = (oi / rev - base) if (oi is not None and rev is not None and rev > 0 and _num(base)) else None
    return out


def population_medians(per_company: Mapping[str, dict], arm: str = "persistence") -> Dict[str, Dict[str, Dict[str, Optional[float]]]]:
    """{date: {family: {measure: median of the arm}}} over the companies of each date (`arm` = "persistence" or "runrate")."""
    acc: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
    for rec in per_company.values():
        src = {m: b.get("persistence") for m, b in rec["baselines"].items()} if arm == "persistence" else (rec.get("runrate") or {})
        for m, v in src.items():
            if v is not None:
                acc.setdefault(rec["date"], {}).setdefault(rec["family"], {}).setdefault(m, []).append(v)
    return {d: {f: {m: (statistics.median(v) if v else None) for m, v in ms.items()} for f, ms in fs.items()} for d, fs in acc.items()}


def build(pit, universe: Mapping[str, List[Mapping]], eligibility, state_of) -> dict:
    """`universe` = {date: [{cik, family, ticker}]}; `eligibility(accepted_at, filed, asof) -> "ok" | ...`; `state_of(cik, date, ticker)` -> the engines'
    `build_state` at T, or None."""
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
            st = state_of(cik, d, c.get("ticker"))
            tbv = (st or {}).get("tbv") if fam == "financial" else None
            per[f"{d}_{cik}"] = {"date": d, "cik": cik, "family": fam, "baselines": company_baselines(rows, fam, tbv), "runrate": runrate(rows, fam, st),
                                 "n_quarters": len(rows)}
    return {"companies": per, "pop_median": population_medians(per), "pop_median_runrate": population_medians(per, "runrate"),
            "rule": "SPEC_rebuild Addendum AE.3: persistence = latest quarter known at T; t4q = mean of the latest four; pop_median = cross-sectional median of persistence "
                    "per date and family over the gate universe; quarters by the pack's own source and eligibility rule. Addendum AH: runrate = the four contiguous "
                    "quarters known at T against the build_state base year; pop_median_runrate = its median per date and family"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    from . import env as env_mod
    from valuation.common import build_state
    from valuation.muse.documents import eligibility
    paths = config.state_paths(a.state_dir)
    out = paths["root"] / "baselines" / BASELINES_FILE
    if out.exists():
        print(f"REFUSED: {out} exists (written once)")
        return 5
    g = env_mod._g1r()
    cfg = env_mod._cfg(state_dir=a.state_dir, rf={}, n_draws=g.gate1.N_DRAWS, store=g.DEFAULT_STORE, id_map=g.DEFAULT_IDMAP,
                       prices_daily=config.WORKSPACE / "data" / "prices_daily", prices_monthly=g.DEFAULT_PRICES, headers=None, crosswalk=None, sic=g.DEFAULT_SIC,
                       priors_dir=None, strict_classification=False)
    g._init(cfg)
    pit = g._ENV["pit"]

    def state_of(cik, d, ticker):
        try:
            pc = pit.company_pit(cik, d, ticker)
            return None if pc is None else build_state(pc)
        except Exception:
            return None
    universe = {}
    for d in config.DATES:
        u = json.loads((paths["ctx"] / f"universe_{d}.json").read_text(encoding="utf-8"))
        universe[d] = u["companies"]
    rep = build(pit, universe, eligibility, state_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as fh:
        json.dump(rep, fh, default=str)
    n = len(rep["companies"])
    print(json.dumps({"written": str(out), "n_company_dates": n, "errors": sum(1 for r in rep["companies"].values() if r.get("error")), "pop_median": rep["pop_median"]},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
