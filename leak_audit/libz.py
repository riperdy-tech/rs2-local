"""Addendum Z item 9 helpers (branch review-2026-10/leak-audit).  Audit code only; outputs go to scratch/rev23/leak_audit_z/.  Reads the gate-1b outputs, the forensic dev panel, D5 prices and the local SEC archive.
Never touches the engine, wt-gate2, data/gate2 or the GPU; one process.  0.0 is a value: tests are `is None` / isnan.

MAIN-RESULT RULE (Addendum Z 4): a delisted name with no observed traded price at T (the 'census' names: priced by a stale public-float proxy, no D5 file) is excluded from main results (survivor == False is
the main universe); the census names appear only in labelled sensitivity rows."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from leak_audit import lib

OLD = lib.OUT                                     # scratch/rev23/leak_audit (the Addendum-Y audit; read only)
OUT = lib.WS / "scratch" / "rev23" / "leak_audit_z"
lib.OUT = OUT                                     # lib.dump writes here
DEV_PANEL = lib.FOREN / "panel_q20.pkl"
SUBMISSIONS = lib.WS / "data" / "sec_bulk" / "submissions.zip"
D5 = lib.D5
HOLD_DATES = lib.DATES


def dump(obj, name):
    OUT.mkdir(parents=True, exist_ok=True)
    lib.dump(obj, name)


def load_dev() -> pd.DataFrame:
    d = pd.read_pickle(DEV_PANEL)
    return d[d.family != "commodity"].reset_index(drop=True)


def load_hold() -> pd.DataFrame:
    p = lib.load_panel()
    return p[(p.family != "commodity") & p.s_cfg.notna()].reset_index(drop=True)


Y5 = ("y_ey", "y_fcfy", "y_gp", "y_roc", "y_mom")


def dev_bars(df: pd.DataFrame, score: str = "vp_mean", n_boot: int = 0, controls=(), bounds=("excluded", "minus100", "last_close")) -> dict:
    """H1 (pooled B1 coefficient, one-sided 90% wild-cluster lower bound when n_boot>0) and H2 (residual and raw industry-neutral quintile spread, pp) of the development panel at 12 months, by the
    forensic machinery (fxm = the registered construction with the horizon as a parameter), as a10c_dev_controls does."""
    from rebuild_harness.forensics import fxm
    out = {}
    for b in bounds:
        dd = df[df[score].notna()]
        c = fxm.pooled_coef(dd, dd[score], 12, b, Y5, control_cols=controls, n_boot=n_boot)
        pdd = fxm.per_date(dd, score, 12, b, Y5, extra_resid_cols=controls)
        h2 = pdd["spread_resid"].dropna()
        h2r = pdd["spread_raw"].dropna()
        out[b] = {"H1": None if c is None else c["beta"], "H1_lb90": None if c is None else c.get("lower90"), "H1_t": None if c is None else c["t"], "n": None if c is None else c["n"],
                  "H2_pp": 100 * float(h2.mean()) if len(h2) else None, "H2_raw_pp": 100 * float(h2r.mean()) if len(h2r) else None, "n_dates": int(len(h2))}
    return out


def fmt_dev(res) -> str:
    def f(x, nd=3):
        return "n/a" if x is None else f"{x:+.{nd}f}"
    return " ;; ".join(f"{f(res[b]['H1'])}" + (f" (lb {f(res[b]['H1_lb90'])})" if res[b].get("H1_lb90") is not None else "") + f" | {f(res[b]['H2_pp'], 1)}pp" for b in res) + f"   n={res['excluded']['n']}"


def hold_keys(df, mask) -> set:
    return set(zip(df.loc[mask, "date"], df.loc[mask, "cik"]))


def within_industry_quintile(df: pd.DataFrame, score: str, min_ind: int = 5, min_q: int = 25) -> pd.Series:
    """The registered quintile membership (gate1_metrics._neutral_spread): per date, the score's percentile rank WITHIN its industry (industries with >= 5 names of the date), then quintiles of that rank across
    the date's eligible names by sorted order ((arange(n)*5)//n, mergesort).  Returns 0..4 (4 = top), NaN where not eligible.  Needs only the score (no outcome): membership cannot depend on a return."""
    from rebuild_harness import metrics as hm
    out = pd.Series(np.nan, index=df.index)
    for d, idx in df.groupby("date").groups.items():
        sub = df.loc[idx]
        s = sub[score].to_numpy(dtype=float)
        ok = np.isfinite(s)
        sub, s = sub[ok], s[ok]
        inds = np.array([i if isinstance(i, str) else "unknown" for i in sub["industry"].tolist()])
        rank = np.full(len(s), np.nan)
        for k in set(inds.tolist()):
            m = np.where(inds == k)[0]
            if len(m) < min_ind:
                continue
            rank[m] = hm.pct_rank(s[m])
        el = ~np.isnan(rank)
        if el.sum() < min_q:
            continue
        pos = np.where(el)[0]
        order = np.argsort(rank[el], kind="mergesort")
        grp = np.empty(len(pos), dtype=int)
        grp[order] = (np.arange(len(pos)) * 5) // len(pos)
        out.loc[sub.index[pos]] = grp
    return out


def month_ends(T, n=4):
    """S_0 = T, S_1 .. S_{n-1}: the calendar month-ends 0, 1, ... months after the month of T (T is a month-end of the panel)."""
    import calendar
    from datetime import date as _date
    out = []
    for k in range(n):
        idx = T.year * 12 + (T.month - 1) + k
        y, m0 = divmod(idx, 12)
        out.append(_date(y, m0 + 1, calendar.monthrange(y, m0 + 1)[1]))
    return out
