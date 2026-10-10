"""diagnostics.py - the reported diagnostics fixed before any gate-2 outcome (SPEC_rebuild Addenda AD R3/R8 and AE.1-AE.3), beside the registered bars of scoring.py.

    python -m rebuild_harness.gate2.diagnostics --state-dir DIR --outcomes FILE --baselines FILE [--repeat-state DIR] [--out FILE]

R3a  FILING SKILL (primary): Muse's PRICE-BLIND pass-1 forecasts against the code, the population median and persistence, on G1's statistic (paired median of
     |A - outcome| - |B - outcome|, upper end of the one-sided 90% company-clustered bootstrap < 0), for revenue growth (operating) and the margin change (ROTE
     change for financials), q1.  "Muse adds filing skill" needs pass 1 to beat all three on a measure; the trailing-four-quarter baseline is reported (AE.3).
R3b  THE RED TEAM'S VALUE: final against pass 1 on the same statistic (AE.1: under the tightened rule the red team may revise nothing; then final = pass 1, said so).
R3c  STRICT ANCHORING: among proposed revisions, the share moving toward the price without a new quote from a filing section (G4-strict, <= 10%); registered G4
     (a named error counts) is in scoring.py.
R8   REPEATABILITY: the repeat control's placed percentiles against run 2's for the same company-dates: median and mean absolute shift, share identical.
Every comparison is also reported by date (Addendum AA).  Nothing here changes a registered bar.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional

import numpy as np

from . import config, scoring

MEASURE_FAMILIES = {"growth": ("operating",), "margin": ("operating", "financial")}


def _pass1_arm(row: Mapping) -> Optional[dict]:
    """The pass-1 (price-blind) forecasts of a scoring row's run, with the same base as the arms (Addendum O 2)."""
    rd = row.get("run_dir")
    if not rd:
        return None
    res = json.loads((Path(rd) / "result.json").read_text(encoding="utf-8"))
    fy = scoring._fy1((res.get("pass1") or {}).get("result"))
    return dict(fy, margin_base=row["muse"].get("margin_base"))


def _baseline_arms(row: Mapping, base: Mapping) -> Dict[str, dict]:
    """{"persistence", "t4q", "pop_median"}: forecasts of the target statistic itself (a change), so their base is 0."""
    rec = (base.get("companies") or {}).get(row["key"]) or {}
    pm = ((base.get("pop_median") or {}).get(row["date"]) or {}).get(row["family"]) or {}
    out = {}
    for name in ("persistence", "t4q", "pop_median"):
        arm = {"margin_base": 0.0}
        for m in ("growth", "margin"):
            v = pm.get(m) if name == "pop_median" else ((rec.get("baselines") or {}).get(m) or {}).get(name)
            arm[m] = None if v is None else {"p50": v}
        out[name] = arm
    return out


def compare(rows: List[Mapping], outcomes: Mapping, a: str, b: str, measure: str, draws=config.BOOT_DRAWS, seed=config.BOOT_SEED) -> dict:
    """G1's statistic for arm `a` against arm `b` (negative median d = `a` is closer), pooled and by date."""
    pairs = []
    for r in rows:
        if r["family"] not in MEASURE_FAMILIES[measure]:
            continue
        y = scoring._outcome_value(outcomes.get(r["key"]), "q1", measure, r["family"])
        fa, fb = scoring._fc(r.get(a) or {}, measure), scoring._fc(r.get(b) or {}, measure)
        if y is None or fa is None or fb is None:
            continue
        pairs.append({"cik": r["cik"], "date": r["date"], "d": abs(fa - y) - abs(fb - y)})
    res = {"a": a, "b": b, "measure": measure, "n": len(pairs)}
    if not pairs:
        return dict(res, median_d=None, upper90=None, a_better=None, by_date={})
    d = [p["d"] for p in pairs]
    boot = scoring.cluster_bootstrap_median(d, [p["cik"] for p in pairs], draws, seed)
    up = float(np.quantile(boot, 0.90))
    by = defaultdict(list)
    for p in pairs:
        by[p["date"]].append(p["d"])
    return dict(res, median_d=float(np.median(d)), upper90=up, a_better=bool(np.median(d) < 0 and up < 0),
                by_date={k: {"n": len(v), "median_d": float(np.median(v))} for k, v in sorted(by.items())})


