"""Negative controls and a positive path for m3l_gh_run_witness.py, on a throwaway git repository."""
import json, subprocess
from pathlib import Path

import pytest

import m3l_gh_run_witness as w


def sh(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True).stdout.decode().strip()


def put(repo, rel, obj):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def commit(repo, msg):
    sh(repo, "add", "-A")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    return sh(repo, "rev-parse", "HEAD")


SCORER_SRC = 'DATA = 1\nA = DATA / "fundamentals_history.json"\nB = DATA / "momentum_state.json"\n' \
             'C = DATA / "factor_scores_dual_door.json"\nD = DATA / "gone.json"\n'
WORKFLOW = "git add public/data/factor_scores_dual_door.json || true\n"


def base_tree(repo, filed="2026-10-20", price_asof="2026-10-27"):
    put(repo, "scripts/score_factors_dual_door.py", SCORER_SRC)
    put(repo, ".github/workflows/wf.yml", WORKFLOW)
    put(repo, "scripts/build_momentum_state.py", "out = 'momentum_state.json'\n")
    put(repo, "public/data/fundamentals_history.json",
        {"tickers": {"AAA": {}, "BBB": {}}, "shares_cover": {"AAA": {"filed": filed}, "BBB": {"filed": "2026-01-01"}}})
    put(repo, "public/data/fundamentals_battery.json", {"tickers": {"AAA": {}}})
    put(repo, "public/data/eps_trajectory.json", {"AAA": {"fetched_at": "x", "input_hash": "y", "source": "z",
                                                           "next_q_eps": None, "next_y_eps": None}})
    put(repo, "public/data/momentum_state.json", {"tickers": {"AAA": {"price_asof": price_asof},
                                                              "BBB": {"price_asof": "2026-10-27"}}})
    put(repo, "public/data/price_history.json", {"prices": {"AAA": [1, 2]}})


def output_tree(repo):
    put(repo, "public/data/factor_scores_dual_door.json",
        {"nominated_tickers": ["AAA", "BBB"], "nominated_count": 2, "profiles": {"AAA": {"best_pctl": 99}}})


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "init", "-q")
    return r


def make_run(repo, **tree_kw):
    base_tree(repo, **tree_kw)
    head = commit(repo, "head")
    output_tree(repo)
    out = commit(repo, "out")
    return head, out


def log_for(base, out, ts="2026-10-28T01:00:07Z", checkout=True, push_from=None):
    return ((f"2026-10-28T00:25:06Z HEAD is now at {base[:9]} msg\n" if checkout else "")
            + f"{ts} STEP DONE: score_factors_dual_door rc=0\n"
            + f"{ts} [main {out[:7]}] Auto-update\n"
            + f"{ts}    {(push_from or base)[:7]}..{out[:7]}  main -> main\n")


RUN = {"conclusion": "success", "updated_at": "2026-10-28T01:00:10Z", "path": ".github/workflows/wf.yml"}


def test_positive_run_checks_pass(repo):
    head, out = make_run(repo)
    checks, meta = w.run_checks({**RUN, "head_sha": head}, [], log_for(head, out), w.Git(repo))
    assert all(checks.values()), checks
    assert meta["output_commit"] == out


def test_r1_failed_conclusion(repo):
    head, out = make_run(repo)
    checks, _ = w.run_checks({**RUN, "conclusion": "failure", "head_sha": head}, [], log_for(head, out), w.Git(repo))
    assert checks["R1_conclusion_success"] is False


def test_r3_output_parent_not_head(repo):
    head, out = make_run(repo)
    put(repo, "x.txt", "unrelated")
    other = commit(repo, "other")  # parent is `out`, not `head`
    checks, _ = w.run_checks({**RUN, "head_sha": head}, [], log_for(head, other), w.Git(repo))
    assert checks["R3_output_commit_on_witnessed_base"] is False


def test_r3_missing_push_line(repo):
    head, out = make_run(repo)
    checks, _ = w.run_checks({**RUN, "head_sha": head}, [], "STEP DONE: score_factors_dual_door rc=0\n", w.Git(repo))
    assert checks["R3_output_commit_on_witnessed_base"] is False and checks["R4_output_pushed_before_run_end"] is False


def test_r4_push_after_run_end(repo):
    head, out = make_run(repo)
    checks, _ = w.run_checks({**RUN, "head_sha": head}, [], log_for(head, out, ts="2026-10-28T02:00:00Z"), w.Git(repo))
    assert checks["R4_output_pushed_before_run_end"] is False


