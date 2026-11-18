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
from datetime import date, timedelta

from qwen_c.value import desk
from qwen_c.value.desk import DeskRefusal
from qwen_c.value.facts import (DA_EXCLUDES_AMORTIZATION, ITEM_SUBSTITUTES, PRETAX_DERIVED, PRETAX_FROM_NI, SUBSTITUTE_PREFIX, SUBSTITUTE_SCOPE_PREFIX,
                                  has_stamp, taxonomy_of)
from qwen_c.value.ix_figures import SHARES_STAMP, STAMP as IX_STAMP

INPUTS_VERSION = "m3q.inputs.v18"   # v18 2026-11-19 WO_UV3: diluted shares from class-of-stock members (proven against the member EPS by check_shares, no rescaling) where no other count resolves; every ix_read stamp of a figure the base uses reaches base["stamps"]; names that passed before are unchanged   # v17 2026-11-19 WO_UV2: senior-notes debt tags where no debt tag resolves (parts reconciled), cash interest also supplies the base year's interest where operating income is derived, an unclassified balance sheet gives working capital 0 for every family (flag working_capital_unclassified_balance_sheet), partnership units with per-unit EPS as the diluted count, a filed 0.0 preferred balance is a value and preferred dividends are taken as 0 where EPS x shares reconciles (financial route), derived-pretax and redeemable-NCI flags; names that passed before are unchanged   # v16 2026-11-19 WO_NC9c: base() takes real_estate (the decided method's real-estate family: an unclassified balance sheet gives working capital 0, a stale operating-income tag gives pretax plus interest, each stamped; False is byte-identical)   # v15 2026-11-18 WO_NC8: base() takes interest_override (the interest on borrowings stated from the filing text) where the tagged figure gives a cost of debt outside the band; stamped interest_from_filing_text, base["interest_from_filing"], the lease and financing-interest additions are not made for it, a kd_out_of_band refusal carries .figures   # v14 2026-11-18 WO_NC3: tax_rate's last rung is the statutory rate the company files for the base year (stamped tax_rate_statutory_fallback), base() carries it with a second rate (tax_fallback) and takes tau_override for the value at that rate   # v13 2026-11-18 WO_NC2: base["stamps"] also carry the substitute labels and scope stamps of equity, capex, D&A, current items and pretax income   # v12 2026-11-17 WO_NC1: labelled substitutes (period-end share count, cash interest paid) only where the exact figure is absent; base["substitutes"] only when one is used   # v11 2026-11-07 coverage A: check_shares accepts a diluted share count filed in thousands where the rescaled count reconciles with filed diluted EPS   # v10 2026-11-03 F_SPEC_valuation_menu v1.3 (F11): base["ytd"], the facts' year-to-date pair of year 1 (menu option ytd)   # v9 2026-11-03 F_SPEC_valuation_menu F6: tau = 0 where no income tax is filed; IFRS 16 lease liabilities in debt where lease interest is in the interest; kd with the financing interest outside nonoperating interest   # v8 2026-11-03 F_SPEC_valuation_menu §2.1, §6: record.rev_growth; stamps for zero and outside-band tax, kd unused at delta 0, OI from pretax plus interest, ADS share scale   # v7 2026-10-31 CROSS_CHECK_Q3 5/6 and Q3b N4/N5/N8: the financial base's data rules, common equity   # v6 2026-10-30 WO_Q6: base_financial record book_growth_max; v5 2026-10-30 B12b bounds: delta cap, negative equity at the cap, interest-only K_0 scaling   # v4 2026-10-30 B12: K_0 scales with revenue, delta at the book ratio   # v3 2026-10-30 CROSS_CHECK_Q2: net-debt delta, NCI bounds, vintages bounds, stamps
POOL_YEARS = 5
MIN_POOL_YEARS = 3
TAX_BAND = (0.0, 0.35)
PERSISTENT_SPREAD = 0.05
STATUTORY_UPLIFT = 0.055       # WO_NC3: the upper quartile of (measured rate - filed statutory rate) on 28 stored US filers, 2026-11-18: the second rate of a statutory fallback
TAX_DEPART = 0.05            # ruling 9: the latest in-band rate is used only within 5 points of the in-band median
KD_BAND = (0.01, 0.20)       # ruling 5 (the audited coverage rule)
SHARES_TOL = 0.05            # ruling 5: NI / diluted shares against filed diluted EPS
RONIC0_CAP = 1.0             # ruling 21 (the doctrine's cap)
EPS_ROUNDING = 0.006         # CROSS_CHECK_Q2 N15
NCI_MATERIAL, NCI_DOMINANT = 0.10, 0.25   # N9
VINTAGE_LIFE = (5, 40)       # N8
VINTAGE_RATIO_TOL = 0.5
DELTA_CAP = 0.75             # B12b (OPINION_B12b_fable.md): the book delta's ceiling
ZERO_TAX_TOL = 0.02          # F_SPEC §6 tax (a): net income within 2% of pretax income less NCI
NEAR_ZERO_TAX = 0.01         # F_SPEC v1.2: a measured median within 1 point of 0 is a zero rate, stamped
COVER_WINDOW_DAYS = 120      # WO_NC1: a cover-page share count counts for a year end only when dated within 120 days after it
DEBT_TOTAL_EXCLUDES_SHORT = {"LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"}
CURRENT_INCLUDES_SHORT = {"DebtCurrent", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"}
DEBT_INCLUDES_LEASES = {"DebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"}


def _by_end(f, concept):
    return {v["end"]: v["value"] for v in (f.get(concept) or {}).get("values", [])}


def check_shares(f, e0, numer, shares, stamps, what, strict=False, eps=None):
    """Ruling 5 / N15: the per-share scale of the filed diluted shares, proven against filed diluted EPS. Returns the shares to use.
    Coverage A 2026-11-07: a count filed in thousands (the XBRL scale slip measured on SWBI) is rescaled when the count times 1e3
    reconciles, stamped. Nothing else is accepted (a 1e6 slip is not measured on any filer, so it stays refused). Not accepted, measured 11-07: reconciling on the filed diluted numerator (an
    if-converted convertible would then count as shares and as debt, CHEF), and preferred dividends without a filed preferred balance
    (State Street files its preferred in equity untagged after 2013): both stay refused."""
    eps = _by_end(f, "eps_diluted").get(e0) if eps is None else eps          # WO_UV2: the per-unit EPS of a partnership is passed in
    if not eps:
        stamps.append("shares_unreconciled_no_eps")
        return shares
    ok = lambda x: _eps_ok(x, eps)
    for k in (1.0, 1e3):
        if ok(numer / (shares * k)):
            if k != 1.0:
                stamps.append(f"shares_filed_scale_x{k:.0e}_eps_reconciled")
            return shares * k
    if strict or "per_share_basis_unverified" not in stamps:              # strict (WO_NC1, a substitute count): the ADS allowance does not apply; F_SPEC §6: a 20-F/40-F filer (an ADS ratio) is valued
        raise DeskRefusal("shares_scale_unverified", f"{what} / diluted shares {numer / shares:.6g} against filed diluted EPS {eps:.6g}")
    stamps.append("shares_scale_unverified_ads")
    return shares


def _eps_ok(x, eps):
    """N15: net income per share `x` against filed diluted EPS `eps`: within SHARES_TOL, or within EPS_ROUNDING (EPS is filed to the cent)."""
    return abs(x / eps - 1) <= SHARES_TOL or abs(x - eps) <= EPS_ROUNDING


def _verified_shares(f, e0, numer, substitutes, stamps, what):
    """(shares, substituted) for `numer` at the base year `e0`, proven against filed diluted EPS (check_shares). WO_UV2: where no diluted
    weighted-average count is filed but the partnership's diluted unit count and its per-unit diluted EPS are, the units are the count, and
    they are proven against that per-unit EPS; units that do not reconcile are not used (shares_unavailable, as before). Otherwise as before."""
    lp, lp_eps = _by_end(f, "lp_units_diluted").get(e0), _by_end(f, "eps_lp_diluted").get(e0)
    if e0 not in _by_end(f, "diluted_shares") and lp is not None and lp > 0 and lp_eps:
        try:
            n = check_shares(f, e0, numer, lp, [], what, strict=True, eps=lp_eps)
        except DeskRefusal as e:
            if e.code != "shares_scale_unverified":
                raise
            raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}; the diluted partnership units are filed but do not reconcile with the filed per-unit EPS ({e})")
        stamps.append("shares_from_partnership_units_reconciled_with_per_unit_eps")
        return n, False
    try:
        shares, sub = _shares_or_substitute(f, e0, substitutes)
    except DeskRefusal as e:
        if e.code != "shares_unavailable":
            raise
        got = _ix_shares(f, e0, numer, stamps, what)                      # WO_UV3: only where the base would be refused for the count
        if got is None:
            raise
        return got, False
    return check_shares(f, e0, numer, shares, stamps, what, strict=sub), sub


