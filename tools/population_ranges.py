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

THE COHORTS (`ranges_for`), each the rebuild's own rule (step 2c, PHASE_4_AMENDMENTS.md "Revision 24 step 2b" rulings 1, 2, 5-7):
  * the long-run margin (`margin_retention`): priors.py's margin_target, the operating margin LEVEL five years out. The cell is the cyclicality tercile x
    the sign of the operating margin's deviation from its 8-year median (|deviation| below 0.5 points, or no score: the stated pooled band; a band under
    MIN_N: its pooled sign band); the centre the median-retention path at year 5 (the 8-year median plus r_5 x the deviation, r_5 the band curve's
    year-5 value; the commodity family's the normalization curve's at its score); the spread the measured year-5 residual of the cell's group holding
    the company's CURRENT operating margin (`residual_k5_by_level`), merged up (sign-pooled, then fully pooled) and refused, named, under MIN_N
    (Addenda H1, I1, I5). P5-P95 of the operating margin five years out; and in earnings-margin terms (the unit of long_run_margin) by the paired
    translation of cross-check 19 (ruling A), earnings_q = (1 - t) x OM_q + Delta, Delta the median of the record's m_t - (1 - tax_t) x OM_t
    (`paired_gap`), t the record's median effective tax rate (`translation_tax`; 21% stamped `tax_rate_statutory_fallback` outside [0, 0.5]).
  * the margin by cyclicality alone (`normalization`): the cyclicality quintile band (the table's own cuts) and its year-5 median retention; context.
  * growth for years 3-10 (`growth_decay`): the family's table (the operating family's when the family's is unmeasured), the bucket of the growth
    delivered (3-year CAGR, else the latest year) on the table's growth edges. The table measures year-k growth at P25, P50 and P75 only, and the
    retained share of the year-1 growth gap over the long-run reference at P5-P95 for k <= 5.
  * the 10-year revenue CAGR (`terminal`): the family, and the shrinking stratum when the record's 8-year ln-revenue trend is below 0; the K-year revenue
    CAGR with delisted companies at their last filed year (`with_delisted`). Context for the growth path and the bound of the revenue growth to year
    10; it is not terminal_g's range (terminal_g has none: the gate checks it against the pack's growth anchor).
  * the return on new investment's context (`roic_level`): priors.py's `ronic`, the ROIC LEVEL five years out, I + phi_5 (L0 - I) plus the measured
    year-5 residual of the group holding the company's trailing 3-year ROIC (L0); I is the table's own stand-in for the date's industry median
    (`roic_reference`, stamped). The `ronic` (incremental) and `ronic_fade` tables are not read: priors.py reads neither.
  * a family the tables do not measure (family_not_built; a financial company's margin and ROIC): "no measured population for this family" per input.

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

# the inputs the briefing prints, in its order (step 2c: terminal_g has no population line, ruling 5; the `terminal` table is the 10-year revenue CAGR;
# terminal_ronic's context is the ROIC level five years out, ruling 6; the `ronic` and `ronic_fade` tables are not printed: priors.py reads neither)
INPUTS = ("long_run_margin", "normalization", "growth_years_3_10", "revenue_cagr_10y", "terminal_ronic")
NO_POPULATION = "no measured population for this family"

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

def company_record(rows, base_year=None, *, family, usd=True, earnings_record=None, untagged=(), earnings_rows=None) -> dict:
    """The features the cohorts condition on, from fiscal-year rows ({year: row}, fundamentals_history's form; a year may be a digit string), at
    the base year (default: the newest year held). `family` is `family_for`'s. `usd` is False for a filer whose figures are not in US dollars (the
    size bucket is then unknown, as the rebuild's). `earnings_record` is tools/throughcycle_record.analyse's dict for the same base year (its m_tc and
    x_L are the earnings margins the long-run margin is quoted in); None computes it here on the same rows. Returns a dict; a figure that cannot be
    computed is None, and `missing` names why. `earnings_rows` (step 2c) are the rows the earnings record was measured on (the pack's consolidated view,
    input_scope.record_view_for), for the paired non-operating gap; None reads `rows`."""
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
    # step 2c (ruling 6): the trailing 3-year ROIC level (common.build_state's roic3: the mean of NOPAT / invested capital over the three
    # consecutive fiscal years ending at the base year, each defined; NOPAT at the same tax rate; a debt never tagged in any held year counts 0)
    never = all(all(rws[p].get(k) is None for p in periods) for k in DEBT_COMPONENTS)
    roic_y = {}
    for p in periods:
        r_ = rws[p]
        d_ = total_debt(r_)
        if d_ is None and never:
            d_ = 0.0
        eq_, cash_, sti_ = _num(r_.get("equity")), _num(r_.get("cash")), _num(r_.get("st_investments"))
        ic_ = None if (eq_ is None or d_ is None or cash_ is None) else eq_ + d_ - cash_ - (0.0 if sti_ is None else sti_)
        nop_ = nopat_of(_num(r_.get("operating_income")), tax)
        if nop_ is not None and ic_ is not None and ic_ > 0:
            roic_y[p] = nop_ / ic_
    out["roic3"] = (sum(roic_y[base - k] for k in range(3)) / 3.0) if all((base - k) in roic_y for k in range(3)) else None
    # the earnings margins (X / revenue: the record's m_tc over its window, x_L of the base year) and the record's operating-margin median
    rec = earnings_record if earnings_record is not None else tcr.analyse(rws, None, untagged_fields=untagged, base_year=base)
    out["em_trend"] = _num(rec.get("m_tc"))
    out["em_current"] = _num(rec.get("x_L"))
    out["em_years"] = list(rec.get("m_years") or [])
    out["om_tc"], out["om_basis"] = _num(rec.get("om_tc")), rec.get("om_basis")
    out.update(translation_tax(rws, base))
    ers = {int(y): r for y, r in (earnings_rows or {}).items() if str(y).isdigit() and isinstance(r, dict)} if earnings_rows is not None else rws
    out.update(paired_gap(ers, rws, base, untagged))
    return out


TAX_FALLBACK = 0.21             # ruling 2: the statutory rate when the record's median effective rate is not within [0, 0.5]
TAX_BOUNDS = (0.0, 0.5)
TAX_IDENTITY_TOL = 0.05         # a year whose net income + tax differs from pre-tax income by more than 5% is not read (capability_test._pretax_note)


def _years_phrase(years):
    return f"1 fiscal year, FY{years[0]}" if len(years) == 1 else f"{len(years)} fiscal years, FY{years[0]}-FY{years[-1]}"


def year_tax(row):
    """(rate, None) or (21%, why): one fiscal year's effective tax rate, tax provision / pre-tax income, when pre-tax income is positive, the tax and
    net income are filed, net income + tax equals pre-tax income within 5% and the rate is within [0, 0.5]; else the statutory 21% and the reason."""
    pt, tx, ni = _num(row.get("pretax_income")), _num(row.get("tax_provision")), _num(row.get("net_income"))
    if pt is None or tx is None or not pt > 0:
        return TAX_FALLBACK, "no positive pre-tax income and tax figure"
    if ni is None or abs((ni + tx) - pt) / abs(pt) > TAX_IDENTITY_TOL:
        return TAX_FALLBACK, "net income + tax differs from pre-tax income by more than 5%"
    r = tx / pt
    if not (TAX_BOUNDS[0] <= r <= TAX_BOUNDS[1]):
        return TAX_FALLBACK, f"the rate {r:.1%} is outside [0%, 50%]"
    return r, None


def paired_gap(earn_rows, op_rows, base, untagged=()) -> dict:
    """{"delta", "delta_years", "delta_tax_fallback_years", "delta_source"}: the paired historical non-operating gap of the translation (cross-check 19,
    ruling A, replacing step 2b ruling 2's two independent medians): the median, over the record's window (fiscal years base-7..base) with both
    margins defined, of m_t - (1 - tax_t) x OM_t; m_t the earnings margin (earnings before acquired-intangible amortization over revenue,
    throughcycle_record.adjusted_earnings, on the rows the earnings record was measured on), OM_t the operating margin on the population tables'
    own basis (operating income over revenue as filed), tax_t the year's own effective rate (`year_tax`, 21% stamped per year). None with no such year."""
    vals, years, fb = [], [], []
    for y in range(int(base) - WINDOW + 1, int(base) + 1):
        er, orow = earn_rows.get(y), op_rows.get(y)
        if not isinstance(er, dict) or not isinstance(orow, dict):
            continue
        rev_e, rev_o, oi = _num(er.get("revenue")), _num(orow.get("revenue")), _num(orow.get("operating_income"))
        x = tcr.adjusted_earnings(er, untagged)
        if x is None or rev_e is None or not rev_e > 0 or oi is None or rev_o is None or not rev_o > 0:
            continue
        tx, why = year_tax(er)
        if why is not None:
            fb.append(y)
        vals.append(x / rev_e - (1.0 - tx) * (oi / rev_o))
        years.append(y)
    if not vals:
        return {"delta": None, "delta_years": [], "delta_tax_fallback_years": [],
                "delta_source": f"no fiscal year of FY{int(base) - WINDOW + 1}-FY{int(base)} with both an earnings margin and an operating margin"}
    note = (f"; 21% statutory in FY{', FY'.join(str(y) for y in fb)} (tax_rate_statutory_fallback)" if fb else "")
    return {"delta": statistics.median(vals), "delta_years": years, "delta_tax_fallback_years": fb,
            "delta_source": f"the median of {_years_phrase(years)}{note}"}


def translation_tax(rws, base) -> dict:
    """{"tax_t", "tax_t_source", "tax_t_years", "tax_t_stamps"}: the tax rate of the operating-to-earnings translation (ruling 2 of step 2b): the median
    effective tax rate (tax provision / pre-tax income) of the record's window, the fiscal years base-7..base, over the years with positive pre-tax
    income, a tax figure and a net income for which net income + tax equals pre-tax income within 5% (the pack's own screen of a domestic-only pre-tax
    figure: a year that fails it is not read). Used when within [0, 0.5]; otherwise 21%, stamped `tax_rate_statutory_fallback`, with the reason."""
    rates, years, failed = [], [], []
    for y in range(int(base) - WINDOW + 1, int(base) + 1):
        r = rws.get(y)
        if not isinstance(r, dict):
            continue
        pt, tx, ni = _num(r.get("pretax_income")), _num(r.get("tax_provision")), _num(r.get("net_income"))
        if pt is None or tx is None or not pt > 0:
            continue
        if ni is None or abs((ni + tx) - pt) / abs(pt) > TAX_IDENTITY_TOL:
            failed.append(y)
            continue
        rates.append(tx / pt)
        years.append(y)
    note = f"; FY{', FY'.join(str(y) for y in failed)} not read (net income + tax differs from pre-tax income by more than 5%)" if failed else ""
    if not rates:
        return {"tax_t": TAX_FALLBACK, "tax_t_years": [], "tax_t_stamps": ["tax_rate_statutory_fallback"],
                "tax_t_source": f"21% statutory: no fiscal year of FY{int(base) - WINDOW + 1}-FY{int(base)} with positive pre-tax income and a tax "
                                f"figure that passes the identity{note}"}
    med = statistics.median(rates)
    if not (TAX_BOUNDS[0] <= med <= TAX_BOUNDS[1]):
        return {"tax_t": TAX_FALLBACK, "tax_t_years": years, "tax_t_stamps": ["tax_rate_statutory_fallback"],
                "tax_t_source": f"21% statutory: the median effective rate {med:.1%} of {len(years)} years is outside [0%, 50%]{note}"}
    return {"tax_t": med, "tax_t_years": years, "tax_t_stamps": [],
            "tax_t_source": f"the median effective rate of {_years_phrase(years)}{note}"}


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
    out: Dict[str, Any] = {"vintage": V, "cut_date": None, "priors_version": None, "family": rec.get("family"), "min_n": None, "inputs": {},
                           # cross-check 19, ruling C: the record's 8-year ln-revenue OLS slope (the terminal table's shrinking test), for the gate
                           "revenue_trend8": rec.get("trend8")}
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
        why = (f"the company's family is {fam or 'not known'}; the population tables measure operating, commodity and financial companies only"
               if fam != "family_not_built" else "the tables do not measure real estate, utilities and pipelines, shells or pre-profit companies "
               f"(family_not_built: {rec.get('family_reason') or 'the rebuild classification rules'})")
        out["inputs"] = {k: _unmeasured(why) for k in INPUTS}            # ruling 7 of step 2b
        return out

    # ---- the long-run margin (step 2c, ruling 1): the rebuild's margin_target, the operating margin LEVEL five years out -------------------------
    # priors.PopulationPriors._operating, restated: centred on the median-retention path at year 5 (the 8-year median operating margin plus r_5 times
    # the deviation; r_5 the band curve's year-5 value, the commodity family's the normalization curve's at its score), the spread the measured
    # year-5 residual of the cell of the company's CURRENT operating-margin band (residual_k5_by_level), merged up (sign-pooled, then fully pooled)
    # and refused, named, under MIN_N. Then printed in earnings-margin terms by the paired translation (cross-check 19, ruling A).
    if fam == "financial":
        ins["long_run_margin"] = _unmeasured("the margin tables measure operating and commodity companies; a financial company's margin is not measured")
        ins["normalization"] = dict(ins["long_run_margin"])
    else:
        ins["long_run_margin"] = _margin_target(T_, rec, min_n)
        ins["normalization"] = _normalization_line(T_, rec, min_n)

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

    # ---- the 10-year revenue CAGR (terminal; step 2c, ruling 5) ---------------------------------------------------------------------------------
    # context for the growth path and the bound of the revenue growth to year 10 the inputs imply; never terminal_g's range (terminal_g has none)
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
        ins["revenue_cagr_10y"] = {"available": False, "reason": f"the terminal table has n={cell.get('n') or 0} < {min_n} for this family"}
    else:
        ins["revenue_cagr_10y"] = {
            "available": True, "table": "terminal", "cohort": f"{fam}:{stratum}:with_delisted", "stratum": stratum, "variant": "with_delisted", "K": K,
            "fallbacks": tfb, "n": int(cell["n"]), "quantiles": _quantiles(cell), "trend8": trend8,
            "cohort_text": (f"{fam} companies" + (" whose 8-year revenue trend was falling" if stratum == "shrinking" else "")
                            + f": the {K}-year revenue CAGR, companies that stopped filing included at their last filed year (3 years or more)")}

    # ---- the return on new investment's context (step 2c, ruling 6): the ROIC LEVEL five years out --------------------------------------------
    if fam == "financial":
        ins["terminal_ronic"] = _unmeasured("the ROIC-level table measures operating and commodity companies; a financial company's return is not "
                                            "measured")
    else:
        ins["terminal_ronic"] = _roic_level(T_, rec, min_n)
    return out


def _unmeasured(detail):
    """An input the tables do not measure for the company's family (ruling 7): printed "no measured population for this family"."""
    return {"available": False, "family_unmeasured": True, "reason": f"{NO_POPULATION}: {detail}"}


def _curve_r5(rows, min_n):
    """priors._curve_from_rows(...).at(CURVE_REF_YEAR): the measured medians read consecutively from k = 1 while n >= min_n, each clipped to [0, 1];
    the year-5 value, or the last measured one when the measurement stops sooner (the curve holds it). None with no measured row."""
    vals = []
    for r in rows or []:
        if r.get("median") is None or r.get("n", 0) < min_n:
            break
        vals.append(min(1.0, max(0.0, r["median"])))
    return vals[min(CURVE_REF_YEAR, len(vals)) - 1] if vals else None


def _normalization_r5(T, score, min_n):
    """priors._normalization_ref(...)(score).at(5): the quintile bands' curves (score median known, n >= MIN_N, a measured curve) at year 5,
    interpolated at the score (flat beyond the end bands). None when no band has a curve."""
    pts = []
    for b in T["normalization"]["bands"]:
        if b.get("score_median") is None or b["all"]["n"] < min_n:
            continue
        v = _curve_r5(b["all"]["ks"], min_n)
        if v is not None:
            pts.append((b["score_median"], v))
    if not pts:
        return None
    return _interp(score, [p[0] for p in pts], [p[1] for p in pts])


def _level_group(tab, level, min_n):
    """priors._level_group: (the group of a residual-by-level table holding `level` ([lower, upper), open ends None), the n of the whole cell). The
    group is None when the table is absent, the cell has fewer than MIN_N, the level is not a number, or the group holding it has fewer than MIN_N."""
    if not tab or not tab.get("groups"):
        return None, 0
    n_cell = int(tab.get("n", 0))
    if n_cell < min_n or level is None or not math.isfinite(level):
        return None, n_cell
    for g in tab["groups"]:
        lo, hi = g.get("lower"), g.get("upper")
        if (lo is None or level >= lo) and (hi is None or level < hi):
            return (g if g.get("n", 0) >= min_n else None), n_cell
    return None, n_cell


def _shifted(cell, shift):
    """priors._qd(cell, shift)'s quantiles: P5..P95 of the cell plus the centre; None unless P10, P50 and P90 are measured."""
    q = {k: (None if _num(cell.get(k)) is None else _num(cell.get(k)) + shift) for k in QKEYS}
    return q if all(q[k] is not None for k in ("p10", "p50", "p90")) else None


def _level_words(g, what):
    lo, hi = g.get("lower"), g.get("upper")
    if lo is None and hi is None:
        return f"at any {what}"
    if lo is None:
        return f"below {hi:.1%}"
    if hi is None:
        return f"{lo:.1%} or above"
    return f"{lo:.1%} to {hi:.1%}"


def _margin_target(T, rec, min_n):
    """The long-run margin's range (ruling 1): priors.py's margin_target, restated; plus its earnings-margin equivalents (ruling 2)."""
    mr = T["margin_retention"]
    key, bd, score, basis, fb = _margin_retention(T, rec, min_n)
    med8, dev, m = rec.get("med8"), rec.get("dev"), rec.get("m")
    centre = med8 if (med8 is not None and dev is not None) else m          # priors.state_median: the margin held when no 8-year median is formed
    if bd is None:
        return {"available": False, "reason": f"margin_target: the margin_retention band {key} is not in the vintage", "cohort": key}
    rl_tab = mr.get("residual_k5_by_level")
    if rl_tab is None:
        return {"available": False, "reason": "margin_target: this vintage has no level-conditional residual table (priors version < 3)", "cohort": key}
    sg = key.rsplit("_", 1)[-1]
    cands = [key] + ([f"pooled_{sg}"] if sg in ("pos", "neg") and not key.startswith("pooled") else []) + (["pooled_all"] if key != "pooled_all" else [])
    grp, used, ns = None, None, []
    for k in cands:
        g_, n_ = _level_group(rl_tab.get(k), m, min_n)
        ns.append(f"{k} n={n_}")
        if g_ is not None:
            grp, used = g_, k
            break
    if grp is None:
        why = (f"margin_target: no residual cell with n >= {min_n} after the stated merges ({'; '.join(ns)})" if m is not None
               else "margin_target: no current operating margin to place in a level band")
        return {"available": False, "reason": why, "cohort": key}
    if used != key:
        fb = fb + [f"margin_target: residual cell of band {key} has n={(rl_tab.get(key) or {}).get('n', 0)} < {min_n}: merged up to {used} "
                   f"(n={rl_tab[used]['n']})"]
    r5, r5_source = _curve_r5(bd["ks"], min_n), f"band {key} curve"
    if rec.get("family") == "commodity" and score is not None:
        rn = _normalization_r5(T, score, min_n)
        if rn is not None:
            r5, r5_source = rn, "normalization curve of the cyclicality score"
    if centre is None or r5 is None:
        return {"available": False, "reason": "margin_target: no centre (no margin) or no residual spread", "cohort": key}
    shift = r5 * (0.0 if dev is None else dev)
    op = _shifted(grp, centre + shift)
    if op is None:
        return {"available": False, "reason": "margin_target: the residual cell has too few observations for P10/P50/P90", "cohort": key}
    d = {"available": True, "table": "margin_retention.residual_k5_by_level", "cohort": key, "band": key, "residual_cell": used,
         "level_band": {"level": m, "band": grp.get("band"), "lower": grp.get("lower"), "upper": grp.get("upper"), "merged": grp.get("merged")},
         "fallbacks": fb, "score": score, "score_basis": basis, "n": int(grp["n"]), "n_cell": int(rl_tab[used]["n"]),
         "centre_8y_median": centre, "centre_basis": "8-year median" if med8 is not None else "base-year operating margin (no 8-year median)",
         "dev": dev, "r5": r5, "r5_source": r5_source, "level5_median": centre + shift,
         "retention_k5_used": (rl_tab.get(used) or {}).get("retention_k5_used"),
         "cohort_text": (_band_words(used, mr["cyc_cuts"], basis) if r5_source.startswith("band") else
                         f"{_band_words(used, mr['cyc_cuts'], basis)}; centred on the normalization curve at your cyclicality score {score:.3f}"),
         "level_text": f"whose base-year operating margin was {_level_words(grp, 'margin')}", "operating": op}
    # cross-check 19, ruling A (replacing step 2b ruling 2's formula): earnings_q = (1 - t) x OM_q + Delta, Delta the PAIRED historical
    # non-operating gap (`paired_gap`: the median over the record's years of m_t - (1 - tax_t) x OM_t), t the record's median effective rate
    t, delta = rec.get("tax_t"), rec.get("delta")
    d.update(m_tc=rec.get("em_trend"), om_tc=rec.get("om_tc"), om_basis=rec.get("om_basis"), tax_t=t, tax_t_source=rec.get("tax_t_source"),
             tax_t_stamps=list(rec.get("tax_t_stamps") or []), delta=delta, delta_source=rec.get("delta_source"),
             delta_years=list(rec.get("delta_years") or []), delta_tax_fallback_years=list(rec.get("delta_tax_fallback_years") or []))
    if delta is None:
        d["earnings"], d["earnings_reason"] = None, (rec.get("delta_source") or "no paired non-operating gap") + ": no translation to earnings"
    elif t is None:
        d["earnings"], d["earnings_reason"] = None, "no tax rate for the translation"
    else:
        d["earnings"] = {k: (None if op[k] is None else (1.0 - t) * op[k] + delta) for k in QKEYS}
    return d


def _normalization_line(T, rec, min_n):
    """The cyclicality quintile band's year-5 median retention (ruling 3 of step 2b: the company's band, context the gate never reads). Step 2c:
    the share's own quantiles are no longer turned into margin levels (ruling 1); the median path is printed, P10 and P90 not measured."""
    nb = T["normalization"]
    score, basis = _score(T, rec)
    if score is None:
        return {"available": False, "reason": "no cyclicality score (fewer than 6 years of margins and revenues)"}
    b = _band(score, nb["cuts"])
    band = next((x for x in nb["bands"] if x["band"] == b), None)
    if band is None or band["all"]["n"] < min_n:
        return {"available": False, "reason": f"the cyclicality quintile band {b} has n < {min_n}"}
    row = _pos_row(band["all"]["ks"], "median", "n", min_n)
    if row is None:
        return {"available": False, "reason": f"the cyclicality quintile band {b} has no measured year with n >= {min_n}"}
    r = min(1.0, max(0.0, row["median"]))
    med8, dev = rec.get("med8"), rec.get("dev")
    return {"available": True, "table": "normalization", "cohort": f"quintile_{b}", "band": b, "score": score, "score_basis": basis,
            "cohort_text": (f"operating and commodity companies in cyclicality quintile {b + 1} of 5 (score "
                            + (f"{nb['cuts'][b - 1]:.3f}" if b > 0 else "below") + (" to " if 0 < b < len(nb["cuts"]) else (" or above" if b > 0 else " "))
                            + (f"{nb['cuts'][b]:.3f}" if b < len(nb["cuts"]) else "") + "), both sides of the median"),
            "k": row["k"], "n": int(row["n"]), "retention_median": r,
            "op_median_path": (med8 + r * dev) if (med8 is not None and dev is not None) else None}


def roic_reference(T, base_year):
    """(I, year, stamps): the level the ROIC fades toward. priors.py takes the date's industry median trailing 3-year ROIC from the population valued
    on the date (gate1.DateContext), which rs2 does not hold; the table's own measured stand-in is the median roic3 of the vintage's same-fiscal-year
    operating and commodity observations (roic_level.reference_by_year; stats.roic_level_tables names it the population analogue). The vintage's own
    cut year holds only its early filers (vintage 2025: 12.7% for 2025 against 10.3% for 2024; every vintage 2016-2024 has its cut year 0.8-2.6 points above
    the next vintage's figure for it), so the year read is the latest held at or before min(base fiscal year, vintage - 1). (None, None, []) when the
    table holds no such year."""
    rl = T.get("roic_level") or {}
    by = {int(y): v for y, v in (rl.get("reference_by_year") or {}).items() if v is not None}
    V = int(T.get("vintage")) if T.get("vintage") is not None else None
    caps = [c for c in ((int(base_year) if base_year is not None else None), (V - 1 if V is not None else None)) if c is not None]
    ys = [y for y in by if not caps or y <= min(caps)]
    if not ys:
        return None, None, []
    y = max(ys)
    stamps = ["roic_reference_population_median_not_industry"]
    if base_year is not None and y != int(base_year):
        stamps.append(f"roic_reference_year_{y}_for_base_year_{int(base_year)}")
    return by[y], y, stamps


def _roic_level(T, rec, min_n):
    """The ROIC level five years out (ruling 6): priors.py's `ronic` input, restated - I + phi_5 (L0 - I) plus the measured year-5 residual of the
    cell of the company's CURRENT trailing 3-year ROIC band (roic_level.residual_k5_by_level); the band by the sign of L0 - I (|gap| under
    min_abs_gap: all), a band under MIN_N read as `all`, the residual cell merged to `all` under MIN_N and refused, named, there. I is
    `roic_reference`'s stand-in for the industry median (stamped)."""
    rl = T.get("roic_level")
    if not rl or not rl.get("bands"):
        return {"available": False, "reason": "ronic: this vintage has no roic_level table (priors version < 2)"}
    L0 = rec.get("roic3")
    if L0 is None:
        return {"available": False, "reason": "ronic: no trailing 3-year ROIC for the company (three consecutive fiscal years with NOPAT and positive "
                                              "invested capital)"}
    I, iy, istamps = roic_reference(T, rec.get("base_year"))
    if I is None:
        return {"available": False, "reason": "ronic: the vintage holds no population median ROIC for a fiscal year at or before the base year"}
    gap = L0 - I
    key = "pos" if gap >= rl["min_abs_gap"] else ("neg" if gap <= -rl["min_abs_gap"] else "all")
    fb = []
    bd = rl["bands"].get(key)
    if bd is None or bd.get("n", 0) < min_n:
        fb.append(f"ronic: band {key} too thin in this vintage: the sign-pooled ROIC retention")
        bd, key = rl["bands"].get("all"), "all"
    phi5 = _curve_r5(bd["ks"], min_n) if bd else None
    lv_tab = rl.get("residual_k5_by_level")
    if lv_tab is None:
        return {"available": False, "reason": "ronic: this vintage has no level-conditional ROIC residual table (priors version < 3)"}
    res, used, ns = None, None, []
    for k in ([key] + (["all"] if key != "all" else [])):
        g_, n_ = _level_group(lv_tab.get(k), L0, min_n)
        ns.append(f"{k} n={n_}")
        if g_ is not None:
            res, used = g_, k
            break
    if res is None:
        return {"available": False, "reason": f"ronic: no ROIC residual cell with n >= {min_n} after the stated merges ({'; '.join(ns)})"}
    if used != key:
        fb.append(f"ronic: residual cell {key} has n={(lv_tab.get(key) or {}).get('n', 0)} < {min_n}: merged to {used} (n={lv_tab[used]['n']})")
    if phi5 is None:
        return {"available": False, "reason": "ronic: no measured ROIC retention curve in this vintage"}
    centre5 = I + phi5 * gap
    q = _shifted(res, centre5)
    if q is None:
        return {"available": False, "reason": "ronic: the residual spread has too few observations for P10/P50/P90"}
    side = {"pos": "more than 2 points above", "neg": "more than 2 points below", "all": "on either side of"}[used]
    return {"available": True, "table": "roic_level.residual_k5_by_level", "cohort": f"{rec.get('family')}:{key}", "band": key, "residual_cell": used,
            "fallbacks": fb, "n": int(res["n"]), "n_cell": int(lv_tab[used]["n"]), "L0": L0, "reference": I, "reference_year": iy,
            "reference_stamps": istamps, "phi5": phi5, "level5_median": centre5, "quantiles": q,
            "level_band": {"level": L0, "band": res.get("band"), "lower": res.get("lower"), "upper": res.get("upper"), "merged": res.get("merged")},
            "cohort_text": f"operating and commodity companies whose trailing 3-year ROIC was {side} the population median of its fiscal year",
            "level_text": f"whose trailing 3-year ROIC was {_level_words(res, 'ROIC')}"}


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
    """The POPULATION RANGES section the briefing prints after DEFAULTS: one line per input with the cohort in words, n, the vintage and
    P10/P25/P75/P90; P50 only when `show_p50` (the pilot's flag ranges_show_p50). A quantile the table does not measure reads "not measured"; an input
    the tables do not measure for the company's family reads "no measured population for this family" (ruling 7). Step 2c: the long-run margin is
    the operating margin five years out with its earnings-margin equivalents (rulings 1-2); the `terminal` table is printed as the 10-year revenue
    CAGR, never as terminal_g's range (ruling 5); terminal_ronic's context is the ROIC level five years out (ruling 6)."""
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
        if d.get("family_unmeasured"):
            return f"- {name}: {d.get('reason')}"
        return f"- {name}: not available — {d.get('reason')}"

    def fb(d):
        return f"; {'; '.join(d['fallbacks'])}" if d.get("fallbacks") else ""

    d = ins.get("long_run_margin") or {}
    name = "long_run_margin population (translated estimate from operating-margin tables, margin five years out)"
    if d.get("available"):
        # cross-check 19 (rulings A and B): the earnings-margin quantiles on the main line, labelled a translated estimate five years out (your
        # long_run_margin is the margin at the end of the fade); the operating quantiles, om_tc, Delta and t on the supporting context line
        if d.get("earnings") is not None:
            lines.append(f"- {name}: cohort: {d['cohort_text']}{fb(d)}; the spread of the n={d['n']:,} of them {d['level_text']}, vintage {V} | "
                         f"earnings margin: {_qline(d['earnings'], show_p50, _pct)} | measured five years out; your long_run_margin is the margin at "
                         f"the end of your fade")
        else:
            lines.append(f"- {name}: not available — {d.get('earnings_reason')}")
        dv = "not available" if d.get("delta") is None else _pct(d["delta"], True)
        base_txt = "8-year median operating margin" if d["centre_basis"] == "8-year median" else "base-year operating margin"
        dev_txt = _pct(d["dev"], True) if d["dev"] is not None else "(none)"
        lines.append(f"- long_run_margin context (the operating margin five years out, the tables' unit): {_qline(d['operating'], show_p50, _pct)} | "
                     f"centred on the median path: your {base_txt} {_pct(d['centre_8y_median'])} plus {d['r5']:.2f} of your base year's deviation "
                     f"from it {dev_txt} ({d['r5_source']}) | the translation: earnings margin = (1 - t) x operating margin + Delta; "
                     f"t = {_pct(d['tax_t'])}, {d['tax_t_source']}; Delta = {dv}, your earnings margin less (1 - that year's tax rate) x its "
                     f"operating margin, {d.get('delta_source')}; om_tc {_pct(d.get('om_tc'))}, m_tc {_pct(d.get('m_tc'))} (DEFAULTS long_run)")
    else:
        lines.append(na(name, d))
    d = ins.get("normalization") or {}
    name = "the margin by cyclicality alone"
    if d.get("available"):
        path = f"; your operating margin on that path: {_pct(d['op_median_path'])}" if d.get("op_median_path") is not None else ""
        lines.append(f"- {name}: cohort: {d['cohort_text']}; n={d['n']:,} at year {d['k']}, vintage {V} | the median company kept "
                     f"{d['retention_median']:.2f} of its operating margin's deviation from its 8-year median after {d['k']} years{path} | "
                     f"P10 and P90 {NOT_MEASURED}")
    else:
        lines.append(na(name, d))
    d = ins.get("growth_years_3_10") or {}
    name = "growth of years 3-10 population"
    if d.get("available"):
        yrs = []
        for k in sorted(d["by_k"]):
            q = d["by_k"][k]
            pts = [f"P25 {_pct(q['p25'], True)}"] + ([f"P50 {_pct(q['p50'], True)}"] if show_p50 else []) + [f"P75 {_pct(q['p75'], True)}"]
            yrs.append(f"year {k} " + " ".join(pts))
        ratio = ""
        if d.get("ratio"):
            ratio = (f" | the share of year 1's {d['what']} growth above the long-run reference {_pct(d['terminal_reference'], digits=2)} still there in "
                     f"year {d['ratio_k']} (n={d['ratio_n']:,}): {_qline(d['ratio'], show_p50, lambda v: NOT_MEASURED if v is None else f'{v:.2f}')}")
        lines.append(f"- {name} ({d['what']} growth in each year): cohort: {d['cohort_text']}{fb(d)}; n={d['n']:,}, vintage {V} | "
                     f"P10 and P90 {NOT_MEASURED} | " + "; ".join(yrs) + ratio)
    else:
        lines.append(na(name, d))
    d = ins.get("revenue_cagr_10y") or {}
    name = "10-year revenue CAGR (context for your growth path; it bounds the revenue growth to year 10 your inputs imply)"
    if d.get("available"):
        k_note = "" if d.get("K") == 10 else f" (this vintage measures {d['K']} years)"
        lines.append(f"- {name}: cohort: {d['cohort_text']}{k_note}{fb(d)}; n={d['n']:,}, vintage {V} | "
                     f"{_qline(d['quantiles'], show_p50, lambda v: _pct(v, True))}")
    else:
        lines.append(na(name, d))
    d = ins.get("terminal_ronic") or {}
    name = "terminal_ronic context (the return on invested capital five years out)"
    if d.get("available"):
        lines.append(f"- {name}: cohort: {d['cohort_text']}{fb(d)}; the spread of the n={d['n']:,} of them {d['level_text']}, vintage {V} | "
                     f"{_qline(d['quantiles'], show_p50, _pct)} | centred on the median path: the population median ROIC of FY{d['reference_year']} "
                     f"{_pct(d['reference'])} plus {d['phi5']:.2f} of the distance from it to your trailing 3-year ROIC {_pct(d['L0'])}")
    else:
        lines.append(na(name, d))
    return "\n".join(lines)


# ---- the cohort's bounds for the plausibility gate --------------------------------------------------------------------------------------------

def gate_bounds(ranges: Optional[dict]) -> Dict[str, Optional[dict]]:
    """{metric: {"p5", "p10", "p90", "p95", "cohort", "n", "K"} or None}: the cohort bounds the plausibility gate compares the implied trajectory
    with (fiduciary_gate.plausibility_gate). Step 2c: long_run_margin from the long-run margin's earnings-margin equivalents (ruling 2); revenue_cagr_10y
    from the terminal table's K-year revenue CAGR (ruling 5); terminal_ronic from the ROIC level five years out (ruling 6); earnings_ratio_10y has no
    measured cohort (None); terminal_g has no population range (ruling 5: the gate checks it against the pack's growth anchor). None also when the
    input is not available."""
    ins = (ranges or {}).get("inputs") or {}

    def b(name, key):
        d = ins.get(name) or {}
        q = d.get(key) if d.get("available") else None
        if not q or any(q.get(k) is None for k in ("p5", "p10", "p90", "p95")):
            return None
        return {"p5": q["p5"], "p10": q["p10"], "p90": q["p90"], "p95": q["p95"], "cohort": d.get("cohort"), "n": d.get("n"), "K": d.get("K")}
    return {"long_run_margin": b("long_run_margin", "earnings"), "revenue_cagr_10y": b("revenue_cagr_10y", "quantiles"),
            "terminal_ronic": b("terminal_ronic", "quantiles"), "earnings_ratio_10y": None}


def family_unmeasured(ranges: Optional[dict], metric: str) -> bool:
    """Whether the tables measure no population for this metric's input because of the company's family (ruling 7 of step 2b)."""
    src = {"long_run_margin": "long_run_margin", "revenue_cagr_10y": "revenue_cagr_10y", "terminal_ronic": "terminal_ronic"}.get(metric)
    d = ((ranges or {}).get("inputs") or {}).get(src) if src else None
    return bool(isinstance(d, dict) and d.get("family_unmeasured"))
