"""build_fundamentals_history.py — 10-year fundamentals + value-trap battery
from the SEC companyfacts bulk archive.

Reads companyfacts.zip (SEC XBRL frames, ~19.7K CIK files) directly — no
extraction to disk — for every ticker in stocks.json, builds an annual
fundamentals history (revenue, margins, cash flow, balance sheet, shares),
and computes the value-trap battery the audit found missing:

  - Piotroski F-Score (9 checks, reported with how many were computable)
  - Sloan accruals ratio ((NI - CFO) / avg assets; high = earnings not cash)
  - Net share issuance (1y and 3y CAGR of diluted shares)
  - Beneish M-Score (real 8-ratio computation; replaces the old -2.0
    placeholder; missing ratios neutralized and reported, never invented)
  - 10y revenue/operating-margin arrays (mid-cycle inputs for cyclicals)

Outputs:
  public/data/fundamentals_history.json — ticker -> {years: {fy: {...}}}
  public/data/fundamentals_battery.json — ticker -> battery summary
  (battery is the file scoring code should consume; history is the audit trail)

Usage:
  python scripts/build_fundamentals_history.py                 # full universe
  python scripts/build_fundamentals_history.py --limit 50      # smoke run
  python scripts/build_fundamentals_history.py --tickers NVDA,LLY
  python scripts/build_fundamentals_history.py --refresh-one NVDA   # live SEC, patch in place

--refresh-one fetches ONE company's companyfacts live from data.sec.gov (same structure as
one member of the bulk zip, always current), runs the identical extraction, and patches only
that ticker's rows into the four production files (tmp + os.replace; every other ticker
byte-untouched; provenance rides along). LOCAL-ONLY: the patched files must never be
committed — data on git comes only from the cloud's fresh-zip rebuild, which reproduces
the same rows from the same facts and dissolves the patch. Exit 0 = rows updated (or
already identical); non-zero = fetch/extract failure, files untouched.

Data honesty rules: a metric that cannot be computed is null with its gaps
reported — no neutral-looking defaults.
"""

import argparse
import json
import math
import os
import re
import statistics
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

from issuer_securities import non_common_securities

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
STOCKS_JSON = DATA / "stocks.json"
ZIP_PATH = ROOT / "companyfacts.zip"
CIK_MAP_JSON = DATA / "cik_map.json"
HISTORY_JSON = DATA / "fundamentals_history.json"
BATTERY_JSON = DATA / "fundamentals_battery.json"
# TTM lives in its OWN file: fundamentals_history's per-ticker dicts are keyed by fiscal year
# and consumers do int(year) over the keys (valuation_backbone sorts int(y) directly) — a
# non-year key inside would crash them all.
TTM_JSON = DATA / "fundamentals_ttm.json"
QTR_JSON = DATA / "fundamentals_quarterly.json"

SEC_HEADERS = {"User-Agent": "StockScreener/1.0 (contact@example.com)"}
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F")
MAX_YEARS = 12  # keep up to 12 fiscal years

# Tag priority lists (us-gaap first, ifrs-full equivalents after — the two
# namespaces are merged with us-gaap winning on name collisions). Foreign
# filers reporting in non-USD units stay uncovered by design: the USD-only
# unit filter prevents currency-mismatched yields (TSM files in TWD).
DURATION_TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "Revenue", "RevenueFromContractsWithCustomers"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    # net_income: the history resolves it by NI_LADDER (Fix 1a); this list still feeds the TTM
    # freshness bar (newest annual period end), unchanged.
    "net_income": ["NetIncomeLoss", "ProfitLoss",
                   "ProfitLossAttributableToOwnersOfParent"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets",
              "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet",
           "DepreciationAndAmortisationExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense",
            "GeneralAndAdministrativeExpense"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt"],
    # CH-3: primary restricted to the DILUTED tag only. A filer whose BASIC series outlives its
    # Diluted series used to hand the whole field to Basic (INVA +14.9%, 64 live basic-as-diluted
    # cells). The other three tags backfill via FIELD_SPECS["shares_diluted"] below.
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    # Tax fields so fetch_data can derive an effective tax rate for ROIC from SEC data
    # (instead of a daily yfinance stock.financials fetch per ticker — quota killer).
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                      "ProfitLossBeforeTax"],
    "tax_provision": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations",
                      "IncomeTaxExpenseIncome"],
    # CH-8: per-year stock-based compensation. Single-tag primary (ShareBasedCompensation, the
    # CF add-back) so the primary vote cannot re-rank; the other two tags backfill via FIELD_SPECS.
    "sbc": ["ShareBasedCompensation"],
}
INSTANT_TAGS = {
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent", "CurrentAssets"],
    "current_liabilities": ["LiabilitiesCurrent", "CurrentLiabilities"],
    "total_liabilities": ["Liabilities"],
    # equity and cash keep their place in the field order; extract_history resolves them by ladder
    # (resolve_equity_series, resolve_cash_series — Fixes 1a and 2a), never by a vote over these lists
    # (the lists still define the vote's candidate pools: vote_raws in extract_history).
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "Equity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "CashAndCashEquivalents"],
    "lt_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
                    "TradeAndOtherCurrentReceivables"],
    "inventory": ["InventoryNet", "Inventories"],
    "ppe_net": ["PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipment"],
    # Altman-Z B-term (retained earnings / total assets) for the SEC-derived Z in fetch_data.
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"],
    # CH-7: marketable securities. Each list is a LADDER of alternatives for ONE balance-sheet
    # line (first tag to resolve a year wins it) — NEVER summed (ADI files 1,153M under two tags
    # for the same line). st and lt kept SEPARATE, not merged: 80.6% of AAPL's securities book is
    # noncurrent, not one-year liquidity. Un-suffixed totals, Investments, LongTermInvestments,
    # CashCashEquivalentsAndShortTermInvestments are REFUSED (fiduciary/insurance float, cash
    # double-count) — see the refusal block below.
    "st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                       "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                       "OtherShortTermInvestments", "HeldToMaturitySecuritiesCurrent"],
    "lt_investments": ["MarketableSecuritiesNoncurrent",
                       "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
                       "HeldToMaturitySecuritiesNoncurrent"],
}
SHARES_UNIT = "shares"

# Fields excluded from the accession-coverage vote AND the year-row union (CH-7 + CH-9).
# The accession vote scores accessions by field coverage; letting these new instant fields vote
# rewrote 11 pre-existing cells on RC/CPT in measurement. They still RECEIVE the chosen
# accession's correction in the row-build loop — they just do not get a say in WHICH accession
# wins, and a new-field-only year bin can never evict an existing year-row.
VOTE_EXCLUDED_FIELDS = ("st_investments", "lt_investments", "sbc",
                        "debt_lt_noncurrent", "debt_current", "short_term_borrowings_separate",
                        "finance_lease_liability", "operating_lease_liability", "borrowings_total",
                        "goodwill", "intangibles_ex_goodwill", "amortization_intangibles",
                        "net_income_incl_nci", "equity_incl_nci", "cash_restricted",
                        "customer_money_assets", "customer_money_liabilities", "insurance_reserves",
                        "eps_diluted", "net_income_available_to_common_diluted", "preferred_dividends")


def get_cik_map():
    """ticker -> 10-digit CIK string, cached locally."""
    if CIK_MAP_JSON.exists():
        try:
            cached = json.loads(CIK_MAP_JSON.read_text(encoding="utf-8"))
            if cached.get("map"):
                return cached["map"]
        except (OSError, json.JSONDecodeError):
            pass
    print("Fetching SEC CIK mapping ...")
    resp = requests.get("https://www.sec.gov/files/company_tickers.json",
                        headers=SEC_HEADERS, timeout=60)
    resp.raise_for_status()
    mapping = {e["ticker"]: str(e["cik_str"]).zfill(10) for e in resp.json().values()}
    CIK_MAP_JSON.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "map": mapping}), encoding="utf-8")
    return mapping


# ── Scale-error defence ──────────────────────────────────────────────────────────────────────
# SEC filings are not internally consistent. The SAME fiscal period is sometimes reported twice
# with values a clean power of 1000 apart, and since the corrupt value is usually in the LATER
# filing, "most recent wins" picks it every time. Verified against the raw companyfacts:
#     COHR  FY2023 D&A          681,687,000 (10-K)   vs      681,687,000,000 (later 10-K)
#     INVE  FY2021 NetIncome      1,620,000 (10-K)   vs    1,620,000,000,000 (10-K/A)
#     BKTI  FY2020 shares            12,561          and           12,561,000
# One period cannot have two true values 1000x apart, so this is provable corruption rather than
# a judgement call — unlike INVE's genuine restatements, which move a number by 0.3%.
#
# Measured impact before this fix: 672 year-over-year ~1000x transitions across 451 tickers,
# 49% of them in shares_diluted.
#
# NOTE what this deliberately does NOT do: reject values merely for being large relative to the
# series. That was tested and is unsafe — at a 10x bar it flags NVDA's real $120bn net income
# (29x), AMZN's real 20:1 split (21.5x), AMD's Xilinx equity (22.3x) and CRM's margin expansion
# (20.7x). A magnitude filter silently deletes the best names in the book. Only provable
# contradictions and clean power-of-1000 series breaks are touched.
SCALE_STEPS = (1e3, 1e6, 1e9)


def _pow1000_ratio(a, b):
    """Return the power-of-1000 step if |a|/|b| is ~one, else None."""
    if not a or not b:
        return None
    r = abs(a) / abs(b)
    for p in SCALE_STEPS:
        if 0.7 * p <= r <= 1.4 * p:
            return p
    return None


def _pick_consistent(cands, reference):
    """From [(filed, val), ...] for ONE period, pick the value consistent with `reference`.

    Falls back to most-recent when there is no conflict or no reference to judge against —
    identical to the old behaviour, so nothing changes for the 99% that are clean.
    """
    vals = {v for _, v in cands if v is not None}
    if len(vals) < 2:
        return max(cands, key=lambda c: c[0] or "")[1]
    hi, lo = max(vals, key=abs), min(vals, key=abs)
    if _pow1000_ratio(hi, lo) is None:          # ordinary restatement -> keep most recent
        return max(cands, key=lambda c: c[0] or "")[1]
    if reference is None:                        # conflict but nothing to anchor on
        return lo                                # the inflated one is the error in every case seen
    return min(vals, key=lambda v: abs(math.log10(max(abs(v), 1e-9) / max(abs(reference), 1e-9))))


def _series_median(s):
    """Median absolute magnitude of a {year: value} series (nonzero values), or None."""
    vals = [abs(x) for x in s.values() if x]
    return statistics.median(vals) if vals else None


def _normalise_series_scale(series):
    """Rescale years whose value is a clean power of 1000 off the MOST RECENT year.

    Catches the case a per-period contradiction cannot: a company that reported in THOUSANDS for
    years and then switched to units, where each individual year has only one value and nothing
    contradicts it (BKTI reported shares in thousands through FY2022, units from FY2023). The most
    recent filing defines current units, so it is the anchor.
    """
    if len(series) < 3:
        return series
    yrs = sorted(series)
    anchor_y = yrs[-1]
    anchor = series[anchor_y]
    if not anchor:
        return series
    # median magnitude of years already on the anchor's scale, to avoid anchoring on an outlier
    same = [abs(series[y]) for y in yrs if series[y] and _pow1000_ratio(series[y], anchor) is None]
    ref = statistics.median(same) if len(same) >= 2 else abs(anchor)
    out = dict(series)
    for y in yrs:
        v = series[y]
        if not v:
            continue
        p = _pow1000_ratio(ref, v)               # value is p times SMALLER than the current scale
        if p:
            out[y] = v * p
    return out


# -- FIELD SPECS (2026-08-20) -------------------------------------------------------------
# Curated against companyfacts.zip over the 269-ticker book (2,917 ticker-years); every proposal
# adversarially re-verified against filed cash-flow statements before landing here.
#
# WHY THIS EXISTS. annual_duration_series picks ONE winning tag per field -- most-recent-latest-
# year, then coverage -- and never mixes tags. That is right per tag (see its docstring: AAPL's
# SalesRevenueNet has 11 old years ending 2017) but it silently drops years the WINNER lacks even
# when another ALREADY-MAPPED tag covers them. Measured: that single effect is ~85% of the
# revenue / pretax / ocf nulls. Adding tag names does nothing for it; stitching does.
#
# THREE MECHANISMS, strict order:
#   COMBINED        priority list, each usable ALONE. Primary = today's winner (unchanged, so
#                   every year currently filled stays byte-identical); the rest BACKFILL only
#                   years the primary lacks.
#   COMPONENT_SLOTS at most ONE tag per slot, summed ACROSS slots, and only if EVERY slot
#                   resolves. A partial sum is not an approximation, it is a wrong number:
#                   amortisation-slot alone runs a median 0.222 of true D&A, depreciation-slot
#                   alone 0.925 (n=1822 paired observations).
#   LONE_DEPRECIATION_ALLOWLIST  da only. A filer whose depreciation tag IS its entire D&A line,
#                   verified against the filed statement. NEVER inferred: NVS files
#                   DepreciationPropertyPlantAndEquipment 1,208M against a true FY2021 D&A of
#                   4,949M (-76%). Adding a ticker requires reading its cash-flow statement.
FIELD_SPECS = {
 "da": {
  "COMBINED": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
               "DepreciationAmortizationAndAccretionNet",
               "DepreciationAndAmortisationExpense",                 # ifrs-full
               "AdjustmentsForDepreciationAndAmortisationExpense",   # ifrs-full
               "OtherDepreciationAndAmortization"],
  "COMPONENT_SLOTS": [
    ["Depreciation", "DepreciationExpense", "AdjustmentsForDepreciationExpense",
     "DepreciationPropertyPlantAndEquipment", "DepreciationNonproduction"],
    ["AmortizationOfIntangibleAssets", "AdjustmentForAmortization", "AmortisationExpense",
     "AdjustmentsForAmortisationExpense", "AmortisationIntangibleAssetsOtherThanGoodwill",
     "FiniteLivedIntangibleAssetsAmortizationExpense",
     "AmortizationOfAcquiredIntangibleAssets"]],
  "LONE_DEPRECIATION_ALLOWLIST": {"GOOG", "GOOGL", "UNP"},
  # CH-5 (SHIPPED, operator-approved 2026-08-21): OtherDepreciationAndAmortization is POLYSEMOUS —
  # the broadest CF D&A line at ABNB, but "other D&A EXCLUDING acquisition-intangible amortization"
  # at AMD (shipped -75%) and an amortization ALIAS at LIVN. Gate it to ABNB so AMD/LIVN resolve
  # from component sums. AMD 2025 D&A -75% -> -6% (feeds base_cf live). DECLARED trade: LIVN 2020
  # 38,312,000 -> 29,031,000 (worse) + 4 currently-correct cells nulled (AMD 2020/21, LIVN 21/22) —
  # latest-FY correctness outranks historical completeness.
  "TICKER_GATED_TAGS": {"OtherDepreciationAndAmortization": {"ABNB"}},
  # PER-FILER DENIES (2026-08-21, each adjudicated by READING the filed cash-flow statement —
  # never from tag plausibility):
  #   FIX: its "DepreciationAndAmortization" tag IS the depreciation line mislabeled — filed FY2025
  #        CF statement (accn 0001104659-26-017530, R7) shows TWO lines: "Depreciation expense"
  #        62,379k (== the tag's 62,400k rounded) and "Amortization of identifiable intangible
  #        assets" 79,580k, filed separately under AmortizationOfIntangibleAssets. Denying the
  #        mislabeled tag lets the component slots sum both lines (both cover 2009-2025):
  #        FY2025 141,959k vs the 62,400k that shipped (-56%).
  #   ABNB: DepreciationDepletionAndAmortization is its depreciation line (2021: 85.6M == the
  #        separate Depreciation tag's 86M), NOT the CF total. Filed FY2022 10-K CF statement
  #        (accn 0001559720-23-000003, R8): "Depreciation and amortization" 81/138/126 ($M,
  #        2022/2021/2020) == OtherDepreciationAndAmortization exactly. Denying the partial
  #        primary lets the ABNB-gated OtherD&A cover 2019-2024. FY2025: null is CORRECT — the
  #        FY2025 10-K's CF statement carries no D&A line at all (folded into "Other, net").
  "TICKER_DENY_TAGS": {"DepreciationAndAmortization": {"FIX"},
                       "DepreciationDepletionAndAmortization": {"ABNB"}},
 },
 # BANK REVENUE IS NET REVENUE (2026-10-06, operator). A bank files no single revenue line, so the listed
 # tags below mean different things at different banks: at many of them
 # RevenueFromContractWithCustomerExcludingAssessedTax is only the ASC 606 FEE slice of the income
 # statement. Measured on the shipped file (screener-publish, 2026-10-06), over financial filers that file
 # both InterestIncomeExpenseNet (NII) and NoninterestIncome and ship a revenue: 102 ship a revenue below
 # 0.5x of (NII + noninterest income), only 32 within 2% of it, 14 above it (gross-ish). FXNC FY2025 ships
 # 14,290,000 against a net revenue of 90,264,000; RF FY2021 104,000,000 against 6,438,000,000. 66 of the
 # 102 are scored; PEBO is nominated. Where a filer files a listed revenue total AND both components for
 # the same annual period (companyfacts.zip), the total equals NET (NII + noninterest income) in 385 cases,
 # GROSS (InterestAndDividendIncomeOperating + noninterest income) in 90, NEITHER in 782: no listed tag
 # carries one meaning across banks. And 215 financials with revenue null in their latest year file both
 # components for it.
 # THE RULE. A filer is a BANK P&L FILER (bank_net_revenue_filer) when some annual period end has all
 # three of: (a) InterestIncomeExpenseNet, (b) NoninterestIncome, and (c) at least one of
 # InterestAndDividendIncomeOperating, InterestIncomeOperating, InterestExpenseDeposits. (a)+(b) alone
 # are not a bank: ZOOZ, LGL, ILLR and LEXX, operating companies (EV charging, instruments, software,
 # biotech), tag their NON-operating interest and other income with them, and net-revenue-by-definition
 # would replace their real revenue with it (ZOOZ FY2025 247,000 -> -4,807,000). (c) is the income
 # statement of a lender: it excludes all four and keeps the 323 Financial Services / mortgage-REIT
 # qualifiers plus LC and CASS (bank holding companies); it drops AGNC (null anyway), AROW, ACRE and SACH,
 # which fall back to the listed tag exactly as before (a missed lender keeping today's value is
 # acceptable; a wrong number on an operating company is not). The test comes from the filings, never from
 # the vendor sector. InterestAndFeeIncomeLoansAndLeases was considered and REJECTED as (c): ILLR
 # (software) files it. For a qualifying filer revenue is, by definition, NET revenue:
 # InterestIncomeExpenseNet + NoninterestIncome (the "total net revenue" of a bank income statement), in
 # the annual history (extract_history), the TTM (ttm_snapshot) and the quarterly snapshot
 # (quarterly_snapshot) alike; a listed tag is REFUSED for it in every year and every output, never mixed
 # (an ASC 606 slice in one year beside net revenue in the next would manufacture growth). A year missing
 # either component is null. Any other filer is untouched; this spec's lists below still serve them.
 "revenue": {"COMBINED": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                          "RevenueFromContractWithCustomerIncludingAssessedTax",
                          "SalesRevenueNet", "Revenue", "RevenueFromContractsWithCustomers"],
             "COMPONENT_SLOTS": []},
 # Fix 1a follow-up: `net_income` itself is resolved by NI_LADDER, never from this spec. The spec is
 # kept unchanged ONLY so the accession vote and the bin-end anchor keep reading the candidate pool
 # the vote read before the scope fix (vote_raws in extract_history): the filing calendar and the
 # choice of a row's accession are properties of the filings, not of the field's accounting scope.
 "net_income": {"COMBINED": ["NetIncomeLoss", "ProfitLoss"], "COMPONENT_SLOTS": []},
 "ocf": {"COMBINED": ["NetCashProvidedByUsedInOperatingActivities",
                      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                      "CashFlowsFromUsedInOperatingActivities",
                      "CashFlowsFromUsedInOperatingActivitiesContinuingOperations"],
         "COMPONENT_SLOTS": []},
 "capex": {"COMBINED": ["PaymentsToAcquirePropertyPlantAndEquipment",
                        "PaymentsToAcquireProductiveAssets",
                        "PaymentsToAcquireOtherPropertyPlantAndEquipment",   # CH-4: gated -> LLY
                        "PaymentsToAcquireOtherProductiveAssets"],           # CH-4: gated -> ROP
           "COMPONENT_SLOTS": [],
           # CH-4: these two tags are POLYSEMOUS across filers — a real capex line at LLY/ROP
           # (verified vs dPPE+D&A within 2.5%), but <1% of actual PP&E additions at GSAT. So
           # they BACKFILL ONLY the named tickers; ungated they would ship GSAT a capex 1/130th
           # of truth and a matching inflated FCF. Primary vote (DURATION_TAGS["capex"]) unchanged.
           "TICKER_GATED_TAGS": {"PaymentsToAcquireOtherPropertyPlantAndEquipment": {"LLY"},
                                 "PaymentsToAcquireOtherProductiveAssets": {"ROP"}},
           # 2026-09-28: years every mechanism above leaves empty are backfilled from the filing's
           # own investing section when it PROVES the total -- see resolve_capex_by_closure.
           "INVESTING_CLOSURE": True,
           # 2026-09-28: a FILLED year is replaced by the row's own proof only under
           # _replacement_allowed (anchored, specific PP&E lines only, no conflicting filing).
           "CLOSURE_REPLACES_FILLED": True},
 "operating_income": {"COMBINED": ["OperatingIncomeLoss",
                                   "ProfitLossFromOperatingActivities"],
                      "COMPONENT_SLOTS": []},
 "pretax_income": {"COMBINED": [
   "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
   "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
   "ProfitLossBeforeTax"],
   "COMPONENT_SLOTS": []},
 # CH-3: deliberate PRIMARY-VOTE change (diluted tag is primary via DURATION_TAGS; the other three
 # BACKFILL only). Justified by the 0-lost corpus gate, not by plausibility. The 12 filers whose
 # only tag is WeightedAverageShares (undifferentiated) stay unchanged — disclosure via the CH-6
 # tag record, not substitution. The winning tag per cell rides CH-6's provenance runs.
 "shares_diluted": {"COMBINED": ["WeightedAverageNumberOfDilutedSharesOutstanding",
                                 "WeightedAverageNumberOfSharesOutstandingBasic",
                                 "WeightedAverageShares", "AdjustedWeightedAverageShares"],
                    "COMPONENT_SLOTS": []},
 # CH-8: SBC. Primary = ShareBasedCompensation (best match to the APIC equity-statement witness,
 # 85.3%); the other two BACKFILL only (Allocated is a COMPONENT at AIT, 7.7x mis-tag at SIMO,
 # sign-flipped at INTU — never primary). Backfill priority is (-max_year, -coverage), not list order.
 "sbc": {"COMBINED": ["ShareBasedCompensation", "AdjustmentsForSharebasedPayments",
                      "AllocatedShareBasedCompensationExpense"],
         "COMPONENT_SLOTS": []},
}
# Tags deliberately REFUSED, recorded so nobody re-adds them:
#   Accumulated*                     balance-sheet stocks, not period flows
#   *ImpairmentLoss*                 bundles impairment (AZN 6,530 vs 5,733 D&A-only)
#   *NextTwelveMonths / Future*      forward-looking disclosure, not a period figure
#   AmortizationOfFinancingCosts     financing cost, not D&A
#   DepreciationRightofuseAssets     alone runs 0.308 of true D&A and is already inside most
#                                    filers' depreciation line -> double-count
#   PaymentsToAcquireBusinesses*     M&A, not capex
#   ...BeforeIncomeTaxesDomestic     tax-footnote US-only geographic COMPONENT, not the total.
#                                    Never primary (absent from DURATION_TAGS) but won BACKFILL
#                                    because the footnote series files later than the income
#                                    statement and backfill sorts by (-max_year, -coverage).
#                                    Domestic + Foreign == Total in 54/54 checked filer-years;
#                                    GOOG FY2014 shipped 8,894M (Domestic) vs true 17,259M
#                                    (Domestic 8,894 + Foreign 8,365). Removed -> 165 cells
#                                    corrected, 8 NHC 2014-2021 correctly nulled (NHC files no
#                                    Foreign leg and no total pre-2022). No allowlist: none of
#                                    the 8 is a latest FY and no pretax allowlist mechanism exists.
#   Investments (us-gaap)            fiduciary/insurance float, not corporate securities:
#                                    PAYC 5,507M = client funds (LiabilitiesCurrent 5,368.4M);
#                                    PCTY 3,482,421,000; HG 5,026,660,000 = 144.6% of mcap; UVE
#                                    1,532,604,000 (insurer). Not st/lt_investments.
#   LongTermInvestments              polysemous, opposite economics: GE 38,788M insurance run-off
#                                    (LiabilityForFuturePolicyBenefits 35,438M) vs INVA 404,497,000
#                                    genuine AFS debt. No rule separates them; INVA declared false-neg.
#   AvailableForSaleSecuritiesDebtSecurities (un-suffixed total)
#                                    double-counts cash: BMRN total - (current+noncurrent) == cash
#                                    to the dollar; above current-asset headroom in 81 of 487 t-y.
#   OtherLongTermInvestments / un-suffixed MarketableSecurities / CashCashEquivalentsAndShortTermInvestments
#                                    GOOG OtherLTI 68,687M is "Non-marketable securities"; NHC
#                                    MarketableSecurities 303,462,000 > its current headroom 216M;
#                                    CCESTI contains cash by definition. Ladder tags NEVER summed
#                                    (ADI 1,153M filed under two tags for one line; sum-vs-total p10=0.133).
#   ifrs financial-asset families    note-level grab-bags (NVS OtherCurrentFinancialAssets 1,998M ->
#                                    155M in one year, cash flat) — 13/14 live IFRS filers None (STOP).
#   AllocatedShareBasedCompensationExpense (as SBC primary)
#                                    backfill-only: COMPONENT at AIT (7,289,000 vs filed total
#                                    12,002,000); 7.7x superset/mis-tag at SIMO (203,305,000 vs
#                                    filed 26,283,000); SIGN-FLIPPED at INTU 2008-2010.
#   ExpenseFromSharebasedPaymentTransactionsWithEmployees (as SBC)
#                                    P&L expense, not the CF add-back (NVS 1,330M vs 1,096M).
#   IncreaseDecreaseThroughSharebasedPaymentTransactions (as SBC)
#                                    equity movement, not SBC expense (IHG 67M vs 47M).
#   Total_Debt (vendor) / DebtLongtermAndShorttermCombinedAmount / ifrs Borrowings (as a RULE)
#                                    no single definition: vendor reproduces WITH leases at 56
#                                    names, WITHOUT at 23; AZN Borrowings INCLUDES IFRS-16 leases,
#                                    SAP/NVS EXCLUDE them (all identities exact). Components only.


