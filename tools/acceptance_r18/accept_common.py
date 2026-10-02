"""Revision 18 acceptance scripts (brief section 6, amendments 1 and 2): what every AT script shares.

THE SCRIPTS (SP\\rev18\\accept\\; each is socket-blocked, offline, CPU only; none loads a model; none writes into a live data root):

  build_day.py          builds the day's record for a name list: the pack, the reference exactly as `build` returned it, the independent
                        `reference_inputs` call, the cash-term state and the hash of every input (the one stated day of amendment 2, point 4)
  at1a_desk_parity.py   AT1a  desk = reference to the cent on default inputs (unrounded, amendment 1 point 3)
  at1b_reduction.py     AT1b  revision 18's `build` with the reduction switches reproduces revision 16's value to the cent
  at1c_tested_design.py AT1c  production's engine = the backtest candidate's V_S to the cent on 200 paired name-dates (seed 20261002)
  at1d_single_source.py AT1d  the pack's printed reference = build(**reference_inputs(...)) to the cent
  at1e_round_trip.py    AT1e  the reverse DCF's two round trips, with the cash term (amendment 2 point 3)
  at2_closure.py        AT2   the closure artifact, and brief A's marker for every aggregate name (amendment 2 point 1)
  at3_coverage.py       AT3   coverage against revision 16 on the same day and data
  at4_no_nonpositive.py AT4   no reference at or below zero is printed
  at5_level_sanity.py   AT5   the median V/P and the share of gross errors
  at6_fence_cap_text.py AT6   fence, cap, text, PACK_REVISION and FACTS_VERSION
  at7_suite.py          AT7   the full suite, and the backtest harness tests at their pinned commits (foreground)
  at9_cash_alive.py     AT9   the cash term applies to at least 90% of the names that hold a cash figure
  at8_untouched_look.py AT8   the ONE look at the 167 untouched names (counts only; guarded to run once, on one configuration)
  test_accept_scripts.py proves every script on synthetic data or tiny fixtures (pytest); it never runs AT8's look
  desk_checks.py        the desk-side arithmetic AT1a and AT1e share

Every script prints PASS / FAIL lines and writes one JSON result; `--out` names it and an existing file is never overwritten.
Names of the untouched list are never printed, logged, written or put in an error message: AT8 and the 167 code paths carry counts.
"""
import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ACCEPT = Path(__file__).resolve().parent


def default_tree():
    """The rs2 tree these scripts belong to: $RS2_TREE, else the repository holding this file (tools/acceptance_r18/), else the sibling
    worktree `rs2-r18` of the scratchpad folder SP/rev18/accept/ lives in."""
    env = os.environ.get("RS2_TREE")
    if env:
        return Path(env)
    for cand in (ACCEPT.parents[1], ACCEPT.parents[1] / "rs2-r18"):
        if (cand / "tools" / "consensus_reference.py").exists():
            return cand
    return None


# ---- offline -----------------------------------------------------------------------------------------------------------------

def block_network():
    """Every socket, name resolution and git network verb is refused for the rest of the process."""
    class _Blocked(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("Socket access blocked: the acceptance scripts are offline")

        def connect(self, *a, **k):
            raise RuntimeError("Socket access blocked: the acceptance scripts are offline")

    def _no(*a, **k):
        raise RuntimeError("Network name resolution blocked: the acceptance scripts are offline")
    socket.socket = _Blocked
    socket.getaddrinfo = _no
    socket.create_connection = _no
    net = {"fetch", "pull", "push", "clone", "ls-remote", "remote", "submodule"}
    orig = subprocess.Popen.__init__

    def guarded(self, cmd, *a, **k):
        parts = [str(x) for x in (cmd if isinstance(cmd, (list, tuple)) else str(cmd).split())]
        if parts and os.path.basename(parts[0]).lower() in ("git", "git.exe") and net & set(parts):
            raise RuntimeError(f"git network operation refused: {parts}")
        return orig(self, cmd, *a, **k)
    subprocess.Popen.__init__ = guarded


def network_is_blocked():
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except RuntimeError:
        return True
    except OSError:
        return False
    return False


# ---- hashes, files, results --------------------------------------------------------------------------------------------------

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def git_head(tree):
    """(commit sha, tree is clean) of a git working tree; (None, None) when it is not one."""
    try:
        sha = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(tree), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True,
                               check=True).stdout.strip()
        return sha, dirty == ""
    except Exception:
        return None, None


