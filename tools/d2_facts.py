"""Design D2, port part (b): the pack facts that produce the `d2` long-run members of `unbundled_dcf(d2=...)` from filed data.

PLAN_terminal_reinvestment.md section 3a (with its amendment), O3, O5, O8; REPORT_census_1a_addendum.md sections 1 and 2; BRIEF_D2b2_pack_facts.md.
The members are named in one place, `consensus_reference` ("THE d2 MEMBERS"); `financial_model_tool._d2_prepare` validates them. This module only
MEASURES them, from the fiscal-year rows of the fundamentals history, and never changes what the model reads: the result rides in the facts
(`d2`, `d2_provenance`, `d2_unavailable`: SIDECAR_ONLY) and the desk reads it only when its context sets `d2_enabled`.

Rules held throughout:
  * 0.0 is a value: every test is `is None`, never `or`.
  * Nothing is filled silently: a member that cannot be measured is absent and named (`d2_unavailable` for a required one), and every
    departure from the plain filed value is a stamp in the member's provenance.
  * The route (family) is measured from the filed record; where the rule needs a field the history does not hold, the answer is "operating"
    and the stamp `family_route_unresolved`.
  * Nothing here imports a sibling repository or a scratch script (the census scripts are the reference for the measurement, not a dependency).
"""
from __future__ import annotations

from typing import Any

import throughcycle_record as tcr

POOLED_YEARS = 5                 # the base year and the 4 before it
INSURANCE_RESERVE_SHARE = 0.10   # the census addendum's route rule, section 1
FUNDING_SHARE = 0.50
KD_PLAUSIBLE = (0.01, 0.20)      # D2b3 (b): a kd outside it is a measurement failure (the member is unavailable), not a gate on the sample
VENDOR_AGREE = (0.7, 1.3)        # D2b3 (a): a rung-sourced capex_d2 / debt_d2_total must agree with the vendor within this ratio
# The route rule's tests the fiscal-year rows cannot evaluate (no loan, deposit, repurchase or investments concept is held)
TESTS_NOT_EVALUATED = ("lending_book_ge_50pct_of_assets", "deposits_ge_50pct_of_liabilities", "repurchase_agreements_ge_20pct_of_assets",
                       "investments_ge_50pct_of_assets")
_REQUIRED_OPERATING = ("delta", "tau", "pooled")
# D2b3 (BRIEF_D2b3_coverage.md, Part R). The class of a capex_d2 rung, read from the winning tag in the provenance (the screener's Part S names the tag
# of the rung that filed; a '+'-joined composite is a component sum). A tag not listed here is carried verbatim with no class.
CAPEX_CLASS_BY_TAG = (
    ("PaymentsForProceedsFromProductiveAssets", "net_of_proceeds"),
    ("PaymentsForConstructionInProcess", "construction_in_process"),
    ("PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets", "includes_intangibles"),
    ("PaymentsToAcquireOtherPropertyPlantAndEquipment", "other_ppe_partial_risk"),
)
REAL_ESTATE_TAGS = ("PaymentsToAcquireRealEstate", "PaymentsToDevelopRealEstateAssets", "PaymentsForCapitalImprovements", "PaymentsToAcquireLand")
NONOPERATING_INTEREST_TAG = "InterestExpenseNonoperating"   # the one interest_on_borrowings rung that still carries lease interest
DEBT_FREE_LEASE_MARGIN = 1.10                                # fix 4: vendor Total_Debt <= 1.10 x filed lease liabilities reads as leases only


def capex_class(cell):
    """The class markers of one year's capex_d2 cell {"tag", "state"}: ["from_capex"] / ["component_sum", "real_estate_components"] / ["net_of_proceeds"] / ..."""
    if not cell:
        return []
    tag, state = cell.get("tag") or "", cell.get("state") or ""
    out = []
    if state in ("from_capex", "component_sum"):
        out.append(state)
    if state == "s" and "component_sum" not in out:
        out.append("component_sum")
    if "+" in tag or any(t in tag for t in REAL_ESTATE_TAGS):
        if "component_sum" not in out:
            out.append("component_sum")
        if any(t in tag for t in REAL_ESTATE_TAGS):
            out.append("real_estate_components")
    for needle, marker in CAPEX_CLASS_BY_TAG:
        if needle in tag:
            out.append(marker)
    return out


