"""Backtest registration section 3: the two arms, as thin wrappers around the revisions' own `build`.

`cref` is a revision's consensus_reference module and `tcr` revision 17's throughcycle_record; the caller passes them in
(one revision per process), so this file imports neither and the two revisions never meet.  Every call of `build` in
the harness goes through `baseline_build` / `candidate_build`, so the production-input check (C2) exercises the very
call sites the backtest uses.

One name-date `nm` is a plain dict:
  rows       {fiscal year (str or int): the extractor's row}, years up to and including L
  L          base fiscal year (int);  stub_months  months from L's fiscal year end to T (as production's `_stub`)
  untagged   the extractor's untagged_fields for the company;  dc_tags  {year: debt_current tag} (provenance runs resolved)
  shares     diluted weighted-average shares of L, split-adjusted to T (4.3)
  m          the synthetic growth (4.6) or None;  sector;  y_L  mean DTB3 over the 12 months to L's fiscal year end

0.0 is a value: every numeric test uses `is_num`, never truthiness.
"""
import math
import statistics

from .common import is_num, is_num_or_inf

FINANCIAL_SECTORS = ("Financial Services", "Real Estate")     # 3.2.3: no cash term for these (cash is an operating asset)


# ---- the shared pieces ---------------------------------------------------------------------------------------------

def owner_earnings(row):
    """NI + D&A - capex of a fiscal-year row, or None when any of the three is missing."""
    ni, da, cx = row.get("net_income"), row.get("da"), row.get("capex")
    if is_num(ni) and is_num(da) and is_num(cx):
        return float(ni) + float(da) - float(cx)
    return None


def synthetic_estimates(rev_L, ni_L, shares, m):
    """4.6: the consensus-free estimates handed to both builds.  EPS growth m for the current and the next year, one analyst,
    year-ago EPS = NI_L / diluted shares (a non-positive base routes the name to 'no value', as production would without
    consensus levels); revenue averages rev_L (1+m) and rev_L (1+m)^2, growth m, one analyst; no high or low range."""
    return {"0y": {"eps": {"growth": m, "year_ago": ni_L / shares, "analysts": 1},
                   "revenue": {"avg": rev_L * (1.0 + m), "growth": m, "analysts": 1}},
            "+1y": {"eps": {"growth": m, "analysts": 1},
                    "revenue": {"avg": rev_L * (1.0 + m) ** 2, "growth": m, "analysts": 1}}}


def classify_failure(out):
    """The reason a `build` result carries no value, as a short key for the per-reason counts."""
    why = out.get("growth_unusable") or ""
    reason = out.get("reason") or ""
    if why.startswith("EPS base"):
        return "eps_base_not_positive"
    if why:
        return "growth_unusable"
    if reason == "cost of equity not above terminal growth":
        return "coe_not_above_terminal_growth"
    if reason:
        return "build_other"
    return "no_value"


def _precheck(nm):
    """(reason, rowL, OE, rev) - the failures common to both arms, before any build."""
    rows = nm["rows"]
    rowL = rows.get(str(nm["L"]))
    if rowL is None:
        rowL = rows.get(nm["L"])
    if rowL is None:
        return "no_base_row", None, None, None
    oe = owner_earnings(rowL)
    if oe is None:
        return "owner_earnings_missing", rowL, None, None
    if not oe > 0:
        return "owner_earnings_not_positive", rowL, oe, None
    if not is_num(nm.get("m")):
        return "m_missing", rowL, oe, None
    if not (is_num(nm.get("shares")) and nm["shares"] > 0):
        return "shares_missing", rowL, oe, None
    rev, ni = rowL.get("revenue"), rowL.get("net_income")
    if not (is_num(rev) and rev > 0):
        return "revenue_missing", rowL, oe, None
    if not is_num(ni):
        return "net_income_missing", rowL, oe, None
    return None, rowL, oe, float(rev)


# ---- the baseline: revision 16's engine, unchanged ------------------------------------------------------------------

def baseline_build(cref, *, base_cf, estimates, coe, terminal_g, shares, median_5y, stub_months=None, base_label=None,
                   da=None, capex=None, levels_reason=None, levels_block=None, anchor=None):
    """The single call site of revision 16's `build`."""
    return cref.build(base_cf, estimates, coe, terminal_g, shares, median_5y, da=da, capex=capex, stub_months=stub_months,
                      base_label=base_label, levels_reason=levels_reason, levels_block=levels_block, anchor=anchor)


def baseline_terminal_growth(cref, gA, pi, m):
    """3.1: terminal_default(gA, pi, None, m), which returns gA (no consensus revenue growth is passed)."""
    return cref.terminal_default(gA, pi, None, m)[0]


