"""m3l_gh_run_witness.py: is a GitHub-run factor scoring PIT_PROSPECTIVE (PLAN W.4), candidate by candidate?

Usage: python m3l_gh_run_witness.py <run_id> [--archive DIR] [--repo DIR] [--out DIR]

Read-only. Evidence comes only from independent witnesses: GitHub's run metadata and server log (archived by WO_L1)
and git objects. Local clocks, file mtimes and generated_at fields are never used as evidence.

Run checks (any failure fails the run):
  R1 conclusion == success
  R2 head_sha and runner type from GitHub's metadata
  R3 the log's push line '<old>..<new>  main -> main' starts at head_sha; <new> exists and its first parent is head_sha
  R4 decision time = run updated_at (GitHub server); the push line is at or before it
  R5 the scorer step finished with rc=0

Per candidate and leg: PIT_VALID / PIT_VALID_ANNOTATED / PIT_VALID_UNPRESERVED / ABSENT / EXCLUDED, with reasons.
"""
import argparse, csv, io, json, re, subprocess, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths  # noqa: E402

DEFAULT_ARCHIVE = book_paths.witness_archive()
DEFAULT_REPO = book_paths.screener_repo()
OUT_DIR = book_paths.books() / "m3l_verifier" / "out"
SCORER = "scripts/score_factors_dual_door.py"
OPERATOR_EXCLUDED = book_paths.operator_excluded()

# Chain steps that run before the scorer and the data files they write. Each entry is confirmed against the step's
# source at head_sha (the file name must appear in it); an unconfirmed entry is reported, never silently used.
IN_RUN_WRITERS = {
    "scripts/refresh_prices.py": ["public/data/stocks.json"],
    "scripts/build_price_history.py": ["public/data/price_history.json"],
    "scripts/fetch_macro_state.py": ["public/data/macro_state.json"],
    "scripts/score_reverse.py": ["public/data/reverse_scores.json"],
    "scripts/filter_tier1_hygiene.py": ["public/data/tier1_hygiene_survivors.json"],
    "scripts/build_daily_price_history.py": ["public/data/daily_closes.json"],
    "scripts/build_momentum_state.py": ["public/data/momentum_state.json"],
    "scripts/fetch_eps_trajectory.py": ["public/data/eps_trajectory.json"],
    # sync_mri_snapshot() runs inside the scorer; on a machine with an MRI checkout it copies the live outputs into
    # public/data/mri/ before the scorer reads them (the data-fetch workflow commits public/data/mri/).
    "scripts/mri_sync.py": ["public/data/mri/current_sector_ranking.json", "public/data/mri/cost_of_capital_anchor.json"],
    # Paradigm Weekly Analyst Coverage (paradigm-weekly-analyst.yml) runs these before run_chain.py; first verified 2026-11-02
    # (run 41327077634 had failed as UNEXPLAINED_CHANGE only because they were missing here).
    "scripts/fetch_sec_data.py": ["public/data/stocks.json"],
    "scripts/build_fundamentals_history.py": ["public/data/fundamentals_history.json", "public/data/fundamentals_battery.json",
                                              "public/data/stocks.json"],
}
SCORER_PREVIOUS_OUTPUT = {"public/data/factor_scores.json"}  # read before overwrite (P3.5 band hysteresis)
SCORER_OUTPUT_ONLY = {"public/data/factor_scores_dual_door.json"}  # OUT_JSON: written, never read
# Read by helpers the scorer imports at head_sha (tradability.CONFIG_JSON, hygiene_thresholds.SIFTER_CONFIG_PATH,
# depth_conviction.load_conviction_map(DATA / "depth_reports")). A directory is compared as a git tree.
HELPER_INPUTS = ["scripts/not_tradable.json", "scripts/sifter_config.json", "public/data/depth_reports"]
# Used only when the primary file is absent (sifter_config.json -> momentum_config.json).
OPTIONAL_FALLBACKS = {"scripts/momentum_config.json": "scripts/sifter_config.json"}
PRIMARY_OF = {v: k for k, v in OPTIONAL_FALLBACKS.items()}  # primary -> its fallback
STATUS_ORDER = ["PIT_VALID", "PIT_VALID_ANNOTATED", "PIT_VALID_UNPRESERVED", "ABSENT", "EXCLUDED"]