def r3c(rows: List[Mapping]) -> dict:
    prop = [d for r in rows for d in r["decisions"] if d.get("proposed")]
    toward = [d for d in prop if d.get("toward_price")]
    bad = [d for d in toward if not d.get("new_quote_from_filing")]
    acc_bad = [d for d in bad if d.get("accepted")]
    share = (len(bad) / len(prop)) if prop else None
    return {"n_proposed": len(prop), "n_toward_price": len(toward), "n_toward_without_new_filing_quote": len(bad), "share": share,
            "n_accepted_of_that_kind": len(acc_bad), "passes": None if share is None else bool(share <= config.G4_MAX_SHARE and not acc_bad),
            "vacuous": share is None, "rule": "G4-strict (Addendum AE.1): share of proposed revisions toward the price without a new filing quote <= 10%, none accepted"}


def r8(main_rows: List[Mapping], repeat_rows: List[Mapping]) -> dict:
    by = {r["key"]: r for r in main_rows}
    shifts, same, n = [], 0, 0
    for r in repeat_rows:
        m = by.get(r["key"])
        if m is None:
            continue
        n += 1
        for name, p in r["positions"].items():
            q = m["positions"].get(name)
            if not p or not q:
                continue
            s = abs(float(p["percentile"]) - float(q["percentile"]))
            shifts.append(s)
            same += 1 if (s < 1e-9 and p.get("width") == q.get("width")) else 0
    med = float(np.median(shifts)) if shifts else None
    return {"n_company_dates": n, "n_inputs": len(shifts), "median_abs_shift": med, "mean_abs_shift": float(np.mean(shifts)) if shifts else None,
            "share_identical": (same / len(shifts)) if shifts else None,
            "multi_sample_required": None if med is None else bool(med > 10.0), "rule": "Addendum AD R8: a median shift above 10 percentile points requires several samples"}


def run(state_dir, outcomes_path, baselines_path, repeat_state=None, draws=config.BOOT_DRAWS, seed=config.BOOT_SEED) -> dict:
    rows, _st, _ex = scoring.load_rows(state_dir)
    outcomes = scoring.load_outcomes(outcomes_path)
    base = json.loads(Path(baselines_path).read_text(encoding="utf-8"))
    for r in rows:
        r["muse_p1"] = _pass1_arm(r)
        r.update(_baseline_arms(r, base))
    out = {"n_rows": len(rows), "R3a": {}, "R3b": {}, "R3c": r3c(rows)}
    for m in ("growth", "margin"):
        cs = {b: compare(rows, outcomes, "muse_p1", b, m, draws, seed) for b in ("code", "pop_median", "persistence", "t4q")}
        out["R3a"][m] = dict(cs, filing_skill=None if any(cs[b]["a_better"] is None for b in ("code", "pop_median", "persistence"))
                             else all(cs[b]["a_better"] for b in ("code", "pop_median", "persistence")))
        out["R3b"][m] = compare(rows, outcomes, "muse", "muse_p1", m, draws, seed)
    out["R3b"]["red_team_revised_nothing"] = all(not d.get("accepted") for r in rows for d in r["decisions"])
    if repeat_state:
        rep_rows, _s, _e = scoring.load_rows(repeat_state)
        out["R8"] = r8(rows, rep_rows)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--outcomes", type=Path, required=True)
    ap.add_argument("--baselines", type=Path, required=True)
    ap.add_argument("--repeat-state", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    rep = run(a.state_dir, a.outcomes, a.baselines, a.repeat_state)
    text = json.dumps(rep, indent=1, default=str)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
