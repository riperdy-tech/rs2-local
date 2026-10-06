"""common.py - shared types and arithmetic for the valuation package.

THE DATA INTERFACE (Addendum A of SPEC_rebuild.md). Every function in this package takes `asof` and reads its facts from a
`CompanyPIT`, which holds FILED values, each with its filing date and accession, taken as first filed:

  * a value counts only if its filing date is STRICTLY BEFORE the valuation date;
  * a fiscal period exists only from its own annual report (10-K, 20-F, 40-F); the value of a period comes from that report;
  * nothing is filled from a current snapshot: a value that is not filed is None ("not available").

`CompanyPIT` re-checks the first rule on construction and raises PITViolation, so a source that leaks cannot get past the engines.
The shared layer (valuation/pit_data.py) produces `CompanyPIT` objects through `valuation/pit_adapter.py`; `valuation/pit_companyfacts.py`, the INTERIM adapter
over the SEC companyfacts files, is kept for its own tests only.

Conventions: 0.0 is a value (`is None`, never `or`, for numerics); rates are fractions; money is in the filing's own units.
"""
from __future__ import annotations

import hashlib
import math
import random
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parents[1]
for _p in (HERE, HERE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import throughcycle_record as tcr  # noqa: E402  (pure functions; the repo's single owner of tax rate, tangible equity, short-term debt, NWC)

MAX_HORIZON = 25                  # SPEC 3.1 (A5): the explicit horizon is at most 25 years
TERMINAL_G_ANCHOR = 0.0375        # Addendum H2: the long-run nominal growth anchor of the stable-growth convention
ANNUAL_FORMS = ("10-K", "10-K405", "10-KT", "20-F", "40-F")
NORMAL = statistics.NormalDist()
DEFAULT_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


class PITViolation(Exception):
    """A value dated on or after the valuation date reached a function that must be point-in-time."""


class DataNotPresent(Exception):
    """A data set or an input the method needs is not there. A refusal, never a fallback."""


class InputError(ValueError):
    """An input is malformed (a curve out of range, a horizon past 25 years, a non-monotone quantile set)."""


# ---- dates ---------------------------------------------------------------------------------------------------------------------

def parse_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()


def num(v):
    """v as a float when it is a real number, else None. 0.0 is a value."""
    return tcr._num(v)


# ---- point-in-time data ----------------------------------------------------------------------------------------------------------

# canonical annual fields the package reads (same names as the screener's history, so priors and the harness share vocabulary)
FIELDS = (
    "revenue", "operating_income", "pretax_income", "tax_provision", "net_income", "da", "capex", "ppe_net",
    "cash", "st_investments", "lt_investments", "debt_current", "short_term_borrowings_separate", "debt_lt_noncurrent",
    "finance_lease_liability", "operating_lease_liability", "equity", "equity_incl_nci", "goodwill",
    "intangibles_ex_goodwill", "amortization_intangibles", "interest_expense", "total_assets", "total_liabilities",
    "current_assets", "current_liabilities", "insurance_reserves", "preferred_equity", "ocf",
)


@dataclass(frozen=True)
class Filed:
    """One filed value: what it is, the period it describes, and the filing it first appeared in."""
    value: float
    period_end: str
    filed: str
    accession: str
    form: str = ""
    tag: str = ""
    period_start: Optional[str] = None


@dataclass(frozen=True)
class SicInfo:
    code: Optional[str]
    description: str = ""
    source: str = ""             # e.g. "SEC submissions JSON (current assignment)"
    point_in_time: bool = False  # SEC publishes only the CURRENT SIC; True only if a source holds a dated history


@dataclass
class CompanyPIT:
    """Filed facts of one company as of `asof`.

    series[field][period_end] -> Filed        canonical annual fields (revenue, operating_income, ... see FIELDS)
    concepts[name][period_end] -> Filed       further XBRL concepts by their us-gaap name (insurance, ASC 932, lending tags)
    annual_reports                            [(period_end, filed, accession, form)] of the annual reports filed before asof
    """
    ticker: str
    asof: date
    series: Dict[str, Dict[str, Filed]] = field(default_factory=dict)
    concepts: Dict[str, Dict[str, Filed]] = field(default_factory=dict)
    annual_reports: List[tuple] = field(default_factory=list)
    sic: Optional[SicInfo] = None
    cik: Optional[str] = None
    shares_outstanding: Optional[Filed] = None
    notes: List[str] = field(default_factory=list)
    same_day_ok: set = field(default_factory=set)      # accessions filed ON `asof` that the layer certified as accepted by the 16:00 ET decision time (Addendum C 2)

    def __post_init__(self):
        self.asof = parse_date(self.asof)
        self.check()

    def check(self):
        """PITViolation unless every value and every annual report was filed strictly before `asof` - or on `asof` itself with an accession the layer certified in
        `same_day_ok` (accepted at or before 16:00 ET: the decision-time rule of Addendum C 2 replaces "strictly before")."""
        bad = []

        def late(filed, accn):
            d = parse_date(filed)
            return d > self.asof or (d == self.asof and accn not in self.same_day_ok)
        for tab in (self.series, self.concepts):
            for name, per in tab.items():
                for pe, f in per.items():
                    if late(f.filed, f.accession):
                        bad.append((name, pe, f.filed))
        for ar in self.annual_reports:
            if late(ar[1], ar[2]):
                bad.append(("annual_report", ar[0], ar[1]))
        if self.shares_outstanding is not None and late(self.shares_outstanding.filed, self.shares_outstanding.accession):
            bad.append(("shares_outstanding", self.shares_outstanding.period_end, self.shares_outstanding.filed))
        if bad:
            raise PITViolation(f"{self.ticker}: {len(bad)} value(s) filed on or after {self.asof}: {bad[:5]}")

    def periods(self) -> List[str]:
        """Fiscal periods (period_end, ascending) that have an annual report filed before asof."""
        return sorted({ar[0] for ar in self.annual_reports})

    def row(self, period_end: str) -> Dict[str, Optional[float]]:
        return {f: (self.series[f][period_end].value if period_end in self.series.get(f, {}) else None) for f in FIELDS}

    def rows(self) -> Dict[str, Dict[str, Optional[float]]]:
        return {pe: self.row(pe) for pe in self.periods()}

    def concept_values(self, name: str) -> Dict[str, float]:
        return {pe: f.value for pe, f in sorted(self.concepts.get(name, {}).items())}

    def filing_trail(self, field_name: str, period_end: str) -> Optional[Filed]:
        return self.series.get(field_name, {}).get(period_end)


class PITSource:
    """The interface a point-in-time data layer implements."""

    def load(self, ticker: str, asof) -> CompanyPIT:   # pragma: no cover - interface
        raise NotImplementedError


# ---- quantile distributions and sampling -----------------------------------------------------------------------------------------

class QuantileDist:
    """A distribution given by quantiles (at least P10, P50, P90; P5/P25/P75/P95 optional).

    ppf(u): piecewise-linear in probability between the given quantiles; beyond the outermost quantiles a normal tail whose scale
    is the local slope in z-space of the two outermost quantiles. Deterministic; documented in the report.
    """

    def __init__(self, quantiles: Mapping[float, float], label: str = ""):
        qs = sorted((float(p), float(v)) for p, v in quantiles.items())
        if not qs or any(not (0.0 < p < 1.0) for p, _ in qs):
            raise InputError("quantile levels must lie strictly between 0 and 1")
        have = {round(p, 6) for p, _ in qs}
        for need in (0.10, 0.50, 0.90):
            if need not in have:
                raise InputError(f"a quantile set needs P10, P50 and P90 (missing {need})")
        for (p0, v0), (p1, v1) in zip(qs, qs[1:]):
            if v1 < v0:
                raise InputError(f"quantiles must not decrease: P{p0 * 100:g}={v0} > P{p1 * 100:g}={v1}")
        if any(math.isnan(v) or math.isinf(v) for _, v in qs):
            raise InputError("quantiles must be finite")
        self.q = qs
        self.label = label

    @classmethod
    def point(cls, x: float, label: str = "point") -> "QuantileDist":
        return cls({0.10: x, 0.50: x, 0.90: x}, label)

    def quantile(self, p: float) -> float:
        return self.ppf(p)

    def ppf(self, u: float) -> float:
        qs = self.q
        if u <= qs[0][0]:
            return self._tail(u, qs[0], qs[1])
        if u >= qs[-1][0]:
            return self._tail(u, qs[-1], qs[-2])
        for (p0, v0), (p1, v1) in zip(qs, qs[1:]):
            if p0 <= u <= p1:
                return v0 if p1 == p0 else v0 + (v1 - v0) * (u - p0) / (p1 - p0)
        raise AssertionError("unreachable")

    @staticmethod
    def _tail(u, edge, inner):
        (p0, v0), (p1, v1) = edge, inner
        if v1 == v0:
            return v0
        z0, z1 = NORMAL.inv_cdf(p0), NORMAL.inv_cdf(p1)
        slope = (v1 - v0) / (z1 - z0)
        z = NORMAL.inv_cdf(min(max(u, 1e-12), 1 - 1e-12))
        return v0 + slope * (z - z0)

    def as_dict(self):
        return {f"p{p * 100:g}": v for p, v in self.q}


def _cholesky(m):
    n = len(m)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                d = m[i][i] - s
                if d <= 1e-12:
                    raise InputError("the correlation matrix is not positive definite")
                L[i][j] = math.sqrt(d)
            else:
                L[i][j] = (m[i][j] - s) / L[j][j]
    return L


def draw_inputs(dists: Mapping[str, QuantileDist], n: int, seed: int,
                corr: Optional[Mapping[tuple, float]] = None) -> List[Dict[str, float]]:
    """n joint draws of the inputs: a Gaussian copula (independence unless `corr` gives pairwise correlations) on the marginals."""
    names = sorted(dists)
    k = len(names)
    m = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    for (a, b), r in (corr or {}).items():
        if a in dists and b in dists and a != b:
            i, j = names.index(a), names.index(b)
            m[i][j] = m[j][i] = float(r)
    L = _cholesky(m)
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        z = [rng.gauss(0.0, 1.0) for _ in range(k)]
        c = [sum(L[i][j] * z[j] for j in range(i + 1)) for i in range(k)]
        out.append({names[i]: dists[names[i]].ppf(NORMAL.cdf(c[i])) for i in range(k)})
    return out


def quantile_of(values: Sequence[float], p: float) -> float:
    """Linear-interpolation quantile (type 7) of a non-empty sequence."""
    xs = sorted(values)
    if not xs:
        raise InputError("no values")
    h = (len(xs) - 1) * p
    lo = int(math.floor(h))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (h - lo)


def summarize(values: Sequence[float], levels=DEFAULT_LEVELS) -> Dict[str, float]:
    out = {f"p{p * 100:g}": quantile_of(values, p) for p in levels}
    out["mean"] = sum(values) / len(values)
    out["n"] = len(values)
    return out


def prob_above(values: Sequence[float], x: float) -> float:
    return sum(1 for v in values if v > x) / len(values)


def model_disagreement(primary_median, secondary_median):
    """(log(primary / secondary), None) of two medians (SPEC 3); (None, reason) when either is missing or not positive."""
    if primary_median is None or secondary_median is None:
        return None, "a median is missing"
    if primary_median <= 0 or secondary_median <= 0:
        return None, "a median is not positive, so the log ratio is undefined"
    return math.log(primary_median / secondary_median), None


# ---- curves -----------------------------------------------------------------------------------------------------------------------

@dataclass
class Curve:
    """Retention curve v_1..v_N (year t = 1..N): the fraction of an initial gap still present in year t. N is the horizon."""
    values: List[float]
    name: str = ""
    source: str = ""

    def __post_init__(self):
        if not self.values:
            raise InputError(f"curve {self.name!r} is empty")
        if len(self.values) > MAX_HORIZON:
            raise InputError(f"curve {self.name!r} has {len(self.values)} years; the horizon is at most {MAX_HORIZON}")
        for v in self.values:
            if math.isnan(v) or not (0.0 <= v <= 1.0):
                raise InputError(f"curve {self.name!r}: retention {v} is outside [0, 1]")

    def __len__(self):
        return len(self.values)

    def at(self, t: int) -> float:
        """Year t (1-based); beyond the last year the last value holds."""
        return self.values[min(t, len(self.values)) - 1]


def terminal_growth_rate(rf: float) -> float:
    """Addendum H2 (Damodaran's convention): terminal growth = min(the risk-free rate at T, the 3.75% long-run anchor): one value per date, never drawn from
    the realized growth of companies."""
    return min(float(rf), TERMINAL_G_ANCHOR)


def terminal_growth_after(g_last: float, g_base: float):
    """(rate, basis): the perpetuity growth after the last explicit year.  `g_base` is the date's value (`terminal_growth_rate`); a decay path that reaches a
    NEGATIVE rate by the last explicit year continues at that rate (no floor): a shrinking company does not jump back to the long-run rate."""
    if g_last < 0.0:
        return g_last, "decay path reached a negative rate by the last explicit year: that rate continues"
    return g_base, "min(risk-free rate at T, 3.75% anchor)"


LEVEL_REF_YEAR = 5                # Addendum H1: a level input (margin, return on new capital) is the level this many years on


def level_path_weights(curve: Curve, n: int, ref: int = LEVEL_REF_YEAR):
    """(weights, info): w_t, t = 1..n, the fraction of the move from today's level to the year-`ref` level that is made by year t (Addendum H1):

        w_t = (1 - v_t) / (1 - v_ref)   for t <= ref         v = the measured retention curve (the fraction of the initial gap still open)
        w_t = 1                         for t > ref          the level is held after year `ref` (the measured retention levels off by then)

    so a level x_t = x_0 + (x_ref - x_0) w_t moves along the measured curve's shape and, when x_ref is the median level, reproduces the curve exactly.
    Two structural conventions, both reported in `info`: a fraction of a move lies in [0, 1], so a w_t outside it (a measured curve that is not monotone) is
    clipped (`clipped`); and a curve with v_ref = 1 (no part of the gap closed by the reference year at the median) has no shape to take, so the move is linear
    in t (`shape` = "linear")."""
    denom = 1.0 - curve.at(ref)
    clipped = False
    if denom <= 1e-9:
        return [min(t, ref) / ref for t in range(1, n + 1)], {"shape": "linear", "clipped": False, "v_ref": curve.at(ref)}
    out = []
    for t in range(1, n + 1):
        if t >= ref:
            out.append(1.0)
            continue
        w = (1.0 - curve.at(t)) / denom
        if w < 0.0 or w > 1.0:
            clipped = True
        out.append(min(1.0, max(0.0, w)))
    return out, {"shape": "curve", "clipped": clipped, "v_ref": curve.at(ref)}


def exp_curve(n: int, half_life_years: float, name="", source="") -> Curve:
    """v_t = 0.5 ** (t / half_life): for tests and placeholders. half_life <= 0 -> full reversion in year 1."""
    if half_life_years <= 0:
        return Curve([0.0] * n, name, source)
    return Curve([0.5 ** (t / half_life_years) for t in range(1, n + 1)], name, source)


# ---- file hash ----------------------------------------------------------------------------------------------------------------------

def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- the company's state (what priors condition on, what the engines start from) ------------------------------------------------------

def _median(xs):
    xs = list(xs)
    return tcr.median(xs) if xs else None


def cyclicality_score(margins: Mapping[str, float], revenues: Mapping[str, float], max_years: int = 12, min_years: int = 6):
    """(result, None) or (None, reason). A continuous score in [0, 1] (SPEC 3.3): the unweighted mean of four components, each in
    [0, 1] and free of tuned constants. Higher = more cyclical. Uses the latest `max_years` annual operating margins and revenues.

      margin_volatility  = s / (s + |median m|), s = standard deviation of the margin series          (noise / (noise + signal))
      reversal_frequency = share of the interior years at which the margin change reverses its sign   (turning points / opportunities)
      autocorrelation    = (1 - rho) / 2, rho = lag-1 autocorrelation of the margin's first differences (mean reversion: rho near -0.5..-1);
                           0 when the first differences do not vary at all (a flat or straight-line margin has no cycle)
      revenue_cyclicality= e / (e + |b|), e = standard deviation of the residuals of ln(revenue) on a straight line in time, b = its slope

    The equal weights are an unweighted baseline; weights and any rescaling against the population belong to the priors build.
    Fewer than `min_years` years: None and the reason (never a default score).
    """
    ms = [margins[p] for p in sorted(margins)][-max_years:]
    rs = [revenues[p] for p in sorted(revenues) if revenues[p] is not None and revenues[p] > 0][-max_years:]
    if len(ms) < min_years or len(rs) < min_years:
        return None, f"fewer than {min_years} annual years held (margins {len(ms)}, revenues {len(rs)})"
    comp = {}
    s = statistics.pstdev(ms)
    med = abs(statistics.median(ms))
    comp["margin_volatility"] = 0.0 if s == 0 else s / (s + med)
    d = [b - a for a, b in zip(ms, ms[1:])]
    flips = sum(1 for a, b in zip(d, d[1:]) if a * b < 0)
    comp["reversal_frequency"] = flips / (len(d) - 1)
    mean_d = sum(d) / len(d)
    den = sum((x - mean_d) ** 2 for x in d)
    if den == 0:
        comp["autocorrelation"] = 0.0          # first differences do not vary (a flat or straight-line margin): no cycle to measure
    else:
        rho = sum((a - mean_d) * (b - mean_d) for a, b in zip(d, d[1:])) / den
        rho = max(-1.0, min(1.0, rho))
        comp["autocorrelation"] = (1.0 - rho) / 2.0
    ln = [math.log(x) for x in rs]
    xs = list(range(len(ln)))
    mx, my = sum(xs) / len(xs), sum(ln) / len(ln)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ln)) / sxx
    a = my - b * mx
    e = math.sqrt(sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ln)) / len(ln))
    comp["revenue_cyclicality"] = 0.0 if e == 0 else e / (e + abs(b))
    return {"score": sum(comp.values()) / 4.0, "components": comp, "years": len(ms)}, None


