"""facts.py - point-in-time filed figures for the 3Q desk (SPEC_m3q_valuation.md §2, WO_Q4).

Source: SEC companyfacts (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json) read through sec_store, so the exact bytes are
pinned. companyfacts lists every filing's own reported value with its accession, so a value counts at time T only if its accession was
effective by T (packet.effective_at of the submissions acceptance). An accession missing from the submissions' recent list counts only
if its filing date is at least 2 calendar days before T's date, stamped `acceptance_by_filed_date`. A snapshot fetched after T is a
reconstruction of what was filed, stamped `snapshot_after_T`; it is not proof of what a reader had at T.

For each concept and fiscal-year end, the value of the LATEST eligible filing is used (a restatement filed before T is what was known
at T). Annual flows are full-year facts (fp FY, a 350-380 day duration) from 10-K, 10-K/A, 20-F, 20-F/A, 40-F, 40-F/A; balances are
instants at a fiscal-year end of the same forms. Nothing is defaulted: a missing concept is absent from the result with its reason.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from qwen_c import packet, sec_store

FACTS_VERSION = "m3q.facts.v6"   # v6 2026-11-03 F_SPEC_valuation_menu F6: derived series, each value stamped: pretax income where no income-tax fact is filed, IFRS diluted shares from basic plus the dilutive effect (EPS-reconciled), equity from the total less NCI; the cost-of-sales D&A line as the last D&A tag; IFRS 16 lease and financing-interest facts for inputs   # v5 2026-11-03 RR_Q7 3: IFRS net income (ProfitLoss, ordinary holders), NCI, diluted EPS, depreciation   # v4 2026-10-31 CROSS_CHECK_Q3b N5: preferred liquidation preference   # v3 2026-10-30 CROSS_CHECK_Q3 5, 6, 11: preferred stock, income to common, AOCI (financial route)   # v2 2026-10-30 CROSS_CHECK_Q 5, 8, 27, 28: debt ladder, latest filing first, revenue total, latest annual
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}

# concept -> (kind, [(taxonomy, tag, unit)] in priority order). Each fiscal year takes the value of the highest-priority tag that has that
# year, so a company that changed tags keeps one series; every value records its tag.
CONCEPTS = {
    "revenue": ("flow", [("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"), ("us-gaap", "Revenues", "USD"),
                         ("us-gaap", "SalesRevenueNet", "USD"), ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax", "USD"),
                         ("ifrs-full", "Revenue", "USD"), ("ifrs-full", "RevenueFromContractsWithCustomers", "USD")]),
    "operating_income": ("flow", [("us-gaap", "OperatingIncomeLoss", "USD"), ("ifrs-full", "ProfitLossFromOperatingActivities", "USD")]),
    "net_income": ("flow", [("us-gaap", "NetIncomeLoss", "USD"), ("ifrs-full", "ProfitLossAttributableToOwnersOfParent", "USD"),
                            ("ifrs-full", "ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity", "USD"),
                            ("us-gaap", "ProfitLoss", "USD"), ("ifrs-full", "ProfitLoss", "USD")]),
    "nci_income": ("flow", [("us-gaap", "NetIncomeLossAttributableToNoncontrollingInterest", "USD"),
                            ("ifrs-full", "ProfitLossAttributableToNoncontrollingInterests", "USD")]),
    "pretax_income": ("flow", [("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "USD"),
                               ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments", "USD"),
                               ("ifrs-full", "ProfitLossBeforeTax", "USD")]),
    "tax_provision": ("flow", [("us-gaap", "IncomeTaxExpenseBenefit", "USD"), ("ifrs-full", "IncomeTaxExpenseContinuingOperations", "USD")]),
    # da: total D&A, including the amortization of acquired intangibles, except the tags in DA_EXCLUDES_AMORTIZATION
    "da": ("flow", [("us-gaap", "DepreciationDepletionAndAmortization", "USD"), ("us-gaap", "DepreciationAmortizationAndAccretionNet", "USD"),
                    ("us-gaap", "DepreciationAndAmortization", "USD"), ("ifrs-full", "DepreciationAndAmortisationExpense", "USD"),
                    ("ifrs-full", "AdjustmentsForDepreciationAndAmortisationExpense", "USD"), ("us-gaap", "Depreciation", "USD"),
                    ("ifrs-full", "DepreciationExpense", "USD"), ("ifrs-full", "AdjustmentsForDepreciationExpense", "USD"),
                    ("us-gaap", "CostOfGoodsAndServicesSoldDepreciationAndAmortization", "USD")]),     # F6: the last tag, kept only per DA_COST_LINE
    "amortization": ("flow", [("us-gaap", "AmortizationOfIntangibleAssets", "USD")]),
    "capex": ("flow", [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
                       ("us-gaap", "PaymentsToAcquireProductiveAssets", "USD"),
                       ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "USD"),
                       ("us-gaap", "PaymentsToAcquireOtherPropertyPlantAndEquipment", "USD"),
                       ("us-gaap", "PaymentsToAcquireOilAndGasPropertyAndEquipment", "USD"),
                       ("us-gaap", "PaymentsToExploreAndDevelopOilAndGasProperties", "USD"),
                       ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets", "USD"),
                       ("us-gaap", "PaymentsForCapitalImprovements", "USD"), ("us-gaap", "PaymentsForConstructionInProcess", "USD"),
                       ("us-gaap", "PaymentsToAcquireRealEstate", "USD")]),
    "interest_expense": ("flow", [("us-gaap", "InterestExpense", "USD"), ("us-gaap", "InterestExpenseNonoperating", "USD"),
                                  ("us-gaap", "InterestExpenseDebt", "USD"), ("ifrs-full", "FinanceCosts", "USD"),
                                  ("us-gaap", "InterestAndDebtExpense", "USD")]),
    "diluted_shares": ("flow", [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),
                                ("ifrs-full", "AdjustedWeightedAverageShares", "shares")]),
    "eps_diluted": ("flow", [("us-gaap", "EarningsPerShareDiluted", "USD/shares"), ("ifrs-full", "DilutedEarningsLossPerShare", "USD/shares")]),
    "assets_current": ("instant", [("us-gaap", "AssetsCurrent", "USD"), ("ifrs-full", "CurrentAssets", "USD")]),
    "liabilities_current": ("instant", [("us-gaap", "LiabilitiesCurrent", "USD"), ("ifrs-full", "CurrentLiabilities", "USD")]),
    "cash": ("instant", [("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"),
                         ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD"),
                         ("ifrs-full", "CashAndCashEquivalents", "USD")]),
    # debt (CROSS_CHECK_Q 5, 27; tags from the 156-name census): a total tag if one is filed, else noncurrent + current + short-term.
    # inputs.debt_total applies the rules on which tag already includes which part.
    "debt_total": ("instant", [("us-gaap", "DebtAndCapitalLeaseObligations", "USD"), ("us-gaap", "DebtLongtermAndShorttermCombinedAmount", "USD"),
                               ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", "USD"),
                               ("us-gaap", "LongTermDebt", "USD"), ("ifrs-full", "Borrowings", "USD")]),
    "debt_noncurrent": ("instant", [("us-gaap", "LongTermDebtNoncurrent", "USD"), ("us-gaap", "LongTermDebtAndCapitalLeaseObligations", "USD"),
                                    ("us-gaap", "LongTermNotesPayable", "USD"), ("ifrs-full", "LongtermBorrowings", "USD"),
                                    ("us-gaap", "ConvertibleDebtNoncurrent", "USD")]),
    "debt_current": ("instant", [("us-gaap", "DebtCurrent", "USD"), ("us-gaap", "LongTermDebtCurrent", "USD"),
                                 ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsCurrent", "USD"),
                                 ("ifrs-full", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "USD"),
                                 ("ifrs-full", "CurrentPortionOfLongtermBorrowings", "USD"), ("us-gaap", "ConvertibleDebtCurrent", "USD")]),
    "debt_short": ("instant", [("us-gaap", "ShortTermBorrowings", "USD"), ("us-gaap", "LinesOfCreditCurrent", "USD"),
                               ("us-gaap", "CommercialPaper", "USD"), ("ifrs-full", "ShorttermBorrowings", "USD")]),
    "st_investments": ("instant", [("us-gaap", "ShortTermInvestments", "USD"), ("us-gaap", "MarketableSecuritiesCurrent", "USD")]),
    "goodwill": ("instant", [("us-gaap", "Goodwill", "USD"), ("ifrs-full", "Goodwill", "USD")]),
    "intangibles": ("instant", [("us-gaap", "IntangibleAssetsNetExcludingGoodwill", "USD"), ("us-gaap", "FiniteLivedIntangibleAssetsNet", "USD"),
                                ("ifrs-full", "IntangibleAssetsOtherThanGoodwill", "USD")]),
    "equity": ("instant", [("us-gaap", "StockholdersEquity", "USD"), ("ifrs-full", "EquityAttributableToOwnersOfParent", "USD")]),
    # the financial route (CROSS_CHECK_Q3 6, 11): preferred stock inside StockholdersEquity, income available to common, AOCI
    "preferred_equity": ("instant", [("us-gaap", "PreferredStockValue", "USD"), ("us-gaap", "PreferredStockValueOutstanding", "USD"),
                                     ("us-gaap", "PreferredStockIncludingAdditionalPaidInCapital", "USD"),
                                     ("us-gaap", "PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount", "USD")]),
    "preferred_liquidation": ("instant", [("us-gaap", "PreferredStockLiquidationPreferenceValue", "USD")]),
    "ni_common": ("flow", [("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic", "USD"),
                           ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersDiluted", "USD")]),
    "preferred_dividends": ("flow", [("us-gaap", "PreferredStockDividendsIncomeStatementImpact", "USD"),
                                     ("us-gaap", "DividendsPreferredStock", "USD"), ("us-gaap", "DividendsPreferredStockCash", "USD")]),
    "aoci": ("instant", [("us-gaap", "AccumulatedOtherComprehensiveIncomeLossNetOfTax", "USD")]),
    "ppe_net": ("instant", [("us-gaap", "PropertyPlantAndEquipmentNet", "USD"), ("ifrs-full", "PropertyPlantAndEquipment", "USD")]),
    "ppe_gross": ("instant", [("us-gaap", "PropertyPlantAndEquipmentGross", "USD")]),
    "lease_liability": ("instant", [("us-gaap", "OperatingLeaseLiability", "USD")]),
    # the filed amortization schedule of finite-lived intangibles (the next five years and after), instants at the fiscal-year end
    "amort_next_1": ("instant", [("us-gaap", "FiniteLivedIntangibleAssetsAmortizationExpenseNextTwelveMonths", "USD")]),
    "amort_next_2": ("instant", [("us-gaap", "FiniteLivedIntangibleAssetsAmortizationExpenseYearTwo", "USD")]),
    "amort_next_3": ("instant", [("us-gaap", "FiniteLivedIntangibleAssetsAmortizationExpenseYearThree", "USD")]),
    "amort_next_4": ("instant", [("us-gaap", "FiniteLivedIntangibleAssetsAmortizationExpenseYearFour", "USD")]),
    "amort_next_5": ("instant", [("us-gaap", "FiniteLivedIntangibleAssetsAmortizationExpenseYearFive", "USD")]),
    "amort_after_5": ("instant", [("us-gaap", "FiniteLivedIntangibleAssetsAmortizationExpenseAfterYearFive", "USD")]),
    # F6 (AUX_CONCEPTS): the inputs of the derived series in _derive, and the lease and financing interest that inputs.base reads
    "income_continuing": ("flow", [("us-gaap", "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest", "USD"),
                                   ("ifrs-full", "ProfitLossFromContinuingOperations", "USD")]),
    "income_discontinued": ("flow", [("us-gaap", "IncomeLossFromDiscontinuedOperationsNetOfTax", "USD"),
                                     ("ifrs-full", "ProfitLossFromDiscontinuedOperations", "USD")]),
    "profit_loss_consolidated": ("flow", [("us-gaap", "ProfitLoss", "USD"), ("ifrs-full", "ProfitLoss", "USD")]),
    "basic_shares_ifrs": ("flow", [("ifrs-full", "WeightedAverageShares", "shares")]),
    "dilutive_effect_ifrs": ("flow", [("ifrs-full", "DilutiveEffectOfAllInstrumentsOnWeightedAverageNumberOfOrdinaryShares", "shares"),
                                      ("ifrs-full", "DilutiveEffectOfShareOptionsOnNumberOfOrdinaryShares", "shares")]),
    "equity_incl_nci": ("instant", [("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "USD"),
                                    ("ifrs-full", "Equity", "USD")]),
    "nci_equity": ("instant", [("us-gaap", "MinorityInterest", "USD"), ("ifrs-full", "NoncontrollingInterests", "USD")]),
    "cost_excl_da": ("flow", [("us-gaap", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization", "USD")]),
    "lease_interest_ifrs16": ("flow", [("ifrs-full", "InterestExpenseOnLeaseLiabilities", "USD")]),
    "lease_liabilities_ifrs16": ("instant", [("ifrs-full", "LeaseLiabilities", "USD")]),
    "lease_liabilities_current_ifrs16": ("instant", [("ifrs-full", "CurrentLeaseLiabilities", "USD")]),
    "financing_interest": ("flow", [("us-gaap", "FinancingInterestExpense", "USD")]),
}
AUX_CONCEPTS = {"income_continuing", "income_discontinued", "profit_loss_consolidated", "basic_shares_ifrs", "dilutive_effect_ifrs",
                "equity_incl_nci", "nci_equity", "cost_excl_da", "lease_interest_ifrs16", "lease_liabilities_ifrs16", "lease_liabilities_current_ifrs16",
                "financing_interest"}
# F6: the cost-of-sales D&A line is D&A only where the same year's cost of sales is filed EXCLUDING D&A (the face statement then shows
# D&A as its own line, which this tag carries); without that companion the year's value is dropped. Stamped da_from_cost_of_sales_line
DA_COST_LINE = "CostOfGoodsAndServicesSoldDepreciationAndAmortization"
# F6: a USD fact under any tag naming an income tax, in an annual form effective by T, means the company reports income taxes
TAX_FACT_RX = re.compile(r"IncomeTax|TaxExpense|CurrentTax|DeferredTax|TaxesPaid")
PRETAX_FROM_NI = "pretax_from_net_income_no_tax_filed"
EPS_TOL, EPS_ROUNDING = 0.01, 0.006        # the ProfitLoss reconciliation's 1%; diluted EPS is filed to the cent (inputs.EPS_ROUNDING)


DA_EXCLUDES_AMORTIZATION = {"Depreciation", "DepreciationExpense", "AdjustmentsForDepreciationExpense"}     # depreciation alone: nothing to subtract for D&A_org
MAX_CONCEPTS = {"revenue"}


def latest_annual_period(subs, T):
    """The report period of the newest annual filing (ANNUAL_FORMS) effective by T, from the submissions, or None (ruling 8)."""
    rows = [r for r in packet._filing_rows(subs) if r["form"] in ANNUAL_FORMS and r["effective"] and r["effective"] <= T and r.get("report_date")]
    return max((r["report_date"] for r in rows), default=None)


def companyfacts_url(cik):
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"


def submissions_url(cik):
    return f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"


def eligible_accessions(subs, T):
    """{accession: effective UTC} for the submissions' filings effective by T (aware datetime)."""
    return {r["accession"]: r["effective"] for r in packet._filing_rows(subs) if r["effective"] and r["effective"] <= T}


