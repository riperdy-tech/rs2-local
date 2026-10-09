"""Check 7: the engine-consistent equity risk premium and the Damodaran beta files used at each of the nine dates."""
import json
from datetime import date
from leak_audit import lib
from valuation.discount_rate import DamodaranStore
out = {}
for d in lib.DATES:
    c = json.load(open(lib.RUN / f"context_{d}.json"))
    e = c["erp"]
    out[d] = {"row_date": e["row_date"], "row_date_le_T": e["row_date"] <= d, "age_days": (date.fromisoformat(d) - date.fromisoformat(e["row_date"])).days, "damodaran_erp": e["damodaran_erp"],
              "engine_erp": e["erp"], "engine_growth": e["engine_growth"], "index_level": e["index_level"], "rf_row": e["rf_row"], "rf_used": c["rf"], "universe_n": e["universe"]["n"],
              "erp_file_sha": e["file_sha256"][:12], "universe_rule": e["universe"]["rule"]}
    print(d, {k: out[d][k] for k in ("row_date", "age_days", "damodaran_erp", "engine_erp", "engine_growth", "index_level", "rf_used")})
st = DamodaranStore()
snaps = st.beta_snapshots()
out["beta_snapshots"] = [{"date": str(s["date"]), "file": s["file"]} for s in snaps]
print([ (str(s["date"]), s["file"]) for s in snaps][-5:])
out["beta_file_for_T"] = {}
for d in lib.DATES:
    ok = [s for s in snaps if s["date"] < date.fromisoformat(d)]
    out["beta_file_for_T"][d] = {"file": ok[-1]["file"], "file_date": str(ok[-1]["date"]), "lt_T": ok[-1]["date"] < date.fromisoformat(d)}
print(out["beta_file_for_T"])
# ERP file: index level vs the S&P 500 close on the row date (SPY as a proxy via D5): is the index_level the known close of the month before?
import pandas as pd
spy = pd.read_csv(lib.D5 / "SPY.csv.gz", usecols=["Date", "Close"])
lib.dump(out, "a15_erp.json")