def kd_interest(row, ob_tag=None):
    """(interest, source) for kd. interest_on_borrowings when filed, else interest_expense. Lease interest is subtracted when the source is
    interest_expense or the Nonoperating rung of interest_on_borrowings (the winning tag, from provenance); never from an IFRS borrowings rung.
    A null lease interest counts 0. 0.0 is a value. Sources: interest_on_borrowings:<tag>, interest_on_borrowings:<tag>_less_lease_interest,
    interest_expense, interest_expense_less_lease_interest; (None, None) when neither interest is filed."""
    ob, li = _n(row.get("interest_on_borrowings")), _n(row.get("lease_interest"))
    if ob is not None:
        label = "interest_on_borrowings:" + (ob_tag or "tag_unknown")
        if ob_tag is not None and NONOPERATING_INTEREST_TAG in ob_tag and li is not None:
            return ob - li, label + "_less_lease_interest"
        return ob, label
    ie = _n(row.get("interest_expense"))
    if ie is None:
        return None, None
    return (ie, "interest_expense") if li is None else (ie - li, "interest_expense_less_lease_interest")


def debt_free_inference(rws, window, base_row, vendor_total_debt):
    """Fix 4. (zero_ok, evidence): True only when no debt tag is filed in any window year (the existing ladder's four components and
    debt_d2_total all null in every year) AND the vendor Total_Debt is 0 or at most 1.10 x the base year's filed lease liabilities
    (finance_lease_liability + operating_lease_liability, a null one counting 0). Never True without that test."""
    ladder = ("debt_lt_noncurrent", "lt_debt", "debt_current", "short_term_borrowings_separate", "debt_d2_total")
    for y in window:
        r = rws.get(y)
        if r is not None and any(_n(r.get(f)) is not None for f in ladder):
            return False, {"reason": "a debt tag is filed in a window year", "year": y}
    vtd = _n(vendor_total_debt)
    if vtd is None:
        return False, {"reason": "vendor Total_Debt not available"}
    leases = sum(v for v in (_n(base_row.get("finance_lease_liability")), _n(base_row.get("operating_lease_liability"))) if v is not None)
    ok = vtd == 0 or vtd <= DEBT_FREE_LEASE_MARGIN * leases
    return ok, {"vendor_total_debt": vtd, "filed_lease_liabilities": leases, "reason": "vendor debt is zero or within 1.10x the filed leases" if ok
                else "vendor debt exceeds 1.10x the filed leases"}


def _n(v):
    return tcr._num(v)


def _sic(sic):
    try:
        return int(str(sic).strip())
    except (TypeError, ValueError):
        return None


def gross_debt(row, dc_tag=None):
    """(debt, filed, lt_filed): the non-lease gross debt exactly as `throughcycle_record.invested_capital` counts it (debt_lt_noncurrent else
    lt_debt, plus `short_term_debt`; a null component counts 0, leases excluded). `filed` is False when no debt component is filed at all."""
    lt = _n(row.get("debt_lt_noncurrent"))
    if lt is None:
        lt = _n(row.get("lt_debt"))
    filed = lt is not None or _n(row.get("debt_current")) is not None or _n(row.get("short_term_borrowings_separate")) is not None
    return (0.0 if lt is None else lt) + tcr.short_term_debt(row, dc_tag), filed, lt is not None


