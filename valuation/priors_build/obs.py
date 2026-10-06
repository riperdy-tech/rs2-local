"""obs.py - one company's observations at one vintage: the state at each fiscal year t, and what happened next.

An observation is (cik, fiscal year t).  Its STATE is computed from the first-filed rows of fiscal years up to t only; its OUTCOMES are the first-filed
rows of fiscal years t+1.. t+10.  A fiscal year exists only from its own annual report; the layer is asked for the company as of the vintage's cut
date, in `first_filed` mode, so every row was filed strictly before the cut date and nothing later can reach this module (the no-look-ahead proof
is a test: valuation/tests/test_priors.py).  A prior built at vintage V therefore uses an outcome only if the later year's annual report was filed
before V's cut date, which is not after any valuation date the vintage serves.

Fiscal years are put on a chain index (consecutive years differ by 1; a gap of n years jumps by n), so "t-7..t" and "t+k" mean years, not rows.

0.0 is a value: every test is `is None` / is_num.  Nothing is defaulted; a figure that cannot be computed is NaN (None before the DataFrame).
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional

from valuation import common as vc
from valuation.classification import classification
# chain_index, nopat_of and invested_capital are common's definitions (the engines' state reads them too); re-exported here for the callers that import them from obs
from valuation.common import (FIELDS, Filed, SicInfo, chain_index, cyclicality_score, invested_capital, nopat_of, num, total_debt,  # noqa: F401
                              trailing_level)
from valuation.pit_data import is_num

MAX_K = 10
WINDOW = 8                     # the A2 window: fiscal years t-7..t
RECORD_MIN = 5                 # the record rule: at least this many defined margin years in the window (Addendum A 1)
tcr = vc.tcr


def nan_if_none(x):
    return float("nan") if x is None else x


# ---- a company's chain of fiscal years -----------------------------------------------------------------------------------------------------

class PitView:
    """A CompanyPIT look-alike truncated at fiscal year t: what `classification` reads (periods, a base-period row, concepts, sic)."""

    def __init__(self, ticker, asof, periods, rows, reports, concepts, sic):
        self.ticker, self.asof = ticker, asof
        self._periods, self._rows = list(periods), rows
        self.annual_reports, self.concepts, self.sic = reports, concepts, sic
        self.series, self.shares_outstanding, self.notes, self.cik = {}, None, [], None

    def check(self):
        return

    def periods(self):
        return list(self._periods)

    def row(self, pe):
        return self._rows[pe]

    def rows(self):
        return {pe: self._rows[pe] for pe in self._periods}


# ---- the measures (the same definitions the engines' state uses) -----------------------------------------------------------------------------

def tax_rate_median(rows_by_pe, periods) -> float:
    """build_state's tax rule: the median effective rate over the latest 8 years with positive pre-tax income (tcr clip [0, 0.35]); the repo's default
    when there is none."""
    rates = []
    for p in periods[-8:]:
        r = rows_by_pe[p]
        pt, tx = num(r["pretax_income"]), num(r["tax_provision"])
        if pt is not None and tx is not None and pt > 0:
            rates.append(tcr.tax_rate(r))
    return vc._median(rates) if rates else tcr.TAX_DEFAULT


def bridge_of(row) -> Optional[float]:
    """The equity bridge of the engines at EV = 0 (common.equity_bridge): -debt - finance leases - minority interest + cash + short-term and long-term
    investments (operating leases not subtracted).  EV = market cap - bridge.  None unless debt and cash are filed (an untagged lease or investment is none)."""
    d, cash = total_debt(row), num(row.get("cash"))
    if d is None or cash is None:
        return None
    g = lambda k: 0.0 if num(row.get(k)) is None else num(row.get(k))
    eq, eqn = num(row.get("equity")), num(row.get("equity_incl_nci"))
    nci = (eqn - eq) if (eq is not None and eqn is not None) else 0.0
    return -d - g("finance_lease_liability") - nci + cash + g("st_investments") + g("lt_investments")


def tbv_of(row) -> Optional[float]:
    """Tangible book value of build_state: equity - goodwill - intangibles, less preferred equity when both are filed."""
    t, _ = tcr.tangible_equity_detail(row)
    pref = num(row.get("preferred_equity"))
    if t is not None and pref is not None:
        t -= pref
    return t


def margin_of(row) -> Optional[float]:
    rev, oi = num(row.get("revenue")), num(row.get("operating_income"))
    return None if (rev is None or not rev > 0 or oi is None) else oi / rev


def rev_of(row) -> Optional[float]:
    r = num(row.get("revenue"))
    return r if (r is not None and r > 0) else None


def fcff_of(row, prev_row, tax) -> Optional[float]:
    """Realised FCFF of a year: NOPAT - (capex - D&A + change in net working capital).  The inputs of the engines' chain, on filed figures."""
    n = nopat_of(num(row.get("operating_income")), tax)
    cx, da = num(row.get("capex")), num(row.get("da"))
    if n is None or cx is None or da is None or prev_row is None:
        return None
    w1, w0 = tcr.net_working_capital(row), tcr.net_working_capital(prev_row)
    if w1 is None or w0 is None:
        return None
    return n - (cx - da + (w1 - w0))


