"""stage2_layer.py - the Stage 2 configuration (SPEC_rebuild.md Addendum V; binding for gate 2 by Addendum W) on BOTH arms of gate 2.

Addendum W: "The CODE arm is the Stage 2 configuration (V1 + V2 + V3 on the frozen engine)", and the MUSE arm is valued the same way, so that the pair differs only in the placed inputs.

    V1  the value of an arm is the MEAN of the engine's per-share equity draws (each draw floored at 0 by the engine), not the median.  The engine already summarises it
        (`iv_per_share.mean` of `code_only` and of `final`); nothing is recomputed from draws.
    V2  value = mean IV x (1 - P(fail within 12 months)); the equity recovery is 0.  P(fail) is the logistic model of `rebuild_harness/stage2/survival.py` (same six variables, winsor, ridge
        1.0, Newton fit, minimum 5 events), fitted for each replay date T from data resolved before T ONLY: the quarter-end observations t with t + 12 months <= T, labelled with the D1
        failure events dated before T (an expanding window).  Training observations: the forensic panel (the 20 quarter-ends 2020-2024), the lean observations of 2016-2019, and the lean
        observations of 2025-03-31 and 2025-06-30 built for this job (they are the only 2025 quarter-ends that satisfy t + 12 months <= T for a replay date).  P(fail) is a property of the
        company-date, so both arms share it; it is formed from the filings known at T, before any model call, and written once (`stage2/survival_pfail.json`).
    V3  the commodity family is out of scope for both arms: `sample.draw_date` leaves it out of the draw and `scoring.load_rows` refuses a commodity row.
    V4  (verdict quintiles within industry) and V5 (the expectation gap) are not part of gate 2's bars and are not formed here.

`fit_models` is the only place a model is fitted; `build_pfail_table` is the only place a probability is formed.  Both write their file with exclusive creation: a table is never overwritten.
0.0 is a value: every test is `is None` or isnan.  CPU only; no model, no server, no network.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from . import config

PANEL_PKL = config.WORKSPACE / "scratch" / "rev23" / "forensics" / "analysis" / "panel_q20.pkl"
OBS_PRE2020 = config.WORKSPACE / "scratch" / "rev23" / "stage2_data" / "obs_pre2020"
EVENTS_ALL = config.WORKSPACE / "data" / "sec_bulk" / "index_P4b" / "events_all.json"
OBS_2025_DATES = ("2025-03-31", "2025-06-30")
LAYERS = {
    "V1": "value = mean of the engine's per-share equity draws (floored at 0 per draw by the engine); not the median",
    "V2": "value = mean IV x (1 - P(fail within 12 months)), equity recovery 0; P(fail) from the point-in-time ridge-logistic model fitted for each replay date from observations resolved before it",
    "V3": "the commodity family is out of scope for both arms",
}


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def stage2_paths(state_dir=None) -> dict:
    root = config.state_paths(state_dir)["stage2"]
    return {"root": root, "obs": root / "obs_2025", "models": root / "survival_models.json", "pfail": root / "survival_pfail.json"}


def job_key(date: str, cik: str) -> str:
    return f"{date}_{str(cik).zfill(10)}"


# ---- V1 / V2: the value ---------------------------------------------------------------------------------------------------------------------

def value_ps(mean_ps, p_fail) -> Optional[float]:
    """The registered value of one arm: mean IV per share x (1 - P(fail)).  None when either is missing or not finite (never a silent 0: an arm without a value is not scored)."""
    for x in (mean_ps, p_fail):
        if x is None or isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            return None
    return float(mean_ps) * (1.0 - float(p_fail))


# ---- the training pool and the models -------------------------------------------------------------------------------------------------------

def training_inputs(state_dir=None, *, panel_pkl=PANEL_PKL, obs_pre=OBS_PRE2020, events=EVENTS_ALL) -> dict:
    """Where the training data are and their hashes (the freeze records them)."""
    p = stage2_paths(state_dir)
    obs_files = {}
    for d in (Path(obs_pre), p["obs"]):
        for f in sorted(Path(d).glob("obs_*.jsonl.gz")):
            obs_files[f"{Path(d).name}/{f.name}"] = sha256_file(f)
    return {"panel_pkl": str(panel_pkl), "panel_pkl_sha256": sha256_file(panel_pkl), "obs_dirs": [str(obs_pre), str(p["obs"])], "obs_files_sha256": obs_files,
            "events_all_json": str(events), "events_all_sha256": sha256_file(events)}


def load_pool(state_dir=None, *, panel_pkl=PANEL_PKL, obs_pre=OBS_PRE2020) -> pd.DataFrame:
    """The training pool: the panel's non-commodity rows of 2020-2024 and the lean observations (2016-2019 and the two 2025 quarter-ends), non-commodity (V3)."""
    from rebuild_harness.stage2 import devcheck as DC
    from rebuild_harness.stage2 import layers as L
    from rebuild_harness.stage2 import survival as S
    panel = L.add_dispersion(S.with_features(pd.read_pickle(panel_pkl).reset_index(drop=True)))
    parts = [DC.load_obs(obs_pre)]
    obs25 = stage2_paths(state_dir)["obs"]
    if obs25.is_dir() and any(obs25.glob("obs_*.jsonl.gz")):
        parts.append(DC.load_obs(obs25))
    obs = pd.concat([x for x in parts if len(x)], ignore_index=True)
    return DC.training_pool(panel, obs)


