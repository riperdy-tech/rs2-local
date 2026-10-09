"""Run Study A and Study B on the panel and write the tables.

    python -m rebuild_harness.forecast_study.report PASS_DIR OUT_DIR [--rev-key b_mae]

Writes OUT_DIR/study_A.json, study_A.md, study_B.json, study_B.md (and the panel pickle).  Forecast loss only.

HOW A FORECAST IS SCORED.  Absolute error |y - x| of the forecast of a reported fundamental, on the COMMON sample of a table (every candidate of the table has a forecast for the row).  Reported:
  med    the median absolute error (robust to the data's tails)
  MAE    the mean absolute error on all rows (the tails of the data - pre-revenue companies with margins of -100x, extraction errors in first-filed revenue - dominate it: reported, not relied on)
  MAE_t  the mean absolute error after the 2.5% of rows with the largest |y - ref| are removed, ref being the unconditional population median (so the rule does not depend on any compared candidate)
  win    the share of the trimmed rows on which the candidate is closer to the outcome than the reference candidate (ties are not wins)
  paired mean difference in absolute error against the reference (trimmed rows), with a company-clustered t statistic."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import panel as PN
from . import study as S

TRIM_Q = 0.975
A_VARIANTS = {("operating", "growth"): [None], ("operating", "margin"): [None, "ii_curve"], ("financial", "growth"): [None], ("financial", "rote"): [None, "ii_norm", "ii_curve"]}
LABEL = {"iu": "(i-u) universe median", "iii_last": "(iii) last-year growth", "i": "(i) pop median", "ii": "(ii) code P50", "iii": "(iii) naive", "b_mae": "blend w_MAE", "b_eb": "blend w_EB", "ii_curve": "(ii) retention-only", "ii_norm": "(ii) pre-fade", "persist": "persistence",
         "rev_band": "persist+band reversion", "rev_band_sign": "persist+band x sign reversion", "rev_band_u": "persist+band reversion (universe-fitted)", "rev_band_sign_u": "persist+band x sign (universe-fitted)", "rev_u": "persist+reversion (universe-fitted)", "rev_sign_u": "persist+sign reversion (universe-fitted)", "rev_sign": "persist+sign reversion", "lev_pred": "leverage (forecast revenue)", "lev_pred_clip": "leverage c in [0,1]", "lev_oracle": "leverage (oracle revenue)", "lev_oracle_clip": "leverage c in [0,1], oracle",
         "rev": "persist+reversion"}


def fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:.{nd}f}" if isinstance(x, (float, np.floating)) else str(x)


def md_table(df, nd=4):
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    isint = {c: pd.api.types.is_integer_dtype(df[c]) for c in cols}
    for row in df.itertuples(index=False):
        out.append("| " + " | ".join((str(v) if isint[c] else fmt(v, nd)) for c, v in zip(cols, row)) + " |")
    return "\n".join(out)


def summarize(y, preds, ref, year, cik, base, need=None, base2=None):
    """Score `preds` ({name: Series}) against `y` on the rows where y, ref and every pred in `need` (default all) exist.  See the module docstring for the metrics."""
    need = list(preds) if need is None else need
    ok = y.notna() & ref.notna()
    for n in need:
        ok &= preds[n].notna()
    if not ok.any():
        return {"n": 0}
    yy, rr = y[ok], ref[ok]
    e = {n: (yy - p[ok]).abs() for n, p in preds.items()}
    dev = (yy - rr).abs()
    keep = dev <= dev.quantile(TRIM_Q)
    out = {"n": int(ok.sum()), "n_trim": int(keep.sum()), "pooled": {}, "paired": {}, "win": {}, "paired2": {}, "base2": base2, "by_year": []}
    for n, v in e.items():
        vv = v.dropna()
        kk = v[keep].dropna()
        out["pooled"][n] = {"mae": float(vv.mean()), "mae_t": float(kk.mean()) if len(kk) else float("nan"), "med": float(vv.median()), "n": int(len(vv))}
        if n != base and base in e:
            d = (v - e[base])[keep]
            out["paired"][n] = S.cluster_t(d, cik[ok][keep])
            both = d.notna()
            out["win"][n] = float((d[both] < 0).mean()) if both.any() else float("nan")
        if base2 is not None and n != base2 and base2 in e:
            out["paired2"][n] = S.cluster_t((v - e[base2])[keep], cik[ok][keep])
    yr = year[ok]
    for Y in sorted(yr.unique()):
        m = (yr == Y)
        r = {"year": int(Y), "n": int(m.sum())}
        mt = m & keep
        for n, v in e.items():
            r[n + "_MAEt"] = float(v[mt].mean()) if mt.any() else float("nan")
            r[n + "_med"] = float(v[m].median())
        out["by_year"].append(r)
    return out


def md_summary(title, rec, names, base, base2=None):
    if not rec.get("n"):
        return f"\n### {title}\n\nno common sample\n"
    out = [f"\n### {title}\n", f"common sample n={rec['n']} (trimmed n={rec['n_trim']})\n"]
    by = pd.DataFrame(rec["by_year"])
    cols = ["year", "n"] + [f"{n}_MAEt" for n in names if f"{n}_MAEt" in by] + [f"{n}_med" for n in names if f"{n}_med" in by]
    out.append("By origin year: MAE_t (trimmed MAE) and median AE\n")
    out.append(md_table(by[cols]))
    rows = []
    for n in names:
        if n in rec["pooled"]:
            p = rec["pooled"][n]
            q = rec["paired"].get(n)
            row = {"candidate": LABEL.get(n, n), "MAE": p["mae"], "MAE_t": p["mae_t"], "med": p["med"],
                   f"dMAE_t vs {base}": None if q is None else q["mean"], "t": None if q is None else q["t"], "win": rec["win"].get(n)}
            if base2 is not None:
                q2 = rec["paired2"].get(n)
                row.update({f"dMAE_t vs {base2}": None if q2 is None else q2["mean"], "t2": None if q2 is None else q2["t"]})
            rows.append(row)
    out.append("\nPooled\n")
    out.append(md_table(pd.DataFrame(rows)))
    return "\n".join(out)


def study_a(P, obs, out_dir):
    pop = S.Population(obs)
    res, md = {}, ["# Study A: shrinkage of company-specific inputs (walk-forward, forecast loss only, information to 2024-12-31)\n",
                   "Candidates: (i) unconditional population median, (ii) the code's state-conditioned prior P50, (iii) naive persistence / trailing CAGR, blends i + w (ii - i) with w from the MAE grid or the "
                   "empirical-Bayes moment form, both fitted walk-forward.  Reference for the paired columns: (ii).\n"]
    for (fam, var), variants in A_VARIANTS.items():
        for cvar in variants:
            for k in S.KS:
                d, W = S.run_cell(P, pop, fam, var, k) if cvar is None else _variant_cell(P, pop, fam, var, k, cvar)
                tag = f"{fam}|{var}|k{k}|{'code' if cvar is None else cvar}"
                names = ["i", "iu", "ii", "iii"] + (["iii_last"] if "x_iii_last" in d and var == "growth" else []) + ["b_mae", "b_eb"]
                base_need = [n for n in names if n not in ("b_mae", "b_eb", "iu")]
                preds = {n: d["x_" + n] for n in names}
                rec = {"n_rows_family": int(len(d)), "w_path": {int(y): v for y, v in W.items()}, "company_input": "code" if cvar is None else cvar}
                rec["common_i_ii_iii"] = summarize(d["y"], {n: preds[n] for n in base_need}, d["x_i"], d["year"], d["cik"], "ii", base2="i")
                rec["common_with_blends"] = summarize(d["y"], preds, d["x_i"], d["year"], d["cik"], "ii", need=base_need + ["b_mae", "b_eb", "iu"], base2="i")
                rec["i_vs_iii_all_years"] = summarize(d["y"], {n: preds[n] for n in base_need if n != "ii"}, d["x_i"], d["year"], d["cik"], "i", need=[n for n in base_need if n != "ii"])
                ok = d["y"].notna() & d["x_i"].notna() & d["x_ii"].notna() & d["x_iii"].notna() & d["x_b_mae"].notna() & d["x_b_eb"].notna()
                rec["coverage_p10_p90_blend_years"] = S.coverage(d[ok], ["i", "ii", "b_mae", "b_eb"])
                rec["coverage_by_year"] = {int(Y): S.coverage(g, ["i", "ii"]) for Y, g in d[d["y"].notna() & d["x_i"].notna() & d["x_ii"].notna()].groupby("year")}
                res[tag] = rec
                md.append(f"\n## {tag}\n")
                md.append("w path (walk-forward; n_train = pairs with the outcome filed before T)\n")
                md.append(md_table(pd.DataFrame([{"year": y, "w_MAE": (v or {}).get("mae"), "w_EB": (v or {}).get("eb"), "n_train": (v or {}).get("n")} for y, v in W.items() if v is not None]), 2)
                          if any(v is not None for v in W.values()) else "no fit possible (too few earlier outcomes)")
                md.append(md_summary("all years with the code's prior: (i), (ii), (iii)", rec["common_i_ii_iii"], base_need, "ii", "i"))
                md.append(md_summary("years with a walk-forward w (both blends)", rec["common_with_blends"], names, "ii", "i"))
                if cvar is None:
                    md.append(md_summary("all origin years incl. 2016, without the code's prior: (i) against (iii)", rec["i_vs_iii_all_years"], [n for n in base_need if n != "ii"], "i"))
                md.append("\nP10-P90 coverage (nominal 0.80), years with blends: " + json.dumps({k_: round(v, 3) for k_, v in rec["coverage_p10_p90_blend_years"].items()}))
                md.append("\nP10-P90 coverage by origin year (i / ii): " + json.dumps({y_: {k_: round(v, 2) for k_, v in c_.items()} for y_, c_ in rec["coverage_by_year"].items()}))
    (out_dir / "study_A.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    (out_dir / "study_A.md").write_text("\n".join(md), encoding="utf-8")
    return res


def _variant_cell(P, pop, fam, var, k, cvar):
    """The same cell with the alternative company-specific input `cvar` (retention-only or pre-fade) taken as (ii): its walk-forward blends; it carries no quantiles."""
    d = S.build_candidates(P, pop, fam, var, k)
    d["x_ii"] = d["x_" + cvar]
    d["x_ii_p10"] = np.nan
    d["x_ii_p90"] = np.nan
    W = S.walk_forward_w(d, sorted(d.year.unique()))
    return S.attach_blends(d, W), W


def study_b(P, obs, out_dir, rev_key):
    pop = S.Population(obs)
    gcells = {k: S.run_cell(P, pop, "operating", "growth", k)[0] for k in S.KS}
    M = S.margin_study(P, obs, pop, gcells, rev_key)
    fin = _fin_rote(P, obs, pop)
    res, md = {"revenue_forecast": rev_key}, [f"# Study B: margin baselines (walk-forward, forecast loss only); revenue forecast for the leverage model: {rev_key}\n",
                                               "Reference for the paired columns: persistence.  `curve` sample: every candidate except the exact code path (origins 2018-2024); `exact` sample adds the exact code path "
                                               "(the vintage supports it from origin 2020).\n"]
    for k in S.KS:
        m = M[k]
        names = ["persist", "ii_curve", "rev_band", "rev_band_sign", "rev_band_u", "rev_band_sign_u", "lev_pred", "lev_pred_clip", "lev_oracle", "lev_oracle_clip"]
        for tag, ns in (("curve", names), ("exact", names[:1] + ["ii"] + names[1:])):
            preds = {n: m[n] for n in ns}
            rec = summarize(m["y"], preds, m["ref"], m["year"], m["cik"], "persist")
            res[f"operating|k{k}|{tag}"] = rec
            md.append(md_summary(f"operating margin, k={k}, sample `{tag}`", rec, ns, "persist"))
        lam = {}
        rv = S.Reversion(obs, "operating", "m", "med8", "m", True)
        for Y in sorted(m.year.unique()):
            r_ = rv.fit(k, S.t_of(Y))
            lam[int(Y)] = {"lam": r_["lam"], "n": r_["n"], "cuts": r_["cuts"]}
        res[f"operating|k{k}|lambda_path"] = lam
        md.append(f"\nband reversion speeds lambda by origin year (k={k}, grid [0,1]): " + json.dumps({y: {b: round(v, 2) for b, v in l["lam"].items()} for y, l in lam.items()}))
    for k in S.KS:
        m = fin[k]
        for tag, ns in (("curve", ["persist", "ii_curve", "rev", "rev_sign", "rev_u", "rev_sign_u"]), ("exact", ["persist", "ii", "ii_norm", "ii_curve", "rev", "rev_sign", "rev_u", "rev_sign_u"])):
            preds = {n: m[n] for n in ns}
            rec = summarize(m["y"], preds, m["ref"], m["year"], m["cik"], "persist")
            res[f"financial|k{k}|{tag}"] = rec
            md.append(md_summary(f"financial ROTE, k={k}, sample `{tag}`", rec, ns, "persist"))
    (out_dir / "study_B.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    (out_dir / "study_B.md").write_text("\n".join(md), encoding="utf-8")
    return res, M


def _fin_rote(P, obs, pop):
    rv = S.Reversion(obs, "financial", "rote", "rote_med8", "rote", False)
    rvs = S.Reversion(obs, "financial", "rote", "rote_med8", "rote", False, signed=True)
    U = S.universe_frame(P, "rote", "rote_med8", "rote")
    rvu, rvus = S.Reversion(U, "financial", "rote", "rote_med8", "rote", False), S.Reversion(U, "financial", "rote", "rote_med8", "rote", False, signed=True)
    f = P[P.family == "financial"]
    out = {}
    for k in S.KS:
        rows = []
        for idx, r in f.iterrows():
            T = S.t_of(r.year)
            R0 = r["rote_latest"]
            st = pop.stats("financial", "rote", k, T)
            rec = {"idx": idx, "year": r.year, "cik": r.cik, "y": r[f"rote_{k}"], "persist": R0, "ref": np.nan if st is None else st["p50"], "ii": r.get(f"c_rote_{k}_p50", np.nan),
                   "ii_norm": r.get(f"c_rote_norm_{k}_p50", np.nan), "ii_curve": r.get(f"c_rote_curve_{k}_p50", np.nan)}
            rec["rev"] = rv.predict(k, T, R0, r["f_rote_med8"], None)[0] if pd.notna(R0) else np.nan
            rec["rev_sign"] = rvs.predict(k, T, R0, r["f_rote_med8"], None)[0] if pd.notna(R0) else np.nan
            rec["rev_u"] = rvu.predict(k, T, R0, r["f_rote_med8"], None)[0] if pd.notna(R0) else np.nan
            rec["rev_sign_u"] = rvus.predict(k, T, R0, r["f_rote_med8"], None)[0] if pd.notna(R0) else np.nan
            rows.append(rec)
        out[k] = pd.DataFrame(rows).set_index("idx")
    return out


def headline(resA, resB, out_dir):
    """The two tables the recommendations rest on, generated from the JSON: Study A (pooled over the years with a walk-forward w) and Study B (curve sample, against persistence)."""
    rows = []
    for tag, rec in resA.items():
        c = rec["common_with_blends"]
        if not c.get("n"):
            continue
        fam, var, k, inp = tag.split("|")
        W = {int(y): v for y, v in rec["w_path"].items() if v is not None}
        ys = sorted(W)
        r = {"family": fam, "variable": var, "k": k, "company input": inp, "n": c["n"], "years": f"{ys[0]}-{ys[-1]}" if ys else "-"}
        for n in ("i", "iu", "ii", "iii", "b_mae", "b_eb"):
            if n in c["pooled"]:
                r[n + " MAE_t"] = c["pooled"][n]["mae_t"]
                r[n + " med"] = c["pooled"][n]["med"]
        r["w_MAE last3"] = float(np.mean([W[y]["mae"] for y in ys[-3:]])) if ys else None
        r["w_EB last3"] = float(np.mean([W[y]["eb"] for y in ys[-3:]])) if ys else None
        for n in ("b_mae", "b_eb"):
            r[n + " vs ii (t)"] = c["paired"].get(n, {}).get("t")
            r[n + " vs i (t)"] = c["paired2"].get(n, {}).get("t")
        rows.append(r)
    dfa = pd.DataFrame(rows)
    rows = []
    for key, rec in resB.items():
        if not key.endswith("|curve") or not rec.get("n"):
            continue
        fam, k, _ = key.split("|")
        base = rec["pooled"]["persist"]
        for n, v in rec["pooled"].items():
            q = rec["paired"].get(n)
            rows.append({"family": fam, "k": k, "n": rec["n"], "candidate": LABEL.get(n, n), "MAE_t": v["mae_t"], "MAE_t vs persist %": None if n == "persist" else 100 * (v["mae_t"] / base["mae_t"] - 1),
                         "med": v["med"], "med vs persist %": None if n == "persist" else 100 * (v["med"] / base["med"] - 1), "t": None if q is None else q["t"], "win": rec["win"].get(n)})
    dfb = pd.DataFrame(rows)
    parts = ["# Headline tables (generated)", "", "## Study A, pooled over origin years with a walk-forward w", "", md_table(dfa, 4), "",
             "## Study B, sample `curve` (origins 2018-2024), against persistence", "", md_table(dfb, 4), ""]
    (out_dir / "headline.md").write_text(chr(10).join(parts), encoding="utf-8")
    return dfa, dfb


def audit(P, obs, out_dir):
    """The information-cut audit: no fit reached its origin date, nothing was filed after 2024-12-31, the priors vintages are those of year(T) - 1, and the sample sizes by year."""
    bad = [a for a in S.AUDIT if a[3] is not None and a[3] >= a[2]]
    bad_y = [a for a in S.AUDIT if a[4] is not None and a[4] >= int(a[2][:4])]
    allfiled = max(str(P[f"filed_{k}"].dropna().max()) for k in S.KS)
    out = {"n_fits_audited": len(S.AUDIT), "fits_using_an_outcome_filed_on_or_after_T": len(bad), "fits_using_an_origin_year_not_before_the_fitting_year": len(bad_y),
           "latest_outcome_filing_in_the_panel": allfiled, "latest_filing_in_the_observation_table": str(obs["own_filed"].max()), "origin_dates": sorted(P["date"].unique().tolist()),
           "priors_vintage_by_origin_year": {int(y): sorted(set(int(v) for v in g.dropna())) for y, g in P.groupby("year")["vintage"]},
           "rows_by_year_family": {f"{y}|{f}": int(n) for (y, f), n in P.groupby(["year", "family"]).size().items()},
           "excluded_stale_base_rows": int(P.attrs.get("excluded_stale_base", 0)), "matched_to_observation_table": float(P["matched"].mean()),
           "outcome_rows_by_year": {f"{y}|k{k}": int(g[f"filed_{k}"].notna().sum()) for k in S.KS for y, g in P.groupby("year")}}
    assert not bad and not bad_y, (bad[:3], bad_y[:3])
    assert allfiled <= PN.CUT and max(P["date"]) <= "2024-06-30"
    (out_dir / "audit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--rev-key", default="b_mae")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    P, obs = PN.build(a.pass_dir)
    P.to_pickle(a.out_dir / "panel.pkl")
    ra = study_a(P, obs, a.out_dir)
    rb, _ = study_b(P, obs, a.out_dir, a.rev_key)
    headline(ra, rb, a.out_dir)
    audit(P, obs, a.out_dir)
    print("written", a.out_dir, "excluded stale base:", P.attrs.get("excluded_stale_base"))


if __name__ == "__main__":
    main()