# -- CAPEX BY INVESTING-SECTION CLOSURE (2026-09-28, reviewer design) -----------------------------
# WHY. 1,616 of 5,603 names (28.8%; local companyfacts.zip of 2026-08-07) ship no latest-FY capex, and
# 397 of them file their capital-spending line under a concept FIELD_SPECS does not map (oil and gas,
# real estate, ifrs, "other" PP&E). The same concept is a TOTAL at one filer and a COMPONENT at
# another: ASC files PaymentsToAcquireOtherProductiveAssets 284,000 against a 121,003,000 investing
# outflow (the CH-4 GSAT trap again); AR's three standard capex lines leave 150,087,000 of its
# investing section unexplained. Adding tags to COMBINED would ship both. No tag list and no magnitude
# rule separates a total from a component. The filing's own investing section does.
# THE PROOF. For one accession + one ~annual period, the filed investing total must be reproduced
# EXACTLY (integer equality, no tolerance) by a signed subset of the SAME filing's standard-concept
# investing lines. companyfacts carries no company-extension concept, so a section that holds an
# extension line cannot close and stays unproven -> null (null beats wrong). A closing subset is the
# face of the statement: its capex lines are disjoint (no double count) and complete (no component
# passes as the total).
# MEASURED (full universe): 27,469 proven filing-periods; deleting any one face line (104,408 trials)
# or two (62,974) never proved a different capex. The PP&E roll-forward (dPPE_net + D&A) is NOT a
# proof: within 2.5% of the proven total in only 10.7% of 18,338 filer-years, and it accepts a known
# component 2.1% of the time.
# BACKFILL ONLY: applied inside extract_history's row loop, to a row whose capex every FIELD_SPECS
# mechanism left null; the value never enters `series` or `raws`, so it cannot vote in the accession
# rule or move any other cell. It must also sit on the row's own period (_near_ref, 14 days).
# Every concept below was classified by reading its definition and its use in closing subsets across
# the universe; an unlisted concept in the investing grammar is POISON (a subset using it proves nothing).
INVESTING_TOTAL_TAGS = ("NetCashProvidedByUsedInInvestingActivities",
                        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
                        "CashFlowsFromUsedInInvestingActivities",
                        "CashFlowsFromUsedInInvestingActivitiesContinuingOperations")
# Additions to the filer's own PP&E-type assets: SUMMED. Software and intangibles are NOT here (the
# field is PP&E purchases, as PaymentsToAcquirePropertyPlantAndEquipment is; separately presented
# capitalized software stays out, exactly as it does for the primary tag today).
CLOSURE_CAPEX_LINES = frozenset({
    "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment", "PaymentsToAcquireOtherProductiveAssets",
    "PaymentsToAcquireMachineryAndEquipment", "PaymentsToAcquireFurnitureAndFixtures",
    "PaymentsToAcquireBuildings", "PaymentsToAcquireLand", "PaymentsToAcquireLandHeldForUse",
    "PaymentsForConstructionInProcess", "PaymentsForFlightEquipment", "PaymentsToAcquireEquipmentOnLease",
    "PropertyPlantAndEquipmentAdditions",
    "PaymentsToAcquireMiningAssets", "PaymentsToAcquireOilAndGasPropertyAndEquipment",
    "PaymentsToExploreAndDevelopOilAndGasProperties", "PaymentsToAcquireOilAndGasEquipment",
    "PaymentsForCapitalImprovements", "PaymentsToDevelopRealEstateAssets",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",                 # ifrs-full
    "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
    "PurchaseOfMiningAssets",
})
# REMOVED 2026-09-28 (review of the backfill), now POISON because the grammar leaves them unlisted --
# ifrs concepts whose meaning depends on the filer's industry, with no filed fact to tell them apart:
#   PaymentsForDevelopmentProjectExpenditure  IAS 38 capitalized DEVELOPMENT (an intangible): SANG and VS
#       file IntangibleAssetsUnderDevelopment beside it; VALE uses it for mine projects.
#   PurchaseOfExplorationAndEvaluationAssets, PaymentsForExplorationAndEvaluationExpenses  IFRS 6 E&E:
#       exploration capex at ASM/CRML, stream and royalty acquisitions at TFPM (RGLD's us-gaap equivalent is
#       refused by ACQ-1/ACQ-2), a mis-tag at MDXH (a diagnostics company, 19,658,000).
#   A subset using any of the three proves nothing (null beats wrong).
# PropertyPlantAndEquipmentAdditions is a PP&E ROLL-FORWARD TOTAL, not a cash line: it may stand in for
# the whole capex (CHDN FY2025: 274,900,000 == its 70,200,000 + 204,700,000 face lines) but is never
# counted BESIDE another capex line -- AN FY2016 "closes" as 244,500,000 cash + 253,200,000 additions =
# 497,700,000, identically in all three filings that carry the period; L FY2021 482,000,000 + 489,000,000.
CLOSURE_TOTAL_ONLY_LINES = frozenset({"PropertyPlantAndEquipmentAdditions"})
# Acquisition of existing property / mineral interests -> the same-family development/improvement
# lines. ACQ-1: when a closing subset also holds a same-family development line, the acquisition line
# is the SEPARATELY PRESENTED acquisitions line and is excluded (FANG FY2025: development 3,523M kept,
# property acquisitions 5,938M excluded; PR 1,979.6M, CRGY 951.0M -- the companies' own capex bases).
# ACQ-2: see _og_acquisition_line_is_additions. Otherwise the line's role is unproven -> null
# (NNN 937.1M of real-estate acquisitions is not capex; CLDT's lone line may be improvements).
_OG_DEV = frozenset({"PaymentsToExploreAndDevelopOilAndGasProperties", "PaymentsToAcquireOilAndGasPropertyAndEquipment"})
_MINING_DEV = frozenset({"PaymentsToAcquireMiningAssets", "PurchaseOfMiningAssets"})
_RE_DEV = frozenset({"PaymentsForCapitalImprovements", "PaymentsToDevelopRealEstateAssets"})
CLOSURE_ACQUISITION_LINES = {
    "PaymentsToAcquireOilAndGasProperty": _OG_DEV,
    "PaymentsToAcquireMineralRights": _OG_DEV | _MINING_DEV,
    "PaymentsToAcquireRoyaltyInterestsInMiningProperties": _MINING_DEV,
    "PaymentsToAcquireTimberlands": frozenset(),
    "PaymentsToAcquireRealEstate": _RE_DEV, "PaymentsToAcquireCommercialRealEstate": _RE_DEV,
    "PaymentsToAcquireResidentialRealEstate": _RE_DEV, "PaymentsToAcquireRealEstateHeldForInvestment": _RE_DEV,
    "PaymentsToAcquireHeldForSaleRealEstate": _RE_DEV, "PaymentsToAcquireAndDevelopRealEstate": _RE_DEV,
    "PaymentsToAcquireRealEstateAndRealEstateJointVentures": _RE_DEV, "PurchaseOfInvestmentProperty": _RE_DEV,
}
# Net lines hide the gross capex inside them: POISON.
_CLOSURE_POISON_NET = frozenset({"PaymentsForProceedsFromProductiveAssets",
                                 "PaymentsForProceedsFromRealEstateHeldforinvestment",
                                 "PaymentsForProceedsFromNuclearFuel", "PaymentsForProceedsFromRemovalCosts",
                                 "PaymentsForProceedsFromTenantAllowance"})
# Investing grammar (which concepts may be a line of the section, and their sign). Financing and
# operating concepts never enter it -- every extra candidate is a chance for a coincidental closure.
_INV_EXCLUDE = re.compile(
    r"(Financing|OperatingActivit|^ProceedsFromIssuance|^ProceedsFromRepayment|^RepaymentsOf|^ProceedsFromRelatedPartyDebt|"
    r"TreasuryS|^PaymentsForOrigination|^PaymentsOf|^PaymentsForRepurchase|^PaymentsToMinority|^PaymentsRelatedToTax|"
    r"^ProceedsFromPaymentsToMinority|IncurredButNotYetPaid|^PaymentsForRent|^PaymentsForFees|^PaymentsForRestructuring|"
    r"^PaymentsForLoss|^PaymentsForUnderwriting|^PaymentsForCommissions|^PaymentsForBrokerage|^PaymentsForLegal|"
    r"^PaymentsForEnvironmental|^PaymentsForPostemployment|^PaymentsForProvision|^PaymentsForPurchaseOfInvestmentOperating|"
    r"OrRedeemEntitysShares|SoldUnderAgreementsToRepurchase|LoansHeldForSale|LoansHeldforsale)")
_INV_NET_OUT = re.compile(r"^PaymentsForProceedsFrom")                      # value > 0 = net outflow
_INV_NET_IN = re.compile(r"^(ProceedsFromPaymentsFor|NetCashProvidedByUsedInInvestingActivitiesDiscontinued|"
                         r"CashProvidedByUsedInInvestingActivitiesDiscontinued|OtherInflowsOutflowsOfCashClassifiedAsInvesting|"
                         r"CashFlowsFromUsedInInvestingActivitiesDiscontinued|CashFlowsFromUsedInDecreaseIncrease)")
_INV_OUT = re.compile(r"^(PaymentsToAcquire|PaymentsForAcquire|PaymentsToDevelop|PaymentsToExplore|PaymentsForCapitalImprovements|"
                      r"PaymentsForConstructionInProcess|PaymentsForSoftware|PaymentsForFlightEquipment|PaymentsForDeposit|"
                      r"PaymentsForDerivativeInstrumentInvesting|PaymentsForHedgeInvesting|PaymentsToFundLongtermLoans|"
                      r"PaymentForAcquisition|PaymentsForPurchaseOf|PurchaseOf|CashFlowsUsedInObtainingControl|"
                      r"CashAdvancesAndLoansMadeTo|PaymentsForDevelopmentProject|PaymentsForExplorationAndEvaluation|"
                      r"CashDivestedFromDeconsolidation|PaymentsForContributionsTo|PaymentsForAdvanceTo|"
                      r"PaymentForContingentConsiderationLiabilityInvesting|PaymentsForInvestment|IncomeTaxesPaidRefundClassifiedAsInvesting|"
                      r"OtherCashPaymentsToAcquire|PaymentsForLeasingCosts|IncreaseDecreaseInRestrictedCash$|"
                      r"PropertyPlantAndEquipmentAdditions$|InterestPaidCapitalized$)")
_INV_IN = re.compile(r"^(ProceedsFrom(Sale|Sales|Maturit|Collection|Divestiture|Disposal|Disposition|Deconsolidation|Liquidation|"
                     r"Redemption|InsuranceSettlementInvesting|DerivativeInstrumentInvesting|HedgeInvesting|EquityMethodInvestment|"
                     r"DistributionsReceived|LimitedPartnership|InterestReceived|DividendsReceived|GovernmentGrants|"
                     r"RealEstateAndRealEstateJointVentures|PrincipalRepaymentsOnLoansAndLeasesHeldForInvestment|LifeInsurancePolicies|"
                     r"DecommissioningFund|PreviousAcquisition|ReturnOfCapital|IncomeTaxRefundsInvesting|AssetSales|Divestitures)|"
                     r"CashAcquiredFromAcquisition|CashAcquiredInExcessOfPaymentsToAcquireBusiness|CashFlowsFromLosingControl|"
                     r"CashReceiptsFromRepaymentOfAdvancesAndLoans|InterestReceivedClassifiedAsInvesting|DividendsReceivedClassifiedAsInvesting|"
                     r"ReturnOfCapital|RepaymentOfNotesReceivable)")
# Certainly-not-PP&E investing lines (financial assets, businesses, intangibles/software, other/net).
_INV_NONCAPEX = re.compile(
    r"(Securit|Investments?(?!Property)|Business|Subsidiar|Affiliate|JointVenture|EquityMethod|Associates|Loan|"
    r"LeaseReceivable|LeasesHeldForInvestment|Notes|Receivable|Intangible|Software|InProcessResearch|Derivative|Hedge|"
    r"LifeInsurance|FederalHomeLoanBank|FederalReserve|CertificatesOfDeposit|DepositsInBanks|InterestBearingDeposits|"
    r"DepositsWithOtherInstitutions|OtherDeposits|MortgageDeposits|DepositOnLoan|DepositsOnRealEstateAcquisitions|"
    r"MortgageServicingRights|Crypto|RestrictedCash|RestrictedInvestments|FinancialInstruments|FinancialAssets|"
    r"Partnership|InterestIn|ContingentConsideration|OtherInvestingActivities|Discontinued|RetainedInterest|"
    r"ManagementContractRights|PolicyLoans|DelayedTaxExemptExchange|FederalFunds|AgreementsToResell|TrustPreferred|"
    r"IncomeTaxesPaidRefund|AdvanceTo|LoansMadeTo|CashDivested|PreviousAcquisition|ObtainingControl|LosingControl|"
    r"CashAcquired|CashReceipts|InterestReceived|DividendsReceived|ReturnOfCapital|ShorttermDeposits|DecommissioningFund|"
    r"InvestmentProjects|ContributionsTo|OtherInflowsOutflows|InstrumentsOfOtherEntities|InterestEarningAssets|DebtRetirements)")
_CI_DEVELOPMENT = "CostsIncurredDevelopmentCosts"
_CI_ACQUISITION = "CostsIncurredAcquisitionOfOilAndGasProperties"
_CI_ACQUISITION_PARTS = ("CostsIncurredAcquisitionOfProvedOilAndGasProperties",
                         "CostsIncurredAcquisitionOfUnprovedOilAndGasProperties")
CLOSURE_MAX_LINES = 24              # meet-in-the-middle over <= 2^12 x 2^12; larger sections stay unproven
# REPLACEMENT (2026-09-28). A FILLED capex is replaced by the row's own proven total only when the
# proof ADDS lines of a concept that is PP&E by its own definition. The three generic concepts stay out:
# beside a PP&E line they are, by construction, some OTHER category -- LTRX FY2025 adds 6,458,000 of
# "other productive assets" while its gross PP&E moved 11,328,000 -> 11,530,000; TONX FY2025's 295,000,000
# is a token purchase. None of 387 such lines has a same-value twin elsewhere in its filing that would
# say what it is, so they cannot be proven PP&E and the shipped value stays.
CLOSURE_REPLACE_LINES = (CLOSURE_CAPEX_LINES - CLOSURE_TOTAL_ONLY_LINES - {
    "PaymentsToAcquireOtherProductiveAssets", "PaymentsToAcquireProductiveAssets",
    "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
}) | {"PaymentsToAcquireOilAndGasProperty"}      # counted in a proof only via ACQ-2
CLOSURE_MAX_SOLUTIONS = 20000       # a truncated enumeration cannot show every solution agrees -> unproven


def _investing_sign(concept):
    """+1 inflow, -1 outflow, 0 = not a line of the investing grammar."""
    if concept in INVESTING_TOTAL_TAGS or _INV_EXCLUDE.search(concept):
        return 0
    if _INV_NET_OUT.match(concept):
        return -1
    if _INV_NET_IN.match(concept):
        return 1
    if _INV_OUT.match(concept):
        return -1
    if _INV_IN.match(concept):
        return 1
    return 0


def _investing_class(concept):
    """'capex' | 'acquisition' | 'noncapex' | 'poison' for a concept inside the grammar."""
    if concept in CLOSURE_CAPEX_LINES:
        return "capex"
    if concept in CLOSURE_ACQUISITION_LINES:
        return "acquisition"
    if concept in _CLOSURE_POISON_NET:
        return "poison"
    if concept.startswith(("ProceedsFrom", "CashAcquired", "CashReceipts", "CashFlowsFromLosingControl",
                           "InterestReceived", "DividendsReceived", "ReturnOfCapital", "RepaymentOfNotesReceivable")):
        return "noncapex"                  # inflows are never capex (capex is gross; proceeds are not netted)
    if _INV_NONCAPEX.search(concept):
        return "noncapex"
    return "poison"