def load_names(path, expect_sha256=None):
    """The names in a list file (one per line, '#' lines and blanks ignored), upper case, order kept, duplicates dropped. Refuses, naming
    no ticker, a file whose sha256 differs from `expect_sha256` (a prefix of at least 8 characters is enough)."""
    raw = Path(path).read_bytes()
    if expect_sha256 is not None:
        want = str(expect_sha256).strip().lower()
        if len(want) < 8 or not hashlib.sha256(raw).hexdigest().startswith(want):
            raise ValueError("the name list's sha256 differs from the expected value; it is not used")
    seen, out = set(), []
    for ln in raw.decode("utf-8-sig").splitlines():
        s = ln.strip().upper()
        if s and not s.startswith("#") and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def write_result(path, doc):
    """Write the result JSON; an existing file is never overwritten (a result is a record). Returns the path (None when `path` is None)."""
    if path is None:
        return None
    with open(path, "x", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=1, default=str, allow_nan=False))
    return Path(path)


def jsonable(o):
    """JSON-safe copy: +-inf and nan become strings ("inf", "-inf", "nan")."""
    import math
    if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
        return str(o)
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    return o


def unjson(x):
    if x == "inf":
        return float("inf")
    if x == "-inf":
        return float("-inf")
    return x


def report(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)


def finish(result, out):
    """Print the verdict, write the JSON, and return the process exit code (0 pass, 1 fail)."""
    write_result(out, result)
    report(result["at"], result["pass"], result["summary"])
    return 0 if result["pass"] else 1


# ---- the tree under test --------------------------------------------------------------------------------------------------------

