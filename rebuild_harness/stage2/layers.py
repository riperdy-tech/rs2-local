"""V1, V3, V4 and the assembly of V2 (Addendum V): layers on top of the frozen engine's output.  The engine files are not touched; every function here takes the forensic panel (`forensics.panel`) or the
engine's per-name draw summary and returns a score, a dispersion or a mask.

V1  the value is the MEAN of the IV draws (each draw's equity already floored at 0 by the engine), per share, divided by the price.  Guard: ln(P90 / P10) of the draws, entered as an extra control in the B1 and B2
    checks.  A P10 of 0 (the lower tail is wiped out) is an infinite ratio: +inf, which ranks as the widest.  A P90 of 0 or less (no draw has a positive value) leaves it undefined: NaN.
V2  value = mean IV x (1 - P(fail within 12 months)); the equity recovery is 0.
V3  the commodity family is `family_not_built`: out of the universe for every bar.
V4  the percentile rank of the score among the names of the SAME industry on the date; an industry with fewer than `MIN_INDUSTRY` names takes the date-wide rank (annotated, never dropped).

0.0 is a value: every test is `is None` or isnan."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from rebuild_harness import gate1_metrics as gm
from rebuild_harness.forensics import fxm

MIN_INDUSTRY = gm.MIN_INDUSTRY
OUT_OF_SCOPE_FAMILIES = ("commodity",)


def v1_value_ps(draws_equity_ps) -> Optional[float]:
    """The mean of the per-share equity values of the valid draws (each already floored at 0), or None when there are none."""
    a = np.asarray(draws_equity_ps, dtype=float)
    return float(a.mean()) if a.size else None


def dispersion(p10, p90) -> float:
    """ln(P90 / P10) of the draws: +inf when P10 <= 0 < P90, NaN when P90 <= 0 or either is missing."""
    if p10 is None or p90 is None or not (math.isfinite(p10) and math.isfinite(p90)):
        return float("nan")
    if p90 <= 0:
        return float("nan")
    if p10 <= 0:
        return float("inf")
    return math.log(p90 / p10)


def add_dispersion(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["disp"] = [dispersion(a, b) for a, b in zip(out["vp_p10"], out["vp_p90"])]
    return out


def v2_score(vp_mean, pfail):
    """Mean IV / price x (1 - P(fail)); NaN where P(fail) is undefined (no model for the date)."""
    return np.asarray(vp_mean, dtype=float) * (1.0 - np.asarray(pfail, dtype=float))


def v3_in_scope(df: pd.DataFrame) -> pd.Series:
    """True for a name whose family is built (V3: the commodity family is out of the universe)."""
    return ~df["family"].isin(OUT_OF_SCOPE_FAMILIES)


def v4_rank(df: pd.DataFrame, col: str, min_industry: int = MIN_INDUSTRY) -> pd.Series:
    """Percentile rank of `col` among the names of the same industry on the date; a smaller industry takes the date-wide rank.  NaN stays NaN."""
    wide = df.groupby("date")[col].transform(fxm.rank_nan)
    inner = df.groupby(["date", "industry"])[col].transform(fxm.rank_nan)
    n = df.groupby(["date", "industry"])[col].transform(lambda s: s.notna().sum())
    return inner.where(n >= min_industry, wide)
