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
KD_PLAUSIBLE = (0.0, 0.25)       # annotation only (the census flagged k_d outside it); nothing is gated
# The route rule's tests the fiscal-year rows cannot evaluate (no loan, deposit, repurchase or investments concept is held)
TESTS_NOT_EVALUATED = ("lending_book_ge_50pct_of_assets", "deposits_ge_50pct_of_liabilities", "repurchase_agreements_ge_20pct_of_assets",
                       "investments_ge_50pct_of_assets")
_REQUIRED_OPERATING = ("delta", "tau", "pooled")


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
          quote_currency=None, currency_source=None, valuation_date=None, pi=None, untagged=(), dc_tags=None, unit=1e9) -> dict[str, Any]:
    """{"d2": dict | None, "d2_provenance": dict, "d2_unavailable": [member names] | None} for one name at its base year.

    `rows` the fiscal-year rows (the record's view: consolidated net income and equity); `price` and `shares` the pack's price and diluted share
    count (the desk's default), in one quote currency; `statement_currency` / `quote_currency` the currencies of the filed statements and of the
    quote (None = not known: delta is then absent, stamped `delta_currency_unproven`); `pi` the common shareholders' share the pack applies to
    every level it hands the desk (the year-0 and PP&E levels are scaled by it; the pooled totals stay raw, only their ratios are read);
    `untagged` the record's untagged fields; `dc_tags` {year: debt_current tag}. Every level in `d2` (pooled totals, PP&E, amortization, year 0) is
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
    interest, isrc = tcr.non_lease_interest(row)
    source("kd", f"{isrc or 'no interest filed'} / non-lease gross debt (base year)")
    if isrc == "interest_expense":
        stamp("kd", "lease_interest_not_filed")
    if not debt_filed or not debt > 0:
        stamp("kd", "kd_debt_zero_or_unproven")
    elif interest is None:
        stamp("kd", "kd_interest_not_filed")
    elif interest < 0:
        stamp("kd", "kd_negative_interest_after_lease_interest")
    else:
        kd = interest / debt
        d2["kd"] = kd
        if not (KD_PLAUSIBLE[0] <= kd <= KD_PLAUSIBLE[1]):
            stamp("kd", "kd_outside_0_25pct")
    if "delta" in d2 and d2["delta"] > 0 and "kd" not in d2:
        unavailable.append("kd")

    # ---- pooled: five-year raw totals over the complete years
    window = list(range(L - POOLED_YEARS + 1, L + 1))
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

