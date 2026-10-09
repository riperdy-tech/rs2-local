"""Check 3: census (delisted-after-T) names priced by public float.  IV/price distribution against the others; H1/H2 without them and with them only."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
panel = lib.load_panel()
ins = panel[panel.family != "commodity"]
out = {}
g = ins.groupby(ins.survivor.astype(bool))
for k, d in g:
    out[f"survivor={k}"] = {"n": int(len(d)), "vp_mean_q": d.vp_mean.quantile([.05, .25, .5, .75, .95]).to_dict(), "s_cfg_q": d.s_cfg.quantile([.05, .25, .5, .75, .95]).to_dict(),
                           "vp_median_q": d.vp.quantile([.25, .5, .75]).to_dict(), "share_vpmean_gt_1": float((d.vp_mean > 1).mean()), "mcap_median": float(d.mcap.median()),
                           "family": d.family.value_counts().to_dict(), "cls": d.cls.value_counts(dropna=False).to_dict()}
    for b in ("excluded", "minus100", "last_close"):
        out[f"survivor={k}"][f"x12_{b}_n"] = int(d[f"x12_{b}"].notna().sum())
        out[f"survivor={k}"][f"x12_{b}_mean"] = float(d[f"x12_{b}"].mean())
# census by rank of s_cfg within date: where do they sit
ins = ins.copy()
ins["rk"] = ins.groupby("date")["s_cfg"].rank(pct=True)
out["census_rank_in_date_distribution"] = ins[ins.survivor.astype(bool)].rk.describe().to_dict()
out["census_share_top_quintile"] = float((ins[ins.survivor.astype(bool)].rk > 0.8).mean())
out["census_share_bottom_quintile"] = float((ins[ins.survivor.astype(bool)].rk <= 0.2).mean())
# per class
for c, d in ins[ins.survivor.astype(bool)].groupby("cls"):
    out[f"cls={c}"] = {"n": int(len(d)), "rk_mean": float(d.rk.mean()), "vp_mean_median": float(d.vp_mean.median()), "mcap_median": float(d.mcap.median())}
print(pd.Series({k: v for k, v in out.items() if k.startswith("surv")}).to_string()[:3000])
rows = lib.load_rows(panel)
sc = lib.key_map(panel, "s_cfg"); fn = lambda r: sc.get(r["_k"])
cens = set(zip(panel.loc[panel.survivor.astype(bool), "date"], panel.loc[panel.survivor.astype(bool), "cik"]))
for name, keep in {"baseline": lambda r: True, "excl. census names entirely": lambda r: r["_k"] not in cens}.items():
    rs = [r for r in rows if keep(r)]
    res = lib.bars(rs, fn, n_boot=nb)
    out[name] = {"n_rows": len(rs), "res": res}
    print(f"{name:35s} {len(rs)}  {lib.fmt(res)}", flush=True)
# census only: a pooled design needs >=30 names/date with outcome; report what exists
rs = [r for r in rows if r["_k"] in cens]
res = lib.bars(rs, fn, n_boot=0)
out["census only"] = {"n_rows": len(rs), "res": res}
print("census only", len(rs), lib.fmt(res, lb=False))
# census-only descriptive: the bound-filled returns are a constant per date, so only the SCORE differs; report the mean score and the acquired / not split
lib.dump(out, "a09_census.json")
