"""facts.py - point-in-time filed figures for the 3Q desk (SPEC_m3q_valuation.md §2, WO_Q4).

Source: SEC companyfacts (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json) read through sec_store, so the exact bytes are
pinned. companyfacts lists every filing's own reported value with its accession, so a value counts at time T only if its accession was
effective by T (packet.effective_at of the submissions acceptance). An accession missing from the submissions' recent list counts only
if its filing date is at least 2 calendar days before T's date, stamped `acceptance_by_filed_date`. A snapshot fetched after T is a
reconstruction of what was filed, stamped `snapshot_after_T`; it is not proof of what a reader had at T.

For each concept and fiscal-year end, the value of the LATEST eligible filing is used (a restatement filed before T is what was known
at T). Annual flows are full-year facts (fp FY, a 350-380 day duration) from 10-K, 10-K/A, 20-F, 20-F/A, 40-F, 40-F/A; balances are
instants at a fiscal-year end of the same forms. Nothing is defaulted: a missing concept is absent from the result with its reason.
`_ytd` (F11) is year 1's year-to-date revenue and operating income, both legs from the latest 10-Q effective at T (ytd()).
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from qwen_c import packet, sec_store
from qwen_c.value import ix_figures

FACTS_VERSION = "m3q.facts.v15"   # v15 2026-11-19 WO_UV5: a capex or D&A series read from the filing's inline XBRL holds the filing's own years only (the feed's years under another tag are dropped); interest_expense_ifrs (auxiliary: ifrs-full:InterestExpense, read by inputs only where the finance-cost bundle gives a cost of debt outside the band); no existing series moves for a name the filing's inline XBRL was not read for   # v14 2026-11-19 WO_UV3: figures read from the newest annual filing's inline XBRL where companyfacts lacks them and the base would be refused (ix_figures: a year not ingested, capital spending under a company's own tags, one-segment D&A, class-of-stock share counts), each verified by a second filed figure and stamped ix_read; no existing series moves   # v13 2026-11-19 WO_UV2: cash interest paid also under us-gaap:InterestPaid; auxiliary senior-notes, line-of-credit, partnership-unit, redeemable-NCI, total assets and total liabilities concepts (read by inputs only where the exact figure cannot be read); the ProfitLoss basis also less the redeemable NCI income; pretax income derived from net income, NCI income and the tax provision where its tag is absent or stale and no discontinued operation is filed for the year (no existing series moves)   # v12 2026-11-19 WO_NC9c: re_gain_on_sales and re_impairment (auxiliary, the real-estate record block; no existing concept moves)   # v11 2026-11-18 WO_NC3: statutory_tax_rate, the rate the company files for the base year in its own rate reconciliation (auxiliary; inputs.tax_rate reads it only as the last rung)   # v10 2026-11-18 WO_NC2: labelled substitutes for equity, capex, D&A, current items and pretax income (ITEM_SUBSTITUTES), consulted only where the exact concept lacks a needed year, one tag for every year   # v9 2026-11-17 WO_NC1: labelled fact substitutes (revenue: the largest narrower revenue line; aux period-end share counts and interest paid), consulted only where the exact concept is absent   # v8 2026-11-07 coverage A: parent equity is the filed total where the company files no NCI fact of any kind   # v7 2026-11-03 F_SPEC_valuation_menu v1.3 (F11): `_ytd`, year 1's year-to-date revenue and operating income from the latest 10-Q effective at T, current and prior-year legs from that one filing   # v6 2026-11-03 F_SPEC_valuation_menu F6: derived series, each value stamped: pretax income where no income-tax fact is filed, IFRS diluted shares from basic plus the dilutive effect (EPS-reconciled), equity from the total less NCI; the cost-of-sales D&A line as the last D&A tag; IFRS 16 lease and financing-interest facts for inputs   # v5 2026-11-03 RR_Q7 3: IFRS net income (ProfitLoss, ordinary holders), NCI, diluted EPS, depreciation   # v4 2026-10-31 CROSS_CHECK_Q3b N5: preferred liquidation preference   # v3 2026-10-30 CROSS_CHECK_Q3 5, 6, 11: preferred stock, income to common, AOCI (financial route)   # v2 2026-10-30 CROSS_CHECK_Q 5, 8, 27, 28: debt ladder, latest filing first, revenue total, latest annual
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
    # WO_UV5: the IFRS interest expense concept, read by inputs only where the finance-cost bundle (ifrs-full:FinanceCosts) gives a cost of debt outside the band
    "interest_expense_ifrs": ("flow", [("ifrs-full", "InterestExpense", "USD")]),
    # WO_NC1 substitutes: read by inputs only where the exact concept is absent (never part of an exact series)
    "shares_period_end": ("instant", [("us-gaap", "CommonStockSharesOutstanding", "shares"), ("ifrs-full", "NumberOfSharesOutstanding", "shares")]),
    "shares_cover": ("instant", [("dei", "EntityCommonStockSharesOutstanding", "shares")]),
    "interest_paid": ("flow", [("us-gaap", "InterestPaidNet", "USD"), ("ifrs-full", "InterestPaidClassifiedAsOperatingActivities", "USD"),
                               ("ifrs-full", "InterestPaidClassifiedAsFinancingActivities", "USD"),
                               ("us-gaap", "InterestPaid", "USD")]),       # WO_UV2: the gross cash interest, last, so that no company that has a listed tag changes
    # WO_NC3: the statutory rate the company states in its own rate reconciliation (a fraction); read by inputs.tax_rate only, as the last rung
    "statutory_tax_rate": ("flow", [("us-gaap", "EffectiveIncomeTaxRateReconciliationAtFederalStatutoryIncomeTaxRate", "pure"),
                                    ("ifrs-full", "ApplicableTaxRate", "pure")]),
    # WO_NC9c: the real-estate record block only (the decided method's derived funds from operations); no valuation input reads them. Gains: the first
    # tag filed for the year, a gain positive; impairments: the first filed, a charge positive
    "re_gain_on_sales": ("flow", [("us-gaap", "GainLossOnSaleOfProperties", "USD"), ("us-gaap", "GainsLossesOnSalesOfInvestmentRealEstate", "USD"),
                                  ("us-gaap", "GainLossOnDispositionOfAssets", "USD"), ("us-gaap", "GainLossOnSaleOfPropertyPlantEquipment", "USD"),
                                  ("us-gaap", "GainLossOnDispositionOfAssets1", "USD"), ("us-gaap", "GainsLossesOnSalesOfOtherRealEstate", "USD")]),
    "re_impairment": ("flow", [("us-gaap", "ImpairmentOfRealEstate", "USD"), ("us-gaap", "AssetImpairmentCharges", "USD"),
                               ("us-gaap", "ImpairmentOfLongLivedAssetsHeldForUse", "USD")]),
    # WO_UV2: read by inputs only where the exact figure cannot be read (never part of an exact series)
    "debt_senior_total": ("instant", [("us-gaap", "SeniorNotes", "USD")]),
    "debt_senior_noncurrent": ("instant", [("us-gaap", "SeniorLongTermNotes", "USD")]),
    "debt_senior_current": ("instant", [("us-gaap", "SeniorNotesCurrent", "USD")]),
    "line_of_credit_noncurrent": ("instant", [("us-gaap", "LongTermLineOfCredit", "USD")]),
    "lp_units_diluted": ("flow", [("us-gaap", "WeightedAverageLimitedPartnershipUnitsOutstandingDiluted", "shares")]),
    "eps_lp_diluted": ("flow", [("us-gaap", "NetIncomeLossNetOfTaxPerOutstandingLimitedPartnershipUnitDiluted", "USD/shares")]),
    "nci_redeemable_income": ("flow", [("us-gaap", "NetIncomeLossAttributableToRedeemableNoncontrollingInterest", "USD")]),
    "assets_total": ("instant", [("us-gaap", "Assets", "USD"), ("ifrs-full", "Assets", "USD")]),
    "liabilities_total": ("instant", [("us-gaap", "Liabilities", "USD"), ("ifrs-full", "Liabilities", "USD")]),
}
# WO_NC1: the narrower revenue lines, consulted only when no total-revenue tag resolves for any year
REVENUE_SUBSTITUTES = [("ifrs-full", "RevenueFromRenderingOfServices", "USD"), ("ifrs-full", "RevenueFromRenderingOfTransportServices", "USD"),
                       ("ifrs-full", "RevenueFromSaleOfGoods", "USD"), ("ifrs-full", "RevenueFromSaleOfGold", "USD"),
                       ("us-gaap", "SalesRevenueServicesNet", "USD"), ("us-gaap", "SalesRevenueGoodsNet", "USD")]
SUBSTITUTE_PREFIX = "substitute:"
SUBSTITUTE_SCOPE_PREFIX = "substitute_scope:"
# WO_NC2: concept -> [(taxonomy, tag or (tag, tag) summed, unit, scope or None)] in priority order; consulted only where the exact concept lacks a
# year the valuation reads (_item_substitutes). Left out on purpose, so the refusal stands: AmortizationOfIntangibleAssets (only part of D&A) and
# the depletion tags (no depreciation), and every tag not listed
ITEM_SUBSTITUTES = {
    "equity": [("us-gaap", "PartnersCapital", "USD", None),
               ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "USD", "includes_nci")],
    "capex": [("ifrs-full", "PurchaseOfMiningAssets", "USD", None), ("us-gaap", "PropertyPlantAndEquipmentAdditions", "USD", None),
              ("us-gaap", "PaymentsForProceedsFromProductiveAssets", "USD", "net")],      # net of disposals: only while a net outflow in every year read
    "da": [("us-gaap", "ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion", "USD", "producing_activities_only")],      # the oil and gas producing-activities disclosure: no corporate depreciation, with accretion
    "assets_current": [("ifrs-full", "CurrentAssetsOtherThanAssetsOrDisposalGroupsClassifiedAsHeldForSaleOrAsHeldForDistributionToOwners", "USD",
                        "excludes_held_for_sale")],
    "liabilities_current": [("ifrs-full", "CurrentLiabilitiesOtherThanLiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale", "USD",
                             "excludes_held_for_sale")],
    "pretax_income": [("us-gaap", ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign"),
                       "USD", None)],      # both parts must be filed for a year
}
NET_SCOPE = "net"
SUBSTITUTE_WINDOW, SUBSTITUTE_MIN_POOL = 5, 3     # inputs.POOL_YEARS and MIN_POOL_YEARS: the years capex and D&A are pooled over
AUX_CONCEPTS = {"income_continuing", "income_discontinued", "profit_loss_consolidated", "basic_shares_ifrs", "dilutive_effect_ifrs",
                "equity_incl_nci", "nci_equity", "cost_excl_da", "lease_interest_ifrs16", "lease_liabilities_ifrs16", "lease_liabilities_current_ifrs16",
                "financing_interest", "interest_expense_ifrs",
                "shares_period_end", "shares_cover", "interest_paid", "statutory_tax_rate", "re_gain_on_sales", "re_impairment",
                "debt_senior_total", "debt_senior_noncurrent", "debt_senior_current", "line_of_credit_noncurrent", "lp_units_diluted", "eps_lp_diluted",
                "nci_redeemable_income", "assets_total", "liabilities_total"}
# F6: the cost-of-sales D&A line is D&A only where the same year's cost of sales is filed EXCLUDING D&A (the face statement then shows
# D&A as its own line, which this tag carries); without that companion the year's value is dropped. Stamped da_from_cost_of_sales_line
DA_COST_LINE = "CostOfGoodsAndServicesSoldDepreciationAndAmortization"
# F6: a USD fact under any tag naming an income tax, in an annual form effective by T, means the company reports income taxes
TAX_FACT_RX = re.compile(r"IncomeTax|TaxExpense|CurrentTax|DeferredTax|TaxesPaid")
PRETAX_FROM_NI = "pretax_from_net_income_no_tax_filed"
PRETAX_DERIVED = "pretax_derived_from_net_income_nci_tax"      # WO_UV2: net income + NCI income + the filed provision; no discontinued operation filed for the year
DISCONTINUED_RX = re.compile(r"Discontinued")
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


def annual_facts(cf, subs, T, years=8, substitute_revenue=False, substitute_items=False, ix=None):
    """{concept: {"tags", "values": [{end, start, value, tag, accn, form, filed, stamp}] oldest first (at most `years`)}} plus
    {"_absent": {concept: reason}} and {"_stale": {concept: its latest end}} for a concept ending before the latest revenue year.
    Net income from ProfitLoss (consolidated) takes the basis, as filed or less the noncontrolling interest, that reconciles with
    diluted EPS x diluted shares within 1% (stamped); neither: left as filed, stamped `profitloss_basis_unverified`. Then the F6 derived
    series (_derive). substitute_revenue (WO_NC1, the operating route only): where no total-revenue tag resolves for any year, the single
    largest narrower revenue line (REVENUE_SUBSTITUTES), one tag for every year, each value stamped `substitute:revenue:<taxonomy>:<tag>`.
    substitute_items (WO_NC2, the operating route only): the ITEM_SUBSTITUTES, after the derived series.
    ix (WO_UV3): a function returning the newest annual filing's ix_figures.Source (or None), called at most once and only where a reading of
    ix_figures is wanted; None: no reading is made (every series as before).
    cf, subs: the parsed companyfacts and submissions JSON; T: aware."""
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
    if substitute_revenue and "revenue" not in out:
        sub = _revenue_substitute(facts, eligible, known, T, years)
        if sub:
            out["revenue"] = sub
            absent.pop("revenue", None)
    once, ix_read, ix_single = _Once(ix), {}, {}

    def cf_value(tax, tag, unit, kind, end):
        rows = (((facts.get(tax) or {}).get(tag) or {}).get("units") or {}).get(unit) or []
        got = _series(rows, kind, eligible, known, T).get(end)
        return float(got["val"]) if got else None
    newest = latest_annual_period(subs, T)
    have_rev = max((v["end"] for v in out.get("revenue", {}).get("values", [])), default=None)
    if ix is not None and have_rev and newest and newest > have_rev:        # WO_UV3: the newest annual report is not in companyfacts: its own figures, each verified
        src = once()
        if src is not None and src.report_date == newest:
            got = ix_figures.fill_new_year(out, absent, src, cf_value, CONCEPTS, MAX_CONCEPTS, years)
            if got:
                ix_read["new_year"] = got
    nci = {v["end"]: v["value"] for v in out.get("nci_income", {}).get("values", [])}
    eps = {v["end"]: v["value"] for v in out.get("eps_diluted", {}).get("values", [])}
    sh = {v["end"]: v["value"] for v in out.get("diluted_shares", {}).get("values", [])}
    red = {v["end"]: v for v in out.get("nci_redeemable_income", {}).get("values", [])}
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
        if not fits and v["end"] in red:
            # WO_UV2: only where neither basis above reconciles: the filed redeemable NCI income is also taken out (alone, or with the plain NCI)
            options = ([(v["value"] - nci[v["end"]] - red[v["end"]]["value"], "profitloss_less_nci_and_redeemable_nci")] if v["end"] in nci
                       else [(v["value"] - red[v["end"]]["value"], "profitloss_less_redeemable_nci")])
            fits = [o for o in options if implied and abs(o[0] / implied - 1) <= 0.01]
            if fits:
                _add_nci(out, v["end"], red[v["end"]], nci)
                absent.pop("nci_income", None)
        if fits:
            v["value"], v["stamp"] = min(fits, key=lambda o: abs(o[0] / implied - 1))
        else:
            v["stamp"] = "profitloss_basis_unverified"
    _derive(out, absent, cf, eligible, known, T, years)
    if substitute_items:
        _item_substitutes(out, absent, facts, eligible, known, T, years)
        if ix is not None:
            _ix_spending(out, absent, once, ix_read, years, ix_single)
    latest = max((v["end"] for v in out.get("revenue", {}).get("values", [])), default=None)
    stale = {c: d["values"][-1]["end"] for c, d in out.items()
             if latest and d["values"][-1]["end"] < latest and c != "nci_income" and c not in AUX_CONCEPTS}
    out["_absent"], out["_stale"] = absent, stale
    if ix is not None and latest and _shares_wanted(out, latest):
        src = once()                                                   # WO_UV3: class-of-stock share counts; inputs proves them against their own EPS
        cands = ix_figures.share_candidates(src.doc, latest) if src is not None and src.report_date == latest else []
        if cands:
            out["_ix_shares"] = {"end": latest, "accession": src.accession, "url": src.url, "candidates": cands}
    if once.src is not None:
        out["_ix"] = {"url": once.src.url, "accession": once.src.accession, "read": ix_read, "version": ix_figures.IX_FIGURES_VERSION,
                     **({"single_source": ix_single} if ix_single else {})}
    out["_latest_annual_period"] = latest_annual_period(subs, T)
    out["_ytd"] = ytd(cf, eligible, known, T, (out.get("revenue") or {}).get("values", [])[-1:])
    return out


class _Once:
    """Calls `fn` (the ix source loader) at most once; `src` is its result, None while it has not been needed (or it found nothing)."""

    def __init__(self, fn):
        self.fn, self.src, self.called = fn, None, False

    def __call__(self):
        if not self.called and self.fn is not None:
            self.called, self.src = True, self.fn()
        return self.src


def _shares_wanted(out, end):
    """WO_UV3: whether the base year `end` has no diluted share count that the valuation could use: none filed, and no period-end or cover-page count
    (inputs.shares_substitute) with a filed diluted EPS to prove it. Only then are the class-of-stock counts of the filing's document wanted."""
    from qwen_c.value import inputs
    if end in {v["end"] for v in (out.get("diluted_shares") or {}).get("values", [])}:
        return False
    return inputs.shares_substitute(out, end) is None or end not in {v["end"] for v in (out.get("eps_diluted") or {}).get("values", [])}


