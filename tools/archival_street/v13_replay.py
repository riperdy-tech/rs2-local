"""v13_replay.py - the prompt v13 replay (SPEC_prompt_v13, check 2; PREREG_cohorts_nextq 7.6): does v13 read guidance no worse than v12?

    python tools/archival_street/v13_replay.py run [--limit N]

On the S1b set (<books>/m3o/value/archival_2025-10-01_pit: K2's packets, the cost of equity pinned in coe_pinned/): one valuation per
routed name at seed 1300 under the current prompt (v13), slots in v13_slots.json beside the set. The v12 side is S1b's own seed-1000
slot (prompt v12). The runner rules are the greedy check's: a clean tree, one valuation code commit, a stop on any crash,
engine_defect or unpinned cost of equity; cache/j2_yield.flag stops between slots.

Registered reading (SPEC_prompt_v13, written before any run; scored separately):
(1) the share of year-1 guidance picks that code reverts as unreadable is not above v12's;
(2) on names where both v12 and v13 read year-1 guidance, the median |ln((1 + G) / (1 + realised year-1 growth))| under v13 is not
    above v12's.
v13 passes when both hold.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from greedy_check import DIR, ROOT, git, same_code, sha

SEED = 1300
OUT = DIR / "v13_slots.json"
ROUTED = ("operating", "commodity")


def names():
    """Every routed S1b name, in sha256(ticker) order."""
    pool = [n for n in json.loads((DIR / "pool.json").read_text(encoding="utf-8"))["names"]
            if n.get("stage") is None and n.get("family") in ROUTED]
    return sorted((n["ticker"] for n in pool), key=lambda t: sha(t.encode()))


def run(limit):
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("STOP: the rs2-local tree has uncommitted changes to tracked files")
    head = git("rev-parse", "HEAD")
    idx = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"git": head, "names": names(), "slots": {}}
    if not same_code(idx["git"], head):
        sys.exit(f"STOP: the replay began at {idx['git']}, the tree is at {head}, and qwen_c/ changed between them")
    pk_all = json.loads((DIR / "runs.json").read_text(encoding="utf-8"))["packets"]
    pool = {n["ticker"]: n for n in json.loads((DIR / "pool.json").read_text(encoding="utf-8"))["names"]}
    env = dict(os.environ, RS2_ARCHIVAL_COE_DIR=str(DIR / "coe_pinned"), PYTHONIOENCODING="utf-8")
    did = 0
    for t in idx["names"]:
        key = f"{t}:{SEED}"
        if key in idx["slots"]:
            continue
        if limit is not None and did >= limit:
            return 0
        if (ROOT / "cache" / "j2_yield.flag").exists():
            print("yield: cache/j2_yield.flag", flush=True)
            return 5
        n, pk = pool[t], pk_all[t]
        if not pk.get("packet"):
            continue                                # no packet, so S1b has no slot either (j2_run skips it the same way)
        src = Path(pk["packet"]).read_bytes()
        if sha(src) != pk["packet_sha256"]:
            sys.exit(f"STOP: {t} packet does not recompute")
        cmd = [sys.executable, "-m", "qwen_c.value.run", pk["packet"], "--cik", n["cik"], "--sector", str(n["sector"]),
               "--market-cap", str(n["market_cap"]), "--family", n["family"], "--seed", str(SEED), "--offline"]
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        T = json.loads(src.decode("utf-8"))["decision_time_utc"]
        res = ROOT / "cache" / "m3q" / "runs" / f"{t}_{re.sub(r'[^0-9TZ]', '', T)}_{sha(src)[:12]}_{SEED}" / "result.json"
        body = json.loads(res.read_text(encoding="utf-8")) if (r.returncode == 0 and res.exists()) else {}
        pinned = "coe_archival_pinned" in ((body.get("coe") or {}).get("stamps") or [])
        v = body.get("versions") or {}
        if (not body or body.get("status") == "engine_defect" or not same_code(idx["git"], (v.get("git") or [None])[0])
                or (body.get("status") != "no_call" and (not pinned or v.get("prompt") != "m3q.prompt.v13"))):
            print(t, "STOP:", body.get("status") or "crash", (r.stderr or r.stdout)[-400:], flush=True)
            return 7
        did += 1
        idx["slots"][key] = {"status": body["status"], "result": str(res), "result_sha256": sha(res.read_bytes()),
                             "seconds": round(time.time() - t0, 1)}
        OUT.write_text(json.dumps(idx, indent=1), encoding="utf-8")
        print(t, SEED, body["status"], idx["slots"][key]["seconds"], flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("phase", choices=("run",))
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    return run(a.limit)


if __name__ == "__main__":
    sys.exit(main())
