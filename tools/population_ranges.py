"""population_ranges.py - how companies like this one actually evolved: the population ranges of the long-run inputs (revision 24 step 2b).

PHASE_4_REV24_MUSE.md design point 3; BRIEF_R24_S2b_ranges_gate.md item 1. The briefing gives the analyst no formula default for a long-run
judgment (the long-run earnings margin, the growth of years 3-10, terminal growth, the return on new investment); it prints, for each, the
distribution measured on the point-in-time SEC population for the company's cohort. This module reads those distributions and nothing else.

READ-ONLY OVER `tables.json`. The tables are the rebuild's priors_v5 (stocks-workspace/data/priors_v5/<vintage>/tables.json), resolved through
paths.py (`priors_dir`, environment variable RS2_PRIORS_DIR). The rebuild's code (valuation/priors.py and valuation/priors_build/) is never imported
(rs2's repository rule: nothing imports across worktrees); the rules below restate it, and a parity script run in the rebuild's own interpreter
compares the two (stocks-workspace/scratch/rev23/r24_s2b/).

THE VINTAGE. A valuation date T uses the vintage year(T) - 1: its tables are built only from fiscal years whose own annual report was filed strictly
before Jan 1 of year(T) (`vintage_for`, the rebuild's priors_build/config.vintage_for).

THE COMPANY RECORD (`company_record`). The features the tables condition on, computed from the company's own fiscal-year rows (fundamentals_history)
with the rebuild's definitions (valuation/common.build_state and valuation/priors.features): the latest 12 fiscal years; years on a chain index (a
missing year jumps the index); revenue growth latest and over 3 years; the operating margin (operating income / revenue) of the base year, its
8-year median (t-7..t, at least 5 defined years) and the deviation; the cyclicality score (four components on the latest 12 margins and revenues,
at least 6); the 8-year ln-revenue trend (OLS slope, at least 5 points); the base year's return on invested capital (NOPAT at the median effective
tax rate over 8 years / equity + debt - cash - short-term investments); the tangible-book growth (financials). The earnings margins the long-run
margin is quoted in (the record's 8-year median of earnings before acquired-intangible amortization over revenue, m_tc, and the base year's, x_L)
come from tools/throughcycle_record.analyse, the record the pack already prints. The economic family (operating, commodity, financial, or
family_not_built) comes from `family_for`, the rebuild's classification rules on the SIC code and the base year's balance sheet.

THE COHORTS (`ranges_for`), each the rebuild's own rule:
  * long-run earnings margin (`margin_retention`): the cyclicality tercile x the sign of the operating margin's deviation from its 8-year median
    (|deviation| below 0.5 points, or no score: the stated pooled band; a band under MIN_N: its pooled sign band), PopulationPriors._operating's rule.
    The row is the one PopulationPriors positions the curve at (year 5, or the last measured year before it): the largest year the table measures
    the quantiles of the retained share R at. The levels are this company's earnings margins: trend + R x (current - trend) at each quantile of R,
    trend the 8-year median earnings margin (m_tc) and current the base year's (x_L). R is measured on operating margins and applied here to the
    earnings margin (stated in the definition).
  * the same by cyclicality alone (`normalization`): the cyclicality quintile band (the table's own cuts), signs pooled.
  * growth for years 3-10 (`growth_decay`): the family's table (the operating family's when the family's is unmeasured), the bucket of the growth
    delivered (3-year CAGR, else the latest year) on the table's growth edges. The table measures year-k growth at P25, P50 and P75 only, and the
    retained share of the year-1 growth gap over the long-run reference at P5-P95 for k <= 5.
  * terminal growth (`terminal`): the family, and the shrinking stratum when the record's 8-year ln-revenue trend is below 0; the K-year revenue
    CAGR with delisted companies at their last filed year (`with_delisted`).
  * the return on new investment (`ronic`): the family x the base year's return on invested capital tercile (the table's own cuts); the 3-year
    incremental return where invested capital grew at least 10%. `ronic_fade` (pooled): the retained share of a return's excess over the population
    median, P25-P75 only.

0.0 is a value: every test is `is None`. Nothing is defaulted silently; an input the tables cannot serve is `available: False` with the reason, and
every fallback to a pooled cell is listed.
"""
from __future__ import annotations

import bisect
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import throughcycle_record as tcr

LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
QKEYS = ("p5", "p10", "p25", "p50", "p75", "p90", "p95")
CURVE_REF_YEAR = 5          # the year a curve's distribution is positioned at (the rebuild's CURVE_REF_YEAR; quantiles are measured to k = 5)
WINDOW = 8                  # the record window t-7..t
RECORD_MIN = 5              # defined margin years needed for the 8-year median, and points for the ln-revenue trend
MAX_YEARS = 12              # build_state reads the latest 12 fiscal years
CYC_MIN_YEARS = 6           # cyclicality_score's minimum
A2_MIN_DEV = 0.005          # a margin deviation under 0.5 points has no direction (stats.A2_MIN_DEV)
BAND_NAMES = {0: "low", 1: "mid", 2: "high"}
DEBT_COMPONENTS = ("debt_lt_noncurrent", "debt_current", "short_term_borrowings_separate")
CYC_COMPONENTS = ("margin_volatility", "reversal_frequency", "autocorrelation", "revenue_cyclicality")
FAMILIES = ("operating", "commodity", "financial")

# the inputs the briefing prints, in its order
INPUTS = ("long_run_margin", "normalization", "growth_years_3_10", "terminal_g", "terminal_ronic", "ronic_fade")

_TABLES: Dict[tuple, dict] = {}


# ---- vintages and tables ------------------------------------------------------------------------------------------------------------------

