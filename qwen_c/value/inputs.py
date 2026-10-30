"""inputs.py - the code-owned valuation inputs of 3Q (SPEC_m3q_valuation.md §2, §4 V8; CROSS_CHECK_Q_RULINGS batch C).

Code owns every measured quantity; the model owns the forecast (growth, margins, F, the long-run margin, RONIC_T, terminal g). Nothing
here is a default of either: an input that cannot be measured is a named refusal (desk.DeskRefusal) or, where the economics allow a
consistent zero, a stated zero with a stamp.

THE EARNINGS BASE (rulings 6, 9). From filed pretax income, so neither a one-year tax anomaly nor the interest earned on cash is
capitalised:
    pt_ex = PT_0 - C x bill - NCI_0 / (1 - tau)          C = cash + short-term investments, bill = the 3-month bill rate over FY0
    X_0   = (pt_ex + A_0)(1 - tau)                        A_0 only when the amortization basis holds in every pooled year (ruling 19)
    K_0   = OI_0 - pt_ex                                  the non-operating items only, held flat in dollars by the bridge
The operating-margin bridge X_t = (op_t R_t + A_t - K_0)(1 - tau), A_t the filed amortization schedule (0 once run off; the long-run
margin is bridged with A = 0), returns X_0 at the base year, and cash is added once, at face. K_0 carrying A_0 made the base year's
amortization permanent (found by the v1.3 production-path test, D_acquirer +12%). With no
bill rate the cash is NOT added and the interest stays in the base (stamped): never both.
"""
import statistics

from qwen_c.value import desk
from qwen_c.value.desk import DeskRefusal
from qwen_c.value.facts import DA_EXCLUDES_AMORTIZATION

