"""The gate-1b freeze file (REGISTRATION_gate1b.md section 1): written once, before any 2025 date is run, only if the development pass check held.

    python -m rebuild_harness.stage2.freeze --out-dir NEW_FOLDER --panel PANEL.pkl --obs-pre OBS_DIR --events EVENTS_ALL.json --devcheck DEVCHECK_DIR

It is `gate1_freeze.json`'s content (the engine identity with the hashes the files have on disk, and `holdout.compute_contents`: the point-in-time store, the daily price folder, the monthly fallback, the
cover index, the Damodaran files, the priors vintages, the crosswalk, the headers, the D1 index, the D3 documents, the configuration, the seeds and the packages) plus a `stage2` block: the code commit of
this repository, the settings of V1-V4, the survival coefficients fitted for each of the nine dates from data resolved before it, the hashes of the data they were fitted on, and the development check's
result files.  The folder must be new and empty (nothing is overwritten); the freeze is printed with its sha256."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from rebuild_harness import gate1_run, holdout
from . import devcheck as DC
from . import layers as L
from . import survival as S
from . import holdout_run as HR

WS = gate1_run.WORKSPACE
D = WS / "data"
OLD_FREEZE = WS / "scratch" / "rev23" / "gate1_holdout" / "gate1_freeze.json"
REGISTRATION = WS / "docs" / "review_2026-09-22" / "rev23" / "REGISTRATION_gate1b.md"
SPEC = WS / "docs" / "review_2026-09-22" / "rev23" / "SPEC_rebuild.md"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def fit_holdout_models(panel_pkl, obs_dir, events_path, dates=HR.DATES) -> dict:
    """{date: SurvivalModel.as_dict()} for the nine holdout dates, from the observations resolved before each (the quarter-ends to 2024-12-31)."""
    panel = L.add_dispersion(S.with_features(pd.read_pickle(panel_pkl).reset_index(drop=True)))
    events = S.load_fail_events(events_path)
    pool = DC.training_pool(panel, DC.load_obs(obs_dir))
    out = {}
    for d in dates:
        m = S.fit_for_date(pool, d, events)
        if m is None:
            raise RuntimeError(f"no survival model can be fitted for {d}: too few failures resolved before it")
        out[d] = m.as_dict()
    return out


def build(out_dir: Path, panel_pkl, obs_dir, events_path, devcheck_dir) -> tuple:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"{out_dir} exists and is not empty: the freeze goes into a new folder")
    out_dir.mkdir(parents=True, exist_ok=True)
    old = json.loads(OLD_FREEZE.read_text(encoding="utf-8"))
    ra = old["annotations"]["run_arguments"]
    a = SimpleNamespace(store=ra["store"], prices=ra["prices_monthly_fallback"], prices_daily=ra["prices_daily"], headers=ra["headers"], crosswalk=ra["crosswalk"], priors_dir=ra["priors_dir"],
                        delisting_index=ra["delisting_index"], delisting_docs=ra["delisting_docs"], survivorship_cover=ra["survivorship_cover"], no_prices_fallback=False)
    inputs = gate1_run.freeze_inputs(a)
    inputs["priors"] = ra["priors_dir"]
    repo = gate1_run.REPO
    freeze = out_dir / "gate1b_freeze.json"
    doc = holdout.write_freeze(freeze, [gate1_run.gate1_engine], repo=repo, registration="REGISTRATION_gate1b.md (2026-10-09); SPEC_rebuild.md Addenda J-V", inputs=inputs)
    models = fit_holdout_models(panel_pkl, obs_dir, events_path)
    obs_files = {p.name: sha(p) for p in sorted(Path(obs_dir).glob("obs_*.jsonl.gz"))}
    dev = {p.name: sha(p) for p in sorted(Path(devcheck_dir).glob("*.json"))}
    ev = Path(ra["delisting_index"])
    doc["stage2"] = {
        "stage2_commit": holdout._git(repo, "rev-parse", "HEAD").decode().strip(),
        "engine_identical_to": "c7d7a4f (git diff c7d7a4f HEAD over valuation/engine_*, common.py, discount_rate.py, priors.py is empty)",
        "layers": {"V1": "value = mean of the IV draws (per-draw equity floored at 0 by the engine); guard: ln(P90/P10) of the draws as an extra control in B1 and B2",
                   "V2": "value = mean IV x (1 - P(fail within 12 months)); equity recovery 0; P from the ridge logistic model recorded per date below",
                   "V3": "commodity family out of the universe (family_not_built) for every bar", "V4": "verdict quintiles ranked within industry (date-wide rank for an industry below the minimum size); the bars are unchanged"},
        "survival_settings": {"features": list(S.FEATURES), "continuous": list(S.CONTINUOUS), "winsor": list(S.WINSOR), "ridge": S.RIDGE, "min_events": S.MIN_EVENTS, "horizon_months": S.HORIZON_MONTHS,
                              "fail_classes": list(S.FAIL_CLASSES), "label_rule": "an event of a failure class dated after t and no later than t+12 months; at the valuation date T only events dated before T count",
                              "training_rule": "observations at quarter-ends t with t + 12 months <= T, non-commodity, market cap (public float for the census) >= $300M",
                              "distance_to_default": "not used: the price file holds survivors only (stage-2 report)"},
        "run": {"dates": HR.DATES, "horizons_months": list(HR.HORIZONS), "outcomes_end": HR.OUTCOMES_END.isoformat(), "kS_fundamental_outcomes": HR.KS_FX, "workers": "2 (does not change results: deterministic seeds)",
                "runner": "rebuild_harness/stage2/holdout_run.py", "scorer": "rebuild_harness/stage2/holdout_score.py"},
        "survival_coefficients": models,
        "training_data": {"panel_pkl": str(panel_pkl), "panel_pkl_sha256": sha(panel_pkl), "obs_pre2020_dir": str(obs_dir), "obs_files_sha256": obs_files,
                          "events_all_json": str(ev / "events_all.json"), "events_all_sha256": sha(ev / "events_all.json")},
        "development_check": {"dir": str(devcheck_dir), "files_sha256": dev},
        "registration_sha256": sha(REGISTRATION), "spec_sha256": sha(SPEC)}
    doc["annotations"] = {"run_arguments": dict(ra, out_dir=str(out_dir / "run"), dates=HR.DATES, workers=2, erp_shifts=[]),
                          "d1_event_index": {"dir": str(ev), "files": {p.name: sha(p) for p in sorted(ev.iterdir()) if p.is_file()}},
                          "priors_vintages_used": {"2025-dates": 2024, "rule": "vintage = year(T) - 1 (valuation/priors.py)",
                                                   "tables_sha256": {"2024": (D / "priors_v3" / "2024" / "tables.sha256").read_text().strip()}},
                          "price_basis": "D5 daily raw closes, next-session open entry; monthly raw file behind late-starting tickers (M6)", "ledger": str(out_dir / HR.LEDGER_NAME)}
    freeze.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return freeze, sha(freeze)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--panel", required=True, type=Path)
    ap.add_argument("--obs-pre", required=True, type=Path)
    ap.add_argument("--events", required=True, type=Path)
    ap.add_argument("--devcheck", required=True, type=Path)
    a = ap.parse_args(argv)
    freeze, h = build(a.out_dir, a.panel, a.obs_pre, a.events, a.devcheck)
    print(freeze.read_text(encoding="utf-8"))
    print("FREEZE_SHA256", h)


if __name__ == "__main__":
    main()