def _closing_subsets(lines, total):
    """Every subset of lines [(concept, signed_value)] whose sum == total EXACTLY, as frozensets of
    concepts. None when the section is too large or the solutions too many to enumerate completely."""
    n = len(lines)
    if n > CLOSURE_MAX_LINES:
        return None
    half = n // 2
    left, right = lines[:half], lines[half:]

    def sums(part):
        out = {}
        acc = [0] * (1 << len(part))
        for mask in range(1, 1 << len(part)):
            low = mask & -mask
            acc[mask] = acc[mask ^ low] + part[low.bit_length() - 1][1]
        for mask, s in enumerate(acc):
            out.setdefault(s, []).append(mask)
        return out

    sl, sr = sums(left), sums(right)
    found = []
    for s, masks in sl.items():
        other = sr.get(total - s)
        if not other:
            continue
        for ml in masks:
            for mr in other:
                found.append(frozenset([left[i][0] for i in range(len(left)) if ml >> i & 1] +
                                       [right[i][0] for i in range(len(right)) if mr >> i & 1]))
                if len(found) > CLOSURE_MAX_SOLUTIONS:
                    return None
    return found


def _og_acquisition_line_is_additions(d, value):
    """ACQ-2. A PaymentsToAcquireOilAndGasProperty line with no development sibling on the face is the
    filer's ADDITIONS line only when the SAME accession+period proves development spending inside it:
    ASC 932 costs incurred show development > 0 and the line exceeds every acquisition dollar incurred.
    GPOR FY2025: line 527,569,000 vs acquisition costs incurred 83.6M and development 480.4M."""
    dev = d.get(_CI_DEVELOPMENT)
    if not isinstance(dev, (int, float)) or dev <= 0:
        return False
    acq = d.get(_CI_ACQUISITION)
    if not isinstance(acq, (int, float)):
        acq = sum(d.get(c) or 0 for c in _CI_ACQUISITION_PARTS)
    return value > acq


def _closure_capex(d):
    """Proven capex for one accession+period {concept: value}, as (value, composite_tag) or None."""
    total_tag = next((c for c in INVESTING_TOTAL_TAGS if c in d), None)
    if total_tag is None:
        return None
    lines = [(c, _investing_sign(c) * v) for c, v in sorted(d.items())
             if _investing_sign(c) and isinstance(v, (int, float)) and v]
    solutions = _closing_subsets(lines, d[total_tag])
    if not solutions:
        return None
    results = set()
    for s in solutions:
        if any(_investing_class(c) == "poison" for c in s):
            return None
        vals = [abs(d[c]) for c in s]
        if len(vals) != len(set(vals)):
            return None                    # TWIN: a same-value duplicate stood in for an unseen line (GME FY2025)
        cap = [c for c in s if _investing_class(c) == "capex"]
        acq = [c for c in s if _investing_class(c) == "acquisition"]
        if any(d[c] <= 0 for c in cap + acq):
            return None
        used = list(cap)
        for a in acq:
            if CLOSURE_ACQUISITION_LINES[a] & set(cap):
                continue                   # ACQ-1: separately presented acquisitions
            if a == "PaymentsToAcquireOilAndGasProperty" and _og_acquisition_line_is_additions(d, d[a]):
                used.append(a)             # ACQ-2
                continue
            return None                    # the line's role is unproven
        if not used:
            return None
        if len(used) > 1 and CLOSURE_TOTAL_ONLY_LINES & set(used):
            return None                    # a roll-forward total beside a cash line double counts (AN FY2016)
        results.add((sum(d[c] for c in used), tuple(sorted(used))))
    if len({r[0] for r in results}) != 1:
        return None
    value, tags = min(results, key=lambda r: (len(r[1]), r[1]))
    return value, "+".join(tags)


def _replacement_allowed(proof_lines, shipped, filed_zero_tag):
    """REPLACEMENT RULE for one filled year. proof_lines: {concept: value} of the lines the row's own
    proof COUNTED. EVERY counted line must be a CLOSURE_REPLACE_LINES concept -- the anchor included --
    and the shipped value must be ANCHORED: exactly one counted line equals it (today's figure is a line of
    the proven face), or it is a zero the filing files under a CLOSURE_REPLACE_LINES concept. A generic
    anchor is refused because its meaning is unknown: DVN FY2014 ships its "capital expenditures" line
    (PaymentsToAcquireProductiveAssets, 6,988,000,000) and the proof would add 6,462,000,000 filed as
    PaymentsToAcquirePropertyPlantAndEquipment that the same filing's ASC 932 acquisition costs (proved
    5,210,000,000 + unproved 1,177,000,000) show to be the year's property acquisitions."""
    if any(c not in CLOSURE_REPLACE_LINES for c in proof_lines):
        return False
    anchors = [c for c, v in proof_lines.items() if v == shipped]
    if len(anchors) == 1:
        return True
    return not anchors and shipped == 0 and filed_zero_tag in CLOSURE_REPLACE_LINES


def resolve_capex_by_closure(facts, skip_years, lines_out=None):
    """{year: {accession: (value, composite_tag, period_end)}} -- every accession that PROVES a ~annual
    period's capex, for fiscal-year bins (int(end[:4]), as every annual series) NOT in skip_years.

    extract_history applies a proof only from the accession its own vote CHOSE for the row, and only
    when period_end is within 14 days of the row's period (_near_ref). One filing per row: a later
    perimeter restatement proves a different company's capex (AIV 2018: the post-separation comparative
    files OCF 53,486,000 against the row's 396,388,000), and a fresh-start stub or a fiscal-year change
    is another period's capex (CHRD 2020: period ends 11-19, row 12-31). A concept filed twice with
    different values in one accession+period voids that accession+period."""
    groups, conflict = {}, set()
    for concept, body in facts.items():
        if not (_investing_sign(concept) or concept in INVESTING_TOTAL_TAGS
                or concept == _CI_DEVELOPMENT or concept == _CI_ACQUISITION or concept in _CI_ACQUISITION_PARTS):
            continue
        for e in body.get("units", {}).get("USD", []):
            if e.get("form") not in ANNUAL_FORMS:
                continue
            start, end, val = e.get("start"), e.get("end"), e.get("val")
            if not start or not end or val is None:
                continue
            try:
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError:
                continue
            if not 300 <= days <= 400:
                continue
            key = (e.get("accn") or "", start, end)
            g = groups.setdefault(key, {})
            if concept in g and g[concept] != val:
                conflict.add(key)
            g[concept] = val
    out = {}
    for key in sorted(groups):
        accn, _, end = key
        year = int(end[:4])
        if year in skip_years or key in conflict:
            continue
        proven = _closure_capex(groups[key])
        if proven is None:
            continue
        prior = out.setdefault(year, {}).get(accn)
        if prior is None or end > prior[2]:           # one accession, two periods in a bin: latest end
            out[year][accn] = (proven[0], proven[1], end)
            if lines_out is not None:
                lines_out[(accn, end)] = {c: groups[key][c] for c in proven[1].split("+")}
    return out


# -- BANK NET REVENUE (2026-10-06, operator; the measurements sit at FIELD_SPECS["revenue"]) ---------
# Revenue of a bank P&L filer is InterestIncomeExpenseNet + NoninterestIncome. ONE helper decides who is
# such a filer, and the annual history, the TTM and the quarterly snapshot all ask it of the same facts,
# so the three outputs can never disagree about a filer.
BANK_NII_TAG = "InterestIncomeExpenseNet"
BANK_NONII_TAG = "NoninterestIncome"
BANK_REVENUE_TAG = BANK_NII_TAG + "+" + BANK_NONII_TAG
# (c) of the filer test: a lender's own income statement. InterestAndFeeIncomeLoansAndLeases is not on
# this list: ILLR (software) files it.
BANK_STATEMENT_TAGS = ("InterestAndDividendIncomeOperating", "InterestIncomeOperating",
                       "InterestExpenseDeposits")


def _annual_period_ends(facts, tag):
    """Period ends of the ~annual (300-400 day) USD facts `tag` files in an annual form."""
    ends = set()
    for e in facts.get(tag, {}).get("units", {}).get("USD", []):
        if e.get("form") not in ANNUAL_FORMS:
            continue
        start, end = e.get("start"), e.get("end")
        if not start or not end or e.get("val") is None:
            continue
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            ends.add(end)
    return ends


def bank_net_revenue_filer(facts):
    """True when some annual period end (annual form, 300-400 days, USD, the same rule for every tag) has
    all three of: InterestIncomeExpenseNet, NoninterestIncome, and at least one of
    InterestAndDividendIncomeOperating, InterestIncomeOperating, InterestExpenseDeposits (a lender's own
    income statement). The first two alone are filed by operating companies for their NON-operating
    interest and other income (ZOOZ, LGL, ILLR, LEXX), whose revenue must stay the listed one;
    InterestAndFeeIncomeLoansAndLeases is not a test (ILLR, software, files it). The test comes from the
    filings, never from the vendor sector."""
    ends = _annual_period_ends(facts, BANK_NII_TAG) & _annual_period_ends(facts, BANK_NONII_TAG)
    if not ends:
        return False
    statement = set()
    for tag in BANK_STATEMENT_TAGS:
        statement |= _annual_period_ends(facts, tag)
    return bool(ends & statement)


def _bank_component_value(y, series_c, raws_c, chosen, near):
    """One component (NII or noninterest income) of the bank net revenue for the row of fiscal year y,
    resolved as every other cell of the row: the CHOSEN accession's raw value for the row's own period
    (`near`) unless it is a clean power of 1000 off the component's resolved series value; else that
    series value when its period end is the row's period; else None (missing -> the row's revenue is null).
    The component series and raws come from annual_duration_series and are never put into `series`,
    `raws` or `vote_raws`: they cannot vote in the accession rule, form or evict a year-row, or move
    another cell."""
    v = series_c.get(y)
    if v is None:
        return None
    cand = [c for c in raws_c.get(y, []) if c[0] == chosen and near(c[3])] if chosen is not None else []
    if cand:
        av = (_pick_consistent([(c[1], c[2]) for c in cand], v)
              if len({c[2] for c in cand}) > 1 else cand[0][2])
        if _pow1000_ratio(max(av, v, key=abs), min(av, v, key=abs)) is None:
            return av
    # the series value takes the bin's latest-filed value: it sits on the period of the candidate that
    # carries it (a scale-corrected value matches no candidate: the bin's latest-filed one)
    carrying = [c for c in raws_c.get(y, []) if c[2] == v] or raws_c.get(y, [])
    return v if near(max(carrying, key=lambda c: c[1])[3]) else None


# CH-9: interest-bearing debt COMPONENTS (instant/balance-sheet). Resolved one tag at a time in
# LIST ORDER (first tag to cover a year wins it) by resolve_instant_field_series — NOT the
# recency+coverage vote, which can crown a total-including-current tag for a noncurrent-only field
# (MAR: the 2-tag production list ships 23,000,000). Legacy `lt_debt` (INSTANT_TAGS) is untouched.
# NO merged total_debt / net_debt field is emitted — see _debt_note at the write.
INSTANT_FIELD_SPECS = {
 "debt_lt_noncurrent": {"COMBINED": ["LongTermDebtNoncurrent",
   "LongTermDebtAndCapitalLeaseObligations",   # == LongTermDebtNoncurrent in 25/27 live both-filers
   "LongtermBorrowings", "NoncurrentPortionOfNoncurrentBondsIssued"]},   # ifrs; TSM
 "debt_current": {"COMBINED": ["LongTermDebtCurrent",
   "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent",
   "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
   "CurrentPortionOfLongtermBorrowings", "ShortTermBorrowings", "ShorttermBorrowings"]},
 "short_term_borrowings_separate": {"COMBINED": ["CommercialPaper", "ShortTermBorrowings",
                                                 "ShorttermBorrowings"]},
 "finance_lease_liability": {"COMBINED": ["FinanceLeaseLiability", "CapitalLeaseObligations"],
   "SUM_PAIRS": [("FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent"),
                 ("CapitalLeaseObligationsCurrent", "CapitalLeaseObligationsNoncurrent")]},
 "operating_lease_liability": {"COMBINED": ["OperatingLeaseLiability", "LeaseLiabilities"],
   "SUM_PAIRS": [("OperatingLeaseLiabilityCurrent", "OperatingLeaseLiabilityNoncurrent"),
                 ("CurrentLeaseLiabilities", "NoncurrentLeaseLiabilities")]},
 # CH-9 (operator-approved 2026-08-21): per-filer ALLOWLISTED ifrs Borrowings total. NULL for every
 # filer except the allowlist — ifrs Borrowings has no single cross-filer definition (AZN includes
 # IFRS-16 leases, SAP/NVS exclude them), so it can only ship where the composition is per-filer
 # verified. NVS: Borrowings 28,729M for 2025, leases 1,920M proven OUTSIDE it (two-year identity
 # exact). This is a COMBINED current+noncurrent total — deliberately its own field, NEVER merged
 # into debt_lt_noncurrent/debt_current, and NOT a computed total_debt.
 "borrowings_total": {"COMBINED": ["Borrowings"], "TICKER_ALLOWLIST": {"NVS"}},
 # R17 (2026-09-30): tangible-equity inputs (instant, USD). Ladders — the first rung to resolve a
 # year wins it; tags are NEVER summed except the one declared pair. The us-gaap and ifrs-full
 # namespaces are merged before extraction, so ifrs-full Goodwill is the same key "Goodwill".
 # intangibles_ex_goodwill rungs, in order: IntangibleAssetsNetExcludingGoodwill, ifrs
 # IntangibleAssetsOtherThanGoodwill, Finite+Indefinite pair (both required that year), then
 # FiniteLivedIntangibleAssetsNet alone ("AFTER_PAIRS"). Rung per year is in the provenance tag.
 # A2: a balance cannot be negative — REJECT_NEGATIVE refuses a negative rung for that year (the
 # next rung is tried, null if none) and leaves a `negative_rejected` note in the provenance.
 "goodwill": {"COMBINED": ["Goodwill"], "REJECT_NEGATIVE": True},
 "intangibles_ex_goodwill": {
   "COMBINED": ["IntangibleAssetsNetExcludingGoodwill", "IntangibleAssetsOtherThanGoodwill"],
   "SUM_PAIRS": [("FiniteLivedIntangibleAssetsNet",
                  "IndefiniteLivedIntangibleAssetsExcludingGoodwill")],
   "AFTER_PAIRS": ["FiniteLivedIntangibleAssetsNet"],
   "REJECT_NEGATIVE": True},
}
# Declared STOP resolved by allowlist (CH-9 / §4.8): NVS files no LongtermBorrowings and its ifrs
# Borrowings is a mixed total, so debt_lt_noncurrent stays null and debt_current is SUPPRESSED
# (its bare 794M current-portion invites a 97%-understated total-debt sum). The verified total ships
# in borrowings_total instead; leases resolve normally into operating_lease_liability.
DEBT_NULL_TICKERS = {"NVS"}
# R17 duration ladder: amortization of acquired intangibles as its own field. The existing `da`
# field and its component-slot logic are untouched. None stays None — a year the filer does not
# tag is null, never 0 (a filed 0 is a value).
# A2 (2026-09-30): the generic cash-flow tag AdjustmentForAmortization is NOT a rung (it is not
# specific to acquired intangibles — KRYS's negative cell was investment-discount accretion). Signs:
# SIGN_FLIP_TAGS = the ifrs roll-forward element that presents amortization as a reduction; its
# negative value ships as the absolute value and a `sign_flipped` note. Any other negative value is
# refused for that rung (`negative_rejected`; the next rung is tried, null if none).
DURATION_LADDER_SPECS = {
 "amortization_intangibles": {"COMBINED": [
   "AmortizationOfIntangibleAssets", "AmortizationOfAcquiredIntangibleAssets",
   "FiniteLivedIntangibleAssetsAmortizationExpense",
   "AmortisationIntangibleAssetsOtherThanGoodwill",             # ifrs-full
   "AdjustmentsForAmortisationExpense",                         # ifrs-full
   "AmortisationExpense"],                                      # ifrs-full
   "SIGN_FLIP_TAGS": ["AmortisationIntangibleAssetsOtherThanGoodwill"],
   "REJECT_NEGATIVE": True},
 # ASC 260 identity fields (brief_rev20_followup.md, S1): annual-duration, resolved per fiscal year by the same
 # ladder reader and candidate rules, vote-excluded. A filed 0 is a value; a year nothing is filed for is null.
 # eps_diluted reads the USD/shares unit (ifrs filers in another currency stay uncovered, as for every other
 # ifrs field); EarningsPerShareBasicAndDiluted is the LAST rung, used only in a year where no diluted figure is
 # filed, and the year's rung rides in the provenance (`eps_rung`). The share-scale step P-2 keeps its own EPS
 # read (_filed_diluted_eps), unchanged. NO_SCALE_DEFENCE: the power-of-1000 defences catch dollar amounts filed in
 # the wrong unit; a per-share figure has no such slip (real values run from cents to hundreds of dollars), so
 # eps_diluted skips the series normalisation, the duplicate-filing power-of-1000 tie-break and the row loop's
 # scale arbitration: duplicates of one period resolve to the latest filed.
 "eps_diluted": {"COMBINED": ["EarningsPerShareDiluted",
                              "DilutedEarningsLossPerShare",                      # ifrs-full
                              "EarningsPerShareBasicAndDiluted"],
                 "UNITS": ("USD/shares",), "NO_SCALE_DEFENCE": True},
 "net_income_available_to_common_diluted": {"COMBINED": ["NetIncomeLossAvailableToCommonStockholdersDiluted"]},
 "preferred_dividends": {"COMBINED": ["PreferredStockDividendsIncomeStatementImpact",
                                      "PreferredStockDividendsAndOtherAdjustments"]},
}
# eps_rung[T][year]: which rung of the eps_diluted ladder resolved the cell.
SCALE_EXEMPT_FIELDS = ("eps_diluted",)
EPS_RUNG = {"EarningsPerShareDiluted": "diluted", "DilutedEarningsLossPerShare": "ifrs_diluted",
            "EarningsPerShareBasicAndDiluted": "basic_and_diluted"}
# The three R17 fields; encode_provenance lists, per ticker, those never tagged in any shipped year.
R17_FIELDS = ("goodwill", "intangibles_ex_goodwill", "amortization_intangibles")

# ── Input scope (brief_input_scope_fixes.md, Fixes 1a and 2a, 2026-10-02) ───────────────────────
# Fix 1a. Under ASC 810 only net income is attributed between the parent and the noncontrolling
# interests (NCI); EPS (ASC 260) divides the PARENT's net income. us-gaap ProfitLoss is consolidated
# net income INCLUDING the NCI and used to win the recency+coverage vote whenever its series was the
# longer one. `net_income` is now the parent's, resolved PER FISCAL YEAR by this scope ladder (the
# first rung to resolve a year wins it; rungs 3/4 subtract the NCI line; rung 6 keeps ProfitLoss and
# marks it). ni_scope per year rides in the provenance. A filed 0 is a value: an NCI line of 0
# resolves rung 3.
NI_LADDER = (
    ("NetIncomeLoss", None, "parent"),                                          # 1 us-gaap
    ("ProfitLossAttributableToOwnersOfParent", None, "parent"),                 # 2 ifrs-full
    ("ProfitLoss", "us", "parent_derived"),                                     # 3 PL - us-gaap NCI line
    ("ProfitLoss", "ifrs", "parent_derived"),                                   # 4 PL - ifrs NCI line
    ("ProfitLoss", None, "no_nci_filed"),                                       # 5 / 6 (nci_unknown)
)
NCI_LINE_US = "NetIncomeLossAttributableToNoncontrollingInterest"
NCI_SPLIT_US = ("NetIncomeLossAttributableToRedeemableNoncontrollingInterest",
                "NetIncomeLossAttributableToNonredeemableNoncontrollingInterest")
NCI_LINE_IFRS = "ProfitLossAttributableToNoncontrollingInterests"
# N, the closed list of noncontrolling-interest elements. StockholdersEquityIncludingPortion... counts
# only when it differs from StockholdersEquity at the same instant (_nci_filed_ends).
NCI_ELEMENTS = ("MinorityInterest", "RedeemableNoncontrollingInterestEquityCarryingAmount",
                "RedeemableNoncontrollingInterestEquityFairValue", NCI_LINE_US) + NCI_SPLIT_US + \
               ("NoncontrollingInterests", NCI_LINE_IFRS)
SE_INCL_NCI = "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
# `equity` is the parent's, resolved per year by resolve_equity_series (the equity_scope ladder):
#   1 us-gaap StockholdersEquity (parent); 2 ifrs EquityAttributableToOwnersOfParent (parent);
#   3 SE_INCL_NCI - MinorityInterest, same instant, both filed (parent_derived); 4 ifrs Equity -
#   NoncontrollingInterests, same instant, both filed (parent_derived); 5 SE_INCL_NCI, else ifrs Equity,
#   where no element of N is filed with a non-zero value (no_nci_filed, or nci_zero_filed when an element
#   is filed only as 0); 6 the same figure where a non-zero element of N is filed and nothing above
#   resolves (nci_unknown: kept and marked). Redeemable NCI is NOT subtracted in rung 3: it sits in
#   temporary equity, outside the including-NCI total (ASC 810-10-45-16; IAS 1.54(q)-(r)).
# Fix 2a. Since ASU 2016-18 the cash-flow total CashCashEquivalentsRestrictedCash... (CCERCRCE) runs one
# year-end further back than the balance sheet and used to win the vote; it includes restricted and
# segregated cash. `cash` is the unrestricted line, resolved per year by this ladder (cash_scope per
# year in the provenance): 1 CashAndCashEquivalentsAtCarryingValue; 2 ifrs CashAndCashEquivalents;
# 3 CCERCRCE - cash_restricted when an element of R is filed and the difference is >= 0; 4 CCERCRCE when
# no element of R is filed; else null (`cash_unresolved`, or `cash_unresolved_securities_segregated`
# when the only R element filed is a CashAndSecuritiesSegregated... one: it includes securities, so it
# is not a component of CCERCRCE and cannot be subtracted from it).
CCERCRCE = "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
# FAMILY RULE (follow-up item 4). R, the customer-money assets and liabilities hold totals next to their
# own components (RestrictedCash = ...Current + ...Noncurrent; RestrictedCashAndCashEquivalents =
# RestrictedCash + RestrictedCashEquivalents; AssetsHeldInTrust = ...Current + ...Noncurrent). Within a
# family the most aggregate element filed at the instant is taken, and an element is never added to its
# own component. Shapes: a GROUP is an ordered tuple of ALTERNATIVES; an alternative is a tuple of tags,
# summed over the ones filed (a lone Current or Noncurrent is a figure, not a wrong total); the first
# alternative with any tag filed wins the group. An ATTEMPT is a tuple of groups summed over the groups
# that resolve; a FAMILY is a tuple of attempts, the first attempt with any group resolved wins.
_RCACE = (("RestrictedCashAndCashEquivalentsAtCarryingValue",),
          ("RestrictedCashAndCashEquivalentsCurrent", "RestrictedCashAndCashEquivalentsNoncurrent"))