def fit_models(dates: Sequence[str], pool: pd.DataFrame, events: Mapping) -> Dict[str, dict]:
    """{date: SurvivalModel.as_dict()}: for each T the model fitted from the observations resolved before T.  A date that cannot be fitted raises (no silent default)."""
    from rebuild_harness.stage2 import survival as S
    out = {}
    for d in dates:
        m = S.fit_for_date(pool, d, events)
        if m is None:
            raise RuntimeError(f"no survival model can be fitted for {d}: fewer than {S.MIN_EVENTS} failures resolved before it")
        out[d] = m.as_dict()
    return out


def write_models(state_dir=None, dates: Sequence[str] = config.DATES, **kw) -> dict:
    """Fit and write `stage2/survival_models.json` once (exclusive creation).  Returns the document."""
    from rebuild_harness.stage2 import survival as S
    p = stage2_paths(state_dir)
    if p["models"].exists():
        raise FileExistsError(f"{p['models']} exists: the models are fitted once")
    pool = load_pool(state_dir, **{k: v for k, v in kw.items() if k in ("panel_pkl", "obs_pre")})
    events = S.load_fail_events(kw.get("events", EVENTS_ALL))
    inputs = training_inputs(state_dir, **kw)
    doc = {"layers": LAYERS, "training_data": inputs, "n_pool": int(len(pool)),
           "settings": {"features": list(S.FEATURES), "continuous": list(S.CONTINUOUS), "winsor": list(S.WINSOR), "ridge": S.RIDGE, "min_events": S.MIN_EVENTS,
                        "horizon_months": S.HORIZON_MONTHS, "fail_classes": list(S.FAIL_CLASSES),
                        "training_rule": "observations at quarter-ends t with t + 12 months <= T, non-commodity, market cap (public float for the census) >= $300M; labels: D1 failure events "
                                         "dated after t, no later than t + 12 months and before T"},
           "models": fit_models(dates, pool, events)}
    p["root"].mkdir(parents=True, exist_ok=True)
    with open(p["models"], "x", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, indent=1, sort_keys=True))
    return doc


def load_models(state_dir=None) -> Dict[str, "SurvivalModel"]:
    from rebuild_harness.stage2 import survival as S
    doc = json.loads(stage2_paths(state_dir)["models"].read_text(encoding="utf-8"))
    return {d: S.SurvivalModel.from_dict(m) for d, m in doc["models"].items()}


# ---- P(fail) of a company-date ---------------------------------------------------------------------------------------------------------------

def _jf(x):
    """A JSON-safe float: NaN -> None, +-inf -> "inf" / "-inf" (the survival variables use infinities as values)."""
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, float) and math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return x


def pfail_of(model, pit, family: str) -> dict:
    """P(fail) of one company-date from its point-in-time company object `pit` (the one the engine is given): the six variables of the base-year items, then the model of its date."""
    from valuation.common import build_state
    from rebuild_harness.forensics import analytics as A
    from rebuild_harness.stage2 import survival as S
    sv = A.solvency_inputs(pit, build_state(pit))
    feats = S.raw_features(sv, family)
    p = float(model.predict(np.array([[feats[k] for k in S.FEATURES]], dtype=float))[0])
    return {"p_fail": p, "features": {k: _jf(float(feats[k])) for k in S.FEATURES}, "solvency_items": {k: _jf(v) for k, v in sv.items()}, "model_asof": model.asof}