def add_tree_paths(tree):
    tree = Path(tree).resolve()
    for p in (str(tree / "tools" / "audit_202608"), str(tree / "tools"), str(tree)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return tree


def bootstrap(tree, sd, mri, root, date, closure=None, stub_world=True):
    """Pin one acceptance day and import the tree's modules under it (the guards of wb_p3.py):

      SCREENER_DATA_DIR / MRI_OUTPUTS_DIR / MRI_ANCHORS_DIR are set before any module imports and the resolved values are checked;
      sockets are blocked; company news, the SEC release and the world-news digest are stubbed; the clock is frozen at `date` 12:00;
      the MRI duckdb store is never opened (`_mri_query` refused; the one MRI read is the cash term's bill rate, a read-only parquet);
      capability_test.HERE and valuation_backbone.HERE are `root` (enrich/, cache/, research/ - one root for the estimates and the fence);
      `closure` (a path) is the closure artifact read through the production accessor (default: the tree's cache/reference_closure.json).

    Returns a namespace of the modules and the frozen date. Call it once per process."""
    block_network()
    sys.dont_write_bytecode = True
    tree, root, sd, mri = (Path(p).resolve() for p in (tree, root, sd, mri))
    os.environ["SCREENER_DATA_DIR"] = str(sd)
    os.environ["MRI_OUTPUTS_DIR"] = str(mri)
    os.environ["MRI_ANCHORS_DIR"] = str(mri)
    os.environ.setdefault("STOCKS_ROOT", str(Path.home() / "stocks"))
    add_tree_paths(tree)
    import capability_test as cap
    import common
    import consensus_reference as cref
    import financial_model_tool as fmt
    import pack_facts
    import rs2_data
    import valuation_backbone as vb
    assert tree in Path(cap.__file__).resolve().parents, cap.__file__
    cfg = rs2_data.CONFIG
    resolved = {"screener_data_dir": str(Path(cfg["screener_data_dir"]).resolve()), "mri_outputs_dir": str(Path(cfg["mri_outputs_dir"]).resolve()),
                "anchors_dir": str(Path(cfg.get("anchors_dir") or cfg["mri_outputs_dir"]).resolve())}
    assert resolved == {"screener_data_dir": str(sd), "mri_outputs_dir": str(mri), "anchors_dir": str(mri)}, resolved
    assert Path(cap.SD).resolve() == sd and Path(common.SD).resolve() == sd and Path(vb.SD).resolve() == sd
    y, m, d = (int(x) for x in str(date).split("-"))
    fixed = datetime(y, m, d, 12, 0, 0)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed
    for mod in (cap, rs2_data, vb):
        mod.datetime = Frozen
    try:
        import catalyst_research
        catalyst_research.datetime = Frozen
    except ImportError:
        pass
    common.enable_json_cache()
    if stub_world:
        cap.company_news.fetch = lambda company, t: {"date": str(date), "rows": [], "unresponsive_engines": [], "errors": ["stubbed: acceptance"]}
        cap.sec_guidance.latest_earnings_release = lambda *a, **k: None
        cap.world_news.digest = lambda *a, **k: None

    def _no_store(*a, **k):
        raise RuntimeError("MRI duckdb store query refused (a live build reads the anchor JSON files only)")
    rs2_data._mri_query = _no_store
    cap.HERE = root
    vb.HERE = root
    if closure is not None and hasattr(rs2_data, "reference_closure"):
        real = rs2_data.reference_closure
        rs2_data.reference_closure = lambda path=None: real(closure)
    return SimpleNamespace(cap=cap, common=common, cref=cref, fmt=fmt, pack_facts=pack_facts, rs2=rs2_data, vb=vb, tree=tree, root=root,
                           sd=sd, mri=mri, date=str(date), fixed=fixed, resolved=resolved, closure=closure)


def constants(ns):
    """The tree's PACK_REVISION, FACTS_VERSION, ANCHOR_ROLE and TASK (AT6 reads them from the day file)."""
    return {"PACK_REVISION": getattr(ns.cap, "PACK_REVISION", None), "FACTS_VERSION": getattr(ns.pack_facts, "FACTS_VERSION", None),
            "ANCHOR_ROLE": getattr(ns.cref, "ANCHOR_ROLE", None), "TASK": getattr(ns.cap, "TASK", None)}


def bootstrap_from_day(meta):
    """Re-create the day a build_day file was built on (the same tree, data directories, date and closure artifact)."""
    inp = meta["inputs"]
    res = inp["resolved_dirs"]
    return bootstrap(inp["tree"], res["screener_data_dir"], res["mri_outputs_dir"], inp["root"], inp["date"],
                     closure=inp["closure_artifact"] if inp.get("closure_sha256") else None)


def load_day(path):
    """(meta, rows) of a build_day file, +-inf strings turned back into floats where a number is expected (the reference's record_R_tc)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in doc["rows"].values():
        ref = r.get("reference")
        if isinstance(ref, dict):
            ref["record_R_tc"] = unjson(ref.get("record_R_tc"))
    return doc["meta"], doc["rows"]


def inputs_record(ns, extra_files=()):
    """The hashes the day is stated by (amendment 2, point 4): the final commit of the tree, the history and TTM files, the closure
    artifact, every MRI anchor file as resolved that day."""
    commit, clean = git_head(ns.tree)
    art = Path(ns.closure) if ns.closure else Path(ns.tree) / "cache" / "reference_closure.json"
    anchors = {}
    ad = Path(ns.rs2.anchors_dir())
    for p in sorted(ad.glob("*anchor*.json")):
        anchors[p.name] = sha256_file(p)
    rec = {"tree": str(ns.tree), "root": str(ns.root), "tree_commit": commit, "tree_clean": clean, "date": ns.date,
           "pack_revision": getattr(ns.cap, "PACK_REVISION", None),
           "history_sha256": sha256_file(Path(ns.sd) / "fundamentals_history.json"),
           "ttm_sha256": sha256_file(Path(ns.sd) / "fundamentals_ttm.json") if (Path(ns.sd) / "fundamentals_ttm.json").exists() else None,
           "closure_artifact": str(art), "closure_sha256": sha256_file(art) if art.exists() else None,
           "mri_anchors_dir": str(ad), "mri_anchor_sha256": anchors, "resolved_dirs": ns.resolved}
    for f in extra_files:
        rec.setdefault("extra", {})[str(f)] = sha256_file(f)
    return rec
