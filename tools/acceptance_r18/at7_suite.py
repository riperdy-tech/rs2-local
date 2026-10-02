"""AT7 (brief section 6): the full rs2 suite passes, run in the foreground; the backtest harness tests still pass at their own pinned commits.

  python at7_suite.py --tree <rs2 final commit> [--python <interpreter>] [--harness <worktree>@<commit>::<tests path> ...] [--out <result.json>]

The suite is `python -m pytest tests tools/audit_202608/tests -q` run in --tree (default interpreter: C:/Program Files/Python312/python.exe).
Each --harness names a worktree, the commit its HEAD must be (a different HEAD is a failure: the harness is tested at its pinned commit
only) and the tests path inside it; its tests run with that worktree as the working directory. The summary line of every run is recorded.
No socket is opened by this script; the suites it runs are the project's own (sockets are blocked by their fixtures).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402

DEFAULT_PY = r"C:\Program Files\Python312\python.exe"
SUMMARY = re.compile(r"^(?:=+ )?(\d+ (?:passed|failed|error)[^=]*?)(?: =+)?$", re.M)


def run_pytest(python, cwd, targets):
    p = subprocess.run([python, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider"], cwd=str(cwd), capture_output=True, text=True)
    text = (p.stdout or "") + (p.stderr or "")
    lines = [l.strip() for l in text.splitlines() if re.search(r"\b\d+ (passed|failed|error)", l)]
    return {"returncode": p.returncode, "summary_line": lines[-1] if lines else (text.strip().splitlines() or [None])[-1],
            "passed": p.returncode == 0}


def check_pin(worktree, commit):
    head, _clean = ac.git_head(worktree)
    return head, head is not None and head.startswith(commit) if commit else False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--python", default=DEFAULT_PY)
    ap.add_argument("--harness", action="append", default=[])
    ap.add_argument("--targets", nargs="*", default=["tests", "tools/audit_202608/tests"], help="the suite's test paths (default: the two directories)")
    ap.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    runs = []
    suite = run_pytest(a.python, a.tree, a.targets)
    suite.update(name="rs2 suite", tree=str(a.tree), commit=ac.git_head(a.tree)[0])
    runs.append(suite)
    for spec in a.harness:
        m = re.fullmatch(r"(.+?)@([0-9a-fA-F]{7,40})::(.+)", spec)
        if not m:
            raise SystemExit(f"--harness wants <worktree>@<commit>::<tests path>, got a different form")
        wt, commit, tests = Path(m.group(1)), m.group(2), m.group(3)
        head, pinned = check_pin(wt, commit)
        if not pinned:
            runs.append({"name": f"harness {wt.name}", "passed": False, "returncode": None, "summary_line": f"HEAD {head} is not the pinned commit {commit}"})
            continue
        r = run_pytest(a.python, wt, [tests])
        r.update(name=f"harness {wt.name}", tree=str(wt), commit=head)
        runs.append(r)
    ok = all(r["passed"] for r in runs)
    result = {"at": "AT7 suite", "pass": ok, "runs": runs, "summary": "; ".join(f"{r['name']}: {r['summary_line']}" for r in runs)}
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
