"""j2_run.py - J2-5 (J2_SPEC_forecast_test_v02.md): the archival packets and valuations of the census pool at T 2025-12-31.

    python tools/archival_j2/j2_run.py packets --screener-repo <stock-screener development checkout>
    python tools/archival_j2/j2_run.py run [--limit N] [--ticker X]

Pool: <books>/m3o/value/archival_2025-12-31/pool.json (pool.py). Index: runs.json beside it (tmp + replace, resumable: a filled slot is
never redone).
- packets: one archival_sec_acceptance_v1 packet per pool name on the pool's frame commit, online (SEC, standing approval). A refusal is
  recorded with its reason and that name gets no valuation.
- run: `python -m qwen_c.value.run` per packet at seeds 1000 and 3000, from the repository root, with RS2_ARCHIVAL_COE_DIR set to the
  pinned set coe_pinned/ (operator ruling 2026-11-04; checked against its manifest by coe.py on every call). The tracked tree must be
  clean and every result must carry the commit of the first valuation. A crash, an engine_defect or a result without the
  coe_archival_pinned stamp stops the pass (exit 7), so a code defect never fills a slot. A fix commit after such a stop continues the
  index only through `--continue-from <the index's commit>`, which must be an ancestor of HEAD; the change is appended to the index's
  git_changes, and every slot keeps the commit of its own result. GPU: run only inside a window agreed with the
  "F03 benchmark workflows" session (STATE section 9). Creating cache/j2_yield.flag stops the pass at the next slot (exit 5).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools" / "paper_books"))
import book_paths  # noqa: E402

DIR = book_paths.books() / "m3o" / "value" / "archival_2025-12-31"
SEEDS = (1000, 3000)
REGIME = "archival_sec_acceptance_v1"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def save(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def packets(pool, idx, screener_repo):
    for n in pool["pool"]:
        t = n["ticker"]
        if t in idx["packets"]:
            continue
        r = subprocess.run([sys.executable, "-m", "qwen_c.packet", "--ticker", t, "--T", pool["T"], "--commit", pool["frame"]["commit"],
                            "--regime", REGIME, "--screener-repo", screener_repo, "--cik", n["cik"], "--online"],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            out = json.loads(r.stdout[r.stdout.index("{"):])
            idx["packets"][t] = {"packet": out["packet"], "packet_sha256": out["packet_sha256"], "annotations": out.get("annotations")}
        except (ValueError, KeyError):
            idx["packets"][t] = {"packet": None, "refused": (r.stderr or r.stdout)[-600:]}
        save(DIR / "runs.json", idx)
        print(t, "packet" if idx["packets"][t]["packet"] else "refused", flush=True)
    return 0


def run(pool, limit, ticker, cont=None):
    """The valuations, in rounds: each round re-reads the packets (packets() may still be writing runs.json) and fills slots.json; it
    ends when every pool name has a packet entry and no slot is left."""
    path = DIR / "slots.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"slots": {}, "git": None}
    n_run = 0
    while True:
        pk_all = json.loads((DIR / "runs.json").read_text(encoding="utf-8"))["packets"]
        rc, did = _round(pool, idx, pk_all, limit, ticker, n_run, cont)
        if rc is not None:
            return rc
        n_run += did
        if not did:
            if all(n["ticker"] in pk_all for n in pool["pool"]):
                return 0
            time.sleep(120)


def _round(pool, idx, pk_all, limit, ticker, n_run, cont=None):
    """(exit code or None, slots run this round)."""
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("STOP: the rs2-local tree has uncommitted changes to tracked files")
    head = git("rev-parse", "HEAD")
    if idx.get("git") not in (None, head):
        if cont != idx["git"] or subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", cont, head]).returncode:
            sys.exit(f"STOP: the index was filled at {idx['git']}, the tree is at {head} (--continue-from {idx['git']} after a fix)")
        idx.setdefault("git_changes", []).append({"from": idx["git"], "to": head, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    idx["git"] = head
    env = dict(os.environ, RS2_ARCHIVAL_COE_DIR=str(DIR / "coe_pinned"), PYTHONIOENCODING="utf-8")
    runs, did = ROOT / "cache" / "m3q" / "runs", 0
    for n in pool["pool"]:
        t, pk = n["ticker"], pk_all.get(n["ticker"]) or {}
        if not pk.get("packet") or (ticker and t != ticker):
            continue
        src = Path(pk["packet"]).read_bytes()
        if sha(src) != pk["packet_sha256"]:
            sys.exit(f"STOP: {t} packet does not recompute")
        T = json.loads(src.decode("utf-8"))["decision_time_utc"]
        for seed in SEEDS:
            key = f"{t}:{seed}"
            if key in idx["slots"]:
                continue
            if limit is not None and n_run + did >= limit:
                save(DIR / "slots.json", idx)
                return 0, did
            if (ROOT / "cache" / "j2_yield.flag").exists():                 # another session asked for the GPU: stop between slots
                save(DIR / "slots.json", idx)
                print("yield: cache/j2_yield.flag", flush=True)
                return 5, did
            rd = runs / f"{t}_{re.sub(r'[^0-9TZ]', '', T)}_{sha(src)[:12]}_{seed}"
            if rd.exists():
                k = 1
                while rd.with_name(f"{rd.name}_aside{k}").exists():
                    k += 1
                os.rename(rd, rd.with_name(f"{rd.name}_aside{k}"))
            did += 1
            t0 = time.time()
            r = subprocess.run([sys.executable, "-m", "qwen_c.value.run", pk["packet"], "--cik", n["cik"], "--sector", str(n["sector"]),
                                "--market-cap", str(n["market_cap"]), "--family", n["family"], "--seed", str(seed)],
                               cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            res = rd / "result.json"
            body = json.loads(res.read_text(encoding="utf-8")) if (r.returncode == 0 and res.exists()) else {}
            pinned = "coe_archival_pinned" in ((body.get("coe") or {}).get("stamps") or [])
            if (not body or body.get("status") == "engine_defect" or (body.get("versions") or {}).get("git", [None])[0] != head
                    or (body.get("status") != "no_call" and not pinned)):
                save(DIR / "slots.json", idx)
                print(t, seed, "STOP:", body.get("status") or "crash", "pinned" if pinned else "not pinned", (r.stderr or r.stdout)[-400:],
                      flush=True)
                return 7, did
            idx["slots"][key] = {"status": body["status"], "reason": body.get("reason"), "result": str(res),
                                 "result_sha256": sha(res.read_bytes()), "seconds": round(time.time() - t0, 1), "git": head}
            save(DIR / "slots.json", idx)
            print(t, seed, body["status"], body.get("reason") or "", idx["slots"][key]["seconds"], flush=True)
    return None, did


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("packets", "run"))
    ap.add_argument("--screener-repo")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
    ap.add_argument("--continue-from", help="the index's commit, when a fix commit follows a stop")
    a = ap.parse_args()
    pool = json.loads((DIR / "pool.json").read_text(encoding="utf-8"))
    path = DIR / "runs.json"
    idx = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"pool_sha256": sha((DIR / "pool.json").read_bytes()),
                                                                              "packets": {}, "slots": {}, "git": None}
    if idx["pool_sha256"] != sha((DIR / "pool.json").read_bytes()):
        sys.exit("STOP: pool.json changed since the index began")
    if a.phase == "packets":
        if not a.screener_repo:
            sys.exit("packets needs --screener-repo")
        return packets(pool, idx, a.screener_repo)
    return run(pool, a.limit, a.ticker, a.continue_from)


if __name__ == "__main__":
    sys.exit(main())
