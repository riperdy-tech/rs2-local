"""E5's scoring (SPEC_rebuild Addendum AL.24): the oracle rank IC of engine v2 against v1 on one information set, with the Y1 controls.

    python -m rebuild_harness.forensics.e5_score RUN_DIR PRICE_FEATURES.pkl OUT.json

Panel: the forensic panel of RUN_DIR (`panel.build`: valued names of market cap >= $300M) joined to each record's `e5` values.  Scores: ln(value per share /
price) of `v2` and of `v1_same`, on their common sample (both defined and positive).  Statistic: `fxm.per_date(...)["ic_resid"]` at 3 months under each
bound, with the five yardsticks and the Y1 controls (book / price, log market cap, idiosyncratic volatility, 1-month return, 1/price) as residualising
columns, industry-demeaned; the mean over dates (pooled) and per valuation year.  Bars (AL.24): (i) pooled and every year, v2 >= v1 - 0.02 under each
bound; (ii) every family with >= 500 name-dates: the sign of v2's pooled ic_resid equals v1's.  Also reported: v1's full-K stored oracle (`or_main`) on its
own sample, n per date, and the names one engine values and the other does not."""
import gzip
import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import fxm
from . import panel as P

BOUNDS = ("excluded", "minus100", "last_close")
Y1 = ("y1_bp", "y1_log_size", "y1_idio_vol", "y1_ret_1m", "y1_inv_price")
MARGIN = 0.02
MIN_FAMILY = 500


