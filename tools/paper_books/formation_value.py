"""formation_value.py - F10 (F_SPEC_valuation_menu sections 7-8): the menu valuation of every A0 book name of one formation, at seeds 1000 and
3000, through `python -m qwen_c.value.run` run from this repository's root, only after every Q1 analysis of the formation has finished.

    python tools/paper_books/formation_value.py 2026-11-30 [--limit N] [--ticker X]

Order of a pass:
1. The anchors are pinned first, even before Q1 has finished (it is a file copy, no GPU): <books>/m3o/value/anchors_<T>/ holds the MRI
   anchor files the cost of equity reads (ANCHOR_FILES) and manifest.json (sha256, built_at, asof, source). The copy is the newest MRI
   build - the live outputs or a dated copy under its archive/ - whose built_at is at or before the formation's decision time and whose
   asof is not after its date; none: STOP. Every later pass of the formation uses that copy (MRI_ANCHORS_DIR), rechecking each sha256 and
   refusing a copy whose asof is after T.
2. Without cache/paper_books/formation/finished_<T>.flag (formation_run.py writes it when no Q1 name is left) the pass exits 0: a
   valuation never takes a Q1 slot (m3o_engine.py:315,351).
3. Each map name with a packet that is not operator_excluded (in the map or in operator_excluded.json) gets its fields once: CIK (the
   packet's), sector and market cap (stocks.json at the map's output commit, through git), and the family (value_family.family on the
   SEC facts at the decision time). A slot whose field is missing is the named no_call field_missing, not a run.
4. Per slot, in ticker then seed order: yield to a contemporaneous formation with work left (exit 5); qwen_c.runner.gpu_preflight
   (busy or unreadable: exit 3); the tracked tree must be clean and at the commit of the formation's first valuation; a run directory left
   by a killed pass is moved aside (<dir>_aside<k>, recorded); then the valuation.
A slot is filled by a result the model or the code produced about the name (FILLS; a no_call for a reason of the name's own). A crash
(no result.json), an engine_defect, a result of another commit, packet, seed or T, or an environment no_call (ENV_NO_CALLS) is a code
defect: the run directory is moved aside, value_STOP_<T>.flag is written, and the pass stops (exit 7) until a human looks. A transport
outcome (timeout, infra_retry, infra_fatal) is moved aside and the pass stops (exit 6); its third failure writes the STOP flag.

The index <books>/m3o/value/formation_<T>.json records per slot: status, reason, result path, result sha256, seconds (tmp + replace
writes; resumable: a filled slot is never re-run). One instance at a time (value.lock beside formation_run's runner.lock).
value_finished_<T>.flag is written when every slot is filled.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402
import formation_run as FR  # noqa: E402
import paths  # noqa: E402

ROOT = HERE.parents[1]                                                    # the rs2-local repo root: qwen_c runs from here
PY = sys.executable
INPUTS = book_paths.books() / "m3o" / "inputs"
VALUE = book_paths.books() / "m3o" / "value"
STATE = ROOT / "cache" / "paper_books" / "formation"
LOCK = STATE / "value.lock"
RUNS = ROOT / "cache" / "m3q" / "runs"                                    # qwen_c.value.run.RUNS
SEEDS = (1000, 3000)
ANCHOR_FILES = ("cost_of_capital_anchor.json", "long_run_growth_anchor.json", "sector_multiple_bands.json")
FILLS = ("ok", "ok_with_reverts", "reply_invalid", "no_call", "malformed", "context_overflow")
ENV_NO_CALLS = ("coe_unavailable", "coe_anchor_after_T")
NEEDS_MARKET_CAP = ("operating", "commodity")
MAX_FAILS = 3
EXCLUDED = book_paths.operator_excluded()                                 # data in rs2-state, read once per pass (a pass is a process)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")
    for _ in range(20):                                                   # a reader can block a replace on Windows
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.5)
    os.replace(tmp, path)


def parse_t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------- anchors

def read_build(d):
    """{file: {sha256, built_at, asof}} of one anchor build directory holding every ANCHOR_FILES file with one built_at, else None."""
    man = {}
    for f in ANCHOR_FILES:
        p = Path(d) / f
        if not p.is_file():
            return None
        b = p.read_bytes()
        try:
            j = json.loads(b)
        except ValueError:
            return None
        man[f] = {"sha256": sha(b), "built_at": j.get("built_at"), "asof": j.get("asof")}
    if len({v["built_at"] for v in man.values()}) != 1 or not all(v["built_at"] and v["asof"] for v in man.values()):
        return None
    return man


def candidates():
    """The live anchor directory and every dated build under its archive/ (MRI copies each daily build there)."""
    live = paths.resolve("anchors_dir")
    return [live] + sorted(p for p in (live / "archive").glob("*/*") if p.is_dir())


def admissible(man, T):
    v = next(iter(man.values()))
    return parse_t(v["built_at"]) <= T and all(str(x["asof"])[:10] <= T.date().isoformat() for x in man.values())


def pin_anchors(formation_T, T):
    """(dir, manifest sha256) of the formation's pinned anchor copy; made from the newest admissible build at the first call."""
    dest = VALUE / f"anchors_{formation_T}"
    mpath = dest / "manifest.json"
    if mpath.is_file():
        rec = json.loads(mpath.read_text(encoding="utf-8"))
        if read_build(dest) != rec["files"]:
            sys.exit(f"STOP: the pinned anchor copy {dest.name} does not recompute to its manifest")
        for f, v in rec["files"].items():
            if str(v["asof"])[:10] > T.date().isoformat():
                sys.exit(f"STOP: pinned anchor {f} has asof {v['asof']}, after T {T.date()}")
        return dest, sha(mpath.read_bytes())
    best = None
    for d in candidates():
        man = read_build(d)
        if man and admissible(man, T) and (best is None or next(iter(man.values()))["built_at"] > next(iter(best[1].values()))["built_at"]):
            best = (d, man)
    if best is None:
        sys.exit(f"STOP: no MRI anchor build at or before {T.isoformat()} (live or archive)")
    src, man = best
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)                                                # a crashed copy of our own; never a pinned one
    tmp.mkdir(parents=True)
    for f in ANCHOR_FILES:
        shutil.copyfile(Path(src) / f, tmp / f)
    if read_build(tmp) != man:
        sys.exit(f"STOP: the anchor copy from {src} changed while it was copied")
    rec = {"files": man, "source": str(src), "decision_time_utc": T.isoformat().replace("+00:00", "Z"),
           "pinned_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    (tmp / "manifest.json").write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, dest)
    print(f"pinned anchors {dest.name} from {src} (built_at {next(iter(man.values()))['built_at']})", flush=True)
    return dest, sha(mpath.read_bytes())


# ---------------------------------------------------------------- per-name fields

def stocks_rows(commit):
    """{symbol: row} of stocks.json at the screener output commit (the dedicated clone's git objects)."""
    raw = subprocess.run(["git", "-C", str(book_paths.screener_repo()), "show", f"{commit}:public/data/stocks.json"],
                         capture_output=True, check=True).stdout
    d = json.loads(raw)
    rows = d if isinstance(d, list) else d.get("stocks", d)
    return {r["symbol"]: r for r in rows if isinstance(r, dict) and r.get("symbol")} if isinstance(rows, list) else rows


def name_family(cik, T):
    """value_family's record from the SEC facts at T (online: SEC standing approval; the valuation fetches the same documents)."""
    import value_family
    from qwen_c.value import facts
    cf, subs, _ = facts.fetch(cik, T, online=True)
    return value_family.family(cf, subs, facts.annual_facts(cf, subs, T), T)


def fields(n, stocks, T):
    pk = json.loads(Path(n["packet"]).read_text(encoding="utf-8"))
    cik, row = pk.get("cik"), stocks.get(pk["ticker"]) or {}
    fam = name_family(cik, T) if cik else {"family": None, "reason": "no CIK in the packet"}
    return {"packet": n["packet"], "packet_sha256": n.get("packet_sha256"), "formation_state": n.get("state"), "cik": cik,
            "sector": row.get("sector"), "market_cap": row.get("marketCap"), "family": fam.get("family"), "family_record": fam,
            "slots": {}, "failures": {}, "asides": []}


# ---------------------------------------------------------------- slots

def gpu_ok():
    """(ok, why): qwen_c.runner.gpu_preflight; RunRefused (gpu_busy, gpu_state_unreadable) is not ok, any other error is raised."""
    from qwen_c import runner
    try:
        runner.gpu_preflight(runner.llm_provider.OLLAMA_URL)
        return True, None
    except runner.RunRefused as e:
        return False, str(e)


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def aside(d):
    k = 1
    while d.with_name(f"{d.name}_aside{k}").exists():
        k += 1
    os.rename(d, d.with_name(f"{d.name}_aside{k}"))
    return f"{d.name}_aside{k}"


def run_dir(n, seed):
    src = Path(n["packet"]).read_bytes()
    pk = json.loads(src.decode("utf-8"))
    return RUNS / f"{pk['ticker']}_{re.sub(r'[^0-9TZ]', '', pk['decision_time_utc'])}_{sha(src)[:12]}_{seed}", pk


def judge(body, n, pk, seed, head):
    """(fill, why, defect). defect: a code-class failure (STOP)."""
    if not body:
        return False, "crash: no result.json", True
    status = body.get("status")
    if status == "engine_defect":
        return False, f"engine_defect: {str(((body.get('attempts') or [{}])[-1]).get('detail'))[:200]}", True
    if ((body.get("versions") or {}).get("git") or [None])[0] != head:
        return False, f"code state {(body.get('versions') or {}).get('git')} is not {head}", True
    if (body.get("packet_sha256"), body.get("ticker"), body.get("seed"), body.get("T")) != (
            n["packet_sha256"], pk["ticker"], seed, pk["decision_time_utc"]):
        return False, "result is not this slot's (packet, ticker, seed or T)", True
    own = body.get("reason") == "coe_unavailable" and str(body.get("detail")) == "missing ['loading']"   # the sector has no band
    if status == "no_call" and body.get("reason") in ENV_NO_CALLS and not own:
        return False, f"environment no_call {body.get('reason')}: {str(body.get('detail'))[:200]}", True
    if status not in FILLS:
        return False, f"status {status}", False
    return True, None, False


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    if not take_lock():
        print("another valuation pass holds the lock", flush=True)
        return 0
    try:
        return one_pass()
    finally:
        release_lock()


def one_pass():
    ap = argparse.ArgumentParser()
    ap.add_argument("formation_T")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
    a = ap.parse_args()
    stop = STATE / f"value_STOP_{a.formation_T}.flag"
    if stop.exists():
        print("value STOP flag present: a human must look:", stop.read_text(encoding="utf-8"), flush=True)
        return 7
    mpath = INPUTS / f"formation_{a.formation_T}.json"
    if not mpath.is_file():
        print(f"no map {mpath.name} yet: nothing to value", flush=True)
        return 0
    raw = mpath.read_bytes()
    m = json.loads(raw.decode("utf-8"))
    T = parse_t(m["decision_time_utc"])
    adir, asha = pin_anchors(a.formation_T, T)
    if not (STATE / f"finished_{a.formation_T}.flag").exists():
        print(f"Q1 of {a.formation_T} has not finished (no finished flag): waiting", flush=True)
        return 0
    ipath = VALUE / f"formation_{a.formation_T}.json"
    idx = json.loads(ipath.read_text(encoding="utf-8")) if ipath.exists() else {
        "formation_T": a.formation_T, "decision_time_utc": m["decision_time_utc"], "output_commit": m["output_commit"],
        "map": str(mpath), "map_sha256": sha(raw), "seeds": list(SEEDS), "git": None, "names": {}}
    if idx.get("anchors", {"manifest_sha256": asha})["manifest_sha256"] != asha:
        sys.exit("STOP: the pinned anchor manifest differs from the one the index was filled with")
    idx["anchors"] = {"dir": str(adir), "manifest_sha256": asha}
    todo = sorted(t for t, n in m["names"].items() if n.get("packet") and n.get("state") != "operator_excluded" and t not in EXCLUDED)
    stocks = None
    for t in todo:
        if t not in idx["names"]:
            stocks = stocks if stocks is not None else stocks_rows(m["output_commit"])
            try:
                idx["names"][t] = fields(m["names"][t], stocks, T)
            except Exception as e:  # noqa: BLE001  SEC unreachable or similar: nothing is recorded, the next pass measures again
                print(t, f"family not measured ({type(e).__name__}: {str(e)[:200]}): stopping", flush=True)
                return 6
            save(ipath, idx)
            print(t, "family", idx["names"][t]["family"], flush=True)
    env = dict(os.environ, MRI_ANCHORS_DIR=str(adir), PYTHONIOENCODING="utf-8")
    n_run = 0
    for t in todo:
        n = idx["names"][t]
        if a.ticker and t != a.ticker:
            continue
        for seed in SEEDS:
            k = str(seed)
            if k in n["slots"]:
                continue
            if a.limit is not None and n_run >= a.limit:
                return 0
            need = ["cik", "sector", "family"] + (["market_cap"] if n["family"] in NEEDS_MARKET_CAP else [])
            missing = [f for f in need if n.get(f) is None or n.get(f) == ""]
            if "market_cap" in need and "market_cap" not in missing and not n["market_cap"] > 0:
                missing.append("market_cap")                              # stocks.json writes 0 for a cap it could not measure
            if missing:
                n["slots"][k] = {"status": "no_call", "reason": "field_missing", "detail": missing, "result": None}
                save(ipath, idx)
                print(t, seed, "no_call field_missing", missing, flush=True)
                continue
            if FR.formation_waiting():
                print("a formation has Q1 work left: yielding the GPU", flush=True)
                return 5
            ok, why = gpu_ok()
            if not ok:
                print("GPU busy or unreadable: stopping;", why, flush=True)
                return 3
            if git("status", "--porcelain", "--untracked-files=no"):
                print("the rs2-local tree has uncommitted changes to tracked files: stopping", flush=True)
                return 6
            head = git("rev-parse", "HEAD")
            if idx["git"] not in (None, head):
                stop.write_text(f"the code moved from {idx['git']} to {head} inside formation {a.formation_T}", encoding="utf-8")
                print("STOP:", stop.read_text(encoding="utf-8"), flush=True)
                return 7
            rd, pk = run_dir(n, seed)
            if n["packet_sha256"] and sha(Path(n["packet"]).read_bytes()) != n["packet_sha256"]:
                sys.exit(f"STOP: {t} packet does not recompute")
            if rd.exists():
                n["asides"].append(aside(rd))
                save(ipath, idx)
            n_run += 1
            t0 = time.time()
            r = subprocess.run([PY, "-m", "qwen_c.value.run", n["packet"], "--cik", str(n["cik"]), "--sector", str(n["sector"]),
                                # the financial route reads no market value; run.py requires the argument
                                "--market-cap", str(n["market_cap"] if n["market_cap"] is not None else 0), "--family", str(n["family"]), "--seed", k],
                               cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            res = rd / "result.json"
            body = json.loads(res.read_text(encoding="utf-8")) if (r.returncode == 0 and res.exists()) else {}
            fill, fwhy, defect = judge(body, n, pk, seed, head)
            if not fill:
                n["failures"][k] = n["failures"].get(k, 0) + 1
                moved = aside(rd) if rd.exists() else None
                if moved:
                    n["asides"].append(moved)
                save(ipath, idx)
                print(t, seed, f"failure {n['failures'][k]}: {fwhy}; moved to {moved};", (r.stderr or r.stdout)[-300:], flush=True)
                if defect or n["failures"][k] >= MAX_FAILS:
                    stop.write_text(f"{t} seed {seed}: {fwhy} (failure {n['failures'][k]})", encoding="utf-8")
                    return 7
                return 6
            idx["git"] = head
            n["slots"][k] = {"status": body["status"], "reason": body.get("reason"), "result": str(res),
                             "result_sha256": sha(res.read_bytes()), "seconds": round(time.time() - t0, 1)}
            save(ipath, idx)
            print(t, seed, body["status"], body.get("reason") or "", n["slots"][k]["seconds"], flush=True)
    save(ipath, idx)
    if not a.ticker and a.limit is None and all(str(s) in idx["names"][t]["slots"] for t in todo for s in SEEDS):
        (STATE / f"value_finished_{a.formation_T}.flag").write_text("done")
    return 0


def take_lock():
    """formation_run's single-instance lock rule (pid_alive, never os.kill) on value.lock."""
    if LOCK.exists():
        try:
            if FR.pid_alive(int(LOCK.read_text().strip())):
                return False
        except ValueError:
            pass
    LOCK.write_text(str(os.getpid()))
    return True


def release_lock():
    try:
        if LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