def baseline_value(cref, nm, coe, terminal_g, estimates=None):
    """3.1: V_B for one name-date.  {'value', 'reason', 'coe', 'terminal_g'}; value None carries a reason key."""
    res = {"value": None, "reason": None, "coe": coe, "terminal_g": terminal_g}
    why, rowL, oe, rev = _precheck(nm)
    if why:
        res["reason"] = why
        return res
    if not is_num(coe):
        res["reason"] = "coe_missing"
        return res
    est = estimates if estimates is not None else synthetic_estimates(rev, float(rowL["net_income"]), nm["shares"], nm["m"])
    out = baseline_build(cref, base_cf=oe, estimates=est, coe=coe, terminal_g=terminal_g, shares=nm["shares"],
                         median_5y=nm["m"], stub_months=nm.get("stub_months"))
    if out.get("value") is None:
        res["reason"] = classify_failure(out)
    else:
        res["value"] = float(out["value"])
    return res


# ---- the structural candidate: revision 17's arithmetic with the registered inputs ----------------------------------

class Switches:
    """What the harness changes in revision 17's inputs.  The registered candidate is the default; the other settings exist
    for the checks (C2: everything off = revision 17 as committed; C3: the reduction to revision 16)."""

    def __init__(self, returns="rtc", margin="trend", cash=True, working_capital=True, terminal="trend", earnings_base="X",
                 x_l_override=True):
        assert returns in ("rtc", "inf", "analyse")
        assert margin in ("trend", "none", "analyse")
        assert terminal in ("trend", "gA")
        assert earnings_base in ("X", "OE")
        self.returns, self.margin, self.cash = returns, margin, cash
        self.working_capital, self.terminal, self.earnings_base = working_capital, terminal, earnings_base
        self.x_l_override = x_l_override        # False exists only to show, in a test, the double count the override prevents


REGISTERED = Switches()
REVISION_17_AS_COMMITTED = Switches(returns="analyse", margin="analyse", cash=False, working_capital=True, terminal="trend")


def candidate_build(cref, *, base_cf, estimates, coe, terminal_g, shares, median_5y, stub_months=None, base_label=None,
                    da=None, capex=None, levels_reason=None, levels_block=None, anchor=None, record=None, base_ni=None,
                    base_revenue=None, base_cap=None):
    """The single call site of revision 17's `build`."""
    return cref.build(base_cf, estimates, coe, terminal_g, shares, median_5y, da=da, capex=capex, stub_months=stub_months,
                      base_label=base_label, levels_reason=levels_reason, levels_block=levels_block, anchor=anchor,
                      record=record, base_ni=base_ni, base_revenue=base_revenue, base_cap=base_cap)


def trend_level(tcr, rows, rec, L, untagged):
    """3.2.2: T_L = a + b L, with b the Theil-Sen slope of the margin series `analyse` chose (om_basis over om_years, each
    year from the same throughcycle_record margin function) and a = median(om_y - b y).  None when the record has no margin series."""
    basis, years = rec.get("om_basis"), rec.get("om_years")
    if basis is None or not years:
        return None
    fns = {"with_amortization": lambda row: tcr.operating_margin(row, untagged),
           "without_amortization": tcr.operating_margin_plain,
           "pretax_with_amortization": lambda row: tcr.pretax_margin(row, untagged),
           "pretax_without_amortization": tcr.pretax_margin_plain}
    nrows = tcr.normalise_rows(rows)
    pts = []
    for y in years:
        v = fns[basis](nrows[y])
        assert v is not None, "an om_year whose margin is undefined"
        pts.append((y, v))
    b = tcr.theil_sen(pts)
    if b is None:
        return None
    a = tcr.median([v - b * y for y, v in pts])
    return a + b * L


def returns_override(rec, coe):
    """3.2.1: R_tc, p from `analyse`; r_blend := R_tc and ronic_t := r + p max(0, R_tc - r) (+inf when R_tc is +inf);
    both None when R_tc is None (RONIC_T = r and the stamp record_not_available follow in `build`)."""
    r_tc, p = rec.get("R_tc"), rec.get("p")
    if r_tc is None:
        rec["r_blend"] = None
        rec["ronic_t"] = None
    else:
        rec["r_blend"] = r_tc
        rec["ronic_t"] = math.inf if r_tc == math.inf else coe + p * max(0.0, r_tc - coe)
    return rec


def cash_term(tcr, nm, rowL, untagged):
    """3.2.3: (C_L, i_L, stamps).  C_L = cash + short-term investments at L (a null short-term investments counts 0); a null
    cash means no cash term (C_L = i_L = 0, stamp).  i_L = C_L y_L (1 - tax_L), tax_L = throughcycle_record.tax_rate of L."""
    cash, sti = rowL.get("cash"), rowL.get("st_investments")
    if not is_num(cash):
        return 0.0, 0.0, ["cash_term_not_available"]
    c = float(cash) + (float(sti) if is_num(sti) else 0.0)
    y = nm.get("y_L")
    if not is_num(y):
        return 0.0, 0.0, ["cash_term_not_available_no_bill_rate"]
    return c, c * y * (1.0 - tcr.tax_rate(rowL)), []


