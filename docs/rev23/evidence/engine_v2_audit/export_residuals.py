"""Export the D-T1 residual panel (vintage 2024: outcomes filed before 2025-01-01) as built by rs2-local review-2026-10/gate2-run2 a605eff
(`valuation/priors_build/near_term.residual_frame`), so D-T1 can be recomputed from the file alone (d_t1_from_csv.py). Columns: cik, date,
family, var, k, resid. Derived from public SEC filings; no other field is exported."""
import hashlib
import sys
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
import pandas as pd  # noqa: E402
from valuation.priors_build import near_term as b  # noqa: E402

out = Path(__file__).with_name("d_t1_residuals_cut2025.csv.gz")
res = b.residual_frame(pd.read_pickle(b.PANEL), b.load_obs(), "2025-01-01")
res[["cik", "date", "family", "var", "k", "resid"]].to_csv(out, index=False, float_format="%.10g", compression={"method": "gzip", "mtime": 0})
print(len(res), "rows ->", out.name, hashlib.sha256(out.read_bytes()).hexdigest())