def vintage_for(T) -> int:
    """The vintage a valuation date uses: year(T) - 1 (its cut date, Jan 1 of year(T), is not after T)."""
    d = T if isinstance(T, date) else date.fromisoformat(str(T)[:10])
    return d.year - 1


def tables_dir() -> Path:
    """The priors_v5 folder, through paths.py (`priors_dir`; RS2_PRIORS_DIR overrides). Raises, naming every candidate, when it is not found."""
    import paths
    return paths.resolve("priors_dir")


def load_tables(vintage: int, tdir=None) -> Optional[dict]:
    """The vintage's tables, or None when the vintage is not on disk. Read once per (folder, vintage)."""
    d = Path(tdir) if tdir is not None else tables_dir()
    key = (str(d), int(vintage))
    if key not in _TABLES:
        p = d / str(int(vintage)) / "tables.json"
        if not p.exists():
            return None
        _TABLES[key] = json.loads(p.read_text(encoding="utf-8"))
    return _TABLES[key]


def vintages_available(tdir=None) -> List[int]:
    d = Path(tdir) if tdir is not None else tables_dir()
    return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit() and (p / "tables.json").exists())


# ---- the rebuild's measures, restated -----------------------------------------------------------------------------------------------------

def _num(v):
    return tcr._num(v)


def _median(xs):
    xs = list(xs)
    return statistics.median(xs) if xs else None


def cyclicality_score(margins: Dict[Any, float], revenues: Dict[Any, float], max_years: int = MAX_YEARS, min_years: int = CYC_MIN_YEARS):
    """(result, None) or (None, reason): valuation/common.cyclicality_score, restated. The unweighted mean of margin_volatility, reversal_frequency,
    autocorrelation and revenue_cyclicality on the latest `max_years` operating margins and positive revenues."""
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
        comp["autocorrelation"] = 0.0
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


