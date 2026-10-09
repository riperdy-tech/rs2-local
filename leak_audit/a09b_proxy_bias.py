"""Check 3 (continued): how biased is the public-float price proxy?  For the SURVIVORS (which have a real price at T) compute the same proxy the census names get (latest float / latest 10-K/10-Q share count,
filed before T) and compare it to the traded close at T.  Then rescale the census names' score by the survivors' proxy ratio and recompute H1/H2."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib
from rebuild_harness import survivorship as sv
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
ci = sv.CoverIndex(lib.WS / "data" / "survivorship_cover")
panel = lib.load_panel()
p = panel[(panel.family != "commodity")].copy()
p["surv"] = p.survivor.astype(bool)
out = {}
ratios = []
for _, r in p[~p.surv].iterrows():
    it = ci.latest(r.cik, r.date)
    if it is None or it["price_proxy"] is None:
        ratios.append(np.nan); continue
    ratios.append(it["price_proxy"] / r.price)
p.loc[~p.surv, "proxy_ratio"] = ratios
x = p.loc[~p.surv, "proxy_ratio"].dropna()
out["survivors_with_cover"] = int(len(x)); out["survivors_total"] = int((~p.surv).sum())
out["proxy_over_price_quantiles"] = x.quantile([.05, .1, .25, .5, .75, .9, .95]).to_dict()
out["proxy_over_price_geomean"] = float(np.exp(np.log(x[x > 0]).mean()))
# by size group and for large majority-held? just overall + by mcap tercile
p["mc_t"] = pd.qcut(p.mcap, 3, labels=["small", "mid", "large"])
out["by_size_median"] = p[~p.surv].groupby("mc_t", observed=True).proxy_ratio.median().to_dict()
# age of the float date for census vs survivors
ages = {"census": [], "surv": []}
for _, r in p.sample(2500, random_state=2).iterrows():
    it = ci.latest(r.cik, r.date)
    if it is None: continue
    age = (pd.Timestamp(r.date) - pd.Timestamp(it["end"])).days if it["end"] else None
    if age is not None: ages["census" if r.surv else "surv"].append(age)
out["float_age_days_median"] = {k: (float(np.median(v)) if v else None) for k, v in ages.items()}
# census: the proxy relation for all 626
c = p[p.surv]
ca = []
for _, r in c.iterrows():
    it = ci.latest(r.cik, r.date)
    ca.append((pd.Timestamp(r.date) - pd.Timestamp(it["end"])).days if it and it["end"] else np.nan)
out["census_float_age_days_median_all"] = float(np.nanmedian(ca))
med = out["proxy_over_price_quantiles"][0.5]
print({k: v for k, v in out.items() if k != "by_size_median"}, out["by_size_median"])
# rescaled score: census names' IV/price divided by 1/med: price_true ~ proxy/med -> vp_true = vp * proxy/price_true... vp = IV/proxy ; vp_true = IV/(proxy/med) = vp*med
panel2 = panel.copy()
sc2 = panel2["s_cfg"].copy()
m = panel2.survivor.astype(bool)
sc2[m] = sc2[m] * med
panel2["s_adj"] = sc2
rows = lib.load_rows(panel)
for lab, col in (("baseline s_cfg", "s_cfg"), (f"census score x median proxy ratio ({med:.2f})", "s_adj")):
    sc = lib.key_map(panel2, col); fn = lambda r: sc.get(r["_k"])
    res = lib.bars(rows, fn, n_boot=nb)
    out[lab] = res
    print(f"{lab:55s} {lib.fmt(res)}", flush=True)
# also: census rescaled by the 25th percentile ratio (a stronger deflation)
for q in (0.25, 0.75):
    qv = out["proxy_over_price_quantiles"][q]
    s3 = panel2["s_cfg"].copy(); s3[m] = s3[m] * qv
    panel2["s_q"] = s3
    sc = lib.key_map(panel2, "s_q"); fn = lambda r: sc.get(r["_k"])
    res = lib.bars(rows, fn, n_boot=0)
    out[f"census x q{q}"] = res
    print(f"census score x q{q} ratio ({qv:.2f})  {lib.fmt(res, lb=False)}")
lib.dump(out, "a09b_proxy_bias.json")