def e5_of(run_dir) -> dict:
    out = {}
    for f in sorted(Path(run_dir).glob("records_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("e5") is not None:
                    out[(r["date"], r["cik"])] = r["e5"]
    return out


def _log_ratio(v, price):
    return math.log(v / price) if (v is not None and price and v > 0 and price > 0) else None


def build(run_dir, pf_path) -> pd.DataFrame:
    df = P.build(run_dir)
    with open(pf_path, "rb") as fh:
        pf = pickle.load(fh)["features"]
    get = lambda t, d, k: (pf.get(t, {}).get(d, {}) or {}).get(k) if t is not None else None
    df["y1_idio_vol"] = [get(t, d, "idio_vol_1y") for t, d in zip(df["ticker"], df["date"])]
    df["y1_ret_1m"] = [get(t, d, "ret_1m") for t, d in zip(df["ticker"], df["date"])]
    df["y1_bp"] = [(e / m) if (e is not None and m) else None for e, m in zip(df.get("sv_equity"), df["mcap"])]
    df["y1_log_size"] = [math.log(m) if m and m > 0 else None for m in df["mcap"]]
    df["y1_inv_price"] = [1.0 / p if p and p > 0 else None for p in df["price"]]
    e5 = e5_of(run_dir)
    rec = [e5.get((d, c)) or {} for d, c in zip(df["date"], df["cik"])]
    df["e5_v2"] = [_log_ratio(r.get("v2"), p) for r, p in zip(rec, df["price"])]
    df["e5_v1"] = [_log_ratio(r.get("v1_same"), p) for r, p in zip(rec, df["price"])]
    df["e5_v2_reason"] = [r.get("v2_reason") for r in rec]
    df["e5_v2_rote_only"] = [_log_ratio(r.get("v2_rote_only"), p) for r, p in zip(rec, df["price"])]          # AK.51 item 3: the labelled sensitivity
    df["e5_v1_rote_only"] = [_log_ratio(r.get("v1_same_rote_only"), p) for r, p in zip(rec, df["price"])]
    ratio = lambda fam, r: r.get("or_rote") if fam == "financial" else r.get("or_both")          # the stored full-K oracle, value / price (panel.row_of)
    df["or_full"] = [math.log(x) if (x is not None and isinstance(x, float) and math.isfinite(x) and x > 0) else None
                     for x in (ratio(f, r) for f, (_, r) in zip(df["family"], df.iterrows()))]
    return df


def stat(sub, score, bound, h=3):
    pdd = fxm.per_date(sub, score, h, bound, extra_resid_cols=Y1)
    pdd["year"] = [str(d)[:4] for d in pdd.index]
    return {"pooled": float(np.nanmean(pdd["ic_resid"])), "by_year": {y: float(np.nanmean(g["ic_resid"])) for y, g in pdd.groupby("year")},
            "n_dates": int(pdd["ic_resid"].notna().sum()), "n_per_date": {str(k): int(v) for k, v in pdd["n"].items()}}


def score(df) -> dict:
    common = df[df["e5_v2"].notna() & df["e5_v1"].notna()].copy()
    rep = {"rows_panel": int(len(df)), "common_sample": int(len(common)), "v2_only": int((df["e5_v2"].notna() & df["e5_v1"].isna()).sum()),
           "v1_only": int((df["e5_v1"].notna() & df["e5_v2"].isna()).sum()),
           "v2_refusal_reasons": df.loc[df["e5_v1"].notna() & df["e5_v2"].isna(), "e5_v2_reason"].fillna("none").str[:80].value_counts().head(10).to_dict(),
           "bounds": {}, "families": {}, "bar_i": True, "bar_ii": True}
    for b in BOUNDS:
        v2, v1 = stat(common, "e5_v2", b), stat(common, "e5_v1", b)
        ok_pool = v2["pooled"] >= v1["pooled"] - MARGIN
        ok_years = {y: v2["by_year"][y] >= v1["by_year"].get(y, np.nan) - MARGIN for y in v2["by_year"]}
        rep["bounds"][b] = {"v2": v2, "v1_same": v1, "pass_pooled": bool(ok_pool), "pass_years": {y: bool(x) for y, x in ok_years.items()}}
        if not (ok_pool and all(ok_years.values())):
            rep["bar_i"] = False
    for fam, sub in common.groupby("family"):
        if len(sub) < MIN_FAMILY:
            rep["families"][fam] = {"n": int(len(sub)), "tested": False}
            continue
        v2, v1 = stat(sub, "e5_v2", "excluded"), stat(sub, "e5_v1", "excluded")
        same = np.sign(v2["pooled"]) == np.sign(v1["pooled"])
        rep["families"][fam] = {"n": int(len(sub)), "tested": True, "v2_pooled": v2["pooled"], "v1_pooled": v1["pooled"], "same_sign": bool(same)}
        if not same:
            rep["bar_ii"] = False
    fin = df[(df["family"] == "financial") & df["e5_v2_rote_only"].notna() & df["e5_v1_rote_only"].notna()]
    if len(fin) >= MIN_FAMILY:                                                         # AK.51 item 3: reported, not a bar
        rep["sensitivity_financial_rote_only"] = {"n": int(len(fin)), "v2": stat(fin, "e5_v2_rote_only", "excluded")["pooled"],
                                                  "v1": stat(fin, "e5_v1_rote_only", "excluded")["pooled"]}
    rep["diag_horizons"] = {}                                                          # AK.51: 12 and 36 months, reported; never rescue a 3-month fail
    for h in (12, 36):
        try:
            rep["diag_horizons"][str(h)] = {"v2": stat(common, "e5_v2", "excluded", h)["pooled"], "v1_same": stat(common, "e5_v1", "excluded", h)["pooled"]}
        except Exception as e:                                                         # a horizon not formed for every date is stated, not filled
            rep["diag_horizons"][str(h)] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if df["or_full"].notna().any():
        rep["v1_full_k_reported"] = stat(df[df["or_full"].notna()], "or_full", "excluded")
    rep["E5"] = "PASS" if (rep["bar_i"] and rep["bar_ii"]) else "FAIL"
    return rep


def main(argv=None):
    a = argv or sys.argv[1:]
    df = build(a[0], a[1])
    rep = score(df)
    lin = Path(a[0]) / "lineage.json"
    rep["lineage"] = json.loads(lin.read_text(encoding="utf-8")) if lin.exists() else None
    Path(a[2]).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("common_sample", "v2_only", "v1_only")}), "| verdict written to", a[2], "and NOT printed (AL.31: sealed until cross-check 12 is ruled)")


if __name__ == "__main__":
    main()
