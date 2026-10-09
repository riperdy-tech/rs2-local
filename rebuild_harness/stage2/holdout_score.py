"""Score the gate-1b holdout exactly as registered (REGISTRATION_gate1b.md section 3 and 4).

    python -m rebuild_harness.stage2.holdout_score RUN_DIR OUT_DIR --coefficients FREEZE_OR_COEFFICIENTS.json [--n-boot 999] [--dev]

Bars (hard, each under the three survivorship bounds of Addenda M, N and P):
  H1  the pooled B1 coefficient > 0 (the 12-month excess return on the percentile rank of value / price plus the five yardsticks, with industry and date effects: `gate1_v2.b1_pooled`); strong pass when its
      one-sided 90% wild-cluster lower bound (999 draws, date clusters) is also > 0
  H2  the industry-neutral residual top-minus-bottom quintile spread (`gate1_v2.b2_v2`) > 0; strong pass at >= +3 pp
  H3  the engine's P50 median absolute error <= the naive baseline's, for next-fiscal-year revenue growth and operating margin of the OPERATING family (`gate1_v2.b4_v2`); financial ROTE reported
Reported: H4 (the median statistic and Damodaran-ERP variants, with and without the survival layer, the dispersion guard, family and sub-period splits), H5 (the level: the median value / price, the extremes
and the family medians).
The value is the configuration of Addendum V as frozen: V1 (mean of the draws) x (1 - P(fail)) from the frozen survival coefficients of the date (V2), the commodity family out (V3); the bars are as defined
(V4 changes the verdict selection, not the bars).
Outcome: PASS when H1, H2 and H3 pass under all three bounds; FAIL when a hard bar fails under all three; NOT DECIDED when a hard bar straddles across the bounds.
`--dev` scores a development run (the forensic records of 2020-2024) for a test of this code: the label of the outcome is then "DEVELOPMENT, not a holdout"."""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from rebuild_harness import gate1_metrics as gm
from rebuild_harness import gate1_v2 as v2m
from rebuild_harness.forensics import fxm, panel as fpanel
from rebuild_harness.forensics.analysis_f import Y5
from . import devcheck as DC
from . import layers as L
from . import survival as S

BOUNDS = gm.BOUNDS
N_BOOT = v2m.N_BOOT
STRONG_B2 = 0.03


def build_panel(run_dir, dates=None) -> pd.DataFrame:
    """The forensic panel of the run (valued names of at least $300M) plus the mean of the draws under Damodaran's own premium (`fx_dam`)."""
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
                o = fpanel.row_of(r)
                dm = (r.get("fx_dam") or {}).get("full") if r.get("fx_dam") else None
                o["vp_mean_dam"] = (dm["mean"] / r["price"]) if (dm and r.get("price")) else None
                o["vp_p50_dam"] = (dm["p50"] / r["price"]) if (dm and r.get("price")) else None
                rows.append(o)
    return pd.DataFrame(rows)


def apply_models(panel: pd.DataFrame, models: dict) -> pd.DataFrame:
    """P(fail) of every name from the FROZEN coefficients of its date (never refitted here)."""
    out = L.add_dispersion(S.with_features(panel))
    out["pfail"] = np.nan
    for d, idx in out.groupby("date").groups.items():
        m = models.get(d)
        if m is None:
            continue
        mod = S.SurvivalModel.from_dict(m) if isinstance(m, dict) else m
        out.loc[idx, "pfail"] = mod.predict(out.loc[idx, list(S.FEATURES)].to_numpy(dtype=float))
    out["s_med"] = out["vp"]
    out["s_mean"] = out["vp_mean"]
    out["s_cfg"] = L.v2_score(out["vp_mean"], out["pfail"])
    out["s_cfg_dam"] = L.v2_score(out["vp_mean_dam"].astype(float), out["pfail"])
    out["s_med_surv"] = L.v2_score(out["vp"], out["pfail"])
    return out


def _keymap(panel, col):
    return {(d, c): v for d, c, v in zip(panel["date"], panel["cik"], panel[col]) if v == v and v is not None}