def _ix_shares(f, e0, numer, stamps, what):
    """WO_UV3: the diluted count of the fiscal year `e0` from the class-of-stock members of the newest annual filing's inline XBRL (ix_figures.
    share_candidates), or None. Each candidate (one member, or the sum of members that file one EPS) is proven against ITS OWN filed diluted EPS
    with check_shares, strict, and is used only at the scale the tag states (a count that only reconciles after check_shares' thousands
    rescale is not used). Exactly one count may reconcile: none, or two different ones, and nothing is read."""
    ix = f.get("_ix_shares")
    if not ix or ix["end"] != e0:
        return None
    ok = {}
    for c in ix["candidates"]:
        try:
            n = check_shares(f, e0, numer, c["shares"], [], what, strict=True, eps=c["eps"])
        except DeskRefusal:
            continue
        if n == c["shares"]:
            ok[n] = c
    if len(ok) != 1:
        return None
    n, c = next(iter(ok.items()))
    stamps.append(f"{SHARES_STAMP}:{ix['accession']}:{'+'.join(m.split(':')[-1] for m in c['members'])}")
    stamps.append("shares_reconciled_with_class_eps")
    return n


def _eps_reconciles(f, e, numer):
    """WO_UV2: whether `numer` / the filed diluted shares of year `e` matches that year's filed diluted EPS (check_shares' reconciliation, counts in
    thousands included); False where either is not filed."""
    eps, shares = _by_end(f, "eps_diluted").get(e), _by_end(f, "diluted_shares").get(e)
    return bool(eps) and shares is not None and shares > 0 and any(_eps_ok(numer / (shares * k), eps) for k in (1.0, 1e3))


