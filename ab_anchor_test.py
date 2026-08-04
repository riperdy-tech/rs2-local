#!/usr/bin/env python3
"""ab_anchor_test.py — A/B: does the continuity anchor stabilize the final call?

For each ticker's latest COMPLETE report, regenerate ONLY the final assembly
K times per arm (plain vs --anchor) via run_rs2.py --refinal. Same frozen
analysis, same data; only the call emission repeats. Measures per arm:
  * self-consistency: share of reps agreeing with the arm's modal action family
  * flip-vs-source:   share of reps whose family differs from the source verdict
  * conviction stdev
Outputs ab_reports/ab_results.json + a table. Never touches the live overlay
(outputs live in ab_reports/, which the orchestrator never reads).

Usage: python ab_anchor_test.py [--reps 3] [--tickers MEDP,MPWR,...]
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
REPORTS = Path(CONFIG["out_reports_dir"])
AB = HERE / "ab_reports"
DEFAULT = "MEDP,MPWR,AGX,RMBS,DELL,BMRN,GOOGL,ROST"

sys.path.insert(0, str(HERE))
from run_rs2 import _action_family, unload_model   # noqa: E402

NEEDED = ("S1_macro_classify.md", "S2_quality.md", "S3_valuation.md", "S4_scenarios.md",
          "S5_conviction.md", "S6_redteam_audit.md", "verdict.json", "S3_valuation_inputs.json")


def latest_complete(t):
    for d in sorted(REPORTS.glob(f"{t}_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if all((d / f).exists() for f in NEEDED):
            return d
    return None


def score(plan):
    res = {}
    for t, src in plan:
        src_v = json.loads((src / "verdict.json").read_text(encoding="utf-8"))
        src_fam = _action_family(src_v.get("action"))
        for arm in ("plain", "anchor"):
            fams, convs, changed = [], [], []
            for d in sorted(AB.glob(f"{t}_*_{arm}")):
                try:
                    v = json.loads((d / "verdict.json").read_text(encoding="utf-8"))
                except Exception:
                    continue
                fams.append(_action_family(v.get("action")))
                if isinstance(v.get("conviction"), (int, float)):
                    convs.append(v["conviction"])
                changed.append(v.get("changed_because"))
            if not fams:
                continue
            modal = max(set(fams), key=fams.count)
            res.setdefault(t, {"source_family": src_fam})[arm] = {
                "n": len(fams), "families": fams,
                "self_consistency": round(fams.count(modal) / len(fams), 2),
                "flip_vs_source": round(sum(f != src_fam for f in fams) / len(fams), 2),
                "conviction_stdev": round(statistics.pstdev(convs), 2) if len(convs) > 1 else 0.0,
                "changed_because": changed,
            }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tickers", default=DEFAULT)
    ap.add_argument("--score-only", action="store_true",
                    help="skip generation; re-score existing ab_reports/ output")
    args = ap.parse_args()
    tickers = [x.strip().upper() for x in args.tickers.split(",") if x.strip()]
    plan = []
    for t in tickers:
        src = latest_complete(t)
        if src is None:
            print(f"  ! {t}: no complete report — skipped", flush=True)
            continue
        plan.append((t, src))

    if not args.score_only:
        total = len(plan) * 2 * args.reps
        print(f"A/B: {len(plan)} tickers x 2 arms x {args.reps} reps = {total} regenerations",
              flush=True)
        done, t_start = 0, time.time()
        for t, src in plan:
            for arm_flag in ([], ["--anchor"]):
                for rep in range(args.reps):
                    done += 1
                    arm = "anchor" if arm_flag else "plain"
                    eta = ((time.time() - t_start) / max(done - 1, 1)
                           * (total - done) / 60) if done > 1 else 0
                    print(f"[{done}/{total}] {t} {arm} rep{rep+1}  (eta ~{eta:.0f}m)", flush=True)
                    r = subprocess.run([sys.executable, str(HERE / "run_rs2.py"), t,
                                        "--refinal", str(src)] + arm_flag,
                                       capture_output=True, text=True)
                    if r.returncode != 0:
                        print(f"   FAILED: {(r.stderr or r.stdout)[-300:]}", flush=True)
        unload_model(CONFIG["model"])

    res = score(plan)
    AB.mkdir(exist_ok=True)
    (AB / "ab_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"\n{'ticker':<7} {'src':>5} | {'plain flip':>10} {'cons':>5} | "
          f"{'anchor flip':>11} {'cons':>5}", flush=True)
    agg = {"plain": [0, 0], "anchor": [0, 0]}
    for t, r in res.items():
        p, a = r.get("plain", {}), r.get("anchor", {})
        for arm, d in (("plain", p), ("anchor", a)):
            if d:
                agg[arm][0] += sum(f != r["source_family"] for f in d["families"])
                agg[arm][1] += d["n"]
        print(f"{t:<7} {r['source_family']:>5} | {p.get('flip_vs_source', '-'):>10} "
              f"{p.get('self_consistency', '-'):>5} | {a.get('flip_vs_source', '-'):>11} "
              f"{a.get('self_consistency', '-'):>5}", flush=True)
    for arm in ("plain", "anchor"):
        n, d = agg[arm]
        print(f"{arm}: overall flip-vs-source {n}/{d} = "
              f"{round(100 * n / d, 1) if d else '-'}%", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
