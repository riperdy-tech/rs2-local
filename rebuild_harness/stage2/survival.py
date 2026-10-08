"""V2 of Addendum V: the probability that a company fails within 12 months, from point-in-time solvency variables, by a logistic regression fitted on data that were resolved before the valuation date.

THE TARGET.  A D1 exit event of class `bankruptcy`, `bankruptcy_no_exit_record`, `delisted_other` or `deregistered_other` (the classes the survivorship machinery bounds at -100% inside the horizon, Addendum P1) dated
after the observation date t and no later than t + 12 months.  An acquisition is not a failure.  The label comes from the all-events D1 index (`events_all.json`) for EVERY company, whether or not the price
file holds it.

THE VARIABLES (six; all from filings known at t).
  cur_ratio   current assets / current liabilities
  nd_ebitda   (debt + finance leases - cash - short-term investments) / EBITDA, EBITDA = operating income + D&A (operating income where D&A is not filed);
              EBITDA <= 0 with positive net debt is +inf (the worst), with net cash 0.0
  int_cov     operating income / interest expense; no interest expense is +inf (the best)
  ocf_neg     1 if operating cash flow is negative, else 0
  burn_inv    max(0, -operating cash flow) / (cash + short-term investments): the share of liquid assets one year of cash burn consumes, the inverse of the cash runway; 0 when cash flow is
              not negative (the runway is then infinite, which a ratio of runway could not hold); +inf for a burn against no liquid assets
  financial   1 for the financial family (the other variables are mostly not filed by a bank or insurer, and a base rate of its own is the honest minimum)
  NOT USED: the naive distance to default of the specification.  The price file holds today's listings only: a company that failed has no daily price history, so its volatility cannot be formed, and a
  distance to default would be present for every survivor and absent for nearly every failure (measured: the share of failures within 12 months with a one-year volatility is 0 against 99.8% of the
  rest).  Training on it would learn "has a price history" = "survived".  The market value of equity is likewise a public float for those companies, a different basis.  The stage-2 report states this as a deviation from the specification.

THE FIT.  Winsorise each continuous variable at the 1st and 99th percentile of the TRAINING set's finite values (+-inf go to the cut), standardise with the training mean and standard deviation, a missing value takes
the training mean (0 after standardising), ridge-penalised logistic regression (penalty RIDGE on the slopes, none on the intercept), Newton-Raphson.  Nothing of the validation date enters.

THE WINDOW.  Expanding: for the valuation date T the training observations are those at quarter-ends t with t + 12 months <= T, labelled with the events dated before T.  Equity recovery is 0 (stated).

Pure numpy; no scikit-learn in this environment.  0.0 is a value: every test is `is None` or isnan."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

FAIL_CLASSES = ("bankruptcy", "bankruptcy_no_exit_record", "delisted_other", "deregistered_other")
HORIZON_MONTHS = 12
FEATURES = ("cur_ratio", "nd_ebitda", "int_cov", "ocf_neg", "burn_inv", "financial")
CONTINUOUS = ("cur_ratio", "nd_ebitda", "int_cov", "burn_inv")
WINSOR = (0.01, 0.99)
RIDGE = 1.0                      # prior standard deviation 1 per standardised unit of log-odds: fixed before any validation figure, not tuned
MIN_EVENTS = 5                   # a date with fewer training events than this has no model (P(fail) is then undefined, not zero)
INF = float("inf")
NAN = float("nan")


# ---- the variables --------------------------------------------------------------------------------------------------------------------------

def _num(x):
    return x is not None and isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def raw_features(sv: Optional[dict], family: Optional[str]) -> Dict[str, float]:
    """The six variables from the solvency items of `forensics.analytics.solvency_inputs` (None = not filed).  NaN where the variable cannot be formed; +-inf where the ratio is beyond any number."""
    sv = sv or {}
    out = {k: NAN for k in FEATURES}
    out["financial"] = 1.0 if family == "financial" else 0.0
    ca, cl = sv.get("current_assets"), sv.get("current_liabilities")
    if _num(ca) and _num(cl) and cl > 0:
        out["cur_ratio"] = ca / cl
    cash, sti = sv.get("cash"), sv.get("st_investments")
    liquid = (cash + (sti if _num(sti) else 0.0)) if _num(cash) else NAN
    debt, fl = sv.get("debt"), sv.get("finance_leases")
    net_debt = (debt + (fl if _num(fl) else 0.0) - liquid) if (_num(debt) and liquid == liquid) else NAN
    ebit, da = sv.get("operating_income"), sv.get("da")
    ebitda = (ebit + da) if (_num(ebit) and _num(da)) else (ebit if _num(ebit) else NAN)
    if ebitda == ebitda and net_debt == net_debt:
        out["nd_ebitda"] = net_debt / ebitda if ebitda > 0 else (INF if net_debt > 0 else 0.0)
    ie = sv.get("interest_expense")
    if _num(ie) and ie > 0:
        out["int_cov"] = ebit / ie if _num(ebit) else NAN
    elif _num(ie) or (ie is None and _num(debt) and debt == 0):
        out["int_cov"] = INF if _num(ebit) else NAN
    ocf = sv.get("ocf")
    if _num(ocf):
        out["ocf_neg"] = 1.0 if ocf < 0 else 0.0
        burn = max(0.0, -ocf)
        if burn == 0.0:
            out["burn_inv"] = 0.0
        elif liquid == liquid:
            out["burn_inv"] = burn / liquid if liquid > 0 else INF
    return out


def feature_matrix(rows: Iterable[tuple]) -> np.ndarray:
    """(n, 6) array of `raw_features` for (sv, family) pairs."""
    return np.array([[raw_features(sv, fam)[k] for k in FEATURES] for sv, fam in rows], dtype=float).reshape(-1, len(FEATURES))


# ---- the transform --------------------------------------------------------------------------------------------------------------------------

@dataclass
class Transform:
    lo: Dict[str, float] = field(default_factory=dict)
    hi: Dict[str, float] = field(default_factory=dict)
    mean: Dict[str, float] = field(default_factory=dict)
    sd: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def fit(cls, X: np.ndarray) -> "Transform":
        t = cls()
        for j, k in enumerate(FEATURES):
            col = X[:, j]
            if k in CONTINUOUS:
                fin = col[np.isfinite(col)]
                if len(fin) == 0:
                    t.lo[k], t.hi[k] = 0.0, 0.0
                else:
                    t.lo[k], t.hi[k] = float(np.quantile(fin, WINSOR[0])), float(np.quantile(fin, WINSOR[1]))
                col = _winsor(col, t.lo[k], t.hi[k])
            ok = col[~np.isnan(col)]
            t.mean[k] = float(ok.mean()) if len(ok) else 0.0
            sd = float(ok.std()) if len(ok) > 1 else 0.0
            t.sd[k] = sd if sd > 0 else 1.0
        return t

    def apply(self, X: np.ndarray) -> np.ndarray:
        Z = np.empty_like(X, dtype=float)
        for j, k in enumerate(FEATURES):
            col = X[:, j]
            if k in CONTINUOUS:
                col = _winsor(col, self.lo[k], self.hi[k])
            z = (col - self.mean[k]) / self.sd[k]
            Z[:, j] = np.where(np.isnan(z), 0.0, z)
        return Z

    def as_dict(self):
        return {"lo": self.lo, "hi": self.hi, "mean": self.mean, "sd": self.sd}


def _winsor(col: np.ndarray, lo: float, hi: float) -> np.ndarray:
    out = col.astype(float).copy()
    nan = np.isnan(out)
    out = np.clip(np.where(nan, 0.0, out), lo, hi)       # +-inf clip to the cut; NaN restored below
    out[nan] = np.nan
    return out


# ---- the model ------------------------------------------------------------------------------------------------------------------------------

def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


def fit_ridge_logistic(Z: np.ndarray, y: np.ndarray, ridge: float = RIDGE, max_iter: int = 100, tol: float = 1e-10):
    """(intercept, slopes): maximise sum[y log p + (1-y) log(1-p)] - ridge/2 |slopes|^2 by Newton-Raphson (the objective is strictly concave: the ridge makes a separable sample finite)."""
    n, k = Z.shape
    A = np.column_stack([np.ones(n), Z])
    pen = np.diag([0.0] + [ridge] * k)
    p0 = min(max(float(y.mean()), 1e-6), 1 - 1e-6)
    beta = np.zeros(k + 1)
    beta[0] = math.log(p0 / (1 - p0))

    def neg_obj(b):
        z = A @ b
        return float(np.sum(np.logaddexp(0.0, z) - y * z) + 0.5 * b @ pen @ b)

    f = neg_obj(beta)
    for _ in range(max_iter):
        p = _sigmoid(A @ beta)
        g = A.T @ (y - p) - pen @ beta
        W = np.maximum(p * (1 - p), 1e-12)
        H = (A * W[:, None]).T @ A + pen
        step = np.linalg.solve(H, g)
        t = 1.0
        while t > 1e-10:                                         # backtracking: a full Newton step overshoots when the probabilities saturate
            f_new = neg_obj(beta + t * step)
            if f_new <= f - 1e-4 * t * float(g @ step):
                break
            t *= 0.5
        else:
            break
        beta = beta + t * step
        done = abs(f - f_new) < tol * max(1.0, abs(f))
        f = f_new
        if done:
            break
    return float(beta[0]), beta[1:].copy()


def auc(score: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney AUC (ties count one half); NaN when a class is empty."""
    score, y = np.asarray(score, dtype=float), np.asarray(y)
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return NAN
    r = pd.Series(score).rank(method="average").to_numpy()
    return float((r[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


@dataclass
class SurvivalModel:
    asof: str
    transform: Transform
    intercept: float
    coef: np.ndarray
    n_train: int
    n_events: int
    train_dates: List[str]
    ridge: float = RIDGE

    def predict(self, X: np.ndarray) -> np.ndarray:
        return _sigmoid(self.intercept + self.transform.apply(X) @ self.coef)

    def as_dict(self) -> dict:
        return {"asof": self.asof, "intercept": self.intercept, "coef": dict(zip(FEATURES, [float(c) for c in self.coef])), "transform": self.transform.as_dict(), "n_train": self.n_train,
                "n_events": self.n_events, "train_dates": self.train_dates, "ridge": self.ridge, "winsor": list(WINSOR), "features": list(FEATURES)}


# ---- labels ---------------------------------------------------------------------------------------------------------------------------------

def load_fail_events(path, classes: Sequence[str] = FAIL_CLASSES) -> Dict[str, np.ndarray]:
    """{cik: sorted datetime64[D] array of the dates of its events of the failure classes} from the all-events D1 index."""
    ev = json.loads(Path(path).read_text(encoding="utf-8"))
    by: Dict[str, list] = {}
    for e in ev:
        if e["class"] in classes:
            by.setdefault(str(e["cik"]).zfill(10), []).append(e["date"])
    return {c: np.sort(np.array(v, dtype="datetime64[D]")) for c, v in by.items()}


def add_months(date, months: int = HORIZON_MONTHS) -> pd.Timestamp:
    return pd.Timestamp(date) + pd.DateOffset(months=months)


def label_failure(cik: str, t, events: Dict[str, np.ndarray], known_before=None, months: int = HORIZON_MONTHS) -> int:
    """1 when the company has an event of a failure class dated after t and no later than t + `months`; with `known_before` only events dated before that day count (the training rule: an
    event dated on or after the valuation date T is not known at T)."""
    ev = events.get(str(cik).zfill(10))
    if ev is None or len(ev) == 0:
        return 0
    lo = np.datetime64(pd.Timestamp(t).date())
    hi = np.datetime64(add_months(t, months).date())
    if known_before is not None:
        kb = np.datetime64(pd.Timestamp(known_before).date()) - np.timedelta64(1, "D")
        hi = min(hi, kb)
    return int(((ev > lo) & (ev <= hi)).any())


# ---- the expanding window -------------------------------------------------------------------------------------------------------------------

def training_mask(dates: pd.Series, T, months: int = HORIZON_MONTHS) -> np.ndarray:
    """Observations at t with t + months <= T (their 12-month outcome has been fully observed by T)."""
    T = pd.Timestamp(T)
    return np.array([add_months(d, months) <= T for d in dates], dtype=bool)


def fit_for_date(obs: pd.DataFrame, T, events: Dict[str, np.ndarray], ridge: float = RIDGE, min_events: int = MIN_EVENTS) -> Optional[SurvivalModel]:
    """The model for valuation date T from `obs` (columns date, cik, family, and the six raw variables `FEATURES`): the observations resolved by T, labelled with the events dated before T.
    None when fewer than `min_events` failures are in the training set (no model; the caller states it)."""
    mask = training_mask(obs["date"], T)
    tr = obs[mask]
    if len(tr) == 0:
        return None
    y = np.array([label_failure(c, d, events, known_before=T) for c, d in zip(tr["cik"], tr["date"])], dtype=float)
    if y.sum() < min_events:
        return None
    X = tr[list(FEATURES)].to_numpy(dtype=float)
    tf = Transform.fit(X)
    b0, b = fit_ridge_logistic(tf.apply(X), y, ridge)
    return SurvivalModel(asof=str(pd.Timestamp(T).date()), transform=tf, intercept=b0, coef=b, n_train=int(len(tr)), n_events=int(y.sum()), train_dates=sorted(set(map(str, tr["date"]))), ridge=ridge)


def with_features(df: pd.DataFrame, sv_col: Optional[str] = None) -> pd.DataFrame:
    """Add the six raw variables to a frame that holds the solvency items either as a dict column `sv` (lean observations) or as the panel's flat `sv_*` columns."""
    out = df.copy()
    if sv_col is not None:
        feats = [raw_features(s, f) for s, f in zip(out[sv_col], out["family"])]
    else:
        keys = ("current_assets", "current_liabilities", "cash", "st_investments", "debt", "operating_income", "da", "interest_expense", "ocf", "finance_leases")
        feats = []
        for rec in out[["family"] + ["sv_" + k for k in keys]].to_dict("records"):
            sv = {k: (None if rec["sv_" + k] is None or rec["sv_" + k] != rec["sv_" + k] else rec["sv_" + k]) for k in keys}
            feats.append(raw_features(sv, rec["family"]))
    for k in FEATURES:
        out[k] = [f[k] for f in feats]
    return out
