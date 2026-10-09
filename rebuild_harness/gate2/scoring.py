"""scoring.py - the gate-2 bars G1-G6 (registration section 4), MUSE against CODE, paired by company and date.

    python -m rebuild_harness.gate2.scoring --outcomes outcomes/outcomes_<scoring date>.jsonl [--state-dir DIR] [--out DIR]

INPUTS: the runner's folders (`progress.jsonl`; per company-date `result.json` and `job.json`; the masked control's `runs_masked`) and an outcomes file from `outcome_extract`
(first-reported quarterly outcomes and the 3/6/12-month excess returns with the three delisting bounds, only where elapsed).  This module reads no price file and no filing.

PAIRING.  A company-date enters a bar only when BOTH arms valued it (status `ok`: the CODE arm is `code_only` of the same run) and the bar's outcome exists.  Every exclusion is counted by reason.

G1  forecast accuracy (HARD).  For q1, the first fiscal quarter first reported after T: d = |MUSE forecast - outcome| - |CODE forecast - outcome|, where the forecast is the engine's year-1 P50
    (the arm's own engine run: CODE at the prior's P50, MUSE at Muse's final placements) for revenue growth (operating and commodity families: the frozen engine forecasts no revenue
    growth for financials) and for the operating margin (the return on tangible equity for financials).  Bar, for EACH of the two measures: the median of d is < 0 and the upper end of its
    one-sided 90% bootstrap interval (clustered by company) is < 0.  (Reading: both measures must pass; the pooled-over-both statistic and the per-family figures are reported.)  q2 is reported only.
G2  return information (HARD in direction).  IV is the STAGE 2 VALUE of Addenda V and W on BOTH arms: the mean of the engine's draws x (1 - P(fail within 12 months)), with P(fail) the
    point-in-time model of `stage2_layer` (the same for the two arms of a company-date); commodity is out of scope.  Rank IC (Spearman) of IV/price with the 3-month excess return, MUSE minus CODE, pooled over dates (the observation-weighted mean of the per-date IC
    differences; dates with fewer than 10 paired observations are listed and left out).  The 90% bootstrap interval (clustered by company) is reported.  Computed under each of the three
    delisting bounds; the direction (> 0) must hold under all three: all three hold = pass, none = fail, a mix = NOT DECIDED.  6 and 12 months are reported where elapsed.
G3  calibration (reported).  The share of realised q1 growth and margin that fall inside the arm's stated P10..P90 (both arms).
G4  anchoring (HARD).  Among pass-2 revisions (proposed by the model), the share that move toward the price with neither a quote not cited in pass 1 nor a named error is <= 10%.  Also
    reported: the same share without a new quote alone, and whether any ACCEPTED revision is of that kind (the code should refuse them all).  No revisions at all: the bar holds vacuously, said so.
G5  integrity (HARD).  The leakage audit has no violation on any run folder and the templates; every accepted citation passes the quote check re-run on the saved prompts; no run has a failed call
    (after its one retry) without a recorded fallback; no company-date ended `model_unavailable`, `context_overflow`, `request_rejected` or `error`.
G6  name bias (reported).  The masked control's mean absolute shift of the placed percentiles against the unmasked run of the same company-date (inputs anchored in both).

THE VERDICT is the registration's section 5, mechanically: PASS = G1, G2 (direction), G4 and G5 all pass; FAIL = a hard bar fails (G2 fails when it fails under all three bounds); NOT DECIDED = G2
straddles the bounds (or a bar has no observation) and no hard bar fails.  Real money remains the operator's decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from . import config, stage2_layer

BOUNDS = ("excluded", "minus100", "last_close")
MIN_DATE_N = 10


# ---- loading ------------------------------------------------------------------------------------------------------------------------------

def _fy1(res: Optional[Mapping]) -> dict:
    fy = (res or {}).get("forecast_year1") or {}
    if "growth" in fy:
        return {"growth": fy["growth"], "margin": fy.get("margin")}
    if "rote" in fy:
        return {"growth": None, "margin": fy["rote"]}
    return {"growth": None, "margin": None}


def row_from_run(result: Mapping, job: Mapping, run_dir: Optional[Path] = None, p_fail: Optional[float] = None) -> Optional[dict]:
    """The scoring row of one finished company-date, or None when it holds no pair of arms.  Each arm carries `iv`, the Stage 2 value (V1 mean x V2 survival, `stage2_layer.value_ps`), and
    `iv_p50`, the engine's median, kept as a diagnostic only."""
    if result.get("status") != "ok":
        return None
    code_s = (result.get("code_only") or {}).get("iv_per_share") or {}
    muse_s = (result.get("final") or {}).get("iv_per_share") or {}
    price = (job.get("price_info") or {}).get("price")
    code = dict(_fy1((result.get("code_only") or {}).get("result")), iv=stage2_layer.value_ps(code_s.get("mean"), p_fail), iv_p50=code_s.get("p50"))
    muse = dict(_fy1((result.get("final") or {}).get("result")), iv=stage2_layer.value_ps(muse_s.get("mean"), p_fail), iv_p50=muse_s.get("p50"))
    return {"key": job["key"], "date": result.get("asof"), "cik": job.get("cik"),
            "family": result.get("family"), "price": price, "code": code, "muse": muse, "decisions": (result.get("redteam") or {}).get("decisions", []),
            "positions": (result.get("final") or {}).get("positions", {}), "p_fail": p_fail, "run_dir": str(run_dir) if run_dir else None, "masked": bool(job.get("masked"))}