def greenwald_maintenance_capex(capex, ppe, rev, rev_prev):
    """Greenwald: maintenance capex = capex - (PP&E / revenue) x (change in revenue). None when an input is missing or revenue <= 0."""
    if None in (capex, ppe, rev, rev_prev) or rev <= 0:
        return None
    return capex - (ppe / rev) * (rev - rev_prev)


DEBT_COMPONENTS = ("debt_lt_noncurrent", "debt_current", "short_term_borrowings_separate")


def total_debt(row):
    """Interest-bearing debt EXCLUDING leases: debt_lt_noncurrent + short-term debt counted once (tcr.short_term_debt).
    When no debt component is filed: 0.0 if no interest charge is filed either, else None (an inconsistency, not a zero)."""
    lt = num(row.get("debt_lt_noncurrent"))
    dc, stb = num(row.get("debt_current")), num(row.get("short_term_borrowings_separate"))
    if lt is None and dc is None and stb is None:
        ie = num(row.get("interest_expense"))
        return None if (ie is not None and ie > 0) else 0.0
    return (0.0 if lt is None else lt) + tcr.short_term_debt(row)


def build_state(pit: CompanyPIT, max_years: int = 12) -> dict:
    """The company's state at pit.asof: base-period figures and the history features the engines and priors read.

    Everything is computed from annual reports filed before asof. A figure that is not filed is None and is listed in
    `missing` (the engines refuse with the list); bridge items (leases, minority interest, investments) that are not tagged are read
    as none and listed in `read_as_none`.
    """
    pit.check()
    rows = pit.rows()
    periods = pit.periods()[-max_years:]
    st = {"ticker": pit.ticker, "asof": pit.asof.isoformat(), "periods": periods, "missing": [], "read_as_none": [],
          "notes": list(pit.notes)}
    if not periods:
        st["missing"].append("no annual report filed before the valuation date")
        return st
    base_pe = periods[-1]
    base = rows[base_pe]
    prev = rows[periods[-2]] if len(periods) > 1 else {}
    st["base_period"] = base_pe
    ar = [a for a in pit.annual_reports if a[0] == base_pe]
    st["base_filed"] = ar[0][1] if ar else None
    st["base_accession"] = ar[0][2] if ar else None
    st["years_held"] = len(periods)

    rev = {p: rows[p]["revenue"] for p in periods if rows[p]["revenue"] is not None}
    om = {}
    for p in periods:
        r, oi = rows[p]["revenue"], rows[p]["operating_income"]
        if r is not None and r > 0 and oi is not None:
            om[p] = oi / r
    st["revenue_series"], st["op_margin_series"] = rev, om
    st["revenue"] = base["revenue"]
    st["operating_income"] = base["operating_income"]
    st["op_margin"] = om.get(base_pe)
    st["op_margin_median"] = _median(om.values())
    st["op_margin_years"] = len(om)
    # tax: median effective rate over the latest 8 years where it is computable (tcr clip [0, 0.35]); the repo's default otherwise
    rates = []
    for p in periods[-8:]:
        r = rows[p]
        pt, tx = num(r["pretax_income"]), num(r["tax_provision"])
        if pt is not None and tx is not None and pt > 0:
            rates.append(tcr.tax_rate(r))
    if rates:
        st["tax_rate"], st["tax_rate_source"] = _median(rates), f"median effective rate, {len(rates)} years"
    else:
        st["tax_rate"], st["tax_rate_source"] = tcr.TAX_DEFAULT, "default (no year with positive pre-tax income and a tax figure)"
    # growth state
    g = {}
    ps = sorted(rev)
    for a, b in zip(ps, ps[1:]):
        if rev[a] > 0:
            g[b] = rev[b] / rev[a] - 1.0
    st["growth_series"] = g
    st["growth_latest"] = g.get(base_pe)
    # Greenwald maintenance capex ratio and D&A ratio (median of the latest 8 years where defined)
    gap, mr, dr = [], [], []
    for a, b in zip(periods, periods[1:]):
        rb, ra = rows[b], rows[a]
        m = greenwald_maintenance_capex(num(rb["capex"]), num(rb["ppe_net"]), num(rb["revenue"]), num(ra["revenue"]))
        da = num(rb["da"])
        if m is not None and da is not None and rb["revenue"] > 0:
            mr.append(m / rb["revenue"])
            dr.append(da / rb["revenue"])
            gap.append((m - da) / rb["revenue"])
    st["maint_capex_ratio"] = _median(mr[-8:])
    st["da_ratio"] = _median(dr[-8:])
    st["maint_gap_ratio"] = _median(gap[-8:])
    st["maint_years"] = len(gap[-8:])
    cx, da0 = num(base["capex"]), num(base["da"])
    st["capex_to_da_latest"] = (cx / da0) if (cx is not None and da0 not in (None, 0)) else None
    st["ppe_to_revenue"] = (base["ppe_net"] / base["revenue"]) if (base["ppe_net"] is not None and base["revenue"] and base["revenue"] > 0) else None
    # net working capital intensity (median NWC / revenue over the latest 8 years; short-term debt subtracted once)
    nw = []
    for p in periods[-8:]:
        v = tcr.net_working_capital(rows[p])
        if v is not None and rows[p]["revenue"] and rows[p]["revenue"] > 0:
            nw.append(v / rows[p]["revenue"])
    st["nwc_ratio"] = _median(nw)
    st["nwc_years"] = len(nw)
    # balance sheet bridge items at the base period
    st["debt"] = total_debt(base)
    # Addendum G 5: a debt component that is never tagged in ANY held year counts as 0 (the untagged-marker convention used for goodwill) and is stamped
    untagged = [k for k in DEBT_COMPONENTS if all(rows[p][k] is None for p in periods)]
    if untagged:
        st["debt_components_never_tagged"] = untagged
        st["read_as_none"].append("debt components never tagged in any held year, counted as 0: " + ", ".join(untagged))
        if st["debt"] is None and len(untagged) == len(DEBT_COMPONENTS):
            st["debt"] = 0.0
    fl0 = num(base["finance_lease_liability"])
    st["debt_incl_finance_leases"] = None if st["debt"] is None else st["debt"] + (0.0 if fl0 is None else fl0)
    for k, label in (("finance_lease_liability", "finance leases"), ("operating_lease_liability", "operating leases"),
                     ("st_investments", "short-term investments"), ("lt_investments", "long-term investments")):
        v = num(base[k])
        if v is None:
            st["read_as_none"].append(f"{label} (not tagged)")
        st[k] = 0.0 if v is None else v
    st["cash"] = num(base["cash"])
    eq, eqn = num(base["equity"]), num(base["equity_incl_nci"])
    if eqn is not None and eq is not None:
        st["nci"] = eqn - eq
        st["nci_basis"] = "book value (equity including NCI minus parent equity)"
    else:
        st["nci"] = 0.0
        st["read_as_none"].append("noncontrolling interest (equity incl. NCI or parent equity not filed)")
        st["nci_basis"] = "none"
    st["equity"] = eq
    st["total_assets"] = num(base["total_assets"])
    # tangible equity and the return on it
    tbv, partial = tcr.tangible_equity_detail(base)
    pref = num(base["preferred_equity"])
    if tbv is not None and pref is not None:
        tbv -= pref
    st["tbv"], st["tbv_partial"] = tbv, bool(partial)
    st["tbv_series"] = {}
    for p in periods:
        t_, _ = tcr.tangible_equity_detail(rows[p])
        pf = num(rows[p]["preferred_equity"])
        if t_ is not None and pf is not None:
            t_ -= pf
        if t_ is not None:
            st["tbv_series"][p] = t_
    rote = {}
    tp = sorted(st["tbv_series"])
    for i, p in enumerate(tp):
        ni = num(rows[p]["net_income"])
        if ni is None:
            continue
        den = st["tbv_series"][p] if i == 0 else 0.5 * (st["tbv_series"][p] + st["tbv_series"][tp[i - 1]])
        if den > 0:
            rote[p] = ni / den
    st["rote_series"] = rote
    st["rote_latest"] = rote.get(base_pe)
    st["rote_median"] = _median(rote.values())
    # interest and cost of debt: interest expense / average (debt + finance leases): the interest line carries finance-lease interest
    ie = num(base["interest_expense"])
    dprev = total_debt(prev) if prev else None
    flp = num(prev.get("finance_lease_liability")) if prev else None
    dprev_all = None if dprev is None else dprev + (0.0 if flp is None else flp)
    dnow = st["debt_incl_finance_leases"]
    if ie is not None and dnow is not None and dprev_all is not None and (dnow + dprev_all) > 0:
        st["kd_effective"] = ie / (0.5 * (dnow + dprev_all))
    else:
        st["kd_effective"] = None
    ftag = pit.series.get("interest_expense", {}).get(base_pe)
    st["kd_basis"] = ("net of interest income (tag " + ftag.tag + ")") if (ftag is not None and "Net" in ftag.tag) else "gross interest expense"
    st["interest_expense"] = ie
    st["de_book"] = (dnow / eq) if (dnow is not None and eq is not None and eq > 0) else None
    cyc, why = cyclicality_score(om, rev)
    st["cyclicality"], st["cyclicality_reason"] = cyc, why
    st["shares_outstanding"] = pit.shares_outstanding.value if pit.shares_outstanding is not None else None
    st["sic"] = pit.sic.code if pit.sic else None
    for k in ("revenue", "operating_income"):
        if st.get(k) is None:
            st["missing"].append(k)
    if st["revenue"] is not None and st["revenue"] <= 0:
        st["missing"].append("revenue is not positive")
    if st["cash"] is None:
        st["missing"].append("cash")
    if st["debt"] is None:
        st["missing"].append("debt (an interest charge is filed but no debt component)")
    return st


