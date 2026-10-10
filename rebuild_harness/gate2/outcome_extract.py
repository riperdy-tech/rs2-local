"""outcome_extract.py - the gate-2 outcomes of one company-date, at a scoring date (registration section 3).  The only module of this package that reads a return or a filing
made after T; the replay runner never imports it.

    python -m rebuild_harness.gate2.outcome_extract --scoring-date YYYY-MM-DD [--state-dir DIR] [--delisting-index DIR --delisting-docs DIR] ...

FORECAST OUTCOMES.  "The next one and two fiscal quarters' revenue growth and operating margin (ROTE for financials), first reported after T."
  * Quarters come from the shared layer in its OUTCOME mode (`PitData.quarterly_rows(cik, None, ..., mode="first_filed")`: the first value reported for each quarter, never a later
    restatement), with the quarter a year earlier as the comparative of the same row.
  * q1 is the earliest quarter whose first report was filed AFTER T (a quarter that ended before T but was reported after it is q1, as it is the next quarter to be reported);
    q2 is the quarter that follows it (a period end 80-100 days later); a gap leaves q2 empty, never bridged.
  * revenue growth = revenue / revenue a year earlier - 1; operating margin = operating income / revenue; ROTE (financials) = 4 x quarterly net income / tangible book at the
    base fiscal year end known at T (`tbv` from the engines' own state): the layer holds no quarterly tangible equity, so this is a STATED APPROXIMATION and says so in its field name
    (`rote_annualised_on_tbv_at_T`).
The engines forecast a fiscal YEAR; the forecast for a quarter is the engine's year-1 forecast (growth of year 1; the year-1 margin or ROTE), the same convention for both arms (the
pairing of registration section 4 cancels its bias).  q1 lies in year 1 whenever T is within a year of the base year's end; q2 may lie in year 2, so only q1 carries the hard bar.

RETURN OUTCOMES.  `rebuild_harness.outcomes.horizon_outcomes`: excess return over SPY from the next session's open (adjusted), at 3, 6 and 12 months where the horizon has elapsed by the
scoring date, each with the three delisting bounds (`excluded`, `minus100`, `last_close`).  A horizon that has not elapsed is absent, never a partial.

THE OUTPUT is `outcomes/outcomes_<scoring date>.jsonl`, one line per (company, date) of the sample whose run finished; written once per scoring date (exclusive creation).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from . import config

OUTCOME_MODE = "first_filed"
FIELDS = ("revenue", "operating_income", "net_income")


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def quarter_measures(row: Mapping, family: str, tbv: Optional[float]) -> dict:
    v, p = row.get("values") or {}, row.get("prior_year") or {}
    rev, rev0, oi, ni = v.get("revenue"), p.get("revenue"), v.get("operating_income"), v.get("net_income")
    growth = (rev / rev0 - 1.0) if (_num(rev) and _num(rev0) and rev0 > 0) else None
    margin = (oi / rev) if (_num(oi) and _num(rev) and rev > 0) else None
    rote = (4.0 * ni / tbv) if (family == "financial" and _num(ni) and _num(tbv) and tbv > 0) else None
    # Addendum O 2 (G1 compares year-on-year CHANGES): the same quarter a year earlier, from the comparative column of the same filing
    oi0, ni0 = p.get("operating_income"), p.get("net_income")
    margin0 = (oi0 / rev0) if (_num(oi0) and _num(rev0) and rev0 > 0) else None
    margin_change = (margin - margin0) if (margin is not None and margin0 is not None) else None
    rote_change = (4.0 * (ni - ni0) / tbv) if (family == "financial" and _num(ni) and _num(ni0) and _num(tbv) and tbv > 0) else None
    return {"period_end": row["period_end"], "filed": row["filed"], "accession": row.get("accession"), "revenue_growth": growth, "operating_margin": margin,
            "rote_annualised_on_tbv_at_T": rote, "operating_margin_year_earlier": margin0, "operating_margin_change": margin_change,
            "rote_change_annualised_on_tbv_at_T": rote_change}


def quarter_outcomes(pit_data, cik: str, asof: str, family: str, tbv: Optional[float] = None, mode: str = OUTCOME_MODE) -> dict:
    """{"q1": {...} | None, "q2": {...} | None}: the next two fiscal quarters first reported after `asof` (see the module docstring)."""
    rows = pit_data.quarterly_rows(cik, None, FIELDS, 1000, mode)
    after = sorted((r for r in rows if str(r["filed"])[:10] > str(asof)[:10]), key=lambda r: r["period_end"])
    out: dict = {"q1": None, "q2": None}
    if not after:
        return out
    q1 = after[0]
    out["q1"] = quarter_measures(q1, family, tbv)
    for r in after[1:]:
        gap = _days(q1["period_end"], r["period_end"])
        if 80 <= gap <= 100:
            out["q2"] = quarter_measures(r, family, tbv)
            break
        if gap > 100:
            break
    return out


def months_after(d: str, h: int) -> date:
    y, m = divmod(date.fromisoformat(d).month - 1 + h, 12)
    return date(date.fromisoformat(d).year + y, m + 1, 1)


def return_outcomes(pit_data, key: Optional[str], asof: str, scoring_date: str, horizons: Sequence[int] = config.RETURN_HORIZONS) -> dict:
    """{h: {"status", "excess", "ret", "bounds": {...}}} for the horizons whose month has fully elapsed by the scoring date."""
    from rebuild_harness import outcomes as oc
    hz = tuple(h for h in horizons if months_after(asof, h) <= date.fromisoformat(scoring_date))
    out = {}
    for h in hz:
        if key is None:
            out[str(h)] = {"status": oc.UNOBSERVABLE, "excess": None, "ret": None, "bounds": {"excluded": None, "minus100": None, "last_close": None}}
            continue
        o = oc.horizon_outcome(pit_data, key, asof, h)
        out[str(h)] = {"status": o["status"], "excess": o.get("excess"), "ret": o.get("ret"), "bounds": o.get("bounds"), "flags": o.get("flags")}
    return out


def company_outcomes(pit_data, job: Mapping, scoring_date: str, *, tbv: Optional[float] = None, ticker_of=None) -> dict:
    """`ticker_of(job)` names the security whose returns are measured: the runner's own resolver (`gate1_run._best_ticker`, the common stock by SEC order,
    Addendum AD.10), so the outcome is the return of the very security priced at T. Without it the sample file's ticker is used (tests only): that ticker
    can be a preferred share or a note (BRKRP for Bruker), the defect AD.10 fixed in the price."""
    cik, d = str(job["cik"]).zfill(10), job["date"]
    tk = ticker_of(job) if ticker_of is not None else job.get("ticker")
    return {"key": f"{d}_{cik}", "date": d, "cik": cik, "ticker": tk, "sample_ticker": job.get("ticker"), "family": job.get("family"),
            "quarters": quarter_outcomes(pit_data, cik, d, job.get("family"), tbv), "returns": return_outcomes(pit_data, tk, d, scoring_date)}


def outcomes_path(scoring_date: str, state_dir=None) -> Path:
    return config.state_paths(state_dir)["outcomes"] / f"outcomes_{scoring_date}.jsonl"


def build(pit_data, jobs: Sequence[Mapping], scoring_date: str, state_dir=None, tbv_of=lambda job: None, out=print, ticker_of=None) -> Path:
    """Write outcomes_<scoring date>.jsonl for `jobs` (exclusive creation: an existing file for a scoring date is refused)."""
    p = outcomes_path(scoring_date, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "x", encoding="utf-8") as fh:
        for j in jobs:
            fh.write(json.dumps(company_outcomes(pit_data, j, scoring_date, tbv=tbv_of(j), ticker_of=ticker_of), default=str) + "\n")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scoring-date", required=True)
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--store", type=Path)
    ap.add_argument("--id-map", type=Path)
    ap.add_argument("--prices-daily", type=Path)
    ap.add_argument("--prices", type=Path)
    ap.add_argument("--delisting-index", type=Path, required=True)
    ap.add_argument("--delisting-docs", type=Path, required=True)
    ap.add_argument("--sic", type=Path)
    a = ap.parse_args(argv)
    from . import runner as runner_mod
    from . import sample as sample_mod
    from . import env as env_mod
    from rebuild_harness import delisting_inputs
    g = env_mod._g1r()
    smp = sample_mod.load_verified(sample_mod.sample_path(a.state_dir))
    paths = config.state_paths(a.state_dir)
    prog = {}
    if paths["progress"].exists():
        for line in paths["progress"].read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            prog[r["key"]] = r
    jobs = [j for j in sample_mod.jobs(smp) if prog.get(runner_mod.job_key(j), {}).get("status") == "ok"]
    idm = json.loads((a.id_map or g.DEFAULT_IDMAP).read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    tk_of = {}
    for t, c in idm.items():
        tk_of.setdefault(str(c).zfill(10), []).append(t)
    idx = delisting_inputs.EventIndex(a.delisting_index)
    docs = delisting_inputs.DelistingDocs(a.delisting_docs)
    events, _rep = delisting_inputs.build_price_events(idx, docs, lambda c: tk_of.get(str(c).zfill(10), []), since=min(config.DATES))
    ev_path = paths["outcomes"] / f"price_events_{a.scoring_date}.json"
    ev_path.parent.mkdir(parents=True, exist_ok=True)
    ev_path.write_text(json.dumps(events), encoding="utf-8")
    cfg = env_mod._cfg(state_dir=a.state_dir, rf={}, n_draws=g.gate1.N_DRAWS, store=a.store or g.DEFAULT_STORE, id_map=a.id_map or g.DEFAULT_IDMAP,
                       prices_daily=a.prices_daily or (config.WORKSPACE / "data" / "prices_daily"), prices_monthly=a.prices or g.DEFAULT_PRICES, headers=None, crosswalk=None,
                       sic=a.sic or g.DEFAULT_SIC, priors_dir=None, strict_classification=False)
    cfg["price_events"] = str(ev_path)
    from rebuild_harness import run_harness
    saved = run_harness.block_network
    run_harness.block_network = lambda: None
    try:
        g._init(cfg)
    finally:
        run_harness.block_network = saved
    pit = g._ENV["pit"]
    from valuation.common import build_state

    def tbv_of(j):
        """Tangible book at the base fiscal year end known at T (financials only): the denominator of the stated ROTE approximation."""
        if j.get("family") != "financial":
            return None
        try:
            pc = pit.company_pit(j["cik"], j["date"], j.get("ticker"))
            return None if pc is None else build_state(pc).get("tbv")
        except Exception:
            return None
    p = build(pit, jobs, a.scoring_date, a.state_dir, tbv_of=tbv_of, ticker_of=lambda j: g._best_ticker(pit, str(j["cik"]).zfill(10), j["date"])[0])
    print(f"{len(jobs)} company-dates -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