_RC = (("RestrictedCash",), ("RestrictedCashCurrent", "RestrictedCashNoncurrent"))
_RCE = (("RestrictedCashEquivalents",),
        ("RestrictedCashEquivalentsCurrent", "RestrictedCashEquivalentsNoncurrent"))
_SEGREGATED = (("CashSegregatedUnderFederalAndOtherRegulations",),
               ("CashSegregatedUnderCommodityExchangeActRegulation", "CashSegregatedUnderOtherRegulations"))
# The two CashAndSecuritiesSegregated... elements include securities: not components of CCERCRCE, so
# they are customer money held under regulation, not R.
_SECURITIES_SEGREGATED = (("CashAndSecuritiesSegregatedUnderFederalAndOtherRegulations",),
                          ("CashAndSecuritiesSegregatedUnderSecuritiesExchangeCommissionRegulation",))
_TRUST = (("AssetsHeldInTrust",), ("AssetsHeldInTrustCurrent", "AssetsHeldInTrustNoncurrent"))
RESTRICTED_FAMILY = ((_RCACE,), (_RC, _RCE))                         # R, restricted cash
SEGREGATED_FAMILY = ((_SEGREGATED,),)                                # R, cash segregated for customers
SECURITIES_SEGREGATED_FAMILY = ((_SECURITIES_SEGREGATED,),)
# New instant fields. "srt:" keys are the srt namespace, added to the merged facts under that prefix by
# build_ticker_outputs (the same concept as the us-gaap element: never added together).
CUSTOMER_MONEY_ASSETS_FAMILY = (((("FundsHeldForClients",),), (("SettlementAssetsCurrent",),), _TRUST,
                                 _SECURITIES_SEGREGATED),)
CUSTOMER_MONEY_LIABILITIES_FAMILY = (((("PayablesToCustomers",), ("srt:PayablesToCustomers",)),
                                      (("SettlementLiabilitiesCurrent",),)),)
MONEY_FAMILIES = {"restricted": RESTRICTED_FAMILY, "segregated": SEGREGATED_FAMILY,
                  "securities_segregated": SECURITIES_SEGREGATED_FAMILY,
                  "customer_money_assets": CUSTOMER_MONEY_ASSETS_FAMILY,
                  "customer_money_liabilities": CUSTOMER_MONEY_LIABILITIES_FAMILY}
# Plain sums (each null when none of its tags is filed); insurance_reserves' three elements are disjoint.
INSTANT_SUM_FIELDS = {
    "insurance_reserves": ("LiabilityForFuturePolicyBenefits",
                           "LiabilityForUnpaidClaimsAndClaimsAdjustmentExpense", "UnearnedPremiums"),
}
SRT_TAGS = ("PayablesToCustomers",)


def _nci_filed_ends(facts, nonzero_only=False):
    """[(end, form)] of every filed element of N (any form). StockholdersEquityIncludingPortion... counts
    only where a StockholdersEquity fact of the same end is filed and none carries the same value (its
    difference from the parent's equity is then a non-zero NCI); filed without StockholdersEquity it is
    not NCI evidence by itself. `nonzero_only`: elements filed as 0 do not count.
    A filed zero NCI is evidence of NO outside holders (a value, not an absence), so the scope decisions
    ask for the non-zero evidence and tell a filed zero from no element at all."""
    out = []
    for tag in NCI_ELEMENTS:
        for e in facts.get(tag, {}).get("units", {}).get("USD", []):
            if e.get("end") and e.get("val") is not None and not (nonzero_only and e["val"] == 0):
                out.append((e["end"], e.get("form")))
    se = {}
    for e in facts.get("StockholdersEquity", {}).get("units", {}).get("USD", []):
        if e.get("end") and e.get("val") is not None:
            se.setdefault(e["end"], set()).add(e["val"])
    for e in facts.get(SE_INCL_NCI, {}).get("units", {}).get("USD", []):
        if e.get("end") and e.get("val") is not None and e["end"] in se and e["val"] not in se[e["end"]]:
            out.append((e["end"], e.get("form")))
    return out


def _nci_filed_years(facts, nonzero_only=False):
    """Fiscal-year bins (calendar end year, annual forms) in which an element of N is filed (with a
    non-zero value when `nonzero_only`)."""
    return {int(end[:4]) for end, form in _nci_filed_ends(facts, nonzero_only) if form in ANNUAL_FORMS}


def _nci_scope_unresolved(y, nci_any, nci_nonzero):
    """Scope of a ProfitLoss / Equity figure that no parent or derived rung resolved (rungs 5 and 6): an
    element of N filed with a non-zero value -> nci_unknown (the figure is kept and marked); elements
    filed only as 0 -> nci_zero_filed (the zero is read as a value: no outside holders); none -> no_nci_filed."""
    if y in nci_nonzero:
        return "nci_unknown"
    return "nci_zero_filed" if y in nci_any else "no_nci_filed"


def _nci_line_series(facts, which):
    """(series, raws) of the NCI income line for rung 3 ('us') or 4 ('ifrs'). us-gaap: the total line,
    else (per year) the redeemable + nonredeemable split, BOTH required; raws of a split year hold the
    per-accession sums of filings that carry both halves for the same end."""
    if which == "ifrs":
        s, r, _ = annual_duration_series(facts, [NCI_LINE_IFRS])
        return s, r
    s, r, _ = annual_duration_series(facts, [NCI_LINE_US])
    s, r = dict(s), dict(r)
    sa, ra, _ = annual_duration_series(facts, [NCI_SPLIT_US[0]])
    sb, rb, _ = annual_duration_series(facts, [NCI_SPLIT_US[1]])
    for y in set(sa) & set(sb):
        if y in s or sa[y] is None or sb[y] is None:
            continue
        s[y] = sa[y] + sb[y]
        bmap = {(c[0], c[3]): c for c in rb.get(y, [])}
        r[y] = [(c[0], c[1], c[2] + bmap[(c[0], c[3])][2], c[3])
                for c in ra.get(y, []) if (c[0], c[3]) in bmap]
    return s, r


def resolve_net_income_series(facts):
    """Fix 1a: `net_income` by the scope ladder, per fiscal year (see NI_LADDER).

    Returns (series, raws, prov, tags, scope, derived, incl). For a rung 3/4 year, series holds the
    parent's figure (ProfitLoss - NCI line), raws hold ProfitLoss's candidates (they carry the accession
    for the row vote), and derived[y] = {"pl", "nci", "nci_raws"}: the row builder runs the accession
    override on ProfitLoss and subtracts the NCI line of the same accession (else the NCI series value).
    `incl` is net_income_incl_nci: (series, raws, prov, tags) — ProfitLoss when filed; else a rung-1/2
    parent + the us-gaap/ifrs NCI line when both are filed; else the parent's figure when no element of
    N is filed with a non-zero value that year; else absent. A filed zero NCI is evidence of no outside
    holders: it leaves rung 5 and the consolidated-equals-parent rule open (`nci_zero_filed`).
    """
    nci_any, nci_nonzero = _nci_filed_years(facts), _nci_filed_years(facts, nonzero_only=True)
    tag_series = {}
    for tag in ("NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"):
        s, r, _ = annual_duration_series(facts, [tag])
        tag_series[tag] = (s, r)
    nci_lines = {w: _nci_line_series(facts, w) for w in ("us", "ifrs")}
    series, raws, prov, tags, scope, derived = {}, {}, {}, {}, {}, {}
    for i, (tag, nci_w, sc) in enumerate(NI_LADDER):
        s, r = tag_series[tag]
        for y, v in s.items():
            if y in series or v is None:
                continue
            if nci_w is not None:
                ns, nr = nci_lines[nci_w]
                if ns.get(y) is None:
                    continue
                series[y] = v - ns[y]
                derived[y] = {"pl": v, "nci": ns[y], "nci_raws": nr.get(y, [])}
                tags[y] = tag + "-" + (NCI_LINE_IFRS if nci_w == "ifrs" else NCI_LINE_US)
                scope[y] = sc
            else:
                series[y] = v
                tags[y] = tag
                scope[y] = _nci_scope_unresolved(y, nci_any, nci_nonzero) if sc == "no_nci_filed" else sc
            raws[y] = r.get(y, [])
            prov[y] = "primary" if i == 0 else tags[y]
    # net_income_incl_nci
    pl_s, pl_r = tag_series["ProfitLoss"]
    i_series, i_raws, i_prov, i_tags = {}, {}, {}, {}
    for y, v in pl_s.items():
        if v is not None:
            i_series[y], i_raws[y], i_prov[y], i_tags[y] = v, pl_r.get(y, []), "primary", "ProfitLoss"
    for tag, w in (("NetIncomeLoss", "us"), ("ProfitLossAttributableToOwnersOfParent", "ifrs")):
        ps, pr = tag_series[tag]
        ns = nci_lines[w][0]
        for y, v in ps.items():
            if y in i_series or v is None:
                continue
            if ns.get(y) is not None:
                i_series[y], i_raws[y] = v + ns[y], []
                i_prov[y] = i_tags[y] = tag + "+" + (NCI_LINE_IFRS if w == "ifrs" else NCI_LINE_US)
            elif y not in nci_nonzero:
                i_series[y], i_raws[y] = v, pr.get(y, [])
                i_prov[y] = i_tags[y] = tag
    return series, raws, prov, tags, scope, derived, (i_series, i_raws, i_prov, i_tags)


def _instant_end(raws, y):
    """The instant a resolved instant year sits at: the latest end among its candidates (the series takes
    the latest (end, filed) value of the year bin)."""
    ends = [c[3] for c in raws.get(y, [])]
    return max(ends) if ends else None


def resolve_equity_series(facts):
    """Follow-up item 2: `equity` is the parent's on every rung, per year (see the ladder above
    CCERCRCE: StockholdersEquity; ifrs owners of the parent; including-NCI total minus MinorityInterest;
    ifrs Equity minus NoncontrollingInterests; the figure where no non-zero element of N is filed;
    the figure kept and marked). A subtraction takes both elements at ONE instant, both filed.
    Returns (series, raws, prov, tags, scope). A derived year has no single accession (raws empty)."""
    nci_any, nci_nonzero = _nci_filed_years(facts), _nci_filed_years(facts, nonzero_only=True)
    t = {tag: annual_instant_series(facts, [tag])[:2] for tag in (
        "StockholdersEquity", "EquityAttributableToOwnersOfParent", SE_INCL_NCI, "Equity",
        "MinorityInterest", "NoncontrollingInterests")}
    series, raws, prov, tags, scope = {}, {}, {}, {}, {}

    def put(y, v, r, p, tag, sc):
        series[y], raws[y], prov[y], tags[y], scope[y] = v, r, p, tag, sc

    for tag in ("StockholdersEquity", "EquityAttributableToOwnersOfParent"):           # rungs 1, 2
        s, r = t[tag]
        for y, v in s.items():
            if y not in series and v is not None:
                put(y, v, r.get(y, []), "primary" if tag == "StockholdersEquity" else tag, tag, "parent")
    for total, nci in ((SE_INCL_NCI, "MinorityInterest"), ("Equity", "NoncontrollingInterests")):   # rungs 3, 4
        (ts, tr), (ns, nr) = t[total], t[nci]
        for y, v in ts.items():
            if y in series or v is None or ns.get(y) is None:
                continue
            if _instant_end(tr, y) != _instant_end(nr, y):
                continue
            tg = total + "-" + nci
            put(y, v - ns[y], [], tg, tg, "parent_derived")
    for tag in (SE_INCL_NCI, "Equity"):                                                # rungs 5, 6
        s, r = t[tag]
        for y, v in s.items():
            if y not in series and v is not None:
                put(y, v, r.get(y, []), tag, tag, _nci_scope_unresolved(y, nci_any, nci_nonzero))
    return series, raws, prov, tags, scope


def resolve_equity_incl_nci_series(facts):
    """Fix 1a(b): equity including the NCI. Rungs per year: the us-gaap including-NCI tag; ifrs Equity
    (a consolidated total, `ifrs_equity`); StockholdersEquity + MinorityInterest (+
    RedeemableNoncontrollingInterestEquityCarryingAmount when filed), both of the first two required;
    StockholdersEquity when no element of N is filed with a non-zero value that year (a filed zero is
    evidence of no NCI); else absent. Returns (series, raws, prov, tags, rung)."""
    nci_nonzero = _nci_filed_years(facts, nonzero_only=True)
    inc, inc_r, _ = annual_instant_series(facts, [SE_INCL_NCI])
    ife, ife_r, _ = annual_instant_series(facts, ["Equity"])
    se, se_r, _ = annual_instant_series(facts, ["StockholdersEquity"])
    mi, _, _ = annual_instant_series(facts, ["MinorityInterest"])
    rnci, _, _ = annual_instant_series(facts, ["RedeemableNoncontrollingInterestEquityCarryingAmount"])
    series, raws, prov, tags, rung = {}, {}, {}, {}, {}
    for y in sorted(set(inc) | set(ife) | set(se)):
        if inc.get(y) is not None:
            series[y], raws[y], prov[y], tags[y], rung[y] = inc[y], inc_r.get(y, []), "primary", SE_INCL_NCI, "incl_tag"
        elif ife.get(y) is not None:
            series[y], raws[y], prov[y], tags[y], rung[y] = ife[y], ife_r.get(y, []), "Equity", "Equity", "ifrs_equity"
        elif se.get(y) is not None and mi.get(y) is not None:
            total = se[y] + mi[y]
            t = "StockholdersEquity+MinorityInterest"
            if rnci.get(y) is not None:
                total += rnci[y]
                t += "+RedeemableNoncontrollingInterestEquityCarryingAmount"
            series[y], raws[y], prov[y], tags[y], rung[y] = total, [], t, t, "parent_plus_minority"
        elif se.get(y) is not None and y not in nci_nonzero:
            series[y], raws[y], prov[y], tags[y], rung[y] = se[y], se_r.get(y, []), "StockholdersEquity", \
                "StockholdersEquity", "parent_no_nci"
    return series, raws, prov, tags, rung


def resolve_instant_sum_series(facts, tag_list):
    """Sum of every listed instant tag filed in the year (each tag's own scale-defended series); a year
    none of them files is absent (null), never 0. Returns (series, raws, prov, tags); raws are empty
    (a summed year has no single accession)."""
    per = [(t, annual_instant_series(facts, [t])[0]) for t in tag_list]
    series, raws, prov, tags = {}, {}, {}, {}
    for y in sorted(set().union(*[set(s) for _, s in per])):
        parts = [(t, s[y]) for t, s in per if s.get(y) is not None]
        if not parts:
            continue
        series[y] = sum(v for _, v in parts)
        raws[y] = []
        prov[y] = tags[y] = "+".join(t for t, _ in parts)
    return series, raws, prov, tags


def _family_tags(family):
    return {t for attempt in family for group in attempt for alt in group for t in alt}


def _family_value(per, y, family):
    """(value, [tags used]) of a family in year y, or (None, []) when none of it is filed. Within a group
    the first alternative with any tag filed wins (the most aggregate element: a total is never added to
    its own component); an attempt sums the groups that resolve; the first attempt that resolves wins.
    A filed 0 is a value."""
    for attempt in family:
        total, used = None, []
        for group in attempt:
            for alt in group:
                parts = [(t, per[t][y]) for t in alt if per.get(t, {}).get(y) is not None]
                if parts:
                    v = sum(x for _, x in parts)
                    total = v if total is None else total + v
                    used += [t for t, _ in parts]
                    break
        if total is not None:
            return total, used
    return None, []


def resolve_money_fields(facts):
    """Follow-up item 4: cash_restricted (restricted family + segregated-cash family), customer_money_assets
    and customer_money_liabilities by the FAMILY rule (see RESTRICTED_FAMILY above), plus the per-year
    CashAndSecuritiesSegregated... figure (not part of R; it still shows that CCERCRCE cannot be shown as
    unrestricted). Returns ({field: (series, raws, prov, tags)}, {year: securities_segregated_value}); raws
    are empty (a summed year has no single accession); the tag string lists the elements used."""
    per = {t: annual_instant_series(facts, [t])[0]
           for fam in MONEY_FAMILIES.values() for t in _family_tags(fam)}
    years = sorted(set().union(*[set(s) for s in per.values()]))
    out = {f: ({}, {}, {}, {}) for f in ("cash_restricted", "customer_money_assets", "customer_money_liabilities")}
    securities = {}

    def put(field, y, value, used):
        series, raws, prov, tags = out[field]
        series[y], raws[y] = value, []
        prov[y] = tags[y] = "+".join(used)

    for y in years:
        rv, ru = _family_value(per, y, RESTRICTED_FAMILY)
        sv, su = _family_value(per, y, SEGREGATED_FAMILY)
        if rv is not None or sv is not None:
            put("cash_restricted", y, sum(v for v in (rv, sv) if v is not None), ru + su)
        for field, family in (("customer_money_assets", CUSTOMER_MONEY_ASSETS_FAMILY),
                              ("customer_money_liabilities", CUSTOMER_MONEY_LIABILITIES_FAMILY)):
            v, u = _family_value(per, y, family)
            if v is not None:
                put(field, y, v, u)
        cv, _ = _family_value(per, y, SECURITIES_SEGREGATED_FAMILY)
        if cv is not None:
            securities[y] = cv
    return out, securities


def resolve_cash_series(facts, restricted, securities_segregated):
    """Fix 2a: `cash` = the unrestricted line by the cash ladder (see CCERCRCE above). `restricted` is the
    cash_restricted series (R); `securities_segregated` the {year: value} of the CashAndSecuritiesSegregated...
    family. Returns (series, raws, prov, tags, scope); scope[y] is set for every year CCERCRCE or a rung
    files: `cash_unresolved` (null cell) for a negative rung-3 difference,
    `cash_unresolved_securities_segregated` (null cell) when a securities-segregated element is the only
    restricted-type element filed (it is not a component of CCERCRCE, so it cannot be subtracted, and
    CCERCRCE cannot be shown as unrestricted)."""
    series, raws, prov, tags, scope = {}, {}, {}, {}, {}
    for i, (tag, sc) in enumerate((("CashAndCashEquivalentsAtCarryingValue", "unrestricted_line"),
                                   ("CashAndCashEquivalents", "ifrs_cash_and_equivalents"))):
        s, r, _ = annual_instant_series(facts, [tag])
        for y, v in s.items():
            if y not in series and v is not None:
                series[y], raws[y], prov[y], tags[y], scope[y] = v, r.get(y, []), \
                    ("primary" if i == 0 else tag), tag, sc
    s, r, _ = annual_instant_series(facts, [CCERCRCE])
    for y, v in s.items():
        if y in series or v is None:
            continue
        if restricted.get(y) is not None:
            if v - restricted[y] >= 0:
                t = CCERCRCE + "-restricted"
                series[y], raws[y], prov[y], tags[y], scope[y] = v - restricted[y], [], t, t, \
                    "derived_minus_restricted"
            else:
                scope[y] = "cash_unresolved"
        elif securities_segregated.get(y) is not None:
            scope[y] = "cash_unresolved_securities_segregated"
        else:
            series[y], raws[y], prov[y], tags[y], scope[y] = v, r.get(y, []), CCERCRCE, CCERCRCE, \
                "total_no_restricted_filed"
    return series, raws, prov, tags, scope


def _ladder_note(notes, y, note, tag, value, **extra):
    """R17 provenance note for year y ({year: [ {note, tag, value, ...}, ... ]}); no-op if notes is None."""
    if notes is not None:
        notes.setdefault(y, []).append({"note": note, "tag": tag, "value": value, **extra})


def _ladder_conflict(notes, series, tags, y, v, tag):
    """R17 `rung_conflict`: a filed 0 already won year y and this LATER rung holds a positive value.
    Record, do not resolve — the first rung stays (the ladder rule). No-op unless collecting notes."""
    if notes is not None and v and v > 0 and series.get(y) == 0 \
            and not any(n["note"] == "rung_conflict" for n in notes.get(y, [])):
        _ladder_note(notes, y, "rung_conflict", tags[y], 0, later_tag=tag, later_value=v)