def load_rows(state_dir=None, masked: bool = False) -> Tuple[List[dict], Counter, Counter]:
    """(rows, statuses of every final company-date, exclusions): from progress.jsonl (the latest line per key) and each run folder's result.json and job.json."""
    paths = config.state_paths(state_dir)
    pfail = stage2_layer.load_pfail(state_dir)
    latest: Dict[str, dict] = {}
    if paths["progress"].exists():
        for line in paths["progress"].read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if bool(r.get("masked")) == masked:
                latest[r["key"]] = r
    rows, statuses, excl = [], Counter(), Counter()
    for key, r in sorted(latest.items()):
        statuses[r["status"]] += 1
        if r["status"] != "ok":
            excl[f"status_{r['status']}"] += 1
            continue
        run_dir = paths["root"] / r["run_dir"] if not Path(r["run_dir"]).is_absolute() else Path(r["run_dir"])
        try:
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            job = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            excl["unreadable_run_folder"] += 1
            continue
        job = dict(job, cik=r["cik"], masked=masked)
        if (result.get("family") or r.get("family")) in config.OUT_OF_SCOPE_FAMILIES:
            excl["out_of_scope_family_v3"] += 1
            continue
        pf = (pfail.get(stage2_layer.job_key(r["date"], r["cik"])) or {}).get("p_fail")
        row = row_from_run(result, job, run_dir, pf)
        if row is None or row["code"]["iv"] is None or row["muse"]["iv"] is None:
            excl["no_pair_of_arms_or_no_survival_probability"] += 1
            continue
        row["date"], row["cik"], row["family"] = r["date"], r["cik"], r.get("family") or row["family"]
        rows.append(row)
    return rows, statuses, excl


def load_outcomes(path) -> Dict[str, dict]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["key"]] = r
    return out


# ---- statistics -----------------------------------------------------------------------------------------------------------------------