def route(sic, row, sector, financial_sectors, debt):
    """The desk routing table (census addendum section 1) on what the fiscal-year row holds. {"family": "financial" | "operating", "evidence",
    "stamps", "tests_not_evaluated"}.
    Financial when: insurance reserves >= 10% of total assets; a broker-dealer SIC (6211); a credit SIC (6020-6199) whose non-lease borrowings
    fund >= 50% of liabilities. The lending-book, deposits, repurchase-agreement and investments tests need concepts the row does not hold: they
    are not evaluated, and a name the evaluated tests leave as operating while its SIC (6000-6799) or sector says financial or real estate -
    or which has no SIC - is operating with `family_route_unresolved`. Real-estate SICs (6500-6599, 6798) stay operating (D2 with delta and no s,
    O6/O8) unless a test above confirms otherwise."""
    code = _sic(sic)
    stamps, ta, tl, ir = [], _n(row.get("total_assets")), _n(row.get("total_liabilities")), _n(row.get("insurance_reserves"))
    if code is None:
        stamps.append("sic_missing")
    if ta is not None and ta > 0 and ir is not None and ir / ta >= INSURANCE_RESERVE_SHARE:
        return {"family": "financial", "evidence": f"insurance reserves are {ir / ta:.1%} of total assets (>= 10%)", "stamps": stamps,
                "tests_not_evaluated": list(TESTS_NOT_EVALUATED)}
    if code == 6211:
        return {"family": "financial", "evidence": "broker-dealer SIC 6211", "stamps": stamps, "tests_not_evaluated": list(TESTS_NOT_EVALUATED)}
    funding = (debt / tl) if (debt is not None and tl is not None and tl > 0) else None
    if code is not None and 6020 <= code <= 6199 and funding is not None and funding >= FUNDING_SHARE:
        return {"family": "financial", "evidence": f"credit SIC {code}, non-lease borrowings {funding:.0%} of liabilities", "stamps": stamps,
                "tests_not_evaluated": list(TESTS_NOT_EVALUATED)}
    if code is None or 6000 <= code <= 6799 or sector in financial_sectors:
        stamps.append("family_route_unresolved")
    ev = f"SIC {code}: no evaluated test confirms a financial route" if code is not None else "no SIC: no evaluated test confirms a financial route"
    if code is not None and (6500 <= code <= 6599 or code == 6798):
        ev += "; real-estate treatment (D2 with delta, no s)"
    return {"family": "operating", "evidence": ev, "stamps": stamps, "tests_not_evaluated": list(TESTS_NOT_EVALUATED)}


def _scale(v, pi, unit=1.0):
    """A level in the desk's unit: scaled by pi (the common shareholders' share) and divided by `unit` (1e9: the desk's bridge works in $B)."""
    return None if v is None else (v * pi if pi is not None else v) / unit