def resolve_instant_field_series(facts, spec, ticker=None, unit_keys=("USD",), notes=None):
    """Instant field resolved by CURATED LADDER, not the recency+coverage vote.

    COMBINED tags in LIST ORDER: the first tag to cover a year wins it (a total-including-current
    tag must not be crowned for a noncurrent-only field). Then SUM_PAIRS: (current, noncurrent)
    component pairs, summed ONLY when BOTH sides are present for the year (a one-sided component is
    a wrong total — CMI finance-lease 2009-2017 noncurrent-only, EXPE/MEDP 2018 lone-0 false-zero).
    A TICKER_ALLOWLIST spec restricts the field to named filers (per-filer-verified totals only).
    AFTER_PAIRS (R17): tags tried last, one at a time, only for years nothing above resolved.
    REJECT_NEGATIVE + `notes` (R17/A2): a negative rung is refused for the year (next rung tried) and
    noted `negative_rejected`; a filed 0 that beats a later positive rung is noted `rung_conflict`.
    Returns (series, raws, prov, tags). provenance is 'primary' for combined[0], else the tag name;
    'pair_sum' for summed years (raws=[] so the accession vote skips them).
    """
    allow = spec.get("TICKER_ALLOWLIST")
    if allow is not None and ticker not in allow:
        return {}, {}, {}, {}
    combined = list(spec.get("COMBINED") or [])
    reject_neg = bool(spec.get("REJECT_NEGATIVE"))
    series, raws, prov, tags = {}, {}, {}, {}
    for i, tag in enumerate(combined):
        s, r, _ = annual_instant_series(facts, [tag], unit_keys)
        for y, v in s.items():
            if y in series:
                _ladder_conflict(notes, series, tags, y, v, tag)
            elif v is not None:
                if reject_neg and v < 0:
                    _ladder_note(notes, y, "negative_rejected", tag, v)
                    continue
                series[y] = v
                raws[y] = r.get(y, [])
                prov[y] = "primary" if i == 0 else tag
                tags[y] = tag
    for pair in spec.get("SUM_PAIRS") or []:
        sa, _, _ = annual_instant_series(facts, [pair[0]], unit_keys)
        sb, _, _ = annual_instant_series(facts, [pair[1]], unit_keys)
        for y in set(sa) & set(sb):                    # BOTH sides mandatory
            if sa[y] is None or sb[y] is None:
                continue
            pair_tag = pair[0] + "+" + pair[1]
            total = sa[y] + sb[y]
            if y in series:
                _ladder_conflict(notes, series, tags, y, total, pair_tag)
            elif reject_neg and min(sa[y], sb[y], total) < 0:      # a negative side makes the sum wrong
                _ladder_note(notes, y, "negative_rejected", pair_tag, total)
            else:
                series[y] = total
                raws[y] = []
                prov[y] = "pair_sum"
                tags[y] = pair_tag
    for tag in spec.get("AFTER_PAIRS") or []:          # R17: last rung, only years nothing above resolved
        s, r, _ = annual_instant_series(facts, [tag], unit_keys)
        for y, v in s.items():
            if y in series:
                _ladder_conflict(notes, series, tags, y, v, tag)
            elif v is not None:
                if reject_neg and v < 0:
                    _ladder_note(notes, y, "negative_rejected", tag, v)
                    continue
                series[y] = v
                raws[y] = r.get(y, [])
                prov[y] = tag
                tags[y] = tag
    return series, raws, prov, tags


def resolve_duration_ladder_series(facts, spec, unit_keys=("USD",), notes=None):
    """Duration field resolved by CURATED LADDER (R17): COMBINED tags in LIST ORDER, the first tag
    to resolve a year wins it, tags NEVER summed. Each tag is read alone through
    annual_duration_series, so the annual-form / 300-400-day / end-year alignment and the scale
    defences are exactly those of every other duration field. A year no tag resolves is absent
    (null in the row), never 0. Returns (series, raws, prov, tags) like the instant resolver;
    provenance is 'primary' for combined[0], else the tag name.
    A2 signs: a negative value from a SIGN_FLIP_TAGS tag ships as its absolute value (`sign_flipped`
    note; the row-build loop refuses to restore the negative raw); a negative value from any
    other tag is refused for the year under REJECT_NEGATIVE (`negative_rejected`, next rung tried).
    A filed 0 that beats a later positive rung is noted `rung_conflict` (record, do not resolve).
    """
    flip = set(spec.get("SIGN_FLIP_TAGS") or [])
    reject_neg = bool(spec.get("REJECT_NEGATIVE"))
    series, raws, prov, tags = {}, {}, {}, {}
    for i, tag in enumerate(spec.get("COMBINED") or []):
        s, r, _ = annual_duration_series(facts, [tag], unit_keys, not spec.get("NO_SCALE_DEFENCE"))
        for y, v in s.items():
            if v is None:
                continue
            raw = v
            flipped = v < 0 and tag in flip
            if flipped:
                v = -v
            if y in series:
                _ladder_conflict(notes, series, tags, y, v, tag)
            elif reject_neg and v < 0:
                _ladder_note(notes, y, "negative_rejected", tag, v)
            else:
                series[y] = v
                raws[y] = r.get(y, [])
                prov[y] = "primary" if i == 0 else tag
                tags[y] = tag
                if flipped:
                    _ladder_note(notes, y, "sign_flipped", tag, raw)
    return series, raws, prov, tags


def resolve_field_series(facts, spec, unit_keys=("USD",), ticker=None, baseline_tags=None):
    """Series for one field: primary winner, then backfill, then component sum.

    Returns (series, raws, provenance, tags). provenance[year] is "primary" | "backfill" |
    "component_sum" | "lone_depreciation"; tags[year] is the winning tag name (or a
    '+'-joined composite for component_sum years). Years resolved by SUMMATION have no single
    accession, so extract_history must exclude them from its accession-coverage vote -- a
    summed year cannot be attributed to one filing.
    """
    combined = list(spec.get("COMBINED") or [])
    # PRIMARY IS COMPUTED OVER THE ORIGINAL TAG LIST ONLY.
    # annual_duration_series picks max(candidates, key=(max_year, coverage)) over whatever list
    # it is handed, so passing the EXPANDED list changes which tag wins and can DROP years the
    # old winner covered. Measured when this was got wrong: 13 capex values vanished on LNKS and
    # LTM. Additions must therefore only ever BACKFILL; the currently-filled years stay
    # byte-identical by construction.
    # PER-FILER DENY (2026-08-21): a tag proven mislabeled AT A SPECIFIC FILER by reading its
    # cash-flow statement (FIX "DepreciationAndAmortization" == depreciation-only; ABNB
    # "DepreciationDepletionAndAmortization" likewise) is removed for that filer from BOTH the
    # primary vote and backfill, letting component sums / gated tags carry the field. Empty deny
    # dict must leave the build byte-identical.
    denied = spec.get("TICKER_DENY_TAGS") or {}
    deny = {t for t, tk in denied.items() if ticker in tk}
    base_tags = [t for t in (baseline_tags or combined[:1]) if t not in deny]
    series, raws, ptag = annual_duration_series(facts, base_tags, unit_keys)
    series = dict(series)
    raws = dict(raws)
    prov = {y: "primary" for y in series}
    tags = {y: ptag for y in series}          # winning tag per year, parallel to prov

    # BACKFILL -- only years the primary lacks, other combined tags, latest/most-coverage first.
    gated = spec.get("TICKER_GATED_TAGS") or {}       # CH-4: tag usable only for named tickers
    alts = []
    for tag in combined:
        if tag in deny:
            continue                                   # per-filer denied tag -> skip entirely
        if tag in gated and ticker not in gated[tag]:
            continue                                   # gated tag, wrong ticker -> skip entirely
        s, r, _ = annual_duration_series(facts, [tag], unit_keys)
        if s:
            alts.append((max(s), len(s), s, r, tag))
    for _, _, s, r, tag in sorted(alts, key=lambda z: (-z[0], -z[1])):
        for y, v in s.items():
            if y not in series:
                series[y], raws[y], prov[y] = v, r.get(y, []), "backfill"
                tags[y] = tag

    slots = spec.get("COMPONENT_SLOTS") or []
    if slots:
        slot_series = []
        slot_tags = []
        for slot in slots:
            merged = {}
            mtags = {}
            for tag in slot:
                s, _, _ = annual_duration_series(facts, [tag], unit_keys)
                for y, v in s.items():
                    # CH-5: prefer the first NON-ZERO alternative — a 0-valued tag must not beat a
                    # later non-zero one in the same slot (LIVN AmortizationOfIntangibleAssets = 0
                    # for 2019/2020 while real amortization exists under an alternative).
                    if merged.get(y) in (None, 0) and v is not None:
                        merged[y] = v
                        mtags[y] = tag
            slot_series.append(merged)
            slot_tags.append(mtags)
        years = set()
        for s in slot_series:
            years |= set(s)
        for y in sorted(years):
            if y in series:
                continue                              # combined always wins outright
            vals = [s.get(y) for s in slot_series]
            # EVERY slot must resolve, and no negative contribution: RL 2009 files
            # Depreciation = -164.2M against a true 184.4M.
            if all(v is not None and v >= 0 for v in vals):
                series[y], raws[y], prov[y] = sum(vals), [], "component_sum"
                # composite tag marks a cell with no single filed tag (excluded from overlap tests)
                tags[y] = "+".join(slot_tags[i][y] for i in range(len(slot_series)))
        allow = spec.get("LONE_DEPRECIATION_ALLOWLIST") or set()
        if ticker in allow and len(slot_series) >= 2 and not slot_series[1]:
            for y, v in slot_series[0].items():
                if y not in series and v is not None and v >= 0:
                    series[y], raws[y], prov[y] = v, [], "lone_depreciation"
                    tags[y] = slot_tags[0][y]
    return series, raws, prov, tags


def annual_duration_series(facts, tags, unit_keys=("USD",), scale_defence=True):
    """(fiscal_year -> value, fiscal_year -> [(accn, filed, val), ...]) for ~12-month-duration
    facts from annual filings.

    Tag selection: most RECENT latest-year wins, then most coverage. Tags are
    never mixed within one series — companies switch tags over time (e.g.
    Revenues -> RevenueFromContractWithCustomer...), and both first-tag-wins
    and coverage-only selection picked stale tags (AAPL's SalesRevenueNet has
    11 old years but ends in 2017).

    The second return value carries the WINNING tag's raw per-year candidates with their
    accession ids, so extract_history can assemble each year-row from ONE filing (see the
    row-consistency note there). The resolved series itself is unchanged from the previous
    behaviour. `scale_defence=False` (per-share fields) skips the power-of-1000 tie-break and series
    normalisation: a period's value is the latest filed.
    """
    candidates = []
    for tag in tags:
        units = facts.get(tag, {}).get("units", {})
        best = {}
        raw = {}
        for uk in unit_keys:
            for e in units.get(uk, []):
                if e.get("form") not in ANNUAL_FORMS:
                    continue
                start, end = e.get("start"), e.get("end")
                val = e.get("val")
                if not start or not end or val is None:
                    continue
                try:
                    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                except ValueError:
                    continue
                if not 300 <= days <= 400:
                    continue
                year = int(end[:4])
                best.setdefault(year, []).append((e.get("filed"), val))
                raw.setdefault(year, []).append((e.get("accn") or "", e.get("filed") or "",
                                                 val, end))
        if best and not scale_defence:
            candidates.append(({y: max(c, key=lambda z: z[0] or "")[1] for y, c in best.items()}, raw, tag))
        elif best:
            # resolve per-period scale contradictions, then normalise the whole series
            prelim = {y: max(c, key=lambda z: z[0] or "")[1] for y, c in best.items()}
            clean = {y: v for y, v in prelim.items()
                     if sum(1 for _, vv in best[y] if vv is not None) == 1}
            _refvals = [abs(v) for v in clean.values() if v]
            ref = statistics.median(_refvals) if _refvals else None
            resolved = {y: _pick_consistent(c, ref) for y, c in best.items()}
            candidates.append((_normalise_series_scale(resolved), raw, tag))
    if not candidates:
        return {}, {}, None
    # winner selection stays on s[0] (series) ONLY — never on the appended tag string;
    # tuple comparison reaching the tag is the documented 13-capex-loss trap.
    return max(candidates, key=lambda s: (max(s[0]), len(s[0])))


def annual_instant_series(facts, tags, unit_keys=("USD",)):
    """(fiscal_year -> value, fiscal_year -> [(accn, filed, val), ...]) for balance-sheet
    (instant) facts from annual filings.

    Same recency-then-coverage tag selection — and the same raw-candidate side channel —
    as annual_duration_series.
    """
    candidates = []
    for tag in tags:
        units = facts.get(tag, {}).get("units", {})
        best = {}
        raw = {}
        for uk in unit_keys:
            for e in units.get(uk, []):
                if e.get("form") not in ANNUAL_FORMS:
                    continue
                end = e.get("end")
                val = e.get("val")
                if not end or val is None:
                    continue
                year = int(end[:4])
                best.setdefault(year, []).append(((end, e.get("filed") or ""), val))
                raw.setdefault(year, []).append((e.get("accn") or "", e.get("filed") or "",
                                                 val, end))
        if best:
            prelim = {y: max(c, key=lambda z: z[0])[1] for y, c in best.items()}
            clean = {y: v for y, v in prelim.items()
                     if sum(1 for _, vv in best[y] if vv is not None) == 1}
            _refvals = [abs(v) for v in clean.values() if v]
            ref = statistics.median(_refvals) if _refvals else None
            resolved = {y: _pick_consistent([(k[1], v) for k, v in c], ref)
                        for y, c in best.items()}
            candidates.append((_normalise_series_scale(resolved), raw, tag))
    if not candidates:
        return {}, {}, None
    # winner selection stays on s[0] (series) ONLY — see annual_duration_series note.
    return max(candidates, key=lambda s: (max(s[0]), len(s[0])))


QUARTERLY_FORMS = ("10-Q", "10-Q/A")
# Flow fields the RS2 base_cf needs fresh (owner earnings = NI + D&A − capex; blend adds revenue;
# fcf derived). Balance-sheet items and averages (shares_diluted is a weighted average — NOT
# additive, the FY + YTD − YTD identity does not hold for it) are deliberately excluded.
TTM_FIELDS = ("revenue", "net_income", "ocf", "capex", "da")


def ttm_snapshot(facts):
    """Trailing-twelve-month flows from 10-Q YTD rows: TTM = FY + YTD_cur − YTD_prior.

    Validated against HWM before implementation (2026-08-08): the zip carries YTD duration rows
    for every needed tag through the 10-Q filed 2026-08-06, and the identity reproduces the
    hand-computed TTM. Date guards make the identity exact rather than approximate:
      * YTD rows start at the fiscal-year start by construction; the current YTD leg must start
        the day after the FY leg ends (±5d), and the prior YTD leg must cover the same fiscal
        span one year earlier (end 350-380d before, duration within 14d of the current leg).
      * Tag selection mirrors annual_duration_series' recency-then-coverage rule and NEVER mixes
        tags across the three legs (HWM's "Revenues" tag is dead — 0 annual rows, 10-Q rows
        ending 2019 — so first-tag-wins would bridge live and dead series).
      * Same-period duplicate filings resolve via _pick_consistent against the annual median,
        and each leg is pow-1000 checked against that median (same scale defence as the annual
        series; magnitude-vs-series filters stay banned — see the scale-error note above).
    A field with no complete triple is absent — honest absence, the engine falls back to FY.
    Returns {"through", "filed", "fy_leg_end", "fields": {...}} or None if nothing computed.
    """
    out = {}
    prov = None
    bank = bank_net_revenue_filer(facts)       # a bank P&L filer's revenue is NII + noninterest income

    def duration_entries(tag):
        entries = []
        for e in facts.get(tag, {}).get("units", {}).get("USD", []):
            start, end, val = e.get("start"), e.get("end"), e.get("val")
            if not start or not end or val is None:
                continue
            try:
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError:
                continue
            entries.append({"form": e.get("form"), "start": start, "end": end,
                            "days": days, "val": val, "filed": e.get("filed") or ""})
        return entries

    # Newest annual period end across EVERY TTM tag of the company — the freshness bar below.
    # It must be company-wide, not per-tag: right after a 10-K the live tag correctly yields
    # nothing, and a DEAD tag (old 10-Qs, older 10-Ks) would then pass a per-tag check and
    # win with a years-old "TTM" (2026-08-21: EL's live 10-K produced through=2017-03-31;
    # 98 production rows — MDT 2015-07-31, PAYX 2017-11-30 — carried the same defect).
    newest_fy_end = ""
    for field in TTM_FIELDS:
        for tag in DURATION_TAGS[field]:
            for e in duration_entries(tag):
                if e["form"] in ANNUAL_FORMS and 300 <= e["days"] <= 400 and e["end"] > newest_fy_end:
                    newest_fy_end = e["end"]

    def tag_cand(tag):
        """The TTM candidate of ONE tag (all three legs from it), or None."""
        entries = duration_entries(tag)
        ann = [e for e in entries if e["form"] in ANNUAL_FORMS and 300 <= e["days"] <= 400]
        qtd = [e for e in entries if e["form"] in QUARTERLY_FORMS and 60 <= e["days"] <= 300]
        if not ann or not qtd:
            return None
        # TTM must be FRESHER than the newest annual period: right after a 10-K (no newer
        # 10-Q yet) the formula would happily emit a TTM through last Q3 — STALER than the
        # FY the engine already has, silently presented as fresher.
        if max(e["end"] for e in qtd) <= newest_fy_end:
            return None
        ann_med = statistics.median(abs(e["val"]) for e in ann)

        def resolve(rows):
            # duplicate filings of the SAME period -> scale-consistent pick
            return _pick_consistent([(r["filed"], r["val"]) for r in rows], ann_med)

        # current leg: YTD row with the latest end (max duration at that end wins the
        # quarterly-vs-YTD tie; at Q1 they are the same row)
        end_cur = max(e["end"] for e in qtd)
        cur_rows = [e for e in qtd if e["end"] == end_cur]
        dmax = max(e["days"] for e in cur_rows)
        cur_rows = [e for e in cur_rows if abs(e["days"] - dmax) <= 3]
        cur = dict(cur_rows[0]); cur["val"] = resolve(cur_rows)
        # FY leg: latest annual period ending before the current YTD starts, adjacent to it
        fy_rows = [e for e in ann if e["end"] < cur["start"]]
        if not fy_rows:
            return None
        fy_end = max(e["end"] for e in fy_rows)
        if not 0 <= (date.fromisoformat(cur["start"]) - date.fromisoformat(fy_end)).days <= 5:
            return None                        # current YTD does not start right after an FY
        fy_leg = [e for e in fy_rows if e["end"] == fy_end]
        fy = dict(fy_leg[0]); fy["val"] = resolve(fy_leg)
        # prior leg: same YTD span one fiscal year earlier
        pri_rows = [e for e in qtd
                    if abs(e["days"] - cur["days"]) <= 14
                    and 350 <= (date.fromisoformat(cur["end"])
                                - date.fromisoformat(e["end"])).days <= 380]
        if not pri_rows:
            return None
        pri_end = max(e["end"] for e in pri_rows)
        pri_rows = [e for e in pri_rows if e["end"] == pri_end]
        pri = dict(pri_rows[0]); pri["val"] = resolve(pri_rows)
        # per-leg scale defence: a leg a clean power of 1000 off the annual median is the
        # same corruption the annual series guards against
        legs = []
        for r in (fy, cur, pri):
            v = r["val"]
            p = _pow1000_ratio(ann_med, v)
            legs.append(v * p if p else v)
        ttm_val = legs[0] + legs[1] - legs[2]
        return {"val": ttm_val, "through": cur["end"], "filed": cur["filed"],
                "fy_leg_end": fy_end, "ann_years": len({e["end"][:4] for e in ann}),
                "pri_end": pri_end}

    cands = {}

    def cand_of(tag):
        if tag not in cands:
            cands[tag] = tag_cand(tag)
        return cands[tag]

    def combine(a, b, sign):
        """a + sign*b when both legs-triples cover the SAME windows (one rung, never mixed)."""
        if a is None or b is None:
            return None
        if (a["through"], a["fy_leg_end"], a["pri_end"]) != (b["through"], b["fy_leg_end"], b["pri_end"]):
            return None
        c = dict(a)
        c["val"] = a["val"] + sign * b["val"]
        return c

    def nci_cand(which):
        if which == "ifrs":
            return cand_of(NCI_LINE_IFRS)
        total = cand_of(NCI_LINE_US)
        return total if total is not None else combine(cand_of(NCI_SPLIT_US[0]), cand_of(NCI_SPLIT_US[1]), 1)

    for field in TTM_FIELDS:
        best = None
        if field == "net_income":
            # Fix 1a(d): the scope ladder; the first rung with a complete triple wins, all three legs
            # from that rung (a rung missing a leg is skipped for the next)
            pl = cand_of("ProfitLoss")
            for cand in (cand_of("NetIncomeLoss"), cand_of("ProfitLossAttributableToOwnersOfParent"),
                         combine(pl, nci_cand("us"), -1), combine(pl, nci_cand("ifrs"), -1), pl):
                if cand is not None:
                    best = cand
                    break
        elif field == "revenue" and bank:
            # bank net revenue: both components over the SAME windows, else absent; never a listed tag
            best = combine(cand_of(BANK_NII_TAG), cand_of(BANK_NONII_TAG), 1)
        else:
            for tag in DURATION_TAGS[field]:
                cand = cand_of(tag)
                if cand is None:
                    continue
                if best is None or (cand["through"], cand["ann_years"]) > (best["through"], best["ann_years"]):
                    best = cand
        if best is None:
            continue
        out[field] = best["val"]
        # provenance from the field with the freshest through-date (they should agree; the
        # engine-side audit cross-checks coverage)
        if prov is None or best["through"] > prov["through"]:
            prov = {"through": best["through"], "filed": best["filed"],
                    "fy_leg_end": best["fy_leg_end"]}
    if not out or prov is None:
        return None
    # Fix 1a(d): consolidated TTM net income on the history's rule (it never sets the snapshot's
    # through/filed): ProfitLoss; else a rung-1/2 parent + its NCI line; else the parent's figure when
    # no element of N is filed with a non-zero value inside the TTM window (a filed zero is evidence of
    # no NCI); else absent.
    incl = cand_of("ProfitLoss")
    if incl is None:
        for ptag, which in (("NetIncomeLoss", "us"), ("ProfitLossAttributableToOwnersOfParent", "ifrs")):
            pc = cand_of(ptag)
            if pc is None:
                continue
            incl = combine(pc, nci_cand(which), 1)
            if incl is None:
                lo = (date.fromisoformat(pc["fy_leg_end"]) - timedelta(days=366)).isoformat()
                if not any(lo <= end <= pc["through"] for end, _ in _nci_filed_ends(facts, nonzero_only=True)):
                    incl = pc
            break
    if incl is not None:
        out["net_income_incl_nci"] = incl["val"]
    ocf, capex = out.get("ocf"), out.get("capex")
    if ocf is not None and capex is not None:
        out["fcf"] = ocf - capex
    return {"through": prov["through"], "filed": prov["filed"],
            "fy_leg_end": prov["fy_leg_end"], "fields": out}