def _ix_spending(out, absent, once, ix_read, years, note):
    """WO_UV3: capital spending and D&A from the newest annual filing's inline XBRL (ix_figures), for the operating route and only where the
    valuation would be refused for them: the base year, or at least SUBSTITUTE_MIN_POOL of the last SUBSTITUTE_WINDOW fiscal years of revenue,
    is missing from the series (after the companyfacts series and the WO_NC2 substitutes). WO_UV5: a series so read holds the filing's years only
    (ix_figures.fill_capex, fill_da); `note` receives, per concept, the years read and the feed's years dropped, for inputs' refusal wording."""
    ends = sorted(v["end"] for v in (out.get("revenue") or {}).get("values", []))[-SUBSTITUTE_WINDOW:]
    if not ends:
        return

    def lacking(concept):
        have = {v["end"] for v in (out.get(concept) or {}).get("values", [])}
        return ends[-1] not in have or len(have & set(ends)) < SUBSTITUTE_MIN_POOL
    for concept, fn in (("capex", lambda s: ix_figures.fill_capex(out, absent, s, years, note)),
                        ("da", lambda s: ix_figures.fill_da(out, absent, s, DA_EXCLUDES_AMORTIZATION, years, note))):
        if lacking(concept):
            src = once()
            if src is not None and src.report_date >= ends[-1]:
                got = fn(src)
                if got:
                    ix_read[concept] = got