def candidate_value(cref, tcr, nm, coe, gA, pi, sw=REGISTERED, estimates=None):
    """3.2: V_S for one name-date at the cost of equity `coe`.  {'value', 'reason', 'stamps', 'coe', 'terminal_g', ...}."""
    res = {"value": None, "reason": None, "stamps": [], "coe": coe, "terminal_g": None, "operating_base_not_positive": False,
           "cash": 0.0, "interest_removed": 0.0, "R_tc": None, "p": None, "trend_level": None}
    why, rowL, oe, rev = _precheck(nm)
    if why:
        res["reason"] = why
        return res
    if not is_num(coe):
        res["reason"] = "coe_missing"
        return res
    untagged = frozenset(nm.get("untagged") or ())
    L = nm["L"]
    rec = tcr.analyse(nm["rows"], coe, untagged_fields=untagged, base_year=L, debt_current_tags=nm.get("dc_tags") or {})
    res["R_tc"], res["p"] = rec["R_tc"], rec["p"]
    # returns
    if sw.returns == "rtc":
        returns_override(rec, coe)
    elif sw.returns == "inf":
        rec["r_blend"], rec["ronic_t"] = math.inf, math.inf
    # margins
    if sw.margin == "trend":
        t_l = trend_level(tcr, nm["rows"], rec, L, untagged)
        res["trend_level"] = t_l
        rec["om_tc"] = t_l
    elif sw.margin == "none":
        rec["om_tc"] = None
    if not sw.working_capital:
        rec["nwc_intensity"] = None
    # the earnings base and the cash term
    x_L = tcr.adjusted_earnings(rowL, untagged)
    base_cf = oe
    base_ni = x_L if sw.earnings_base == "X" else oe
    c_l = i_l = 0.0
    has_cash_term = False
    if sw.cash and nm.get("sector") not in FINANCIAL_SECTORS:
        c_l, i_l, stamps = cash_term(tcr, nm, rowL, untagged)
        res["stamps"] += stamps
        has_cash_term = not stamps
    res["cash"], res["interest_removed"] = c_l, i_l
    if has_cash_term:
        base_cf = oe - i_l
        base_ni = None if base_ni is None else base_ni - i_l
        if x_L is not None and sw.x_l_override:
            rec["x_L"] = (x_L - i_l) / rev       # without this override margin_rule reads the removed interest as a margin change
        if base_cf <= 0 or (base_ni is not None and base_ni <= 0):
            res["operating_base_not_positive"] = True
            res["stamps"].append("operating_base_not_positive")
            res["value"] = c_l / nm["shares"]
            res["terminal_g"] = None
            return res
    # terminal growth
    if sw.terminal == "trend":
        tg, basis, _ = cref.terminal_growth_default(gA, pi, rec["g_rev"], None, nm["m"])
    else:
        tg, _ = cref.terminal_default(gA, pi, None, nm["m"])
    res["terminal_g"] = tg
    est = estimates if estimates is not None else synthetic_estimates(rev, float(rowL["net_income"]), nm["shares"], nm["m"])
    out = candidate_build(cref, base_cf=base_cf, estimates=est, coe=coe, terminal_g=tg, shares=nm["shares"],
                          median_5y=nm["m"], stub_months=nm.get("stub_months"), anchor=gA, record=rec,
                          base_ni=base_ni, base_revenue=rev, base_cap=None)
    res["stamps"] += list(out.get("stamps") or [])
    res["build"] = {k: out.get(k) for k in ("terminal_ronic", "ronic0", "m_long", "om_5", "margin_cell", "margin_fraction", "margin_ratio",
                                              "long_run_path")}
    if out.get("value") is None:
        res["reason"] = classify_failure(out)
        return res
    res["value"] = float(out["value"]) + (c_l / nm["shares"] if has_cash_term else 0.0)
    return res


# ---- the cost of equity of each arm and variant ---------------------------------------------------------------------

def coe_of(adjL, rf_eff, erp):
    """COE_i = rf_eff + adjL x ERP (3.1 and 3.2.5)."""
    return rf_eff + adjL * erp


def erp_from_market(coe_mkt_B, rf_eff):
    """ERP_B = COE_mkt_B - rf_eff (3.1)."""
    return coe_mkt_B - rf_eff


def rf_effective(rf, gA):
    """4.4: rf_eff = max(rf, gA), a perpetual riskless rate is never taken below perpetual nominal growth."""
    return max(rf, gA)


def adjusted_loading(raw):
    """4.5: adjL = 0.67 raw + 0.33 (rs2_data.py:1175)."""
    return 0.67 * raw + 0.33
