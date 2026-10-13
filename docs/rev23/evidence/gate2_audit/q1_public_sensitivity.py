"""Audit finding (AK.34): a q1 quarter whose results were public in Muse's pack before T.  G1 re-computed without those rows, as a SENSITIVITY (not a
registered bar; which reading governs is the operator's).  Writes only under OUT.

    python q1_public_sensitivity.py OUTCOMES.jsonl OUT_DIR [--draws N]
  S1: q1 removed where an 8-K filed after the q1 quarter ended is in the pack (its earnings release was public and shown to Muse)
  S2: q1 removed where the q1 quarter had already ended at T (the strictest reading: only quarters ending after T are forecasts)
"""
import json
import sys
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
from rebuild_harness.gate2 import scoring  # noqa: E402

STATE = Path(r"C:\Users\riper\stocks\stocks-workspace\data\gate2_run2")


def manifest_entries(run_dir):
    man = json.loads((STATE / run_dir / "pack.json").read_text(encoding="utf-8")).get("manifest", {})
    out = []

    def walk(x):
        if isinstance(x, dict):
            if "form" in x and "filed" in x:
                out.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(man)
    return out


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    draws = int(sys.argv[sys.argv.index("--draws") + 1]) if "--draws" in sys.argv else None
    out.mkdir(parents=True, exist_ok=True)
    prog = {}
    for line in (STATE / "progress.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        prog[r["key"]] = r
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines()]
    flags = {}
    for o in rows:
        q1 = (o.get("quarters") or {}).get("q1")
        if not q1 or not q1.get("period_end"):
            continue
        T = o["key"][:10]
        pe = str(q1["period_end"])[:10]
        public = any(str(e.get("form", "")).startswith("8-K") and str(e["filed"])[:10] > pe for e in manifest_entries(prog[o["key"]]["run_dir"]))
        flags[o["key"]] = {"public_in_pack": public, "ended_before_T": pe < T}
    res = {"source": str(src), "n_q1": len(flags), "s1_removed": sum(f["public_in_pack"] for f in flags.values()),
           "s2_removed": sum(f["ended_before_T"] for f in flags.values())}
    for name, rule in (("S1", "public_in_pack"), ("S2", "ended_before_T")):
        p = out / f"outcomes_{name}.jsonl"
        with open(p, "w", encoding="utf-8") as fh:
            for o in rows:
                o2 = json.loads(json.dumps(o))
                if flags.get(o["key"], {}).get(rule):
                    o2["quarters"]["q1"] = None
                fh.write(json.dumps(o2) + "\n")
        rep = scoring.score(STATE, p, reproduced=json.loads((Path(__file__).parent / "reproduced_refusals.json").read_text(encoding="utf-8")), **({"draws": draws} if draws else {}))
        res[name] = {k: rep.get(k) for k in ("verdict", "G1")} if isinstance(rep, dict) else str(rep)
        (out / f"score_{name}.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    (out / "flags.json").write_text(json.dumps(flags, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
