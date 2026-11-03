"""Routine check of new GitHub runs: archive, verify each new scoring run (WO_L3 v1.2), pair-check its output (WO_L5).

Usage: python check_new_runs.py [--since 2026-10-28T10:00:00Z] [--repo DIR]   (default repo: paths.py screener_publish_repo)
The repo must hold the runs' commits (run `git fetch origin` in it first; that only moves origin/* refs).
Writes <rs2_state_dir>/paper_books/m3l_verifier/out/check_<utc>.json and prints one line per run.
"""
import argparse, json, subprocess, sys, types, zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import m3l_gh_run_witness as W  # noqa: E402

ARCHIVE = W.DEFAULT_ARCHIVE

VALIDATOR_REV = "3094fc70835b80cb23d3358092129b3ef4bdddb8"


def pair_check(git, commit):
    src = git.show(VALIDATOR_REV, "scripts/check_paired_publication.py").decode("utf-8")
    m = types.ModuleType("check_paired_publication")
    m.__file__ = "check_paired_publication.py"
    exec(src, m.__dict__)
    load = lambda p: json.loads(git.show(commit, p), object_pairs_hook=m._strict_object, parse_constant=m._invalid_number)
    try:
        return "PASS", m.validate(load("public/data/stocks.json"), load("public/data/reverse_scores.json"))
    except (ValueError, TypeError) as e:
        return "FAIL", str(e)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-28T10:00:00Z")
    ap.add_argument("--repo", default=str(W.DEFAULT_REPO))
    a = ap.parse_args()
    subprocess.run([sys.executable, str(HERE / "archive_runs.py")], check=True, capture_output=True)
    git = W.Git(a.repo)
    rows = []
    import csv
    for r in csv.DictReader(open(ARCHIVE / "index.csv", encoding="utf-8")):
        if r["created_at"] < a.since or r["logs_status"] != "SAVED":
            continue
        with zipfile.ZipFile(ARCHIVE / r["run_id"] / "logs.zip") as z:
            if not any(b"STEP DONE: score_factors_dual_door rc=0" in z.read(n) for n in z.namelist()):
                continue
        try:
            res = W.verify(r["run_id"], ARCHIVE, a.repo)
        except Exception as e:  # missing objects: fetch the repo and rerun
            rows.append({"run_id": r["run_id"], "workflow": r["workflow_name"], "error": str(e)[:200]})
            continue
        row = {"run_id": r["run_id"], "workflow": r["workflow_name"], "runner": res.get("runner_type"),
               "run_created_at": r["created_at"], "run_updated_at": r["updated_at"],   # GitHub's clock (witness), for consumers' T checks
               "verdict": res["verdict"], "failed_checks": [k for k, v in res["checks"].items() if not v],
               "output_commit": res.get("output_commit"), "candidates": res.get("candidate_counts"),
               "momentum": list((res.get("leg_counts") or {}).get("momentum", {})),
               "input_issues": [i["path"].split("/")[-1] for i in res.get("input_issues", [])]}
        if res.get("output_commit"):
            row["pair"], row["pair_detail"] = pair_check(git, res["output_commit"])
        rows.append(row)
        print(json.dumps(row))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    W.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (W.OUT_DIR / f"check_{stamp}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
