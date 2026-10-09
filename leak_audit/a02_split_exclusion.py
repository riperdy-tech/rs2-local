"""Check 1 (second half): H1/H2 with the names that split (or were adjusted for a spin-off) around T excluded; registered code, 999 draws for the lower bound."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib

nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
panel = lib.load_panel()
rows = lib.load_rows(panel)
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl").set_index(["date", "cik"])
sc = lib.key_map(panel, "s_cfg")
fn = lambda r: sc.get(r["_k"])

def flag(k, col):
    try:
        v = f.at[k, col]
    except KeyError:
        return 0
    return 0 if v is None or v != v else v

def sel(pred):
    return [r for r in rows if pred(r["_k"])]

variants = {
    "baseline (all)": lambda k: True,
    "excl. any split in (T-1y, T+1y]": lambda k: flag(k, "n_split_win") == 0,
    "excl. any split AFTER T (to 2026-10)": lambda k: flag(k, "n_later_splits") == 0,
    "excl. splits in (T-1y, T+1y] of ratio >=1.5-fold": lambda k: flag(k, "n_split_win_ge1p5") == 0,
    "ONLY names with a split in (T-1y, T+1y]": lambda k: flag(k, "n_split_win") > 0,
    "ONLY names with a split after T": lambda k: flag(k, "n_later_splits") > 0,
}
out = {}
for name, pred in variants.items():
    rs = sel(pred)
    res = lib.bars(rs, fn, n_boot=nb if "ONLY" not in name else 0)
    out[name] = {"n_rows": len(rs), "res": res}
    print(f"{name:55s} rows={len(rs):6d}  {lib.fmt(res)}", flush=True)
lib.dump(out, "a02_split_exclusion.json")
