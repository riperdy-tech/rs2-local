"""Phase B of Stage 2: the development pass check of Addendum V on the 20 quarter-ends 2020-2024, from the forensic panel (no engine is re-run).

    python -m rebuild_harness.stage2.devcheck --panel PANEL.pkl --obs-pre OBS_DIR --events EVENTS_ALL.json --out OUT_DIR [--n-boot 999]

THE RULE (Addendum V), fixed before any figure of this check was formed.  With V1-V4 on the 20 quarter-ends, 12-month excess return, under each of the three survivorship bounds:
  P1  the B1 coefficient's one-sided 90% wild-cluster lower bound (999 draws, clusters = dates; the registered method) is > 0 on all 20 dates;
  P2  the B1 coefficient (point) is > 0 in 2020-2022 and in 2023-2024, each sub-period a pooled regression of its own dates;
  P3  the B2 residual quintile spread is > 0 in each sub-period;
  P4  the dispersion guard: with ln(P90/P10) of the draws added as an extra control (a rank column in the B1 design, a column in the B2 residualisation), P1 holds (lower bound > 0) and the B2 spread
      on all 20 dates is > 0, under all three bounds.  The sub-period figures with the control are reported beside it.
The configuration tested is V1+V2+V3 with the bars as defined (B1 on the pooled percentile rank, B2 on industry-neutral quintiles, which already rank within industry: V4 changes the verdict selection and
leaves the bars unchanged, as Addendum V says).  The variant that also enters the within-industry rank into B1 is reported with the others.  The layers are shown one at a time and together.

The survival model of V2 is fitted for each date from observations resolved before it (`survival.fit_for_date`): the lean observations of the quarter-ends 2016-2019 (`stage2.obs`) and the panel's own
rows of earlier dates.  Commodity names are not in the training set (V3).  Nothing here tunes anything to a return."""
import argparse
import gzip
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from rebuild_harness.forensics import fxm
from rebuild_harness.forensics.analysis_f import Y5
from . import layers as L
from . import survival as S

BOUNDS = fxm.BOUNDS
SPLIT = "2022-12-31"
H = 12
GUARD_COL = "disp"


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        o = o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


