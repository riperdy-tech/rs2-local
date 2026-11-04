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
  coe_archival_pinned stamp stops the pass (exit 7), so a code defect never fills a slot. GPU: run only inside a window agreed with the
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


def run(pool, idx, limit, ticker):
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("STOP: the rs2-local tree has uncommitted changes to tracked files")
    head = git("rev-parse", "HEAD")
    if idx.get("git") not in (None, head):
        sys.exit(f"STOP: the index was filled at {idx['git']}, the tree is at {head}")
    idx["git"] = head
    env = dict(os.environ, RS2_ARCHIVAL_COE_DIR=str(DIR / "coe_pinned"), PYTHONIOENCODING="utf-8")
    runs, n_run = ROOT / "cache" / "m3q" / "runs", 0
    for n in pool["pool"]:
        t, pk = n["ticker"], idx["packets"].get(n["ticker"]) or {}
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
            if limit is not None and n_run >= limit:
                save(DIR / "runs.json", idx)
                return 0
            if (ROOT / "cache" / "j2_yield.flag").exists():                 # another session asked for the GPU: stop between slots
                save(DIR / "runs.json", idx)
                print("yield: cache/j2_yield.flag", flush=True)
                return 5
            rd = runs / f"{t}_{re.sub(r'[^0-9TZ]', '', T)}_{sha(src)[:12]}_{seed}"
            if rd.exists():
                k = 1
                while rd.with_name(f"{rd.name}_aside{k}").exists():
                    k += 1
                os.rename(rd, rd.with_name(f"{rd.name}_aside{k}"))
            n_run += 1
            t0 = time.time()
            r = subprocess.run([sys.executable, "-m", "qwen_c.value.run", pk["packet"], "--cik", n["cik"], "--sector", str(n["sector"]),
                                "--market-cap", str(n["market_cap"]), "--family", n["family"], "--seed", str(seed)],
                               cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            res = rd / "result.json"
            body = json.loads(res.read_text(encoding="utf-8")) if (r.returncode == 0 and res.exists()) else {}
            pinned = "coe_archival_pinned" in ((body.get("coe") or {}).get("stamps") or [])
            if (not body or body.get("status") == "engine_defect" or (body.get("versions") or {}).get("git", [None])[0] != head
                    or (body.get("status") != "no_call" and not pinned)):
                save(DIR / "runs.json", idx)
                print(t, seed, "STOP:", body.get("status") or "crash", "pinned" if pinned else "not pinned", (r.stderr or r.stdout)[-400:],
                      flush=True)
                return 7
            idx["slots"][key] = {"status": body["status"], "reason": body.get("reason"), "result": str(res),
                                 "result_sha256": sha(res.read_bytes()), "seconds": round(time.time() - t0, 1)}
            save(DIR / "runs.json", idx)
            print(t, seed, body["status"], body.get("reason") or "", idx["slots"][key]["seconds"], flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("packets", "run"))
    ap.add_argument("--screener-repo")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ticker")
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
    return run(pool, idx, a.limit, a.ticker)


if __name__ == "__main__":
    sys.exit(main())
