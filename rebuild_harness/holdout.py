"""The holdout lock (SPEC section 6): a run that touches valuation dates in 2023-2024 is refused unless a FREEZE FILE names every engine in the run, by
git commit and by the sha256 of the engine's files.

Development dates are 2017-2022.  Holdout dates are 2023-01-01 .. 2024-12-31 inclusive.  A date outside both windows (2016 or earlier, 2025 on)
is not locked here (the AI replay has its own rules); the run still states which window each date is in.

Freeze file (JSON):
    {"engines": {"<engine name>": {"git_commit": "<40-hex>", "files": {"<path relative to the repo root>": "<sha256>", ...}}}, "frozen_at": "...",
     "registration": "<registration file name>", "contents": {...}}

THE FREEZE CONTENTS (Addendum J10).  A freeze names more than the code.  `contents` holds, and a holdout run must reproduce exactly:
    code_commit           the repository HEAD at the freeze
    point_in_time_store   the tree hash of the point-in-time store folder (every file's relative path, size and sha256, in sorted order, hashed together)
    price_snapshot        the sha256 of the price file (or the tree hash of a price folder)
    damodaran             the sha256 of MANIFEST.json and of every Damodaran file it lists (each must match the manifest)
    priors                the tree hash of the priors folder and of every vintage folder in it
    industry_crosswalk    the sha256 of the SIC -> Damodaran-industry crosswalk file
    sic_headers           the sha256 of the EDGAR headers file the SIC as filed is read from (None when no headers file is used)
    config                the engine configuration (the module constants the caller names)
    seeds                 the random seeds and the seed rule
    packages              the Python version and the versions of the packages the harness uses
`write_freeze` computes them from `inputs` (a dict of paths and values, see `compute_contents`) and REFUSES to write a freeze without them; `enforce` refuses a holdout run
whose freeze lacks any of them, or whose current inputs hash differently, naming the first difference.  The Muse items (model hash, quantization, context, sampling, prompts)
belong to gate 2's freeze, not this one.

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
import sys
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


# ---- the freeze contents (Addendum J10) ------------------------------------------------------------------------------------------------

CONTENT_KEYS = ("code_commit", "point_in_time_store", "price_snapshot", "damodaran", "priors", "industry_crosswalk", "sic_headers", "config", "seeds", "packages")
PACKAGES = ("numpy", "pandas", "openpyxl")
CHUNK = 1 << 20


def file_sha256(p):
    """sha256 of a data file's bytes as they are (no line-ending normalisation: that is for source files only)."""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(root):
    """{"tree_sha256", "n_files", "bytes"} of a folder: the sha256 of the sorted lines `relative posix path, size, file sha256` of every file under it.  A file added, removed,
    renamed or changed in any byte changes it."""
    root = Path(root)
    if not root.is_dir():
        raise HoldoutRefused(f"{root} is not a folder: no tree hash")
    lines, total = [], 0
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        size = p.stat().st_size
        total += size
        lines.append(f"{p.relative_to(root).as_posix()}\t{size}\t{file_sha256(p)}")
    return {"tree_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(), "n_files": len(lines), "bytes": total}


def package_versions(names=PACKAGES):
    from importlib import metadata
    out = {"python": ".".join(str(x) for x in sys.version_info[:3])}
    for n in names:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            out[n] = None
    return out


def _damodaran(root):
    root = Path(root)
    man_p = root / "MANIFEST.json"
    if not man_p.is_file():
        raise HoldoutRefused(f"no Damodaran MANIFEST.json under {root}")
    man = json.loads(man_p.read_text(encoding="utf-8"))
    files = {}
    for name, spec in sorted((man.get("files") or {}).items()):
        f = root / name
        if not f.is_file():
            raise HoldoutRefused(f"the Damodaran manifest lists {name}, which is not under {root}")
        h = file_sha256(f)
        if h != spec["sha256"]:
            raise HoldoutRefused(f"{name} has sha256 {h}, the Damodaran manifest says {spec['sha256']}")
        files[name] = h
    return {"manifest_sha256": file_sha256(man_p), "files": files}


def _price(path):
    path = Path(path)
    if path.is_dir():
        return dict(tree_hash(path), kind="folder")
    if not path.is_file():
        raise HoldoutRefused(f"no price snapshot at {path}")
    return {"sha256": file_sha256(path), "kind": "file", "bytes": path.stat().st_size}


def compute_contents(inputs, repo):
    """The freeze contents of the inputs a run reads.  `inputs`: {"store": folder, "prices": file or folder, "damodaran": folder, "priors": folder, "crosswalk": file, "headers": file or None,
    "config": {...}, "seeds": {...}}.  A missing key is a refusal (a freeze that cannot name an input is not a freeze)."""
    need = ("store", "prices", "damodaran", "priors", "crosswalk", "config", "seeds")
    miss = [k for k in need if inputs.get(k) is None]
    if miss:
        raise HoldoutRefused(f"the freeze contents need these inputs and the run gave none: {miss}")
    pri = Path(inputs["priors"])
    vint = {d.name: tree_hash(d)["tree_sha256"] for d in sorted(pri.iterdir()) if d.is_dir() and d.name.isdigit()}
    if not vint:
        raise HoldoutRefused(f"no priors vintage folder (a year) under {pri}")
    hdr = inputs.get("headers")
    return {"code_commit": _git(Path(repo), "rev-parse", "HEAD").decode().strip(), "point_in_time_store": tree_hash(inputs["store"]), "price_snapshot": _price(inputs["prices"]),
            "damodaran": _damodaran(inputs["damodaran"]), "priors": dict(tree_hash(pri), vintages=vint), "industry_crosswalk": {"sha256": file_sha256(inputs["crosswalk"])},
            "sic_headers": None if hdr is None else {"sha256": file_sha256(hdr)}, "config": json.loads(json.dumps(inputs["config"], sort_keys=True)),
            "seeds": json.loads(json.dumps(inputs["seeds"], sort_keys=True)), "packages": package_versions()}


def verify_contents(frozen, current):
    """Raises HoldoutRefused naming the first key whose frozen value differs from the current one (or is missing from the freeze)."""
    if not isinstance(frozen, dict):
        raise HoldoutRefused("the freeze file has no `contents` (Addendum J10): the commit alone is not a freeze")
    absent = [k for k in CONTENT_KEYS if k not in frozen]
    if absent:
        raise HoldoutRefused(f"the freeze contents lack {absent} (Addendum J10)")
    for k in CONTENT_KEYS:
        if frozen[k] != current[k]:
            raise HoldoutRefused(f"the freeze and the run differ in `{k}`: frozen {json.dumps(frozen[k], sort_keys=True)[:160]}, now {json.dumps(current[k], sort_keys=True)[:160]}")


def write_freeze(path, engines, repo=None, registration=None, inputs=None):
    """Write a freeze file for the engines and the inputs as they are now (the coordinator does this, once, after the development work is final).  `inputs` is required: see
    `compute_contents`."""
    if inputs is None:
        raise HoldoutRefused("a freeze names the store, prices, Damodaran files, priors, crosswalk, configuration, seeds and packages as well as the code (Addendum J10): no `inputs` given")
    entries = {}
    root = None
    for e in engines:
        ident, root = engine_identity(e, repo)
        entries[e.engine_name] = ident
    doc = {"engines": entries, "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "registration": registration,
           "contents": compute_contents(inputs, repo if repo else root)}
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


def enforce(dates, engines, freeze_path=None, repo=None, allow_rerun=False, record=True, inputs=None):
    """Refuse (HoldoutRefused) a run that touches the holdout unless `freeze_path` freezes every engine AND its contents (Addendum J10: `inputs` are the run's own, hashed here
    and compared with the freeze's `contents`; a holdout run that states none is refused).  Returns {"holdout_dates": [...], "windows": {date: window}, "frozen": {engine:
    commit}, "contents_verified": bool}.  Call this FIRST in a run, before any data is opened."""
    dates = [str(d)[:10] for d in dates]
    windows = {d: classify(d) for d in dates}
    touched = touches_holdout(dates)
    info = {"holdout_dates": touched, "windows": windows, "frozen": {}, "contents_verified": False}
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
    if inputs is None:
        raise HoldoutRefused("a holdout run must state its inputs (store, prices, Damodaran files, priors, crosswalk, configuration, seeds) so that they can be checked against the freeze: none given")
    first_files = next(iter(getattr(engines[0], "frozen_files", [])), None) if engines else None
    root = Path(repo).resolve() if repo else (repo_root(first_files) if first_files else None)
    verify_contents(doc.get("contents"), compute_contents(inputs, root))
    info["contents_verified"] = True
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
