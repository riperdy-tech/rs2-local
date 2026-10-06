"""The holdout lock (SPEC section 6): a run that touches valuation dates in 2023-2024 is refused unless a FREEZE FILE names every engine in the run, by
git commit and by the sha256 of the engine's files.

Development dates are 2017-2022.  Holdout dates are 2023-01-01 .. 2024-12-31 inclusive.  A date outside both windows (2016 or earlier, 2025 on)
is not locked here (the AI replay has its own rules); the run still states which window each date is in.

Freeze file (JSON):
    {"engines": {"<engine name>": {"git_commit": "<40-hex>", "files": {"<path relative to the repo root>": "<sha256>", ...}}}, "frozen_at": "...",
     "registration": "<registration file name>"}

An engine passes when, for EVERY file in its identity (`engine.frozen_files`: its own module by default; the old engine lists the reference modules
too):
  1. the freeze lists the file with a sha256;
  2. the file on disk hashes to it (the working copy is the frozen copy).  The hash is the sha256 of the text with CRLF read as LF, so a Windows
     checkout and the git blob of the same content agree; the plain sha256 of a CRLF working file differs;
  3. the file at the named commit hashes to it (the commit really holds that content: `git show <commit>:<path>`);
  4. the commit is an ancestor of, or equal to, HEAD.
The engine must also have no frozen file that the freeze omits, and the freeze must name no engine twice.

"Run once": every accepted holdout run appends a line to `holdout_runs.jsonl` next to the freeze file; a second holdout run of the same engine under the
same freeze is refused unless `allow_rerun=True`, which only the coordinator sets (it is not a command-line default).

Nothing here reads a price, an outcome or a filing.
"""
import hashlib
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

DEV_START, DEV_END = date(2017, 1, 1), date(2022, 12, 31)
HOLDOUT_START, HOLDOUT_END = date(2023, 1, 1), date(2024, 12, 31)


class HoldoutRefused(RuntimeError):
    pass


def classify(d):
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    if DEV_START <= d <= DEV_END:
        return "development"
    if HOLDOUT_START <= d <= HOLDOUT_END:
        return "holdout"
    return "outside_development_and_holdout"


def touches_holdout(dates):
    return sorted({str(d)[:10] for d in dates if classify(d) == "holdout"})


CRLF, LF = bytes([13, 10]), bytes([10])


def sha256_bytes(b):
    """sha256 of the content with CRLF read as LF: a Windows checkout (autocrlf) and the git blob of the same text must hash the same."""
    return hashlib.sha256(b.replace(CRLF, LF)).hexdigest()


def sha256_file(p):
    return sha256_bytes(Path(p).read_bytes())


def _git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode != 0:
        raise HoldoutRefused(f"git {' '.join(args)} failed in {repo}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def repo_root(path):
    return Path(_git(Path(path).resolve().parent, "rev-parse", "--show-toplevel").decode().strip())


def engine_identity(engine, repo=None):
    """{"git_commit": HEAD, "files": {repo-relative posix path: sha256}} of an engine as it is now."""
    files = [Path(p).resolve() for p in getattr(engine, "frozen_files", [])]
    if not files:
        raise HoldoutRefused(f"engine {getattr(engine, 'engine_name', engine)!r} declares no frozen_files: it has no identity to freeze")
    root = Path(repo).resolve() if repo else repo_root(files[0])
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    return {"git_commit": head, "files": {p.relative_to(root).as_posix(): sha256_file(p) for p in files}}, root


def write_freeze(path, engines, repo=None, registration=None):
    """Write a freeze file for the engines as they are now (the coordinator does this, once, after the development work is final)."""
    entries = {}
    for e in engines:
        ident, _root = engine_identity(e, repo)
        entries[e.engine_name] = ident
    doc = {"engines": entries, "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "registration": registration}
    Path(path).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


def _check_engine(engine, entry, repo):
    name = getattr(engine, "engine_name", "?")
    files = {Path(p).resolve(): None for p in getattr(engine, "frozen_files", [])}
    if not files:
        raise HoldoutRefused(f"engine {name!r} declares no frozen_files")
    commit = entry.get("git_commit")
    if not commit or len(commit) != 40:
        raise HoldoutRefused(f"freeze entry for {name!r} names no 40-hex git commit")
    root = Path(repo).resolve() if repo else repo_root(next(iter(files)))
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    anc = subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=root, capture_output=True)
    if anc.returncode != 0:
        raise HoldoutRefused(f"frozen commit {commit} of {name!r} is not an ancestor of (or equal to) HEAD {head}")
    listed = entry.get("files") or {}
    for p in files:
        rel = p.relative_to(root).as_posix()
        want = listed.get(rel)
        if not want:
            raise HoldoutRefused(f"freeze for {name!r} does not list {rel}")
        have = sha256_file(p)
        if have != want:
            raise HoldoutRefused(f"{rel} of {name!r} has sha256 {have}, the freeze says {want}: the engine changed after the freeze")
        at_commit = sha256_bytes(_git(root, "show", f"{commit}:{rel}"))
        if at_commit != want:
            raise HoldoutRefused(f"{rel} at commit {commit} has sha256 {at_commit}, the freeze says {want}: the commit does not hold the frozen file")
    return commit


def enforce(dates, engines, freeze_path=None, repo=None, allow_rerun=False, record=True):
    """Refuse (HoldoutRefused) a run that touches the holdout unless `freeze_path` freezes every engine.  Returns {"holdout_dates": [...],
    "windows": {date: window}, "frozen": {engine: commit}}.  Call this FIRST in a run, before any data is opened."""
    dates = [str(d)[:10] for d in dates]
    windows = {d: classify(d) for d in dates}
    touched = touches_holdout(dates)
    info = {"holdout_dates": touched, "windows": windows, "frozen": {}}
    if not touched:
        return info
    if freeze_path is None or not Path(freeze_path).is_file():
        raise HoldoutRefused(f"dates {touched} are in the holdout (2023-2024) and no freeze file was given: refused")
    doc = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    entries = doc.get("engines") or {}
    for e in engines:
        name = getattr(e, "engine_name", None)
        if name not in entries:
            raise HoldoutRefused(f"the freeze file does not name engine {name!r}: refused")
        info["frozen"][name] = _check_engine(e, entries[name], repo)
    ledger = Path(freeze_path).with_name("holdout_runs.jsonl")
    seen = set()
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                j = json.loads(line)
                seen.add((j["freeze_sha256"], j["engine"]))
    fsha = sha256_file(freeze_path)
    for e in engines:
        if (fsha, e.engine_name) in seen and not allow_rerun:
            raise HoldoutRefused(f"engine {e.engine_name!r} has already been run on the holdout under this freeze (the holdout is run once): refused")
    if record:
        with open(ledger, "a", encoding="utf-8") as f:
            for e in engines:
                f.write(json.dumps({"freeze_sha256": fsha, "engine": e.engine_name, "dates": touched,
                                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    return info
