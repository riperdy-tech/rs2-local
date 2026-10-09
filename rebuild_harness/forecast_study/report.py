"""Run Study A and Study B on the panel and write the tables.

    python -m rebuild_harness.forecast_study.report PASS_DIR OUT_DIR [--rev-key b_mae]

Writes OUT_DIR/study_A.json, study_A.md, study_B.json, study_B.md (and the panel pickle).  Forecast loss only."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import panel as PN
from . import study as S

A_VARIANTS = {("operating", "growth"): [None], ("operating", "margin"): [None, "ii_curve"], ("financial", "growth"): [None], ("financial", "rote"): [None, "ii_norm", "ii_curve"]}
LABEL = {"i": "(i) pop median", "ii": "(ii) code P50", "iii": "(iii) naive", "b_mae": "blend w_MAE", "b_eb": "blend w_EB", "ii_curve": "(ii) curve-only", "ii_norm": "(ii) pre-fade"}


def fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:.{nd}f}" if isinstance(x, (float, np.floating)) else str(x)


def md_table(df, nd=4):
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(fmt(r[c], nd) if not isinstance(r[c], (int, np.integer, str)) else str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def study_a(P, obs, out_dir):
    pop = S.Population(obs)
    res, md = {}, ["# Study A: shrinkage of company-specific inputs (walk-forward, forecast loss only, information to 2024-12-31)\n"]
    for (fam, var), variants in A_VARIANTS.items():
        for cvar in variants:
            for k in S.KS:
                d, W = S.run_cell(P, pop, fam, var, k) if cvar is None else _variant_cell(P, pop, fam, var, k, cvar)
                tag = f"{fam}|{var}|k{k}|{'code' if cvar is None else cvar}"
                cands = ["i", "ii", "iii", "b_mae", "b_eb"]
                e_all, s_all = S.score_cell(d, cands, need=("i", "ii", "iii"))
                e_w, s_w = S.score_cell(d, cands, need=("i", "ii", "iii", "b_mae", "b_eb"))
                by = S.by_year(e_all, cands)
                cov_y = {}
                for Y, g in s_all.groupby("year"):
                    cov_y[int(Y)] = S.coverage(g, ["i", "ii", "b_mae", "b_eb"])
                rec = {"n_rows_family": int(len(d)), "n_scored_all": int(len(e_all)), "n_scored_w": int(len(e_w)), "w_path": {int(y): v for y, v in W.items()},
                       "by_year": by.to_dict("records"), "coverage_by_year": cov_y, "coverage_pooled_w": S.coverage(s_w, ["i", "ii", "b_mae", "b_eb"])}
                for nm, e in (("pooled_all", e_all), ("pooled_w", e_w)):
                    r = {}
                    for c in cands:
                        if c in e and e[c].notna().any():
                            r[c] = {"mae": float(e[c].mean()), "med": float(e[c].median()), "n": int(e[c].notna().sum())}
                    rec[nm] = r
                for ref in ("iii", "i", "ii"):
                    for c in ("ii", "b_mae", "b_eb"):
                        if c != ref and c in e_w and ref in e_w:
                            rec.setdefault("paired_w", {})[f"{c}-{ref}"] = S.cluster_t(e_w[c] - e_w[ref], e_w["cik"])
                        if c != ref and c in e_all and ref in e_all and c in ("ii",):
                            rec.setdefault("paired_all", {})[f"{c}-{ref}"] = S.cluster_t(e_all[c] - e_all[ref], e_all["cik"])
                res[tag] = rec
                md.append(_md_cell_a(tag, rec, by, W, cands))
    (out_dir / "study_A.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    (out_dir / "study_A.md").write_text("\n".join(md), encoding="utf-8")
    return res


def _variant_cell(P, pop, fam, var, k, cvar):
    """The same cell with the alternative company-specific input `cvar` (curve-only or pre-fade) taken as (ii): its walk-forward blends and its coverage (none: the variants carry no quantiles)."""
    d = S.build_candidates(P, pop, fam, var, k)
    d["x_ii"] = d["x_" + cvar]
    d["x_ii_p10"] = np.nan
    d["x_ii_p90"] = np.nan
    W = S.walk_forward_w(d, sorted(d.year.unique()))
    return S.attach_blends(d, W), W


def _md_cell_a(tag, rec, by, W, cands):
    out = [f"\n## {tag}\n"]
    out.append(f"rows of the family {rec['n_rows_family']}; scored on the common sample (outcome, i, ii, iii present) {rec['n_scored_all']}; with both blends {rec['n_scored_w']}\n")
    cols = ["year", "n"] + [f"{c}_mae" for c in cands if f"{c}_mae" in by] + [f"{c}_med" for c in cands if f"{c}_med" in by]
    out.append("MAE and median AE by origin year\n")
    out.append(md_table(by[cols]))
    out.append("\nw path (walk-forward)\n")
    wp = pd.DataFrame([{"year": y, "w_MAE": (v or {}).get("mae"), "w_EB": (v or {}).get("eb"), "n_train": (v or {}).get("n")} for y, v in W.items()])
    out.append(md_table(wp, 2))
    for nm in ("pooled_all", "pooled_w"):
        r = rec[nm]
        out.append(f"\n{nm}: " + "; ".join(f"{LABEL.get(c, c)} MAE {fmt(v['mae'])} / med {fmt(v['med'])} (n={v['n']})" for c, v in r.items()))
    out.append("\ncoverage of P10-P90 (nominal 0.80), pooled over years with a blend: " + json.dumps({k: round(v, 3) for k, v in rec["coverage_pooled_w"].items()}))
    if rec.get("paired_w"):
        out.append("\npaired mean difference in absolute error (negative = first is better), cluster-robust t: " +
                   "; ".join(f"{k}: {fmt(v['mean'], 5)} (t={fmt(v['t'], 2)})" for k, v in rec["paired_w"].items()))
    return "\n".join(out)


def study_b(P, obs, out_dir, rev_key):
    pop = S.Population(obs)
    gcells = {k: S.run_cell(P, pop, "operating", "growth", k)[0] for k in S.KS}
    M = S.margin_study(P, obs, gcells, rev_key)
    res, md = {"revenue_forecast": rev_key}, [f"# Study B: margin baselines (walk-forward, forecast loss only); revenue forecast for the leverage model: {rev_key}\n"]
    for k in S.KS:
        m = M[k]
        cands = ["persist", "ii", "ii_curve", "rev_band", "lev_pred", "lev_pred_clip", "lev_oracle", "lev_oracle_clip"]
        ok = m.y.notna() & m.persist.notna()
        err = pd.DataFrame({"year": m.year, "cik": m.cik})
        for c in cands:
            err[c] = (m.y - m[c]).abs()
        res[f"operating|k{k}"] = {}
        # (a) 2017-2024, no exact code input: persistence, curve-only code path, band reversion, leverage (pred and oracle) on their common sample
        for tag, need in (("curve_sample", ["persist", "ii_curve", "rev_band", "lev_pred", "lev_oracle"]), ("exact_sample", ["persist", "ii", "ii_curve", "rev_band", "lev_pred", "lev_oracle"]),
                          ("persist_rev_only", ["persist", "ii_curve", "rev_band"])):
            msk = ok.copy()
            for c in need:
                msk &= err[c].notna()
            e = err[msk]
            by = S.by_year(e, cands)
            rec = {"n": int(len(e)), "pooled": {c: {"mae": float(e[c].mean()), "med": float(e[c].median())} for c in cands if e[c].notna().any()}, "by_year": by.to_dict("records"), "paired_vs_persist": {}}
            for c in cands:
                if c != "persist" and e[c].notna().any():
                    rec["paired_vs_persist"][c] = S.cluster_t(e[c] - e["persist"], e["cik"])
            res[f"operating|k{k}"][tag] = rec
            md.append(f"\n## operating margin, k={k}, sample `{tag}` (n={len(e)})\n")
            cols = ["year", "n"] + [f"{c}_mae" for c in cands if f"{c}_mae" in by and by[f"{c}_mae"].notna().any()]
            md.append(md_table(by[cols]))
            md.append("\npooled MAE (median AE): " + "; ".join(f"{c} {fmt(v['mae'])} ({fmt(v['med'])})" for c, v in rec["pooled"].items()))
            md.append("\npaired vs persistence (mean diff, cluster t): " + "; ".join(f"{c}: {fmt(v['mean'], 5)} (t={fmt(v['t'], 2)})" for c, v in rec["paired_vs_persist"].items()))
        lam = {}
        rv = S.Reversion(obs, "operating", "m", "med8", "m", True)
        for Y in sorted(m.year.unique()):
            r_ = rv.fit(k, S.t_of(Y))
            lam[int(Y)] = {"lam": r_["lam"], "n": r_["n"], "cuts": r_["cuts"]}
        res[f"operating|k{k}"]["lambda_path"] = lam
        md.append(f"\nband reversion speeds lambda by year (k={k}): " + json.dumps({y: {b: round(v, 2) for b, v in l["lam"].items()} for y, l in lam.items()}))
    # financial: ROTE baselines
    mf = _fin_rote(P, obs)
    for k in S.KS:
        m = mf[k]
        cands = ["persist", "ii", "ii_norm", "ii_curve", "rev"]
        err = pd.DataFrame({"year": m.year, "cik": m.cik})
        for c in cands:
            err[c] = (m.y - m[c]).abs()
        res[f"financial|k{k}"] = {}
        for tag, need in (("curve_sample", ["persist", "ii_curve", "rev"]), ("exact_sample", ["persist", "ii", "ii_norm", "ii_curve", "rev"])):
            msk = m.y.notna() & m.persist.notna()
            for c in need:
                msk &= err[c].notna()
            e = err[msk]
            by = S.by_year(e, cands)
            rec = {"n": int(len(e)), "pooled": {c: {"mae": float(e[c].mean()), "med": float(e[c].median())} for c in cands if e[c].notna().any()}, "by_year": by.to_dict("records"), "paired_vs_persist": {}}
            for c in cands:
                if c != "persist" and e[c].notna().any():
                    rec["paired_vs_persist"][c] = S.cluster_t(e[c] - e["persist"], e["cik"])
            res[f"financial|k{k}"][tag] = rec
            md.append(f"\n## financial ROTE, k={k}, sample `{tag}` (n={len(e)})\n")
            cols = ["year", "n"] + [f"{c}_mae" for c in cands if f"{c}_mae" in by and by[f"{c}_mae"].notna().any()]
            md.append(md_table(by[cols]))
            md.append("\npooled MAE (median AE): " + "; ".join(f"{c} {fmt(v['mae'])} ({fmt(v['med'])})" for c, v in rec["pooled"].items()))
            md.append("\npaired vs persistence (mean diff, cluster t): " + "; ".join(f"{c}: {fmt(v['mean'], 5)} (t={fmt(v['t'], 2)})" for c, v in rec["paired_vs_persist"].items()))
    (out_dir / "study_B.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    (out_dir / "study_B.md").write_text("\n".join(md), encoding="utf-8")
    return res, M


def _fin_rote(P, obs):
    rv = S.Reversion(obs, "financial", "rote", "rote_med8", "rote", False)
    f = P[P.family == "financial"]
    out = {}
    for k in S.KS:
        rows = []
        for idx, r in f.iterrows():
            T = S.t_of(r.year)
            R0 = r["rote_latest"]
            rec = {"idx": idx, "year": r.year, "cik": r.cik, "y": r[f"rote_{k}"], "persist": R0, "ii": r.get(f"c_rote_{k}_p50", np.nan), "ii_norm": r.get(f"c_rote_norm_{k}_p50", np.nan),
                   "ii_curve": r.get(f"c_rote_curve_{k}_p50", np.nan)}
            rec["rev"] = rv.predict(k, T, R0, r["f_rote_med8"], None)[0] if pd.notna(R0) else np.nan
            rows.append(rec)
        out[k] = pd.DataFrame(rows).set_index("idx")
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
    study_a(P, obs, a.out_dir)
    study_b(P, obs, a.out_dir, a.rev_key)
    print("written", a.out_dir)


if __name__ == "__main__":
    main()
