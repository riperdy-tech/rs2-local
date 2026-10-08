"""F3 (IV attribution and terminal-value variants), F4 (distress strata), F5 (factor decomposition), F6 (the oracle valuation) and F8 (the expectation gap).  See analysis_f for the conventions."""
import math

import numpy as np
import pandas as pd

from . import fxm
from .analysis_f import BOUNDS, FAMILIES, HZ, Y5, md, ranked_within, render_metric, horizon_table, score_compare, scopes_of

G_LO, G_HI = -0.60, 1.50          # the grids of the implied-growth solve (analytics.G_GRID_OP) and of the margin solve
M_LO, M_HI = -0.50, 0.80
GF_LO, GF_HI = -0.50, 1.00        # financial grids (tangible-book growth, ROTE target)
RF_LO, RF_HI = -0.30, 0.60
G_ANCHOR = 0.0375


def _q(s, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    s = s.dropna()
    return [float(s.quantile(q)) for q in qs] if len(s) else [float("nan")] * len(qs)


def _f(x, nd=3):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


# ---- F3 --------------------------------------------------------------------------------------------------------------------------------------------

def f3(df, out):
    L = ["# F3. IV attribution and terminal-value variants", ""]
    # (a) where the value comes from: PV shares of the point value at the P50 inputs
    rows = []
    for fam in FAMILIES + ("all",):
        s = df if fam == "all" else df[df["family"] == fam]
        for lab, col in (("explicit years 1-5", "pv_share_explicit_1_5"), ("fade years 6..N", "pv_share_fade"), ("terminal value", "pv_share_terminal")):
            q = _q(s[col])
            rows.append([fam, lab] + [_f(x, 3) for x in q] + [_f(float(s[col].mean()), 3), int(s[col].notna().sum())])
    L += ["## (a) PV share of the enterprise value at the P50 inputs (operating and commodity: of EV; financial: of the tangible book plus the PV of the excess returns, so a share can be negative or above one)", "",
          "Horizon N is the length of the growth-decay curve (the number of explicit plus fade years); the terminal value is the funded-growth perpetuity after year N.", ""]
    L += md(["family", "leg", "P10", "P25", "P50", "P75", "P90", "mean", "n"], rows) + [""]
    nq = df.groupby("family")["pv_N"].describe()[["min", "50%", "max"]]
    L += ["Horizon N by family (years): " + "; ".join(f"{f}: min {int(r['min'])}, median {int(r['50%'])}, max {int(r['max'])}" for f, r in nq.iterrows()), ""]
    # (b) which judgment input moves the cross-section of ln(IV/price)
    d = df[(df["vp_pt"] > 0)].copy()
    d["y"] = np.log(d["vp_pt"])
    grp = ["date", "family"]
    gm_ = d.groupby(grp)["y"].transform("mean")
    d["ydm"] = d["y"] - gm_
    L += ["## (b) Which input drives the cross-sectional variance of ln(IV / price)", "",
          "Point value at the P50 inputs (the engine's own chain, verified equal to the engine's point value on every name; `chain_matches_engine`). One input at a time is swapped to (i) the population P50 of that input "
          "(the median, over the date's prepared names of market cap >= $300M in the family, of the prior's P50) or (ii) the company's own state (latest revenue growth, current operating margin, own 3-year ROIC; "
          "financial: latest tangible-book growth, ROTE). `variance removed` = 1 - Var(ln swapped) / Var(ln base); `covariance share` = Cov(ln base - ln swapped, ln base) / Var(ln base). Variances are within date and family "
          "(each date-family mean removed), pooled over dates.", ""]
    att = {}
    for fam in FAMILIES:
        s = d[d["family"] == fam]
        keys = ("g1", "rote_target") if fam == "financial" else ("g1", "margin_target", "ronic")
        names = [f"{kind}_{k}" for kind in ("pop", "own") for k in keys] + ["pop_all", "own_all"]
        ok = np.ones(len(s), dtype=bool)
        for nme in names:
            col = "sw_" + nme
            ok &= (s[col] > 0).to_numpy() if col in s else False
        s = s[ok]
        if len(s) < 200:
            continue
        v0 = float((s["ydm"] ** 2).mean())
        rows = []
        att[fam] = {"var_base": v0, "n": int(len(s))}
        for nme in names:
            ys = np.log(s["sw_" + nme])
            ysdm = ys - ys.groupby([s["date"], s["family"]]).transform("mean")
            edm = s["ydm"] - ysdm
            red = 1.0 - float((ysdm ** 2).mean()) / v0
            cs = float((edm * s["ydm"]).mean()) / v0
            rows.append([nme, _f(red, 3), _f(cs, 3)])
            att[fam][nme] = {"variance_removed": red, "cov_share": cs}
        L += [f"**{fam}** (name-dates {len(s)}; within-date variance of ln(IV/price) at the P50 point {_f(v0, 3)})", ""] + md(["swap", "variance removed", "covariance share"], rows) + [""]
    # (c) IV against price dispersion (total dollars, comparable across names)
    dd = d.copy()
    dd["lnIV"] = np.log(dd["vp_pt"] * dd["mcap"])
    dd["lnP"] = np.log(dd["mcap"])
    for c in ("lnIV", "lnP"):
        dd[c + "_dm"] = dd[c] - dd.groupby(grp)[c].transform("mean")
    vIV, vP = float((dd["lnIV_dm"] ** 2).mean()), float((dd["lnP_dm"] ** 2).mean())
    cov = float((dd["lnIV_dm"] * dd["lnP_dm"]).mean())
    L += ["## (c) Dispersion of the engine's total equity value against that of the market capitalisation (within date and family, point value at P50)", "",
          f"Var(ln IV) = {_f(vIV)}; Var(ln market cap) = {_f(vP)}; Cov = {_f(cov)}; correlation = {_f(cov / math.sqrt(vIV * vP))}; Var(ln IV/price) = {_f(vIV + vP - 2 * cov)}.", ""]
    out["F3_attribution"] = {"by_family": att, "var_ln_iv": vIV, "var_ln_mcap": vP, "cov": cov}
    # (d) terminal-value variants as ranking variables
    scores = [("registered: median of the draws", "vp"), ("terminal leg capped at 50% of EV", "vp_cap50"), ("terminal leg removed (explicit + fade only)", "vp_notv"),
              ("mean, capped", "vp_cap50_mean"), ("mean, terminal removed", "vp_notv_mean")]
    L += ["## (d) Terminal-value variants (draw by draw; cap: the PV of the terminal leg is at most the PV of the explicit and fade years, i.e. at most 50% of the enterprise value; financial: of tangible book plus excess)", ""]
    L2, res = score_compare(df, scores, hs=(6, 12, 24, 36), title="F3 variants")
    out["F3_variants"] = {f"{k[0]}|{k[1]}": v for k, v in res.items()}
    res12 = {}
    for lab, col in scores[:3]:
        res12[col] = horizon_table(df[df[col].notna()], col, hs=(12,))
    for lab, col in scores[:3]:
        L += render_metric(res12[col], "spread_resid", hs=(12,), title=f"{lab}: residual spread by valuation year, 12 months, pp")
    out["F3_variants_by_year"] = {col: {f"{h}|{s}": v for (h, s), v in r.items()} for col, r in res12.items()}
    return L + L2


# ---- F4 --------------------------------------------------------------------------------------------------------------------------------------------

def _rank_by_date(df, col):
    return df.groupby("date")[col].transform(fxm.rank_nan)


def solvency_frame(df):
    """The solvency score from point-in-time data at T: current ratio, net debt / EBITDA (EBIT where D&A is not filed), EBIT / interest, the sign of operating cash flow and the naive Merton distance to
    default (Bharath-Shumway: sigma_V = E/(E+D) sigma_E + D/(E+D)(0.05 + 0.25 sigma_E), drift = the past-year return, one year).  Each component is turned into its percentile rank on the date (higher =
    safer); the score is the mean of the available ranks, needed for at least 3 of 5 components; terciles by date (T1 = the least solvent third)."""
    d = df.copy()
    cl = d["sv_current_liabilities"]
    d["s_cur"] = np.where(cl > 0, d["sv_current_assets"] / cl, np.nan)
    debt = d["sv_debt"] + d["sv_finance_leases"].fillna(0.0)
    nd = debt - d["sv_cash"] - d["sv_st_investments"].fillna(0.0)
    ebitda = d["sv_operating_income"] + d["sv_da"].fillna(0.0)
    lev = np.where(d["sv_operating_income"].isna() | nd.isna(), np.nan, np.where(ebitda > 0, nd / ebitda.where(ebitda > 0), np.where(nd > 0, np.inf, -np.inf)))
    d["s_lev"] = -lev
    ie = d["sv_interest_expense"]
    d["s_cov"] = np.where(d["sv_operating_income"].isna(), np.nan, np.where(ie > 0, d["sv_operating_income"] / ie.where(ie > 0), np.where(ie == 0, np.inf, np.nan)))
    d["s_ocf"] = np.where(d["sv_ocf"].isna(), np.nan, (d["sv_ocf"] > 0).astype(float))
    E, D, sE, mu = d["mcap"], debt, d["vol_1y"], d["ret_1y"]
    sV = E / (E + D) * sE + D / (E + D) * (0.05 + 0.25 * sE)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = (np.log((E + D) / D) + mu - 0.5 * sV ** 2) / sV
    d["s_dd"] = np.where(D.isna(), np.nan, np.where(D <= 0, np.inf, np.where(sE.isna() | mu.isna(), np.nan, dd)))
    comps = ["s_cur", "s_lev", "s_cov", "s_ocf", "s_dd"]
    for c in comps:
        d["r_" + c] = _rank_by_date(d, c)
    R = d[["r_" + c for c in comps]]
    d["solv_n"] = R.notna().sum(axis=1)
    d["solv"] = np.where(d["solv_n"] >= 3, R.mean(axis=1), np.nan)
    d["solv_rank"] = _rank_by_date(d, "solv")
    d["tercile"] = np.where(d["solv"].isna(), np.nan, np.minimum((d["solv_rank"] * 3).astype(float), 2.999).astype(float) // 1 + 1)
    d["solv_rank_fam"] = d.groupby(["date", "family"])["solv"].transform(fxm.rank_nan)
    d["tercile_fam"] = np.where(d["solv"].isna(), np.nan, np.minimum((d["solv_rank_fam"] * 3), 2.999) // 1 + 1)
    return d


def f4(df, out):
    d = solvency_frame(df)
    L = ["# F4. Distress strata", "",
         "Solvency score at T (point-in-time data only): the mean percentile rank, on the date, of five components, needing at least three: current ratio; net debt / EBITDA (EBIT where D&A is not filed; "
         "negative EBITDA with positive net debt ranks last); EBIT / interest expense; the sign of operating cash flow; and the naive distance to default from the market value of equity, the debt and the one-year "
         "daily-return volatility and drift. Terciles by date: T1 = the least solvent third. Census names (companies that left after T, priced by public float) carry no daily-price components.", ""]
    cov = d.groupby("family").apply(lambda g: pd.Series({"names": len(g), "scored (>= 3 components)": g["solv"].notna().mean(), "components median": g["solv_n"].median()}))
    L += md(["family", "name-dates", "share scored", "median components"], [[f, int(r["names"]), _f(r["scored (>= 3 components)"], 3), r["components median"]] for f, r in cov.iterrows()]) + [""]
    comp_cov = {c: float(d[c].replace([np.inf, -np.inf], np.nan).notna().mean() + (d[c].isin([np.inf, -np.inf])).mean()) for c in ("s_cur", "s_lev", "s_cov", "s_ocf", "s_dd")}
    L += ["Component coverage (share of name-dates with a value): " + ", ".join(f"{k} {v:.2f}" for k, v in comp_cov.items()), ""]
    out["F4"] = {"coverage": {f: {"names": int(r["names"]), "scored": float(r["scored (>= 3 components)"])} for f, r in cov.iterrows()}, "component_coverage": comp_cov}
    sc = d[d["tercile"].notna()]
    # (a) the engine's metrics inside each tercile
    for h in (6, 12, 24):
        rows = []
        for t, lab in ((1, "T1 least solvent"), (2, "T2"), (3, "T3 most solvent")):
            sub = sc[sc["tercile"] == t]
            r = fxm.metric_row(sub, "vp", h)
            out["F4"][f"tercile{t}|{h}"] = r
            rows.append([lab, fxm.triple(r, "spread_resid"), fxm.triple(r, "ic"), fxm.triple(r, "spread_raw"), r["excluded"]["n_obs"], _f(float(sub["vp"].median()), 2)])
        r = fxm.metric_row(sc, "vp", h)
        rows.append(["all scored", fxm.triple(r, "spread_resid"), fxm.triple(r, "ic"), fxm.triple(r, "spread_raw"), r["excluded"]["n_obs"], _f(float(sc["vp"].median()), 2)])
        r = fxm.metric_row(sc[sc["tercile"] >= 2], "vp", h)
        rows.append(["T2+T3 (bottom tercile set aside, diagnostic only)", fxm.triple(r, "spread_resid"), fxm.triple(r, "ic"), fxm.triple(r, "spread_raw"), r["excluded"]["n_obs"], _f(float(sc[sc["tercile"] >= 2]["vp"].median()), 2)])
        L += [f"## (a) IV/price ranking inside each solvency tercile, {h}-month excess return (excl / -100% / last)", ""] + md(["stratum", "residual spread pp", "IC x 100", "raw neutral spread pp", "name-dates (excl)", "median IV/price"], rows) + [""]
    # (b) value-trap grid: mean excess return by IV/price quintile (date-wide) and tercile
    L += ["## (b) Mean 12-month excess return (%) by IV/price quintile of the date (rows, Q1 = most expensive) and solvency tercile (columns)", ""]
    sc = sc.copy()
    sc["vq"] = np.minimum((_rank_by_date(sc, "vp") * 5).astype(float), 4.999) // 1 + 1
    grid = {}
    for b in BOUNDS:
        x = f"x12_{b}"
        t = sc.groupby(["vq", "tercile"])[x].agg(["mean", "count"]).unstack("tercile")
        grid[b] = t
        rows = []
        for q in range(1, 6):
            rows.append([f"Q{q}"] + [(_f(100 * t["mean"].loc[q, k], 1) + f" (n {int(t['count'].loc[q, k])})") if (q in t.index and k in t["mean"].columns) else "n/a" for k in (1.0, 2.0, 3.0)])
        top_bot = [100 * (t["mean"].loc[5, k] - t["mean"].loc[1, k]) if (5 in t.index and 1 in t.index and k in t["mean"].columns) else float("nan") for k in (1.0, 2.0, 3.0)]
        rows.append(["Q5 - Q1 (pp)"] + [_f(v, 1) for v in top_bot])
        L += [f"bound: {fxm.BLABEL[b]}", ""] + md(["IV/price quintile", "T1 least solvent", "T2", "T3 most solvent"], rows) + [""]
        out["F4"][f"grid|{b}"] = {"top_minus_bottom_pp": top_bot}
    # (c) where the census failures sit
    sv = d[d["survivor"]].copy()
    sv["ev_date"] = pd.to_datetime(sv["surv_event_date"], errors="coerce")
    sv["h_end"] = pd.to_datetime(sv["date"]) + pd.DateOffset(months=12)
    sv["in12"] = sv["ev_date"] <= sv["h_end"]
    bk = {"bankruptcy": "bankruptcy-class", "bankruptcy_no_exit_record": "bankruptcy-class", "delisted_other": "other distress-type exit", "deregistered_other": "other distress-type exit",
          "acquisition_completed": "acquisition", "acquisition_weak": "acquisition"}
    sv["cls_g"] = sv["cls"].map(bk).fillna("other")
    d2 = d.copy()
    d2["vq"] = np.minimum((_rank_by_date(d2, "vp") * 5).astype(float), 4.999) // 1 + 1
    sv["vq"] = d2.loc[sv.index, "vq"]
    ntot = len(d)
    L += ["## (c) Where the companies that left sit (census names: no price at T in D5, an exit event in D1 after T, priced by public float)", "",
          f"Census names in the panel: {len(sv)} of {ntot} name-dates ({100 * len(sv) / ntot:.1f}%); inside the 12-month horizon: {int(sv['in12'].sum())}.", ""]
    rows = []
    for g in ("bankruptcy-class", "other distress-type exit", "acquisition", "other"):
        s = sv[(sv["cls_g"] == g) & sv["in12"]]
        row = [g, len(s)]
        for t in (1.0, 2.0, 3.0):
            row.append(int((s["tercile"] == t).sum()))
        row.append(int(s["tercile"].isna().sum()))
        for q in (1, 2, 3, 4, 5):
            row.append(int((s["vq"] == q).sum()))
        rows.append(row)
    L += md(["exit class (event within 12 months)", "n", "T1", "T2", "T3", "no solvency score", "IV/P Q1 (dearest)", "Q2", "Q3", "Q4", "Q5 (cheapest)"], rows) + [""]
    # failure incidence per tercile (bankruptcy-class inside 12 months) over all scored names
    inc = []
    allfail = sv[(sv["cls_g"] == "bankruptcy-class") & sv["in12"]]
    for t in (1.0, 2.0, 3.0):
        n_all = int((d["tercile"] == t).sum())
        n_f = int((allfail["tercile"] == t).sum())
        inc.append([f"T{int(t)}", n_all, n_f, _f(100 * n_f / max(n_all, 1), 2)])
    L += ["Bankruptcy-class exits inside 12 months per scored name-date:", ""] + md(["tercile", "name-dates", "failures", "% of name-dates"], inc) + [""]
    inc2 = []
    for q in (1, 2, 3, 4, 5):
        n_all = int((d2["vq"] == q).sum())
        n_f = int((allfail["vq"] == q).sum())
        inc2.append([f"Q{q}", n_all, n_f, _f(100 * n_f / max(n_all, 1), 2)])
    L += ["The same by IV/price quintile of the date (Q1 dearest, Q5 cheapest):", ""] + md(["quintile", "name-dates", "failures", "% of name-dates"], inc2) + [""]
    out["F4"]["failures_by_tercile"] = inc
    out["F4"]["failures_by_vq"] = inc2
    # (d) the engine's own IV/price of the failures
    if len(allfail):
        L += [f"Median IV/price of the bankruptcy-class exits inside 12 months: {_f(float(allfail['vp'].median()), 2)} (all names: {_f(float(d['vp'].median()), 2)}); share with IV/price above 1: "
              f"{_f(float((allfail['vp'] > 1).mean()), 2)} (all names: {_f(float((d['vp'] > 1).mean()), 2)}).", ""]
    return L


# ---- F5 --------------------------------------------------------------------------------------------------------------------------------------------

def f5(df, out, n_boot=0):
    d = df.copy()
    d["c_size"] = np.log(d["mcap"])
    d["c_beta"] = d["beta_1y"]
    d["c_lev"] = d["sv_debt"] / d["sv_total_assets"]
    d["c_liq"] = np.log(d["dvol_3m"].where(d["dvol_3m"] > 0))
    for c in ("c_size", "c_beta", "c_lev", "c_liq"):
        d[c] = d[c].replace([np.inf, -np.inf], np.nan)
    layers = [("five yardsticks (the B1 specification)", [], False), ("+ size (ln market cap)", ["c_size"], False), ("+ beta (1y, daily, vs SPY)", ["c_size", "c_beta"], False),
              ("+ leverage (debt / total assets)", ["c_size", "c_beta", "c_lev"], False), ("+ liquidity (ln median daily dollar volume, 3m)", ["c_size", "c_beta", "c_lev", "c_liq"], False),
              ("+ family dummies", ["c_size", "c_beta", "c_lev", "c_liq"], True)]
    L = ["# F5. Factor decomposition", "",
         "Pooled regression of the h-month excess return on the engine's percentile rank, the five yardstick ranks and the added controls' percentile ranks (a missing control enters at rank 0.5 with an indicator), with "
         "date and industry effects absorbed; date-clustered t. Beside it, the B2-style residual spread of the engine's rank after the yardsticks AND the controls.", ""]
    res = {}
    for h in (12, 24):
        rows = []
        for lab, ctrl, fam in layers:
            row = [lab]
            for b in BOUNDS:
                c = fxm.pooled_coef(d, d["vp"], h, b, Y5, ctrl, fam)
                res[f"{h}|{lab}|{b}"] = c
                row.append("n/a" if c is None else f"{c['beta']:+.4f} (t {c['t']:+.1f})")
            sp = []
            for b in BOUNDS:
                s = fxm.summarize(fxm.per_date(d, "vp", h, b, Y5, extra_resid_cols=ctrl), h)
                res[f"{h}|{lab}|{b}|spread"] = s
                sp.append(f"{100 * s['spread_resid']:+.2f}" + ("*" if fxm.sig(s, "spread_resid") else ""))
            row.append(" / ".join(sp))
            rows.append(row)
        L += [f"## {h}-month horizon", ""] + md(["controls added"] + [f"engine coefficient, {fxm.BLABEL[b]}" for b in BOUNDS] + ["residual spread pp (excl / -100% / last)"], rows) + [""]
    # what the engine rank loads on
    rows = []
    for lab, col in (("ey (earnings yield)", "y_ey"), ("fcfy", "y_fcfy"), ("gross profitability", "y_gp"), ("return on capital", "y_roc"), ("momentum 12-1", "y_mom"), ("size", "c_size"), ("beta", "c_beta"),
                     ("leverage", "c_lev"), ("liquidity", "c_liq")):
        cs = []
        for dt, g in d.groupby("date"):
            ok = g[col].notna() & g["vp"].notna()
            if ok.sum() > 50:
                cs.append(float(np.corrcoef(fxm.pct_rank(g.loc[ok, "vp"]), fxm.pct_rank(g.loc[ok, col]))[0, 1]))
        rows.append([lab, _f(float(np.mean(cs)), 3) if cs else "n/a"])
    fam_share = d.groupby("family")["vp"].median()
    L += ["## What the engine's IV/price rank correlates with (mean per-date Spearman)", ""] + md(["variable", "mean rank correlation with IV/price"], rows) + [""]
    L += ["Median IV/price by family: " + ", ".join(f"{k} {v:.2f}" for k, v in fam_share.items()), ""]
    out["F5"] = res
    return L


# ---- F6 --------------------------------------------------------------------------------------------------------------------------------------------

def f6(df, out):
    d = df.copy()
    d["or_main"] = np.where(d["family"] == "financial", d["or_rote"], d["or_both"])
    d["or_partial_a"] = np.where(d["family"] == "financial", d["or_tbv_growth_only"], d["or_growth_only"])
    d["or_partial_b"] = np.where(d["family"] == "financial", d["or_rote"], d["or_margin_only"])
    d["naive"] = d["sw_own_all"]
    d["or_main"] = d["or_main"].where(d["or_main"].notna())
    common = d[d["or_main"].notna() & d["naive"].notna() & d["vp"].notna() & d["vp_pt"].notna()].copy()
    L = ["# F6. The oracle valuation", "",
         "**What is replaced.** The frozen engine's chain (`valuation.engine_operating.operating_chain` / `engine_financial.financial_chain`, copied with per-year overrides and checked equal to the engine's point value "
         "at the P50 inputs on every name) is fed, for the years after the base year that have been reported (first-reported annual figures, consecutive fiscal years, prices not used anywhere in the valuation):",
         "", "- operating and commodity: the year-t revenue growth (realised revenue / prior-year realised revenue - 1; year 1 against the base-year revenue as first reported) and the year-t operating margin (operating income / "
         "revenue), for t = 1..K where K is the number of consecutive reported years (up to 8); when K >= 5 the long-run margin (the margin level five years on, which also prices growth reinvestment and the terminal) is the "
         "realised year-5 margin; for K < 5 it stays the prior's P50. After year K the engine's own P50 path continues (its growth-decay year-t growth and its margin-path year-t margin: the jump, if any, is not smoothed). "
         "The return on new capital (ROIC level five years on), the discount rate, the balance sheet, the terminal rules and the roll-forward are the engine's own.",
         "- financial: the return that enters year t's residual income is the realised ROTE (net income / average tangible common equity) for t = 1..K; tangible-book growth stays the engine's P50 path "
         "(`or_tbv_growth_only` replaces only the growth; `or_rote_tbv` both).",
         "- the value is the point value (no draws) at those inputs, per share, over the price: so the comparison with the engine uses the point value at the P50 inputs (`vp_pt`) as well as the registered median "
         "of the draws (`vp`).", "- naive inputs: the same chain with growth, margin and ROIC (financial: tangible-book growth, ROTE) set to the company's own latest state.", "",
         f"Common sample (a name with an oracle value, a naive value and the registered value): {len(common)} of {len(d)} name-dates ({100 * len(common) / len(d):.0f}%); realised years K (revenue growth path) median "
         f"{int(common['or_kg'].median())}, by valuation year: " + ", ".join(f"{y} {common[common.year == y]['or_kg'].median():.0f}" for y in sorted(common["year"].unique())), ""]
    scores = [("naive inputs (own state)", "naive"), ("engine P50, median of draws (registered)", "vp"), ("engine P50, point value", "vp_pt"), ("ORACLE (growth and margin / ROTE)", "or_main"),
              ("oracle: growth (financial: tangible-book growth) only", "or_partial_a"), ("oracle: margin (financial: ROTE) only", "or_partial_b")]
    res = {}
    for h in (6, 12, 24, 36):
        L2, r = score_compare(common, scores, hs=(h,), title="F6, common sample,")
        L += L2
        res.update({f"{k[0]}|{k[1]}": v for k, v in r.items()})
    # by valuation year at 12 months, and by family
    for lab, col in scores[1:4]:
        rr = horizon_table(common, col, hs=(12,))
        L += render_metric(rr, "spread_resid", hs=(12,), title=f"{lab}: residual spread by valuation year, 12 months, pp")
        res[f"by_year|{col}"] = {f"{h}|{s}": v for (h, s), v in rr.items()}
    for fam in FAMILIES:
        sub = common[common["family"] == fam]
        if len(sub) < 500:
            continue
        L2, r = score_compare(sub, [scores[0], scores[1], scores[3]], hs=(12,), title=f"F6, {fam} only,")
        L += L2
        res.update({f"{fam}|{k[0]}|{k[1]}": v for k, v in r.items()})
    rows = []
    for lab, col in scores:
        row = [lab]
        for h in (12, 24):
            for b in BOUNDS:
                c = fxm.pooled_coef(common, common[col], h, b, Y5)
                row.append("n/a" if c is None else f"{c['beta']:+.3f} (t {c['t']:+.1f})")
        rows.append(row)
    L += ["**Pooled coefficient on the score's rank (date and industry effects, five yardsticks), common sample**", ""] + md(["score"] + [f"{h}m {fxm.BLABEL[b]}" for h in (12, 24) for b in BOUNDS], rows) + [""]
    # the oracle with >= 3 realised years only (the deep oracle), 12 and 24 months
    deep = common[common["or_kg"] >= 3]
    L2, r = score_compare(deep, scores, hs=(12, 24), title="F6, names with at least 3 realised years,")
    L += L2
    res.update({f"deep|{k[0]}|{k[1]}": v for k, v in r.items()})
    # how far the oracle moves the value
    pos = common[(common["or_main"] > 0) & (common["vp_pt"] > 0)]
    mv = np.log(pos["or_main"] / pos["vp_pt"])
    cc = float(np.corrcoef(np.log(pos["or_main"]), np.log(pos["vp_pt"]))[0, 1])
    L += [f"ln(oracle value / engine point value) over {len(pos)} name-dates with both positive: P10 {mv.quantile(.1):+.2f}, P25 {mv.quantile(.25):+.2f}, median {mv.median():+.2f}, P75 {mv.quantile(.75):+.2f}, "
          f"P90 {mv.quantile(.9):+.2f}; correlation of ln(oracle/price) with ln(engine point/price) {cc:.2f}.", ""]
    out["F6"] = res
    return L


# ---- F8 --------------------------------------------------------------------------------------------------------------------------------------------

def _saturate(imp, status, lo, hi):
    """The implied value, or the grid end where no root exists (annotate, never drop): value above the price on the whole grid -> the lower end; below everywhere -> the upper end."""
    return np.where(imp.notna(), imp, np.where(status == "no_root_value_above_price", lo, np.where(status == "no_root_value_below_price", hi, np.nan)))


def gap_frame(df):
    d = df.copy()
    fin = d["family"] == "financial"
    gT = np.minimum(d["rf"], G_ANCHOR)
    D = (d["im_g_avg3_eng"] - gT) / (d["p50_g1"] - gT)
    d["g1_sat"] = np.where(fin, _saturate(d["im_g1_imp"], d["im_g1_status"], GF_LO, GF_HI), _saturate(d["im_g1_imp"], d["im_g1_status"], G_LO, G_HI))
    d["g1_gap"] = d["p50_g1"] - d["g1_sat"]
    d["gT"], d["Dfac"] = gT, D
    d["g_avg3_imp_sat"] = gT + (d["g1_sat"] - gT) * D
    d["g_avg3_gap"] = d["im_g_avg3_eng"] - d["g_avg3_imp_sat"]
    d["m5_sat"] = _saturate(d["im_m5_imp"], d["im_m5_status"], M_LO, M_HI)
    d["m5_gap"] = d["p50_margin_target"] - d["m5_sat"]
    d["rote_sat"] = _saturate(d["im_rote_imp"], d["im_rote_status"], RF_LO, RF_HI)
    d["rote_gap"] = d["p50_rote_target"] - d["rote_sat"]
    d["gap_second"] = np.where(fin, d["rote_gap"], d["m5_gap"])
    d["r_gap_g"] = ranked_within(d, "g_avg3_gap", ("date", "family"))
    d["r_gap_2"] = ranked_within(d, "gap_second", ("date", "family"))
    d["gap_score"] = d[["r_gap_g", "r_gap_2"]].mean(axis=1, skipna=False)
    d["gap_score"] = d["gap_score"].where(d["gap_score"].notna())
    # naive own-state analogues (price-implied against what the company has been doing)
    d["naive_g_gap"] = np.where(fin, np.nan, d["own_g1"] - d["g1_sat"])
    d["status_g"] = d["im_g1_status"]
    return d


def _fe_reg(y, Xs, dates, cluster=None):
    """OLS of y on the columns of Xs with date effects absorbed; (coefficients, date-clustered se, n, R2 within)."""
    from rebuild_harness import gate1_v2 as v2m
    ok = np.isfinite(y) & np.all(np.isfinite(Xs), axis=1)
    y, Xs, dt = y[ok], Xs[ok], np.asarray(dates)[ok]
    if len(y) < 200:
        return None
    codes = v2m._codes(dt.tolist())
    Z = v2m.demean(np.column_stack([y, Xs]), [codes])
    yt, Xt = Z[:, 0], Z[:, 1:]
    beta, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
    u = yt - Xt @ beta
    se = [v2m.cluster_se(Xt, u, codes, j) for j in range(Xt.shape[1])]
    r2 = 1.0 - float((u ** 2).sum() / (yt ** 2).sum())
    return beta, se, int(len(y)), r2


def f8(df, out):
    d = gap_frame(df)
    L = ["# F8. The expectation gap", "",
         "For each name the frozen engine's point chain is run with ONE input varied and the others at their P50 (the engine's own mechanics), and the input that makes the per-share value equal the price is solved for "
         "(a grid scan for the sign change nearest the P50, then 60 bisections): the year-1 revenue growth `g1` (operating and commodity: revenue growth; financial: tangible-book growth), whose year 1-3 path follows the "
         "engine's growth-decay curve, and the long-run (year-5) operating margin (financial: the ROTE target). gap = the engine's P50 minus the price-implied value of the same quantity. Where the price is outside the "
         "solve grid (growth -60% .. +150%, margin -50% .. +80%, financial growth -50% .. +100%, ROTE -30% .. +60%) the implied value is set to the grid end and the name is kept (annotated in `*_status`).", ""]
    st = d.groupby("family")["im_g1_status"].value_counts(normalize=True).unstack().fillna(0.0)
    L += ["Solve status of the growth solve (share of name-dates):", ""] + md(["family"] + list(st.columns), [[f] + [_f(float(r[c]), 3) for c in st.columns] for f, r in st.iterrows()]) + [""]
    st2 = d.groupby("family")["im_m5_status"].value_counts(normalize=True).unstack().fillna(0.0)
    L += ["Solve status of the margin solve (operating and commodity):", ""] + md(["family"] + list(st2.columns), [[f] + [_f(float(r[c]), 3) for c in st2.columns] for f, r in st2.iterrows()]) + [""]
    q = d.groupby("family").apply(lambda g: pd.Series({"g1 P50 (engine) median": g["p50_g1"].median(), "g1 implied (sat.) median": g["g1_sat"].median(), "gap median": g["g1_gap"].median(),
                                                      "m5 / ROTE P50 median": (g["p50_margin_target"] if g.name != "financial" else g["p50_rote_target"]).median(),
                                                      "m5 / ROTE implied median": (g["m5_sat"] if g.name != "financial" else g["rote_sat"]).median()}))
    L += ["Medians:", ""] + md(["family"] + list(q.columns), [[f] + [_f(float(r[c]), 3) for c in q.columns] for f, r in q.iterrows()]) + [""]
    # the gap as a ranking variable
    scores = [("expectation gap score (mean rank of growth gap and margin / ROTE gap, within family)", "gap_score"), ("growth gap alone (years 1-3 average), within family", "r_gap_g"),
              ("margin / ROTE gap alone, within family", "r_gap_2"), ("registered IV/price", "vp")]
    sub = d[d["gap_score"].notna()].copy()
    L2, res = score_compare(sub, scores, hs=(6, 12, 24, 36), title="F8 gap as ranking variable,")
    corr = []
    for dt, g in sub.groupby("date"):
        if len(g) > 50:
            corr.append(float(np.corrcoef(fxm.pct_rank(g["gap_score"]), fxm.pct_rank(g["vp"]))[0, 1]))
    L += [f"Mean per-date rank correlation of the gap score with IV/price: {np.mean(corr):.2f} (n dates {len(corr)}); sample {len(sub)} name-dates.", ""] + L2
    out["F8_rank"] = {f"{k[0]}|{k[1]}": v for k, v in res.items()}
    for fam in FAMILIES:
        s = sub[sub["family"] == fam]
        if len(s) < 500:
            continue
        L3, r = score_compare(s, scores[:1] + scores[3:], hs=(12,), title=f"F8 {fam},")
        L += L3
        out["F8_rank"].update({f"{fam}|{k[0]}|{k[1]}": v for k, v in r.items()})
    # does the gap predict the first-reported surprise?  realised minus price-implied
    L += ["## Does the gap predict the subsequent first-reported fundamental surprise?", "",
          "Surprise = the average realised revenue growth of years 1-3 (first reported; needs three consecutive reported years) minus the price-implied average growth of years 1-3. If the engine's P50 is right and "
          "the market is wrong, surprise = gap (slope 1). If the market is right, surprise = 0 whatever the gap (slope 0). The regressions have date effects (absorbed) and date-clustered standard errors. "
          "`naive gap` = the company's own latest growth minus the price-implied year-1 growth (horse race: does the engine add beyond the naive extrapolation?). Operating and commodity are pooled; the financial family uses tangible-book growth.", ""]
    surp = {}
    for fam_lab, mask in (("operating + commodity", d["family"] != "financial"), ("financial", d["family"] == "financial")):
        s = d[mask & d["R_gavg3"].notna() & d["g_avg3_imp_sat"].notna()].copy()
        if len(s) < 300:
            continue
        s["surprise"] = s["R_gavg3"] - s["g_avg3_imp_sat"]
        s["vs_engine"] = s["R_gavg3"] - s["im_g_avg3_eng"]
        gdates = s["date"].to_numpy()
        r1 = _fe_reg(s["surprise"].to_numpy(), s[["g_avg3_gap"]].to_numpy(), gdates)
        s["naive_gap_avg"] = (s["gT"] + (s["own_g1"] - s["gT"]) * s["Dfac"]) - s["g_avg3_imp_sat"]
        r2 = _fe_reg(s["surprise"].to_numpy(), s[["g_avg3_gap", "naive_gap_avg"]].to_numpy(), gdates)
        r3 = _fe_reg(s["vs_engine"].to_numpy(), s[["g_avg3_gap"]].to_numpy(), gdates)
        sp = float(np.corrcoef(fxm.pct_rank(s["g_avg3_gap"]), fxm.pct_rank(s["surprise"]))[0, 1])
        s["gq"] = np.minimum((_rank_by_date(s, "g_avg3_gap") * 5).astype(float), 4.999) // 1 + 1
        qm = s.groupby("gq")[["g_avg3_gap", "surprise", "vs_engine"]].mean()
        L += [f"**{fam_lab}** ({len(s)} name-dates, {s['date'].nunique()} dates, valuation years {int(s['year'].min())}-{int(s['year'].max())})", "",
              f"- surprise on engine gap: slope {r1[0][0]:+.3f} (se {r1[1][0]:.3f}); R2 within {r1[3]:.3f}; rank correlation {sp:+.3f}",
              f"- horse race (surprise on engine gap and naive gap): engine {r2[0][0]:+.3f} (se {r2[1][0]:.3f}), naive {r2[0][1]:+.3f} (se {r2[1][1]:.3f})",
              f"- realised minus the engine's own P50 growth on the engine gap: slope {r3[0][0]:+.3f} (se {r3[1][0]:.3f}) (-1 if the market is right, 0 if the engine is)", ""]
        L += md(["gap quintile (Q5 = engine most above the price)", "mean gap", "mean surprise (realised - implied)", "mean realised - engine P50"],
                [[f"Q{int(k)}", _f(float(r['g_avg3_gap']), 3), _f(float(r['surprise']), 3), _f(float(r['vs_engine']), 3)] for k, r in qm.iterrows()]) + [""]
        surp[fam_lab] = {"n": len(s), "slope": float(r1[0][0]), "se": float(r1[1][0]), "horse_engine": float(r2[0][0]), "horse_naive": float(r2[0][1]), "slope_vs_engine": float(r3[0][0]), "rank_corr": sp}
    # margin surprise at year 3 (operating + commodity)
    s = d[(d["family"] != "financial") & d["R_m3"].notna() & d["im_m3_imp"].notna()].copy()
    if len(s) > 300:
        s["surprise"] = s["R_m3"] - s["im_m3_imp"]
        s["gap"] = s["im_m3_eng"] - s["im_m3_imp"]
        s["naive_gap"] = s["state_op_margin"] - s["im_m3_imp"]
        r1 = _fe_reg(s["surprise"].to_numpy(), s[["gap"]].to_numpy(), s["date"].to_numpy())
        r2 = _fe_reg(s["surprise"].to_numpy(), s[["gap", "naive_gap"]].to_numpy(), s["date"].to_numpy())
        L += [f"**Operating margin, year 3** ({len(s)} name-dates): surprise = realised year-3 margin minus the price-implied year-3 margin; slope on the engine's margin gap {r1[0][0]:+.3f} (se {r1[1][0]:.3f}); "
              f"horse race with the naive gap (current margin minus implied): engine {r2[0][0]:+.3f} (se {r2[1][0]:.3f}), naive {r2[0][1]:+.3f} (se {r2[1][1]:.3f}).", ""]
        surp["margin_y3"] = {"n": len(s), "slope": float(r1[0][0]), "se": float(r1[1][0]), "horse_engine": float(r2[0][0]), "horse_naive": float(r2[0][1])}
    s = d[(d["family"] == "financial") & d["R_rote3"].notna() & d["rote_sat"].notna()].copy()
    if len(s) > 150:
        s["surprise"] = s["R_rote3"] - s["rote_sat"]
        s["gap"] = s["p50_rote_target"] - s["rote_sat"]
        s["naive_gap"] = s["own_rote_target"] - s["rote_sat"]
        r1 = _fe_reg(s["surprise"].to_numpy(), s[["gap"]].to_numpy(), s["date"].to_numpy())
        r2 = _fe_reg(s["surprise"].to_numpy(), s[["gap", "naive_gap"]].to_numpy(), s["date"].to_numpy())
        L += [f"**Financial ROTE, year 3** ({len(s)} name-dates): surprise = realised year-3 ROTE minus the price-implied ROTE target; slope on the engine's ROTE gap {r1[0][0]:+.3f} (se {r1[1][0]:.3f}); horse race: engine "
              f"{r2[0][0]:+.3f} (se {r2[1][0]:.3f}), naive {r2[0][1]:+.3f} (se {r2[1][1]:.3f}).", ""]
        surp["rote_y3"] = {"n": len(s), "slope": float(r1[0][0]), "se": float(r1[1][0]), "horse_engine": float(r2[0][0]), "horse_naive": float(r2[0][1])}
    out["F8_surprise"] = surp
    return L