class Git:
    def __init__(self, repo):
        self.repo = str(repo)

    def run(self, *args, check=True):
        p = subprocess.run(["git", "-C", self.repo, *args], capture_output=True)
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
        return p

    def exists(self, rev):
        return self.run("rev-parse", "--verify", "-q", rev + "^{commit}", check=False).returncode == 0

    def rev(self, rev):
        return self.run("rev-parse", rev + "^{commit}").stdout.decode().strip()

    def blob_id(self, rev, path):
        p = self.run("rev-parse", f"{rev}:{path}", check=False)
        return p.stdout.decode().strip() if p.returncode == 0 else None

    def show(self, rev, path):
        return self.run("show", f"{rev}:{path}").stdout

    def json(self, rev, path, default=None):
        if default is not None and self.blob_id(rev, path) is None:
            return default
        return json.loads(self.show(rev, path).decode("utf-8"))


def read_log_text(run_dir):
    """{job log file: text}. GitHub's log archive holds one top-level file per job (plus per-step copies)."""
    z = run_dir / "logs.zip"
    if z.exists():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in sorted(zf.namelist()) if "/" not in n] or sorted(zf.namelist())
            return {n: zf.read(n).decode("utf-8", "replace") for n in names}
    t = run_dir / "log.txt"
    return {"log.txt": t.read_text(encoding="utf-8", errors="replace")} if t.exists() else {}


def load_jobs(run_dir):
    raw = (run_dir / "jobs.json").read_text(encoding="utf-8")
    jobs, dec, i = [], json.JSONDecoder(), 0
    while i < len(raw):
        while i < len(raw) and raw[i].isspace():
            i += 1
        if i >= len(raw):
            break
        obj, i = dec.raw_decode(raw, i)
        jobs.extend(obj.get("jobs", []))
    return jobs


def parse_ts(s):
    s = s.strip().rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = head + "." + frac[:6]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


PUSH_RE = re.compile(r"(\d{4}-\d\d-\d\dT[\d:.]+Z)\s+\+?\s*([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})\s+main -> main")


COMMIT_RE = re.compile(r"(\d{4}-\d\d-\d\dT[\d:.]+Z)\s+\[main ([0-9a-f]{7,40})\] ")
CHECKOUT_RE = re.compile(r"(\d{4}-\d\d-\d\dT[\d:.]+Z)\s+HEAD is now at ([0-9a-f]{7,40})")
# GitHub-hosted actions/checkout (-B main refs/remotes/origin/main) prints `git log -1 --format=%H`, then the SHA.
CHECKOUT_RE2 = re.compile(r"(\d{4}-\d\d-\d\dT[\d:.]+Z)\s+\[command\]\S*git log -1 --format=%H\s*\n\S+Z\s+([0-9a-f]{40})")


