"""Z item 1, step 4b: the 12-month excess returns of the M&A-flagged names against the rest (descriptive), MAIN and ALL universes; and the 21 holdout MAIN names with a D1 acquisition inside the window."""
import numpy as np
import pandas as pd

from leak_audit import lib, libz

out = {}
for name, df0 in (("holdout", libz.load_hold()), ("dev", libz.load_dev())):
    F = pd.read_pickle(libz.OUT / f"z02_flags_{'hold' if name == 'holdout' else name}.pkl")
    df = df0.merge(F, on=["date", "cik"], how="left")
    df["x"] = pd.to_numeric(df.x12_last_close, errors="coerce")
    res = {}
    for uni, d in (("ALL", df), ("MAIN", df[~df.survivor.astype(bool)])):
        for t in ("M1", "M2", "M3"):
            f = d[t].fillna(False).astype(bool)
            res[f"{uni}|{t}"] = {"n_flag": int(f.sum()), "mean_x12_flag": float(d[f].x.mean()), "median_x12_flag": float(d[f].x.median()), "n_obs_flag": int(d[f].x.notna().sum()),
                                 "mean_x12_rest": float(d[~f].x.mean()), "median_x12_rest": float(d[~f].x.median())}
            print(name, uni, t, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res[f"{uni}|{t}"].items()})
    out[name] = res
h = libz.load_hold().merge(pd.read_pickle(libz.OUT / "z02_flags_hold.pkl"), on=["date", "cik"])
m1 = h[(~h.survivor.astype(bool)) & h.M1][["date", "ticker", "mcap", "price", "x12_last_close", "x12_excluded"]]
print(m1.sort_values("date").to_string())
out["holdout_main_M1_names"] = m1.astype({"mcap": float}).to_dict("records")
libz.dump(out, "z04b_ma_returns.json")