def shares_substitute(f, e0):
    """WO_NC1: (count, taxonomy, tag) of the period-end share count to stand in for an absent diluted weighted-average count for the base
    year `e0`, or None: the count filed for that year end (us-gaap CommonStockSharesOutstanding, ifrs-full NumberOfSharesOutstanding, in that
    order, as facts lists them), else the cover-page count (dei) dated within COVER_WINDOW_DAYS after the year end (the earliest such date)."""
    pe = _by_end(f, "shares_period_end").get(e0)             # facts takes the highest-priority tag per year end
    if pe is not None and pe > 0:
        return pe, taxonomy_of("shares_period_end", _tag(f, "shares_period_end", e0)), _tag(f, "shares_period_end", e0)
    lo, hi = date.fromisoformat(e0), date.fromisoformat(e0) + timedelta(days=COVER_WINDOW_DAYS)
    cover = sorted((v["end"], v["value"], v["tag"]) for v in (f.get("shares_cover") or {}).get("values", [])
                   if v["value"] > 0 and lo < date.fromisoformat(v["end"]) <= hi)
    return (cover[0][1], taxonomy_of("shares_cover", cover[0][2]), cover[0][2]) if cover else None


def interest_substitute(f, e0):
    """WO_NC1: (expense, taxonomy, tag) to stand in for a gross interest expense not filed for the base year `e0`, or None: cash interest
    paid, when positive. A net interest line is NOT taken (coordinator's audit 2026-11-17): it nets interest income, which the base
    already removes at the bill rate, and no name of the measured corpus needed it."""
    for v in (f.get("interest_paid") or {}).get("values", []):
        if v["end"] == e0 and v["value"] > 0:
            return v["value"], taxonomy_of("interest_paid", v["tag"]), v["tag"]
    return None


def _label(concept, tax, tag):
    return f"{SUBSTITUTE_PREFIX}{concept}:{tax}:{tag}"


def _shares_or_substitute(f, e0, substitutes):
    """(shares, substituted): the filed diluted weighted-average count for `e0`; where none is filed (None, not 0) a period-end count
    (WO_NC1), appended to `substitutes` and then reconciled strictly with filed diluted EPS, which a substitute needs: without a filed
    diluted EPS for the year it stays refused. Else shares_unavailable as before."""
    shares = _by_end(f, "diluted_shares").get(e0)
    if shares is None:
        sub = shares_substitute(f, e0)
        if sub is None:
            raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}")
        if _by_end(f, "eps_diluted").get(e0) is None:
            raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}; a period-end count ({sub[2]}) is filed but no diluted EPS to reconcile it")
        substitutes.append(_label("diluted_shares", sub[1], sub[2]))
        return sub[0], True
    if not shares > 0:
        raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}")
    return shares, False


def _tag(f, concept, end):
    return next((v["tag"] for v in (f.get(concept) or {}).get("values", []) if v["end"] == end), None)


def statutory_rate(f, e0):
    """WO_NC3: (rate, "<taxonomy>:<tag>") of the statutory tax rate the company files for the fiscal year end `e0` in its own rate
    reconciliation, when it lies in TAX_BAND; else None. A filed 0.0 is a rate."""
    for v in (f.get("statutory_tax_rate") or {}).get("values", []):
        if v["end"] == e0 and TAX_BAND[0] <= v["value"] <= TAX_BAND[1]:
            return v["value"], f"{taxonomy_of('statutory_tax_rate', v['tag'])}:{v['tag']}"
    return None


def tax_rate(f, e0=None):
    """V8: (tau, stamp). The in-band years (provision / pretax in [0, 0.35], positive pretax) of the last 8: with >= 3 of them, their median
    unless the latest year is in band and within 5 points of it (then the latest); with fewer, the latest if in band; else a persistent
    rate (>= 3 measured years, all >= 0, within 5 points): their median. F6: else, with no income-tax fact filed at all (the base year's
    pretax income derived by facts._derive), a zero rate. F_SPEC §6: else, with no provision filed for the base year `e0`
    and its filed net income within 2% of pretax income less NCI, a zero rate; else, with >= 3 measured years, zero when their median
    is within 1 point of 0 (v1.2), else their UNCLAMPED median when it lies in [0, 1); else (WO_NC3) the statutory rate the company files for
    `e0` when it lies in the band, stamped tax_rate_statutory_fallback (the last rung: every rung above comes first); else refused."""
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
    e0 = e0 if e0 is not None else max(pre, default=None)
    if any(v["end"] == e0 and has_stamp(v, PRETAX_FROM_NI) for v in (f.get("pretax_income") or {}).get("values", [])):
        return 0.0, "tax_zero_no_tax_filed"                                # F6: no income-tax fact of any kind is filed (facts._derive)
    ni, nci = _by_end(f, "net_income").get(e0), _by_end(f, "nci_income").get(e0, 0.0)
    if e0 in pre and e0 not in tax and ni is not None and abs(ni - (pre[e0] - nci)) <= ZERO_TAX_TOL * abs(pre[e0] - nci):
        return 0.0, "tax_zero_no_provision"
    if len(recent) >= 3 and abs(statistics.median(recent)) < NEAR_ZERO_TAX:   # F_SPEC v1.2: a shipper's ~0% median (INSW -0.06%)
        return 0.0, "tax_rate_median_near_zero"
    if len(recent) >= 3 and 0 <= statistics.median(recent) < 1:
        return statistics.median(recent), "tax_rate_median_outside_band"
    sr = statutory_rate(f, e0)
    if sr is not None:
        return sr[0], "tax_rate_statutory_fallback"
    raise DeskRefusal("tax_unavailable", f"no usable measured tax rate (latest {rates[-1][1] if rates else None}); no statutory rate in the band is filed for {e0}")


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