INPUTS_VERSION = "m3q.inputs.v6"   # v6 2026-10-30 WO_Q6: base_financial record book_growth_max; v5 2026-10-30 B12b bounds: delta cap, negative equity at the cap, interest-only K_0 scaling   # v4 2026-10-30 B12: K_0 scales with revenue, delta at the book ratio   # v3 2026-10-30 CROSS_CHECK_Q2: net-debt delta, NCI bounds, vintages bounds, stamps
POOL_YEARS = 5
MIN_POOL_YEARS = 3
TAX_BAND = (0.0, 0.35)
PERSISTENT_SPREAD = 0.05
TAX_DEPART = 0.05            # ruling 9: the latest in-band rate is used only within 5 points of the in-band median
KD_BAND = (0.01, 0.20)       # ruling 5 (the audited coverage rule)
SHARES_TOL = 0.05            # ruling 5: NI / diluted shares against filed diluted EPS
RONIC0_CAP = 1.0             # ruling 21 (the doctrine's cap)
EPS_ROUNDING = 0.006         # CROSS_CHECK_Q2 N15
NCI_MATERIAL, NCI_DOMINANT = 0.10, 0.25   # N9
VINTAGE_LIFE = (5, 40)       # N8
VINTAGE_RATIO_TOL = 0.5
DELTA_CAP = 0.75             # B12b (OPINION_B12b_fable.md): the book delta's ceiling
DEBT_TOTAL_EXCLUDES_SHORT = {"LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"}
CURRENT_INCLUDES_SHORT = {"DebtCurrent", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"}


def _by_end(f, concept):
    return {v["end"]: v["value"] for v in (f.get(concept) or {}).get("values", [])}


def _tag(f, concept, end):
    return next((v["tag"] for v in (f.get(concept) or {}).get("values", []) if v["end"] == end), None)


def tax_rate(f):
    """V8: (tau, stamp). The in-band years (provision / pretax in [0, 0.35], positive pretax) of the last 8: with >= 3 of them, their median
    unless the latest year is in band and within 5 points of it (then the latest); with fewer, the latest if in band; else a persistent
    rate (>= 3 measured years, all >= 0, within 5 points): their median; else refused."""
    tax, pre = _by_end(f, "tax_provision"), _by_end(f, "pretax_income")
    years = sorted(set(tax) & set(pre))
    rates = [(e, tax[e] / pre[e]) for e in years if pre[e] > 0][-8:]
    band = [t for _, t in rates if TAX_BAND[0] <= t <= TAX_BAND[1]]
    latest_in_band = rates and rates[-1][0] == years[-1] and TAX_BAND[0] <= rates[-1][1] <= TAX_BAND[1]
    if len(band) >= 3:
        med = statistics.median(band)
        if latest_in_band and abs(rates[-1][1] - med) <= TAX_DEPART:
            return rates[-1][1], "tax_rate_measured"
        return med, "tax_rate_multi_year_median"
    if latest_in_band:
        return rates[-1][1], "tax_rate_measured_short_history"
    recent = [t for _, t in rates]
    if len(recent) >= 3 and min(recent) >= 0 and max(recent) - min(recent) <= PERSISTENT_SPREAD and max(recent) < 1:
        return statistics.median(recent), "tax_rate_persistent_outside_band"
    raise DeskRefusal("tax_unavailable", f"no usable measured tax rate (latest {rates[-1][1] if rates else None}); never a stamped default")


def debt_total(f, end):
    """(debt at fiscal-year end `end`, how) or (None, None) when no debt tag is filed for it (rulings 5, 27)."""
    tot, nc, cur, sh = (_by_end(f, k).get(end) for k in ("debt_total", "debt_noncurrent", "debt_current", "debt_short"))
    if tot is not None:
        t = _tag(f, "debt_total", end)
        if t in DEBT_TOTAL_EXCLUDES_SHORT and sh is not None:
            return tot + sh, f"{t}+short"
        return tot, t
    if nc is None and cur is None and sh is None:
        return None, None
    parts = (nc or 0.0) + (cur or 0.0)
    if sh is not None and _tag(f, "debt_current", end) not in CURRENT_INCLUDES_SHORT:
        parts += sh
    return parts, "components"


def base(f, *, market_cap, bill_rate):
    """The measured base for value_operating. `market_cap` (USD, from the formation's price row) sets delta at market weights (O5);
    `bill_rate` (a fraction, or None) is the 3-month bill rate over the base fiscal year (the cash term)."""
    rev = _by_end(f, "revenue")
    ends = sorted(rev)[-POOL_YEARS:]
    if len(ends) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(ends)} fiscal years of revenue; at least {MIN_POOL_YEARS} are needed to pool")
    e0 = ends[-1]
    if any(not rev[e] > 0 for e in ends):
        raise DeskRefusal("revenue_not_positive", f"a pooled year has revenue <= 0: {[(e, rev[e]) for e in ends if not rev[e] > 0]}")
    stale = {c: d for c, d in (f.get("_stale") or {}).items() if c in ("net_income", "capex", "da", "revenue", "pretax_income", "operating_income")}
    if stale:
        raise DeskRefusal("facts_stale", f"concepts end before the latest revenue year {e0}: {stale}")
    if f.get("_latest_annual_period") and f["_latest_annual_period"] > e0:
        raise DeskRefusal("base_year_not_latest_annual", f"the newest eligible annual report is for {f['_latest_annual_period']}, the facts end {e0}")
    stamps = ["rou_depreciation_not_separated", "leases_not_modeled"]
    if any((v.get("form") or "").startswith(("20-F", "40-F")) for v in f["revenue"]["values"]):
        stamps.append("per_share_basis_unverified")                         # ruling 18: no ADS ratio is applied
    else:
        stamps.append("split_after_fy0_unchecked")                          # CROSS_CHECK_Q2 #18: split detection not built
    tau, s = tax_rate(f)
    stamps.append(s)
    ni, da, cx, am, pt, oi = (_by_end(f, k) for k in ("net_income", "da", "capex", "amortization", "pretax_income", "operating_income"))
    for name, series in (("net_income", ni), ("da", da), ("capex", cx), ("pretax_income", pt), ("operating_income", oi)):
        if e0 not in series:
            raise DeskRefusal("input_missing" if name not in ("operating_income",) else "bridge_unavailable", f"{name} for the latest fiscal year {e0}")
    pool = [e for e in ends if e in da and e in cx]
    if len(pool) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(pool)} years with revenue, D&A and capex")
    # ruling 19: the amortization basis holds in every pooled year, or nowhere
    sched = [_by_end(f, f"amort_next_{k}").get(e0) for k in range(1, 6)]
    after = _by_end(f, "amort_after_5").get(e0)
    use_amort = all(a is not None for a in sched) and all(e in am for e in pool)
    if use_amort:
        a0, amort_schedule, amort_after = am[e0], sched, (after if after is not None else 0.0)
        if after is None:
            stamps.append("amortization_after_year5_not_filed")
    else:
        a0, amort_schedule, amort_after = 0.0, [0.0] * 5, 0.0
        stamps.append("amortization_basis_not_filed_every_year")
    # the cash term (ruling 6)
    cash = _by_end(f, "cash")
    if e0 not in cash:
        raise DeskRefusal("input_missing", f"cash for {e0}")
    c_l = cash[e0] + _by_end(f, "st_investments").get(e0, 0.0)
    if bill_rate is None:
        i_pre, excess_cash = 0.0, 0.0
        stamps.append("cash_term_not_available_no_bill_rate")
    else:
        i_pre, excess_cash = c_l * bill_rate, c_l
    nci = _by_end(f, "nci_income").get(e0)
    if nci is None:
        nci = 0.0
        stamps.append("nci_not_filed")
    elif pt[e0] > 0 and abs(nci) / pt[e0] > NCI_DOMINANT:                # N9: the K_0 dollar hold of the NCI share is not valid then
        raise DeskRefusal("nci_dominant", f"NCI {nci:.6g} is {abs(nci) / pt[e0]:.0%} of pretax income")
    elif pt[e0] > 0 and abs(nci) / pt[e0] > NCI_MATERIAL:
        stamps.append("nci_material")
    pt_ex = pt[e0] - i_pre - nci / (1 - tau)
    x0 = (pt_ex + a0) * (1 - tau)
    if not x0 > 0:
        raise DeskRefusal("e0_not_positive", f"X_0 = {x0:.6g}: no earnings base (O7)")
    k0 = oi[e0] - pt_ex
    k0_int = _by_end(f, "interest_expense").get(e0) or 0.0                                            # B12b: only interest scales with revenue (debt grows with it)
    stamps.append("bridge_constant_from_base_year")
    r_sum = sum(rev[e] for e in pool)
    da_tag = {v["end"]: v["tag"] for v in f["da"]["values"]}
    d_ratio = sum(da[e] - (am[e] if use_amort and da_tag[e] not in DA_EXCLUDES_AMORTIZATION else 0.0) for e in pool) / r_sum
    c_ratio = sum(cx[e] for e in pool) / r_sum
    capex_record = {e: cx[e] / rev[e] for e in pool}
    ac, lc, eq, ie, gw, ia = (_by_end(f, k) for k in ("assets_current", "liabilities_current", "equity", "interest_expense", "goodwill",
                                                       "intangibles"))
    if not (e0 in ac and e0 in lc):
        raise DeskRefusal("input_missing", f"current assets and current liabilities for {e0}")
    debt0, how0 = debt_total(f, e0)
    if how0 and how0.startswith("LongTermDebt") and _tag(f, "debt_current", e0) == "LongTermDebtCurrent":
        stamps.append("debt_total_tag_ambiguous")                          # CROSS_CHECK_Q2 #27 (MTCH)
    prev = ends[-2]
    debt_prev, _ = debt_total(f, prev)
    interest = ie.get(e0)
    if debt0 is None:
        if interest:
            raise DeskRefusal("debt_unavailable", f"interest expense {interest:.6g} is filed for {e0} but no debt tag resolves")
        debt0, how0 = 0.0, "no_debt_filed"
        stamps.append("no_debt_filed")
    if debt_prev is None:
        debt_prev = 0.0 if how0 == "no_debt_filed" else None
    if debt_prev is None:
        raise DeskRefusal("debt_unavailable", f"no debt tag resolves for the opening year {prev}")
    if debt0 > 0 and not interest:
        raise DeskRefusal("debt_without_interest", f"debt {debt0:.6g} at {e0} with no filed interest expense")
    kd = interest / ((debt0 + debt_prev) / 2) if debt0 + debt_prev > 0 else 0.0
    if debt0 + debt_prev > 0 and not KD_BAND[0] <= kd <= KD_BAND[1]:
        raise DeskRefusal("kd_out_of_band", f"kd = interest / average debt = {kd:.4f}, outside {KD_BAND}")
    cur_debt = _by_end(f, "debt_current").get(e0, 0.0) + (_by_end(f, "debt_short").get(e0, 0.0)
                                                           if _tag(f, "debt_current", e0) not in CURRENT_INCLUDES_SHORT else 0.0)
    nwc0 = (ac[e0] - cash[e0] - _by_end(f, "st_investments").get(e0, 0.0)) - (lc[e0] - cur_debt)
    w = nwc0 / rev[e0]
    if not (prev in eq and prev in cash):
        raise DeskRefusal("input_missing", f"equity and cash for {prev} (the opening capital)")
    for c in ("goodwill", "intangibles", "st_investments"):
        if not _by_end(f, c):
            stamps.append(f"{c}_not_filed_taken_as_0")                    # N14
    # ruling 21: tangible capital, the return capped at 100%
    tangible = eq[prev] + debt_prev - cash[prev] - _by_end(f, "st_investments").get(prev, 0.0) - gw.get(prev, 0.0) - ia.get(prev, 0.0)
    ronic0 = (x0 + (interest or 0.0) * (1 - tau)) / tangible if tangible > 0 else float("inf")
    if not ronic0 > 0:
        raise DeskRefusal("ronic_not_positive", f"RONIC_0 = {ronic0:.6g}")
    if ronic0 > RONIC0_CAP:
        ronic0 = RONIC0_CAP
        stamps.append("ronic0_capped_at_100pct" if tangible > 0 else "tangible_capital_not_positive_ronic0_capped")
    if not (market_cap and market_cap > 0):
        raise DeskRefusal("market_cap_unavailable", "delta needs the market value of equity")
    net_debt = max(0.0, debt0 - c_l)                                       # N10: net of cash and short-term investments
    delta_market = net_debt / (net_debt + market_cap)                     # O5's market weight, kept as a diagnostic
    if e0 not in eq:
        raise DeskRefusal("input_missing", f"book equity for {e0}")
    # B12 (b12_leverage.json): the book ratio new capital is funded at; B12b bounds (OPINION_B12b_fable.md): capped at DELTA_CAP, and a
    # negative book equity is valued at the cap, stamped, not refused
    if net_debt <= 0:
        delta = 0.0
    elif eq[e0] <= 0:
        delta = DELTA_CAP
        stamps.append("book_equity_negative_delta_at_cap")
    else:
        delta = net_debt / (net_debt + eq[e0])
        if delta > DELTA_CAP:
            delta = DELTA_CAP
            stamps.append("delta_book_capped")
    if how0 in ("DebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"):
        stamps.append("debt_includes_finance_leases")
    if delta > 0:
        stamps.append("leverage_book_ratio_assumed")                      # B12: debt grows with the business at its book ratio
    shares = _by_end(f, "diluted_shares").get(e0)
    if not (shares and shares > 0):
        raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}")
    eps = _by_end(f, "eps_diluted").get(e0)
    if eps:
        implied = ni[e0] / shares
        if abs(implied / eps - 1) > SHARES_TOL and abs(implied - eps) > EPS_ROUNDING:   # N15: EPS is filed to the cent
            raise DeskRefusal("shares_scale_unverified", f"NI / diluted shares {implied:.6g} against filed diluted EPS {eps:.6g}")
    else:
        stamps.append("shares_unreconciled_no_eps")
    stamps.append("shares_weighted_average_diluted")
    # ruling 4: the vintages D&A rule from filed PP&E (prior gross, gross, net, D&A_org of the base year); else pooled, stamped
    gross, net = _by_end(f, "ppe_gross"), _by_end(f, "ppe_net")
    da_org0 = da[e0] - (am.get(e0, 0.0) if da_tag[e0] not in DA_EXCLUDES_AMORTIZATION else 0.0)   # N8: always without amortization
    ppe = ({"gross_prior": gross[prev], "gross": gross[e0], "net": net[e0], "da_org_0": da_org0}
           if prev in gross and e0 in gross and e0 in net and gross[e0] > 0 and da_org0 > 0 else None)
    if ppe is None:
        stamps.append("da_vintages_no_gross_ppe")
    else:
        # N8: the vintages rule only within bounds: life in [5, 40], its year-5 D&A ratio (flat revenue, pooled capex) within +-50% of pooled
        life = round(ppe["gross_prior"] / ppe["da_org_0"])
        path, _ = desk.da_org_path(5, [rev[e0]] * 6, [c_ratio * rev[e0]] * 5, d_ratio, ppe)
        if not (VINTAGE_LIFE[0] <= life <= VINTAGE_LIFE[1] and abs(path[4] / rev[e0] / d_ratio - 1) <= VINTAGE_RATIO_TOL):
            ppe = None
            stamps.append(f"da_vintages_out_of_bounds(life {life})")
    return {"version": INPUTS_VERSION, "fy0": e0, "ppe": ppe, "revenue_hist": [rev[e] for e in ends], "R0": rev[e0], "x0": x0, "m0": x0 / rev[e0],
            "oi0": oi[e0], "k0": k0, "k0_interest": k0_int, "op_margin0": oi[e0] / rev[e0], "d_ratio": d_ratio, "c_ratio": c_ratio, "w": w, "tau": tau,
            "ronic0": ronic0, "delta": delta, "delta_market": delta_market, "kd": kd, "debt0": debt0, "debt_basis": how0, "shares": shares, "excess_cash": excess_cash,
            "cash_interest_pretax": i_pre, "bill_rate": bill_rate, "amort_schedule": amort_schedule, "amort_thereafter": amort_after,
            "p_ratio": 0.0, "rou_ratio": 0.0, "stamps": stamps,
            "da_rule": "vintages" if ppe else "pooled",
            "record": {"op_margin": {e: oi[e] / rev[e] for e in ends if e in oi}, "capex_ratio": capex_record,
                       "rev_growth_max": max(rev[ends[i]] / rev[ends[i - 1]] - 1 for i in range(1, len(ends)))}}


