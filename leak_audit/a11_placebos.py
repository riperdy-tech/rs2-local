"""Check 10: placebos.
 (a) the score shuffled across names within date x industry (N shuffles, fixed seed): the null distribution of the H1 coefficient and the H2 residual spread under the registered design;
 (b) the outcome replaced by the PRE-period excess return (T-12m -> T) over the same names (survivors only: the census names have no price history); with all five yardsticks and without the
     12-1 momentum yardstick (which is nearly the same variable);
 (c) the score lagged 12 months: IV/price of T-12m (development panel, quarter-ends) -> 12-month return from T, and the stale intrinsic value over today's price."""
import sys, copy
import numpy as np, pandas as pd
from leak_audit import lib
NS = int(sys.argv[1]) if len(sys.argv) > 1 else 150
panel = lib.load_panel()
rows = lib.load_rows(panel)
sc = lib.key_map(panel, "s_cfg")
f = pd.read_pickle(lib.OUT / "a01_d5_features.pkl").set_index(["date", "cik"])
out = {}
# ---------------- (a)
base = lib.bars(rows, lambda r: sc.get(r["_k"]), n_boot=0)
out["real"] = base
print("real", lib.fmt(base, lb=False), flush=True)
rng = np.random.default_rng(20261009)
groups = {}
for r in rows:
    groups.setdefault((r["date"], r["industry"] or "unknown"), []).append(r["_k"])
H1 = {b: [] for b in lib.BOUNDS}; H2 = {b: [] for b in lib.BOUNDS}
for i in range(NS):
    shuf = {}
    for g, ks in groups.items():
        vals = np.array([sc[k] for k in ks if k in sc]); kk = [k for k in ks if k in sc]
        perm = rng.permutation(len(vals))
        for k, j in zip(kk, perm):
            shuf[k] = vals[j]
    res = lib.bars(rows, lambda r, shuf=shuf: shuf.get(r["_k"]), n_boot=0)
    for b in lib.BOUNDS:
        H1[b].append(res[b]["H1"]); H2[b].append(res[b]["H2_pp"])
    if i % 25 == 0:
        print("shuffle", i, flush=True)
out["a_shuffle"] = {b: {"H1_mean": float(np.mean(H1[b])), "H1_sd": float(np.std(H1[b], ddof=1)), "H1_q95": float(np.quantile(H1[b], .95)), "H1_max": float(np.max(H1[b])),
                        "H2_mean_pp": float(np.mean(H2[b])), "H2_sd_pp": float(np.std(H2[b], ddof=1)), "H2_q95_pp": float(np.quantile(H2[b], .95)), "H2_max_pp": float(np.max(H2[b])),
                        "p_H1": float((np.array(H1[b]) >= base[b]["H1"]).mean()), "p_H2": float((np.array(H2[b]) >= base[b]["H2_pp"]).mean()), "n_shuffles": NS} for b in lib.BOUNDS}
print("(a)", out["a_shuffle"], flush=True)
# ---------------- (b)
def with_outcome(rs, getter):
    new = []
    for r in rs:
        v = getter(r["_k"])
        r2 = dict(r)
        if v is None or v != v:
            r2["bounds"] = {12: {"excluded": None, "minus100": None, "last_close": None}}
            r2["excess"] = {12: None}
        else:
            r2["bounds"] = {12: {"excluded": v, "minus100": v, "last_close": v}}
            r2["excess"] = {12: v}
        new.append(r2)
    return new
pre = lambda k: (float(f.at[k, "pre12_x"]) if k in f.index and f.at[k, "pre12_x"] == f.at[k, "pre12_x"] else None)
rows_pre = with_outcome(rows, pre)
fn = lambda r: sc.get(r["_k"])
Y4 = tuple(y for y in lib.YARDS if y != "yardstick_momentum_12_1")
res_pre5 = lib.bars(rows_pre, fn, n_boot=0, bounds=("excluded",))
res_pre4 = lib.bars(rows_pre, fn, n_boot=0, bounds=("excluded",), yardsticks=Y4)
res_post4 = lib.bars(rows, fn, n_boot=0, bounds=("excluded",), yardsticks=Y4)
out["b_pre_period"] = {"pre12_5yard": res_pre5, "pre12_4yard_no_mom": res_pre4, "post12_4yard_no_mom": res_post4}
print("(b) pre-period (T-12m -> T) outcome, 5 yardsticks:", lib.fmt({"excluded": res_pre5["excluded"], "minus100": res_pre5["excluded"], "last_close": res_pre5["excluded"]}, lb=False))
print("(b) pre-period, no momentum yardstick          :", lib.fmt({"excluded": res_pre4["excluded"], "minus100": res_pre4["excluded"], "last_close": res_pre4["excluded"]}, lb=False))
print("    post-period (registered outcome), no mom.  :", lib.fmt({"excluded": res_post4["excluded"], "minus100": res_post4["excluded"], "last_close": res_post4["excluded"]}, lb=False))
# ---------------- (c)
dev = pd.read_pickle(lib.FOREN / "panel_q20.pkl")
dev = dev[dev.family != "commodity"]
cur = panel[panel.family != "commodity"].set_index(["date", "cik"])
res_c = {}
for T in ("2025-03-31", "2025-06-30", "2025-09-30"):
    Tm = str(int(T[:4]) - 1) + T[4:]
    dd = dev[dev.date == Tm].set_index("cik")
    res_c[T] = int(len(dd))
lagged_vp, lagged_iv_over_mc_now = {}, {}
for T in ("2025-03-31", "2025-06-30", "2025-09-30"):
    Tm = str(int(T[:4]) - 1) + T[4:]
    dd = dev[dev.date == Tm].set_index("cik")
    for cik, r in dd.iterrows():
        k = (T, cik)
        if k in cur.index and r.vp_mean == r.vp_mean and r.mcap and cur.at[k, "mcap"]:
            lagged_vp[k] = float(r.vp_mean)
            lagged_iv_over_mc_now[k] = float(r.vp_mean * r.mcap / cur.at[k, "mcap"])
rows3 = [r for r in rows if r["date"] in ("2025-03-31", "2025-06-30", "2025-09-30")]
same = lambda r: sc.get(r["_k"]) if r["_k"] in lagged_vp else None
lag1 = lambda r: lagged_vp.get(r["_k"])
lag2 = lambda r: lagged_iv_over_mc_now.get(r["_k"])
c_same = lib.bars(rows3, same, n_boot=0); c_lag1 = lib.bars(rows3, lag1, n_boot=0); c_lag2 = lib.bars(rows3, lag2, n_boot=0)
out["c_lag"] = {"n_matched": len(lagged_vp), "same_names_current_score": c_same, "lagged_ivprice": c_lag1, "stale_iv_over_current_mcap": c_lag2}
print("(c) n matched", len(lagged_vp))
for lab, r_ in (("current score, same names/dates (3 quarter-end dates)", c_same), ("IV/price of T-12m (stale ranking)", c_lag1), ("IV(T-12m)/mcap(T)", c_lag2)):
    print(f"   {lab:55s} {lib.fmt(r_, lb=False)}")
lib.dump(out, "a11_placebos.json")
