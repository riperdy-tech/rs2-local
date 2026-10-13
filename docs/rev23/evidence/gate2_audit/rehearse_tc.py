"""Q3 rehearsal of `tag_consistent.py rescore`, end to end, with NO real outcome: pseudo-outcomes where q1 is the latest quarter filed BEFORE T (its
extractor measures as the 'registered' values), everything else from score_day's dummy outcomes.  Writes only under OUT."""
import json
import subprocess
import sys
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
from rebuild_harness import gate1_run as g  # noqa: E402
from rebuild_harness.gate2 import score_day  # noqa: E402
from valuation.pit_data import PitData  # noqa: E402

STATE = Path(r"C:\Users\riper\stocks\stocks-workspace\data\gate2_run2")
OUT = Path(__file__).parent / "tag_consistent_rehearsal"
BASE = Path(r"C:\Users\riper\stocks\stocks-workspace\data\gate2_rehearsal_r4\baselines\baselines.json")
OUT.mkdir(exist_ok=True)
dummy = score_day.dummy_outcomes(STATE, OUT / "dummy.jsonl")
pit = PitData(g.DEFAULT_STORE)
with open(OUT / "pseudo_outcomes_2099-01-01.jsonl", "x", encoding="utf-8") as fo:
    for line in dummy.read_text(encoding="utf-8").splitlines():
        o = json.loads(line)
        rows = pit.quarterly_rows(o["cik"], o["key"][:10], ("revenue", "operating_income", "net_income"), 1, "first_filed")
        if rows and str(rows[-1]["filed"])[:10] < o["key"][:10]:
            r = rows[-1]
            v, p = r["values"], r["prior_year"]
            q = {"period_end": r["period_end"], "filed": r["filed"], "accession": r["accession"],
                 "revenue_growth": (v["revenue"] / p["revenue"] - 1) if v.get("revenue") and p.get("revenue") else None,
                 "operating_margin_change": None, "rote_change_annualised_on_tbv_at_T": None}
            o["quarters"] = {"q1": q, "q2": None}
        o["family"] = o.get("family") or None
        fo.write(json.dumps(o) + "\n")
rc = subprocess.run([sys.executable, str(Path(__file__).parent / "tag_consistent.py"), "rescore", "--state-dir", str(STATE),
                     "--outcomes", str(OUT / "pseudo_outcomes_2099-01-01.jsonl"), "--store", str(g.DEFAULT_STORE), "--baselines", str(BASE),
                     "--out", str(OUT / "run"), "--draws", "200"]).returncode
print("rescore rc", rc)