def test_missing_input_and_unpreserved_classes(repo, monkeypatch):
    head, out = make_run(repo)
    monkeypatch.setattr(w, "IN_RUN_WRITERS", {"scripts/build_momentum_state.py": ["public/data/momentum_state.json"]})
    git = w.Git(repo)
    inputs = w.scorer_input_paths(git.show(head, w.SCORER).decode())
    rows, adds, unconfirmed = w.classify_inputs(git, head, out, {**RUN}, inputs)
    cls = {r["path"]: r["class"] for r in rows}
    assert cls["public/data/gone.json"] == "MISSING"
    assert cls["public/data/momentum_state.json"] == "IN_RUN_UNPRESERVED"
    assert cls["public/data/fundamentals_history.json"] == "HEAD_TREE"
    assert unconfirmed == []


def test_post_decision_filed_is_excluded(repo):
    head, out = make_run(repo, filed="2026-10-29")
    _, rows = w.candidate_table(w.Git(repo), head, out, "2026-10-28", {})
    aaa = next(r for r in rows if r["ticker"] == "AAA")
    assert aaa["status"] == "EXCLUDED" and aaa["legs"]["sec"][0] == "EXCLUDED"


def test_post_decision_price_asof_is_excluded(repo):
    head, out = make_run(repo, price_asof="2026-10-29")
    _, rows = w.candidate_table(w.Git(repo), head, out, "2026-10-28", {})
    aaa = next(r for r in rows if r["ticker"] == "AAA")
    assert aaa["legs"]["momentum"][0] == "EXCLUDED"


def test_absent_legs_and_null_eps_are_visible_not_dropped(repo):
    head, out = make_run(repo)
    _, rows = w.candidate_table(w.Git(repo), head, out, "2026-10-28", {})
    assert [r["ticker"] for r in rows] == ["AAA", "BBB"]
    aaa, bbb = rows
    assert aaa["legs"]["eps"] == ("PIT_VALID_ANNOTATED", "eps_null_record")
    assert bbb["legs"]["eps"][0] == "ABSENT" and bbb["status"] == "PIT_PROSPECTIVE"


def test_base_witnessed_by_checkout_line_passes(repo):
    head, mid = make_run(repo)              # mid: a commit the scoring job checked out (e.g. the fetch job's push)
    put(repo, "y.txt", "scores")
    out = commit(repo, "scores")
    checks, meta = w.run_checks({**RUN, "head_sha": head}, [], {"0_score.txt": log_for(mid, out)}, w.Git(repo))
    assert all(checks.values()), checks
    assert meta["scoring_base"] == mid and meta["scoring_base_witness"] == "checkout_log"


def test_base_without_checkout_line_fails(repo):
    head, mid = make_run(repo)
    put(repo, "y.txt", "scores")
    out = commit(repo, "scores")
    logs = {"0_score.txt": log_for(mid, out, checkout=False)}
    checks, meta = w.run_checks({**RUN, "head_sha": head}, [], logs, w.Git(repo))
    assert checks["R3_output_commit_on_witnessed_base"] is False and meta["scoring_base_witness"] == "unwitnessed"


def test_merge_push_keeps_the_runs_own_commit_as_output(repo):
    head, out = make_run(repo)
    sh(repo, "checkout", "-q", "-b", "other", head)
    put(repo, "z.txt", "another writer")
    other = commit(repo, "other writer")
    sh(repo, "checkout", "-q", "-")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", "--no-edit", "other")
    merged = sh(repo, "rev-parse", "HEAD")
    checks, meta = w.run_checks({**RUN, "head_sha": head}, [], log_for(head, out, push_from=other)
                                .replace(f"..{out[:7]}  main", f"..{merged[:7]}  main"), w.Git(repo))
    assert all(checks.values()), checks
    assert meta["output_commit"] == out and meta["pushed_tip"] == merged and meta["pushed_tip_is_output"] is False


def test_writer_that_did_not_run_in_this_job_is_not_applied(repo, monkeypatch):
    head, out = make_run(repo)
    monkeypatch.setattr(w, "IN_RUN_WRITERS", {"scripts/build_momentum_state.py": ["public/data/momentum_state.json"]})
    git = w.Git(repo)
    inputs = w.scorer_input_paths(git.show(head, w.SCORER).decode())
    ran, _, _ = w.classify_inputs(git, head, out, {**RUN}, inputs, job_log="=== STEP: build_momentum_state ===")
    not_ran, _, _ = w.classify_inputs(git, head, out, {**RUN}, inputs, job_log="=== STEP: score_reverse ===")
    cls = lambda rows: {r["path"]: r["class"] for r in rows}["public/data/momentum_state.json"]
    assert cls(ran) == "IN_RUN_UNPRESERVED" and cls(not_ran) == "HEAD_TREE"
