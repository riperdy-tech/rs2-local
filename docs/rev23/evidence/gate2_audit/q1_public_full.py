"""S1/S2 (AK.34) on a given outcomes file through the FULL scoring stages (bars, diagnostics incl. R3a, the independent recomputation, Audit 1), using
the flags written by q1_public_sensitivity.py.  Writes only under OUT.   python q1_public_full.py OUTCOMES.jsonl FLAGS.json BASELINES OUT"""
import json
import sys
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
from rebuild_harness.gate2 import score_day  # noqa: E402

STATE = Path(r"C:\Users\riper\stocks\stocks-workspace\data\gate2_run2")
src, flags, base, out = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")), Path(sys.argv[3]), Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines()]
res = {}
for name, rule in (("S1", "public_in_pack"), ("S2", "ended_before_T")):
    p = out / f"outcomes_{name}_2026-10-06.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for o in rows:
            o2 = json.loads(json.dumps(o))
            if flags.get(o["key"], {}).get(rule):
                o2["quarters"]["q1"] = None
            fh.write(json.dumps(o2) + "\n")
    res[name] = score_day.run_stages(STATE, p, base, None, out / name, {"mode": f"SENSITIVITY {name} ({rule}) on {src.name}", "scoring_date": "2026-10-06"})
print(json.dumps(res, indent=1))