def trend_slope(logrev_by_idx: Dict[int, float]) -> Optional[float]:
    """OLS slope of ln(revenue) on the chain index (obs.trend_slope); None under RECORD_MIN points."""
    if len(logrev_by_idx) < RECORD_MIN:
        return None
    xs = sorted(logrev_by_idx)
    ys = [logrev_by_idx[x] for x in xs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return None if sxx == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def nopat_of(ebit, tax) -> Optional[float]:
    """EBIT - tax x max(EBIT, 0) (common.nopat_of)."""
    return None if ebit is None else ebit - tax * max(ebit, 0.0)


def total_debt(row) -> Optional[float]:
    """common.total_debt: debt_lt_noncurrent + short-term debt counted once; with no component filed, 0.0 unless an interest charge is filed (None)."""
    lt = _num(row.get("debt_lt_noncurrent"))
    dc, stb = _num(row.get("debt_current")), _num(row.get("short_term_borrowings_separate"))
    if lt is None and dc is None and stb is None:
        ie = _num(row.get("interest_expense"))
        return None if (ie is not None and ie > 0) else 0.0
    return (0.0 if lt is None else lt) + tcr.short_term_debt(row)


def _tbv(row) -> Optional[float]:
    t, _ = tcr.tangible_equity_detail(row)
    pref = _num(row.get("preferred_equity"))
    if t is not None and pref is not None:
        t -= pref
    return t


# ---- the company record --------------------------------------------------------------------------------------------------------------------

def company_record(rows, base_year=None, *, family, usd=True, earnings_record=None, untagged=()) -> dict:
    """The features the cohorts condition on, from fiscal-year rows ({year: row}, fundamentals_history's form; a year may be a digit string), at
    the base year (default: the newest year held). `family` is `family_for`'s. `usd` is False for a filer whose figures are not in US dollars (the
    size bucket is then unknown, as the rebuild's). `earnings_record` is tools/throughcycle_record.analyse's dict for the same base year (its m_tc and
    x_L are the earnings margins the long-run margin is quoted in); None computes it here on the same rows. Returns a dict; a figure that cannot be
    computed is None, and `missing` names why."""
    rws = {int(y): r for y, r in (rows or {}).items() if str(y).isdigit() and isinstance(r, dict)}
    held = sorted(y for y in rws if base_year is None or y <= int(base_year))
    out: Dict[str, Any] = {"family": family, "usd": bool(usd), "base_year": None, "missing": []}
    if not held:
        out["missing"].append("no fiscal year held")
        return out
    periods = held[-MAX_YEARS:]
    base = periods[-1]
    out["base_year"] = base
    row = rws[base]
    idx = {p: p for p in periods}            # fiscal years are calendar labels: the chain index is the year itself (a gap jumps it)
    by_idx = {i: p for p, i in idx.items()}
    t = idx[base]
    rev_series = {p: _num(rws[p].get("revenue")) for p in periods if _num(rws[p].get("revenue")) is not None}
    om = {}
    for p in periods:
        r, oi = _num(rws[p].get("revenue")), _num(rws[p].get("operating_income"))
        if r is not None and r > 0 and oi is not None:
            om[p] = oi / r
    rev = {p: v for p, v in rev_series.items() if v > 0}
    r0 = rev.get(base)
    out["rev"] = r0
    pm, p3 = by_idx.get(t - 1), by_idx.get(t - 3)
    out["g_latest"] = (r0 / rev[pm] - 1.0) if (r0 is not None and pm in rev) else None
    out["g3"] = ((r0 / rev[p3]) ** (1.0 / 3.0) - 1.0) if (r0 is not None and p3 in rev) else None
    tb = {p: v for p in periods for v in (_tbv(rws[p]),) if v is not None and v > 0}
    out["tg_latest"] = (tb[base] / tb[pm] - 1.0) if (base in tb and pm in tb) else None
    out["tg3"] = ((tb[base] / tb[p3]) ** (1.0 / 3.0) - 1.0) if (base in tb and p3 in tb) else None
    win = [by_idx[i] for i in range(t - WINDOW + 1, t + 1) if i in by_idx]
    mw = [om[p] for p in win if p in om]
    out["m"] = om.get(base)
    out["med8"] = float(statistics.median(mw)) if len(mw) >= RECORD_MIN else None
    out["n8"] = len(mw)
    out["dev"] = (out["m"] - out["med8"]) if (out["m"] is not None and out["med8"] is not None) else None
    out["trend8"] = trend_slope({idx[p]: math.log(rev[p]) for p in win if p in rev})
    cyc, why = cyclicality_score(om, rev_series)
    out["cyc_score"] = cyc["score"] if cyc else None
    out["cyc_components"] = cyc["components"] if cyc else None
    out["cyc_years"] = cyc["years"] if cyc else None
    if cyc is None:
        out["missing"].append(f"cyclicality: {why}")
    # the base year's return on invested capital (features(): NOPAT at the state's tax rate / invested capital)
    rates = []
    for p in periods[-8:]:
        pt, tx = _num(rws[p].get("pretax_income")), _num(rws[p].get("tax_provision"))
        if pt is not None and tx is not None and pt > 0:
            rates.append(tcr.tax_rate(rws[p]))
    tax = _median(rates) if rates else tcr.TAX_DEFAULT
    out["tax"] = tax
    debt = total_debt(row)
    if debt is None and all(all(rws[p].get(k) is None for p in periods) for k in DEBT_COMPONENTS):
        debt = 0.0                           # build_state, Addendum G 5: every debt component never tagged counts 0
    eq, cash = _num(row.get("equity")), _num(row.get("cash"))
    sti = _num(row.get("st_investments"))
    ic = None if (eq is None or debt is None or cash is None) else eq + debt - cash - (0.0 if sti is None else sti)
    nop = nopat_of(_num(row.get("operating_income")), tax)
    out["roic"] = (nop / ic) if (nop is not None and ic is not None and ic > 0) else None
    # the earnings margins (X / revenue: the record's m_tc over its window, x_L of the base year)
    rec = earnings_record if earnings_record is not None else tcr.analyse(rws, None, untagged_fields=untagged, base_year=base)
    out["em_trend"] = _num(rec.get("m_tc"))
    out["em_current"] = _num(rec.get("x_L"))
    out["em_years"] = list(rec.get("m_years") or [])
    return out


# ---- the family (the rebuild's classification rules) ----------------------------------------------------------------------------------------

_NOT_BUILT = [((6500, 6599), "reit_or_real_estate"), ((6798, 6798), "reit_or_real_estate"), ((6770, 6770), "blank_check_shell"),
              ((6719, 6719), "conglomerate_or_holding_company"), ((9990, 9990), "conglomerate_or_holding_company"),
              ((9995, 9995), "conglomerate_or_holding_company"), ((4900, 4949), "regulated_utility_or_pipeline")]
_FINANCIAL_EXCEPTIONS = {6282: "investment advice: a fee business, valued as operating", 6411: "insurance agents and brokers: a fee business, valued as operating"}
_FINANCIAL = [(6000, 6411)]
_COMMODITY = [(1000, 1299), (1400, 1499), (1311, 1311), (1321, 1321), (1381, 1382), (2911, 2911), (2611, 2611), (2621, 2621),
              (2810, 2829), (2860, 2879), (3312, 3317), (3330, 3339), (4400, 4499)]
PRE_PROFIT_WINDOW = 4
PRE_PROFIT_MIN_LOSS_YEARS = 3
INSURANCE_RESERVE_SHARE = 0.10


def sic_family(sic):
    """(family, note) from a SIC code: valuation/classification.sic_family, restated."""
    if sic is None or not str(sic).strip().isdigit():
        return None, "no SIC code"
    code = int(str(sic).strip())
    for (a, b), kind in _NOT_BUILT:
        if a <= code <= b:
            return "family_not_built", kind
    if code in _FINANCIAL_EXCEPTIONS:
        return "operating", _FINANCIAL_EXCEPTIONS[code]
    if any(a <= code <= b for a, b in _FINANCIAL):
        return "financial", "banks, credit, brokers, insurers"
    if any(a <= code <= b for a, b in _COMMODITY):
        return "commodity", "mining, oil and gas, refining, commodity chemicals, steel, shipping, pulp and paper"
    return "operating", "default"


def family_for(sic, rows, base_year=None) -> dict:
    """{"family", "reason", "stamps"}: valuation/classification.classification's rules on the SIC code and the base year's row. The lending-book
    test reads loan and deposit concepts the fiscal-year rows do not hold: it is not evaluated (stamped), so a lender whose SIC is not financial
    stays in its SIC family here."""
    rws = {int(y): r for y, r in (rows or {}).items() if str(y).isdigit() and isinstance(r, dict)}
    held = sorted(y for y in rws if base_year is None or y <= int(base_year))
    stamps = ["lending_book_test_not_evaluated"]
    if not held:
        return {"family": None, "reason": "unclassifiable: no fiscal year held", "stamps": stamps}
    row = rws[held[-1]]
    fam_sic, note = sic_family(sic)
    if fam_sic is None:
        stamps.append("sic_missing")
    if fam_sic == "family_not_built":
        return {"family": "family_not_built", "reason": f"SIC {sic}: {note}; family not built", "stamps": stamps}
    ta, ir = _num(row.get("total_assets")), _num(row.get("insurance_reserves"))
    if ta is not None and ta > 0 and ir is not None and ir / ta >= INSURANCE_RESERVE_SHARE:
        return {"family": "financial", "reason": f"balance sheet: insurance reserves are {ir / ta:.1%} of total assets (>= 10%)", "stamps": stamps}
    if ta is None or ta <= 0 or ir is None:
        stamps.append("insurance_reserve_test_not_evaluated")
    if fam_sic == "financial":
        return {"family": "financial", "reason": f"SIC {sic}: {note}", "stamps": stamps}
    fam = fam_sic if fam_sic is not None else "operating"
    reason = f"SIC {sic}: {note}" if fam_sic is not None else "no SIC code; no balance-sheet financial profile"
    vals = [v for p in held[-PRE_PROFIT_WINDOW:] for v in (_num(rws[p].get("operating_income")),) if v is not None]
    loss = sum(1 for v in vals if v <= 0)
    if loss >= PRE_PROFIT_MIN_LOSS_YEARS:
        return {"family": "family_not_built", "stamps": stamps,
                "reason": f"pre_profit: operating income <= 0 in {loss} of the last {len(held[-PRE_PROFIT_WINDOW:])} fiscal years; family not built"}
    return {"family": fam, "reason": reason, "stamps": stamps}


# ---- the cohort assignment ------------------------------------------------------------------------------------------------------------------

def _bucket(x, edges) -> int:
    """np.searchsorted(edges, x, side="right"); -1 for a missing or non-finite x (priors._bucket)."""
    if x is None or not math.isfinite(x):
        return -1
    return bisect.bisect_right(list(edges), x)


def _band(x, cuts) -> int:
    """priors._band: the band of x among `cuts` (a value equal to a cut goes to the upper band); -1 for a missing x; 0 with no cuts."""
    if x is None or not math.isfinite(x):
        return -1
    return bisect.bisect_right(list(cuts), x) if cuts else 0


def _pos_row(rows, key, n_key, min_n, ref=CURVE_REF_YEAR):
    """priors._pos_row: the rows read consecutively from k = 1 while the value is measured and n >= min_n; the one at year `ref`, or the last before it."""
    used = []
    for r in rows:
        if r.get(key) is None or r.get(n_key, 0) < min_n:
            break
        used.append(r)
    return used[min(ref, len(used)) - 1] if used else None


def _quantiles(cell, keys=QKEYS) -> Dict[str, Optional[float]]:
    return {k: (_num(cell.get(k)) if isinstance(cell, dict) else None) for k in keys}


def _sorted_levels(trend, current, rq):
    """trend + R x (current - trend) at each quantile of R, as the quantiles of the level (a negative deviation reverses the order)."""
    vals = [trend + rq[k] * (current - trend) for k in QKEYS]
    vals.sort()
    return dict(zip(QKEYS, vals))


def _score(T, rec):
    """The cyclicality score on the vintage's weights: the equal-weight score unless the vintage adopted fitted weights (PopulationPriors)."""
    w = T.get("cyc_weights") or {}
    comp = rec.get("cyc_components")
    if comp and w.get("adopted"):
        return sum(wi * comp[c] for wi, c in zip(w["weights"], CYC_COMPONENTS)), "fitted weights"
    return rec.get("cyc_score"), "equal weights"


def _interp(x, xs, ys):
    """np.interp for increasing xs: linear between the points, flat beyond the ends."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    j = bisect.bisect_right(xs, x)
    x0, x1, y0, y1 = xs[j - 1], xs[j], ys[j - 1], ys[j]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _normalization_interpolated(T, score, min_n):
    """(raw quantiles, the rebuild's position, the bands' rows used) of the margin's retention at `score`, interpolated between the normalization
    quintile bands (PopulationPriors._normalization_position): the bands with a score median and n >= MIN_N, each at its year-5 row. The position is
    the rebuild's own (each band's quantiles clipped to [0, 1], then interpolated); the raw quantiles are interpolated unclipped for the levels.
    None without a score or a band."""
    if score is None:
        return None
    pts = []
    for b in T["normalization"]["bands"]:
        if b.get("score_median") is None or b["all"]["n"] < min_n:
            continue
        row = _pos_row(b["all"]["ks"], "median", "n", min_n)
        if row is None or not row.get("q"):
            continue
        q = _quantiles(row["q"])
        if any(q[k] is None for k in ("p10", "p50", "p90")):
            continue
        pts.append((b["score_median"], q, {"k": row["k"], "n": int(row["q"].get("n") or row["n"]), "score_median": b["score_median"]}))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    raw = {k: (_interp(score, xs, [p[1][k] for p in pts]) if all(p[1][k] is not None for p in pts) else None) for k in QKEYS}
    pos = {k: (_interp(score, xs, [min(1.0, max(0.0, p[1][k])) for p in pts]) if all(p[1][k] is not None for p in pts) else None) for k in QKEYS}
    lo = max([i for i, x in enumerate(xs) if x <= score] or [0])
    hi = min([i for i, x in enumerate(xs) if x >= score] or [len(xs) - 1])
    return raw, pos, [pts[lo][2]] + ([pts[hi][2]] if hi != lo else [])


def _margin_retention(T, rec, min_n):
    mr = T["margin_retention"]
    cuts = mr["cyc_cuts"]
    score, basis = _score(T, rec)
    fallbacks = []
    med8, dev = rec.get("med8"), rec.get("dev")
    if med8 is not None and dev is not None and abs(dev) >= A2_MIN_DEV:
        sg = "pos" if dev > 0 else "neg"
        cb = _band(score, cuts)
        if cb >= 0:
            key = f"{BAND_NAMES.get(cb, cb)}_{sg}"
        else:
            key = f"pooled_{sg}"
            fallbacks.append("no cyclicality score (fewer than 6 years): the sign-only pooled band")
    elif med8 is not None and dev is not None:
        key = "pooled_all"
        fallbacks.append("the operating margin is within 0.5 points of its 8-year median (no direction): the pooled band")
    else:
        key = "pooled_all"
        fallbacks.append("fewer than 5 defined operating-margin years in the 8-year window: no 8-year median; the pooled band")
    bd = mr["bands"].get(key)
    if bd is not None and bd["n"] < min_n:
        new = "pooled_all" if ("pos" not in key and "neg" not in key) else ("pooled_pos" if key.endswith("pos") else "pooled_neg")
        fallbacks.append(f"band {key} has n={bd['n']} < {min_n}: the pooled band {new}")
        key = new
        bd = mr["bands"].get(key)
    return key, bd, score, basis, fallbacks


def _band_words(key, cuts, basis):
    if key.startswith("pooled"):
        cyc = "of any cyclicality"
    else:
        name = key.split("_")[0]
        lo, hi = cuts[0], cuts[1]
        cyc = {"low": f"in the least cyclical third (cyclicality score below {lo:.3f})",
               "mid": f"in the middle third of cyclicality (score {lo:.3f} to {hi:.3f})",
               "high": f"in the most cyclical third (score {hi:.3f} or above)"}[name]
    sg = key.rsplit("_", 1)[1]
    side = {"pos": "whose operating margin was above its 8-year median", "neg": "whose operating margin was below its 8-year median",
            "all": "whatever the side of their operating margin's 8-year median"}[sg]
    fitted = " (the vintage's fitted cyclicality weights)" if basis != "equal weights" else ""
    return f"operating and commodity companies {cyc}{fitted}, {side}"


def ranges_for(company_record_: dict, T, tables=None, tdir=None) -> dict:
    """The population ranges of the long-run inputs for `company_record_` (`company_record`'s dict) at valuation date T. `tables` (a vintage's
    tables.json) overrides the read. Returns {"vintage", "cut_date", "priors_version", "family", "min_n", "inputs": {name: {...}}}: each input is
    {"available": True, "table", "cohort", "cohort_text", "n", ... quantiles} or {"available": False, "reason"}."""
    rec = company_record_ or {}
    V = vintage_for(T)
    T_ = tables if tables is not None else load_tables(V, tdir)
    out: Dict[str, Any] = {"vintage": V, "cut_date": None, "priors_version": None, "family": rec.get("family"), "min_n": None, "inputs": {}}
    if T_ is None:
        why = f"no priors vintage {V} on disk"
        out["inputs"] = {k: {"available": False, "reason": why} for k in INPUTS}
        out["unavailable"] = why
        return out
    min_n = int(T_.get("min_n") or 50)
    out.update(cut_date=T_.get("cut_date"), priors_version=T_.get("priors_version"), min_n=min_n,
               obs_sha256=T_.get("obs_sha256"))
    fam = rec.get("family")
    ins = out["inputs"]
    if fam not in FAMILIES:
        why = (f"the company's family is {fam or 'not known'}: the population tables measure operating, commodity and financial companies only"
               if fam != "family_not_built" else "the company is in a family the population tables do not measure (family_not_built: "
               "real estate, utilities and pipelines, shells, or pre-profit)")
        out["inputs"] = {k: {"available": False, "reason": why} for k in INPUTS}
        return out

    # ---- the long-run earnings margin (margin_retention), and by cyclicality alone (normalization) -------------------------------------------
    trend, current = rec.get("em_trend"), rec.get("em_current")
    lvl_missing = None
    if trend is None:
        lvl_missing = "the record holds fewer than 5 years of earnings margin in its 8-year window (no 8-year median earnings margin)"
    elif current is None:
        lvl_missing = "the base year's earnings margin is not defined"
    if fam == "financial":
        ins["long_run_margin"] = {"available": False, "reason": "the margin tables measure operating and commodity companies; a financial company's "
                                                                "long-run margin has no population range here"}
        ins["normalization"] = dict(ins["long_run_margin"])
    else:
        key, bd, score, basis, fb = _margin_retention(T_, rec, min_n)
        row = _pos_row(bd["ks"], "median", "n", min_n) if bd else None
        interp = _normalization_interpolated(T_, score, min_n) if fam == "commodity" else None
        if interp is not None:
            # PopulationPriors, commodity family: the margin's retention is the normalization curve of the company's cyclicality score, its
            # distribution the quintile bands' interpolated quantile by quantile at the score (flat beyond the end bands)
            rq, pos, used = interp
            nb_ = T_["normalization"]
            d = {"available": True, "table": "normalization", "cohort": "commodity:normalization_at_score", "band": key, "fallbacks": fb, "score": score,
                 "score_basis": basis, "k": used[0]["k"], "n": min(u["n"] for u in used), "retention": rq, "position": pos, "trend": trend,
                 "current": current, "op_margin": rec.get("m"), "op_median8": rec.get("med8"), "op_dev": rec.get("dev"),
                 "cohort_text": (f"operating and commodity companies at your cyclicality score {score:.3f}: the quintile bands of the score interpolated "
                                 f"at it (band medians {', '.join(f'{u['score_median']:.3f}' for u in used)}), both sides of the median"
                                 + (" (the vintage's fitted cyclicality weights)" if basis != "equal weights" else ""))}
        elif row is None or not row.get("q"):
            d = {"available": False, "reason": f"the band {key} has no measured year with n >= {min_n}", "cohort": key}
        else:
            rq = _quantiles(row["q"])
            d = {"available": True, "table": "margin_retention", "cohort": key, "band": key, "fallbacks": fb, "score": score, "score_basis": basis,
                 "cohort_text": _band_words(key, T_["margin_retention"]["cyc_cuts"], basis), "k": row["k"], "n": int(row["q"].get("n") or row["n"]),
                 "retention": rq, "position": {k: (None if v is None else min(1.0, max(0.0, v))) for k, v in rq.items()},
                 "trend": trend, "current": current, "op_margin": rec.get("m"), "op_median8": rec.get("med8"), "op_dev": rec.get("dev")}
        if d.get("available"):
            if lvl_missing:
                d.update(available=False, reason=lvl_missing)
            elif any(d["retention"][k] is None for k in QKEYS):
                d.update(available=False, reason="the cohort's retained share is not measured at every quantile")
            else:
                d["levels"] = _sorted_levels(trend, current, d["retention"])
                if rec.get("dev") is not None and (current - trend) * rec["dev"] < 0:
                    d["stamps"] = ["earnings_deviation_sign_differs_from_operating"]
        ins["long_run_margin"] = d
        nb = T_["normalization"]
        if score is None:
            ins["normalization"] = {"available": False, "reason": "no cyclicality score (fewer than 6 years of margins and revenues)"}
        else:
            b = _band(score, nb["cuts"])
            band = next((x for x in nb["bands"] if x["band"] == b), None)
            if band is None or band["all"]["n"] < min_n:
                ins["normalization"] = {"available": False, "reason": f"the cyclicality quintile band {b} has n < {min_n}"}
            else:
                row = _pos_row(band["all"]["ks"], "median", "n", min_n)
                if row is None or not row.get("q"):
                    ins["normalization"] = {"available": False, "reason": f"the cyclicality quintile band {b} has no measured year with n >= {min_n}"}
                else:
                    rq = _quantiles(row["q"])
                    d = {"available": True, "table": "normalization", "cohort": f"quintile_{b}", "band": b, "score": score, "score_basis": basis,
                         "cohort_text": (f"operating and commodity companies in cyclicality quintile {b + 1} of 5 (score "
                                         + (f"{nb['cuts'][b - 1]:.3f}" if b > 0 else "below") + (" to " if 0 < b < len(nb["cuts"]) else (" or above" if b > 0 else " "))
                                         + (f"{nb['cuts'][b]:.3f}" if b < len(nb["cuts"]) else "") + "), both sides of the median"),
                         "k": row["k"], "n": int(row["q"].get("n") or row["n"]), "retention": rq, "trend": trend, "current": current}
                    if lvl_missing:
                        d.update(available=False, reason=lvl_missing)
                    else:
                        d["levels"] = _sorted_levels(trend, current, rq)
                    ins["normalization"] = d

    # ---- growth for years 3-10 (growth_decay) -------------------------------------------------------------------------------------------------
    gd = T_["growth_decay"].get(fam)
    gfb = []
    if (not gd or not gd.get("buckets")) and fam != "operating":
        gd = T_["growth_decay"].get("operating")
        gfb.append("the family's growth_decay table is unmeasured: the operating family's table")
    if fam == "financial":
        gv, gbasis = (rec.get("tg3"), "3-year tangible-book CAGR") if rec.get("tg3") is not None else (rec.get("tg_latest"), "latest-year tangible-book growth")
    else:
        gv, gbasis = (rec.get("g3"), "3-year revenue CAGR") if rec.get("g3") is not None else (rec.get("g_latest"), "latest-year revenue growth")
    if not gd or not gd.get("buckets") or gv is None:
        ins["growth_years_3_10"] = {"available": False, "reason": "no growth delivered (fewer than two fiscal years of revenue) or no measured table"}
    else:
        edges = T_["edges"]["growth"]
        gb = _bucket(gv, edges)
        bk = next((x for x in gd["buckets"] if x["bucket"][0] <= gb <= x["bucket"][1]), None)
        if bk is None:
            ins["growth_years_3_10"] = {"available": False, "reason": f"no growth_decay bucket holds band {gb}"}
        else:
            lo_e = edges[bk["bucket"][0] - 1] if bk["bucket"][0] > 0 else None
            hi_e = edges[bk["bucket"][1]] if bk["bucket"][1] < len(edges) else None
            rng = ("at any level" if lo_e is None and hi_e is None else f"below {hi_e:.0%}" if lo_e is None
                   else f"{lo_e:.0%} or more" if hi_e is None else f"{lo_e:.0%} to {hi_e:.0%}")
            by_k = {}
            for r in bk["ks"]:
                if 3 <= r["k"] <= 10 and r.get("n", 0) >= min_n and r.get("raw_p50") is not None:
                    by_k[r["k"]] = {"n": r["n"], "p25": r.get("raw_p25"), "p50": r.get("raw_p50"), "p75": r.get("raw_p75")}
            prow = _pos_row(bk["ks"], "ratio_median", "n_ratio", min_n)
            what = "tangible book" if fam == "financial" else "revenue"
            ins["growth_years_3_10"] = {
                "available": True, "table": "growth_decay", "cohort": f"{fam}:bucket_{bk['bucket'][0]}-{bk['bucket'][1]}", "fallbacks": gfb,
                "cohort_text": f"{fam} companies whose {gbasis} was {rng}", "growth_delivered": gv, "growth_basis": gbasis, "what": what,
                "n": bk["n_k1"], "terminal_reference": (gd.get("terminal_reference") or {}).get("value"), "by_k": by_k,
                "ratio_k": prow["k"] if prow else None, "ratio_n": prow.get("n_ratio") if prow else None,
                "ratio": _quantiles(prow.get("ratio_q")) if prow and prow.get("ratio_q") else None}

    # ---- terminal growth (terminal) ------------------------------------------------------------------------------------------------------------
    tm = T_["terminal"]
    K = tm.get("K_eff")
    trend8 = rec.get("trend8")
    stratum = "shrinking" if (trend8 is not None and trend8 < 0) else "all"
    tfb = [] if trend8 is not None else ["the record's 8-year revenue trend is not measured (fewer than 5 years): all companies of the family"]
    cell = ((tm.get("families") or {}).get(fam) or {}).get(stratum, {}).get("with_delisted") or {}
    if stratum == "shrinking" and (cell.get("n") or 0) < min_n:
        tfb.append(f"too few shrinking {fam} companies (n={cell.get('n') or 0}): all companies of the family")
        stratum = "all"
        cell = ((tm.get("families") or {}).get(fam) or {}).get("all", {}).get("with_delisted") or {}
    if not K or (cell.get("n") or 0) < min_n:
        ins["terminal_g"] = {"available": False, "reason": f"the terminal table has n={cell.get('n') or 0} < {min_n} for this family"}
    else:
        ins["terminal_g"] = {
            "available": True, "table": "terminal", "cohort": f"{fam}:{stratum}:with_delisted", "stratum": stratum, "variant": "with_delisted", "K": K,
            "fallbacks": tfb, "n": int(cell["n"]), "quantiles": _quantiles(cell), "trend8": trend8,
            "cohort_text": (f"{fam} companies" + (" whose 8-year revenue trend was falling" if stratum == "shrinking" else "")
                            + f": the {K}-year revenue CAGR, companies that stopped filing included at their last filed year (3 years or more)")}

    # ---- the return on new investment (ronic, ronic_fade) ---------------------------------------------------------------------------------------
    rt = T_.get("ronic") or {}
    fam_r = (rt.get("families") or {}).get(fam)
    if fam_r is None:
        ins["terminal_ronic"] = {"available": False, "reason": f"the ronic table measures operating and commodity companies, not {fam}"}
    else:
        cuts = rt.get("roic_cuts") or []
        rb = _band(rec.get("roic"), cuts)
        rfb = []
        name = BAND_NAMES.get(rb) if rb >= 0 else None
        cellr = (fam_r.get("bands") or {}).get(name) if name else None
        if cellr is None:
            rfb.append("no return on invested capital for the base year: every company of the family")
        elif (cellr.get("n") or 0) < min_n:
            rfb.append(f"the {name} band has n={cellr.get('n')} < {min_n}: every company of the family")
            cellr = None
        cohort = name if cellr is not None else "floored_all"
        if cellr is None:
            cellr = fam_r.get("floored_all") or {}
        words = {"low": f"in the lowest third of return on invested capital (below {cuts[0]:.1%})" if cuts else "",
                 "mid": f"in the middle third of return on invested capital ({cuts[0]:.1%} to {cuts[1]:.1%})" if len(cuts) > 1 else "",
                 "high": f"in the top third of return on invested capital ({cuts[1]:.1%} or above)" if len(cuts) > 1 else ""}.get(cohort, "of any return on invested capital")
        if (cellr.get("n") or 0) < min_n:
            ins["terminal_ronic"] = {"available": False, "reason": f"the ronic cell has n={cellr.get('n') or 0} < {min_n}"}
        else:
            ins["terminal_ronic"] = {
                "available": True, "table": "ronic", "cohort": f"{fam}:{cohort}", "fallbacks": rfb, "roic": rec.get("roic"), "n": int(cellr["n"]),
                "quantiles": _quantiles(cellr),
                "cohort_text": (f"{fam} companies {words}: the 3-year incremental return on invested capital where the capital grew at least "
                                f"{float(rt.get('ic_growth_floor') or 0.1):.0%}")}
    rf = T_.get("ronic_fade") or {}
    used = []
    for r in rf.get("ks") or []:
        if r.get("median") is None or r.get("n", 0) < min_n:
            break
        used.append(r)
    if not used:
        ins["ronic_fade"] = {"available": False, "reason": f"the ronic_fade table has no year with n >= {min_n}"}
    else:
        last = used[-1]
        ins["ronic_fade"] = {
            "available": True, "table": "ronic_fade", "cohort": "pooled", "k": last["k"], "n": last["n"], "reference": rf.get("reference"),
            "quantiles": {"p5": None, "p10": None, "p25": last.get("p25"), "p50": last.get("median"), "p75": last.get("p75"), "p90": None, "p95": None},
            "cohort_text": (f"all operating and commodity companies: the share of a return on invested capital's excess over the population median "
                            f"({float(rf.get('reference') or 0):.1%}) still there after {last['k']} years")}
    return out


# ---- the briefing's text --------------------------------------------------------------------------------------------------------------------

RANGES_LINE = "how companies like this one actually evolved; context for your choice, not a target."
NOT_MEASURED = "not measured"


def _pct(v, signed=False, digits=1):
    if v is None:
        return NOT_MEASURED
    return f"{v * 100:+.{digits}f}%" if signed else f"{v * 100:.{digits}f}%"


def _qline(q, show_p50, fmt):
    keys = ("p10", "p25", "p50", "p75", "p90") if show_p50 else ("p10", "p25", "p75", "p90")
    return ", ".join(f"{k.upper()} {fmt(q.get(k))}" for k in keys)


def render_section(ranges: Optional[dict], show_p50: bool) -> str:
    """The POPULATION RANGES section the briefing prints after DEFAULTS: one line per long-run input with the cohort in words, n, the vintage and
    P10/P25/P75/P90; P50 only when `show_p50` (the pilot's flag ranges_show_p50). A quantile the table does not measure reads "not measured"."""
    r = ranges or {}
    V = r.get("vintage")
    head = (f"## POPULATION RANGES   [{RANGES_LINE} Population tables priors_v5, vintage {V}: fiscal years whose annual report was filed "
            f"before {r.get('cut_date') or 'the cut date'}, companies that later stopped filing included]")
    lines = [head]
    ins = r.get("inputs") or {}
    if not ins:
        lines.append(f"- not available: {r.get('unavailable') or 'the population ranges were not computed for this pack'}")
        return "\n".join(lines)

    def na(name, d):
        return f"- {name}: not available — {d.get('reason')}"

    d = ins.get("long_run_margin") or {}
    if d.get("available"):
        fb = f"; {'; '.join(d['fallbacks'])}" if d.get("fallbacks") else ""
        lines.append(f"- long_run_margin population (the earnings margin at the end of the fade): cohort: {d['cohort_text']}{fb}; n={d['n']:,} at year {d['k']}, "
                     f"vintage {V} | {_qline(d['levels'], show_p50, _pct)} | the cohort's share of the margin's deviation still there after "
                     f"{d['k']} years (measured on operating margins), applied to your earnings margin: your 8-year median {_pct(d['trend'])} plus "
                     f"that share of your base year's {_pct(d['current'])} minus it")
    else:
        lines.append(na("long_run_margin population", d))
    d = ins.get("normalization") or {}
    if d.get("available"):
        lines.append(f"- long_run_margin population by cyclicality alone: cohort: {d['cohort_text']}; n={d['n']:,} at year {d['k']}, vintage {V} | "
                     f"{_qline(d['levels'], show_p50, _pct)} | the same arithmetic on this band's share")
    else:
        lines.append(na("long_run_margin population by cyclicality alone", d))
    d = ins.get("growth_years_3_10") or {}
    if d.get("available"):
        fb = f"; {'; '.join(d['fallbacks'])}" if d.get("fallbacks") else ""
        yrs = []
        for k in sorted(d["by_k"]):
            q = d["by_k"][k]
            pts = [f"P25 {_pct(q['p25'], True)}"] + ([f"P50 {_pct(q['p50'], True)}"] if show_p50 else []) + [f"P75 {_pct(q['p75'], True)}"]
            yrs.append(f"year {k} " + " ".join(pts))
        ratio = ""
        if d.get("ratio"):
            ratio = (f" | the share of year 1's {d['what']} growth above the long-run reference {_pct(d['terminal_reference'], digits=2)} still there in "
                     f"year {d['ratio_k']} (n={d['ratio_n']:,}): {_qline(d['ratio'], show_p50, lambda v: NOT_MEASURED if v is None else f'{v:.2f}')}")
        lines.append(f"- growth of years 3-10 population ({d['what']} growth in each year): cohort: {d['cohort_text']}{fb}; n={d['n']:,}, vintage {V} | "
                     f"P10 and P90 {NOT_MEASURED} | " + "; ".join(yrs) + ratio)
    else:
        lines.append(na("growth of years 3-10 population", d))
    d = ins.get("terminal_g") or {}
    if d.get("available"):
        fb = f"; {'; '.join(d['fallbacks'])}" if d.get("fallbacks") else ""
        lines.append(f"- terminal_g population: cohort: {d['cohort_text']}{fb}; n={d['n']:,}, vintage {V} | "
                     f"{_qline(d['quantiles'], show_p50, lambda v: _pct(v, True))}")
    else:
        lines.append(na("terminal_g population", d))
    d = ins.get("terminal_ronic") or {}
    if d.get("available"):
        fb = f"; {'; '.join(d['fallbacks'])}" if d.get("fallbacks") else ""
        lines.append(f"- terminal_ronic population: cohort: {d['cohort_text']}{fb}; n={d['n']:,}, vintage {V} | {_qline(d['quantiles'], show_p50, _pct)}")
    else:
        lines.append(na("terminal_ronic population", d))
    d = ins.get("ronic_fade") or {}
    if d.get("available"):
        lines.append(f"- the fade of the return on new investment, population: cohort: {d['cohort_text']}; n={d['n']:,}, vintage {V} | "
                     f"{_qline(d['quantiles'], show_p50, lambda v: NOT_MEASURED if v is None else f'{v:.2f}')}")
    else:
        lines.append(na("the fade of the return on new investment, population", d))
    return "\n".join(lines)


# ---- the cohort's P5-P95 for the plausibility gate --------------------------------------------------------------------------------------------

def gate_bounds(ranges: Optional[dict]) -> Dict[str, Optional[dict]]:
    """{metric: {"p5", "p95", "cohort", "n"} or None}: the cohort bounds the plausibility gate compares the implied trajectory with
    (fiduciary_gate.plausibility_gate). long_run_margin from the margin levels; revenue_cagr_10y and terminal_g from the terminal table's K-year
    revenue CAGR (its K stated); terminal_ronic from the ronic table; earnings_ratio_10y has no measured cohort (None)."""
    ins = (ranges or {}).get("inputs") or {}

    def b(name, key):
        d = ins.get(name) or {}
        q = d.get(key) if d.get("available") else None
        if not q or q.get("p5") is None or q.get("p95") is None:
            return None
        return {"p5": q["p5"], "p95": q["p95"], "cohort": d.get("cohort"), "n": d.get("n"), "K": d.get("K")}
    return {"long_run_margin": b("long_run_margin", "levels"), "revenue_cagr_10y": b("terminal_g", "quantiles"),
            "terminal_ronic": b("terminal_ronic", "quantiles"), "earnings_ratio_10y": None, "terminal_g": b("terminal_g", "quantiles")}