QTR_FIELDS = ("revenue", "net_income", "gross_profit")


def quarterly_snapshot(facts):
    """Last ~10 SINGLE QUARTERS of the core flow fields, with YoY — the regime-persistence
    evidence served from filings instead of hoped-for from news (AMD 2026-08: a fresh,
    healthy-looking research brief carried none of the +50%/+107% record quarter that had
    been public for three days; filings cannot miss their own numbers).

    Single quarters come from 10-Q duration rows (60-120d). Q4 has no 10-Q: derived as
    FY − YTD-Q3 when both legs share the fiscal-year start (same date guards as the TTM
    identity). Same per-period scale resolution as everywhere else. Returns
    {"quarters": [{"end", "revenue", "net_income", "gross_profit", "yoy_revenue",
    "yoy_net_income"}, ...]} oldest->newest, or None."""
    def tag_q(tag):
        """{quarter end: single-quarter value} of ONE tag, or None."""
        entries = []
        for e in facts.get(tag, {}).get("units", {}).get("USD", []):
            start, end, val = e.get("start"), e.get("end"), e.get("val")
            if not start or not end or val is None:
                continue
            try:
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError:
                continue
            entries.append({"form": e.get("form"), "start": start, "end": end,
                            "days": days, "val": val, "filed": e.get("filed") or ""})
        singles = {}
        for e in entries:
            if e["form"] in QUARTERLY_FORMS and 60 <= e["days"] <= 120:
                singles.setdefault(e["end"], []).append((e["filed"], e["val"]))
        ann = [e for e in entries if e["form"] in ANNUAL_FORMS and 300 <= e["days"] <= 400]
        if not singles or not ann:
            return None
        ann_med = statistics.median(abs(e["val"]) for e in ann)
        q = {end: _pick_consistent(c, ann_med) for end, c in singles.items()}
        # derived Q4 = FY − YTD-Q3 (YTD row ending 76-104d before the FY end, same start)
        ytd3 = {}
        for e in entries:
            if e["form"] in QUARTERLY_FORMS and 240 <= e["days"] <= 300:
                ytd3.setdefault(e["end"], []).append((e["filed"], e["val"], e["start"]))
        for fy_e in ann:
            if fy_e["end"] in q:
                continue
            for y_end, cands in ytd3.items():
                try:
                    gap = (date.fromisoformat(fy_e["end"]) - date.fromisoformat(y_end)).days
                except ValueError:
                    continue
                if 76 <= gap <= 104 and any(c[2] == fy_e["start"] for c in cands):
                    yv = _pick_consistent([(c[0], c[1]) for c in cands], ann_med)
                    q[fy_e["end"]] = fy_e["val"] - yv
                    break
        return q

    def combine(a, b, sign):
        if a is None or b is None:
            return None
        return {e: a[e] + sign * b[e] for e in a if e in b}

    per_field = {}
    bank = bank_net_revenue_filer(facts)       # a bank P&L filer's revenue is NII + noninterest income
    for field in QTR_FIELDS:
        if field == "revenue" and bank:
            # bank net revenue per quarter, never a listed tag; no quarter in common -> no revenue, and
            # the snapshot is None below exactly as for any filer without revenue
            q = combine(tag_q(BANK_NII_TAG), tag_q(BANK_NONII_TAG), 1)
            if q:
                per_field[field] = q
            continue
        if field == "net_income":
            # Fix 1a(d): the scope ladder per quarter — the first rung with the quarter wins it
            pl = tag_q("ProfitLoss")
            nci_us = combine(tag_q(NCI_SPLIT_US[0]), tag_q(NCI_SPLIT_US[1]), 1) or {}
            nci_us.update(tag_q(NCI_LINE_US) or {})            # the total line wins its quarters
            merged = {}
            for rung in (tag_q("NetIncomeLoss"), tag_q("ProfitLossAttributableToOwnersOfParent"),
                         combine(pl, nci_us, -1), combine(pl, tag_q(NCI_LINE_IFRS), -1), pl):
                for e, v in (rung or {}).items():
                    merged.setdefault(e, v)
            if merged:
                per_field[field] = merged
            continue
        best = None
        for tag in DURATION_TAGS[field]:
            q = tag_q(tag)
            if q is None:
                continue
            cand = {"q": q, "latest": max(q), "n": len(q)}
            if best is None or (cand["latest"], cand["n"]) > (best["latest"], best["n"]):
                best = cand
        if best:
            per_field[field] = best["q"]
    if "revenue" not in per_field:
        return None
    ends = sorted(set().union(*[set(v) for v in per_field.values()]))[-10:]
    rows = []
    for e in ends:
        rows.append({"end": e, **{f: per_field.get(f, {}).get(e) for f in QTR_FIELDS}})
    for i, r in enumerate(rows):
        try:
            e0 = date.fromisoformat(r["end"])
        except ValueError:
            continue
        for p in rows[:i]:
            try:
                lag = (e0 - date.fromisoformat(p["end"])).days
            except ValueError:
                continue
            if 350 <= lag <= 380:
                for f, k in (("revenue", "yoy_revenue"), ("net_income", "yoy_net_income")):
                    # YoY off a NEGATIVE/zero base is meaningless (the exact -17.5%-CAGR trap
                    # the auditor caught the model committing on ARWR) — omit, never invent
                    if r.get(f) and p.get(f) and p[f] > 0:
                        r[k] = round((r[f] / p[f] - 1) * 100, 1)
    return {"quarters": rows} if rows else None


# ── Share-count scale slip, proven from the SAME filing (P-2) ────────────────────────────────
# A filer can tag its diluted share count in thousands (or millions) with no second filing to
# contradict it, so the per-period and series defences above never see it. The cell is rescaled
# only on SEC evidence from the filing that carries it -- never from the vendor's numbers:
#   1. EPS identity: net income / (filed diluted EPS x shares) is a power of 1000 (band 0.7-1.4);
#      when it lies in [0.7, 1.4] itself it AFFIRMS the count and nothing else is tried
#   2. cover page:   dei:EntityCommonStockSharesOutstanding (classes summed) / shares likewise,
#      only when the EPS identity is missing or inconclusive
# Anything else is left unchanged. The correction rides as a state on the cell
# (provenance.scale_corrected: "e" = EPS identity, "c" = cover count); the base provenance runs
# are untouched.
SCALE_FIX_KS = (-2, -1, 1, 2)
SHARES_COVER_TAG = "EntityCommonStockSharesOutstanding"


def _scale_k(ratio):
    """k in SCALE_FIX_KS when ratio lies in [0.7, 1.4] x 1000**k, else None."""
    if ratio is None or not ratio > 0:
        return None
    for k in SCALE_FIX_KS:
        p = 1000.0 ** k
        if 0.7 * p <= ratio <= 1.4 * p:
            return k
    return None


def _rescale(value, k):
    out = value * 1000 ** k if k > 0 else value / 1000 ** -k
    if isinstance(value, int) and float(out).is_integer():
        return int(out)
    return out


def correct_share_scale(shares, net_income, eps_diluted, cover):
    """(value, state) for one fiscal-year shares_diluted cell; state is None when unchanged."""
    if not isinstance(shares, (int, float)) or not shares > 0:
        return shares, None
    if net_income is not None and net_income != 0 and eps_diluted is not None and eps_diluted != 0:
        ratio = net_income / (eps_diluted * shares)
        k = _scale_k(ratio)
        if k is not None:
            return _rescale(shares, k), "scale_corrected_eps"
        if 0.7 <= ratio <= 1.4:
            return shares, None        # the identity AFFIRMS the count: the cover test does not run
    if cover is not None and cover > 0:
        k = _scale_k(cover / shares)
        if k is not None:
            return _rescale(shares, k), "scale_corrected_cover"
    return shares, None


def _filed_diluted_eps(facts, accn, near):
    """The diluted EPS filing `accn` reports for the cell's period, or None (none, or two values)."""
    vals = set()
    for e in facts.get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", []):
        if e.get("accn") != accn or e.get("form") not in ANNUAL_FORMS:
            continue
        start, end, val = e.get("start"), e.get("end"), e.get("val")
        if not start or not end or not isinstance(val, (int, float)):
            continue
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            continue
        if 300 <= days <= 400 and near(end):
            vals.add(val)
    return vals.pop() if len(vals) == 1 else None


def _filing_cover_count(dei, accn):
    """Cover-page share count of filing `accn`, classes summed, or None."""
    vals = [e["val"] for e in (dei or {}).get(SHARES_COVER_TAG, {}).get("units", {}).get("shares", [])
            if e.get("accn") == accn and isinstance(e.get("val"), (int, float))]
    total = sum(vals)
    return total if vals and total > 0 else None


def latest_shares_cover(dei):
    """{"val", "date", "filed"} for the latest filing's cover count (classes summed), or None."""
    ents = [e for e in (dei or {}).get(SHARES_COVER_TAG, {}).get("units", {}).get("shares", [])
            if e.get("filed") and e.get("accn") and isinstance(e.get("val"), (int, float))]
    if not ents:
        return None
    last = max(ents, key=lambda e: (e["filed"], e.get("end") or ""))
    same = [e for e in ents if e["accn"] == last["accn"]]
    total = sum(e["val"] for e in same)
    if not total > 0:
        return None
    return {"val": total, "date": max(e.get("end") or "" for e in same) or None, "filed": last["filed"]}


def _shares_cell_accn(cands, value, override_accn, chosen, near):
    """The accession that carries the shares cell: the override, else the latest filing whose raw
    value IS the cell, else the row's chosen accession, else the latest near-period candidate."""
    if override_accn:
        return override_accn
    cands = [c for c in cands if near(c[3])]
    same = [c for c in cands if c[2] == value]
    if same:
        return max(same, key=lambda c: c[1])[0]
    if chosen is not None and any(c[0] == chosen for c in cands):
        return chosen
    return max(cands, key=lambda c: c[1])[0] if cands else None


def _subtract_nci(pl, dv, pl_raws, override_accn, near):
    """(parent net income, NCI used) for a rung 3/4 year: ProfitLoss as the row arbitration chose it,
    minus the NCI line of the SAME accession (the override's, else the latest filing whose raw ProfitLoss
    is that value) when that accession holds one for the period, else the NCI line's series value."""
    accn = override_accn
    if accn is None:
        same = [c for c in pl_raws if c[2] == pl and near(c[3])]
        accn = max(same, key=lambda c: c[1])[0] if same else None
    nci = dv["nci"]
    if accn is not None:
        cand = [c for c in dv["nci_raws"] if c[0] == accn and near(c[3])]
        if cand:
            nci = (_pick_consistent([(c[1], c[2]) for c in cand], dv["nci"])
                   if len({c[2] for c in cand}) > 1 else cand[0][2])
    return pl - nci, nci


def extract_history(facts, ticker=None, dei=None):
    """Build {fiscal_year: {field: value}} from a CIK's us-gaap facts.

    `dei` (the companyfacts "dei" namespace) is optional: without it the cover-count test of the
    share-scale correction does not run.
    """
    series = {}
    raws = {}
    # Provenance captured alongside every field: base state (primary/backfill/component_sum/
    # lone_depreciation) and the winning tag name per year. Emitted as a parallel top-level
    # "provenance" sibling in main() — never inside a year-row (the int(year) reader hazard).
    prov_of = {}          # field -> {year: base_state}
    tag_of = {}           # field -> {year: winning_tag}
    for field, tags in DURATION_TAGS.items():
        unit = ("shares",) if field == "shares_diluted" else ("USD",)
        if field == "net_income":                                 # Fix 1a: scope ladder, not the vote
            (series[field], raws[field], prov_of[field], tag_of[field],
             ni_scope, ni_derived, ni_incl) = resolve_net_income_series(facts)
            continue
        spec = FIELD_SPECS.get(field)
        if spec:
            # `tags` is the ORIGINAL DURATION_TAGS list — it defines the primary winner, so the
            # existing output is preserved exactly and FIELD_SPECS can only add.
            series[field], raws[field], prov_of[field], tag_of[field] = resolve_field_series(
                facts, spec, unit, ticker, baseline_tags=tags)
        else:
            series[field], raws[field], wtag = annual_duration_series(facts, tags, unit)
            prov_of[field] = {y: "primary" for y in series[field]}
            tag_of[field] = {y: wtag for y in series[field]}
    money, securities_segregated = resolve_money_fields(facts)    # item 4: the family-rule fields
    for field, tags in INSTANT_TAGS.items():
        if field == "equity":                                     # Fix 1a: the parent's, by ladder
            series[field], raws[field], prov_of[field], tag_of[field], equity_scope = \
                resolve_equity_series(facts)
            continue
        if field == "cash":                                       # Fix 2a: the unrestricted line
            series[field], raws[field], prov_of[field], tag_of[field], cash_scope = \
                resolve_cash_series(facts, money["cash_restricted"][0], securities_segregated)
            continue
        series[field], raws[field], wtag = annual_instant_series(facts, tags)
        prov_of[field] = {y: "primary" for y in series[field]}
        tag_of[field] = {y: wtag for y in series[field]}
    notes_of = {}         # R17 field -> {year: [ladder notes]}; emitted as provenance `ladder_notes`
    for field, ispec in INSTANT_FIELD_SPECS.items():          # CH-9 debt components (ladder-resolved)
        series[field], raws[field], prov_of[field], tag_of[field] = \
            resolve_instant_field_series(facts, ispec, ticker,
                                         notes=notes_of.setdefault(field, {}) if field in R17_FIELDS else None)
    for field, dspec in DURATION_LADDER_SPECS.items():        # R17 amortization of intangibles
        series[field], raws[field], prov_of[field], tag_of[field] = \
            resolve_duration_ladder_series(facts, dspec, dspec.get("UNITS", ("USD",)),
                                           notes=notes_of.setdefault(field, {}))
    # Fix 1a(b) / 2a(b): new fields (vote-excluded, so they never choose a row's accession)
    series["net_income_incl_nci"], raws["net_income_incl_nci"], prov_of["net_income_incl_nci"], \
        tag_of["net_income_incl_nci"] = ni_incl
    series["equity_incl_nci"], raws["equity_incl_nci"], prov_of["equity_incl_nci"], \
        tag_of["equity_incl_nci"], eq_incl_rung = resolve_equity_incl_nci_series(facts)
    for field, (ms, mr, mp, mt) in money.items():              # the family-rule fields (item 4)
        series[field], raws[field], prov_of[field], tag_of[field] = ms, mr, mp, mt
    for field, tlist in INSTANT_SUM_FIELDS.items():
        series[field], raws[field], prov_of[field], tag_of[field] = resolve_instant_sum_series(facts, tlist)
    if ticker in DEBT_NULL_TICKERS:                           # declared STOP (NVS): null debt fields
        for field in ("debt_lt_noncurrent", "debt_current"):
            series[field], raws[field], prov_of[field], tag_of[field] = {}, {}, {}, {}

    # Vote-excluded fields (CH-7/CH-9) still get resolved and still receive the chosen accession's
    # correction, but do NOT vote in the accession-coverage rule and cannot form/evict a year-row.
    VOTE_FIELDS = [f for f in series if f not in VOTE_EXCLUDED_FIELDS]
    # INVESTING CLOSURE (capex): proven values for years no FIELD_SPECS mechanism filled. Applied in the
    # row loop below, never through series/raws, so they cannot vote or move another cell.
    closure_lines = {}
    closure = (resolve_capex_by_closure(facts, set(), closure_lines)
               if FIELD_SPECS["capex"].get("INVESTING_CLOSURE") else {})
    # The accession vote and the bin-end anchor read the candidate pools the vote read BEFORE the scope
    # fixes (follow-up item 1): the filing calendar and the choice of a row's accession are properties of
    # the filings, not of a field's accounting scope. For net_income, cash and equity those pools are
    # recomputed as the previous vote resolved them; the per-cell override below still reads the scope
    # rung's own raws (the chosen accession's candidate of the rung's tag is used when it holds one,
    # otherwise the rung's value stays).
    vote_raws = dict(raws)
    vote_raws["net_income"] = resolve_field_series(
        facts, FIELD_SPECS["net_income"], ("USD",), ticker, baseline_tags=DURATION_TAGS["net_income"])[1]
    for f in ("equity", "cash"):
        vote_raws[f] = annual_instant_series(facts, INSTANT_TAGS[f])[1]
    # BANK NET REVENUE: the two components are resolved here, outside `series`/`raws`/`vote_raws` (as the
    # capex closure is), and applied in the row loop below; a bank P&L filer's listed revenue is refused.
    bank_filer = bank_net_revenue_filer(facts)
    bank_parts = ({t: annual_duration_series(facts, [t], ("USD",))[:2] for t in (BANK_NII_TAG, BANK_NONII_TAG)}
                  if bank_filer else {})

    # WINDOW ANCHOR. A row survives only if it has revenue or total_assets, but the MAX_YEARS
    # truncation runs BEFORE that gate — so a field whose coverage runs past revenue's (an IFRS
    # filer's WeightedAverageShares over years it files no USD revenue; CH-3's stitching widened
    # this for TM: shares 2010-2025 vs USD revenue 2012-2013 only) would evict the only revenue-
    # bearing years and drop the whole ticker. Anchor the window on the row-forming fields; every
    # other field is a passenger that fills a row it cannot create, and non-forming years are
    # dropped by the gate regardless. Provably loss-free: the surviving rows are a superset of the
    # old ones (any old row-year is formable and, being among the recent union years, is among the
    # recent formable years too). Same eviction the CH-7 st/lt years-union exclusion prevents.
    if not any(series.get(f) for f in series):
        return {}, None
    form_years = set(series.get("revenue", {})) | set(series.get("total_assets", {}))
    if not form_years:
        return {}, None
    years = sorted(form_years)[-MAX_YEARS:]

    history = {}
    overrides = {}        # {str(year): {field: chosen_accession}} for accession-vote overrides
    period_end = {}       # {str(year): "YYYY-MM-DD"} bin-end anchor
    scale_corrected = {}  # {str(year): {"shares_diluted": state}} P-2 share-scale corrections
    nci_used = {}         # {str(year): NCI amount a rung 3/4 subtraction used} (Fix 1a)
    for y in years:
        # ── ROW CONSISTENCY (2026-08-08) ────────────────────────────────────────────────
        # Per-field most-recent-wins mixes FILING BASES inside one row: after a divestiture
        # the next 10-K restates comparative revenue to continuing operations, while net
        # income under our tags keeps the original consolidated figure — WDC FY2023 ended up
        # with HDD-only revenue ($6.25B, restated) against the consolidated flash-crash loss
        # (−$1.68B), a margin of two different companies. Measured across the live book: 314
        # basis-suspect conflicts (>30% or sign-flip) on 88 tickers, and no filed-date
        # preference survives them all (original-first breaks ASC-606-style restatements
        # where the later figure is better; latest-first is what mixed WDC). So instead of
        # judging vintages, assemble each year-row from ONE filing: the accession covering
        # the most fields (tie -> latest filed). The per-period/series scale defences above
        # stay authoritative: an accession value that contradicts the resolved series by a
        # clean power of 1000 is refused (COHR-class corrupt filings must not win a row),
        # and a zero contradicted by a nonzero resolved value is a filing artifact (PSMT
        # revenue 0 vs $2.5B), not data.
        # BIN-END ANCHOR. Year bins are calendar end-year (int(end[:4])), and fiscal years
        # ending Jan 1-2 COLLIDE with the prior year's bin: without this anchor the accession-
        # coverage rule installed JNJ FY2016's $16.54B net income as "2017" (JNJ FY2016 ended
        # 2017-01-01), ILMN's FY2022 GRAIL-impairment loss as "2023", YETI FY2021 as "2022" —
        # found by diffing the full rebuild against the previous production file. The bin's
        # canonical period end is its LATEST end date (deterministic — a filed-date anchor
        # ties, because one later 10-K carries BOTH years as comparatives under one filed
        # date): the collision candidate always ends Jan 1-2 of year y, the bin's own fiscal
        # year always ends later in y. Only candidates within 14 days of the anchor may join
        # the accession vote.
        end_ref = None
        for f in VOTE_FIELDS:
            for accn, filed, val, end in vote_raws[f].get(y, []):
                if end_ref is None or end > end_ref:
                    end_ref = end
        if end_ref is not None:
            period_end[str(y)] = end_ref

        def _near_ref(end):
            if end_ref is None:
                return True
            try:
                return abs((date.fromisoformat(end) - date.fromisoformat(end_ref)).days) <= 14
            except ValueError:
                return False

        accns = {}
        for f in VOTE_FIELDS:
            for accn, filed, val, end in vote_raws[f].get(y, []):
                if not _near_ref(end):
                    continue
                a = accns.setdefault(accn, {"fields": set(), "filed": ""})
                a["fields"].add(f)
                a["filed"] = max(a["filed"], filed)
        # Among near-complete accessions, the LATEST wins — measured on the two conflicting
        # classes (2026-08-08): an ERROR restatement re-tags the whole comparative row (Macy's
        # FY-Feb-2024: original 10-K and the restated next-10-K comparative both ~100% field
        # coverage — the later, corrected $45M row must win over the original $105M), while a
        # PERIMETER restatement re-tags a sparse subset (WDC FY2023 post-spin comparative: 48%
        # coverage — excluded, so the row stays consolidated and internally consistent).
        # Coverage-first-then-filed inverted the M case; pure-latest would let WDC's 48% row
        # fragment mix again. The 0.8 bar separates the measured populations.
        chosen = None
        if accns:
            mx = max(len(a["fields"]) for a in accns.values())
            elig = {k: a for k, a in accns.items() if len(a["fields"]) >= 0.8 * mx}
            chosen = max(elig, key=lambda k: (elig[k]["filed"], len(elig[k]["fields"])))
        row = {}
        for f in series:
            v = series[f].get(y)
            dv = ni_derived.get(y) if f == "net_income" else None
            if dv is not None:
                v = dv["pl"]       # Fix 1a rung 3/4: the override arbitrates ProfitLoss's candidates
            if chosen is not None and v is not None:
                cand = [c for c in raws[f].get(y, [])
                        if c[0] == chosen and _near_ref(c[3])]
                if cand:
                    if f in SCALE_EXEMPT_FIELDS:
                        av = max(cand, key=lambda c: c[1])[2]
                    elif len({c[2] for c in cand}) > 1:
                        av = _pick_consistent([(c[1], c[2]) for c in cand], v)
                    else:
                        av = cand[0][2]
                    # SCALE-OVERWRITE ARBITRATION (CH-2). av (accession) and v (resolved series)
                    # are UNORDERED here, so the old guard `_pow1000_ratio(av, v)` (which assumes
                    # largest-first) had a directional hole that reinstated a raw-thousands
                    # accession value over an already scale-corrected series (GRMN shares 194,165
                    # over 194,165,000). Order-correct the ratio; when the two ARE a clean
                    # power-of-1000 apart, let the series median decide which sits on the series'
                    # own scale (keeps the correct NHC 2023 sga 21,412,000 over a 21.4T resolved
                    # value; a symmetric band alone would ship the 21.4T).
                    # A2: an accession may not put a negative back into an R17 field (a balance or
                    # amortization is never negative; the ladder already refused/flipped those).
                    if av != v and not (av == 0 and v) and not (f in R17_FIELDS and av < 0):
                        _ref = _series_median(series[f])
                        _take = False
                        if f in SCALE_EXEMPT_FIELDS:      # per-share: no scale slip to arbitrate
                            _take = True
                        elif _pow1000_ratio(max(av, v, key=abs), min(av, v, key=abs)) is None:
                            _take = True
                        elif _ref and abs(math.log10(max(abs(av), 1e-9) / _ref)) < \
                                     abs(math.log10(max(abs(v), 1e-9) / _ref)):
                            _take = True
                        if _take:
                            v = av
                            # fifth state, layered over base: value came from the chosen accession.
                            overrides.setdefault(str(y), {})[f] = chosen
            if dv is not None and v is not None:
                v, nci_used[str(y)] = _subtract_nci(v, dv, raws[f].get(y, []),
                                                    overrides.get(str(y), {}).get(f), _near_ref)
            row[f] = v
        hit = closure.get(y, {}).get(chosen) if chosen is not None else None
        if hit is not None and row.get("capex") is None and _near_ref(hit[2]):
            row["capex"] = hit[0]
            prov_of["capex"][y] = "closure_sum"
            tag_of["capex"][y] = hit[1]
        elif (FIELD_SPECS["capex"].get("CLOSURE_REPLACES_FILLED")
              and hit is not None and row.get("capex") is not None and hit[0] > row["capex"]
              and _near_ref(hit[2])
              # no other filing may prove a DIFFERENT figure for the same period (restatements,
              # re-presentations and coincidental closures disagree across filings: DVN 2015-2018)
              and all(p[0] == hit[0] for a, p in closure.get(y, {}).items() if p[2] == hit[2])
              and _replacement_allowed(closure_lines[(chosen, hit[2])], row["capex"],
                                       tag_of["capex"].get(y) if any(
                                           c[0] == chosen and c[2] == 0 and _near_ref(c[3])
                                           for c in raws["capex"].get(y, [])) else None)):
            row["capex"] = hit[0]
            prov_of["capex"][y] = "closure_replaced"
            tag_of["capex"][y] = hit[1]
            if overrides.get(str(y), {}).pop("capex", None) is not None and not overrides[str(y)]:
                del overrides[str(y)]
        if bank_filer:
            # The listed revenue the loop above resolved is REFUSED for a bank P&L filer in every year
            # (an ASC 606 fee slice beside net revenue in the next year would manufacture growth); the
            # row's revenue is its net revenue, null when either component is missing for the period.
            nii, nonii = (_bank_component_value(y, *bank_parts[t], chosen, _near_ref)
                          for t in (BANK_NII_TAG, BANK_NONII_TAG))
            row["revenue"] = None if nii is None or nonii is None else nii + nonii
            if overrides.get(str(y), {}).pop("revenue", None) is not None and not overrides[str(y)]:
                del overrides[str(y)]
            if row["revenue"] is None:
                prov_of["revenue"].pop(y, None)
                tag_of["revenue"].pop(y, None)
            else:
                prov_of["revenue"][y] = "bank_net_revenue"
                tag_of["revenue"][y] = BANK_REVENUE_TAG
        # Require at least a revenue or assets figure for the year to count
        if row.get("revenue") is None and row.get("total_assets") is None:
            continue
        sh = row.get("shares_diluted")
        if isinstance(sh, (int, float)) and sh > 0:
            a = _shares_cell_accn(raws["shares_diluted"].get(y, []), sh,
                                  overrides.get(str(y), {}).get("shares_diluted"), chosen, _near_ref)
            if a is not None:
                eps = _filed_diluted_eps(facts, a, _near_ref)
                new, state = correct_share_scale(sh, row.get("net_income"), eps,
                                                 _filing_cover_count(dei, a))
                if state:
                    row["shares_diluted"] = new
                    scale_corrected.setdefault(str(y), {})["shares_diluted"] = state
        ocf, capex = row.get("ocf"), row.get("capex")
        row["fcf"] = (ocf - capex) if (ocf is not None and capex is not None) else None
        history[y] = row
    prov_bundle = {"states": prov_of, "tags": tag_of,
                   "overrides": overrides, "period_end": period_end,
                   "notes": {f: n for f, n in notes_of.items() if n},
                   "scale_corrected": scale_corrected,
                   "ni_scope": {str(y): s for y, s in ni_scope.items()},
                   "nci_used": nci_used,
                   "equity_scope": {str(y): s for y, s in equity_scope.items()},
                   "eq_incl_rung": {str(y): r for y, r in eq_incl_rung.items()},
                   "cash_scope": {str(y): s for y, s in cash_scope.items()},
                   "eps_rung": {str(y): EPS_RUNG[t] for y, t in tag_of["eps_diluted"].items()}}
    return history, prov_bundle


