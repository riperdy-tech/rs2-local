"""Z item 1, step 3: H1/H2 with the M&A names removed (registered code), gate-1b holdout and development panel.
MAIN universe = survivor == False (Addendum Z 4: a delisted name with no observed traded price at T is unobservable).  Sensitivity = the registered all-names universe (census names, proxy-priced, included).
Removal is at the name-date level: a (date, cik) is dropped when its M tier flag is set (z02).  Holdout score = s_cfg (registered); development score = vp_mean (V1; the survival layer changes nothing)."""
import sys
import time

import numpy as np
import pandas as pd

from leak_audit import lib, libz

nb = int(sys.argv[1]) if len(sys.argv) > 1 else 399
t0 = time.time()
TIERS = ["M1", "M2", "M3", "M4", "M5"]
out = {"holdout": {}, "dev": {}}

# ---- holdout ----
panel = lib.load_panel()
rows = lib.load_rows(panel)
sc = lib.key_map(panel, "s_cfg")
fn = lambda r: sc.get(r["_k"])
H = libz.load_hold()
Fh = pd.read_pickle(libz.OUT / "z02_flags_hold.pkl")
H = H.merge(Fh, on=["date", "cik"], how="left")
cens = libz.hold_keys(H, H.survivor.astype(bool))
print("holdout rows", len(rows), flush=True)


def run_hold(lab, keep):
    rs = [r for r in rows if keep(r["_k"])]
    res = lib.bars(rs, fn, n_boot=nb)
    out["holdout"][lab] = {"n_rows": len(rs), "res": res}
    print(f"H | {lab:46s} {len(rs):6d} {lib.fmt(res)}  [{time.time()-t0:.0f}s]", flush=True)


run_hold("ALL names (registered; census incl.)", lambda k: True)
run_hold("MAIN: ex-census", lambda k: k not in cens)
for t in TIERS:
    fl = libz.hold_keys(H, H[t].fillna(False).astype(bool))
    run_hold(f"MAIN minus {t}", lambda k, fl=fl: k not in cens and k not in fl)
    run_hold(f"ALL minus {t} (sensitivity)", lambda k, fl=fl: k not in fl)
# name-level (a company flagged at any date of the panel is removed at every date)
for t in ("M1", "M2"):
    ciks = set(H.loc[H[t].fillna(False).astype(bool), "cik"])
    run_hold(f"MAIN minus {t} (name level)", lambda k, ciks=ciks: k not in cens and k[1] not in ciks)
    run_hold(f"ALL minus {t} (name level, sens.)", lambda k, ciks=ciks: k[1] not in ciks)

# ---- development ----
D = libz.load_dev()
Fd = pd.read_pickle(libz.OUT / "z02_flags_dev.pkl")
D = D.merge(Fd, on=["date", "cik"], how="left")


def run_dev(lab, df):
    res = libz.dev_bars(df, "vp_mean", nb)
    out["dev"][lab] = {"n_rows": int(len(df)), "res": res}
    print(f"D | {lab:46s} {len(df):6d} {libz.fmt_dev(res)}  [{time.time()-t0:.0f}s]", flush=True)


nc = ~D.survivor.astype(bool)
run_dev("ALL names (census incl.)", D)
run_dev("MAIN: ex-census", D[nc])
for t in TIERS:
    fl = D[t].fillna(False).astype(bool)
    run_dev(f"MAIN minus {t}", D[nc & ~fl])
    run_dev(f"ALL minus {t} (sensitivity)", D[~fl])
for t in ("M1", "M2"):
    ciks = set(D.loc[D[t].fillna(False).astype(bool), "cik"])
    run_dev(f"MAIN minus {t} (name level)", D[nc & ~D.cik.isin(ciks)])
    run_dev(f"ALL minus {t} (name level, sens.)", D[~D.cik.isin(ciks)])
libz.dump(out, "z03_ma_removal.json")
print("done", time.time() - t0)