def rank_average(x: np.ndarray) -> np.ndarray:
    """Ranks 1..n, ties get the average rank."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    sx = x[order]
    i = 0
    n = len(x)
    while i < n:
        j = i
        while j + 1 < n and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 3:
        return None
    ra, rb = rank_average(a), rank_average(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = float(np.sqrt((ra ** 2).sum() * (rb ** 2).sum()))
    return None if den == 0.0 else float((ra * rb).sum() / den)


def cluster_bootstrap_median(values: Sequence[float], clusters: Sequence[str], draws: int = config.BOOT_DRAWS, seed: int = config.BOOT_SEED) -> np.ndarray:
    """The median of `values` over `draws` resamples of whole clusters (companies) with replacement."""
    groups: Dict[str, List[float]] = defaultdict(list)
    for v, c in zip(values, clusters):
        groups[c].append(v)
    arrs = [np.asarray(v, dtype=float) for _c, v in sorted(groups.items())]
    rng = np.random.default_rng(seed)
    k = len(arrs)
    out = np.empty(draws)
    for b in range(draws):
        idx = rng.integers(0, k, k)
        out[b] = np.median(np.concatenate([arrs[i] for i in idx]))
    return out


def _quant(x: np.ndarray, q: float) -> float:
    return float(np.quantile(x, q))


# ---- G1 -------------------------------------------------------------------------------------------------------------------------------

def _outcome_value(oc: Mapping, quarter: str, measure: str, family: str) -> Optional[float]:
    q = ((oc or {}).get("quarters") or {}).get(quarter)
    if not q:
        return None
    if measure == "growth":
        return q.get("revenue_growth")
    return q.get("rote_annualised_on_tbv_at_T") if family == "financial" else q.get("operating_margin")


def _fc(arm: Mapping, measure: str, p: str = "p50") -> Optional[float]:
    d = arm.get(measure)
    return None if not d else d.get(p)


def paired_errors(rows: Sequence[Mapping], outcomes: Mapping[str, dict], measure: str, quarter: str = "q1") -> Tuple[List[dict], Counter]:
    out, excl = [], Counter()
    for r in rows:
        y = _outcome_value(outcomes.get(r["key"]), quarter, measure, r["family"])
        fm, fc = _fc(r["muse"], measure), _fc(r["code"], measure)
        if fm is None or fc is None:
            excl["no_forecast"] += 1
        elif y is None:
            excl["no_outcome_elapsed_or_first_report"] += 1
        else:
            out.append({"cik": r["cik"], "family": r["family"], "key": r["key"], "muse_err": abs(fm - y), "code_err": abs(fc - y), "d": abs(fm - y) - abs(fc - y)})
    return out, excl


def g1_measure(rows, outcomes, measure, quarter="q1", draws=config.BOOT_DRAWS, seed=config.BOOT_SEED) -> dict:
    pairs, excl = paired_errors(rows, outcomes, measure, quarter)
    res = {"measure": measure, "quarter": quarter, "n": len(pairs), "exclusions": dict(excl)}
    if not pairs:
        res.update(median_d=None, upper90=None, passes=None)
        return res
    d = [p["d"] for p in pairs]
    med = float(np.median(d))
    boot = cluster_bootstrap_median(d, [p["cik"] for p in pairs], draws, seed)
    res.update(median_d=med, upper90=_quant(boot, 0.90), lower10=_quant(boot, 0.10), mean_muse_abs_err=float(np.mean([p["muse_err"] for p in pairs])),
               mean_code_abs_err=float(np.mean([p["code_err"] for p in pairs])), passes=bool(med < 0 and _quant(boot, 0.90) < 0),
               by_family={f: {"n": len(v), "median_d": float(np.median([p["d"] for p in v]))} for f, v in
                          ((f, [p for p in pairs if p["family"] == f]) for f in sorted({p["family"] for p in pairs}))})
    return res


def g1(rows, outcomes, draws=config.BOOT_DRAWS, seed=config.BOOT_SEED) -> dict:
    g = g1_measure(rows, outcomes, "growth", "q1", draws, seed)
    m = g1_measure(rows, outcomes, "margin", "q1", draws, seed + 1)
    pooled_pairs = paired_errors(rows, outcomes, "growth")[0] + paired_errors(rows, outcomes, "margin")[0]
    pooled = None
    if pooled_pairs:
        d = [p["d"] for p in pooled_pairs]
        b = cluster_bootstrap_median(d, [p["cik"] for p in pooled_pairs], draws, seed + 2)
        pooled = {"n": len(d), "median_d": float(np.median(d)), "upper90": _quant(b, 0.90)}
    q2 = {"growth": g1_measure(rows, outcomes, "growth", "q2", draws, seed + 3), "margin": g1_measure(rows, outcomes, "margin", "q2", draws, seed + 4)}
    parts = [g["passes"], m["passes"]]
    passes = None if any(p is None for p in parts) else bool(all(parts))
    return {"growth_q1": g, "margin_q1": m, "pooled_both_measures_q1": pooled, "reported_q2": q2, "passes": passes,
            "rule": "median(|MUSE - outcome| - |CODE - outcome|) < 0 and the upper end of the one-sided 90% company-clustered bootstrap interval < 0, for each of the two measures"}


# ---- G2 -------------------------------------------------------------------------------------------------------------------------------

def _return(outcomes: Mapping, key: str, horizon: str, bound: str) -> Optional[float]:
    r = ((outcomes.get(key) or {}).get("returns") or {}).get(horizon)
    if not r:
        return None
    b = (r.get("bounds") or {}).get(bound)
    return b if isinstance(b, (int, float)) else None


def ic_rows(rows, outcomes, horizon: str, bound: str) -> Tuple[List[dict], Counter]:
    out, excl = [], Counter()
    for r in rows:
        ex = _return(outcomes, r["key"], horizon, bound)
        p = r.get("price")
        if ex is None:
            excl["no_return_under_this_bound_or_not_elapsed"] += 1
        elif not (isinstance(p, (int, float)) and p > 0):
            excl["no_price"] += 1
        else:
            out.append({"cik": r["cik"], "date": r["date"], "key": r["key"], "muse": r["muse"]["iv"] / p, "code": r["code"]["iv"] / p, "excess": ex})
    return out, excl


def delta_ic(obs: Sequence[Mapping]) -> Tuple[Optional[float], dict, List[str]]:
    """(pooled delta IC, per-date detail, dates left out): the observation-weighted mean over dates of IC(MUSE) - IC(CODE)."""
    by: Dict[str, List[Mapping]] = defaultdict(list)
    for o in obs:
        by[o["date"]].append(o)
    detail, left_out, num, den = {}, [], 0.0, 0
    for d, xs in sorted(by.items()):
        if len(xs) < MIN_DATE_N:
            left_out.append(d)
            continue
        ic_m = spearman([x["muse"] for x in xs], [x["excess"] for x in xs])
        ic_c = spearman([x["code"] for x in xs], [x["excess"] for x in xs])
        if ic_m is None or ic_c is None:
            left_out.append(d)
            continue
        detail[d] = {"n": len(xs), "ic_muse": ic_m, "ic_code": ic_c, "delta": ic_m - ic_c}
        num += len(xs) * (ic_m - ic_c)
        den += len(xs)
    return (num / den if den else None), detail, left_out


def g2_bound(rows, outcomes, horizon: str, bound: str, draws=config.BOOT_DRAWS, seed=config.BOOT_SEED) -> dict:
    obs, excl = ic_rows(rows, outcomes, horizon, bound)
    res = {"horizon_months": int(horizon), "bound": bound, "n": len(obs), "exclusions": dict(excl)}
    d0, detail, left = delta_ic(obs)
    res.update(delta_ic=d0, by_date=detail, dates_left_out=left)
    if d0 is None:
        res.update(interval90=None, direction_positive=None)
        return res
    by_cik: Dict[str, List[Mapping]] = defaultdict(list)
    for o in obs:
        by_cik[o["cik"]].append(o)
    groups = [by_cik[c] for c in sorted(by_cik)]
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(draws):
        idx = rng.integers(0, len(groups), len(groups))
        sample = [o for i in idx for o in groups[i]]
        v, _d, _l = delta_ic(sample)
        if v is not None:
            boots.append(v)
    res["interval90"] = [_quant(np.asarray(boots), 0.05), _quant(np.asarray(boots), 0.95)] if boots else None
    res["direction_positive"] = bool(d0 > 0)
    return res


def g2(rows, outcomes, draws=config.BOOT_DRAWS, seed=config.BOOT_SEED) -> dict:
    by_bound = {b: g2_bound(rows, outcomes, "3", b, draws, seed) for b in BOUNDS}
    dirs = [by_bound[b]["direction_positive"] for b in BOUNDS]
    if any(d is None for d in dirs):
        verdict = None
    elif all(dirs):
        verdict = "pass"
    elif not any(dirs):
        verdict = "fail"
    else:
        verdict = "not_decided"
    reported = {h: {b: g2_bound(rows, outcomes, h, b, draws, seed) for b in BOUNDS} for h in ("6", "12")
                if any(_return(outcomes, r["key"], h, "excluded") is not None for r in rows)}
    return {"horizon_3m": by_bound, "verdict": verdict, "reported_6_12_months": reported,
            "rule": "rank IC of IV/price with the 3-month excess return, MUSE minus CODE, > 0 under each of the three delisting bounds"}


# ---- G3, G4, G6 -----------------------------------------------------------------------------------------------------------------------

def g3(rows, outcomes) -> dict:
    out = {}
    for measure in ("growth", "margin"):
        for arm in ("muse", "code"):
            n = hit = 0
            for r in rows:
                y = _outcome_value(outcomes.get(r["key"]), "q1", measure, r["family"])
                lo, hi = _fc(r[arm], measure, "p10"), _fc(r[arm], measure, "p90")
                if y is None or lo is None or hi is None:
                    continue
                n += 1
                hit += 1 if lo <= y <= hi else 0
            out[f"{measure}_{arm}"] = {"n": n, "coverage_p10_p90": (hit / n) if n else None, "target": 0.80}
    return out


def g4(rows) -> dict:
    ds = [d for r in rows for d in r["decisions"]]
    prop = [d for d in ds if d.get("proposed")]
    toward = [d for d in prop if d.get("toward_price")]
    neither = [d for d in toward if not d.get("new_quote") and not d.get("named_error")]
    no_quote = [d for d in toward if not d.get("new_quote")]
    accepted_bad = [d for d in neither if d.get("accepted")]
    share = (len(neither) / len(prop)) if prop else None
    return {"n_decisions": len(ds), "n_revisions_proposed": len(prop), "n_toward_price": len(toward), "n_toward_price_without_new_evidence": len(neither),
            "share": share, "n_toward_price_without_new_quote": len(no_quote), "share_without_new_quote": (len(no_quote) / len(prop)) if prop else None,
            "n_accepted_toward_price_without_new_evidence": len(accepted_bad), "max_share": config.G4_MAX_SHARE,
            "passes": True if share is None else bool(share <= config.G4_MAX_SHARE and not accepted_bad),
            "vacuous": share is None, "rule": "share of pass-2 revisions that move toward the price with neither a new quote nor a named error <= 10%, and none accepted"}


def g6(unmasked_rows, masked_rows) -> dict:
    um = {r["key"]: r for r in unmasked_rows}
    shifts, by_input, n_pairs, only_one = [], defaultdict(list), 0, 0
    for m in masked_rows:
        key = m["key"][2:] if m["key"].startswith("M_") else m["key"]
        u = um.get(key)
        if u is None:
            continue
        n_pairs += 1
        for name in sorted(set(u["positions"]) | set(m["positions"])):
            a, b = u["positions"].get(name), m["positions"].get(name)
            if not a or not b or a.get("status") != "anchored" or b.get("status") != "anchored":
                only_one += 1
                continue
            s = abs(float(a["percentile"]) - float(b["percentile"]))
            shifts.append(s)
            by_input[name].append(s)
    return {"n_company_dates": n_pairs, "n_inputs_compared": len(shifts), "n_inputs_not_anchored_in_both": only_one,
            "mean_abs_shift_percentile_points": (float(np.mean(shifts)) if shifts else None), "median_abs_shift": (float(np.median(shifts)) if shifts else None),
            "by_input": {k: {"n": len(v), "mean_abs_shift": float(np.mean(v))} for k, v in sorted(by_input.items())}, "rule": "reported only"}


# ---- G5 -------------------------------------------------------------------------------------------------------------------------------

def g5(state_dir=None, run_roots: Optional[Sequence[Path]] = None, audit_report: Optional[dict] = None, statuses: Optional[Counter] = None) -> dict:
    from valuation.muse import leakage_audit
    from . import integrity
    paths = config.state_paths(state_dir)
    roots = list(run_roots) if run_roots is not None else [paths["runs"], paths["runs_masked"]]
    rep = audit_report
    if rep is None:
        runs, tmpl = [], []
        for root in roots:
            if Path(root).exists():
                r = leakage_audit.audit(root)
                runs += r["runs"]
        tmpl = [f for f in leakage_audit.audit_templates() if f.severity == "violation"]
        rep = {"runs": runs, "violations": sum(x["violations"] for x in runs) + len(tmpl), "reviews": sum(x["reviews"] for x in runs), "template_violations": len(tmpl)}
    cit_n = cit_bad = json_viol = 0
    failed_examples = []
    for root in roots:
        if not Path(root).exists():
            continue
        for rd in sorted(p.parent for p in Path(root).rglob("result.json")):
            if not (rd / "calls.jsonl").exists() and not list(rd.glob("*_request.json")):
                continue
            v = integrity.verify_run_dir(rd)
            cit_n += v["n_citations"]
            cit_bad += v["n_citations_failed"]
            json_viol += 1 if v["json_rule_violation"] else 0
            if v["failed"] and len(failed_examples) < 10:
                failed_examples.append({"run_dir": v["run_dir"], "failed": v["failed"][:3]})
    bad_status = {s: n for s, n in (statuses or {}).items() if s in ("model_unavailable", "context_overflow", "request_rejected", "error", "transport_failure")}
    ok = rep["violations"] == 0 and cit_bad == 0 and json_viol == 0 and not bad_status
    return {"leakage_violations": rep["violations"], "leakage_reviews_for_the_coordinator": rep["reviews"], "citations_checked": cit_n, "citations_failed": cit_bad,
            "failed_citation_examples": failed_examples, "runs_with_unrecorded_fallback": json_viol, "company_dates_with_a_technical_final_status": bad_status, "passes": bool(ok),
            "rule": "no leakage violation; 100% of accepted citations pass the quote check; no failed call without a recorded fallback; no technical final status"}


# ---- the verdict -----------------------------------------------------------------------------------------------------------------------

def verdict(g1r: Mapping, g2r: Mapping, g4r: Mapping, g5r: Mapping) -> dict:
    hard = {"G1": g1r["passes"], "G2": g2r["verdict"], "G4": g4r["passes"], "G5": g5r["passes"]}
    hard_fail = [k for k, v in hard.items() if v is False or v == "fail"]
    undecided = [k for k, v in hard.items() if v is None or v == "not_decided"]
    if hard_fail:
        v = "FAIL"
    elif undecided:
        v = "NOT DECIDED"
    else:
        v = "PASS"
    return {"verdict": v, "hard_bars": hard, "failed": hard_fail, "undecided": undecided,
            "note": "registration section 5; real money remains the operator's decision"}


def score(state_dir=None, outcomes_path=None, draws=config.BOOT_DRAWS, seed=config.BOOT_SEED, run_roots=None, audit_report=None) -> dict:
    rows, statuses, excl = load_rows(state_dir, masked=False)
    outcomes = load_outcomes(outcomes_path) if outcomes_path else {}
    masked_rows, _ms, _me = load_rows(state_dir, masked=True)
    G1, G2, G3, G4 = g1(rows, outcomes, draws, seed), g2(rows, outcomes, draws, seed), g3(rows, outcomes), g4(rows)
    G5 = g5(state_dir, run_roots, audit_report, statuses)
    G6 = g6(rows, masked_rows)
    return {"n_company_dates_final": sum(statuses.values()), "statuses": dict(statuses), "n_paired": len(rows), "exclusions": dict(excl), "G1": G1, "G2": G2, "G3": G3, "G4": G4, "G5": G5,
            "G6": G6, "verdict": verdict(G1, G2, G4, G5), "outcomes_file": str(outcomes_path) if outcomes_path else None}


def render_markdown(rep: Mapping) -> str:
    def f(x, n=4):
        return "n/a" if x is None else (f"{x:.{n}f}" if isinstance(x, float) else str(x))
    v = rep["verdict"]
    L = [f"# Gate 2 scoring: {v['verdict']}", "", f"Company-dates final: {rep['n_company_dates_final']}; paired (both arms valued): {rep['n_paired']}; statuses: {rep['statuses']}", "",
         "| Bar | Kind | Result |", "|---|---|---|"]
    g1r, g2r, g4r, g5r = rep["G1"], rep["G2"], rep["G4"], rep["G5"]
    L.append(f"| G1 forecast accuracy | hard | {v['hard_bars']['G1']}: growth median d {f(g1r['growth_q1']['median_d'])} (upper90 {f(g1r['growth_q1']['upper90'])}, n={g1r['growth_q1']['n']}); "
             f"margin median d {f(g1r['margin_q1']['median_d'])} (upper90 {f(g1r['margin_q1']['upper90'])}, n={g1r['margin_q1']['n']}) |")
    b = g2r["horizon_3m"]
    L.append("| G2 return information | hard (direction) | " + str(g2r["verdict"]) + ": " + "; ".join(
        f"{k}: dIC {f(b[k]['delta_ic'])} [{', '.join(f(x) for x in (b[k]['interval90'] or [None, None]))}] n={b[k]['n']}" for k in BOUNDS) + " |")
    L.append("| G3 calibration | reported | " + "; ".join(f"{k}: {f(x['coverage_p10_p90'], 3)} (n={x['n']})" for k, x in rep["G3"].items()) + " |")
    L.append(f"| G4 anchoring | hard | {g4r['passes']}: {g4r['n_toward_price_without_new_evidence']} of {g4r['n_revisions_proposed']} revisions ({f(g4r['share'], 3)}); accepted of that kind: "
             f"{g4r['n_accepted_toward_price_without_new_evidence']} |")
    L.append(f"| G5 integrity | hard | {g5r['passes']}: leakage violations {g5r['leakage_violations']}, citations failed {g5r['citations_failed']} of {g5r['citations_checked']}, "
             f"unrecorded fallbacks {g5r['runs_with_unrecorded_fallback']}, technical statuses {g5r['company_dates_with_a_technical_final_status']} |")
    g6r = rep["G6"]
    L.append(f"| G6 name bias | reported | mean absolute shift {f(g6r['mean_abs_shift_percentile_points'], 2)} percentile points over {g6r['n_inputs_compared']} inputs of {g6r['n_company_dates']} company-dates |")
    L += ["", f"Verdict: **{v['verdict']}** (failed: {v['failed']}; undecided: {v['undecided']}). {v['note']}", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--outcomes", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--draws", type=int, default=config.BOOT_DRAWS)
    a = ap.parse_args(argv)
    rep = score(a.state_dir, a.outcomes, a.draws)
    out = a.out or config.state_paths(a.state_dir)["reports"]
    out.mkdir(parents=True, exist_ok=True)
    tag = "scoring" if a.outcomes is None else f"scoring_{Path(a.outcomes).stem}"
    with open(out / f"{tag}.json", "x", encoding="utf-8") as fh:
        fh.write(json.dumps(rep, indent=1, default=str))
    with open(out / f"{tag}.md", "x", encoding="utf-8") as fh:
        fh.write(render_markdown(rep))
    print(render_markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
