"""Check 3 (effect): the census names' acquisition return is deal value / PROXY price - 1 (survivorship.Survivorship.outcome), the proxy being the last public float / shares (median 396 days
before T and, for survivors, 0.84 of the traded close at T).  Re-base those returns on a price at T: ret_adj = (1 + ret) * rho - 1 with rho the survivors' proxy / traded-price ratio
(median 0.84; q25 0.64; q75 1.07), and recompute H1/H2.  Also: census rows with the resolved acquisition return set to the cross-sectional median excess return (no premium credited)."""
import sys, copy
import numpy as np, pandas as pd
from leak_audit import lib
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
panel = lib.load_panel()
rows = lib.load_rows(panel)
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl")
spy = f.groupby("date").spy12_ind.first().to_dict()
cens = panel[panel.survivor.astype(bool) & panel.x12_excluded.notna()]
res_keys = set(zip(cens.date, cens.cik))
print("resolved census rows", len(res_keys))
sc = lib.key_map(panel, "s_cfg"); fn = lambda r: sc.get(r["_k"])
out = {}
def rebased(rho=None, mode=None):
    new = []
    for r in rows:
        if r["_k"] in res_keys:
            r = copy.deepcopy(r)
            ex = r["bounds"][12]["excluded"]
            ret = ex + spy[r["date"]]
            if mode == "median":
                # zero premium: the date's median survivor excess return
                new_ex = float(panel[(panel.date == r["date"]) & (~panel.survivor.astype(bool))].x12_excluded.median())
            else:
                new_ex = (1 + ret) * rho - 1 - spy[r["date"]]
            r["bounds"][12] = {"excluded": new_ex, "minus100": new_ex, "last_close": new_ex}
            r["excess"][12] = new_ex
        new.append(r)
    return new
for lab, rs in (("baseline", rows), ("resolved census returns re-based, rho=0.84 (median proxy/price)", rebased(0.8366)), ("rho=0.64 (q25)", rebased(0.6388)),
                ("rho=0.50", rebased(0.50)), ("resolved census returns set to the date's median survivor excess (no premium)", rebased(mode="median"))):
    res = lib.bars(rs, fn, n_boot=nb)
    out[lab] = res
    print(f"{lab:75s} {lib.fmt(res)}", flush=True)
lib.dump(out, "a09c_census_rebase.json")