def _add_nci(out, end, red, nci):
    """WO_UV2: the redeemable NCI income of `end` joins the NCI income series (added to the plain NCI income where that is filed for the year),
    stamped, so the earnings base takes out the same NCI that the ProfitLoss basis took out. `nci` is the loop's {end: value}, kept in step."""
    d = out.setdefault("nci_income", {"tags": [], "values": []})
    cur = next((x for x in d["values"] if x["end"] == end), None)
    if cur is None:
        d["values"] = sorted(d["values"] + [dict(red, stamp=_stamp(red.get("stamp"), "nci_income_includes_redeemable_nci"))], key=lambda x: x["end"])
    else:
        cur.update(value=cur["value"] + red["value"], tag=f"{cur['tag']}+{red['tag']}", stamp=_stamp(cur.get("stamp"), "nci_income_includes_redeemable_nci"))
    nci[end] = next(x["value"] for x in d["values"] if x["end"] == end)
    d["tags"] = sorted({x["tag"] for x in d["values"]})


def taxonomy_of(concept, tag):
    """The taxonomy of a tag listed under `concept` in CONCEPTS (the substitute stamps name it)."""
    return next(tax for tax, t, _ in CONCEPTS[concept][1] if t == tag)


def _revenue_substitute(facts, eligible, known, T, years):
    """WO_NC1: the company's single largest filed narrower revenue line, as a revenue series, or None. Each candidate tag's annual series
    is built as for any flow; the tag is the one with the largest value at the latest fiscal-year end any candidate has (ties: the
    listing order), and that ONE tag supplies every year, never a mix. Every value is stamped substitute:revenue:<taxonomy>:<tag>."""
    series = {}
    for pri, (tax, tag, unit) in enumerate(REVENUE_SUBSTITUTES):
        rows = (((facts.get(tax) or {}).get(tag) or {}).get("units") or {}).get(unit) or []
        got = _series(rows, "flow", eligible, known, T)
        if got:
            series[(tax, tag)] = (pri, got)
    if not series:
        return None
    latest = max(max(g) for _, g in series.values())
    top = max((k for k, (_, g) in series.items() if latest in g), key=lambda k: (float(series[k][1][latest]["val"]), -series[k][0]))
    tax, tag = top
    stamp = f"{SUBSTITUTE_PREFIX}revenue:{tax}:{tag}"
    vals = [{"end": e, "start": f.get("start"), "value": float(f["val"]), "tag": tag, "accn": f.get("accn"), "form": f.get("form"),
             "filed": f.get("filed"), "stamp": _stamp(f.get("stamp"), stamp)} for e, f in sorted(series[top][1].items())][-years:]
    return {"tags": [tag], "values": vals}


