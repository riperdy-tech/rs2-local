"""Shared helpers for the gate-1b leakage and artefact audit (branch review-2026-10/leak-audit).  Audit code only: it reads the gate-1b outputs, never writes under them, never touches the engine,
the stage2 code, wt-gate2, data/gate2 or the GPU, and uses one process.

    from leak_audit import lib   (run from the worktree root so that `valuation` and `rebuild_harness` import)

H1/H2 are recomputed with the REGISTERED code (`gate1_v2.b1_pooled` / `b2_v2`) on the compact rows of the run, with a score override and an optional row filter, so that every variant is
comparable with the registered figures (H1 +0.207 / +0.170 / +0.186; H2 +8.2 / +7.6 / +8.3 pp).
0.0 is a value: tests are `is None` / isnan."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rebuild_harness import gate1_metrics as gm            # noqa: E402
from rebuild_harness import gate1_v2 as v2m                # noqa: E402
from rebuild_harness import metrics as hm                  # noqa: E402

WS = Path(r"C:\Users\riper\stocks\stocks-workspace")
GATE = WS / "scratch" / "rev23" / "gate1b_holdout"
RUN = GATE / "run"
PANEL = GATE / "report" / "panel_scored.pkl"
OUT = WS / "scratch" / "rev23" / "leak_audit"
FOREN = WS / "scratch" / "rev23" / "forensics" / "analysis"
D5 = WS / "data" / "prices_daily"
BOUNDS = gm.BOUNDS
YARDS = gm.YARDSTICKS
DATES = ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-30", "2025-07-31", "2025-08-29", "2025-09-30"]


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def dump(obj, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(clean(obj), indent=1, default=str), encoding="utf-8")


def load_panel() -> pd.DataFrame:
    return pd.read_pickle(PANEL)


def load_rows(panel: pd.DataFrame | None = None, col: str = "s_cfg"):
    """The registered rows: compact valued rows of mcap >= $300M whose (date, cik) is in the in-scope panel with a score in `col`; each row gets `r['_k']` = (date, cik)."""
    panel = load_panel() if panel is None else panel
    ok = panel[panel[col].notna() & (panel["family"] != "commodity")]            # V3: the commodity family is out of the universe
    keys = set(zip(ok["date"], ok["cik"]))
    rows, _c, _f = gm.load_run(RUN)
    rows = [r for r in rows if r.get("mcap_group") == ">=300M" and (r["date"], r["cik"]) in keys]
    for r in rows:
        r["_k"] = (r["date"], r["cik"])
    return rows


def key_map(panel: pd.DataFrame, col: str) -> dict:
    return {(d, c): float(v) for d, c, v in zip(panel["date"], panel["cik"], panel[col]) if v is not None and v == v}


def b1_point(rows, bound, score_fn, yardsticks=YARDS, effects="industry"):
    """The pooled B1 coefficient only (no bootstrap): the registered design, absorbed date and industry effects."""
    pn = v2m.build_panel(rows, bound, score_fn, yardsticks)
    if pn is None or len(pn["y"]) < v2m.MIN_PANEL or pn["n_dates"] < 3:
        return {"beta": float("nan"), "n": 0 if pn is None else len(pn["y"])}
    beta, u, Xt, yt = v2m.fe_ols(pn["y"], pn["X"], v2m._factors(pn, effects))
    se = v2m.cluster_se(Xt, u, pn["date"], 0)
    return {"beta": float(beta[0]), "se": se, "t": float(beta[0] / se) if se > 0 else float("nan"), "n": int(len(pn["y"]))}


def bars(rows, score_fn, n_boot=0, yardsticks=YARDS, bounds=BOUNDS, b2_group="industry"):
    """{bound: {"H1": beta (and lower bound if n_boot>0), "H2": mean residual spread (pp), "H2_raw", "n"}}; `n_boot=0` gives the point estimates only."""
    out = {}
    for b in bounds:
        if n_boot > 0:
            r1 = v2m.b1_pooled(rows, b, score_fn=score_fn, n_boot=n_boot, yardsticks=yardsticks)
            h1 = {"beta": r1.get("beta"), "lb90": r1.get("lower_90_one_sided"), "t": r1.get("t"), "n": r1.get("n")}
        else:
            r1 = b1_point(rows, b, score_fn, yardsticks)
            h1 = {"beta": r1.get("beta"), "lb90": None, "t": r1.get("t"), "n": r1.get("n")}
        r2 = v2m.b2_v2(rows, b, score_fn=score_fn, group=b2_group, yardsticks=yardsticks, n_resamples=20)
        out[b] = {"H1": h1["beta"], "H1_lb90": h1["lb90"], "H1_t": h1["t"], "H2_pp": (None if r2["mean_spread_residual"] != r2["mean_spread_residual"] else 100 * r2["mean_spread_residual"]),
                  "H2_raw_pp": (None if r2["mean_spread_raw"] != r2["mean_spread_raw"] else 100 * r2["mean_spread_raw"]), "n": h1["n"], "n_dates": r2["n_dates"],
                  "H2_by_date_pp": {d: (None if v["spread_residual"] != v["spread_residual"] else 100 * v["spread_residual"]) for d, v in r2["by_date"].items()}}
    return out


def fmt(res, lb=True) -> str:
    """One-line summary of `bars` output."""
    def f(x, nd=3):
        return "n/a" if x is None else f"{x:+.{nd}f}"
    parts = []
    for b in BOUNDS:
        x = res[b]
        s = f"{f(x['H1'])}" + (f" (lb {f(x['H1_lb90'])})" if (lb and x.get("H1_lb90") is not None) else "") + f" | {f(x['H2_pp'], 1)}pp"
        parts.append(s)
    return " ;; ".join(parts) + f"   n={res['excluded']['n']}"
