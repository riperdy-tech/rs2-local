"""Z item 1, step 4: where the M&A names sat in the score quintiles (registered within-industry quintiles), with market-cap and price-level profile.  Holdout (s_cfg) and development (vp_mean)."""
import numpy as np
import pandas as pd

from leak_audit import lib, libz

out = {}


def prof(d):
    if len(d) == 0:
        return {"n": 0}
    return {"n": int(len(d)), "mcap_median_M": float(d.mcap.median() / 1e6), "mcap_p25_M": float(d.mcap.quantile(.25) / 1e6), "price_median": float(d.price.median()), "share_price_lt10": float((d.price < 10).mean()),
            "share_price_lt5": float((d.price < 5).mean()), "share_mcap_lt1B": float((d.mcap < 1e9).mean()), "x12_last_close_mean": float(d.x12_last_close.astype(float).mean()), "x12_last_close_median": float(d.x12_last_close.astype(float).median()),
            "x12_excluded_n": int(d.x12_excluded.notna().sum())}


for name, df0, score in (("holdout", libz.load_hold(), "s_cfg"), ("dev", libz.load_dev(), "vp_mean")):
    F = pd.read_pickle(libz.OUT / f"z02_flags_{"hold" if name=="holdout" else name}.pkl")
    df = df0.merge(F, on=["date", "cik"], how="left").reset_index(drop=True)
    for c in ("x12_last_close", "x12_excluded"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["q"] = libz.within_industry_quintile(df, score)
    df["census"] = df.survivor.astype(bool)
    res = {}
    for uni, d in (("ALL (census incl.)", df), ("MAIN (ex-census)", df[~df.census])):
        for tier in ("M1", "M2", "M3"):
            ma = d[d[tier].fillna(False).astype(bool) & d.q.notna()]
            rest = d[~d[tier].fillna(False).astype(bool) & d.q.notna()]
            tab = {}
            for q in range(5):
                tab[f"Q{q+1}"] = {"M&A": prof(ma[ma.q == q]), "other": prof(rest[rest.q == q])}
            res[f"{uni} | {tier}"] = {"n_ma": int(len(ma)), "n_ma_ineligible_for_quintiles": int((d[tier].fillna(False).astype(bool) & d.q.isna()).sum()), "share_of_ma_by_quintile": {f"Q{q+1}": float((ma.q == q).mean()) for q in range(5)},
                                      "share_of_quintile_that_is_ma": {f"Q{q+1}": float(d[d.q == q][tier].fillna(False).astype(bool).mean()) for q in range(5)}, "by_quintile": tab,
                                      "ma_all": prof(ma), "other_all": prof(rest)}
    out[name] = res
    print("=====", name, len(df), "eligible for quintiles", int(df.q.notna().sum()))
    for k, v in res.items():
        print(f"{k:32s} n_ma={v['n_ma']:5d} share of M&A by quintile " + " ".join(f"{x:.2f}" for x in v["share_of_ma_by_quintile"].values()) + " | share of quintile that is M&A " + " ".join(f"{x:.3f}" for x in v["share_of_quintile_that_is_ma"].values()))
        print(f"{'':32s} M&A all: mcap med ${v['ma_all'].get('mcap_median_M', float('nan')):.0f}M price med ${v['ma_all'].get('price_median', float('nan')):.1f} <$10 {v['ma_all'].get('share_price_lt10', float('nan')):.2f}  | other: mcap med ${v['other_all']['mcap_median_M']:.0f}M price med ${v['other_all']['price_median']:.1f} <$10 {v['other_all']['share_price_lt10']:.2f}")
libz.dump(out, "z04_ma_quintiles.json")