def run_checks(run, jobs, log, git):
    """`log` is {job log file: text} (or one string).

    v1.2 (2026-10-29): the run's own output commit C is the `[main <sha>]` line that `git commit` printed in the job
    log that ran the scorer. Its first parent is the scoring checkout ("base"). The base is witnessed when the same job
    log shows actions/checkout's `HEAD is now at <base>` (GitHub's server log, at job start), or when it is head_sha.
    The push line must carry C (C is an ancestor of, or equal to, the pushed tip; a writer that merged
    origin/main pushes a merge whose other parent is someone else's work, which is NOT this run's output).
    """
    logs = log if isinstance(log, dict) else {"log": log}
    checks, out = {}, {}
    checks["R1_conclusion_success"] = run.get("conclusion") == "success"
    head = run.get("head_sha")
    out["head_sha"] = head
    runners = sorted({j.get("runner_name") or "" for j in jobs})
    labels = sorted({lab for j in jobs for lab in (j.get("labels") or [])})
    out["runner_names"], out["runner_labels"] = runners, labels
    out["runner_type"] = "self_hosted" if any("self-hosted" in lab for lab in labels) else "github_hosted"
    checks["R2_head_sha_present"] = bool(head) and git.exists(head)

    scorer_files = [n for n, txt in logs.items() if re.search(r"STEP DONE: score_factors_dual_door rc=0", txt)]
    r3 = r4 = False
    if scorer_files and checks["R2_head_sha_present"]:
        txt = logs[scorer_files[0]]
        commits = [m for m in COMMIT_RE.findall(txt) if git.exists(m[1])]
        if commits:
            out["commit_line_utc"], c = commits[0][0], git.rev(commits[0][1])
            base = git.run("rev-parse", f"{c}^1", check=False).stdout.decode().strip()
            out["output_commit"], out["scoring_base"] = c, base
            checkouts = {git.rev(m[1]) for m in CHECKOUT_RE.findall(txt) + CHECKOUT_RE2.findall(txt) if git.exists(m[1])}
            out["scoring_base_witness"] = ("head_sha" if base == head else
                                           "checkout_log" if base in checkouts else "unwitnessed")
            r3 = out["scoring_base_witness"] != "unwitnessed"
            for ts, _old, new in PUSH_RE.findall(txt):
                if git.exists(new) and git.run("merge-base", "--is-ancestor", c, git.rev(new), check=False).returncode == 0:
                    out["push_line_utc"], out["pushed_tip"] = ts, git.rev(new)
                    out["pushed_tip_is_output"] = git.rev(new) == c
                    break
    checks["R3_output_commit_on_witnessed_base"] = r3
    updated = run.get("updated_at")
    out["decision_time_utc"] = updated
    r4 = bool(updated) and "push_line_utc" in out and parse_ts(out["push_line_utc"]) <= parse_ts(updated)
    checks["R4_output_pushed_before_run_end"] = r4
    checks["R5_scorer_rc0"] = bool(scorer_files)
    mri = re.search(r"MRI snapshot sync: ([^\n]+)", "\n".join(logs[n] for n in scorer_files) if scorer_files else "")
    out["mri_sync_log_line"] = mri.group(1).strip() if mri else None
    out["scorer_job_log"] = logs[scorer_files[0]] if scorer_files else None
    return checks, out


def scorer_input_paths(src):
    paths = set()
    for m in re.finditer(r'DATA\s*/\s*"([^"]+)"(?:\s*/\s*"([^"]+)")?', src):
        p = "public/data/" + m.group(1) + ("/" + m.group(2) if m.group(2) else "")
        if p.endswith(".json"):
            paths.add(p)
    for m in re.finditer(r'parent\s*/\s*"([\w.]+\.json)"', src):
        paths.add("scripts/" + m.group(1))
    return sorted(paths)


def workflow_git_adds(yml):
    return set(re.findall(r"git add (public/data/[^\s|]+)", yml))


def classify_inputs(git, head, outc, run, inputs, mri_sync_line=None, job_log=None):
    wf_path = run.get("path") or ""
    wf_path = wf_path.split("@")[0]
    adds = workflow_git_adds(git.show(head, wf_path).decode("utf-8")) if wf_path else set()
    log_steps_writers, confirmations = {}, {}
    for script, files in IN_RUN_WRITERS.items():
        if script == "scripts/mri_sync.py":
            if "copied from" not in (mri_sync_line or ""):
                continue  # it wrote nothing: the log says the MRI outputs were not found on this runner
        elif job_log is not None and Path(script).stem not in job_log:
            continue  # this run's scoring job never ran the writer (a chain step or a workflow command)
        src = git.show(head, script).decode("utf-8", "replace") if git.blob_id(head, script) else ""
        for f in files:
            confirmations[f] = Path(f).name in src
            if confirmations[f]:
                log_steps_writers[f] = script
    rows = []
    for p in inputs:
        h, o = git.blob_id(head, p), git.blob_id(outc, p)
        if p in SCORER_PREVIOUS_OUTPUT:
            cls, note = "PREVIOUS_OUTPUT", "read for hysteresis; the head_sha blob is the input"
        elif p in SCORER_OUTPUT_ONLY:
            cls, note = "OUTPUT_ONLY", "written by the scorer, not read"
        elif h is None and o is None and p in OPTIONAL_FALLBACKS and git.blob_id(head, OPTIONAL_FALLBACKS[p]):
            cls, note = "FALLBACK_UNUSED", f"read only when {OPTIONAL_FALLBACKS[p]} is absent; it is present"
        elif h is None and o is None and p in PRIMARY_OF and git.blob_id(head, PRIMARY_OF[p]):
            cls, note = "PRIMARY_ABSENT_FALLBACK_USED", f"absent; the scorer falls back to {PRIMARY_OF[p]}, which is present"
        elif h is None and o is None:
            cls, note = "MISSING", "absent from both trees"
        elif p in log_steps_writers:
            if p in adds or any(a.endswith("/") and p.startswith(a) for a in adds):  # `git add public/data/mri/`
                cls, note = "IN_RUN_COMMITTED", f"written by {log_steps_writers[p]}; committed"
            else:
                cls, note = "IN_RUN_UNPRESERVED", f"written by {log_steps_writers[p]}; not in the workflow's git add list"
        elif h == o:
            cls, note = "HEAD_TREE", "identical blob before and after the run"
        else:
            cls, note = "UNEXPLAINED_CHANGE", "changed in the output commit without a known writer"
        rows.append({"path": p, "class": cls, "head_blob": h, "output_blob": o, "note": note})
    unconfirmed = sorted(f for f, ok in confirmations.items() if not ok)
    return rows, sorted(adds), unconfirmed