def equity_bridge(ev: float, st: Mapping, *, operating_leases_in_cash_flow: bool = True) -> dict:
    """Equity value from an enterprise value (SPEC 3.1): EV - debt - finance leases - [operating leases] - minority interest
    + cash + short-term investments + long-term (non-operating) investments.

    Cash and investments are added once; the operating chain contains no interest income, so nothing is counted twice.
    Under US GAAP the operating lease COST is inside operating income, so FCFF already carries it and the operating lease LIABILITY
    is NOT subtracted (it would be counted twice); set `operating_leases_in_cash_flow=False` when the margin is lease-adjusted
    (rent added back). Finance leases: their interest is below operating income, so that liability is debt and is subtracted.
    """
    def g(k):
        v = st.get(k)
        return 0.0 if v is None else v
    items = {
        "debt": -g("debt"),
        "finance_leases": -g("finance_lease_liability"),
        "operating_leases": 0.0 if operating_leases_in_cash_flow else -g("operating_lease_liability"),
        "minority_interest": -g("nci"),
        "cash": g("cash"),
        "short_term_investments": g("st_investments"),
        "non_operating_assets": g("lt_investments"),
    }
    return {"enterprise_value": ev, "items": items, "equity_value": ev + sum(items.values()),
            "operating_leases_in_cash_flow": operating_leases_in_cash_flow}


