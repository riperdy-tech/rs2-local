"""Check 2 (effect size): H1/H2 excluding every company with an unexplained share-count jump between consecutive month-ends (|ln(shares ratio / split product)| > 0.25) or an odd-ratio
'split' (a spin-off / stock-dividend adjustment) in (T-1y, T+1y]."""
import sys, math
import numpy as np, pandas as pd
from leak_audit import lib

nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl")
panel = lib.load_panel()
p = panel[(panel.family != "commodity") & (~panel.survivor.astype(bool))].merge(f[["date", "cik", "ticker", "splits_win", "later_splits"]], on=["date", "cik", "ticker"], how="left").sort_values(["cik", "date"])
ev = {}
for _, r in p.iterrows():
    for lst in (r["splits_win"], r["later_splits"]):
        if isinstance(lst, list):
            for d, s in lst:
                ev.setdefault(r.cik, {})[d] = s
anom = set()
detail = []
for cik, g in p.groupby("cik"):
    g = g.set_index("date")
    for a, b in zip(lib.DATES[:-1], lib.DATES[1:]):
        if a in g.index and b in g.index and not isinstance(g.loc[a], pd.DataFrame) and not isinstance(g.loc[b], pd.DataFrame):
            sp = np.prod([s for d, s in ev.get(cik, {}).items() if a < d <= b]) if cik in ev else 1.0
            e = math.log((g.loc[b].shares / g.loc[a].shares) / sp)
            if abs(e) > 0.25:
                anom.add(cik); detail.append((cik, g.loc[a].ticker, a, b, e))
def odd(s):
    if s >= 1.5:
        return abs(2 * s - round(2 * s)) > 0.02
    if s < 1:
        return abs(1 / s - round(1 / s)) > 0.02
    return True
oddc = {c for c, d in ev.items() if any(odd(s) for s in d.values())}
print("anomaly ciks", len(anom), "odd-ratio ciks (any time in file window)", len(oddc))
rows = lib.load_rows(panel)
sc = lib.key_map(panel, "s_cfg"); fn = lambda r: sc.get(r["_k"])
out = {"anomalies": detail}
for name, keep in {"baseline": lambda r: True, "excl. share-jump anomaly ciks": lambda r: r["cik"] not in anom, "excl. odd-ratio (spin-off-like) split ciks": lambda r: r["cik"] not in oddc,
                   "excl. both": lambda r: r["cik"] not in anom and r["cik"] not in oddc}.items():
    rs = [r for r in rows if keep(r)]
    res = lib.bars(rs, fn, n_boot=nb)
    out[name] = {"n_rows": len(rs), "res": res}
    print(f"{name:45s} {len(rs)}  {lib.fmt(res)}", flush=True)
lib.dump(out, "a03b_share_anomaly_exclusion.json")
