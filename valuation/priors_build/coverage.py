"""coverage.py - the coverage and survivorship figures quoted in the gap list of PRIORS_REPORT.md, from a vintage's observation table."""
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.priors_build import config as C
from valuation.priors_build import stats as S

if __name__ == "__main__":
    st = pd.read_csv(C.INPUTS_DIR / "company_status.csv.gz", dtype={"cik": str})
    for y in [int(a) for a in sys.argv[1:]] or [2016, 2025]:
        df = pd.read_csv(C.vintage_dir(y) / "obs.csv.gz", dtype={"cik": str, "sic": str}, low_memory=False)
        d = S.prep_frame(df, st, C.cut_date(y))
        print(y, len(d), "family", d["family"].value_counts(dropna=False).to_dict(), "basis", d["family_basis"].value_counts().to_dict())
        for fam in ("operating", "commodity", "financial"):
            s = d[d["family"] == fam]
            print(" ", fam, len(s), {c: round(float(s[c].notna().mean()), 3) for c in ("rev", "m", "med8", "cyc", "roic", "tbv", "rote", "g3", "y1", "rev_5")},
                  "ceased", round(float(s["ceased"].mean()), 3), "non-USD", round(float((~s["usd"]).mean()), 3))
        print("  SIC known: all", round(float(d["sic"].notna().mean()), 3), "ceased", round(float(d[d["ceased"]]["sic"].notna().mean()), 4),
              "not ceased", round(float(d[~d["ceased"]]["sic"].notna().mean()), 3))