# ---- simulation over input distributions ------------------------------------------------------------------------------------------------

class DrawInvalid(Exception):
    """One draw of the inputs cannot be valued (for example terminal growth at or above the discount rate). Counted and reported, never
    dropped silently and never repaired."""


def simulate(chain_fn, dists: Mapping[str, QuantileDist], n: int, seed: int, corr=None, price_per_share=None, shares=None) -> dict:
    """Run chain_fn(draw) -> {"equity": float, "ev": float, "tv_share": float, ["secondary_equity": float | None]} over n joint draws.

    Returns the distribution summary of equity value, the terminal-value share, the secondary value (when the chain supplies it), the
    counts of invalid draws by reason, and Pr(value > price) when a price per share and a share count are given.
    """
    eq, ev, tvs, sec = [], [], [], []
    invalid: Dict[str, int] = {}
    sec_invalid: Dict[str, int] = {}
    for draw in draw_inputs(dists, n, seed, corr):
        try:
            r = chain_fn(draw)
        except DrawInvalid as e:
            invalid[str(e)] = invalid.get(str(e), 0) + 1
            continue
        eq.append(r["equity"])
        ev.append(r["ev"])
        if r.get("tv_share") is not None:
            tvs.append(r["tv_share"])
        if "secondary_equity" in r:
            if r["secondary_equity"] is None:
                k = r.get("secondary_reason", "secondary value not defined")
                sec_invalid[k] = sec_invalid.get(k, 0) + 1
            else:
                sec.append(r["secondary_equity"])
    out = {"n_draws": n, "n_valid": len(eq), "n_invalid": n - len(eq), "invalid_reasons": invalid,
           "equity": summarize(eq) if eq else None, "ev": summarize(ev) if ev else None,
           "tv_share": summarize(tvs) if tvs else None,
           "secondary_equity": summarize(sec) if sec else None, "secondary_invalid_reasons": sec_invalid,
           "share_negative_equity": (sum(1 for v in eq if v < 0) / len(eq)) if eq else None}
    if eq and price_per_share is not None and shares:
        per = [v / shares for v in eq]
        out["per_share"] = summarize(per)
        out["prob_value_above_price"] = prob_above(per, price_per_share)
        out["prob_value_above_1.2x_price"] = prob_above(per, 1.2 * price_per_share)
        out["prob_value_below_0.8x_price"] = sum(1 for v in per if v < 0.8 * price_per_share) / len(per)
    return out