def _rounding_unit(values):
    """The largest power of ten that divides every non-zero figure: the precision the filing printed them at (1 when none is rounded)."""
    ints, unit = [abs(int(round(v))) for v in values if v], 1
    while ints and all(i % (unit * 10) == 0 for i in ints):
        unit *= 10
    return unit


def senior_debt(f, end):
    """WO_UV2: (debt at `end`, how) from the senior-notes tags, or (None, None). SeniorNotes is the total; SeniorLongTermNotes is its non-current part
    and SeniorNotesCurrent its current part (a current part not filed is none). The total is used only when it is filed beside its non-current
    part and the parts sum to it within the rounding of the filed figures (each printed figure is off by at most half the unit it is printed in,
    so the sum of n figures by at most n/2 units); otherwise nothing is read. A long-term line of credit, filed apart from the notes, is added."""
    tot, nc, cur = (_by_end(f, k).get(end) for k in ("debt_senior_total", "debt_senior_noncurrent", "debt_senior_current"))
    if tot is None or nc is None:
        return None, None
    figures = [tot, nc] + ([cur] if cur is not None else [])
    if abs(nc + (cur if cur is not None else 0.0) - tot) > len(figures) / 2 * _rounding_unit(figures):
        return None, None
    loc = _by_end(f, "line_of_credit_noncurrent").get(end)
    return tot + (loc if loc is not None else 0.0), "SeniorNotes" + ("+LongTermLineOfCredit" if loc is not None else "")


