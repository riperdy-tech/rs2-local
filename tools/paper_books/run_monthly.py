"""The monthly paper-books run (task RS2-Paper-Books, days 1, 2 and 3 at 08:00 KST; register_paper_books_task.ps1).

    python tools/paper_books/run_monthly.py

In order; a failing step logs FAILED to cache/paper_books.log and the run exits 1:
  0. take cache/rs2_state.lock (sync_state.py takes it too, so its reset/commit never runs inside this run), refuse a leftover
     paper-books/unpushed branch in rs2-state, then `git pull --rebase --autostash` there
  1. `git fetch origin` in the screener publish clone (it only moves origin/* refs)
  2. check_new_runs.py: archive and verify the new GitHub runs; a row with an error (missing git objects, ...) fails the step
  3. forward_ledger.py --asof <last completed New York session>; a "STOP at" line (no verified scoring run) fails the step
  4. universe.py fetch for each contemporaneous formation whose latest universe price fetch does not reach the date its marks need
  5. m3o_engine.py (its stop rule exits nonzero)
  6. commit paper_books/ in rs2-state by pathspec and push (pull --rebase and retry); this also runs after a failed step, so nothing a
     step appended is left uncommitted. A push that still fails leaves branch paper-books/unpushed and exits 1.
Idempotent: when mtm_<asof>.json and marks/<asof>.json both exist for the last completed session, nothing runs (a second fetch of
the same date is not identical, and the engine's stop rule would refuse its marks).
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402
from state_lock import rs2_state_lock  # noqa: E402

LOG = ROOT / "cache" / "paper_books.log"
UNPUSHED = "paper-books/unpushed"


class Failed(Exception):
    pass


def log(msg):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(name, args, cwd=None):
    """Run one command; log its output; return stdout. Nonzero exit -> Failed."""
    log(f"[{name}] {' '.join(str(a) for a in args)}")
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (p.stdout + p.stderr).splitlines():
        if line.strip():
            log(f"[{name}]   {line}")
    if p.returncode != 0:
        raise Failed(f"{name} exited {p.returncode}")
    return p.stdout


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise Failed(f"git {' '.join(args)} in {repo}: {(p.stderr or p.stdout).strip()[:300]}")
    return p


def py(script, *args):
    return [sys.executable, "-u", str(HERE / script), *args]


def universe_due(books, asof):
    """[(T, end)]: contemporaneous formations (an inputs map not labelled retrospective) whose latest universe price fetch ends before
    the date their marks need (the next formation's fill session, else asof)."""
    forms = sorted((json.loads(l) for l in (books / "m3l_forward" / "formations.jsonl").read_text(encoding="utf-8").splitlines()
                    if l.strip()), key=lambda r: r["formation_T"])
    due = []
    for i, rec in enumerate(forms):
        T = rec["formation_T"]
        mp = books / "m3o" / "inputs" / f"formation_{T}.json"
        if not mp.exists() or json.loads(mp.read_text(encoding="utf-8")).get("label") == "retrospective":
            continue
        end = forms[i + 1]["fill_session"] if i + 1 < len(forms) else asof
        receipts = sorted((books / "m3o" / "universe_prices").glob(f"universe_{T}_*.receipt.json"))
        have = json.loads(receipts[-1].read_text(encoding="utf-8"))["window"][1] if receipts else ""
        if have < end:
            due.append((T, end))
    return due


def steps(state, books, asof):
    git(state, "pull", "--rebase", "--autostash")
    run("fetch", ["git", "-C", book_paths.screener_repo(), "fetch", "origin"])
    out = run("check_new_runs", py("check_new_runs.py"))
    errors = [l for l in out.splitlines() if l.startswith("{") and "error" in json.loads(l)]
    if errors:
        raise Failed(f"check_new_runs: {len(errors)} run(s) could not be verified (see the log)")
    out = run("forward_ledger", py("forward_ledger.py", "--asof", asof))
    if any(l.startswith("STOP") for l in out.splitlines()):
        raise Failed("forward_ledger stopped: a month-end formation has no verified scoring run")
    for T, end in universe_due(books, asof):
        run("universe", py("universe.py", "fetch", T, "--asof", end))
    run("m3o_engine", py("m3o_engine.py"))


def commit_and_push(state, failed):
    git(state, "add", "--", "paper_books")
    if git(state, "diff", "--cached", "--quiet", "--", "paper_books", check=False).returncode == 0:
        log("[commit] no change in paper_books/")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    msg = f"paper books {stamp}" + (f" (run FAILED: {failed})" if failed else "")
    git(state, "commit", "-m", msg, "--", "paper_books")
    log(f"[commit] {git(state, 'rev-parse', '--short', 'HEAD').stdout.strip()} {msg}")
    for attempt in range(1, 4):
        p = git(state, "push", check=False)
        if p.returncode == 0:
            log("[push] pushed")
            return
        log(f"[push] attempt {attempt} failed: {(p.stderr or p.stdout).strip()[:300]}")
        git(state, "pull", "--rebase", "--autostash", check=False)
        time.sleep(30 * attempt)
    git(state, "branch", "-f", UNPUSHED, "HEAD")
    raise Failed(f"push failed 3 times; the commit is kept on branch {UNPUSHED} of {state}: push it, then delete the branch")


def main():
    state, books = book_paths.books().parent, book_paths.books()
    import forward_ledger as fl
    asof = fl.last_completed_session().isoformat()
    log(f"start: asof {asof}, books {books}")
    if (books / "m3l_forward" / f"mtm_{asof}.json").exists() and (books / "m3o" / "ledger" / "marks" / f"{asof}.json").exists():
        log(f"done: the books are already marked for {asof}; nothing to do")
        return 0
    with rs2_state_lock(wait_s=900) as held:
        if not held:
            log("FAILED: cache/rs2_state.lock is still held after 15 minutes")
            return 2
        if git(state, "rev-parse", "--verify", "-q", UNPUSHED, check=False).returncode == 0:
            log(f"FAILED: branch {UNPUSHED} exists in {state}: push its commit, then delete the branch")
            return 1
        failed = None
        try:
            steps(state, books, asof)
        except Failed as e:
            failed = str(e)
        except Exception as e:                                   # anything unexpected is a failure too, never a silent pass
            failed = f"{type(e).__name__}: {e}"
        try:
            commit_and_push(state, failed)
        except Failed as e:
            failed = f"{failed}; {e}" if failed else str(e)
    if failed:
        log(f"FAILED: {failed}")
        return 1
    log(f"done: asof {asof}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except BaseException as e:                                   # a path that does not resolve, a missing exclusion file, ...
        log(f"FAILED: {type(e).__name__}: {e}")
        code = 1
    sys.exit(code)
