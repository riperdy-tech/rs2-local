"""The forensic panel: one row per valued name-date of market cap >= $300M (the gate-1 universe), flat columns, from the forensic run's records.

    python -m rebuild_harness.forensics.panel RUN_DIR OUT.pkl [--price-features PF.pkl]

Columns (selection): date, year, cik, ticker, family, industry, sector, mcap, price, survivor (census name priced by its public float), cls (its D1 class), the five yardsticks (y_*), the registered score
`vp` (median IV / price) and its siblings from the engine's own distribution (vp_p10 .. vp_p90) and from the draws (vp_mean, vp_cap50, vp_notv, pgt), `vp_point` (the point value at the P50 inputs),
x{h}_{bound} (the h-month excess return under each survivorship bound: the observed value, or the bound's value for an unobservable delisting; None where not formed), the fx analytics, the realised
fundamentals (R_*), and the market features (vol_1y, beta_1y, ret_1y, dvol_3m).  0.0 is a value."""
import argparse
import gzip
import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from . import analytics as A

BOUNDS = ("excluded", "minus100", "last_close")
HZ = (3, 6, 12, 18, 24, 36)
YARDS = ("yardstick_earnings_yield", "yardstick_fcf_yield", "yardstick_gross_profitability", "yardstick_return_on_capital", "yardstick_momentum_12_1")
YSHORT = ("ey", "fcfy", "gp", "roc", "mom")


def _g(d, *ks):
    for k in ks:
        if d is None:
            return None
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def row_of(r) -> dict:
    v = r.get("val") or {}
    fx = r.get("fx") or {}
    price = r.get("price")
    o = {"date": r["date"], "year": int(r["date"][:4]), "cik": r["cik"], "ticker": r.get("ticker"), "family": r.get("family"), "industry": r.get("industry"), "sector": r.get("sector"),
         "mcap": r.get("market_cap"), "price": price, "shares": r.get("shares"), "base_age_months": r.get("base_age_months"), "survivor": r.get("survivorship") is not None,
         "cls": (r.get("survivorship") or {}).get("class"), "surv_event_date": (r.get("survivorship") or {}).get("event_date"), "status": r["status"]}
    for y, s in zip(YARDS, YSHORT):
        o["y_" + s] = _num((r.get("score") or {}).get(y))
    iv = v.get("iv_ps") or {}
    if iv and price:
        for k in ("p10", "p25", "p50", "p75", "p90"):
            o["vp_" + k] = iv[k] / price
        o["vp"] = iv["p50"] / price
    o["vp_point"] = (v["iv_point_p50_inputs_ps"] / price) if v.get("iv_point_p50_inputs_ps") is not None and price else None
    o["tv_share_p50"] = v.get("tv_share_p50")
    exc, bnd = r.get("excess") or {}, r.get("bounds") or {}
    for h in HZ:
        b = bnd.get(str(h))
        for bd in BOUNDS:
            if b is not None:
                val = b.get(bd)
            else:
                val = exc.get(str(h))
            o[f"x{h}_{bd}"] = _num(val)
    d = fx.get("draws") or {}
    if price and d:
        o["vp_mean"] = d["full"]["mean"] / price
        o["vp_cap50"] = d["cap50"]["p50"] / price
        o["vp_notv"] = d["notv"]["p50"] / price
        o["vp_cap50_mean"] = d["cap50"]["mean"] / price
        o["vp_notv_mean"] = d["notv"]["mean"] / price
        o["pgt"] = d["full"].get("prob_above_price")
    o["vp_pt"] = (fx["point_p50_ps"] / price) if (fx.get("point_p50_ps") is not None and price) else None
    o["chain_ok"] = fx.get("chain_matches_engine")
    pv = fx.get("pv") or {}
    for k in ("share_explicit_1_5", "share_fade", "share_terminal"):
        o["pv_" + k] = pv.get(k)
    o["pv_N"] = pv.get("N")
    for k, x in (fx.get("swaps") or {}).items():
        o["sw_" + k] = (x / price) if (x is not None and price) else None
    for k, x in (fx.get("oracle") or {}).items():
        o["or_" + k] = (x / price) if (x is not None and price) else None
    ok = fx.get("oracle_k") or {}
    o["or_kg"], o["or_km"], o["or_kr"] = ok.get("g"), ok.get("m"), ok.get("rote")
    for k, x in (fx.get("p50_inputs") or {}).items():
        o["p50_" + k] = x
    for k, x in (fx.get("own_inputs") or {}).items():
        o["own_" + k] = x
    im = fx.get("implied") or {}
    for k in ("g1_imp", "g1_status", "m5_imp", "m5_status", "rote_imp", "rote_status", "m3_imp", "m3_eng", "g_avg3_imp", "g_avg3_eng"):
        o["im_" + k] = im.get(k)
    sv = fx.get("solvency") or {}
    for k, x in sv.items():
        o["sv_" + k] = x
    o["state_de_book"] = _g(v, "state", "de_book")
    o["state_growth_latest"] = _g(v, "state", "growth_latest")
    o["state_op_margin"] = _g(v, "state", "op_margin")
    o["coe"] = _g(v, "discount", "coe")
    o["wacc"] = _g(v, "discount", "wacc")
    o["rf"] = _g(v, "discount", "rf")
    o["beta_lev"] = _g(v, "discount", "beta_levered")
    real = r.get("fx_out")
    fam = r.get("family")
    if real and fam:
        p = A.oracle_paths(real, fam)
        g, m, ro = p["g"], p["m"], p["rote"]
        o["R_kg"], o["R_km"], o["R_kr"] = len(g), len(m), len(ro)
        for t in (1, 2, 3):
            o[f"R_g{t}"] = g.get(t)
            o[f"R_m{t}"] = m.get(t)
            o[f"R_rote{t}"] = ro.get(t)
        o["R_m5"] = m.get(5)
        o["R_gavg3"] = float(np.mean([g[t] for t in (1, 2, 3)])) if all(t in g for t in (1, 2, 3)) else None
    return o


def build(run_dir, dates=None):
    rows = []
    for f in sorted(Path(run_dir).glob("records_*.jsonl.gz")):
        d = f.name[len("records_"):-len(".jsonl.gz")]
        if dates is not None and d not in dates:
            continue
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r["status"] != "valued" or r.get("mcap_group") != ">=300M":
                    continue
                rows.append(row_of(r))
    return pd.DataFrame(rows)


def add_price_features(df, pf_path):
    with open(pf_path, "rb") as fh:
        pf = pickle.load(fh)["features"]
    for k in ("vol_1y", "beta_1y", "ret_1y", "dvol_3m"):
        df[k] = [(pf.get(t, {}).get(d, {}) or {}).get(k) if t is not None else None for t, d in zip(df["ticker"], df["date"])]
    return df


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--price-features", type=Path)
    a = ap.parse_args(argv)
    df = build(a.run_dir)
    if a.price_features:
        df = add_price_features(df, a.price_features)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(a.out)
    print("rows", len(df), "dates", df["date"].nunique())


if __name__ == "__main__":
    main()