def base(f, *, market_cap, bill_rate, tau_override=None, interest_override=None, real_estate=False):
    """The measured base for value_operating. `market_cap` (USD, from the formation's price row) sets delta at market weights (O5);
    `bill_rate` (a fraction, or None) is the 3-month bill rate over the base fiscal year (the cash term). `tau_override` (WO_NC3):
    replaces the rate tax_rate returns in the base, RONIC and the NCI term, nothing else (the value at a statutory fallback's second rate).
    `interest_override` (WO_NC8, a number in the filing's currency): replaces the tagged interest expense of the base year where it is read, in the
    cost of debt, the interest scaled with revenue (k0_interest) and the interest added back in RONIC; the IFRS 16 lease and financing-interest
    additions are not made (the figure is the interest on borrowings alone). The band still applies. None: byte-identical to before.
    `real_estate` (WO_NC9c, the decided method's real-estate family only; False: byte-identical to before): two data rules that real-estate balance
    sheets and income statements fail structurally are replaced, each stamped. (1) No current assets and no current liabilities filed for the base
    year (an unclassified balance sheet): working capital is 0 (`nwc_not_classified_taken_as_0`); one of the two filed still refuses. (2) The
    operating-income tag is stale: operating income is pretax income plus interest expense for every year, as when the tag is never filed
    (`oi_from_pretax_plus_interest`, `operating_income_tag_stale_not_used`). Nothing else is relaxed.
    WO_UV2, every family: an unclassified balance sheet (no current assets and no current liabilities for the base year) gives working capital 0 also
    where total assets and total liabilities are filed for that year (`working_capital_unclassified_balance_sheet`); where operating income is derived
    and the base year has no gross interest expense, cash interest paid supplies it (as the labelled substitute below does); where no debt tag resolves
    and the filed interest would exceed cash even at the band's lowest rate, the senior-notes tags are read for both years (senior_debt)."""
    rev = _by_end(f, "revenue")
    ends = sorted(rev)[-POOL_YEARS:]
    if len(ends) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(ends)} fiscal years of revenue; at least {MIN_POOL_YEARS} are needed to pool")
    e0 = ends[-1]
    if any(not rev[e] > 0 for e in ends):
        raise DeskRefusal("revenue_not_positive", f"a pooled year has revenue <= 0: {[(e, rev[e]) for e in ends if not rev[e] > 0]}")
    stale = {c: d for c, d in (f.get("_stale") or {}).items() if c in ("net_income", "capex", "da", "revenue", "pretax_income", "operating_income")}
    oi_stale = real_estate and stale.pop("operating_income", None) is not None      # WO_NC9c: a stale operating-income tag is replaced below, not refused
    if stale:
        raise DeskRefusal("facts_stale", f"concepts end before the latest revenue year {e0}: {stale}")
    if f.get("_latest_annual_period") and f["_latest_annual_period"] > e0:
        raise DeskRefusal("base_year_not_latest_annual", f"the newest eligible annual report is for {f['_latest_annual_period']}, the facts end {e0}")
    marks = {x for c in ("revenue", *ITEM_SUBSTITUTES) for v in (f.get(c) or {}).get("values", []) for x in (v.get("stamp") or "").split(";")}
    stamps = ["rou_depreciation_not_separated", "leases_not_modeled"] + sorted(x for x in marks if x.startswith(SUBSTITUTE_SCOPE_PREFIX))     # WO_NC2
    substitutes = sorted(x for x in marks if x.startswith(SUBSTITUTE_PREFIX))
    stamps += _ix_marks(f, ends)                                           # WO_UV3: figures read from the filing's inline XBRL
    if real_estate:
        stamps.append("real_estate_base")                                    # WO_NC9c
    if any((v.get("form") or "").startswith(("20-F", "40-F")) for v in f["revenue"]["values"]):
        stamps.append("per_share_basis_unverified")                         # ruling 18: no ADS ratio is applied
    else:
        stamps.append("split_after_fy0_unchecked")                          # CROSS_CHECK_Q2 #18: split detection not built
    tau, s = tax_rate(f, e0)
    stamps.append(s)
    tax_fallback = None
    if s == "tax_rate_statutory_fallback":                                 # WO_NC3: the filed rate drives the value; a second rate rides beside it
        pre_all = _by_end(f, "pretax_income")
        n_pre = [pre_all[e] for e in ends if e in pre_all]                  # the pooled window's fiscal years with a filed pretax income
        tax_fallback = {"rate": tau, "rate_alt": tau + STATUTORY_UPLIFT, "source_tag": statutory_rate(f, e0)[1],
                        "positive_pretax_years": sum(x > 0 for x in n_pre), "pretax_years": len(n_pre)}
        stamps.append(f"tax_fallback_positive_pretax_years:{tax_fallback['positive_pretax_years']}_of_{tax_fallback['pretax_years']}")
    if tau_override is not None:
        tau = tau_override
    if any(has_stamp(v, PRETAX_DERIVED) for v in (f.get("pretax_income") or {}).get("values", [])):          # WO_UV2: derived or widened figures stay visible
        stamps.append(PRETAX_DERIVED)
    if any(v["end"] == e0 and has_stamp(v, "nci_income_includes_redeemable_nci") for v in (f.get("nci_income") or {}).get("values", [])):
        stamps.append("nci_income_includes_redeemable_nci")
    ni, da, cx, am, pt, oi = (_by_end(f, k) for k in ("net_income", "da", "capex", "amortization", "pretax_income", "operating_income"))
    if not oi or oi_stale:                                                 # F_SPEC §6: OperatingIncomeLoss not filed in any year (WO_NC9c: or, for real estate, stale)
        ie_all = _by_end(f, "interest_expense")
        oi = {e: pt[e] + ie_all[e] for e in pt if e in ie_all}
        stamps.append("oi_from_pretax_plus_interest")
        if oi_stale:
            stamps.append("operating_income_tag_stale_not_used")
        if e0 in pt and e0 not in ie_all:                                  # WO_UV2: no gross interest for the base year: cash interest paid, where the base would be refused
            sub = interest_substitute(f, e0)
            if sub is not None:
                oi[e0] = pt[e0] + sub[0]
                substitutes.append(_label("interest_expense", sub[1], sub[2]))
                stamps.append("oi_interest_from_cash_interest_paid")
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
    k0_int = (_by_end(f, "interest_expense").get(e0) or 0.0) if interest_override is None else interest_override                  # B12b: only interest scales with revenue (debt grows with it)
    stamps.append("bridge_constant_from_base_year")
    r_sum = sum(rev[e] for e in pool)
    da_tag = {v["end"]: v["tag"] for v in f["da"]["values"]}
    d_ratio = sum(da[e] - (am[e] if use_amort and da_tag[e] not in DA_EXCLUDES_AMORTIZATION else 0.0) for e in pool) / r_sum
    c_ratio = sum(cx[e] for e in pool) / r_sum
    capex_record = {e: cx[e] / rev[e] for e in pool}
    ac, lc, eq, ie, gw, ia = (_by_end(f, k) for k in ("assets_current", "liabilities_current", "equity", "interest_expense", "goodwill",
                                                       "intangibles"))
    ta, tl = _by_end(f, "assets_total"), _by_end(f, "liabilities_total")
    unclassified = e0 not in ac and e0 not in lc and (real_estate or (e0 in ta and e0 in tl))     # WO_NC9c: neither filed for the base year: an unclassified balance sheet (WO_UV2: every family, total assets and liabilities filed)
    if not (e0 in ac and e0 in lc) and not unclassified:
        raise DeskRefusal("input_missing", f"current assets and current liabilities for {e0}")
    debt0, how0 = debt_total(f, e0)
    if how0 and how0.startswith("LongTermDebt") and _tag(f, "debt_current", e0) == "LongTermDebtCurrent":
        stamps.append("debt_total_tag_ambiguous")                          # CROSS_CHECK_Q2 #27 (MTCH)
    prev = ends[-2]
    debt_prev, _ = debt_total(f, prev)
    interest = ie.get(e0) if interest_override is None else interest_override                              # WO_NC8
    if interest_override is not None:
        stamps.append("interest_from_filing_text")
    if debt0 is None:
        # F_SPEC §6: kd is unused when delta = 0 (desk.equity_ronic). With no debt tag, delta is 0 when even the most debt the filed
        # interest allows at the band's lowest rate (interest / KD_BAND[0]) is covered by cash and short-term investments
        if interest and interest / KD_BAND[0] > c_l:
            (s0, h0), (sp, _) = senior_debt(f, e0), senior_debt(f, prev)        # WO_UV2: only where the base would be refused
            if s0 is None or sp is None:
                raise DeskRefusal("debt_unavailable", f"interest expense {interest:.6g} is filed for {e0} but no debt tag resolves")
            debt0, how0, debt_prev = s0, h0, sp
            stamps.append("debt_from_senior_notes_tags_parts_reconciled")
        else:
            debt0, how0 = 0.0, "no_debt_filed"
            stamps += ["no_debt_filed"] + (["debt_unresolved_bounded_by_interest", "kd_unused_delta_zero"] if interest else [])
    if debt_prev is None:
        debt_prev = 0.0 if how0 == "no_debt_filed" else None
    if debt_prev is None:
        raise DeskRefusal("debt_unavailable", f"no debt tag resolves for the opening year {prev}")
    sub_interest = None
    if debt0 > 0 and not interest:
        sub_interest = interest_substitute(f, e0) if (e0 not in ie and debt0 > c_l) else None      # WO_NC1: only where the base would be refused
        if sub_interest is not None:
            interest, k0_int = sub_interest[0], sub_interest[0]
            if _label("interest_expense", sub_interest[1], sub_interest[2]) not in substitutes:
                substitutes.append(_label("interest_expense", sub_interest[1], sub_interest[2]))
        elif debt0 > c_l:
            raise DeskRefusal("debt_without_interest", f"debt {debt0:.6g} at {e0} with no filed interest expense")
        else:
            stamps.append("kd_unused_delta_zero")                         # F_SPEC §6: net debt <= 0, so delta = 0
    # F6: IFRS 16 puts the interest on lease liabilities in finance costs. Where the base year's filed lease interest lies inside the
    # interest read, the lease liabilities (both years) are debt, so kd, delta, the capital and the interest added back share one basis;
    # their current part leaves working capital as current debt does
    li, ll = _by_end(f, "lease_interest_ifrs16").get(e0), _by_end(f, "lease_liabilities_ifrs16")
    lease_cur = 0.0
    if (interest and sub_interest is None and li is not None and 0 < li <= interest and e0 in ll and prev in ll and how0 != "no_debt_filed"
            and how0 not in DEBT_INCLUDES_LEASES and interest_override is None):         # not for a substituted interest: whether it holds the lease interest is not filed
        debt0, debt_prev, how0 = debt0 + ll[e0], debt_prev + ll[prev], f"{how0}+lease_liabilities"
        stamps.append("debt_includes_ifrs16_lease_liabilities")
        if e0 in _by_end(f, "lease_liabilities_current_ifrs16"):
            lease_cur = _by_end(f, "lease_liabilities_current_ifrs16")[e0]
        else:
            stamps.append("current_lease_liabilities_not_separated")
    # F6: InterestExpenseNonoperating excludes, by its definition, the interest a financing arm reports inside operating expenses
    # (FinancingInterestExpense), while the debt tags carry that arm's debt: kd takes both interests (kd only; the bridge keeps the former)
    kd_interest = interest
    fin = _by_end(f, "financing_interest").get(e0)
    if interest and fin is not None and interest_override is None and _tag(f, "interest_expense", e0) == "InterestExpenseNonoperating":
        kd_interest = interest + fin
        stamps.append("kd_includes_financing_interest")
    kd = kd_interest / ((debt0 + debt_prev) / 2) if interest and debt0 + debt_prev > 0 else 0.0
    if interest and debt0 + debt_prev > 0 and not KD_BAND[0] <= kd <= KD_BAND[1]:
        refusal = DeskRefusal("kd_out_of_band", f"kd = interest / average debt = {kd:.4f}, outside {KD_BAND}" + (
            "; the interest stated from the filing text, in place of the tagged figure, is also outside" if interest_override is not None else ""))
        refusal.figures = {"fy0": e0, "tag": _tag(f, "interest_expense", e0), "interest": interest, "kd_interest": kd_interest, "debt0": debt0,     # WO_NC8: what the cloud read is shown
                           "debt_prev": debt_prev, "debt_basis": how0, "kd": kd}
        raise refusal
    cur_debt = _by_end(f, "debt_current").get(e0, 0.0) + (_by_end(f, "debt_short").get(e0, 0.0)
                                                           if _tag(f, "debt_current", e0) not in CURRENT_INCLUDES_SHORT else 0.0) + lease_cur
    if unclassified:
        nwc0 = 0.0
        stamps += ["nwc_not_classified_taken_as_0", "working_capital_unclassified_balance_sheet"]
    else:
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
    shares, shares_sub = _verified_shares(f, e0, ni[e0], substitutes, stamps, "NI")
    stamps.append("shares_period_end_not_weighted_average" if shares_sub else "shares_weighted_average_diluted")
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
            "p_ratio": 0.0, "rou_ratio": 0.0, "stamps": stamps + substitutes, **({"substitutes": substitutes} if substitutes else {}),
            **({"tax_fallback": tax_fallback} if tax_fallback else {}),
            **({"interest_from_filing": {"value": interest_override, "tagged_value": ie.get(e0), "kd_used": kd}} if interest_override is not None else {}),
            **({"real_estate": True} if real_estate else {}),
            "da_rule": "vintages" if ppe else "pooled",
            "ytd": _ytd(f, e0),
            "record": {"op_margin": {e: oi[e] / rev[e] for e in ends if e in oi}, "capex_ratio": capex_record,
                       "rev_growth_max": max(rev[ends[i]] / rev[ends[i - 1]] - 1 for i in range(1, len(ends))),
                       "rev_growth": {c[i]: rev[c[i]] / rev[c[i - 1]] - 1 for c in [_year_chain(ends)] for i in range(1, len(c))}}}  # F_SPEC §2.1