def _item_series(facts, tax, tag, unit, kind, eligible, known, T):
    """{end: fact} of one substitute: the annual series of its tag, or, for a pair of tags, the sum over the years both are filed."""
    tags = (tag,) if isinstance(tag, str) else tag
    parts = [_series((((facts.get(tax) or {}).get(t) or {}).get("units") or {}).get(unit) or [], kind, eligible, known, T) for t in tags]
    out = {}
    for e in set.intersection(*(set(p) for p in parts)):
        fs = [p[e] for p in parts]
        out[e] = dict(max(fs, key=lambda f: (f.get("filed") or "", f.get("accn") or "")), val=sum(float(f["val"]) for f in fs))
    return out


def _item_substitutes(out, absent, facts, eligible, known, T, years):
    """WO_NC2: for each concept of ITEM_SUBSTITUTES whose exact series lacks a year the valuation reads (the base year; equity also the year
    before; capex and D&A at least SUBSTITUTE_MIN_POOL of the last SUBSTITUTE_WINDOW fiscal years), the first listed tag that covers those years
    replaces the series WHOLE (one tag for every year, never a mix with the exact tag). No tag qualifies: nothing changes. A filed 0 is a value,
    so a year with an exact 0 is not missing. Each value is stamped substitute:<concept>:<taxonomy>:<tag(s)> and, where the tag differs in kind
    from the concept, substitute_scope:<concept>:<scope>. A net tag (scope `net`) counts only while positive (a net outflow) in every year read."""
    ends = sorted(v["end"] for v in (out.get("revenue") or {}).get("values", []))[-SUBSTITUTE_WINDOW:]
    if not ends:
        return
    for concept, cands in ITEM_SUBSTITUTES.items():
        need = {ends[-1], ends[-2]} if concept == "equity" and len(ends) > 1 else {ends[-1]}
        min_years = SUBSTITUTE_MIN_POOL if concept in ("capex", "da") else 1
        if need <= {v["end"] for v in (out.get(concept) or {}).get("values", [])}:
            continue
        for tax, tag, unit, scope in cands:
            got = _item_series(facts, tax, tag, unit, CONCEPTS[concept][0], eligible, known, T)
            if not need <= set(got) or len(set(got) & set(ends)) < min_years:
                continue
            if scope == NET_SCOPE and any(not got[e]["val"] > 0 for e in ends if e in got):
                continue
            name = tag if isinstance(tag, str) else "+".join(tag)
            marks = [f"{SUBSTITUTE_PREFIX}{concept}:{tax}:{name}"] + ([f"{SUBSTITUTE_SCOPE_PREFIX}{concept}:{scope}"] if scope else [])
            vals = [{"end": e, "start": f.get("start"), "value": float(f["val"]), "tag": name, "accn": f.get("accn"), "form": f.get("form"),
                     "filed": f.get("filed"), "stamp": _stamp(f.get("stamp"), *marks)} for e, f in sorted(got.items())][-years:]
            out[concept] = {"tags": [name], "values": vals}
            absent.pop(concept, None)
            break


