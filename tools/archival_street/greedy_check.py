"""greedy_check.py - the decoding check (REVIEW_fable52_qwen_value_2026-11-10 B8; operator go 2026-11-10): can one greedy valuation
(temperature 0, one call) stand in for the two-seed consensus (seeds at the Modelfile's temperature 0.6, qwen_c consensus v1)?

    python tools/archival_street/greedy_check.py run [--limit N]
    python tools/archival_street/greedy_check.py score

On the S1b set (<books>/m3o/value/archival_2025-10-01_pit: K2's packets, the point-in-time cost of equity pinned in coe_pinned/), on the
current prompt for every arm: N_NAMES names, chosen before any run by the lowest sha256 of the ticker among the S1b names with both S1b
seeds ok (no outcome is looked at). Per name three valuations: seeds 1100 and 3100 at the Modelfile's sampling (the consensus pair) and
seed 7000 at temperature 0 (greedy). Slots in greedy_slots.json beside the set; J2's runner rules: a clean tree, one commit, a stop on any
crash, engine_defect or unpinned cost of equity, cache/j2_yield.flag stops between slots.

score: per name, the greedy reply against the consensus of the pair: (1) the share of judged keys whose resolved option equals the
consensus option (the consensus keeps an option only when both seeds agree, so a key the seeds split on counts as matched when greedy
chose the record-neutral option), (2) the value of record within 1%, (3) the output tokens and seconds. A single sampled seed (1100)
against the same consensus is the baseline. Registered reading, written before any run: greedy replaces the pair if it matches the
consensus value of record within 1% on at least 90% of names AND matches it at least as often as the single sampled seed does.
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
for p in (str(ROOT / "tools" / "paper_books"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
import book_paths  # noqa: E402

DIR = book_paths.books() / "m3o" / "value" / "archival_2025-10-01_pit"
N_NAMES = 23
ARMS = ((7000, 0.0), (1100, None), (3100, None))       # (seed, temperature): None is the Modelfile's sampling
OUT = DIR / "greedy_slots.json"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def same_code(a, b):
    """True when commits a and b differ in nothing under qwen_c/ (the valuation code): a commit elsewhere does not change a valuation."""
    return bool(a and b) and (a == b or subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", a, b, "--", "qwen_c"]).returncode == 0)


def names():
    """The N_NAMES names: S1b names whose two S1b seeds are both ok, lowest sha256(ticker) first."""
    pool = {n["ticker"]: n for n in json.loads((DIR / "pool.json").read_text(encoding="utf-8"))["names"] if n.get("stage") is None}
    slots = json.loads((DIR / "slots.json").read_text(encoding="utf-8"))["slots"]
    ok = [t for t in pool if all(str((slots.get(f"{t}:{s}") or {}).get("status", "")).startswith("ok") for s in (1000, 3000))]
    return [pool[t] for t in sorted(ok, key=lambda t: sha(t.encode()))[:N_NAMES]]


def run(limit):
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("STOP: the rs2-local tree has uncommitted changes to tracked files")
    head = git("rev-parse", "HEAD")
    idx = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"git": head, "names": [n["ticker"] for n in names()], "slots": {}}
    if idx["git"] != head:                    # a later commit is accepted only if it changes nothing under qwen_c/ (the valuation code)
        if subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", idx["git"], head, "--", "qwen_c"]).returncode:
            sys.exit(f"STOP: the check began at {idx['git']}, the tree is at {head}, and qwen_c/ changed between them")
        idx.setdefault("git_changes", []).append({"from": idx["git"], "to": head})
        idx["git"] = head
    pk_all = json.loads((DIR / "runs.json").read_text(encoding="utf-8"))["packets"]
    pool = {n["ticker"]: n for n in json.loads((DIR / "pool.json").read_text(encoding="utf-8"))["names"]}
    env = dict(os.environ, RS2_ARCHIVAL_COE_DIR=str(DIR / "coe_pinned"), PYTHONIOENCODING="utf-8")
    did = 0
    for t in idx["names"]:
        n, pk = pool[t], pk_all[t]
        src = Path(pk["packet"]).read_bytes()
        if sha(src) != pk["packet_sha256"]:
            sys.exit(f"STOP: {t} packet does not recompute")
        for seed, temp in ARMS:
            key = f"{t}:{seed}"
            if key in idx["slots"]:
                continue
            if limit is not None and did >= limit:
                return 0
            if (ROOT / "cache" / "j2_yield.flag").exists():
                print("yield: cache/j2_yield.flag", flush=True)
                return 5
            cmd = [sys.executable, "-m", "qwen_c.value.run", pk["packet"], "--cik", n["cik"], "--sector", str(n["sector"]),
                   "--market-cap", str(n["market_cap"]), "--family", n["family"], "--seed", str(seed)]
            if temp is not None:
                cmd += ["--temperature", str(temp)]
            t0 = time.time()
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            T = json.loads(src.decode("utf-8"))["decision_time_utc"]
            rd = ROOT / "cache" / "m3q" / "runs" / f"{t}_{re.sub(r'[^0-9TZ]', '', T)}_{sha(src)[:12]}_{seed}"
            if temp is not None:
                rd = rd.with_name(f"{rd.name}_t{temp:g}")
            res = rd / "result.json"
            body = json.loads(res.read_text(encoding="utf-8")) if (r.returncode == 0 and res.exists()) else {}
            pinned = "coe_archival_pinned" in ((body.get("coe") or {}).get("stamps") or [])
            if (not body or body.get("status") == "engine_defect" or not same_code(idx["git"], (body.get("versions") or {}).get("git", [None])[0])
                    or (body.get("status") != "no_call" and not pinned) or body.get("temperature") != temp):
                print(t, seed, "STOP:", body.get("status") or "crash", (r.stderr or r.stdout)[-400:], flush=True)
                return 7
            did += 1
            idx["slots"][key] = {"status": body["status"], "temperature": temp, "result": str(res), "result_sha256": sha(res.read_bytes()),
                                 "seconds": round(time.time() - t0, 1)}
            OUT.write_text(json.dumps(idx, indent=1), encoding="utf-8")
            print(t, seed, temp, body["status"], idx["slots"][key]["seconds"], flush=True)
    return 0


def score():
    os.environ["RS2_ARCHIVAL_COE_DIR"] = str(DIR / "coe_pinned")
    from qwen_c.value import consensus, run as vrun, task
    idx = json.loads(OUT.read_text(encoding="utf-8"))
    pool = {n["ticker"]: n for n in json.loads((DIR / "pool.json").read_text(encoding="utf-8"))["names"]}
    pk_all = json.loads((DIR / "runs.json").read_text(encoding="utf-8"))["packets"]
    rows = {}
    for t in idx["names"]:
        res = {s: json.loads(Path(idx["slots"][f"{t}:{s}"]["result"]).read_text(encoding="utf-8"))
               for s, _ in ARMS if f"{t}:{s}" in idx["slots"]}
        if len(res) < 3:
            continue
        n = pool[t]
        packet = json.loads(Path(pk_all[t]["packet"]).read_text(encoding="utf-8"))
        f, b, bar, record, r, prov, fy_ends = vrun.prepare(packet, n["cik"], str(n["sector"]), n["market_cap"] or 0, online=False,
                                                           family=n["family"])
        ids = task.evidence_ids(packet, record, b, bar, r, prov)
        route = "financial" if n["family"] in vrun.FINANCIAL else "operating"
        ok = {str(s): v for s, v in res.items() if s != 7000 and str(v.get("status", "")).startswith("ok")}
        if not ok:
            rows[t] = {"status": "pair_no_call"}
            continue
        con = consensus.combine(ok, ids, b, bar, r, fy_ends, route)
        cv = (con.get("values") or {}).get("base")
        row = {"consensus": cv}
        for s in (7000, 1100):
            v = res[s]
            ok1 = str(v.get("status", "")).startswith("ok")         # one run's own checked value of record (combine needs two seeds)
            ov = (v.get("values") or {}).get("base") if ok1 else None
            oo, co = ((v.get("checks") or {}).get("options") or {}) if ok1 else {}, (con.get("options") or {})
            keys = sorted(set(oo) | set(co))
            raw = [a for a in v.get("attempts", [])]
            row[str(s)] = {"value": ov, "within_1pct": (cv is not None and ov is not None and abs(ov / cv - 1) <= 0.01),
                           "keys_matched": sum(1 for k in keys if oo.get(k) == co.get(k)), "keys": len(keys),
                           "seconds": idx["slots"][f"{t}:{s}"]["seconds"], "attempts": len(raw), "status": v.get("status")}
        rows[t] = row
    summary = {}
    for s in ("7000", "1100"):
        rr = [x[s] for x in rows.values() if s in x]
        summary[s] = {"names": len(rr), "within_1pct": sum(1 for x in rr if x["within_1pct"]),
                      "keys_matched": sum(x["keys_matched"] for x in rr), "keys": sum(x["keys"] for x in rr),
                      "seconds": round(sum(x["seconds"] for x in rr), 1), "repair_turns": sum(1 for x in rr if x["attempts"] > 1)}
    out = {"git": idx["git"], "summary": summary, "names": rows}
    OUT.with_name("greedy_score.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("run", "score"))
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    return run(a.limit) if a.phase == "run" else score()


if __name__ == "__main__":
    sys.exit(main())
