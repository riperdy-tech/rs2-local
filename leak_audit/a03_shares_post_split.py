"""Check 2: for every name-date with a split AFTER T, compare the share count on the traded basis at T (x the split product) with the first post-split cover-page share count
(an independent filing, dated after the ex-date).  A pre/post split basis mismatch would show as a ratio near the split ratio (or its inverse), not near 1.  Controls: the same ratio for
names without a split, same horizon."""
import math, datetime as dt
import numpy as np, pandas as pd
from leak_audit import lib, store

f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl")
p = lib.load_panel()
p = p[(p.family != "commodity") & (~p.survivor.astype(bool))].merge(f[["date", "cik", "ticker", "later_splits", "n_later_splits", "splits_win", "n_split_win"]], on=["date", "cik", "ticker"], how="left")
rows = []
for _, r in p[p.n_later_splits > 0].iterrows():
    c = store.company(r.cik)
    if c is None:
        continue
    for E, S in r.later_splits:
        asof = (dt.date.fromisoformat(E) + dt.timedelta(days=200)).isoformat()
        cov = c.cover_shares(asof)
        # take the first cover count whose cover date is after E: scan asofs
        best = None
        for add in (45, 75, 110, 150, 200, 260, 330):
            a = (dt.date.fromisoformat(E) + dt.timedelta(days=add)).isoformat()
            cv = c.cover_shares(a)
            if cv and cv.get("cover_date") and cv["cover_date"] > E:
                best = cv
                break
        if best is None:
            rows.append((r.date, r.ticker, E, S, r.shares, None, None, None))
            continue
        # product of ALL splits between T and the post cover date
        allp = np.prod([s for d, s in r.later_splits if d < best["cover_date"]])
        rows.append((r.date, r.ticker, E, S, r.shares, best["value"], best["cover_date"], best["value"] / (r.shares * allp)))
d = pd.DataFrame(rows, columns=["date", "ticker", "ex", "ratio", "shares_T", "cover_post", "cover_date", "post_over_expected"])
d["lr"] = np.log(d.post_over_expected)
print(len(d), d.post_over_expected.notna().sum())
print(d.lr.describe(percentiles=[.05,.25,.5,.75,.95]))
bad = d[d.lr.abs() > 0.4].sort_values("lr")
print(len(bad)); print(bad.to_string())
d.to_pickle(lib.OUT / "a03_shares_post_split.pkl")
# control: names without splits, cover ~ 12 months later vs T (organic drift)
ctl = []
ps = p[(p.n_later_splits == 0) & (p.n_split_win == 0)].sample(600, random_state=1)
for _, r in ps.iterrows():
    c = store.company(r.cik)
    if c is None: continue
    T = dt.date.fromisoformat(r.date)
    a = (T + dt.timedelta(days=300)).isoformat()
    cv = c.cover_shares(a)
    if cv and cv["value"] > 0:
        ctl.append(math.log(cv["value"] / r.shares))
ctl = pd.Series(ctl)
print("control organic 10-month drift of cover count, log:", ctl.describe(percentiles=[.05,.5,.95]).to_dict())
