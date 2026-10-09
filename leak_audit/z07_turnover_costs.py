"""Item 2: turnover and costs of the engine's top / bottom quintile books (registered within-industry ranks), MAIN universe, 30 bp per trade (one-way: every buy and every sell costs 30 bp of the value traded).

1-MONTH HOLDING (holdout): rebalanced at each of the 9 month-ends; the book of date t is held to the next month-end's open.  The initial build (t = 0) is reported but excluded from the steady-state averages.
QUARTERLY-REBALANCED HOLDING (development; only the 20 quarter-ends exist, see z06): held 3 months.
12-MONTH HOLDING: every cohort is bought at T and sold 12 months later: each leg trades 1 in and 1 out (2 per leg, 4 for the long-short) = 4 x 30 bp = 120 bp per cohort, a flat charge (turnover 100% per cohort).
  Gross 12-month spreads: (a) the tradable plain EW top-minus-bottom quintile of the 12-month return; (b) the registered industry-neutral raw spread (H2 raw: ranks and returns demeaned within industry).
  Supplement (development only): the same book renewed ANNUALLY as one portfolio, where names that stay in the quintile are not traded: trades = sum |w_new - w_old| of the equal-weighted memberships 12 months apart.
Shorting costs, borrow fees and market impact beyond the flat 30 bp are NOT included."""
import numpy as np
import pandas as pd

from leak_audit import lib, libz
from rebuild_harness import gate1_metrics as gm

C = 0.003
S = pd.read_pickle(libz.OUT / "z06_series.pkl")
out = {}


def m(x):
    x = np.array([v for v in x if v == v], dtype=float)
    return float(x.mean()) if len(x) else float("nan")


