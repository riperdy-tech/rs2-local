"""pit_companyfacts.py - an INTERIM CompanyPIT source over the SEC companyfacts files, for the dry run and for fixtures.

It is replaced by the shared layer (valuation/pit_data.py, harness branch) at merge; the engines depend only on common.CompanyPIT.
What it does, per Addendum A:
  * reads one company's companyfacts JSON (one file per CIK: value, period start/end, form, filing date, accession);
  * keeps only rows of an ANNUAL report (10-K, 10-K405, 10-KT, 20-F, 40-F; amendments are not "first filed") whose filing date is
    STRICTLY BEFORE asof;
  * a fiscal period exists only from its own annual report: a row counts only if its period end is the report's own period end (the latest
    annual-length period the report holds), so comparatives and later restatements are ignored; for a period the EARLIEST such filing wins
    (first filed);
  * flows must span 350-380 days; balance sheet items are instants; nothing is taken from a snapshot or another company;
  * a field's tag ladder is tried tag by tag per period (the first tag that holds the period wins);
  * US-GAAP (USD) only: an IFRS filer has no us-gaap facts and yields an empty company with a note.
It is NOT the production extractor (build_fundamentals_history.py): no vote between tags, no per-filer denies or component sums, no
scale correction. Its tag ladders are plain; values it cannot find are None.

The SIC code comes from the SEC submissions JSON (the repo's cache via sec_primary._subs, network only if allow_network) and is the CURRENT
assignment (stamped). Paths: SEC companyfacts directory from SECFACTS_DIR, else <STOCKS_ROOT>/stock-screener/public/data/sec_facts (the
screener's data tree; the publish clone does not hold it); the ticker -> CIK map from cik_map.json in the same data directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .common import ANNUAL_FORMS, CompanyPIT, DataNotPresent, Filed, PITSource, SicInfo, parse_date

LADDERS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax_provision": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "lt_investments": ["LongTermInvestments", "MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"],
    "debt_current": ["DebtCurrent", "LongTermDebtCurrent"],
    "short_term_borrowings_separate": ["ShortTermBorrowings"],
    "debt_lt_noncurrent": ["LongTermDebtNoncurrent", "LongTermNotesPayable"],
    "finance_lease_liability": ["FinanceLeaseLiability"],
    "operating_lease_liability": ["OperatingLeaseLiability"],
    "equity": ["StockholdersEquity"],
    "equity_incl_nci": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "goodwill": ["Goodwill"],
    "intangibles_ex_goodwill": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "amortization_intangibles": ["AmortizationOfIntangibleAssets"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt", "InterestExpenseNonoperating", "InterestIncomeExpenseNet"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "preferred_equity": ["PreferredStockValue", "PreferredStockValueOutstanding"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
}
# a net interest line is filed as income less expense (negative for a net payer): carried as a positive expense, tag name keeps "Net"
SIGN = {"InterestIncomeExpenseNet": -1}
FLOW_FIELDS = {"revenue", "operating_income", "pretax_income", "tax_provision", "net_income", "da", "capex", "interest_expense",
               "amortization_intangibles", "ocf"}
# insurance reserves: the sum of whichever of these balance sheet liabilities is filed (a filer that tags a total AND its parts would be
# double counted: an interim limitation)
INSURANCE_PARTS = ["LiabilityForClaimsAndClaimsAdjustmentExpense", "LiabilityForFuturePolicyBenefits", "UnearnedPremiums",
                   "PolicyholderContractDeposits"]
# raw concepts carried by name: insurer decomposition, ASC 932, lending book
CONCEPTS = [
    ("PremiumsEarnedNet", True), ("PremiumsEarnedNetPropertyAndCasualty", True), ("PremiumsEarnedNetLife", True),
    ("PolicyholderBenefitsAndClaimsIncurredNet", True), ("PolicyholderBenefitsAndClaimsIncurredGross", True),
    ("DeferredPolicyAcquisitionCostAmortizationExpense", True), ("NetInvestmentIncome", True),
    ("StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves", False),
    ("DiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReservesStandardizedMeasure", False),
    ("LoansAndLeasesReceivableNetReportedAmount", False), ("LoansAndLeasesReceivableNetOfDeferredIncome", False),
    ("FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss", False), ("LoansReceivableNet", False),
    ("Deposits", False),
]


def _days(a: str, b: str) -> int:
    return (parse_date(b) - parse_date(a)).days


def _data_dir() -> Path:
    import paths
    env = (os.environ.get("SCREENER_DEV_DATA_DIR") or "").strip()
    return Path(env) if env else paths.stocks_root() / "stock-screener" / "public" / "data"


class CompanyFactsSource(PITSource):
    def __init__(self, facts_dir=None, cik_map=None, submissions_dirs: Optional[List[Path]] = None, allow_network: bool = False):
        d = _data_dir()
        env = (os.environ.get("SECFACTS_DIR") or "").strip()
        self.facts_dir = Path(facts_dir) if facts_dir else (Path(env) if env else d / "sec_facts")
        self._cik_map = cik_map
        self._cik_map_path = d / "cik_map.json"
        self.submissions_dirs = [Path(p) for p in (submissions_dirs or [])]
        self.allow_network = allow_network

    # -- ticker -> CIK ------------------------------------------------------------------------------------------------------------
    def cik(self, ticker: str) -> Optional[str]:
        if self._cik_map is None:
            if not self._cik_map_path.exists():
                raise DataNotPresent(f"cik_map.json not found at {self._cik_map_path}")
            m = json.loads(self._cik_map_path.read_text(encoding="utf-8"))
            self._cik_map = m.get("map") if isinstance(m.get("map"), dict) else m
        c = self._cik_map.get(ticker) or self._cik_map.get(ticker.upper())
        return str(c).zfill(10) if c else None

    # -- SIC ---------------------------------------------------------------------------------------------------------------------
    def sic(self, cik: str) -> Optional[SicInfo]:
        subs = None
        for d in self.submissions_dirs:
            p = d / f"CIK{cik}.json"
            if p.exists():
                subs = json.loads(p.read_text(encoding="utf-8"))
                break
        if subs is None and self.allow_network:
            import sec_primary
            sec_primary.ALLOW_STALE_SUBMISSIONS = True
            subs = sec_primary._subs(cik)
        if not subs:
            return None
        code = str(subs.get("sic") or "").strip() or None
        return SicInfo(code, str(subs.get("sicDescription") or ""), "SEC submissions JSON (current assignment)", False)

    # -- the company --------------------------------------------------------------------------------------------------------------
    def load(self, ticker: str, asof) -> CompanyPIT:
        asof_d = parse_date(asof)
        cik = self.cik(ticker)
        if cik is None:
            raise DataNotPresent(f"{ticker}: no CIK in cik_map.json")
        pit = CompanyPIT(ticker, asof_d, cik=cik, sic=self.sic(cik))
        p = self.facts_dir / f"CIK{cik}.json"
        if not p.exists():
            raise DataNotPresent(f"{ticker}: no companyfacts file {p}")
        facts = json.loads(p.read_text(encoding="utf-8")).get("facts", {})
        us = facts.get("us-gaap")
        if not us:
            pit.notes.append("no us-gaap facts (IFRS filer?): this interim adapter reads us-gaap only")
            return pit
        asof_s = asof_d.isoformat()

        def annual_rows(concept, unit="USD"):
            rows = ((us.get(concept) or {}).get("units") or {}).get(unit) or []
            return [r for r in rows if r.get("form") in ANNUAL_FORMS and r.get("filed") and r["filed"] < asof_s and r.get("accn")]

        # own period of each annual accession: the latest annual-length duration it holds
        own: Dict[str, str] = {}
        filed_of: Dict[str, tuple] = {}
        for concept, node in us.items():
            for r in ((node.get("units") or {}).get("USD") or []):
                if r.get("form") in ANNUAL_FORMS and r.get("filed") and r["filed"] < asof_s and r.get("start") and r.get("accn"):
                    if 350 <= _days(r["start"], r["end"]) <= 380:
                        a = r["accn"]
                        if a not in own or r["end"] > own[a]:
                            own[a] = r["end"]
                        filed_of[a] = (r["filed"], r["form"])
        reports: Dict[str, tuple] = {}
        for a, end in own.items():
            f, form = filed_of[a]
            if end not in reports or f < reports[end][1]:
                reports[end] = (end, f, a, form)
        pit.annual_reports = sorted(reports.values())

        def first_filed(concept, flow):
            out: Dict[str, Filed] = {}
            for r in annual_rows(concept):
                a = r["accn"]
                if a not in own or r["end"] != own[a]:
                    continue
                if flow:
                    if not r.get("start") or not (350 <= _days(r["start"], r["end"]) <= 380):
                        continue
                elif r.get("start"):
                    continue
                cur = out.get(r["end"])
                if cur is None or r["filed"] < cur.filed:
                    val = float(r["val"]) * SIGN.get(concept, 1)
                    out[r["end"]] = Filed(val, r["end"], r["filed"], a, r["form"], concept, r.get("start"))
            return out

        for fld, tags in LADDERS.items():
            merged: Dict[str, Filed] = {}
            for tag in tags:
                for pe, f in first_filed(tag, fld in FLOW_FIELDS).items():
                    merged.setdefault(pe, f)
            if merged:
                pit.series[fld] = merged
        # insurance reserves = sum of the parts filed for the period
        parts = [first_filed(n, False) for n in INSURANCE_PARTS]
        ins: Dict[str, Filed] = {}
        for pe in sorted({pe for d in parts for pe in d}):
            got = [d[pe] for d in parts if pe in d]
            ins[pe] = Filed(sum(g.value for g in got), pe, max(g.filed for g in got), got[0].accession, got[0].form,
                            "+".join(g.tag for g in got))
        if ins:
            pit.series["insurance_reserves"] = ins
        for name, flow in CONCEPTS:
            d = first_filed(name, flow)
            if d:
                pit.concepts[name] = d
        # cover-page share count: the newest dei value filed before asof (any form)
        best = None
        for r in ((facts.get("dei", {}).get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or []:
            if r.get("filed") and r["filed"] < asof_s and (best is None or (r["filed"], r["end"]) > (best["filed"], best["end"])):
                best = r
        if best:
            pit.shares_outstanding = Filed(float(best["val"]), best["end"], best["filed"], best.get("accn", ""), best.get("form", ""),
                                           "dei:EntityCommonStockSharesOutstanding")
        pit.notes.append("interim companyfacts adapter: plain tag ladders, no extractor votes, denies or scale corrections")
        pit.check()
        return pit
