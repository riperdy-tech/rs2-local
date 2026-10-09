"""Headline B1 coefficients with the registered wild-cluster bootstrap-t (one-sided 90% lower bound, date clusters) for the scores the decision turns on.

    python -m rebuild_harness.forensics.headline PANEL.pkl OUT.json [--n-boot 499]

Note: the registered holdout used 999 draws; the lower bound here uses n_boot draws (default 499).  The clusters are the dates; with overlapping horizons the date-clustered bootstrap is too tight, so the
horizon-24 and -36 lower bounds are optimistic and are shown only to compare with the 12-month ones."""
import argparse
import json
import time

import numpy as np
import pandas as pd

from . import fxm
from .analysis_f import Y5, BOUNDS


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("panel")
    ap.add_argument("out")
    ap.add_argument("--n-boot", type=int, default=499)
    a = ap.parse_args(argv)
    df = pd.read_pickle(a.panel).reset_index(drop=True)
    df["or_main"] = np.where(df["family"] == "financial", df["or_rote"], df["or_both"])
    df["naive"] = df["sw_own_all"]
    common = df[df["or_main"].notna() & df["naive"].notna()]
    cd = df[df["date"] <= "2023-09-30"]
    specs = [("registered median IV/price, all dates", df, "vp", 12), ("registered median IV/price, all dates", df, "vp", 24),
             ("registered median IV/price, dates with a 36m outcome", cd, "vp", 36), ("registered median IV/price, dates with a 36m outcome", cd, "vp", 12),
             ("mean of the draws, all dates", df, "vp_mean", 12), ("mean of the draws, all dates", df, "vp_mean", 24),
             ("naive inputs, common sample", common, "naive", 12), ("registered, common sample", common, "vp", 12), ("ORACLE, common sample", common, "or_main", 12),
             ("2023-2024 dates only (the spent holdout, quarter-ends), registered", df[df["date"] >= "2023-01-01"], "vp", 12),
             ("2020-2022 dates only (quarter-ends), registered", df[df["date"] < "2023-01-01"], "vp", 12)]
    out = []
    for lab, d, col, h in specs:
        for b in BOUNDS:
            t0 = time.time()
            c = fxm.pooled_coef(d, d[col], h, b, Y5, n_boot=a.n_boot)
            row = {"spec": lab, "score": col, "h": h, "bound": b, "result": c, "seconds": round(time.time() - t0)}
            out.append(row)
            print(lab, col, h, b, None if c is None else {k: round(v, 4) for k, v in c.items() if isinstance(v, float)}, flush=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