def _eligible(fact, eligible, known, T):
    acc = fact.get("accn")
    if acc in eligible:
        return True, None
    if acc in known:
        return False, None
    filed = fact.get("filed")
    try:
        ok = date.fromisoformat(filed) + timedelta(days=2) < T.date()
    except (TypeError, ValueError):
        return False, None
    return ok, ("acceptance_by_filed_date" if ok else None)


def _duration_days(fact):
    try:
        return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
    except (KeyError, TypeError, ValueError):
        return None


def _series(rows, kind, eligible, known, T):
    """{end: chosen fact} for one tag's facts."""
    by_end = {}
    for f in rows:
        if f.get("form") not in ANNUAL_FORMS or not isinstance(f.get("val"), (int, float)):
            continue
        if kind == "flow":
            d = _duration_days(f)
            if f.get("fp") != "FY" or d is None or not 350 <= d <= 380:
                continue
        elif "start" in f:
            continue
        ok, stamp = _eligible(f, eligible, known, T)
        if not ok:
            continue
        cur = by_end.get(f["end"])
        key = (f.get("filed") or "", f.get("accn") or "")
        if cur is None or key > cur[0]:
            by_end[f["end"]] = (key, dict(f, stamp=stamp))
    return {e: v[1] for e, v in by_end.items()}


