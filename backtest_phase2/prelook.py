"""Step 5 (second half): the pre-outcome run.  Everything dated on or before T; no return, no price after T except the
T+36 presence test already inside the universe.

  python -m backtest_phase2.prelook --bt-root <SP\\backtest> --baseline-tree <fee17cf tree> --candidate-tree <ac68e25 tree>
                                    --mri-python <MRI venv python> --stage workers|assemble|all

workers : run the MRI solve (COE_mkt_B per date) and, per date, one baseline and one candidate worker process.
assemble: read the workers' results; write out/prelook/table_<Y>.pkl (what a Look reads), per-date coverage, the closure
          record, the C3 reduction and C4 closure checks, and out/prelook/summary.json (counts and rates only).
"""
import argparse
import json
import math
import os
import pickle
import statistics
import subprocess
import sys
from pathlib import Path

from .common import DATES, DESIGN_YEARS, VALIDATION_YEARS, is_num

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd, cwd=None, env=None):
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if env:
        e.update(env)
    return subprocess.Popen(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def run_mri_solve(bt_root, mri_python):
    cmd = [str(mri_python), str(bt_root / "mri" / "pit_anchors.py"), "solve", "--agg-dir", str(bt_root / "out" / "inputs")]
    p = _run(cmd)
    out = p.communicate()[0]
    if p.returncode != 0:
        raise RuntimeError("MRI solve failed:\n" + out)
    return out


def job_path(bt_root, kind, y):
    return bt_root / "out" / "prelook" / f"job_{kind}_{y}.json", bt_root / "out" / "prelook" / f"result_{kind}_{y}.json"


def run_workers(bt_root, baseline_tree, candidate_tree, calibration, years, max_parallel):
    pre = bt_root / "out" / "prelook"
    pre.mkdir(parents=True, exist_ok=True)
    coe = json.loads((bt_root / "mri" / "coe_mkt_B.json").read_text(encoding="utf-8"))
    anchors = json.loads((bt_root / "mri" / "pit_anchors.json").read_text(encoding="utf-8"))["dates"]
    todo = []
    for y in years:
        a = anchors[y]
        if coe[y]["coe_mkt_B"] is None:
            print(f"{y}: no COE_mkt_B ({coe[y]['status']}); the date is not run", flush=True)
            continue
        base = {"inputs": str(bt_root / "out" / "inputs" / f"inputs_{y}.pkl"), "rf": a["rf"], "rf_eff": max(a["rf"], a["gA"]),
                "gA": a["gA"], "pi": a["pi"], "coe_mkt_B": coe[y]["coe_mkt_B"]}
        for arm, tree, typ in (("baseline", baseline_tree, "date_baseline"), ("candidate", candidate_tree, "date_candidate")):
            jp, rp = job_path(bt_root, arm, y)
            job = dict(base, type=typ)
            if arm == "candidate":
                job["calibration"] = str(calibration)
            jp.write_text(json.dumps(job), encoding="utf-8")
            todo.append((arm, y, tree, jp, rp))
    running = []
    failures = []
    while todo or running:
        while todo and len(running) < max_parallel:
            arm, y, tree, jp, rp = todo.pop(0)
            cmd = [sys.executable, "-m", "backtest_phase2.arm_worker", "--arm", arm, "--tree", str(tree), "--job", str(jp), "--out", str(rp)]
            running.append((arm, y, _run(cmd, cwd=HARNESS_ROOT)))
            print(f"started {arm} {y}", flush=True)
        for item in list(running):
            arm, y, p = item
            if p.poll() is not None:
                out = p.stdout.read()
                running.remove(item)
                print(f"finished {arm} {y} rc={p.returncode}", flush=True)
                if p.returncode != 0:
                    failures.append((arm, y, out[-2000:]))
        if running:
            import time
            time.sleep(2)
    if failures:
        raise RuntimeError("worker failures:\n" + "\n".join(f"{a} {y}: {o}" for a, y, o in failures))


def _count(results, pop, key):
    """{valued (> 0), non_positive, reason: n} among the given names for result dict `results[cik]`."""
    c = {"valued": 0, "value_not_positive": 0}
    for nm in pop:
        r = results[nm["cik"]]
        v = r["value"]
        if v is None:
            c["not_valued:" + str(r["reason"])] = c.get("not_valued:" + str(r["reason"]), 0) + 1
        elif v > 0:
            c["valued"] += 1
        else:
            c["value_not_positive"] += 1
    return c


def assemble(bt_root, years):
    pre = bt_root / "out" / "prelook"
    coe = json.loads((bt_root / "mri" / "coe_mkt_B.json").read_text(encoding="utf-8"))
    summary = {"dates": {}}
    for y in years:
        with open(bt_root / "out" / "inputs" / f"inputs_{y}.pkl", "rb") as f:
            d = pickle.load(f)
        if not job_path(bt_root, "baseline", y)[1].exists():
            summary["dates"][y] = {"T": d["T"], "status": "not_run", "reason": coe[y]["status"], "note": coe[y]["note"],
                                   "rf": d["rf"], "rf_eff": d["rf_eff"], "gA": d["gA"], "pi": d["pi"], "pop": len(d["pop"]),
                                   "U": sum(1 for nm in d["pop"] if nm["in_U"]), "universe_tally": d["universe"],
                                   "pre_collapse_tally": d["tally_pre_collapse"], "ambiguities": d["ambiguities"], "aggregate": d["agg_stats"]}
            continue
        rb = json.loads(job_path(bt_root, "baseline", y)[1].read_text(encoding="utf-8"))
        rc = json.loads(job_path(bt_root, "candidate", y)[1].read_text(encoding="utf-8"))
        pop = d["pop"]
        U = [nm for nm in pop if nm["in_U"]]
        B, A, S, Bv, RED = rb["B"], rb["a"], rc["S"], rc["b"], rc["red"]
        table = []
        for nm in pop:
            c = nm["cik"]
            table.append({"cik": c, "ticker": nm["ticker"], "price": nm["price"], "cap": nm["cap"], "sector": nm["sector"],
                          "in_U": nm["in_U"], "u_reason": nm["u_reason"], "rev_years": nm.get("rev_years"), "V_B": B[c]["value"], "V_S": S[c]["value"],
                          "V_a": A[c]["value"], "V_b": Bv[c]["value"],
                          "oe_yield": (nm["oe_L"] / nm["cap"]) if (is_num(nm.get("oe_L")) and nm["cap"] > 0) else None})
        with open(pre / f"table_{y}.pkl", "wb") as f:
            pickle.dump(table, f, protocol=4)
        P = [r for r in table if r["in_U"] and r["V_B"] is not None and r["V_B"] > 0 and r["V_S"] is not None and r["V_S"] > 0]
        # C3: the candidate switched to revision 16's arithmetic against the baseline, same rate, every name of the date
        both = diff_max = n_match = only_one = 0
        for nm in pop:
            vb, vr = B[nm["cik"]]["value"], RED[nm["cik"]]["value"]
            if vb is None and vr is None:
                continue
            if vb is None or vr is None:
                only_one += 1
                continue
            both += 1
            diff = abs(vb - vr)
            diff_max = max(diff_max, diff)
            n_match += int(round(vb, 2) == round(vr, 2))
        vp = lambda key: [r[key] / r["price"] for r in P]
        med = lambda xs: statistics.median(xs) if xs else None
        u_vp = lambda key: [r[key] / r["price"] for r in table if r["in_U"] and r[key] is not None and r[key] > 0]
        cl = rc["closure"]
        m_missing = sum(1 for nm in U if not is_num(nm.get("m")))
        summary["dates"][y] = {
            "T": d["T"], "rf": d["rf"], "rf_eff": d["rf_eff"], "gA": d["gA"], "pi": d["pi"],
            "COE_mkt_B": coe[y]["coe_mkt_B"], "ERP_B": rb["erp_B"], "ERP_S": cl["erp_S"], "ERP_a": rb["erp_a"],
            "U": len(U), "P": len(P), "pop": len(pop),
            "universe_tally": d["universe"], "pre_collapse_tally": d["tally_pre_collapse"], "ambiguities": d["ambiguities"],
            "aggregate": d["agg_stats"], "aggregate_in_pop": cl["aggregate_constituents_in_pop"],
            "coverage": {"B": _count(B, U, "V"), "S": _count(S, U, "V"), "a": _count(A, U, "V"), "b": _count(Bv, U, "V")},
            "closure": cl,
            # F0 (amendment of the reviewer's C-3): the names both arms value (V > 0) over the names revision 16 values, within U
            "F0_intersection": {"valued_by_both": len(P), "valued_by_revision_16": sum(1 for r in table if r["in_U"] and r["V_B"] is not None and r["V_B"] > 0),
                                "ratio": len(P) / max(1, sum(1 for r in table if r["in_U"] and r["V_B"] is not None and r["V_B"] > 0))},
            "median_vp_P": {"B": med(vp("V_B")), "S": med(vp("V_S"))},
            "median_vp_own_valued_U": {"B": med(u_vp("V_B")), "S": med(u_vp("V_S")), "a": med(u_vp("V_a")), "b": med(u_vp("V_b"))},
            "variant_a_low_rate": rb["variant_a_low_rate"],
            "C3": {"names_valued_in_both": both, "match_to_the_cent": n_match, "max_abs_diff": diff_max, "valued_in_only_one": only_one},
            "m_missing_in_U": m_missing, "m_source_in_U": {s: sum(1 for nm in U if nm.get("m_src") == s) for s in ("conditional", "size_bucket", "none")},
            "bound_flag": cl["flag"]}
    (pre / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt-root", required=True, type=Path)
    ap.add_argument("--baseline-tree", required=True, type=Path)
    ap.add_argument("--candidate-tree", required=True, type=Path)
    ap.add_argument("--mri-python", required=True, type=Path)
    ap.add_argument("--calibration", type=Path, default=None)
    ap.add_argument("--stage", choices=["workers", "assemble", "all"], default="all")
    ap.add_argument("--years", nargs="*", default=list(DATES))
    ap.add_argument("--max-parallel", type=int, default=4)
    a = ap.parse_args(argv)
    cal = a.calibration or (a.bt_root / "s1_calibration.json")
    if a.stage in ("workers", "all"):
        print(run_mri_solve(a.bt_root, a.mri_python))
        run_workers(a.bt_root, a.baseline_tree, a.candidate_tree, cal, a.years, a.max_parallel)
    if a.stage in ("assemble", "all"):
        s = assemble(a.bt_root, a.years)
        for y, v in s["dates"].items():
            if v.get("status") == "not_run":
                print(y, "NOT RUN:", v["reason"], "U", v["U"])
                continue
            print(y, "U", v["U"], "P", v["P"], "ERP_B", round(v["ERP_B"], 4), "ERP_S", round(v["ERP_S"], 4), "flag", v["bound_flag"])


if __name__ == "__main__":
    main()
