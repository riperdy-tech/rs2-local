"""Z item 1, step 2: the M&A flags of every (date, cik) of the holdout panel and of the development panel.
Window for an event: [T-12 months, T+12 months] ('within the 12-month outcome window or before': an agreement announced up to a year before T that is still pending at T is in).
  d1_acq_post   a D1 all-events acquisition event (acquisition_completed / acquisition_weak) dated in (T, T+12m]           -> the name was acquired inside the outcome window
  d1_acq_pre    the same, dated in (T-12m, T]  (a company still in the panel at T whose D1 event is earlier: a stale/other-security exit, kept as a flag)
  d1_acq_late   the same, dated in (T+12m, T+24m]  (completed after the window; announced inside it only if a form below says so)
  tgt_14d9      SC 14D9 (+/A) filed in the window  (filed only by the TARGET of a tender offer)
  tgt_proxy     DEFM14A / PREM14A / DEFM14C / PREM14C / SC 13E3 (+/A) in the window  (merger / going-private proxy: target, or a voting acquirer)
  bid_tender    SC TO-T(+/A), SC TO-C, SC 14D1(+/A) in the window (listed under both the bidder and the subject)
  s4_425        S-4(+/A) or 425 in the window (either side)
  k201 / k101   8-K / 8-K/A with Item 2.01 / 1.01 in the window (either side; 1.01 is mostly credit agreements and the like)
Tiers (nested):
  M1 = d1_acq_post OR d1_acq_pre            D1 acquisition classes (completed or weak) in the window
  M2 = M1 OR tgt_14d9 OR tgt_proxy          + the target-side announcement forms
  M3 = M2 OR bid_tender OR s4_425           + tender / registration / 425 either side
  M4 = M3 OR k201                           + 8-K completions of acquisitions or dispositions (either side)
  M5 = M4 OR k101                           + every 8-K with a material definitive agreement (the broadest)
"""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from leak_audit import lib, libz
from leak_audit.a01_d5_features import add_months

f = pd.read_pickle(libz.OUT / "z01_ma_filings.pkl")
f["filed"] = pd.to_datetime(f["filed"])
by = {c: g for c, g in f.groupby("cik")}
ev = {}
for e in json.load(open(lib.WS / "data" / "sec_bulk" / "index_P4b" / "events_all.json")):
    if e["class"] in ("acquisition_completed", "acquisition_weak"):
        ev.setdefault(e["cik"], []).append((pd.Timestamp(e["date"]), e["class"]))
FORM = {"tgt_14d9": {"SC 14D9", "SC 14D9/A", "SC14D9"}, "tgt_proxy": {"DEFM14A", "PREM14A", "DEFM14C", "PREM14C", "SC 13E3", "SC 13E3/A"},
        "bid_tender": {"SC TO-T", "SC TO-T/A", "SC TO-C", "SC 14D1", "SC 14D1/A"}, "s4_425": {"S-4", "S-4/A", "425"}}


def flags(df):
    out = []
    for (d, cik), _ in df.groupby(["date", "cik"]):
        T = pd.Timestamp(d)
        lo, hi, hi2 = pd.Timestamp(add_months(T.date(), -12)), pd.Timestamp(add_months(T.date(), 12)), pd.Timestamp(add_months(T.date(), 24))
        o = {"date": d, "cik": cik}
        es = ev.get(cik, [])
        o["d1_acq_post"] = any(T < x <= hi for x, _c in es)
        o["d1_acq_pre"] = any(lo < x <= T for x, _c in es)
        o["d1_acq_late"] = any(hi < x <= hi2 for x, _c in es)
        g = by.get(cik)
        if g is not None:
            w = g[(g.filed >= lo) & (g.filed <= hi)]
        else:
            w = f.iloc[0:0]
        for k, fs in FORM.items():
            o[k] = bool(w.form.isin(fs).any())
        k8 = w[w.form.isin(["8-K", "8-K/A"])]
        its = k8["items"].astype(str).str.split(",").apply(lambda s: {x.strip() for x in s})
        o["k201"] = bool(its.apply(lambda s: "2.01" in s).any())
        o["k101"] = bool(its.apply(lambda s: "1.01" in s).any())
        # first announcement-type date inside (T, hi] for the target-side forms (when did the market learn?)
        ann = w[w.form.isin(FORM["tgt_14d9"] | FORM["tgt_proxy"] | FORM["bid_tender"])]
        o["first_ann_form_date"] = ann.filed.min() if len(ann) else pd.NaT
        out.append(o)
    r = pd.DataFrame(out)
    r["M1"] = r.d1_acq_post | r.d1_acq_pre
    r["M2"] = r.M1 | r.tgt_14d9 | r.tgt_proxy
    r["M3"] = r.M2 | r.bid_tender | r.s4_425
    r["M4"] = r.M3 | r.k201
    r["M5"] = r.M4 | r.k101
    return r


for name, df in (("hold", libz.load_hold()), ("dev", libz.load_dev())):
    r = flags(df)
    r.to_pickle(libz.OUT / f"z02_flags_{name}.pkl")
    m = df.merge(r, on=["date", "cik"])
    print(name, len(m))
    nc = m[~m.survivor.astype(bool)]
    for lab, d in (("all", m), ("main (ex-census)", nc), ("census", m[m.survivor.astype(bool)])):
        print(f"  {lab:18s} n={len(d):6d} " + " ".join(f"{c}={int(d[c].sum())}({100*d[c].mean():.1f}%)" for c in ["d1_acq_post", "d1_acq_pre", "d1_acq_late", "tgt_14d9", "tgt_proxy", "bid_tender", "s4_425", "k201", "k101", "M1", "M2", "M3", "M4", "M5"]))