# F11 (F_SPEC_valuation_menu v1.3): year 1's year-to-date pair. A 10-Q's year-to-date period starts on the first day of its fiscal year; its
# length names the quarter (three, six or nine months, 52/53-week calendars included)
YTD_FORMS = {"10-Q", "10-Q/A"}
YTD_QUARTERS = ((1, 80, 100), (2, 170, 190), (3, 260, 285))     # (quarter, min days, max days) of end - start
YTD_LENGTH_TOL = 7          # days the prior-year leg may differ in length: a 53-week year's extra week, stamped ytd_lengths_differ
YTD_CALENDAR_TOL = 3        # calendar months differ by up to 3 days between years (a leap day, 30- and 31-day months): not stamped


def _days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _quarter(start, end):
    d = _days_between(start, end)
    return next((q for q, lo, hi in YTD_QUARTERS if lo <= d <= hi), None)


def ytd(cf, eligible, known, T, base):
    """Year 1's year-to-date revenue growth and operating margin (F11), from ONE filing: the latest 10-Q effective at T whose fiscal year is
    year 1, i.e. whose year-to-date period starts the day after the base fiscal year's end (`base`: [the base year's revenue value], the
    fiscal year itself chained by annual_facts' 350-380-day rule). Its prior-year leg is the period in the same filing, under the same tag,
    that starts on the base year's first day and has the same length within YTD_LENGTH_TOL days. Revenue: among the revenue tags with both
    legs, the largest current value (annual_facts' rule). Operating income: the first operating-income tag with the current period.
    Returns {"rev_growth", "op_margin", the period, accession and legs, "absent": None or why}; a number that cannot be measured is None
    with its reason, never a default."""
    out = {"rev_growth": None, "op_margin": None, "absent": None, "op_margin_absent": None}
    if not base:
        return dict(out, absent="no base fiscal year of revenue")
    fy0, b0_start = base[0]["end"], base[0]["start"]
    y1_start = (date.fromisoformat(fy0) + timedelta(days=1)).isoformat()
    out.update(fy0=fy0, year1_start=y1_start)
    facts = cf.get("facts") or {}

    def rows(concept):
        """[(priority, tag, fact)] of a concept's 10-Q facts effective at T with a numeric value and a start."""
        got = []
        for pri, (tax, tag, unit) in enumerate(CONCEPTS[concept][1]):
            for f in (((facts.get(tax) or {}).get(tag) or {}).get("units") or {}).get(unit) or []:
                if (f.get("form") in YTD_FORMS and isinstance(f.get("val"), (int, float)) and not isinstance(f.get("val"), bool)
                        and f.get("start") and f.get("end") and _eligible(f, eligible, known, T)[0]):
                    got.append((pri, tag, f))
        return got
    rev = rows("revenue")
    current = [x for x in rev if x[2]["start"] == y1_start and _quarter(x[2]["start"], x[2]["end"])]
    if not current:
        return dict(out, absent="no 10-Q of year 1 effective at T")
    # the latest filing: the latest year-to-date end, then the latest filed date and accession (an amendment of the same quarter)
    pick = max(current, key=lambda x: (x[2]["end"], x[2].get("filed") or "", x[2]["accn"]))[2]
    accn, end = pick["accn"], pick["end"]
    q, days = _quarter(y1_start, end), _days_between(y1_start, end)
    out.update(quarter=q, start=y1_start, end=end, accn=accn, form=pick.get("form"), filed=pick.get("filed"),
               stamp=_eligible(pick, eligible, known, T)[1])

    def legs(rows_):
        """{tag: (priority, current, prior or None, prior fact or None)} in the filing; a tag with two different values for one leg is
        ambiguous and dropped."""
        by = {}
        for pri, tag, f in rows_:
            if f["accn"] != accn:
                continue
            if f["start"] == y1_start and f["end"] == end:
                by.setdefault(tag, [pri, set(), set(), None])[1].add(float(f["val"]))
            elif (f["start"] == b0_start and f["end"] < y1_start and abs(_days_between(f["start"], f["end"]) - days) <= YTD_LENGTH_TOL):
                d = by.setdefault(tag, [pri, set(), set(), None])
                d[2].add(float(f["val"]))
                d[3] = f
        return {t: (d[0], next(iter(d[1])), next(iter(d[2])) if len(d[2]) == 1 else None, d[3]) for t, d in by.items()
                if len(d[1]) == 1 and len(d[2]) <= 1}
    both = {t: v for t, v in legs(rev).items() if v[2] is not None}
    if not both:
        return dict(out, absent=f"no prior-year comparable of the {days}-day year-to-date revenue in {accn}")
    pairs = {t: v for t, v in both.items() if v[1] > 0 and v[2] > 0}
    if not pairs:
        return dict(out, absent=f"year-to-date revenue not positive in {accn}: {sorted((t, v[1], v[2]) for t, v in both.items())}")
    tag, (_, r1, r0, pf) = max(pairs.items(), key=lambda kv: (kv[1][1], -kv[1][0]))
    stamps = [out["stamp"]]
    if len({v[1] for v in pairs.values()}) > 1:
        stamps.append("ytd_revenue_largest_of_tags")
    if abs(_days_between(pf["start"], pf["end"]) - days) > YTD_CALENDAR_TOL:
        stamps.append(f"ytd_lengths_differ: {days} against {_days_between(pf['start'], pf['end'])} days")
    out.update(revenue=r1, revenue_prior=r0, revenue_tag=tag, prior_start=pf["start"], prior_end=pf["end"], rev_growth=r1 / r0 - 1,
               stamp=_stamp(*stamps))
    oi = sorted(legs(rows("operating_income")).items(), key=lambda kv: kv[1][0])
    if not oi:
        return dict(out, op_margin_absent=f"no year-to-date operating income in {accn}")
    out.update(operating_income=oi[0][1][1], operating_income_prior=oi[0][1][2], operating_income_tag=oi[0][0], op_margin=oi[0][1][1] / r1)
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