def _ix_marks(f, ends):
    """WO_UV3: the ix_read stamps (document, tag or member) of every figure the base uses, one per figure, sorted: the facts' values of the fiscal
    years `ends`. Where a pooled series (capex, D&A) holds both years read from the filing and years companyfacts filed under its own tag, that is
    stamped too (ix_series_mixed:<concept>:<years from companyfacts>_of_<years used>): the two may not cover the same lines, a flag and no gate."""
    marks = {x for c, d in f.items() if not c.startswith("_") for v in d["values"] if v["end"] in ends for x in (v.get("stamp") or "").split(";")
             if x.startswith(IX_STAMP + ":")}
    for c in ("capex", "da"):
        vals = [v for v in (f.get(c) or {}).get("values", []) if v["end"] in ends]
        read = [v for v in vals if any(x.startswith(IX_STAMP + ":") for x in (v.get("stamp") or "").split(";"))]
        if read and len(read) < len(vals):
            marks.add(f"ix_series_mixed:{c}:{len(vals) - len(read)}_of_{len(vals)}")
    return sorted(marks)


def _ytd(f, e0):
    """F11: the facts' year-to-date pair of year 1 when it is measured against this base year (else not available, with why)."""
    y = f.get("_ytd")
    if y is None:
        return {"rev_growth": None, "op_margin": None, "absent": "no year-to-date record in the facts", "op_margin_absent": None}
    if y.get("fy0") != e0:
        return dict(y, rev_growth=None, op_margin=None, absent=f"year-to-date record measured against {y.get('fy0')}, the base year is {e0}")
    return y


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


