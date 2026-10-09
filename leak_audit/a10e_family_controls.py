"""Check 9 (continued): the same replacements and controls on SURVIVORS ONLY (census names removed; they have no D5 features and carry the acquisition returns), plus rank correlations of the score with
1/price, book/price and idio vol."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 199
panel = lib.load_panel()
rows_all = lib.load_rows(panel)
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl").set_index(["date", "cik"])
P = panel.set_index(["date", "cik"])
sc = lib.key_map(panel, "s_cfg")
def num(x):
    return None if x is None or x != x or np.isinf(x) else float(x)
CT = ("ctl_ret_1m", "ctl_idio_vol", "ctl_vol", "ctl_beta", "ctl_dvol")
for r in rows_all:
    k = r["_k"]; s = r["score"]; pr = P.loc[k]; px = r["price"]
    s["ctl_inv_price"] = 1.0 / px if px and px > 0 else None
    s["ctl_log_mcap"] = float(np.log(r["market_cap"])) if r.get("market_cap") else None
    g = f.loc[k] if k in f.index else None
    if g is not None:
        s["ctl_ret_1m"] = num(g.get("ret_1m")); s["ctl_idio_vol"] = num(g.get("idio_vol_1y")); s["ctl_vol"] = num(g.get("vol_1y")); s["ctl_beta"] = num(g.get("beta_1y"))
        dv = num(g.get("dvol_3m")); s["ctl_dvol"] = float(np.log(dv)) if dv and dv > 0 else None
    else:
        for c in CT: s[c] = None
    eq, tbv, mc = num(pr.get("sv_equity")), num(pr.get("sv_tbv")), num(pr.get("mcap"))
    s["alt_bp"] = eq / mc if (eq is not None and mc) else None
    s["alt_tbp"] = tbv / mc if (tbv is not None and mc) else None
cens = set(zip(panel.loc[panel.survivor.astype(bool), "date"], panel.loc[panel.survivor.astype(bool), "cik"]))
Y = lib.YARDS
FULL = Y + ("ctl_ret_1m", "ctl_inv_price", "ctl_idio_vol", "ctl_vol", "ctl_beta", "ctl_dvol", "ctl_log_mcap")
out = {}
fam = {r["_k"]: r["family"] for r in rows_all}
for pop, keep in (("operating family only, all", lambda r: fam[r["_k"]] == "operating"), ("operating family only, survivors", lambda r: fam[r["_k"]] == "operating" and r["_k"] not in cens), ("financial family only, all", lambda r: fam[r["_k"]] == "financial")):
    rows = [r for r in rows_all if keep(r)]
    for c in CT:
        med = {d: float(np.median([r["score"][c] for r in rows if r["date"] == d and r["score"].get(c) is not None])) for d in lib.DATES}
        for r in rows:
            if r["score"].get(c) is None: r["score"][c] = med[r["date"]]
    print("==", pop, len(rows), flush=True)
    for lab, fn, ys in (("real score, 5 yardsticks", lambda r: sc.get(r["_k"]), Y), ("1/price replaces IV", lambda r: r["score"]["ctl_inv_price"], Y),
                        ("book/price replaces IV", lambda r: r["score"].get("alt_bp"), Y), ("tangible book/price replaces IV", lambda r: r["score"].get("alt_tbp"), Y),
                        ("real + reversal, 1/price, idio vol", lambda r: sc.get(r["_k"]), Y + ("ctl_ret_1m", "ctl_inv_price", "ctl_idio_vol")),
                        ("real + full controls (no B/P)", lambda r: sc.get(r["_k"]), FULL),
                        ("real + full controls + book/price", lambda r: sc.get(r["_k"]), FULL + ("alt_bp",))):
        res = lib.bars(rows, fn, n_boot=nb if lab.startswith("real") else 0, yardsticks=ys)
        out[f"{pop} | {lab}"] = res
        print(f"{lab:45s} {lib.fmt(res)}", flush=True)
lib.dump(out, "a10e_family_controls.json")