def load_obs(obs_dir) -> pd.DataFrame:
    rows = []
    for f in sorted(Path(obs_dir).glob("obs_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                rows.append({"date": r["date"], "cik": r["cik"], "family": r["family"], "census": r["census"], "sv": r["sv"], "mcap": r["mcap"]})
    df = pd.DataFrame(rows)
    return S.with_features(df, sv_col="sv") if len(df) else df


def training_pool(panel: pd.DataFrame, obs_pre: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "cik", "family"] + list(S.FEATURES)
    parts = [panel[L.v3_in_scope(panel)][cols]]
    if obs_pre is not None and len(obs_pre):
        parts.insert(0, obs_pre[~obs_pre["family"].isin(L.OUT_OF_SCOPE_FAMILIES)][cols])
    return pd.concat(parts, ignore_index=True)


def fit_all(panel: pd.DataFrame, pool: pd.DataFrame, events) -> dict:
    """{date: SurvivalModel or None} for every date of the panel."""
    return {d: S.fit_for_date(pool, d, events) for d in sorted(panel["date"].unique())}


def predict_panel(panel: pd.DataFrame, models: dict) -> pd.Series:
    out = pd.Series(np.nan, index=panel.index)
    for d, idx in panel.groupby("date").groups.items():
        m = models.get(d)
        if m is not None:
            out.loc[idx] = m.predict(panel.loc[idx, list(S.FEATURES)].to_numpy(dtype=float))
    return out


def label_panel(panel: pd.DataFrame, events) -> pd.Series:
    return pd.Series([S.label_failure(c, d, events) for c, d in zip(panel["cik"], panel["date"])], index=panel.index)


def auc_table(df: pd.DataFrame) -> dict:
    """Out-of-sample AUC of P(fail) against the realised 12-month failure label: by date, by year, by sub-period and pooled (the model of each date never saw that date's outcomes)."""
    d = df[df["pfail"].notna()]
    out = {"by_date": {k: {"auc": S.auc(g["pfail"].to_numpy(), g["fail12"].to_numpy()), "n": int(len(g)), "events": int(g["fail12"].sum()), "mean_p": float(g["pfail"].mean()),
                            "rate": float(g["fail12"].mean())} for k, g in d.groupby("date")}}
    def agg(mask):
        g = d[mask]
        return {"auc": S.auc(g["pfail"].to_numpy(), g["fail12"].to_numpy()), "n": int(len(g)), "events": int(g["fail12"].sum()), "mean_p": float(g["pfail"].mean()) if len(g) else None,
                "rate": float(g["fail12"].mean()) if len(g) else None}
    out["by_year"] = {str(y): agg(d["year"] == y) for y in sorted(d["year"].unique())}
    out["sub_2020_2022"] = agg(d["date"] <= SPLIT)
    out["sub_2023_2024"] = agg(d["date"] > SPLIT)
    out["pooled"] = agg(d["date"] == d["date"])
    # within-date AUC averaged over dates (the cross-section is what the ranking uses)
    a = [v["auc"] for v in out["by_date"].values() if v["auc"] == v["auc"]]
    out["mean_within_date_auc"] = float(np.mean(a)) if a else None
    return out


# ---- the metrics of one variant -----------------------------------------------------------------------------------------------------------------

def b1_cell(df, col, bound, n_boot, controls=()):
    return fxm.pooled_coef(df, df[col], H, bound, Y5, control_cols=controls, n_boot=n_boot)


def b2_cell(df, col, bound, extra=()):
    pdd = fxm.per_date(df, col, H, bound, Y5, extra_resid_cols=extra)
    return fxm.summarize(pdd, H)


def variant_metrics(df: pd.DataFrame, col: str, n_boot: int, guard: bool = True, sub_boot: int = 0) -> dict:
    """B1 (all dates with the bootstrap lower bound; the two sub-periods as point estimates, with a bootstrap bound when sub_boot > 0) and B2 under the three bounds, all dates and the two sub-periods,
    and the same with the dispersion control."""
    res = {"n_rows": int(df[col].notna().sum()), "n_dates": int(df.loc[df[col].notna(), "date"].nunique())}
    early, late = df[df["date"] <= SPLIT], df[df["date"] > SPLIT]
    for b in BOUNDS:
        r = {}
        r["B1_all"] = b1_cell(df, col, b, n_boot)
        r["B1_2020_2022"] = b1_cell(early, col, b, sub_boot)
        r["B1_2023_2024"] = b1_cell(late, col, b, sub_boot)
        r["B2_all"] = b2_cell(df, col, b)
        r["B2_2020_2022"] = b2_cell(early, col, b)
        r["B2_2023_2024"] = b2_cell(late, col, b)
        if guard:
            r["B1_all_guard"] = b1_cell(df, col, b, n_boot, controls=(GUARD_COL,))
            r["B1_2020_2022_guard"] = b1_cell(early, col, b, sub_boot, controls=(GUARD_COL,))
            r["B1_2023_2024_guard"] = b1_cell(late, col, b, sub_boot, controls=(GUARD_COL,))
            r["B2_all_guard"] = b2_cell(df, col, b, extra=(GUARD_COL,))
            r["B2_2020_2022_guard"] = b2_cell(early, col, b, extra=(GUARD_COL,))
            r["B2_2023_2024_guard"] = b2_cell(late, col, b, extra=(GUARD_COL,))
        res[b] = r
    return res


def _g(x, k):
    return None if x is None else x.get(k)


def pass_rule(m: dict) -> dict:
    """The four conditions of the rule on one variant's metrics (None where a figure could not be formed counts as a failure)."""
    def pos(v):
        return v is not None and v == v and v > 0
    P1 = {b: pos(_g(m[b]["B1_all"], "lower90")) for b in BOUNDS}
    P2 = {sp: {b: pos(_g(m[b][f"B1_{sp}"], "beta")) for b in BOUNDS} for sp in ("2020_2022", "2023_2024")}
    P3 = {sp: {b: pos(m[b][f"B2_{sp}"].get("spread_resid")) for b in BOUNDS} for sp in ("2020_2022", "2023_2024")}
    P4 = {b: bool(pos(_g(m[b].get("B1_all_guard"), "lower90")) and pos((m[b].get("B2_all_guard") or {}).get("spread_resid"))) for b in BOUNDS}
    out = {"P1_B1_lower_bound_positive_all_bounds": all(P1.values()), "P1_detail": P1,
           "P2_B1_point_positive_each_subperiod_all_bounds": all(all(v.values()) for v in P2.values()), "P2_detail": P2,
           "P3_B2_positive_each_subperiod_all_bounds": all(all(v.values()) for v in P3.values()), "P3_detail": P3,
           "P4_dispersion_guard_holds": all(P4.values()), "P4_detail": P4}
    out["PASS"] = bool(out["P1_B1_lower_bound_positive_all_bounds"] and out["P2_B1_point_positive_each_subperiod_all_bounds"] and out["P3_B2_positive_each_subperiod_all_bounds"] and out["P4_dispersion_guard_holds"])
    return out


# ---- the variants -------------------------------------------------------------------------------------------------------------------------------

def build_variants(panel: pd.DataFrame):
    """[(label, frame, score column)]: the layers one at a time and together.  The frame of a V3 variant is the in-scope names only."""
    d = panel.copy()
    d["s_v0"] = d["vp"]
    d["s_v1"] = d["vp_mean"]
    d["s_v2med"] = L.v2_score(d["vp"], d["pfail"])
    d["s_v12"] = L.v2_score(d["vp_mean"], d["pfail"])
    ins = d[L.v3_in_scope(d)].copy()
    ins["s_v4"] = L.v4_rank(ins, "s_v12")
    return [("V0 registered median, all families", d, "s_v0"),
            ("V1 mean, all families", d, "s_v1"),
            ("V1+V2 mean x (1-P), all families", d, "s_v12"),
            ("V3 only: median, commodity out", ins, "s_v0"),
            ("V1+V3 mean, commodity out", ins, "s_v1"),
            ("V1+V2+V3 mean x (1-P), commodity out (THE CONFIGURATION)", ins, "s_v12"),
            ("V1+V2+V3+V4 as above, B1 on the within-industry rank", ins, "s_v4"),
            ("V2+V3 only: median x (1-P), commodity out", ins, "s_v2med")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True, type=Path)
    ap.add_argument("--obs-pre", required=True, type=Path)
    ap.add_argument("--events", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--n-boot", type=int, default=999)
    ap.add_argument("--sub-boot", type=int, default=499)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    panel = pd.read_pickle(a.panel).reset_index(drop=True)
    panel = L.add_dispersion(S.with_features(panel))
    events = S.load_fail_events(a.events)
    obs_pre = load_obs(a.obs_pre)
    pool = training_pool(panel, obs_pre)
    print("pool", pool.shape, "pre-2020 obs", len(obs_pre), flush=True)
    models = fit_all(panel, pool, events)
    panel["pfail"] = predict_panel(panel, models)
    panel["fail12"] = label_panel(panel, events)
    coefs = {d: (m.as_dict() if m is not None else None) for d, m in models.items()}
    (a.out / "survival_coefficients.json").write_text(json.dumps(clean(coefs), indent=1), encoding="utf-8")
    ins = panel[L.v3_in_scope(panel)]
    auc = auc_table(ins)
    (a.out / "survival_auc.json").write_text(json.dumps(clean(auc), indent=1), encoding="utf-8")
    print("models", {d: (m.n_events if m is not None else None) for d, m in models.items()}, flush=True)
    print("auc pooled", auc["pooled"], "sub", auc["sub_2020_2022"], auc["sub_2023_2024"], flush=True)
    panel.to_pickle(a.out / "panel_with_layers.pkl")
    results = {}
    for lab, frame, col in build_variants(panel):
        t1 = time.time()
        m = variant_metrics(frame, col, a.n_boot, guard=True, sub_boot=a.sub_boot)
        results[lab] = {"metrics": m, "rule": pass_rule(m)}
        print(lab, "PASS" if results[lab]["rule"]["PASS"] else "no", f"{time.time() - t1:.0f}s", flush=True)
        (a.out / "variants.json").write_text(json.dumps(clean(results), indent=1), encoding="utf-8")
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