def last_weekday_of_month(y, m) -> date:
    import calendar
    d = date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def obs_date(filed_iso: str) -> date:
    """The first month-end session (last weekday of a month) strictly after the filing date of the base year's annual report: the date at which the
    state is known and a price is read (Addendum C 2: a filing accepted after the close is not in the day's price)."""
    f = date.fromisoformat(filed_iso)
    y, m = f.year, f.month
    for _ in range(3):
        d = last_weekday_of_month(y, m)
        if d > f:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return last_weekday_of_month(y, m)


def trend_slope(logrev_by_idx: Dict[int, float]) -> Optional[float]:
    """OLS slope of ln(revenue) on the chain index (A2's trailing-slope test of a shrinking company); None under 5 points."""
    if len(logrev_by_idx) < RECORD_MIN:
        return None
    xs = sorted(logrev_by_idx)
    ys = [logrev_by_idx[x] for x in xs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return None if sxx == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def rote_by_period(rows_by_pe, idx) -> Dict[str, float]:
    """Return on tangible equity of a year: net income over the average of this and the previous year's tangible book (the previous year only when it
    is the previous fiscal year on the chain), else over this year's; defined when the denominator is positive."""
    out = {}
    tb = {pe: tbv_of(r) for pe, r in rows_by_pe.items()}
    by_idx = {idx[pe]: pe for pe in rows_by_pe}
    for pe, r in rows_by_pe.items():
        ni, t = num(r.get("net_income")), tb[pe]
        if ni is None or t is None:
            continue
        pp = by_idx.get(idx[pe] - 1)
        tp = tb.get(pp) if pp is not None else None
        den = 0.5 * (t + tp) if tp is not None else t
        if den > 0:
            out[pe] = ni / den
    return out


# ---- the observation table of one company ----------------------------------------------------------------------------------------------------

COLUMNS_STATE = ("cik", "fye", "own_filed", "form", "currency", "family", "family_basis", "sic", "conflict", "years_held", "rev", "g_latest", "g3",
                 "m", "med8", "n8", "dev", "cyc", "c_mv", "c_rf", "c_ac", "c_rc", "cyc_years", "tax", "nopat", "ic", "roic", "roic3", "tbv", "rote",
                 "tbv_g_latest", "tbv_g3", "rote_med8", "rote_n8", "rote_dev", "trend8", "obs_date", "fcff1", "n_ahead", "revenue_cagr_ok")


def company_observations(c, cut_iso: str, sic_code: Optional[str], ticker: str = "") -> List[dict]:
    """Observations of CompanyPit `c` at the vintage whose cut date is `cut_iso`.  Empty when the company has no fiscal year before the cut."""
    fys = c.fiscal_years(cut_iso, "first_filed")
    if not fys:
        return []
    periods = sorted(fys)
    idx = chain_index(periods)
    by_idx = {idx[p]: p for p in periods}
    rows = {}
    for p in periods:
        full = {f: None for f in FIELDS}
        full.update({k: v for k, v in fys[p].row().items()})
        rows[p] = full
    conc_raw = c.concepts(cut_iso, names=("LoansAndLeasesReceivableNetReportedAmount", "LoansAndLeasesReceivableNetOfDeferredIncome",
                                          "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss", "LoansReceivableNet", "Deposits"),
                         mode="first_filed")
    concepts = {n: {pe: Filed(x.val, pe, x.filed, x.accn, x.form, x.tag) for pe, x in per.items()} for n, per in conc_raw.items()}
    sic = SicInfo(sic_code, "", "damodaran indname 2026-01 via current ticker (current-dated)", False) if sic_code else None

    rev = {p: rev_of(rows[p]) for p in periods}
    om = {p: margin_of(rows[p]) for p in periods}
    tb = {p: tbv_of(rows[p]) for p in periods}
    rote = rote_by_period(rows, idx)
    ic = {p: invested_capital(rows[p]) for p in periods}
    out = []
    for pos, p in enumerate(periods):
        fy = fys[p]
        t = idx[p]
        upto = periods[:pos + 1]
        tax = tax_rate_median(rows, upto)
        r0 = rev[p]
        # growth delivered
        pm = by_idx.get(t - 1)
        g_latest = (r0 / rev[pm] - 1.0) if (r0 is not None and pm is not None and rev[pm] is not None) else None
        p3 = by_idx.get(t - 3)
        g3 = ((r0 / rev[p3]) ** (1.0 / 3.0) - 1.0) if (r0 is not None and p3 is not None and rev[p3] is not None) else None
        tg_latest = (tb[p] / tb[pm] - 1.0) if (tb[p] is not None and tb[p] > 0 and pm is not None and tb[pm] is not None and tb[pm] > 0) else None
        tg3 = ((tb[p] / tb[p3]) ** (1.0 / 3.0) - 1.0) if (tb[p] is not None and tb[p] > 0 and p3 is not None and tb[p3] is not None and tb[p3] > 0) else None
        # margin: A2's window t-7..t on the chain index
        win = [by_idx[i] for i in range(t - WINDOW + 1, t + 1) if i in by_idx]
        mw = [om[q] for q in win if om[q] is not None]
        m0 = om[p]
        med8 = statistics.median(mw) if len(mw) >= RECORD_MIN else None
        dev = (m0 - med8) if (m0 is not None and med8 is not None) else None
        rw = [rote[q] for q in win if q in rote]
        rmed = statistics.median(rw) if len(rw) >= RECORD_MIN else None
        rdev = (rote[p] - rmed) if (p in rote and rmed is not None) else None
        # cyclicality score: the engines' function on the latest 12 years up to t
        omd = {q: om[q] for q in upto if om[q] is not None}
        rvd = {q: rev[q] for q in upto if rev[q] is not None}
        cyc, _why = cyclicality_score(omd, rvd)
        comp = cyc["components"] if cyc else {}
        # ln revenue trend over the window
        lr = {idx[q]: math.log(rev[q]) for q in win if rev[q] is not None}
        # family
        view = PitView(ticker or c.cik, date.fromisoformat(fy.exists_from) + timedelta(days=1), upto, rows,
                       [(q, fys[q].exists_from, fys[q].own_accn, fys[q].own_form) for q in upto], concepts, sic)
        cl = classification(ticker or c.cik, view.asof, view)
        nop = nopat_of(num(rows[p].get("operating_income")), tax)
        icp = ic[p]
        # Addendum H3: the trailing 3-year ROIC level at t (the state's own definition: NOPAT at the observation's tax rate / invested capital, three consecutive years)
        roic_y = {}
        for q in upto:
            nq, iq = nopat_of(num(rows[q].get("operating_income")), tax), ic[q]
            if nq is not None and iq is not None and iq > 0:
                roic_y[q] = nq / iq
        roic3 = trailing_level(roic_y, idx, p)
        # outcomes
        rec = {"cik": c.cik, "fye": p, "own_filed": fy.exists_from, "form": fy.own_form, "currency": fy.currency, "family": cl["family"],
               "family_basis": "sic+bs" if sic_code else "bs_only", "sic": sic_code, "conflict": bool(cl["conflicts"]), "years_held": len(upto),
               "rev": r0, "g_latest": g_latest, "g3": g3, "m": m0, "med8": med8, "n8": len(mw), "dev": dev,
               "cyc": cyc["score"] if cyc else None, "c_mv": comp.get("margin_volatility"), "c_rf": comp.get("reversal_frequency"),
               "c_ac": comp.get("autocorrelation"), "c_rc": comp.get("revenue_cyclicality"), "cyc_years": cyc["years"] if cyc else None,
               "tax": tax, "nopat": nop, "ic": icp, "roic": (nop / icp) if (nop is not None and icp is not None and icp > 0) else None, "roic3": roic3,
               "tbv": tb[p], "bridge": bridge_of(rows[p]), "rote": rote.get(p), "tbv_g_latest": tg_latest, "tbv_g3": tg3, "rote_med8": rmed, "rote_n8": len(rw), "rote_dev": rdev,
               "trend8": trend_slope(lr), "obs_date": obs_date(fy.exists_from).isoformat(), "fcff1": None, "revenue_cagr_ok": r0 is not None}
        n_ahead = 0
        for k in range(1, MAX_K + 1):
            q = by_idx.get(t + k)
            if q is None:
                for nm in ("rev", "m", "nopat", "ic", "tbv", "rote", "filed"):
                    rec[f"{nm}_{k}"] = None
                continue
            n_ahead = k
            rec[f"rev_{k}"] = rev[q]
            rec[f"m_{k}"] = om[q]
            rec[f"nopat_{k}"] = nopat_of(num(rows[q].get("operating_income")), tax)
            rec[f"ic_{k}"] = ic[q]
            rec[f"tbv_{k}"] = tb[q]
            rec[f"rote_{k}"] = rote.get(q)
            rec[f"filed_{k}"] = fys[q].exists_from
            if k == 1:
                rec["fcff1"] = fcff_of(rows[q], rows[p], tax)
        rec["n_ahead"] = n_ahead
        out.append(rec)
    return out