def _year_chain(ends):
    """The fiscal-year ends chained back from the latest, each 350-380 days before the next (a stray quarter or a changed year-end
    is skipped; the chain stops at a gap)."""
    from datetime import date
    if not ends:
        return []
    out = [ends[-1]]
    for e in reversed(ends[:-1]):
        gap = (date.fromisoformat(out[0]) - date.fromisoformat(e)).days
        if 350 <= gap <= 380:
            out.insert(0, e)
        elif gap > 380:
            break
    return out


def base_financial(f):
    """The measured base for value_financial (O3). The driver is opening common book equity: "revenue" R_t = common book equity at the
    start of year t and the "margin" m_t = ROE on it, so E_t = R_t m_t and Flow_t = E_t - (R_{t+1} - R_t), the retained-equity identity.
    Common means after preferred stock: its carrying value comes out of book, and its dividends out of net income (CROSS_CHECK_Q3 6).
    The operating base's data rules apply (CROSS_CHECK_Q3 5): staleness on the route's own series, the newest annual report, an
    unreconciled ProfitLoss refused, net income per diluted share reconciled with filed diluted EPS, and the per-share stamps."""
    eq_all, ni_all = _by_end(f, "equity"), _by_end(f, "net_income")
    carry, liq = _by_end(f, "preferred_equity"), _by_end(f, "preferred_liquidation")
    nic, pdiv = _by_end(f, "ni_common"), _by_end(f, "preferred_dividends")
    # Q3b N5: a preferred carried in APIC (filed PreferredStockValue 0) is taken at its liquidation preference, stamped. Par-valued
    # carrying, late tagging and redemption inside the record are not handled (Q3c-7, carried: no census name today)
    pref = {e: (carry[e] if carry.get(e, 0.0) > 0 else liq[e]) for e in set(carry) | set(liq)
            if carry.get(e, 0.0) > 0 or e in liq}
    at_liq = any(not carry.get(e, 0.0) > 0 and liq.get(e, 0.0) > 0 for e in pref)
    zero = {e for e in carry if carry[e] == 0.0 and e not in pref}          # WO_UV2: a balance filed as 0.0 is a value (carried at 0, no liquidation preference filed)
    ends = _year_chain(sorted(eq_all))[-(POOL_YEARS + 1):]               # Q3b N8: year-ends 350-380 days apart
    if len(ends) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(ends)} fiscal-year equity balances; at least {MIN_POOL_YEARS}")
    e0 = ends[-1]
    ni_last = max(ni_all, default=None)                       # a bank files no revenue concept, so facts._stale cannot see it
    if ni_last != e0:
        raise DeskRefusal("facts_stale", f"equity ends {e0}, net income ends {ni_last}")
    if f.get("_latest_annual_period") and f["_latest_annual_period"] > e0:
        raise DeskRefusal("base_year_not_latest_annual", f"the newest eligible annual report is for {f['_latest_annual_period']}, the facts end {e0}")
    for v in (f.get("net_income") or {}).get("values", []):
        if v["end"] in ends[1:] and v.get("stamp") == "profitloss_basis_unverified":           # Q3b N4: ends[0] is the opening balance
            raise DeskRefusal("profitloss_basis_unverified", f"ProfitLoss for {v['end']} reconciles with diluted EPS on neither basis")
    substitutes = []
    stamps = ["financial_driver_book_equity", "shares_weighted_average_diluted", "financial_classification_unverified"] + _ix_marks(f, ends)
    if any((v.get("form") or "").startswith(("20-F", "40-F")) for v in f["equity"]["values"]):
        stamps.append("per_share_basis_unverified")                         # ruling 18: no ADS ratio is applied
    else:
        stamps.append("split_after_fy0_unchecked")
    # preferred stock (CROSS_CHECK_Q3 6): filed in any year used, it must be filed in every one, with its dividends or income to common
    has_pref = any(pref.get(e, 0.0) > 0 for e in ends)
    first = None
    if has_pref:
        # years before the first filed preferred hold none (an issue in the record); a year missing after it is refused (Q3b b4: BFH)
        first = min(e for e in ends if e in pref)
        missing = []
        for e in (x for x in ends if x >= first and x not in pref and x not in zero):
            # WO_UV2: a year with no balance filed, right after a year whose balance was filed as 0.0, is 0 when that year's preferred dividends
            # are filed as 0 or its income to common equals net income (to the dollar)
            last = max((x for x in ends if x < e and (x in pref or x in zero)), default=None)
            if last in zero and ((e in pdiv and pdiv[e] == 0.0) or (e in nic and e in ni_all and abs(nic[e] - ni_all[e]) < 0.5)):
                zero.add(e)
                stamps.append(f"preferred_balance_not_filed_taken_as_0:{e}")
            else:
                missing.append(e)
        if missing:
            raise DeskRefusal("preferred_series_incomplete", f"preferred stock filed from {first}, not for {missing}")
        if first > ends[0]:
            stamps.append(f"preferred_first_filed:{first}")
        pref = {e: pref.get(e, 0.0) for e in ends}
        stamps.append("preferred_subtracted_at_liquidation_preference" if at_liq else "preferred_subtracted_at_carrying_value")
    eq = {e: eq_all[e] - (pref[e] if has_pref else 0.0) for e in ends}
    ni = {}
    for e in ends[1:]:
        if e not in ni_all:
            continue
        if not has_pref or (e < first and e not in nic and e not in pdiv):     # before the issue: no preferred, no dividends
            ni[e] = ni_all[e]
        elif e in nic:
            ni[e] = nic[e]
        elif e in pdiv:
            ni[e] = ni_all[e] - pdiv[e]
        elif _eps_reconciles(f, e, ni_all[e]):                                # WO_UV2: no dividends filed: none, where EPS x shares reconciles without them
            ni[e] = ni_all[e]
            stamps.append(f"preferred_dividends_taken_as_0_eps_times_shares_reconciles:{e}")
        else:
            raise DeskRefusal("preferred_dividends_unavailable", f"preferred stock is filed but neither income to common nor preferred dividends for {e}")
    if e0 not in ni:
        raise DeskRefusal("input_missing", f"net_income for the latest fiscal year {e0}")
    opening = eq[ends[-2]]
    if not (ni[e0] > 0 and opening > 0):
        raise DeskRefusal("e0_not_positive", f"E_0 = {ni[e0]:.6g}, opening common equity {opening:.6g}")
    shares, shares_sub = _verified_shares(f, e0, ni[e0], substitutes, stamps, "income to common")
    if shares_sub:
        stamps[stamps.index("shares_weighted_average_diluted")] = "shares_period_end_not_weighted_average"
    aoci = _by_end(f, "aoci").get(e0)
    if aoci is not None and eq_all[e0]:
        stamps.append(f"aoci_in_book_not_separated:{aoci / eq_all[e0]:+.3f}")   # CROSS_CHECK_Q3 11: its share of book
    roe_hist = {ends[i]: ni[ends[i]] / eq[ends[i - 1]] for i in range(1, len(ends)) if ends[i] in ni and eq[ends[i - 1]] > 0}
    growth = {ends[i]: eq[ends[i]] / eq[ends[i - 1]] - 1 for i in range(1, len(ends)) if eq[ends[i - 1]] > 0}
    # V3g bounds (CROSS_CHECK_Q3 2, 4): the highest growth net of issuance (growth above that year's ROE is new capital), the lowest as filed
    retained = [min(g, roe_hist[e]) for e, g in growth.items() if e in roe_hist]
    # R_0 = common book equity at the start of the base year, R_1 = at its end (the start of year 1): E_1 = R_1 ROE_1
    return {"version": INPUTS_VERSION, "route": "financial", "fy0": e0, "R0": opening, "R1": eq[e0], "e0": ni[e0],
            "roe0": ni[e0] / opening, "book_hist": [eq[e] for e in ends], "shares": shares, "excess_cash": 0.0,
            "record": {"roe": roe_hist, "book_growth": growth, "common_equity": eq, "income_to_common": ni,
                       "preferred": {e: (pref[e] if has_pref else 0.0) for e in ends}, "book_growth_max": max(retained) if retained else None,
                       "book_growth_min": min(growth.values()) if growth else None},
            "stamps": stamps + substitutes, **({"substitutes": substitutes} if substitutes else {})}