def tstat(x):
    x = np.array([v for v in x if v == v], dtype=float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def rebal(pn, kind):
    """Per-rebalance records of the engine book: gross leg returns over the holding period, trades, cost, net."""
    recs = []
    for o in S[pn][("engine", kind)]:
        if not o["ok"]:
            continue
        gL = float(np.prod([1 + x for x in o["rL"]]) - 1)
        gS = float(np.prod([1 + x for x in o["rS"]]) - 1)
        cost = C * (o["trades_L"] + o["trades_S"])
        recs.append({"date": o["date"], "initial": o["initial"], "gross": gL - gS, "long": gL, "short": gS, "to_L": o.get("to_L"), "to_S": o.get("to_S"), "trades_L": o["trades_L"], "trades_S": o["trades_S"], "cost": cost,
                     "net": gL - gS - cost, "nL": o["nL"], "nS": o["nS"]})
    return pd.DataFrame(recs)


print("=== 1-month (holdout) and quarterly-rebalanced (development) books ===")
for pn, per, lab in (("hold", 12, "1-month holding, monthly rebalance"), ("dev", 4, "3-month holding, quarterly rebalance")):
    for kind in ("ew", "vw"):
        r = rebal(pn, kind)
        ss = r[~r.initial]
        key = f"{pn}|{kind}"
        out[key] = {"label": lab, "n_rebalances": int(len(r)), "n_steady": int(len(ss)),
                    "turnover_long_one_way_mean": m(ss.to_L), "turnover_short_one_way_mean": m(ss.to_S), "turnover_long_range": [float(ss.to_L.min()), float(ss.to_L.max())], "turnover_short_range": [float(ss.to_S.min()), float(ss.to_S.max())],
                    "gross_per_period_mean_all": m(r.gross), "gross_per_period_mean_steady": m(ss.gross), "cost_per_rebalance_mean": m(ss.cost), "net_per_period_mean_steady": m(ss.net),
                    "gross_annualised_steady": per * m(ss.gross), "cost_annualised": per * m(ss.cost), "net_annualised_steady": per * m(ss.net), "t_gross_steady": tstat(ss.gross), "t_net_steady": tstat(ss.net),
                    "initial_build_cost": float(r[r.initial].cost.iloc[0]) if r.initial.any() else None, "periods_per_year": per, "by_rebalance": r.drop(columns=["initial"]).to_dict("records")}
        o = out[key]
        print(f"{pn:4s} {kind}: {lab:38s} n={len(ss)} steady rebalances | one-way TO long {o['turnover_long_one_way_mean']:.2f} short {o['turnover_short_one_way_mean']:.2f} | gross/period {100*o['gross_per_period_mean_steady']:+.2f}% "
              f"cost {100*o['cost_per_rebalance_mean']:.2f}% net {100*o['net_per_period_mean_steady']:+.2f}% | annualised gross {100*o['gross_annualised_steady']:+.1f}% net {100*o['net_annualised_steady']:+.1f}% | t gross {o['t_gross_steady']:+.2f} net {o['t_net_steady']:+.2f}")

print("=== 12-month holding ===")
for pn, df0, score in (("hold", libz.load_hold(), "s_cfg"), ("dev", libz.load_dev(), "vp_mean")):
    df = df0[~df0.survivor.astype(bool)].reset_index(drop=True)
    df["q"] = libz.within_industry_quintile(df, score)
    for bound in ("last_close", "excluded"):
        xc = f"x12_{bound}"
        df[xc] = pd.to_numeric(df[xc], errors="coerce")
        plain, neutral, nrows = [], [], []
        for d, g in df.groupby("date"):
            g = g[g[xc].notna() & g.q.notna()]
            if len(g) < 25:
                continue
            plain.append(float(g[g.q == 4][xc].mean() - g[g.q == 0][xc].mean()))
            sc = g[score].to_numpy(dtype=float)
            sp, _ = gm._neutral_spread(sc, g[xc].to_numpy(dtype=float), [i if isinstance(i, str) else "unknown" for i in g.industry])
            neutral.append(sp)
            nrows.append(len(g))
        cost12 = 4 * C
        key = f"{pn}|12m|{bound}"
        out[key] = {"n_dates": len(plain), "gross_plain_ew_mean": m(plain), "gross_neutral_raw_mean": m(neutral), "cost_per_cohort": cost12, "net_plain": m(plain) - cost12, "net_neutral": m(neutral) - cost12,
                    "t_plain": tstat(plain), "share_dates_positive_plain": float(np.mean([x > 0 for x in plain])), "by_date_plain": plain, "by_date_neutral": neutral}
        print(f"{pn:4s} 12m ({bound:10s}) n_dates={len(plain)}: plain EW Q5-Q1 gross {100*m(plain):+.2f}pp -> net {100*(m(plain)-cost12):+.2f}pp (t of gross {tstat(plain):+.2f}); industry-neutral raw gross {100*m(neutral):+.2f}pp -> net {100*(m(neutral)-cost12):+.2f}pp")
    if pn == "dev":
        # annual renewal turnover from the memberships 12 months apart (equal-weighted, drift ignored)
        dates = sorted(df.date.unique())
        di = {d: i for i, d in enumerate(dates)}
        tr = []
        for d in dates:
            d2 = f"{int(d[:4]) + 1}{d[4:]}"
            if d2 not in di:
                continue
            res = {}
            for nm, qq in (("L", 4), ("S", 0)):
                a = set(df[(df.date == d) & (df.q == qq)].cik)
                b = set(df[(df.date == d2) & (df.q == qq)].cik)
                if not a or not b:
                    break
                res[nm] = sum(abs((1 / len(b) if k in b else 0) - (1 / len(a) if k in a else 0)) for k in a | b)
            if len(res) == 2:
                tr.append((d, res["L"], res["S"]))
        t_ = pd.DataFrame(tr, columns=["date", "trades_L", "trades_S"])
        cost_ann = C * (t_.trades_L + t_.trades_S)
        out["dev|12m|annual_renewal"] = {"n_pairs": int(len(t_)), "one_way_turnover_long": float((t_.trades_L / 2).mean()), "one_way_turnover_short": float((t_.trades_S / 2).mean()), "cost_per_year_mean": float(cost_ann.mean()),
                                         "net_plain_last_close": out["dev|12m|last_close"]["gross_plain_ew_mean"] - float(cost_ann.mean())}
        print(f"dev annual renewal (EW membership overlap, 12 months apart, {len(t_)} pairs): one-way turnover long {(t_.trades_L/2).mean():.2f} short {(t_.trades_S/2).mean():.2f}; cost {100*cost_ann.mean():.2f}pp a year "
              f"(vs the flat 120 bp) -> net plain {100*out['dev|12m|annual_renewal']['net_plain_last_close']:+.2f}pp")
libz.dump(out, "z07_turnover_costs.json")