def worst(statuses):
    return max(statuses, key=STATUS_ORDER.index)


def candidate_table(git, head, outc, decision_date, input_class):
    fs = git.json(outc, "public/data/factor_scores_dual_door.json")
    noms = fs["nominated_tickers"]
    fh = git.json(head, "public/data/fundamentals_history.json")
    fh_t, cover = fh.get("tickers", {}), fh.get("shares_cover", {})
    bat = git.json(head, "public/data/fundamentals_battery.json", {}).get("tickers", {})
    eps = git.json(head, "public/data/eps_trajectory.json", {})
    ph = git.json(outc, "public/data/price_history.json").get("prices", {})
    mom_rev = outc if input_class.get("public/data/momentum_state.json") != "IN_RUN_UNPRESERVED" else head
    mom = git.json(mom_rev, "public/data/momentum_state.json", {}).get("tickers", {})
    mom_unpreserved = input_class.get("public/data/momentum_state.json") == "IN_RUN_UNPRESERVED"
    rows = []
    for t in noms:
        legs = {}
        if t in fh_t:
            filed = (cover.get(t) or {}).get("filed")
            if filed and filed > decision_date:
                legs["sec"] = ("EXCLUDED", f"post_decision_filed:{filed}")
            else:
                legs["sec"] = ("PIT_VALID", f"head_tree; shares_cover_filed={filed}")
        else:
            legs["sec"] = ("ABSENT", "no fundamentals_history row")
        legs["battery"] = ("PIT_VALID", "head_tree") if t in bat else ("ABSENT", "no battery row")
        legs["price"] = ("PIT_VALID_ANNOTATED", "in_run_committed; undated_series") if t in ph else ("ABSENT", "no price row")
        if t in mom:
            pa = mom[t].get("price_asof")
            if pa and pa > decision_date:
                legs["momentum"] = ("EXCLUDED", f"post_decision_price_asof:{pa}")
            elif mom_unpreserved:
                legs["momentum"] = ("PIT_VALID_UNPRESERVED",
                                    f"regenerated in run, bytes not committed; head_tree price_asof={pa}")
            else:
                legs["momentum"] = ("PIT_VALID", f"price_asof={pa}")
        else:
            legs["momentum"] = ("ABSENT", "no momentum row" + (" in head_tree copy" if mom_unpreserved else ""))
        if t in eps:
            nums = [v for k, v in eps[t].items() if k not in ("fetched_at", "input_hash", "source")]
            legs["eps"] = (("PIT_VALID_ANNOTATED", "eps_null_record") if all(v is None for v in nums)
                           else ("PIT_VALID", f"head_tree; fetched_at_claim={eps[t].get('fetched_at')}"))
        else:
            legs["eps"] = ("ABSENT", "no eps_trajectory row")
        prof = fs["profiles"].get(t, {})
        legs["factor_rank"] = (("PIT_VALID", f"best_pctl={prof.get('best_pctl')}; doors={prof.get('nominated_doors')}")
                               if prof else ("ABSENT", "no profile"))
        status = worst([s for s, _ in legs.values()])
        flags = ["operator_excluded"] if t in OPERATOR_EXCLUDED else []
        rows.append({"ticker": t, "status": "EXCLUDED" if status == "EXCLUDED" else "PIT_PROSPECTIVE",
                     "worst_leg_status": status, "flags": flags, "legs": legs})
    return fs, rows