def build(rows, base_year, *, sic=None, sector=None, financial_sectors=(), price=None, shares=None, shares_source=None, statement_currency=None,
          quote_currency=None, currency_source=None, valuation_date=None, pi=None, untagged=(), dc_tags=None, unit=1e9, field_prov=None,
          vendor_total_debt=None, vendor_capex=None, vendor_capex_why=None) -> dict[str, Any]:
    """{"d2": dict | None, "d2_provenance": dict, "d2_unavailable": [member names] | None} for one name at its base year.

    `rows` the fiscal-year rows (the record's view: consolidated net income and equity); `price` and `shares` the pack's price and diluted share
    count (the desk's default), in one quote currency; `statement_currency` / `quote_currency` the currencies of the filed statements and of the
    quote (None = not known: delta is then absent, stamped `delta_currency_unproven`); `pi` the common shareholders' share the pack applies to
    every level it hands the desk (the year-0 and PP&E levels are scaled by it; the pooled totals stay raw, only their ratios are read);
    `untagged` the record's untagged fields; `dc_tags` {year: debt_current tag}; `field_prov` {field: {year: {"tag", "state"}}} the winning tag and state of capex_d2, debt_d2_total and
    interest_on_borrowings (D2b3); `vendor_total_debt` the vendor file's Total_Debt (fix 4 and the debt rung check); `vendor_capex` the vendor's Capital_Expenditure when the pack's
    vendor-capex gate (`_vendor_capex_usable`) passes, else None (`vendor_capex_why` says why). Every level in `d2` (pooled totals, PP&E, amortization, year 0) is
    in units of `unit` currency (default 1e9: $B, the unit of the bridge's revenue); ratios and rates are unit-free."""
    rws = tcr.normalise_rows(rows)
    untagged = frozenset(untagged or ())
    tags = {int(y): t for y, t in (dc_tags or {}).items()}
    prov: dict[str, Any] = {"base_year": None, "members": {}, "stamps": [], "route": None, "optional_absent": [], "pooled_basis": "raw consolidated totals; only their ratios are read"}
    members = prov["members"]

    def stamp(member, s):
        members.setdefault(member, {"source": None, "stamps": []})["stamps"].append(s)
        if s not in prov["stamps"]:
            prov["stamps"].append(s)

    def source(member, src):
        members.setdefault(member, {"source": None, "stamps": []})["source"] = src

    def fail(unavailable):
        return {"d2": None, "d2_provenance": prov, "d2_unavailable": list(unavailable)}

    L = base_year if base_year is not None else (max(rws) if rws else None)
    if L is None or L not in rws:
        prov["stamps"].append("d2_no_base_year_row")
        return fail(_REQUIRED_OPERATING)
    prov["base_year"] = int(L)
    row = rws[L]
    if L < 2025:
        stamp("base_year", "base_year_before_2025")
    if pi is None:
        stamp("year0", "pi_not_measured_levels_unscaled")
    # ---- family
    debt, debt_filed, lt_filed = gross_debt(row, tags.get(L))
    fprov = field_prov or {}
    # D2b3 item 3: when the existing ladder carries no long-term debt (debt_lt_noncurrent and lt_debt both unfiled), the non-lease total of the
    # screener's debt_d2_total is the debt for delta, kd and year0.invested_capital (stamped debt_from_d2_total). The ladder, when it resolves,
    # is unchanged, and so are throughcycle_record.invested_capital and r_tc.
    debt_from_d2 = False
    d2t = _n(row.get("debt_d2_total"))
    d2t_state = ((fprov.get("debt_d2_total") or {}).get(L) or {}).get("state")
    debt_rung_stamps: list[str] = []
    if not lt_filed and d2t is not None:
        verdict, ratio = "unverified", None
        if d2t_state in ("from_ladder",):
            verdict = "ladder"
        else:
            vtd = _n(vendor_total_debt) if (statement_currency and statement_currency == quote_currency) else None
            leases = sum(v for v in (_n(row.get("finance_lease_liability")), _n(row.get("operating_lease_liability"))) if v is not None)
            if vtd is not None and vtd - leases > 0:
                ratio = d2t / (vtd - leases)
                verdict = "agrees" if VENDOR_AGREE[0] <= ratio <= VENDOR_AGREE[1] else "disagrees"
                prov["debt_d2_vendor"] = {"debt_d2_total": d2t, "vendor_total_debt": vtd, "filed_lease_liabilities": leases, "ratio": ratio}
        if verdict == "disagrees":
            debt_rung_stamps.append("debt_d2_vendor_disagrees")
            prov["debt_d2_vendor_ratio"] = ratio
            d2t = None                  # unusable: the member is unavailable (delta_debt_not_filed below), and the fix-4 test sees a filed tag
        elif verdict == "agrees":
            debt_rung_stamps.append("debt_d2_total_rung_vendor_agrees")
        elif verdict == "unverified":
            debt_rung_stamps.append("debt_d2_total_rung_unverified")
    if not lt_filed and d2t is not None:
        debt, debt_filed, lt_filed, debt_from_d2 = d2t, True, True, True
    # fix 4: no debt tag in any window year, and the vendor total is leases only (or zero): non-lease debt is 0
    debt_zero_inferred = False
    if not debt_filed:
        zero_ok, zero_ev = debt_free_inference(rws, list(range(L - POOLED_YEARS + 1, L + 1)), row,
                                               vendor_total_debt if (statement_currency and statement_currency == quote_currency) else None)
        prov["debt_free_test"] = zero_ev
        if zero_ok:
            debt, debt_filed, lt_filed, debt_zero_inferred = 0.0, True, True, True
    rt = route(sic, row, sector, financial_sectors, debt if debt_filed else None)
    prov["route"] = {"sic": sic, "sector": sector, "evidence": rt["evidence"], "tests_not_evaluated": rt["tests_not_evaluated"]}
    source("family", "route rule of REPORT_census_1a_addendum.md section 1 on the fiscal-year row")
    for s in rt["stamps"]:
        stamp("family", s)
    if valuation_date is not None:
        prov["valuation_date"] = str(valuation_date)
    if rt["family"] == "financial":
        stamp("delta", "delta_not_applied_financial_route")
        d2 = {"family": "financial"}
        if valuation_date is not None:
            d2["valuation_date"] = str(valuation_date)
        return {"d2": d2, "d2_provenance": prov, "d2_unavailable": None}
    d2: dict[str, Any] = {"family": "operating"}
    unavailable: list[str] = []

    # ---- tau
    pretax, tax = _n(row.get("pretax_income")), _n(row.get("tax_provision"))
    d2["tau"] = tcr.tax_rate(row)
    source("tau", "throughcycle_record.tax_rate, base year")
    if pretax is None or tax is None or pretax == 0:
        stamp("tau", "tax_rate_default_21pct")

    # ---- delta: non-lease debt net of cash and short-term investments, floored at 0, over (that + market cap)
    source("delta", "non-lease debt (invested_capital's debt) less cash and short-term investments, floored at 0, over itself plus price x diluted shares")
    delta_ok = True
    if not (statement_currency and quote_currency and statement_currency == quote_currency):
        stamp("delta", "delta_currency_unproven")
        prov["members"]["delta"]["currency"] = {"statements": statement_currency, "quote": quote_currency, "evidence": currency_source}
        delta_ok = False
    mcap = price * shares if (_n(price) is not None and _n(shares) is not None and price > 0 and shares > 0) else None
    if mcap is None:
        stamp("delta", "delta_market_cap_unavailable")
        delta_ok = False
    cash, sti = _n(row.get("cash")), _n(row.get("st_investments"))
    if cash is None:
        stamp("delta", "delta_cash_not_filed")
        delta_ok = False
    for s_ in debt_rung_stamps:
        stamp("delta", s_)
    if debt_from_d2:
        stamp("delta", "debt_from_d2_total")
    if debt_zero_inferred:
        stamp("delta", "debt_zero_inferred_leases_only")
    if not debt_filed:
        stamp("delta", "delta_debt_not_filed")          # no debt component is filed at all: unproven, never read as zero debt
        delta_ok = False
    elif not lt_filed:
        stamp("delta", "debt_lt_noncurrent_and_lt_debt_not_filed_counted_zero")
    if delta_ok:
        nd = max(0.0, debt - cash - (0.0 if sti is None else sti))
        d2["delta"] = nd / (nd + mcap)
        members["delta"]["inputs"] = {"non_lease_debt": debt, "cash": cash, "st_investments": sti, "net_debt_floored": nd, "market_cap": mcap,
                                      "shares_source": shares_source}
        if nd == 0.0:
            stamp("delta", "net_cash_delta_zero")
    else:
        unavailable.append("delta")

    # ---- kd: non-lease interest over non-lease gross debt; absent when debt is 0 or unproven, never defaulted
    ob_tag = ((fprov.get("interest_on_borrowings") or {}).get(L) or {}).get("tag")
    interest, isrc = kd_interest(row, ob_tag)
    source("kd", f"{isrc or 'no interest filed'} / non-lease gross debt (base year)")
    if isrc == "interest_expense":
        stamp("kd", "lease_interest_not_filed")
    if isrc is not None and isrc.startswith("interest_on_borrowings") and ob_tag is None:
        stamp("kd", "interest_on_borrowings_tag_unknown")
    if debt_from_d2:
        stamp("kd", "debt_from_d2_total")
        for s_ in debt_rung_stamps:
            stamp("kd", s_)
    if debt_zero_inferred:
        stamp("kd", "debt_zero_inferred_leases_only")
    if not debt_filed or not debt > 0:
        stamp("kd", "kd_debt_zero_or_unproven")
    elif interest is None:
        stamp("kd", "kd_interest_not_filed")
    elif interest < 0:
        stamp("kd", "kd_negative_interest_after_lease_interest")
    else:
        kd = interest / debt
        if not (KD_PLAUSIBLE[0] <= kd <= KD_PLAUSIBLE[1]):
            stamp("kd", "kd_outside_plausible_range")      # a measurement failure, not a gate on the sample: the member is unavailable, the value kept here
            prov["kd_outside_plausible_range"] = {"kd": kd, "interest": interest, "debt": debt, "range": list(KD_PLAUSIBLE)}
        else:
            d2["kd"] = kd
    if "delta" in d2 and d2["delta"] > 0 and "kd" not in d2:
        unavailable.append("kd")

    # ---- pooled: five-year raw totals over the complete years
    window = list(range(L - POOLED_YEARS + 1, L + 1))
    # D2b3 (a): a capex_d2 that is not simply the filed capex is checked against the vendor's Capital_Expenditure (base year, abs) before any year uses it
    cd2_ok, capex_rung_stamp = True, None
    cd2_base = _n(row.get("capex_d2"))
    if cd2_base is not None and ((fprov.get("capex_d2") or {}).get(L) or {}).get("state") != "from_capex":
        vc = _n(vendor_capex)
        if vc is None or vc == 0:
            capex_rung_stamp = "capex_d2_rung_unverified"
            prov["capex_d2_vendor"] = {"capex_d2": cd2_base, "vendor_capex": vc, "why": vendor_capex_why or "vendor Capital_Expenditure absent or zero"}
        else:
            ratio = abs(cd2_base) / abs(vc)
            prov["capex_d2_vendor"] = {"capex_d2": cd2_base, "vendor_capex": vc, "ratio": ratio}
            if VENDOR_AGREE[0] <= ratio <= VENDOR_AGREE[1]:
                capex_rung_stamp = "capex_d2_rung_vendor_agrees"
            else:
                capex_rung_stamp, cd2_ok = "capex_d2_vendor_disagrees", False
    if capex_rung_stamp:
        stamp("pooled", capex_rung_stamp)
        stamp("year0", capex_rung_stamp)
    optional = ("rou_depreciation", "amortization_intangibles", "lease_principal")
    present_any = {f: any(y in rws and _n(rws[y].get(f)) is not None for y in window) for f in optional}
    if "amortization_intangibles" in untagged:
        present_any["amortization_intangibles"] = False
    tot = {"revenue": 0.0, "capex": 0.0, "da_org": 0.0, "lease_principal": 0.0, "rou_dep": 0.0}
    used = 0
    for y in window:
        r = rws.get(y)
        if r is None:
            stamp("pooled", f"pooled_year_{y}_excluded:no_row")
            continue
        vals = {f: _n(r.get(f)) for f in ("revenue", "capex", "da") + optional}
        if cd2_ok and vals["capex"] is None and _n(r.get("capex_d2")) is not None:
            vals["capex"] = _n(r.get("capex_d2"))
            cls = capex_class(((fprov.get("capex_d2") or {}).get(y)) or {})
            prov.setdefault("capex_d2", {})[str(y)] = {"classes": cls, **(((fprov.get("capex_d2") or {}).get(y)) or {})}
            stamp("pooled", f"capex_from_d2_year_{y}" + (":" + "+".join(cls) if cls else ""))
        missing = [f for f in ("revenue", "capex", "da") if vals[f] is None] + [f for f in optional if present_any[f] and vals[f] is None]
        if missing:
            stamp("pooled", f"pooled_year_{y}_excluded:" + "+".join(missing))
            continue
        tot["revenue"] += vals["revenue"]
        tot["capex"] += abs(vals["capex"])
        tot["da_org"] += vals["da"] - (vals["rou_depreciation"] if present_any["rou_depreciation"] else 0.0) \
            - (vals["amortization_intangibles"] if present_any["amortization_intangibles"] else 0.0)
        if present_any["lease_principal"]:
            tot["lease_principal"] += vals["lease_principal"]
        if present_any["rou_depreciation"]:
            tot["rou_dep"] += vals["rou_depreciation"]
        used += 1
    source("pooled", f"sums over FY{window[0]}-FY{window[-1]} of the years with revenue, capex and D&A (and every optional component filed elsewhere in the window); "
                     "D&A_org = D&A - ROU depreciation - acquired amortization, per year then summed")
    if used == 0:
        stamp("pooled", "pooled_no_complete_year")
        unavailable.append("pooled")
    else:
        pooled = {"revenue": tot["revenue"] / unit, "capex": tot["capex"] / unit, "da_org": tot["da_org"] / unit, "years": used}
        if present_any["lease_principal"]:
            pooled["lease_principal"] = tot["lease_principal"] / unit
        else:
            stamp("pooled", "lease_principal_not_filed")
        if present_any["rou_depreciation"]:
            pooled["rou_dep"] = tot["rou_dep"] / unit
        else:
            stamp("pooled", "rou_depreciation_not_filed")
        if not present_any["amortization_intangibles"]:
            stamp("pooled", "amortization_intangibles_not_filed_counted_zero")
        if not tot["revenue"] > 0:
            stamp("pooled", "rev_5yr_nonpositive")
        if not tot["da_org"] > 0:
            stamp("pooled", "da_org_pooled_nonpositive")
        d2["pooled"] = pooled
    if valuation_date is not None:
        d2["valuation_date"] = str(valuation_date)

    # ---- per-year D&A_org for the base year (ppe.da_org_0 and year0.da_org)
    def da_org_of(r):
        da = _n(r.get("da"))
        if da is None:
            return None
        rou, am = _n(r.get("rou_depreciation")), _n(r.get("amortization_intangibles"))
        if (present_any["rou_depreciation"] and rou is None) or (present_any["amortization_intangibles"] and am is None):
            return None
        return da - (rou if present_any["rou_depreciation"] else 0.0) - (am if present_any["amortization_intangibles"] else 0.0)

    da0 = da_org_of(row)
    # ---- ppe: the vintage inputs; absent when ppe_gross is not filed
    gp, g, nt = (_n(rws[L - 1].get("ppe_gross")) if (L - 1) in rws else None), _n(row.get("ppe_gross")), _n(row.get("ppe_net"))
    source("ppe", "ppe_gross (prior year and base year), ppe_net and D&A_org of the base year, scaled by pi")
    if g is None:
        stamp("ppe", "ppe_gross_not_filed")
    elif gp is None or nt is None or da0 is None:
        stamp("ppe", "ppe_inputs_incomplete:" + "+".join(n for n, v in (("gross_prior", gp), ("net", nt), ("da_org_0", da0)) if v is None))
    else:
        d2["ppe"] = {"gross_prior": _scale(gp, pi, unit), "gross": _scale(g, pi, unit), "net": _scale(nt, pi, unit), "da_org_0": _scale(da0, pi, unit)}
    if "ppe" not in d2:
        prov["optional_absent"].append("ppe")

    # ---- amortization: the filed five-year schedule, else the base year's A_0, else absent
    keys = [f"amortization_sched_y{i}" for i in range(1, 6)]
    vals5 = [_n(row.get(k)) for k in keys]
    th = _n(row.get("amortization_sched_thereafter"))
    a0 = None if "amortization_intangibles" in untagged else _n(row.get("amortization_intangibles"))
    source("amortization", "base-year amortization_sched_y1..y5 (all five) and amortization_sched_thereafter, else base-year amortization_intangibles")
    if all(v is not None for v in vals5):
        am = {"schedule": [_scale(v, pi, unit) for v in vals5]}
        if th is None:
            stamp("amortization", "amortization_thereafter_not_filed")       # absent: the desk reads it as 0
        else:
            am["thereafter"] = _scale(th, pi, unit)
        d2["amortization"] = am
    elif a0 is not None:
        if any(v is not None for v in vals5):
            stamp("amortization", "amortization_schedule_partial:" + "+".join(k[-2:] for k, v in zip(keys, vals5) if v is None))
        else:
            stamp("amortization", "amortization_schedule_not_filed")
        d2["amortization"] = {"a0": _scale(a0, pi, unit)}
    else:
        stamp("amortization", "amortization_not_filed")
        prov["optional_absent"].append("amortization")

    # ---- year0: the base-year figures for the Flow_0 identity and the explicit-years diagnostic (scaled by pi, as E_0 is)
    y0: dict[str, float] = {}
    source("year0", "base-year capex, D&A_org, change in NWC, lease principal, ROU depreciation, amortization and invested capital, scaled by pi")
    cx = _n(row.get("capex"))
    if cd2_ok and cx is None and _n(row.get("capex_d2")) is not None:
        cx = _n(row.get("capex_d2"))
        cls = capex_class(((fprov.get("capex_d2") or {}).get(L)) or {})
        prov.setdefault("capex_d2", {})[str(L)] = {"classes": cls, **(((fprov.get("capex_d2") or {}).get(L)) or {})}
        stamp("year0", "capex_from_d2" + (":" + "+".join(cls) if cls else ""))
    for name, v in (("capex", None if cx is None else abs(cx)), ("da_org", da0), ("lease_principal", _n(row.get("lease_principal"))),
                    ("rou_dep", _n(row.get("rou_depreciation"))), ("amortization", a0)):
        if v is None:
            stamp("year0", f"year0_{name}_not_available")
        else:
            y0[name] = _scale(v, pi, unit)
    nwc_l = tcr.net_working_capital(row, tags.get(L))
    nwc_p = tcr.net_working_capital(rws[L - 1], tags.get(L - 1)) if (L - 1) in rws else None
    if nwc_l is None or nwc_p is None:
        stamp("year0", "year0_dnwc_not_available")
    else:
        y0["dnwc"] = _scale(nwc_l - nwc_p, pi, unit)
    ic = tcr.invested_capital(row, untagged, tags.get(L))
    if ic is not None and debt_from_d2:
        # year0.invested_capital under D2 uses the same debt as delta: invested_capital counted the (unfiled) ladder as 0, so the total is added
        ic += debt - tcr.short_term_debt(row, tags.get(L))   # the ladder's short-term debt is already in ic; d2 total replaces the whole ladder
        stamp("year0", "debt_from_d2_total")
    if debt_zero_inferred:
        stamp("year0", "debt_zero_inferred_leases_only")
    if ic is None:
        stamp("year0", "year0_invested_capital_not_available")
    else:
        y0["invested_capital"] = _scale(ic, pi, unit)
    if y0:
        d2["year0"] = y0
    else:
        prov["optional_absent"].append("year0")
    # ---- reserves and reit: absent in this part (O8: diagnostics only); the desk stamps them unavailable
    source("reserves", "not built in this part (O8: diagnostics only)")
    source("reit", "not built in this part (O8: diagnostics only)")
    prov["optional_absent"] += ["reserves", "reit"]

    if unavailable:
        prov["stamps"].append("d2_unavailable:" + "+".join(unavailable))
        return {"d2": None, "d2_provenance": prov, "d2_unavailable": unavailable}
    return {"d2": d2, "d2_provenance": prov, "d2_unavailable": None}