PROV_STATE_CODE = {"primary": "p", "backfill": "b",
                   "component_sum": "s", "lone_depreciation": "l", "closure_sum": "c",
                   "closure_replaced": "r", "bank_net_revenue": "n"}
PROV_DERIVED_FIELDS = ("fcf",)   # computed row field, no filed tag -> no provenance
SCALE_STATE_CODE = {"scale_corrected_eps": "e", "scale_corrected_cover": "v"}   # "c" is closure_sum


def encode_provenance(history_out, prov_by_ticker):
    """Parallel top-level 'provenance' payload from per-ticker prov bundles.

    RLE-encodes (winning_tag, base_state) runs per ticker/field over the SHIPPED non-null
    cells, with index-addressed _tags and _accns tables, plus overrides and period_end maps.
    A run [first_year, tag_index, state_code] holds until the next run's first_year, intersected
    with the years actually present. 'o' (accession_override) is layered via `overrides`, never
    a run state. Called from main() (production) and the acceptance harness (shared, so measured
    counts equal what ships).
    """
    tag_index, accn_index = {}, {}

    def ti(tag):
        if tag not in tag_index:
            tag_index[tag] = len(tag_index)
        return tag_index[tag]

    def ai(accn):
        if accn not in accn_index:
            accn_index[accn] = len(accn_index)
        return accn_index[accn]

    runs, overrides_out, period_end_out, untagged_out, notes_out, scale_out = {}, {}, {}, {}, {}, {}
    scope_out = {"ni_scope": {}, "nci_subtracted": {}, "equity_scope": {}, "equity_incl_nci_rung": {},
                 "cash_scope": {}, "eps_rung": {}}
    # Index accessions over ALL captured overrides (including cells on year-rows later dropped by
    # the revenue/assets gate) so the _accns table is complete; the overrides MAP below still
    # emits only shipped non-null cells. (Indexing only shipped cells undercounts by the handful
    # of dropped-row accessions.)
    for tk in sorted(history_out):
        bundle = prov_by_ticker.get(tk)
        if not bundle:
            continue
        for y in sorted(bundle["overrides"]):
            for f in sorted(bundle["overrides"][y]):
                ai(bundle["overrides"][y][f])
    for tk in sorted(history_out):
        bundle = prov_by_ticker.get(tk)
        if not bundle:
            continue
        states, tags = bundle["states"], bundle["tags"]
        rows = history_out[tk]                        # {str(y): row}
        # R17: which of the three fields the filer never tags in ANY shipped year. [] = all three
        # are tagged in at least one year; a gap inside a tagged series stays a null cell.
        untagged_out[tk] = [f for f in R17_FIELDS
                            if all(row.get(f) is None for row in rows.values())]
        t_runs = {}
        for f in sorted(states):
            if f in PROV_DERIVED_FIELDS:
                continue
            fstate, ftag = states[f], tags[f]
            yrs = sorted(int(y) for y, row in rows.items()
                         if row.get(f) is not None and int(y) in fstate)
            seq, prev = [], None
            for y in yrs:
                key = (ti(ftag.get(y)), PROV_STATE_CODE.get(fstate.get(y), "p"))
                if key != prev:
                    seq.append([y, key[0], key[1]])
                    prev = key
            if seq:
                t_runs[f] = seq
        if t_runs:
            runs[tk] = t_runs
        ot = {}
        for y, fmap in bundle["overrides"].items():
            row = rows.get(y, {})
            inner = {f: ai(accn) for f, accn in fmap.items() if row.get(f) is not None}
            if inner:
                ot[y] = inner
        if ot:
            overrides_out[tk] = ot
        sc = {}
        for y, fmap in bundle.get("scale_corrected", {}).items():
            row = rows.get(y, {})
            inner = {f: SCALE_STATE_CODE[st] for f, st in fmap.items() if row.get(f) is not None}
            if inner:
                sc[y] = inner
        if sc:
            scale_out[tk] = sc
        pe = {y: d for y, d in bundle["period_end"].items() if y in rows}
        if pe:
            period_end_out[tk] = pe
        # A2: R17 ladder notes ({field: {year: [{note, tag, value, ...}]}}) for years the ticker ships
        # a row for — a `negative_rejected` year can be a null cell, so this is not tied to runs.
        tn = {f: {str(y): lst for y, lst in sorted(ym.items()) if str(y) in rows}
              for f, ym in (bundle.get("notes") or {}).items()}
        tn = {f: ym for f, ym in tn.items() if ym}
        if tn:
            notes_out[tk] = tn
        # Fix 1a/2a scope maps, for the years the ticker ships a row for
        for src, dst in (("ni_scope", scope_out["ni_scope"]), ("nci_used", scope_out["nci_subtracted"]),
                         ("equity_scope", scope_out["equity_scope"]),
                         ("eq_incl_rung", scope_out["equity_incl_nci_rung"]),
                         ("cash_scope", scope_out["cash_scope"]), ("eps_rung", scope_out["eps_rung"])):
            m = {y: v for y, v in sorted((bundle.get(src) or {}).items()) if y in rows}
            if m:
                dst[tk] = m

    inv_tags = [None] * len(tag_index)
    for t, i in tag_index.items():
        inv_tags[i] = t
    inv_accns = [None] * len(accn_index)
    for a, i in accn_index.items():
        inv_accns[i] = a
    return {
        "_schema": ("parallel provenance sibling of 'tickers'. runs[T][field] = "
                    "[[first_year, tag_index, state_code], ...] RLE over SHIPPED non-null cells; "
                    "a run holds until the next run's first_year, intersected with years present. "
                    "state_code in _states; _tags/_accns are index-addressed. "
                    "'n' (bank_net_revenue): a bank P&L filer's revenue is InterestIncomeExpenseNet + "
                    "NoninterestIncome, its tag the composite 'InterestIncomeExpenseNet+NoninterestIncome'. "
                    "overrides[T][year][field] = accn_index (effective state 'o'). "
                    "period_end[T][year] = bin end date. "
                    "untagged_fields[T] = the R17 fields (goodwill, intangibles_ex_goodwill, "
                    "amortization_intangibles) the filer never tags in any shipped year; [] = all "
                    "three tagged; a ticker absent from the map was built before R17. "
                    "ladder_notes[T][field][year] = [{note, tag, value, ...}]: sign_flipped (value = "
                    "the filed negative, shipped as its absolute value), negative_rejected (value = "
                    "the refused negative; the next rung was tried), rung_conflict (a filed 0 on "
                    "`tag` was kept although later_tag holds later_value > 0). "
                    "scale_corrected[T][year][field] = state_code ('e'/'v': the cell was a clean "
                    "power of 1000 off and was rescaled from the same filing's EPS identity / "
                    "cover count; base runs unchanged). "
                    "ni_scope[T][year] = the rung that resolved net_income (Fix 1a): parent "
                    "(NetIncomeLoss / ifrs owners of the parent), parent_derived (ProfitLoss minus the "
                    "NCI line), no_nci_filed (ProfitLoss, no noncontrolling-interest element filed), "
                    "nci_zero_filed (ProfitLoss; noncontrolling-interest elements are filed only as 0, "
                    "read as a value: no outside holders), nci_unknown (ProfitLoss kept although a "
                    "non-zero NCI element is filed). "
                    "nci_subtracted[T][year] = the NCI amount a parent_derived year subtracted. "
                    "equity_scope[T][year] = the rung that resolved equity, the parent's on every rung: "
                    "parent (StockholdersEquity / ifrs EquityAttributableToOwnersOfParent), parent_derived "
                    "(the including-NCI total minus MinorityInterest, or ifrs Equity minus "
                    "NoncontrollingInterests, one instant, both filed), no_nci_filed / nci_zero_filed / "
                    "nci_unknown (the including-NCI total, else ifrs Equity, read as ni_scope reads N: "
                    "kept and marked, never subtracted). "
                    "equity_incl_nci_rung[T][year] = incl_tag | ifrs_equity | parent_plus_minority | "
                    "parent_no_nci. "
                    "cash_scope[T][year] = the rung that resolved cash (Fix 2a): unrestricted_line, "
                    "ifrs_cash_and_equivalents, derived_minus_restricted, total_no_restricted_filed, "
                    "cash_unresolved (null cell: restricted elements exceed the cash-flow total) or "
                    "cash_unresolved_securities_segregated (null cell: the only restricted-type element "
                    "filed is a CashAndSecuritiesSegregated... one, which includes securities and cannot "
                    "be subtracted from the cash-flow total). "
                    "eps_rung[T][year] = the rung that resolved eps_diluted (USD/shares, annual): diluted "
                    "(us-gaap EarningsPerShareDiluted), ifrs_diluted (ifrs-full DilutedEarningsLossPerShare) or "
                    "basic_and_diluted (EarningsPerShareBasicAndDiluted, used only in a year where no diluted "
                    "figure is filed). net_income_available_to_common_diluted (NetIncomeLossAvailableToCommon"
                    "StockholdersDiluted) and preferred_dividends (PreferredStockDividendsIncomeStatementImpact, "
                    "else PreferredStockDividendsAndOtherAdjustments) are ladder-resolved like the R17 fields, "
                    "vote-excluded, with their runs and ladder_notes; a filed 0 is a value."),
        "_states": {"p": "primary", "b": "backfill", "s": "component_sum",
                    "l": "lone_depreciation", "c": "closure_sum", "r": "closure_replaced",
                    "n": "bank_net_revenue", "o": "accession_override",
                    "e": "scale_corrected_eps", "v": "scale_corrected_cover"},
        "_tags": inv_tags,
        "_accns": inv_accns,
        "runs": runs,
        "overrides": overrides_out,
        "period_end": period_end_out,
        "untagged_fields": untagged_out,
        "ladder_notes": notes_out,
        "scale_corrected": scale_out,
        **scope_out,
    }


def safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def compute_battery(history):
    """Value-trap battery from the two most recent complete fiscal years."""
    years = sorted(history.keys())
    if len(years) < 2:
        return None
    y0, y1 = years[-1], years[-2]
    c, p = history[y0], history[y1]  # current, prior

    battery = {"fiscal_year": y0, "years_available": len(years)}

    # Fix 1a(e): ratios against consolidated totals (ROA, CFO > NI, accruals, TATA) read the
    # consolidated net income, falling back to the parent's when it is null (one basis, P3).
    ni_c = c.get("net_income_incl_nci") if c.get("net_income_incl_nci") is not None else c.get("net_income")
    ni_p = p.get("net_income_incl_nci") if p.get("net_income_incl_nci") is not None else p.get("net_income")

    # ── Piotroski F-Score ────────────────────────────────────────────────
    checks = {}
    roa_c = safe_div(ni_c, c.get("total_assets"))
    roa_p = safe_div(ni_p, p.get("total_assets"))
    if roa_c is not None:
        checks["roa_positive"] = roa_c > 0
    if c.get("ocf") is not None:
        checks["cfo_positive"] = c["ocf"] > 0
    if roa_c is not None and roa_p is not None:
        checks["roa_improving"] = roa_c > roa_p
    if c.get("ocf") is not None and ni_c is not None:
        checks["cfo_exceeds_ni"] = c["ocf"] > ni_c
    lev_c = safe_div(c.get("lt_debt"), c.get("total_assets"))
    lev_p = safe_div(p.get("lt_debt"), p.get("total_assets"))
    if lev_c is not None and lev_p is not None:
        checks["leverage_decreasing"] = lev_c <= lev_p
    cr_c = safe_div(c.get("current_assets"), c.get("current_liabilities"))
    cr_p = safe_div(p.get("current_assets"), p.get("current_liabilities"))
    if cr_c is not None and cr_p is not None:
        checks["current_ratio_improving"] = cr_c > cr_p
    if c.get("shares_diluted") is not None and p.get("shares_diluted") is not None:
        checks["no_dilution"] = c["shares_diluted"] <= p["shares_diluted"] * 1.02
    gm_c = safe_div(c.get("gross_profit"), c.get("revenue"))
    gm_p = safe_div(p.get("gross_profit"), p.get("revenue"))
    if gm_c is not None and gm_p is not None:
        checks["gross_margin_improving"] = gm_c > gm_p
    at_c = safe_div(c.get("revenue"), c.get("total_assets"))
    at_p = safe_div(p.get("revenue"), p.get("total_assets"))
    if at_c is not None and at_p is not None:
        checks["asset_turnover_improving"] = at_c > at_p

    battery["f_score"] = sum(1 for v in checks.values() if v) if checks else None
    battery["f_score_checks_available"] = len(checks)

    # ── Sloan accruals ───────────────────────────────────────────────────
    if all(x is not None for x in (ni_c, c.get("ocf"),
                                   c.get("total_assets"), p.get("total_assets"))):
        avg_assets = (c["total_assets"] + p["total_assets"]) / 2
        battery["accruals_ratio"] = round((ni_c - c["ocf"]) / avg_assets, 4) if avg_assets else None
    else:
        battery["accruals_ratio"] = None

    # ── Net share issuance ───────────────────────────────────────────────
    # Split guard: a year-over-year share-count jump of +-50% or more is a
    # stock split / reverse split, not issuance (weighted share counts in
    # filings are NOT retro-adjusted across years). Without this, NVDA's
    # 2024 10-for-1 split reads as 41%/yr dilution.
    sh = {y: history[y].get("shares_diluted") for y in years}
    split_suspected = False
    sh_years = [y for y in years if sh.get(y)]
    for a, b in zip(sh_years, sh_years[1:]):
        r = sh[b] / sh[a]
        if r >= 1.5 or r <= 0.55:
            split_suspected = True
            break
    battery["share_count_split_suspected"] = split_suspected
    if split_suspected:
        battery["net_issuance_1y"] = None
        battery["net_issuance_3y_cagr"] = None
        checks.pop("no_dilution", None)
        battery["f_score"] = sum(1 for v in checks.values() if v) if checks else None
        battery["f_score_checks_available"] = len(checks)
    else:
        battery["net_issuance_1y"] = (
            round(sh[y0] / sh[y1] - 1, 4) if sh.get(y0) and sh.get(y1) else None)
        y3 = next((y for y in years if y <= y0 - 3 and sh.get(y)), None)
        # Both endpoints must be POSITIVE, not merely truthy: a negative share
        # count makes the fractional power return a complex number (see the
        # revenue CAGR note below). Undefined -> null.
        battery["net_issuance_3y_cagr"] = (
            round((sh[y0] / sh[y3]) ** (1 / (y0 - y3)) - 1, 4)
            if y3 and (sh.get(y0) or 0) > 0 and sh[y3] > 0 else None)

    # ── Beneish M-Score (8 ratios; missing ones neutralized + reported) ──
    ratios = {}
    missing = []

    def ratio(name, value):
        if value is None:
            missing.append(name)
            ratios[name] = 1.0  # neutral
        else:
            ratios[name] = value

    rec_rev_c = safe_div(c.get("receivables"), c.get("revenue"))
    rec_rev_p = safe_div(p.get("receivables"), p.get("revenue"))
    ratio("DSRI", safe_div(rec_rev_c, rec_rev_p))
    ratio("GMI", safe_div(gm_p, gm_c))  # prior / current: >1 = margin deterioration
    aq_c = None
    aq_p = None
    if all(x is not None for x in (c.get("current_assets"), c.get("ppe_net"), c.get("total_assets"))):
        aq_c = 1 - (c["current_assets"] + c["ppe_net"]) / c["total_assets"]
    if all(x is not None for x in (p.get("current_assets"), p.get("ppe_net"), p.get("total_assets"))):
        aq_p = 1 - (p["current_assets"] + p["ppe_net"]) / p["total_assets"]
    ratio("AQI", safe_div(aq_c, aq_p))
    ratio("SGI", safe_div(c.get("revenue"), p.get("revenue")))
    dep_rate_c = None
    dep_rate_p = None
    if c.get("da") is not None and c.get("ppe_net") is not None and (c["da"] + c["ppe_net"]):
        dep_rate_c = c["da"] / (c["da"] + c["ppe_net"])
    if p.get("da") is not None and p.get("ppe_net") is not None and (p["da"] + p["ppe_net"]):
        dep_rate_p = p["da"] / (p["da"] + p["ppe_net"])
    ratio("DEPI", safe_div(dep_rate_p, dep_rate_c))
    sga_c = safe_div(c.get("sga"), c.get("revenue"))
    sga_p = safe_div(p.get("sga"), p.get("revenue"))
    ratio("SGAI", safe_div(sga_c, sga_p))
    lvg_c = None
    lvg_p = None
    if all(x is not None for x in (c.get("lt_debt"), c.get("current_liabilities"), c.get("total_assets"))):
        lvg_c = (c["lt_debt"] + c["current_liabilities"]) / c["total_assets"]
    if all(x is not None for x in (p.get("lt_debt"), p.get("current_liabilities"), p.get("total_assets"))):
        lvg_p = (p["lt_debt"] + p["current_liabilities"]) / p["total_assets"]
    ratio("LVGI", safe_div(lvg_c, lvg_p))
    tata = None
    if all(x is not None for x in (ni_c, c.get("ocf"), c.get("total_assets"))):
        tata = (ni_c - c["ocf"]) / c["total_assets"] if c["total_assets"] else None
    if tata is None:
        missing.append("TATA")
        tata = 0.0  # neutral for the additive term

    if len(missing) <= 2:  # require at least 6 of 8 real inputs
        m = (-4.84 + 0.92 * ratios["DSRI"] + 0.528 * ratios["GMI"]
             + 0.404 * ratios["AQI"] + 0.892 * ratios["SGI"]
             + 0.115 * ratios["DEPI"] - 0.172 * ratios["SGAI"]
             + 4.679 * tata - 0.327 * ratios["LVGI"])
        battery["m_score"] = round(m, 3)
    else:
        battery["m_score"] = None
    battery["m_score_inputs_missing"] = sorted(missing)

    # ── Cyclical mid-cycle inputs ────────────────────────────────────────
    revs = [(y, history[y]["revenue"]) for y in years if history[y].get("revenue")]
    if len(revs) >= 6:
        (ya, ra), (yb, rb) = revs[max(0, len(revs) - 6)], revs[-1]
        span = yb - ya
        # rb > 0 is load-bearing, not defensive: a negative TERMINAL revenue
        # (contra-revenue, restatement, mis-tagged XBRL fact) makes rb/ra
        # negative, and a negative float ** a fractional power returns a
        # complex, which round() rejects with TypeError. That killed the whole
        # build weekly from 2026-07-05 — the crash aborted main() before either
        # output file was written, so both silently kept their 06-29 contents.
        # A CAGR to a negative endpoint has no real value: null, per the
        # data-honesty rule above.
        battery["revenue_cagr_5y"] = (
            round((rb / ra) ** (1 / span) - 1, 4)
            if span > 0 and ra > 0 and rb > 0 else None)
    else:
        battery["revenue_cagr_5y"] = None
    margins = []
    for y in years:
        m = safe_div(history[y].get("operating_income"), history[y].get("revenue"))
        if m is not None:
            margins.append(m)
    if margins:
        margins_sorted = sorted(margins)
        mid = len(margins_sorted) // 2
        median_m = (margins_sorted[mid] if len(margins_sorted) % 2
                    else (margins_sorted[mid - 1] + margins_sorted[mid]) / 2)
        battery["op_margin_10y_median"] = round(median_m, 4)
        battery["op_margin_latest"] = round(margins[-1], 4)
        battery["op_margin_years"] = len(margins)
    else:
        battery["op_margin_10y_median"] = None
        battery["op_margin_latest"] = None
        battery["op_margin_years"] = 0

    return battery


def build_ticker_outputs(data, ticker):
    """One companyfacts document (zip member or live API) -> every per-ticker output.

    Single extraction path for the weekly build AND --refresh-one, so a live refresh is
    byte-identical to what the next bulk rebuild produces from the same facts. Returns None
    when no usable annual history exists (the ticker is then absent from every file).
    """
    facts_all = data.get("facts", {})
    # Merge namespaces; us-gaap wins on name collisions
    facts = dict(facts_all.get("ifrs-full", {}))
    facts.update(facts_all.get("us-gaap", {}))
    for tag in SRT_TAGS:                     # srt elements ride under an "srt:" key (Fix 2a(b))
        if tag in facts_all.get("srt", {}):
            facts["srt:" + tag] = facts_all["srt"][tag]
    dei = facts_all.get("dei", {})
    history, prov_bundle = extract_history(facts, ticker, dei)
    if not history:
        return None
    ttm = ttm_snapshot(facts)
    # The TTM is built from DURATION_TAGS["capex"] -- the very tag the latest fiscal year's proof has just
    # shown to be a COMPONENT. Its FY leg is that component, so its capex (and fcf) is withheld: consumers
    # fall back to the proven FY figure (null beats wrong).
    if ttm and prov_bundle["states"]["capex"].get(max(history)) == "closure_replaced":
        ttm["fields"].pop("capex", None)
        ttm["fields"].pop("fcf", None)
        if not ttm["fields"]:
            ttm = None
    return {
        "history": {str(y): row for y, row in sorted(history.items())},
        "cover": latest_shares_cover(dei),
        "prov": prov_bundle or None,
        "battery": compute_battery(history) or None,
        "ttm": ttm or None,
        "qtr": quarterly_snapshot(facts) or None,
    }


# ── single-ticker live refresh ───────────────────────────────────────────────────────────
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def fetch_companyfacts_live(cik):
    """One GET against data.sec.gov for one CIK (declared UA). Raises on any HTTP failure."""
    resp = requests.get(SEC_COMPANYFACTS_URL.format(cik=cik), headers=SEC_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _dump_compact(doc):
    return json.dumps(doc, sort_keys=True)


def _dump_battery(doc):
    return json.dumps(doc, indent=1, sort_keys=True)


def _atomic_write_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def merge_ticker_provenance(prov, ticker, rows, bundle):
    """Replace one ticker's provenance in an existing encoded payload, in place.

    Encodes the single ticker with encode_provenance (the production encoder, so run/override
    semantics are identical), then remaps its local _tags/_accns indices into the file's
    existing tables — appending unseen entries at the end so every other ticker's indices stay
    valid. A ticker with no bundle loses its runs/overrides/period_end entries.
    """
    scope_sections = ("ni_scope", "nci_subtracted", "equity_scope", "equity_incl_nci_rung", "cash_scope", "eps_rung")
    for section in ("runs", "overrides", "period_end", "untagged_fields", "ladder_notes",
                    "scale_corrected") + scope_sections:
        prov.setdefault(section, {}).pop(ticker, None)
    if not bundle:
        return
    local = encode_provenance({ticker: rows}, {ticker: bundle})
    tags, accns = prov.setdefault("_tags", []), prov.setdefault("_accns", [])
    tag_pos = {t: i for i, t in enumerate(tags)}
    accn_pos = {a: i for i, a in enumerate(accns)}

    def remap(table, pos, value):
        if value not in pos:
            pos[value] = len(table)
            table.append(value)
        return pos[value]

    t_runs = local["runs"].get(ticker)
    if t_runs:
        prov["runs"][ticker] = {
            f: [[y, remap(tags, tag_pos, local["_tags"][ti]), code] for y, ti, code in seq]
            for f, seq in t_runs.items()}
        if any(code == "n" for seq in t_runs.values() for _, _, code in seq):
            prov.setdefault("_states", {}).update(local["_states"])        # the file may predate state "n"
    t_over = local["overrides"].get(ticker)
    if t_over:
        prov["overrides"][ticker] = {
            y: {f: remap(accns, accn_pos, local["_accns"][ai]) for f, ai in fmap.items()}
            for y, fmap in t_over.items()}
    if local["period_end"].get(ticker):
        prov["period_end"][ticker] = local["period_end"][ticker]
    if ticker in local["untagged_fields"]:
        prov["untagged_fields"][ticker] = local["untagged_fields"][ticker]
    if ticker in local["ladder_notes"]:
        prov["ladder_notes"][ticker] = local["ladder_notes"][ticker]
    if local["scale_corrected"].get(ticker):
        prov["scale_corrected"][ticker] = local["scale_corrected"][ticker]
        prov.setdefault("_states", {}).update(local["_states"])
    for section in scope_sections:
        if local[section].get(ticker):
            prov[section][ticker] = local[section][ticker]


def refresh_one(ticker, data=None):
    """Live-fetch one ticker, re-extract, patch its rows into the four production files.

    `data` (a companyfacts document) bypasses the network — used by the acceptance harness.
    Exit codes: 0 rows updated or already identical; 1 fetch failure; 2 no CIK / no usable
    history (a ticker that previously had rows is NOT deleted on an empty extraction — that is
    treated as failure, files untouched).
    """
    ticker = ticker.strip().upper()
    if data is None:
        cik_map = get_cik_map()
        cik = cik_map.get(ticker)
        if not cik:
            print(f"FATAL: no CIK for {ticker}")
            return 2
        if ticker in non_common_securities(cik_map, json.loads(STOCKS_JSON.read_text(encoding="utf-8"))):
            print(f"FATAL: {ticker} is a non-common security under CIK{cik} — the issuer's history is not its own")
            return 2
        print(f"Fetching live companyfacts for {ticker} (CIK{cik}) ...")
        try:
            data = fetch_companyfacts_live(cik)
        except Exception as e:  # network, HTTP, JSON
            print(f"FATAL: fetch failed: {e}")
            return 1
    out = build_ticker_outputs(data, ticker)
    if out is None:
        print(f"FATAL: no usable annual history for {ticker} in live facts — files untouched")
        return 2

    files = {
        "history": (HISTORY_JSON, _dump_compact),
        "battery": (BATTERY_JSON, _dump_battery),
        "ttm": (TTM_JSON, _dump_compact),
        "qtr": (QTR_JSON, _dump_compact),
    }
    docs, before = {}, {}
    for key, (path, dump) in files.items():
        if not path.exists():
            print(f"FATAL: {path} not found — run a full build first")
            return 2
        before[key] = path.read_text(encoding="utf-8")
        docs[key] = json.loads(before[key])
        # A re-dump of the UNTOUCHED doc must reproduce the file on disk; otherwise the file
        # was not written by this script's dumper and a patch would rewrite every byte of
        # every ticker. Refuse rather than silently reformat production.
        if dump(docs[key]) != before[key]:
            print(f"FATAL: {path.name} does not round-trip through this script's serializer "
                  f"— refusing to patch (rebuild it first)")
            return 2

    for key, (path, dump) in files.items():
        tickers = docs[key].setdefault("tickers", {})
        if out[key]:
            tickers[ticker] = out[key]
        else:
            tickers.pop(ticker, None)
    hist = docs["history"]
    covers = hist.setdefault("shares_cover", {})
    if out["cover"]:
        covers[ticker] = out["cover"]
    else:
        covers.pop(ticker, None)
    if "provenance" in hist:
        merge_ticker_provenance(hist["provenance"], ticker, out["history"], out["prov"])
    elif out["prov"]:
        hist["provenance"] = encode_provenance({ticker: out["history"]}, {ticker: out["prov"]})

    changed = []
    for key, (path, dump) in files.items():
        text = dump(docs[key])
        if text != before[key]:
            changed.append((path, text))
    if not changed:
        print(f"{ticker}: every file already identical to the live facts — nothing written")
        return 0
    for path, text in changed:
        _atomic_write_text(path, text)
        print(f"Patched {ticker} into {path.name} ({len(text.encode('utf-8')):,} bytes)")
    print("LOCAL-ONLY refresh: do not commit these files (git data comes from the cloud rebuild).")
    return 0


def _apply_path_overrides(zip_path, data_dir):
    """Point the build at a companyfacts zip and/or a data directory other than the repo's own.

    The data directory supplies stocks.json and cik_map.json and receives every output file.
    """
    global DATA, STOCKS_JSON, ZIP_PATH, CIK_MAP_JSON, HISTORY_JSON, BATTERY_JSON, TTM_JSON, QTR_JSON
    if zip_path:
        ZIP_PATH = Path(zip_path)
    if data_dir:
        DATA = Path(data_dir)
        STOCKS_JSON = DATA / "stocks.json"
        CIK_MAP_JSON = DATA / "cik_map.json"
        HISTORY_JSON = DATA / "fundamentals_history.json"
        BATTERY_JSON = DATA / "fundamentals_battery.json"
        TTM_JSON = DATA / "fundamentals_ttm.json"
        QTR_JSON = DATA / "fundamentals_quarterly.json"


def main():
    parser = argparse.ArgumentParser(description="Build 10y fundamentals + value-trap battery from companyfacts.zip")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N tickers (smoke runs)")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker subset")
    parser.add_argument("--refresh-one", type=str, default=None, metavar="TICKER",
                        help="Live-fetch ONE ticker from data.sec.gov and patch its rows in place "
                             "(local-only; never commit the result)")
    parser.add_argument("--zip", type=str, default=None, metavar="PATH",
                        help="companyfacts.zip to read (default: <repo>/companyfacts.zip)")
    parser.add_argument("--data-dir", type=str, default=None, metavar="DIR",
                        help="directory holding stocks.json and cik_map.json and receiving every "
                             "output file (default: <repo>/public/data)")
    args = parser.parse_args()
    _apply_path_overrides(args.zip, args.data_dir)

    if args.refresh_one:
        if args.limit or args.tickers:
            parser.error("--refresh-one cannot be combined with --limit/--tickers")
        sys.exit(refresh_one(args.refresh_one))

    if not ZIP_PATH.exists():
        print(f"FATAL: {ZIP_PATH} not found.")
        sys.exit(1)

    stocks = json.loads(STOCKS_JSON.read_text(encoding="utf-8"))
    universe = [s["symbol"] for s in stocks if s.get("symbol") and "." not in s["symbol"]]
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        universe = [t for t in universe if t in wanted] or sorted(wanted)
    if args.limit:
        universe = universe[: args.limit]

    cik_map = get_cik_map()
    # Preferreds, notes and units share the common stock's CIK; the issuer's history is not theirs.
    non_common = non_common_securities(cik_map, stocks)
    targets = {t: f"CIK{cik_map[t]}.json" for t in universe if t in cik_map and t not in non_common}
    print(f"Universe: {len(universe)} tickers | with CIK: {len(targets)} | "
          f"non-common securities excluded: {sum(t in non_common for t in universe)}")

    history_out = {}
    battery_out = {}
    ttm_out = {}
    qtr_out = {}
    prov_by_ticker = {}
    cover_out = {}
    no_entry = 0
    no_history = 0
    processed = 0

    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        names = set(z.namelist())
        for ticker, entry_name in sorted(targets.items()):
            if entry_name not in names:
                no_entry += 1
                continue
            try:
                with z.open(entry_name) as f:
                    data = json.load(f)
            except Exception:
                no_entry += 1
                continue
            out = build_ticker_outputs(data, ticker)
            if out is None:
                no_history += 1
                continue
            history_out[ticker] = out["history"]
            if out["cover"]:
                cover_out[ticker] = out["cover"]
            if out["prov"]:
                prov_by_ticker[ticker] = out["prov"]
            if out["battery"]:
                battery_out[ticker] = out["battery"]
            if out["ttm"]:
                ttm_out[ticker] = out["ttm"]
            if out["qtr"]:
                qtr_out[ticker] = out["qtr"]
            processed += 1
            if processed % 500 == 0:
                print(f"  ... {processed} tickers processed")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # SUBSET RUNS MUST NOT TOUCH PRODUCTION. --limit/--tickers used to write the full production
    # files unconditionally: a 60-ticker smoke test replaced the 5,588-ticker
    # fundamentals_history.json that every RS2 valuation reads (2026-08-07; recovered from git).
    # A partial universe silently masquerading as the full one corrupts everything downstream,
    # so subset output goes to *.SUBSET.json and says so.
    global HISTORY_JSON, BATTERY_JSON, TTM_JSON, QTR_JSON
    if args.limit or args.tickers:
        HISTORY_JSON = HISTORY_JSON.with_name("fundamentals_history.SUBSET.json")
        BATTERY_JSON = BATTERY_JSON.with_name("fundamentals_battery.SUBSET.json")
        TTM_JSON = TTM_JSON.with_name("fundamentals_ttm.SUBSET.json")
        QTR_JSON = QTR_JSON.with_name("fundamentals_quarterly.SUBSET.json")
        print(f"SUBSET run ({len(targets)} tickers) -> writing {HISTORY_JSON.name} / "
              f"{BATTERY_JSON.name} / {TTM_JSON.name} — production files untouched")
    provenance = encode_provenance(history_out, prov_by_ticker)
    provenance["non_common_securities"] = {t: non_common[t] for t in sorted(universe) if t in non_common}
    debt_note = (
        "CH-9 debt components (instant, USD): debt_lt_noncurrent + debt_current = interest-bearing "
        "debt EXCLUDING all leases. short_term_borrowings_separate is ADDITIVE only when debt_current "
        "resolved from LongTermDebtCurrent (else CP/ShortTermBorrowings nesting is filer-specific — "
        "EMR DebtCurrent 4,797M = LTDCurrent 605M + CP 4,192M; ITT DebtCurrent == ShortTermBorrowings). "
        "Leases (finance_lease_liability, operating_lease_liability) are SEPARATE by design; ifrs "
        "LeaseLiabilities is ALL IFRS-16 lease liabilities (no operating/finance split). Legacy "
        "lt_debt is null/zero/understated for 28/172 live names — not for new work. NO computed "
        "total_debt / net_debt field is emitted; whoever sums components must state their lease + "
        "None-vs-0 policy. borrowings_total is a PER-FILER-ALLOWLISTED ifrs Borrowings total "
        "(current+noncurrent, leases excluded) — null for all but named filers whose composition is "
        "verified; it is a labelled total, never merged with the component fields. NVS: "
        "debt_lt_noncurrent + debt_current SUPPRESSED (no clean split; bare current-portion would "
        "masquerade as total debt), verified Borrowings 28,729M ships in borrowings_total.")
    HISTORY_JSON.write_text(json.dumps(
        {"generated_at": generated_at, "source": "SEC companyfacts.zip (annual filings)",
         "_debt_note": debt_note,
         "provenance": provenance, "shares_cover": cover_out,
         "tickers": history_out}, sort_keys=True), encoding="utf-8")
    BATTERY_JSON.write_text(json.dumps(
        {"generated_at": generated_at,
         "_note": ("Value-trap battery. f_score: 0-9 (check f_score_checks_available); "
                   "accruals_ratio: high positive = earnings not backed by cash; "
                   "m_score: > -1.78 = elevated manipulation risk (Beneish); "
                   "net_issuance_*: positive = dilution."),
         "tickers": battery_out}, indent=1, sort_keys=True), encoding="utf-8")

    TTM_JSON.write_text(json.dumps(
        {"generated_at": generated_at,
         "source": "SEC companyfacts.zip (TTM = FY + 10-Q YTD_current - 10-Q YTD_prior)",
         "_note": ("Flow fields only; a field with no complete, date-adjacent FY/YTD/YTD triple "
                   "is absent rather than approximated. 'through' is the TTM window end."),
         "tickers": ttm_out}, sort_keys=True), encoding="utf-8")

    print()
    print(f"Tickers with history: {processed} | battery: {len(battery_out)} | ttm: {len(ttm_out)}")
    print(f"No zip entry: {no_entry} | no usable annual history: {no_history}")
    print(f"Written: {HISTORY_JSON.name} ({HISTORY_JSON.stat().st_size:,} bytes)")
    print(f"Written: {BATTERY_JSON.name} ({BATTERY_JSON.stat().st_size:,} bytes)")
    QTR_JSON.write_text(json.dumps(
        {"generated_at": generated_at,
         "source": "SEC companyfacts.zip (single quarters from 10-Q; Q4 = FY - YTD-Q3)",
         "tickers": qtr_out}, sort_keys=True), encoding="utf-8")
    print(f"Written: {TTM_JSON.name} ({TTM_JSON.stat().st_size:,} bytes)")
    print(f"Written: {QTR_JSON.name} ({QTR_JSON.stat().st_size:,} bytes) — {len(qtr_out)} tickers")


if __name__ == "__main__":
    main()
