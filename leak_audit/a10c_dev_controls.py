"""Check 9, development panel (20 quarter-ends 2020-2024, the forensic run): is the dev edge also spanned by 1/price, book/price and the vol/size controls?  Score = vp_mean (V1, no survival layer:
AUC .65, it changes nothing).  forensics.fxm machinery (registered B1/B2 construction at 12 months), extra controls entered as ranks."""
import sys
import numpy as np, pandas as pd
from leak_audit import lib
from rebuild_harness.forensics import fxm
nb = int(sys.argv[1]) if len(sys.argv) > 1 else 199
d = pd.read_pickle(lib.FOREN / "panel_q20.pkl")
d = d[d.family != "commodity"].reset_index(drop=True)
d["inv_price"] = 1 / d.price
d["bp"] = d.sv_equity / d.mcap
d["tbp"] = d.sv_tbv / d.mcap
d["ldvol"] = np.log(d.dvol_3m.where(d.dvol_3m > 0))
d["lmcap"] = np.log(d.mcap)
for c in ("vol_1y", "beta_1y", "ldvol", "lmcap", "inv_price", "bp"):
    d[c] = d[c].replace([np.inf, -np.inf], np.nan)
    d[c] = d[c].fillna(d.groupby("date")[c].transform("median"))
Y5 = ("y_ey", "y_fcfy", "y_gp", "y_roc", "y_mom")
out = {}
def run(df, lab, score, controls=(), n_boot=0):
    r = {}
    for b in ("excluded", "minus100", "last_close"):
        dd = df[df[score].notna()]
        c = fxm.pooled_coef(dd, dd[score], 12, b, Y5, control_cols=controls, n_boot=n_boot)
        pdd = fxm.per_date(dd, score, 12, b, Y5, extra_resid_cols=controls)
        s = fxm.summarize(pdd, 12)
        r[b] = {"B1": c["beta"] if c else None, "B1_lb": (c or {}).get("lower90"), "B2_resid_pp": 100 * s["spread_resid"], "n": c["n"] if c else None}
    out[lab] = r
    print(f"{lab:62s} " + " ;; ".join(f"{(r[b]['B1'] or float('nan')):+.3f}" + (f" (lb {r[b]['B1_lb']:+.3f})" if r[b]['B1_lb'] is not None else "") + f" | {r[b]['B2_resid_pp']:+.1f}pp" for b in r), flush=True)
for pop, df in (("ALL (census incl.)", d), ("SURVIVORS only", d[~d.survivor.astype(bool)])):
    print("==", pop, len(df), "name-dates")
    run(df, f"{pop} | vp_mean, 5 yardsticks", "vp_mean", (), nb)
    run(df, f"{pop} | 1/price replaces IV", "inv_price")
    run(df, f"{pop} | book/price replaces IV", "bp")
    run(df, f"{pop} | tangible book/price replaces IV", "tbp")
    run(df, f"{pop} | vp_mean + 1/price", "vp_mean", ("inv_price",), nb)
    run(df, f"{pop} | vp_mean + 1/price, vol, beta, dollar vol, mcap", "vp_mean", ("inv_price", "vol_1y", "beta_1y", "ldvol", "lmcap"), nb)
    run(df, f"{pop} | vp_mean + the above + book/price", "vp_mean", ("inv_price", "vol_1y", "beta_1y", "ldvol", "lmcap", "bp"), nb)
lib.dump(out, "a10c_dev_controls.json")