def registered_bars(run_dir, panel_in_scope: pd.DataFrame, col: str, dates=None, n_boot=N_BOOT) -> dict:
    """H1, H2 and H3 with the REGISTERED code on the compact rows of the run, the score being `col` of the panel (a value / price)."""
    rows, _cnt, _full = gm.load_run(run_dir, dates=dates)
    sc = _keymap(panel_in_scope, col)
    rows = [r for r in rows if r.get("mcap_group") == ">=300M" and (r["date"], r["cik"]) in sc]
    fn = lambda r: sc.get((r["date"], r["cik"]))
    out = {"n_rows": len(rows), "n_dates": len({r["date"] for r in rows}), "by_bound": {}}
    for b in BOUNDS:
        b1 = v2m.b1_pooled(rows, b, score_fn=fn, n_boot=n_boot)
        b2 = v2m.b2_v2(rows, b, score_fn=fn)
        out["by_bound"][b] = {"H1": {k: v for k, v in b1.items() if not k.startswith("_")}, "H2": {k: v for k, v in b2.items() if k != "by_date"}, "H2_by_date": b2.get("by_date")}
    out["H3"] = h3(rows)
    return out


def h3(rows) -> dict:
    """H3 on the operating family (revenue growth, operating margin); financial ROTE reported.  The forecasts are the engine's own P50: the layers do not touch them."""
    b4 = v2m.b4_v2([r for r in rows if r.get("family") in ("operating", "financial")])
    bf = b4["by_family_measure"]
    op = {k: bf[k] for k in ("revenue_growth | operating", "operating_margin | operating") if k in bf}
    ok = [v.get("status") for v in op.values()]
    status = "not computed" if (len(op) < 2 or "not computed" in ok) else ("pass" if all(s == "pass" for s in ok) else "fail")
    return {"status": status, "operating": op, "financial_rote_reported": bf.get("rote | financial"), "all_measures": bf}


def fx_bars(panel_in_scope: pd.DataFrame, col: str, n_boot=499, guard=False, h=12) -> dict:
    """B1 (coefficient, lower bound) and B2 (residual spread) of a value column by `forensics.fxm`, used for the reported variants (H4)."""
    out = {}
    for b in BOUNDS:
        d = panel_in_scope[panel_in_scope[col].notna()]
        if len(d) == 0:
            return {}
        ctrl = (DC.GUARD_COL,) if guard else ()
        c = fxm.pooled_coef(d, d[col], h, b, Y5, control_cols=ctrl, n_boot=n_boot)
        pdd = fxm.per_date(d, col, h, b, Y5, extra_resid_cols=ctrl)
        s = fxm.summarize(pdd, h)
        out[b] = {"B1": c, "B2_resid": s["spread_resid"], "B2_resid_lo": s["spread_resid_lo"], "B2_resid_hi": s["spread_resid_hi"], "IC": s["ic"], "n_dates": s["n_dates"], "n_obs": s["n_obs"]}
    return out