def bridge_x_margin(b, op_margins, revenues, amort=None):
    """Analyst operating margins (GAAP basis) to X margins: X_t = (op_t R_t + A_t - K_0 R_t / R_0)(1 - tau). The non-operating items
    (interest above all) scale with revenue, as debt does at a book ratio (B12, b12_leverage.json); `amort` the A_t of the same years
    (None: 0, as for the long run)."""
    if b.get("k0") is None:
        raise DeskRefusal("bridge_unavailable", "no bridge constant: operating income or pretax income for the base year is not filed")
    amort = amort or [0.0] * len(op_margins)
    k_int = b.get("k0_interest", 0.0)
    k_other = b["k0"] - k_int
    return [(m * r + a - k_int * r / b["R0"] - k_other) * (1 - b["tau"]) / r for m, r, a in zip(op_margins, revenues, amort)]


def base_financial(f):
    """The measured base for value_financial (O3). The driver is opening book equity: "revenue" R_t = book equity at the start of year t and
    the "margin" m_t = ROE on it, so E_t = R_t m_t and the route's E_t (1 - g_{t+1} / ROE_t) is earnings less the growth of book equity, the
    retained-equity identity. Needs >= MIN_POOL_YEARS fiscal-year equity balances, positive E_0 and opening equity, and diluted shares."""
    eq, ni = _by_end(f, "equity"), _by_end(f, "net_income")
    ends = sorted(eq)[-(POOL_YEARS + 1):]
    if len(ends) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(ends)} fiscal-year equity balances; at least {MIN_POOL_YEARS}")
    stale = {c: d for c, d in (f.get("_stale") or {}).items() if c in ("net_income", "equity")}
    if stale:
        raise DeskRefusal("facts_stale", f"{stale}")
    e0 = ends[-1]
    if e0 not in ni:
        raise DeskRefusal("input_missing", f"net_income for the latest fiscal year {e0}")
    opening = eq[ends[-2]]
    if not (ni[e0] > 0 and opening > 0):
        raise DeskRefusal("e0_not_positive", f"E_0 = {ni[e0]:.6g}, opening equity {opening:.6g}")
    shares = _by_end(f, "diluted_shares").get(e0)
    if not (shares and shares > 0):
        raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}")
    roe_hist = {ends[i]: ni[ends[i]] / eq[ends[i - 1]] for i in range(1, len(ends)) if ends[i] in ni and eq[ends[i - 1]] > 0}
    # R_0 = book equity at the start of the base year, R_1 = at its end (the start of year 1): E_1 = R_1 ROE_1
    return {"version": INPUTS_VERSION, "route": "financial", "fy0": e0, "R0": opening, "R1": eq[e0], "e0": ni[e0],
            "roe0": ni[e0] / opening, "book_hist": [eq[e] for e in ends], "shares": shares, "excess_cash": 0.0,
            "record": {"roe": roe_hist,                                  # WO_Q6: V3g on book growth, as rev_growth_max on the operating route
                       "book_growth_max": max(eq[ends[i]] / eq[ends[i - 1]] - 1 for i in range(1, len(ends)) if eq[ends[i - 1]] > 0)},
            "stamps": ["financial_driver_book_equity", "preferred_not_separated", "shares_weighted_average_diluted"]}