def annual_facts(cf, subs, T, years=8):
    """{concept: {"tags", "values": [{end, start, value, tag, accn, form, filed, stamp}] oldest first (at most `years`)}} plus
    {"_absent": {concept: reason}} and {"_stale": {concept: its latest end}} for a concept ending before the latest revenue year.
    Net income from ProfitLoss (consolidated) takes the basis, as filed or less the noncontrolling interest, that reconciles with
    diluted EPS x diluted shares within 1% (stamped); neither: left as filed, stamped `profitloss_basis_unverified`. Then the F6 derived
    series (_derive). cf, subs: the parsed companyfacts and submissions JSON; T: aware."""
    eligible = eligible_accessions(subs, T)
    known = {r["accession"] for r in packet._filing_rows(subs)}
    facts = cf.get("facts") or {}
    out, absent = {}, {}
    for concept, (kind, tags) in CONCEPTS.items():
        cands = {}                                                      # end -> [(filed, accn, -priority, value, fact)]
        for pri, (tax, tag, unit) in enumerate(tags):
            rows = (((facts.get(tax) or {}).get(tag) or {}).get("units") or {}).get(unit) or []
            for e, f in _series(rows, kind, eligible, known, T).items():
                cands.setdefault(e, []).append((f.get("filed") or "", f.get("accn") or "", -pri, float(f["val"]), dict(f, tag=tag)))
        merged = {}
        for e, cs in cands.items():
            # ruling 28: the latest eligible filing first; within it, tag priority. Revenue (ruling 5c): within it, the largest line, so the
            # total wins over an ASC 606 subset; the choice is stamped when lines disagree
            latest = max((c[0], c[1]) for c in cs)
            same = [c for c in cs if (c[0], c[1]) == latest]
            if concept in MAX_CONCEPTS:
                pick = max(same, key=lambda c: (c[3], c[2]))
                if len({round(c[3]) for c in same}) > 1:
                    pick[4]["stamp"] = pick[4].get("stamp") or "revenue_largest_of_tags"
            else:
                pick = max(same, key=lambda c: c[2])
            merged[e] = pick[4]
        if not merged:
            absent[concept] = "no eligible annual fact under any listed tag"
            continue
        vals = [{"end": e, "start": f.get("start"), "value": float(f["val"]), "tag": f["tag"], "accn": f.get("accn"), "form": f.get("form"),
                 "filed": f.get("filed"), "stamp": f.get("stamp")} for e, f in sorted(merged.items())][-years:]
        out[concept] = {"tags": sorted({v["tag"] for v in vals}), "values": vals}
    nci = {v["end"]: v["value"] for v in out.get("nci_income", {}).get("values", [])}
    eps = {v["end"]: v["value"] for v in out.get("eps_diluted", {}).get("values", [])}
    sh = {v["end"]: v["value"] for v in out.get("diluted_shares", {}).get("values", [])}
    for v in out.get("net_income", {}).get("values", []):
        if v["tag"] != "ProfitLoss":
            continue
        # consolidated ProfitLoss may or may not already exclude the noncontrolling interest: take the basis that reconciles with diluted
        # EPS x diluted shares within 1%; neither (or no EPS) is stamped unverified and left as filed
        implied = eps[v["end"]] * sh[v["end"]] if v["end"] in eps and v["end"] in sh else None
        options = [(v["value"], "profitloss_as_attributable")]
        if v["end"] in nci:
            options.append((v["value"] - nci[v["end"]], "profitloss_less_nci"))
        fits = [o for o in options if implied and abs(o[0] / implied - 1) <= 0.01]
        if fits:
            v["value"], v["stamp"] = min(fits, key=lambda o: abs(o[0] / implied - 1))
        else:
            v["stamp"] = "profitloss_basis_unverified"
    _derive(out, absent, cf, eligible, known, T, years)
    latest = max((v["end"] for v in out.get("revenue", {}).get("values", [])), default=None)
    stale = {c: d["values"][-1]["end"] for c, d in out.items()
             if latest and d["values"][-1]["end"] < latest and c != "nci_income" and c not in AUX_CONCEPTS}
    out["_absent"], out["_stale"] = absent, stale
    out["_latest_annual_period"] = latest_annual_period(subs, T)
    return out