def _reports_discontinued(cf, eligible, known, T, end):
    """WO_UV2: whether any us-gaap or ifrs-full flow fact under a tag naming a discontinued operation (DISCONTINUED_RX), for the period ending
    `end`, in an annual form effective by T, has a value other than 0."""
    for tax in ("us-gaap", "ifrs-full"):
        for tag, d in ((cf.get("facts") or {}).get(tax) or {}).items():
            if DISCONTINUED_RX.search(tag) and any(
                    f.get("form") in ANNUAL_FORMS and f.get("end") == end and "start" in f and isinstance(f.get("val"), (int, float)) and f["val"] != 0
                    and _eligible(f, eligible, known, T)[0] for rows in (d.get("units") or {}).values() for f in rows):
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
        if not by["nci_equity"] and not by["nci_income"]:
            # coverage A 2026-11-07: no NCI balance and no NCI income filed in any year of the window: nothing is attributed to NCI, so
            # the filed total is the parent's (Visa tags only the total after 2011)
            put("equity", e, t["value"], t["tag"], "equity_total_no_nci_filed", t)
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
    # (5) WO_UV2: pretax income where its tag is absent, or ends before this fiscal year: net income + NCI income + the filed tax provision of
    # the year, only when no discontinued operation is filed for it. Net income plus NCI income is the consolidated profit: where NCI income is
    # not filed for the year, the filed consolidated ProfitLoss is that sum; with neither, NCI counts as none only where no NCI income and no NCI
    # balance is filed in any year (as step 3). A year without a filed provision, or whose ProfitLoss basis is unverified, is not derived
    last_pt = max(by["pretax_income"], default=None)
    for e, v in by["net_income"].items():
        if (last_pt is not None and e <= last_pt) or e not in by["tax_provision"] or v.get("stamp") == "profitloss_basis_unverified":
            continue
        nci_v, plc = by["nci_income"].get(e), by["profit_loss_consolidated"].get(e)
        if _reports_discontinued(cf, eligible, known, T, e):
            continue
        if nci_v is not None:
            profit, tag = v["value"] + nci_v["value"], f"{v['tag']}+{nci_v['tag']}"
        elif plc is not None:
            profit, tag = plc["value"], plc["tag"]
        elif not by["nci_income"] and not by["nci_equity"]:
            profit, tag = v["value"], f"{v['tag']}+no_nci_filed"
        else:
            continue
        put("pretax_income", e, profit + by["tax_provision"][e]["value"], f"{tag}+{by['tax_provision'][e]['tag']}", PRETAX_DERIVED, v)


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


def build(cik, T, *, online, root=None, years=8, substitute_revenue=False, substitute_items=False, ix=True):
    """ix (WO_UV3): the readings of ix_figures may use the newest annual filing's document, read through sec_store (online: fetched when it is
    not stored); False: none is made."""
    cf, subs, prov = fetch(cik, T, online=online, root=root)
    out = annual_facts(cf, subs, T, years=years, substitute_revenue=substitute_revenue, substitute_items=substitute_items,
                       ix=(lambda: ix_figures.load(cik, subs, T, online=online, root=root)) if ix else None)
    out["_provenance"] = dict(prov, facts_version=FACTS_VERSION, T=T.astimezone(timezone.utc).isoformat(), **({"ix_document": out["_ix"]} if "_ix" in out else {}))
    return out
