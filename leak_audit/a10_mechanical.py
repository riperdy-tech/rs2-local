"""Check 9: mechanical-price artefacts.
 (A) B1/B2 with the IV numerator replaced: a constant (pure 1/price), book value / price, tangible book / price, the engine run at the company's OWN state (sw_own_all / price), the engine run at the
     population-median inputs (sw_pop_all / price: a function of price and the discount rate only), and the real score.
 (B) the real score with extra controls: 1-month reversal, 1/price, idiosyncratic volatility (and total vol, beta, liquidity, size) added to the five yardsticks.
Registered code (build_panel / fe_ols / b2_v2); the controls enter as extra 'yardsticks' (percentile rank, missing -> 0.5 plus an indicator)."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
panel = lib.load_panel()
rows = lib.load_rows(panel)
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl")
pf = f.set_index(["date", "cik"])
P = panel.set_index(["date", "cik"])
sc = lib.key_map(panel, "s_cfg")
def num(x):
    return None if x is None or x != x or np.isinf(x) else float(x)
# attach controls to rows
for r in rows:
    k = r["_k"]
    s = r["score"]
    pr = P.loc[k]
    px = r["price"]
    s["ctl_inv_price"] = 1.0 / px if px and px > 0 else None
    s["ctl_log_mcap"] = float(np.log(r["market_cap"])) if r.get("market_cap") else None
    if k in pf.index:
        g = pf.loc[k]
        s["ctl_ret_1m"] = num(g.get("ret_1m")); s["ctl_idio_vol"] = num(g.get("idio_vol_1y")); s["ctl_vol"] = num(g.get("vol_1y")); s["ctl_beta"] = num(g.get("beta_1y"))
        dv = num(g.get("dvol_3m")); s["ctl_dvol"] = float(np.log(dv)) if dv and dv > 0 else None
    else:
        for c in ("ctl_ret_1m", "ctl_idio_vol", "ctl_vol", "ctl_beta", "ctl_dvol"):
            s[c] = None
    eq, tbv, mc = num(pr.get("sv_equity")), num(pr.get("sv_tbv")), num(pr.get("mcap"))
    s["alt_bp"] = eq / mc if (eq is not None and mc) else None
    s["alt_tbp"] = tbv / mc if (tbv is not None and mc) else None
    s["alt_ownstate"] = num(pr.get("sw_own_all")); s["alt_popstate"] = num(pr.get("sw_pop_all")); s["alt_inv_price"] = s["ctl_inv_price"]
    s["alt_vp_median"] = num(pr.get("vp")); s["alt_vp_mean"] = num(pr.get("vp_mean"))
for c in ("ctl_ret_1m", "ctl_idio_vol", "ctl_vol", "ctl_beta", "ctl_dvol"):
    med = {}
    for d in lib.DATES:
        v = [r["score"][c] for r in rows if r["date"] == d and r["score"].get(c) is not None]
        med[d] = float(np.median(v))
    for r in rows:
        if r["score"].get(c) is None:
            r["score"][c] = med[r["date"]]
out = {"A": {}, "B": {}}
ONLY_B = len(sys.argv) > 2 and sys.argv[2] == "B"
print("(A) score replaced")
for lab, key in ([] if ONLY_B else (("REAL: mean x (1-P(fail))  [s_cfg]", None), ("constant numerator: 1/price", "alt_inv_price"), ("book value / price", "alt_bp"), ("tangible book / price", "alt_tbp"),
                 ("engine at own-state inputs / price", "alt_ownstate"), ("engine at population-P50 inputs / price", "alt_popstate"), ("engine median / price (registered V0)", "alt_vp_median"), ("engine mean / price", "alt_vp_mean"))):
    fn = (lambda r: sc.get(r["_k"])) if key is None else (lambda r, key=key: r["score"].get(key))
    res = lib.bars(rows, fn, n_boot=nb if key is None else 0)
    out["A"][lab] = res
    print(f"{lab:48s} {lib.fmt(res)}", flush=True)
print("(B) real score + controls")
fn = lambda r: sc.get(r["_k"])
Y = lib.YARDS
sets = {"5 yardsticks (registered)": Y,
        "+ 1m reversal": Y + ("ctl_ret_1m",), "+ 1/price": Y + ("ctl_inv_price",), "+ idio vol": Y + ("ctl_idio_vol",),
        "+ reversal + 1/price + idio vol": Y + ("ctl_ret_1m", "ctl_inv_price", "ctl_idio_vol"),
        "+ reversal, 1/price, idio vol, total vol, beta, log dollar volume, log mcap": Y + ("ctl_ret_1m", "ctl_inv_price", "ctl_idio_vol", "ctl_vol", "ctl_beta", "ctl_dvol", "ctl_log_mcap"),
        "+ the above + book/price": Y + ("ctl_ret_1m", "ctl_inv_price", "ctl_idio_vol", "ctl_vol", "ctl_beta", "ctl_dvol", "ctl_log_mcap", "alt_bp")}
for lab, ys in sets.items():
    res = lib.bars(rows, fn, n_boot=nb, yardsticks=ys)
    out["B"][lab] = res
    print(f"{lab:75s} {lib.fmt(res)}", flush=True)
lib.dump(out, "a10_mechanical.json")
