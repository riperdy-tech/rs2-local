"""The coordinator's independent recomputation of the gate-2b v3 bars (REGISTRATION_gate2b.md v3 items 5, 12 (a), 13; SPEC_rebuild AK.61, AK.68).
It imports nothing from rebuild_harness or valuation: it reads only the census pipeline's files and recomputes every bar from the registration's text.
Run only at scoring time, after the eligible-outcome file exists.

    python independent_g2b.py <census state dir> <outcomes_eligible jsonl> [--verified-only]

READ: <state>/valuation/companies/*.json (each company's arms: forecast_year1 P50s, base levels, sic2), <state>/baselines/baselines_v2.json (runrate =
PERSIST, pop_median_runrate = POPMED over the universe file, v3 item 13 (b)), and the eligible-outcome file (detail.q1.eligibility.eligible; q1 values).
FORECASTS (gate 2's convention): growth = the arm's year-1 P50; margin change = the P50 minus the base operating margin; ROTE change = the P50 minus the
base ROTE (`rote_latest`).  PERSIST and POPMED are already changes (their "margin" slot is the ROTE change for financials).
OUTCOMES (q1): revenue_growth; operating_margin_change; rote_change_annualised_on_tbv_at_T.  Only rows whose q1 is eligible.
THE STATISTIC: median of d = |A - y| - |B - y| over rows with both forecasts and the outcome.  A beats B when the median < 0 AND the 0.90 quantile of
bootstrap medians < 0 under BOTH the SIC-2 industry clustering (industries with < 5 in the bar's sample pooled per family) AND the company clustering.
2,000 resamples of whole clusters, numpy default_rng seed 777 (deliberately not the pipeline's seed: the medians must agree exactly, the bounds closely).
MINIMUM n: 200 (growth, margin), 100 (ROTE), else NOT DECIDED.  VERDICT: FAIL if any decided bar fails; else NOT DECIDED if any lacks its sample; else PASS.
"""
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

STATE, OUTS = Path(sys.argv[1]), Path(sys.argv[2])
VERIFIED_ONLY = "--verified-only" in sys.argv
MIN_N = {"growth": 200, "margin": 200, "rote": 100}
FAMILY = {"growth": "operating", "margin": "operating", "rote": "financial"}
Y_KEY = {"growth": "revenue_growth", "margin": "operating_margin_change", "rote": "rote_change_annualised_on_tbv_at_T"}
BARS = [("B2", "v2", "persist", "growth"), ("B2", "v2", "popmed", "growth"), ("B2", "v2", "persist", "margin"), ("B2", "v2", "popmed", "margin"),
        ("B2", "v2", "persist", "rote"), ("B3", "v2", "code", "growth"), ("B3", "v2", "code", "margin"), ("B3", "v2", "code", "rote")]


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(x)


def engine_forecast(arm, measure, base):
    if not arm or arm.get("status") != "ok":
        return None
    f = ((arm.get("forecast_year1") or {}).get(measure)) or {}
    p50 = f.get("p50")
    if not num(p50):
        return None
    if measure == "growth":
        return p50
    lvl = base.get("op_margin") if measure == "margin" else base.get("rote_latest")
    return p50 - lvl if num(lvl) else None


def boot_upper(d, cl, draws=2000, seed=777):
    groups = defaultdict(list)
    for v, c in zip(d, cl):
        groups[c].append(v)
    arrs = [np.array(v) for v in groups.values()]
    rng = np.random.default_rng(seed)
    meds = [np.median(np.concatenate([arrs[i] for i in rng.integers(0, len(arrs), len(arrs))])) for _ in range(draws)]
    return float(np.quantile(meds, 0.90)), len(arrs)


def main():
    outs = {}
    for line in OUTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            outs[o["key"]] = o
    base_file = json.loads((STATE / "baselines" / "baselines_v2.json").read_text(encoding="utf-8"))
    rows = []
    for f in sorted(glob.glob(str(STATE / "valuation" / "companies" / "*.json"))):
        v = json.loads(Path(f).read_text(encoding="utf-8"))
        fam, key = v.get("family"), f"{v['date']}_{v['cik']}"
        if fam not in ("operating", "financial"):
            continue
        o = outs.get(key) or {}
        det = ((o.get("detail") or {}).get("q1")) or {}
        if not (det.get("eligibility") or {}).get("eligible"):
            continue
        if VERIFIED_ONLY and fam == "operating" and (det.get("scope") or {}).get("status") not in ("dominance", "closure"):
            continue
        q1 = ((o.get("quarters") or {}).get("q1")) or {}
        base = v.get("base") or {}
        rr = ((base_file.get("companies") or {}).get(key) or {}).get("runrate") or {}
        pm = ((base_file.get("pop_median_runrate") or {}).get(v["date"]) or {}).get(fam) or {}
        fc = {}
        for m in ("growth", "margin", "rote"):
            slot = "growth" if m == "growth" else "margin"                        # the baselines' ROTE change sits in the "margin" slot
            fc[m] = {"v2": engine_forecast((v.get("arms") or {}).get("v2"), m, base),
                     "code": engine_forecast((v.get("arms") or {}).get("code"), m, base),
                     "persist": rr.get(slot), "popmed": pm.get(slot)}
        rows.append({"cik": v["cik"], "family": fam, "sic2": (v.get("sic") or {}).get("sic2") or "unknown",
                     "y": {m: q1.get(Y_KEY[m]) for m in Y_KEY}, "fc": fc})
    report, statuses = {}, []
    for grp, a, b, m in BARS:
        sel = [r for r in rows if r["family"] == FAMILY[m] and num(r["y"][m]) and num(r["fc"][m][a]) and num(r["fc"][m][b])]
        name = f"{grp}: {a} vs {b} on {m}"
        if not sel:
            report[name] = {"n": 0, "status": "NOT DECIDED"}
            statuses.append("NOT DECIDED")
            continue
        d = [abs(r["fc"][m][a] - r["y"][m]) - abs(r["fc"][m][b] - r["y"][m]) for r in sel]
        size = Counter(r["sic2"] for r in sel)
        ind = [f"sic2:{r['sic2']}" if size[r["sic2"]] >= 5 else f"pool:{r['family']}" for r in sel]
        med = float(np.median(d))
        up_i, n_i = boot_upper(d, ind)
        up_c, _ = boot_upper(d, [r["cik"] for r in sel])
        beats = med < 0 and up_i < 0 and up_c < 0
        st = "NOT DECIDED" if len(sel) < MIN_N[m] else ("PASS" if beats else "FAIL")
        statuses.append(st)
        report[name] = {"n": len(sel), "median_d": med, "upper90_industry": up_i, "upper90_company": up_c, "n_industry_clusters": n_i,
                        "few_clusters": n_i < 10, "beats": beats, "status": st}
    verdict = "FAIL" if "FAIL" in statuses else ("NOT DECIDED" if "NOT DECIDED" in statuses else "PASS")
    print(json.dumps({"verified_only": VERIFIED_ONLY, "n_rows_eligible": len(rows), "verdict": verdict, "bars": report}, indent=1))


if __name__ == "__main__":
    main()