def build_pfail_table(jobs: Iterable[Mapping], env, models: Mapping, log=print) -> dict:
    """{key: {"status": "ok", "p_fail", "features", ...} | {"status": <refusal status>, "p_fail": None, "reasons"}} for every (date, company) of the sample.  `env.company_inputs(job)` is the
    runner's own: the same point-in-time company the engine will be given, so a name the runner will refuse is refused here for the same reason."""
    from . import env as env_mod
    out = {}
    jobs = list(jobs)
    for i, job in enumerate(jobs):
        key = job_key(job["date"], job["cik"])
        ci = env.company_inputs(job)
        if isinstance(ci, env_mod.Refusal):
            out[key] = {"status": ci.status, "p_fail": None, "reasons": list(ci.reasons)[:3]}
        else:
            row = pfail_of(models[job["date"]], ci.pit, ci.family)
            out[key] = dict(row, status="ok", family=ci.family)
        if (i + 1) % 100 == 0:
            log(f"p_fail {i + 1}/{len(jobs)}")
    return out


def write_pfail(table: Mapping, models_sha256: str, sample_sha256: str, state_dir=None) -> str:
    """Write `stage2/survival_pfail.json` once (exclusive creation); returns its sha256."""
    p = stage2_paths(state_dir)
    doc = {"layers": LAYERS, "models_file_sha256": models_sha256, "sample_sha256": sample_sha256, "n": len(table),
           "n_ok": sum(1 for r in table.values() if r["status"] == "ok"), "rows": dict(sorted(table.items()))}
    p["root"].mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, indent=1, sort_keys=True).encode("utf-8")
    with open(p["pfail"], "xb") as fh:
        fh.write(data)
    return hashlib.sha256(data).hexdigest()


def load_pfail(state_dir=None) -> Dict[str, dict]:
    p = stage2_paths(state_dir)["pfail"]
    if not p.exists():
        raise FileNotFoundError(f"{p} is missing: the survival probabilities are formed in the preparation (python -m rebuild_harness.gate2.stage2_layer pfail)")
    return json.loads(p.read_text(encoding="utf-8"))["rows"]


# ---- command line ----------------------------------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["models", "pfail"])
    ap.add_argument("--state-dir", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "models":
        doc = write_models(a.state_dir)
        for d, m in doc["models"].items():
            print(d, "n_train", m["n_train"], "n_events", m["n_events"], "train quarter-ends", m["train_dates"][0], "..", m["train_dates"][-1], "(", len(m["train_dates"]), ")")
        print("written", stage2_paths(a.state_dir)["models"])
        return 0
    from . import env as env_mod
    from . import sample as sample_mod
    from rebuild_harness import gate1_run as g
    smp = sample_mod.load_verified(sample_mod.sample_path(a.state_dir))
    models = load_models(a.state_dir)
    ev = env_mod.RealEnv(state_dir=a.state_dir, store=g.DEFAULT_STORE, id_map=g.DEFAULT_IDMAP, prices_daily=config.WORKSPACE / "data" / "prices_daily", prices_monthly=g.DEFAULT_PRICES,
                         headers=g.DEFAULT_HEADERS, crosswalk=g.DEFAULT_CROSSWALK, sic=g.DEFAULT_SIC, priors_dir=config.WORKSPACE / "data" / "priors_v3", strict_classification=True,
                         submissions_zip=config.WORKSPACE / "data" / "sec_bulk" / "submissions.zip", fetch_documents=False)
    table = build_pfail_table(sample_mod.jobs(smp), ev, models)
    sha = write_pfail(table, sha256_file(stage2_paths(a.state_dir)["models"]), sample_mod.sha256_file(sample_mod.sample_path(a.state_dir)), a.state_dir)
    print("written", stage2_paths(a.state_dir)["pfail"], "sha256", sha, "ok", sum(1 for r in table.values() if r["status"] == "ok"), "of", len(table))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