def _stamp(*stamps):
    return ";".join(s for s in stamps if s) or None


def has_stamp(value, stamp):
    """Whether a fact value carries `stamp` (a value's stamps are joined by ';')."""
    return stamp in (value.get("stamp") or "").split(";")


def _reports_income_tax(cf, eligible, known, T):
    """Whether any USD fact under a us-gaap or ifrs-full tag naming an income tax (TAX_FACT_RX) is in an annual form effective by T."""
    for tax in ("us-gaap", "ifrs-full"):
        for tag, d in ((cf.get("facts") or {}).get(tax) or {}).items():
            if TAX_FACT_RX.search(tag) and any(f.get("form") in ANNUAL_FORMS and _eligible(f, eligible, known, T)[0]
                                               for f in ((d.get("units") or {}).get("USD") or [])):
                return True
    return False


def _derive(out, absent, cf, eligible, known, T, years):
    """F6: series derived from filed facts by one rule each, for every company, each value stamped and tagged with its sources (so a
    switch from a filed tag to a derived value stays visible). Only facts already eligible at T enter (they come from `out`)."""
    by = {c: {v["end"]: v for v in (out.get(c) or {}).get("values", [])} for c in CONCEPTS}

    def put(concept, end, value, tag, stamp, src):
        d = out.setdefault(concept, {"tags": [], "values": []})
        d["values"] = sorted(d["values"] + [{"end": end, "start": src.get("start"), "value": value, "tag": tag, "accn": src.get("accn"),
                                             "form": src.get("form"), "filed": src.get("filed"), "stamp": _stamp(src.get("stamp"), stamp)}],
                             key=lambda v: v["end"])[-years:]
        d["tags"] = sorted({v["tag"] for v in d["values"]})
        absent.pop(concept, None)

    # (1) no income tax filed at all: a company that files neither pretax income nor a provision, and no income-tax fact of any kind, shows
    # no tax line, so its pretax income is its income from continuing operations including NCI (else its consolidated profit, when no
    # discontinued operation is filed for the year). inputs.tax_rate then takes tau = 0 (stamped)
    if not by["pretax_income"] and not by["tax_provision"] and not _reports_income_tax(cf, eligible, known, T):
        for e, v in by["net_income"].items():
            if e in by["income_continuing"]:
                src = by["income_continuing"][e]
                put("pretax_income", e, src["value"], src["tag"], PRETAX_FROM_NI, src)
            elif e in by["income_discontinued"] and by["income_discontinued"][e]["value"] != 0:
                continue                                                  # profit includes a discontinued operation: not a continuing base
            elif e in by["profit_loss_consolidated"]:
                src = by["profit_loss_consolidated"][e]
                put("pretax_income", e, src["value"], src["tag"], PRETAX_FROM_NI, src)
            elif e in by["nci_income"]:
                put("pretax_income", e, v["value"] + by["nci_income"][e]["value"], f"{v['tag']}+{by['nci_income'][e]['tag']}", PRETAX_FROM_NI, v)
            else:
                put("pretax_income", e, v["value"], v["tag"], PRETAX_FROM_NI, v)
    # (2) IFRS diluted shares: basic weighted-average shares plus the filed dilutive effect (none filed: 0), accepted only where net income
    # per share on it reconciles with filed diluted EPS within 1% or to the cent
    for e, b in by["basic_shares_ifrs"].items():
        ni, eps = by["net_income"].get(e), by["eps_diluted"].get(e)
        if e in by["diluted_shares"] or ni is None or eps is None:
            continue
        inc = by["dilutive_effect_ifrs"].get(e)
        n = b["value"] + (inc["value"] if inc is not None else 0.0)
        if not n > 0:
            continue
        implied = ni["value"] / n
        if abs(implied - eps["value"]) <= EPS_ROUNDING or (eps["value"] != 0 and abs(implied / eps["value"] - 1) <= EPS_TOL):
            put("diluted_shares", e, n, f"WeightedAverageShares+{inc['tag'] if inc is not None else 'no_dilutive_effect_filed'}",
                "diluted_shares_from_basic_plus_dilutive_effect", b)
    # (3) equity attributable to the parent where only total equity is filed: the total less the filed NCI balance; with no NCI balance
    # filed, the total itself when nothing is attributed to NCI that year (NCI income filed as 0, or consolidated profit equal to net
    # income) and the last NCI balance filed before, if any, was 0
    for e, t in by["equity_incl_nci"].items():
        if e in by["equity"]:
            continue
        if e in by["nci_equity"]:
            nci = by["nci_equity"][e]
            put("equity", e, t["value"] - nci["value"], f"{t['tag']}-{nci['tag']}", "equity_total_less_nci", t)
            continue
        prior = [x for x in by["nci_equity"] if x < e]
        if prior and by["nci_equity"][max(prior)]["value"] != 0:
            continue
        ni, plc, nci_i = by["net_income"].get(e), by["profit_loss_consolidated"].get(e), by["nci_income"].get(e)
        if (nci_i is not None and nci_i["value"] == 0) or (
                ni is not None and plc is not None and ni["tag"] != "ProfitLoss" and abs(plc["value"] - ni["value"]) < 0.5):
            put("equity", e, t["value"], t["tag"], "equity_total_no_nci_income", t)
    # (4) the cost-of-sales D&A line (the last D&A tag) only beside cost of sales filed excluding D&A
    if "da" in out:
        vals = []
        for v in out["da"]["values"]:
            if v["tag"] == DA_COST_LINE:
                if v["end"] not in by["cost_excl_da"]:
                    continue
                v["stamp"] = _stamp(v.get("stamp"), "da_from_cost_of_sales_line")
            vals.append(v)
        if vals:
            out["da"] = {"tags": sorted({v["tag"] for v in vals}), "values": vals}
        else:
            del out["da"]
            absent["da"] = f"only {DA_COST_LINE}, without cost of sales filed excluding D&A"


def fetch(cik, T, *, online, root=None):
    """The companyfacts and submissions bytes through sec_store, parsed, with provenance. A snapshot fetched after T is stamped."""
    prov, docs = {}, {}
    for name, url in (("companyfacts", companyfacts_url(cik)), ("submissions", submissions_url(cik))):
        data = sec_store.get(url, online=online, root=root)
        rec = sec_store.latest_receipt(url, root=root)
        docs[name] = json.loads(data.decode("utf-8"))
        fetched = datetime.fromisoformat(rec["fetched_at"].replace("Z", "+00:00")) if rec and rec.get("fetched_at") else None
        prov[name] = {"url": url, "sha256": rec.get("sha256") if rec else None, "fetched_at": rec.get("fetched_at") if rec else None,
                      "stamp": "snapshot_after_T" if (fetched is None or fetched > T) else None}
    return docs["companyfacts"], docs["submissions"], prov


def build(cik, T, *, online, root=None, years=8):
    cf, subs, prov = fetch(cik, T, online=online, root=root)
    out = annual_facts(cf, subs, T, years=years)
    out["_provenance"] = dict(prov, facts_version=FACTS_VERSION, T=T.astimezone(timezone.utc).isoformat())
    return out