def verify(run_id, archive=DEFAULT_ARCHIVE, repo=DEFAULT_REPO):
    run_dir = Path(archive) / str(run_id)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    jobs = load_jobs(run_dir)
    log = read_log_text(run_dir)
    git = Git(repo)
    checks, meta = run_checks(run, jobs, log, git)
    job_log = meta.pop("scorer_job_log", None)
    result = {"schema": "m3l_gh_run_witness_v1.2", "run_id": run_id, "workflow": run.get("name"),
              "created_at": run.get("created_at"), "checks": checks, **meta}
    if not all(checks.values()):
        result["verdict"] = "FAIL"
        return result
    # The scoring job's checkout: head_sha itself, or a commit this run's fetch job pushed. Inputs and code come from it.
    head, outc = meta["scoring_base"], meta["output_commit"]
    inputs = sorted(set(scorer_input_paths(git.show(head, SCORER).decode("utf-8"))) | set(HELPER_INPUTS))
    rows, adds, unconfirmed = classify_inputs(git, head, outc, run, inputs, meta.get("mri_sync_log_line"),
                                              job_log)
    result["scorer_inputs"] = rows
    result["workflow_git_adds"] = adds
    result["writer_map_unconfirmed"] = unconfirmed
    mri_blob = git.blob_id(outc, "public/data/mri/current_sector_ranking.json")
    mri_snapshot = git.json(outc, "public/data/mri/current_sector_ranking.json") if mri_blob else {}
    decision_date = meta["decision_time_utc"][:10]
    line = meta["mri_sync_log_line"] or ""
    result["mri"] = {"branch": ("COMMITTED_SNAPSHOT" if mri_blob and "not found" in line else
                                "LIVE_PEER_COPIED_AND_COMMITTED" if mri_blob and "copied from" in line else
                                "NO_SNAPSHOT_IN_TREE" if not mri_blob else "UNDETERMINED"),
                     "log_line": line or None,
                     "snapshot_blob": git.blob_id(outc, "public/data/mri/current_sector_ranking.json"),
                     "ranking_date": mri_snapshot.get("date")}
    fs, cand = candidate_table(git, head, outc, decision_date, {r["path"]: r["class"] for r in rows})
    result["nominated_count"] = fs.get("nominated_count")
    result["candidates"] = cand
    counts = {}
    for c in cand:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    result["candidate_counts"] = counts
    leg_counts = {}
    for c in cand:
        for leg, (s, _) in c["legs"].items():
            leg_counts.setdefault(leg, {}).setdefault(s, 0)
            leg_counts[leg][s] += 1
    result["leg_counts"] = leg_counts
    bad_inputs = [r for r in rows if r["class"] in ("MISSING", "UNEXPLAINED_CHANGE")]
    result["input_issues"] = bad_inputs
    result["reconciles"] = sum(counts.values()) == len(fs["nominated_tickers"]) == fs.get("nominated_count")
    # An unconfirmed writer is one this code version does not have; it is reported, not fatal. A changed input with no
    # known writer is fatal: nothing explains where its bytes came from.
    unexplained = [r["path"] for r in rows if r["class"] == "UNEXPLAINED_CHANGE"]
    result["verdict"] = "PASS" if result["reconciles"] and not unexplained else "FAIL"
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args()
    res = verify(a.run_id, a.archive, a.repo)
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    (out / f"{a.run_id}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if "candidates" in res:
        with open(out / f"{a.run_id}.csv", "w", newline="", encoding="utf-8") as f:
            legs = list(res["candidates"][0]["legs"].keys())
            w = csv.writer(f)
            w.writerow(["ticker", "status", "worst_leg_status", "flags"] + [x for l in legs for x in (l, l + "_reason")])
            for c in res["candidates"]:
                w.writerow([c["ticker"], c["status"], c["worst_leg_status"], ";".join(c["flags"])]
                           + [x for l in legs for x in c["legs"][l]])
    print(json.dumps({k: res.get(k) for k in ("verdict", "checks", "candidate_counts", "leg_counts",
                                               "nominated_count", "reconciles", "input_issues",
                                               "writer_map_unconfirmed", "mri")}, indent=1))


if __name__ == "__main__":
    main()
