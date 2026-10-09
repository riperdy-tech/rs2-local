"""Check 10(b) follow-up: the score's relation to the PAST 12-month return is mechanical (IV / price rises when the price has fallen).  Add the past T-12m -> T excess return (and the 12-1 momentum already
in the five yardsticks) as an explicit control and recompute H1/H2, with and without the census names."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 299
panel = lib.load_panel(); rows = lib.load_rows(panel)
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl").set_index(["date", "cik"])
sc = lib.key_map(panel, "s_cfg"); fn = lambda r: sc.get(r["_k"])
cens = set(zip(panel.loc[panel.survivor.astype(bool), "date"], panel.loc[panel.survivor.astype(bool), "cik"]))
med = {d: float(f.loc[d]["pre12_x"].median()) for d in lib.DATES}
for r in rows:
    k = r["_k"]
    v = f.at[k, "pre12_x"] if k in f.index else None
    r["score"]["ctl_pre12"] = float(v) if v is not None and v == v else med[r["date"]]
Y = lib.YARDS
out = {}
for pop, keep in (("all", lambda r: True), ("survivors only", lambda r: r["_k"] not in cens)):
    rs = [r for r in rows if keep(r)]
    for lab, ys in (("5 yardsticks", Y), ("+ past 12m excess return", Y + ("ctl_pre12",))):
        res = lib.bars(rs, fn, n_boot=nb, yardsticks=ys)
        out[f"{pop} | {lab}"] = res
        print(f"{pop:15s} {lab:30s} {lib.fmt(res)}", flush=True)
lib.dump(out, "a10d_pre12_control.json")