def h4(panel: pd.DataFrame, n_boot=499) -> dict:
    ins = panel[L.v3_in_scope(panel)]
    dates = sorted(ins["date"].unique())
    cut = dates[len(dates) // 2 - 1] if len(dates) > 1 else dates[0]
    res = {"configuration: mean x (1-P), commodity out": fx_bars(ins, "s_cfg", n_boot),
           "median statistic (registered V0), commodity out": fx_bars(ins, "s_med", n_boot),
           "without the survival layer: mean only": fx_bars(ins, "s_mean", n_boot),
           "median x (1-P)": fx_bars(ins, "s_med_surv", n_boot),
           "Damodaran's own premium: mean x (1-P)": fx_bars(ins, "s_cfg_dam", n_boot),
           "dispersion guard: configuration with ln(P90/P10) as a control": fx_bars(ins, "s_cfg", n_boot, guard=True),
           "all families incl. commodity: mean x (1-P)": fx_bars(panel, "s_cfg", n_boot)}
    for fam in ("operating", "financial"):
        res[f"family split: {fam}"] = fx_bars(ins[ins["family"] == fam], "s_cfg", n_boot)
    res[f"sub-period: dates up to {cut}"] = fx_bars(ins[ins["date"] <= cut], "s_cfg", n_boot)
    res[f"sub-period: dates after {cut}"] = fx_bars(ins[ins["date"] > cut], "s_cfg", n_boot)
    return res


def h5(panel: pd.DataFrame) -> dict:
    out = {}
    for lab, d in (("commodity out (the universe)", panel[L.v3_in_scope(panel)]), ("all families", panel)):
        v = d["vp"].dropna()
        x = {"n": int(len(v)), "median_vp": float(v.median()), "share_below_0_4": float((v < 0.4).mean()), "share_above_2_5": float((v > 2.5).mean()),
             "median_mean_over_price": float(d["vp_mean"].median()), "median_cfg_over_price": float(d["s_cfg"].median()),
             "family_medians": {f: float(g["vp"].median()) for f, g in d.groupby("family")}, "by_date_median_vp": {k: float(g["vp"].median()) for k, g in d.groupby("date")},
             "iqr_ln_vp_positive": float(np.subtract(*np.percentile(np.log(v[v > 0]), [75, 25])))}
        out[lab] = x
    return out


def outcome(bars: dict) -> dict:
    """The registered rule on H1, H2, H3 over the three bounds."""
    h1 = {b: bars["by_bound"][b]["H1"].get("beta") is not None and bars["by_bound"][b]["H1"]["beta"] > 0 for b in BOUNDS}
    h1s = {b: (bars["by_bound"][b]["H1"].get("lower_90_one_sided") or float("-inf")) > 0 for b in BOUNDS}
    h2 = {b: bars["by_bound"][b]["H2"].get("mean_spread_residual") is not None and bars["by_bound"][b]["H2"]["mean_spread_residual"] > 0 for b in BOUNDS}
    h2s = {b: (bars["by_bound"][b]["H2"].get("mean_spread_residual") or float("-inf")) >= STRONG_B2 for b in BOUNDS}
    h3p = bars["H3"]["status"] == "pass"
    h3 = {b: h3p for b in BOUNDS}
    st = {}
    for name, d in (("H1", h1), ("H2", h2), ("H3", h3)):
        v = set(d.values())
        st[name] = "pass" if v == {True} else ("fail" if v == {False} else "not decided")
    vals = list(st.values())
    res = "PASS" if all(v == "pass" for v in vals) else ("FAIL" if any(v == "fail" for v in vals) else "NOT DECIDED")
    return {"H1_point_positive": h1, "H1_strong_pass_lower_bound_positive": h1s, "H2_positive": h2, "H2_strong_pass_ge_3pp": h2s, "H3_pass": h3, "bar_status_over_bounds": st, "OUTCOME": res,
            "rule": "PASS: H1, H2 and H3 all pass under all three bounds; FAIL: a hard bar fails under all three bounds; NOT DECIDED: any hard bar straddles across the bounds"}


def run(run_dir, out_dir, models: dict, n_boot=N_BOOT, dates=None, dev=False):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel = apply_models(build_panel(run_dir, dates), models)
    ins = panel[L.v3_in_scope(panel)]
    res = {"dev_mode": dev, "n_panel": int(len(panel)), "n_in_scope": int(len(ins)), "dates": sorted(panel["date"].unique()), "p_fail_undefined": int(ins["pfail"].isna().sum())}
    res["registered"] = registered_bars(run_dir, ins, "s_cfg", dates, n_boot)
    res["outcome"] = outcome(res["registered"])
    res["H4"] = h4(panel, min(n_boot, 499))
    res["H5"] = h5(panel)
    (out_dir / "holdout_score.json").write_text(json.dumps(DC.clean(res), indent=1), encoding="utf-8")
    panel.to_pickle(out_dir / "panel_scored.pkl")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--coefficients", required=True, type=Path, help="the freeze file (its stage2.survival_coefficients) or a {date: coefficients} JSON")
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--dev", action="store_true")
    a = ap.parse_args(argv)
    doc = json.loads(a.coefficients.read_text(encoding="utf-8"))
    models = (doc.get("stage2") or {}).get("survival_coefficients") or doc
    res = run(a.run_dir, a.out_dir, models, a.n_boot, dev=a.dev)
    print(json.dumps(DC.clean(res["outcome"]), indent=1))


if __name__ == "__main__":
    main()
