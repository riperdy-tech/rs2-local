"""formation_consensus.py - design revision 2, rule (a): the value of record of every name of one valued formation, from its two seeds.

    python tools/paper_books/formation_consensus.py 2026-10-30

Reads <books>/m3o/value/formation_<T>.json (formation_value.py's index), and for each name whose slots hold a checked result
(ok or ok_with_reverts) combines the seeds through qwen_c.value.consensus (no model call; the desk is prepared offline from the SEC
documents the valuation stored, with the formation's pinned anchors and closure). Writes <books>/m3o/value/consensus_<T>.json:
per name the status, values, annotations (seeds_disagree, one_seed_only, held_at_record, reverts), options and the seeds read; a
name with no checked seed keeps its seeds' no_call reason. Rerunnable; the file is rewritten whole.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import book_paths  # noqa: E402

ROOT = HERE.parents[1]
VALUE = book_paths.books() / "m3o" / "value"


def main(formation_T):
    idx = json.loads((VALUE / f"formation_{formation_T}.json").read_text(encoding="utf-8"))
    os.environ["MRI_ANCHORS_DIR"] = idx["anchors"]["dir"]
    os.environ["RS2_REFERENCE_CLOSURE"] = idx["closure"]["path"]
    sys.path.insert(0, str(ROOT))
    from qwen_c.value import consensus, run, task
    out = {"formation_T": formation_T, "version": consensus.CONSENSUS_VERSION, "index_git": idx["git"],
           "git": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "names": {}}
    for t, n in sorted(idx["names"].items()):
        results = {k: json.loads(Path(s["result"]).read_text(encoding="utf-8")) for k, s in n["slots"].items() if s.get("result")}
        ok = {k: v for k, v in results.items() if str(v.get("status", "")).startswith("ok")}
        if not ok:
            reasons = sorted({f"{s.get('status')}:{s.get('reason')}" for s in n["slots"].values()})
            out["names"][t] = {"status": "no_call", "reason": reasons, "values": {}}
            continue
        packet = json.loads(Path(n["packet"]).read_text(encoding="utf-8"))
        f, b, bar, record, r, prov, fy_ends = run.prepare(packet, n["cik"], str(n["sector"]), n["market_cap"] or 0, online=False,
                                                          family=n["family"])
        ids = task.evidence_ids(packet, record, b, bar, r, prov)
        route = "financial" if n["family"] in run.FINANCIAL else "operating"
        res = consensus.combine(ok, ids, b, bar, r, fy_ends, route)
        seed_base = {k: (v.get("values") or {}).get("base") for k, v in results.items()}
        out["names"][t] = {k: res.get(k) for k in ("status", "reason", "values", "annotations", "reverts", "of_record", "options",
                                                     "seeds")} | {"seed_base": seed_base}
        print(t, res["status"], (res.get("values") or {}).get("base"), seed_base,
              [a for a in res["annotations"] if a.startswith(("seeds_disagree", "one_seed"))], flush=True)
    p = VALUE / f"consensus_{formation_T}.json"
    p.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print("wrote", p, flush=True)
    return out


if __name__ == "__main__":
    main(sys.argv[1])
