"""Check 8: outcome alignment.  Independent recomputation (a01: pandas on the raw D5 files) of every observed 12-month excess return, against the stored x12; dates of entry and exit."""
import numpy as np, pandas as pd
from leak_audit import lib
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl")
p = lib.load_panel()
p = p[(p.family != "commodity") & (~p.survivor.astype(bool))]
m = p.merge(f, on=["date", "cik", "ticker"], how="left")
out = {}
m["entry_gap"] = (pd.to_datetime(m.entry_date) - pd.to_datetime(m.date)).dt.days
out["entry_date_after_T_all"] = bool((m.entry_gap.dropna() >= 1).all())
out["entry_gap_days_dist"] = m.entry_gap.value_counts().sort_index().to_dict()
m["exit_gap"] = (pd.to_datetime(m.exit_date) - pd.to_datetime(m.date)).dt.days
out["exit_gap_days_min_max"] = [float(m.exit_gap.min()), float(m.exit_gap.max())]
out["exit_gap_quantiles"] = m.exit_gap.quantile([0, .01, .5, .99, 1]).to_dict()
# weekday check: is the entry bar the first bar strictly after T?
obs = m[m.x12_excluded.notna() & m.x12_ind.notna()].copy()
obs["diff"] = obs.x12_ind - obs.x12_excluded
out["n_observed_stored"] = int(m.x12_excluded.notna().sum())
out["n_compared"] = int(len(obs))
out["diff_abs_quantiles"] = obs["diff"].abs().quantile([.5, .9, .99, .999, 1]).to_dict()
out["n_abs_diff_gt_1e-6"] = int((obs["diff"].abs() > 1e-6).sum())
out["n_abs_diff_gt_1pp"] = int((obs["diff"].abs() > 0.01).sum())
bad = obs[obs["diff"].abs() > 1e-6][["date", "ticker", "x12_excluded", "x12_ind", "entry_date", "exit_date"]]
print(bad.head(30).to_string())
# stored observed but independent missing / vice versa
out["stored_obs_but_no_independent"] = int((m.x12_excluded.notna() & m.x12_ind.isna()).sum())
out["independent_but_stored_missing"] = int((m.x12_excluded.isna() & m.x12_ind.notna()).sum())
print(m[m.x12_excluded.notna() & m.x12_ind.isna()][["date", "ticker", "x12_excluded", "x12_minus100", "x12_last_close"]].head(15))
print(m[m.x12_excluded.isna() & m.x12_ind.notna()][["date", "ticker", "x12_minus100"]].head(10))
print(out)
lib.dump(out, "a08_outcomes.json")
