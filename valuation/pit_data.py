"""valuation/pit_data.py - the ONE shared point-in-time data layer (SPEC_rebuild.md, Addendum A).

Source: the SEC companyfacts archive, per filing: every fact carries its value, its filing date and its accession.  Nothing here reads
`fundamentals_history.json`, a screener snapshot, a vendor field or a current anchor.

Rules (Addendum A, binding):
  * A filing counts only if its filing date is STRICTLY BEFORE the valuation date (`filed < asof`).
  * Values are AS FIRST FILED: of all the annual-report versions of one (field, fiscal period) filed before `asof`, the earliest wins
    (ties: an original form over an amendment, then the ladder's order).  `mode="latest"` exists only to MEASURE how far restatements move
    values; no engine, prior or metric may use it.
  * A fiscal year exists only from its OWN annual report (10-K, 10-K405, 10-KT, 20-F, 40-F): the filing whose period of report is that year.
    S-1 / F-1 data is never read (only annual-form facts and cover-page share counts of periodic reports are stored).  A fiscal year whose own
    filing is not in companyfacts (a pre-XBRL original) exists from the earliest LATER filing that restates it, stamped
    `no_own_filing_in_companyfacts`: later than the truth, never earlier, so there is no look-ahead.
  * Delisted companies are kept: the archive holds every XBRL filer.
  * The valuation-date price is the TRADED, UNADJUSTED close with share counts on the same basis; total-return series are for outcomes only.
  * Nothing is filled from today: a missing value is None.

API (all dates are `datetime.date` or ISO strings; `asof` is the valuation date):

    pit = PitData(store_dir, zip_path=None, price_source=None, id_map=None)
    pit.cik_for(ticker_or_cik)                      -> 10-digit CIK string or None
    pit.company(cik)                                -> CompanyPit or None (None: no such company in the store / archive)
    pit.snapshot(cik, asof)                         -> Snapshot  (rows, provenance, base year L, cover shares, own filing dates)
    pit.fiscal_years(cik, asof, mode="first_filed") -> {fye iso: FiscalYear}   (only years whose own filing is before asof)
    pit.rows(cik, asof)                             -> {int fiscal year: row dict} in the extractor's field names, plus 'fcf'
    pit.outcome_fiscal_years(cik)                   -> every fiscal year, first-filed, NO cutoff (for OUTCOMES only)
    pit.universe(asof, ciks=None)                   -> (list of cik with an annual report before asof, {reason: count})
    pit.market_cap(cik, asof, key=None)             -> {"market_cap", "price", "shares", ... "flags", "reason"}
    pit.price / pit.price_source                    -> the PriceSource (unadjusted close, split events, total-return index)

Field names follow the production extractor (revenue, gross_profit, operating_income, net_income, ocf, capex, da, ..., total_assets, equity,
cash, ...) so code written for fundamentals_history rows reads these rows unchanged.  The tag ladders are a simplified, documented copy of the
extractor's (no scale-defence, no accession vote: under first-filed each period has one filing, and the corrupt later restatements the
defences exist for are not read).  Every cell records its tag, accession, filing date, form and flags.
"""
import gzip
import json
import math
import zipfile
from collections import defaultdict, namedtuple
from datetime import date, timedelta
from pathlib import Path

PIT_LAYER_VERSION = "1"

ANNUAL_ORIGINAL = ("10-K", "10-K405", "10-KT", "20-F", "40-F")
ANNUAL_AMENDMENT = ("10-K/A", "10-K405/A", "10-KT/A", "20-F/A", "40-F/A")
ANNUAL_FORMS = ANNUAL_ORIGINAL + ANNUAL_AMENDMENT
COVER_FORMS = ANNUAL_FORMS + ("10-Q", "10-Q/A", "10-QT")
COVER_TAG = "EntityCommonStockSharesOutstanding"
DAYS_LO, DAYS_HI = 350, 380          # a fiscal-year duration (52/53-week years included)
FYE_CLUSTER_DAYS = 10                # period ends this close are the same fiscal year
SHARE_COUNT_RATIO = 100.0            # amendment A1 of the earlier harness: a cover count 100x from the filed diluted count is a scale slip


def is_num(v):
    """A real finite number; 0.0 is a value; None, bool, NaN and +/-inf are not."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def to_date(x):
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def add_months(d, n):
    import calendar
    idx = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(idx, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1]))


# ---- the field ladders ---------------------------------------------------------------------------------------------------------------

# kind: duration (an annual flow) or instant (a balance); unit: the only unit read.  ladder: tags in order of preference (us-gaap and ifrs-full
# namespaces are merged; us-gaap wins a tie).  Absent tag = None, never 0.
FIELD_SPECS = {
    "revenue": ("duration", "USD", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                    "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "Revenue",
                                    "RevenueFromContractsWithCustomers"]),
    "gross_profit": ("duration", "USD", ["GrossProfit"]),
    "operating_income": ("duration", "USD", ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"]),
    "net_income": ("duration", "USD", ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"]),
    "ocf": ("duration", "USD", ["NetCashProvidedByUsedInOperatingActivities",
                                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                                "CashFlowsFromUsedInOperatingActivities"]),
    "capex": ("duration", "USD", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                                  "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]),
    "da": ("duration", "USD", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                               "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortisationExpense",
                               "AdjustmentsForDepreciationAndAmortisationExpense"]),
    "sga": ("duration", "USD", ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"]),
    "interest_expense": ("duration", "USD", ["InterestExpense", "InterestExpenseDebt"]),
    "pretax_income": ("duration", "USD", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ProfitLossBeforeTax"]),
    "tax_provision": ("duration", "USD", ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations", "IncomeTaxExpenseIncome"]),
    "sbc": ("duration", "USD", ["ShareBasedCompensation", "AdjustmentsForSharebasedPayments"]),
    "amortization_intangibles": ("duration", "USD", ["AmortizationOfIntangibleAssets", "AmortizationOfAcquiredIntangibleAssets",
                                                     "FiniteLivedIntangibleAssetsAmortizationExpense"]),
    "shares_diluted": ("duration", "shares", ["WeightedAverageNumberOfDilutedSharesOutstanding",
                                              "WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageShares",
                                              "AdjustedWeightedAverageShares"]),
    "eps_diluted": ("duration", "USD/shares", ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare",
                                               "EarningsPerShareBasicAndDiluted"]),
    "total_assets": ("instant", "USD", ["Assets"]),
    "current_assets": ("instant", "USD", ["AssetsCurrent", "CurrentAssets"]),
    "current_liabilities": ("instant", "USD", ["LiabilitiesCurrent", "CurrentLiabilities"]),
    "total_liabilities": ("instant", "USD", ["Liabilities"]),
    "equity": ("instant", "USD", ["StockholdersEquity", "EquityAttributableToOwnersOfParent",
                                  "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity"]),
    "cash": ("instant", "USD", ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents",
                                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "st_investments": ("instant", "USD", ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                                          "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "OtherShortTermInvestments"]),
    "lt_investments": ("instant", "USD", ["MarketableSecuritiesNoncurrent", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"]),
    "lt_debt": ("instant", "USD", ["LongTermDebtNoncurrent", "LongTermDebt"]),
    "debt_lt_noncurrent": ("instant", "USD", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongtermBorrowings",
                                              "NoncurrentPortionOfNoncurrentBondsIssued"]),
    "debt_current": ("instant", "USD", ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent",
                                        "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
                                        "CurrentPortionOfLongtermBorrowings", "ShortTermBorrowings", "ShorttermBorrowings"]),
    "short_term_borrowings_separate": ("instant", "USD", ["CommercialPaper", "ShortTermBorrowings", "ShorttermBorrowings"]),
    "finance_lease_liability": ("instant", "USD", ["FinanceLeaseLiability", "CapitalLeaseObligations"]),
    "operating_lease_liability": ("instant", "USD", ["OperatingLeaseLiability", "LeaseLiabilities"]),
    "receivables": ("instant", "USD", ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent", "TradeAndOtherCurrentReceivables"]),
    "inventory": ("instant", "USD", ["InventoryNet", "Inventories"]),
    "ppe_net": ("instant", "USD", ["PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipment"]),
    "retained_earnings": ("instant", "USD", ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"]),
    "goodwill": ("instant", "USD", ["Goodwill"]),
    "intangibles_ex_goodwill": ("instant", "USD", ["IntangibleAssetsNetExcludingGoodwill", "IntangibleAssetsOtherThanGoodwill",
                                                   "FiniteLivedIntangibleAssetsNet"]),
    "minority_interest": ("instant", "USD", ["MinorityInterest", "NoncontrollingInterests"]),
    # family-classification inputs (SPEC section 2): the balance-sheet tests stated in words
    "insurance_reserves_future_benefits": ("instant", "USD", ["LiabilityForFuturePolicyBenefits"]),
    "insurance_reserves_claims": ("instant", "USD", ["LiabilityForClaimsAndClaimsAdjustmentExpense"]),
    "deposits": ("instant", "USD", ["Deposits"]),
    "loans_receivable": ("instant", "USD", ["LoansAndLeasesReceivableNetReportedAmount"]),
    # commodity cross-check (SPEC 3.3): the ASC 932 standardized measure, an instant filed in the oil and gas reserve disclosure
    "standardized_measure": ("instant", "USD", ["StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserveQuantities"]),
}

# a tag whose scope or content the consumer must know (never silently treated as the preferred tag)
TAG_FLAGS = {
    "ProfitLoss": "net_income_consolidated_may_include_nci",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "equity_includes_nci",
    "Equity": "equity_includes_nci",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": "cash_includes_restricted",
    "WeightedAverageNumberOfSharesOutstandingBasic": "shares_basic_not_diluted",
    "WeightedAverageShares": "shares_undifferentiated",
    "AdjustedWeightedAverageShares": "shares_undifferentiated",
    "EarningsPerShareBasicAndDiluted": "eps_basic_and_diluted",
}

Fact = namedtuple("Fact", "tag unit start end val accn filed form taxo")
Cell = namedtuple("Cell", "val tag unit accn filed form own flags")


def _needed_tags():
    s = {COVER_TAG}
    for _k, _u, ladder in FIELD_SPECS.values():
        s.update(ladder)
    return s


NEEDED_TAGS = _needed_tags()


# ---- the store: companyfacts reduced to the annual-report facts the layer reads ------------------------------------------------------

def compact_company(obj):
    """One companyfacts member -> {"cik", "name", "facts": [[taxo, tag, unit, start, end, val, accn, filed, form], ...]}.  Keeps the needed
    tags: annual-form facts, and the dei cover-page share count of periodic reports.  Facts with no filing date cannot be placed in time
    and are dropped (counted)."""
    out, no_filed = [], 0
    for taxo, body in (obj.get("facts") or {}).items():
        for tag, cb in (body or {}).items():
            if tag not in NEEDED_TAGS:
                continue
            for unit, vals in ((cb or {}).get("units") or {}).items():
                for v in vals:
                    form = v.get("form")
                    if tag == COVER_TAG:
                        if form not in COVER_FORMS:
                            continue
                    elif form not in ANNUAL_FORMS:
                        continue
                    if not v.get("filed"):
                        no_filed += 1
                        continue
                    if v.get("val") is None:
                        continue
                    out.append([taxo, tag, unit, v.get("start"), v.get("end"), v.get("val"), v.get("accn") or "", v["filed"], form])
    return {"cik": str(obj.get("cik", "")).zfill(10), "name": obj.get("entityName"), "facts": out, "dropped_no_filed": no_filed,
            "layer_version": PIT_LAYER_VERSION}


class CompanyPit:
    """One company's annual-report facts and the as-of logic over them."""

    def __init__(self, doc):
        self.cik = doc["cik"]
        self.name = doc.get("name")
        self.by_tag = defaultdict(list)
        self.cover = []
        for taxo, tag, unit, start, end, val, accn, filed, form in doc["facts"]:
            f = Fact(tag, unit, start, end, val, accn, filed, form, taxo)
            (self.cover if tag == COVER_TAG else self.by_tag[tag]).append(f)
        self._accns = None
        self._fy_index = None

    # -- annual accessions and fiscal years --
    def annual_accessions(self):
        """{accn: {"filed", "form", "period"}}: period of report = the latest end among the accession's fiscal-year-length duration facts."""
        if self._accns is None:
            acc = {}
            for facts in self.by_tag.values():
                for f in facts:
                    if f.start is None or f.end is None:
                        continue
                    d = _days(f.start, f.end)
                    if d is None or not DAYS_LO <= d <= DAYS_HI:
                        continue
                    a = acc.setdefault(f.accn, {"filed": f.filed, "form": f.form, "period": f.end})
                    if f.end > a["period"]:
                        a["period"] = f.end
                    if f.filed < a["filed"]:
                        a["filed"] = f.filed
            self._accns = acc
        return self._accns

    def fiscal_year_index(self):
        """[{"fye", "own_accn", "own_filed", "own_form", "periods": [period ends clustered into it]}] sorted by fye.
        The own filing of a fiscal year is the earliest-filed ORIGINAL annual report whose period of report is that year (an amendment
        only when no original is in the archive)."""
        if self._fy_index is None:
            items = sorted(((a["period"], a["filed"], accn, a["form"]) for accn, a in self.annual_accessions().items()))
            clusters, cur = [], []
            for it in items:
                if cur and _days(cur[-1][0], it[0]) > FYE_CLUSTER_DAYS:
                    clusters.append(cur)
                    cur = []
                cur.append(it)
            if cur:
                clusters.append(cur)
            idx = []
            for cl in clusters:
                originals = [c for c in cl if c[3] in ANNUAL_ORIGINAL]
                pool = originals or cl
                own = min(pool, key=lambda c: (c[1], c[2]))
                idx.append({"fye": own[0], "own_accn": own[2], "own_filed": own[1], "own_form": own[3],
                            "own_is_amendment": not originals, "periods": sorted({c[0] for c in cl}),
                            "accns": {c[2] for c in cl}})
            self._fy_index = idx
        return self._fy_index

    def _fye_for(self, end):
        """The fiscal-year end a fact's period end belongs to (within FYE_CLUSTER_DAYS of an own-filing year), else None."""
        best = None
        for fy in self.fiscal_year_index():
            d = abs(_days(fy["fye"], end))
            if d <= FYE_CLUSTER_DAYS and (best is None or d < best[0]):
                best = (d, fy["fye"])
        return best[1] if best else None

    # -- cell selection --
    def _candidates(self, field, asof_iso):
        kind, unit, ladder = FIELD_SPECS[field]
        for rank, tag in enumerate(ladder):
            for f in self.by_tag.get(tag, ()):
                if f.unit != unit or not is_num(f.val) or f.end is None:
                    continue
                if asof_iso is not None and not f.filed < asof_iso:
                    continue
                if kind == "duration":
                    if f.start is None:
                        continue
                    d = _days(f.start, f.end)
                    if d is None or not DAYS_LO <= d <= DAYS_HI:
                        continue
                yield rank, f

    def cells(self, asof, mode="first_filed"):
        """{fye_iso: {field: Cell}} for every fiscal period, using only facts filed strictly before `asof` (None: no cutoff - OUTCOMES only).
        mode "first_filed" (the only mode engines may use) or "latest" (diagnostic)."""
        asof_iso = None if asof is None else to_date(asof).isoformat()
        own_by_fye = {fy["fye"]: fy for fy in self.fiscal_year_index()}
        own_accns = {a: fy["fye"] for fy in self.fiscal_year_index() for a in fy["accns"]}
        out = defaultdict(dict)
        for field in FIELD_SPECS:
            best = {}
            for rank, f in self._candidates(field, asof_iso):
                fye = self._fye_for(f.end)
                if fye is None:
                    fye = f.end            # a comparative of a year whose own filing is not in the archive
                amend = f.form in ANNUAL_AMENDMENT
                if mode == "first_filed":
                    key = (f.filed, amend, rank, f.accn)
                    better = fye not in best or key < best[fye][0]
                else:
                    key = (f.filed, not amend, -rank, f.accn)
                    better = fye not in best or key > best[fye][0]
                if better:
                    best[fye] = (key, rank, f)
            for fye, (_key, rank, f) in best.items():
                flags = []
                if f.tag in TAG_FLAGS:
                    flags.append(TAG_FLAGS[f.tag])
                if f.form in ANNUAL_AMENDMENT:
                    flags.append("from_amendment")
                out[fye][field] = Cell(float(f.val), f.tag, f.unit, f.accn, f.filed, f.form,
                                       own_accns.get(f.accn) == fye, tuple(flags))
        return out

    def fiscal_years(self, asof, mode="first_filed"):
        """{fye iso: FiscalYear} for the years that exist at `asof` (own filing strictly before it; a year with no own filing in the archive exists
        from the earliest filing that carries it).  asof None = no cutoff (outcomes)."""
        asof_iso = None if asof is None else to_date(asof).isoformat()
        cells = self.cells(asof, mode)
        own = {fy["fye"]: fy for fy in self.fiscal_year_index()}
        out = {}
        for fye, fields in cells.items():
            fy = own.get(fye)
            if fy is not None:
                exists_from, own_in_archive = fy["own_filed"], True
            else:
                exists_from, own_in_archive = min(c.filed for c in fields.values()), False
            if asof_iso is not None and not exists_from < asof_iso:
                continue
            if not fields:
                continue
            stamps = [] if own_in_archive else ["no_own_filing_in_companyfacts"]
            if fy is not None and fy["own_is_amendment"]:
                stamps.append("own_filing_is_amendment")
            out[fye] = FiscalYear(fye, fiscal_label(fye), exists_from, fy["own_accn"] if fy else None,
                                  fy["own_form"] if fy else None, fields, tuple(stamps))
        return dict(sorted(out.items()))

    def cover_shares(self, asof):
        """The cover-page share count of the latest periodic report filed strictly before `asof`: every class entry of that filing summed.
        {"value", "cover_date", "filed", "accn", "form", "n_entries"} or None."""
        asof_iso = to_date(asof).isoformat()
        c = [f for f in self.cover if f.filed < asof_iso and is_num(f.val) and f.val > 0 and f.unit == "shares"]
        if not c:
            return None
        last = max(f.filed for f in c)
        sel = [f for f in c if f.filed == last]
        # one filing can carry the same class twice (restated cover): keep one per (accn, end, val)
        uniq = {(f.accn, f.end, f.val): f for f in sel}
        entries = list(uniq.values())
        end = max(f.end for f in entries if f.end) if any(f.end for f in entries) else None
        return {"value": float(sum(f.val for f in entries if f.end == end)) if end else float(sum(f.val for f in entries)),
                "cover_date": end, "filed": last, "accn": entries[0].accn, "form": entries[0].form, "n_entries": len(entries)}

    def facts(self, tags, asof, forms=None):
        """Raw facts of the given tags filed strictly before `asof` (for engines that need a tag the ladders do not carry; only tags in
        NEEDED_TAGS are stored)."""
        asof_iso = to_date(asof).isoformat()
        for t in tags:
            for f in self.by_tag.get(t, ()):
                if f.filed < asof_iso and (forms is None or f.form in forms):
                    yield f


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def fiscal_label(fye_iso):
    """The integer fiscal year of a period end: its calendar year, except a 52/53-week year ending Jan 1-7, which belongs to the year before."""
    d = date.fromisoformat(fye_iso)
    return d.year - 1 if (d.month == 1 and d.day <= 7) else d.year


class FiscalYear:
    __slots__ = ("fye", "year", "exists_from", "own_accn", "own_form", "cells", "stamps")

    def __init__(self, fye, year, exists_from, own_accn, own_form, cells, stamps):
        self.fye, self.year, self.exists_from, self.own_accn, self.own_form = fye, year, exists_from, own_accn, own_form
        self.cells, self.stamps = cells, stamps

    def row(self):
        """{field: value} plus 'fcf' (ocf - capex, both required); a field not filed is absent-as-None."""
        r = {f: self.cells[f].val if f in self.cells else None for f in FIELD_SPECS}
        ocf, cx = r.get("ocf"), r.get("capex")
        r["fcf"] = (ocf - cx) if (ocf is not None and cx is not None) else None
        return r

    def provenance(self):
        return {f: {"tag": c.tag, "accn": c.accn, "filed": c.filed, "form": c.form, "own_filing": c.own, "flags": list(c.flags)}
                for f, c in self.cells.items()}


class Snapshot:
    """Everything the layer knows about one company at one valuation date."""

    def __init__(self, cik, name, asof, years, cover):
        self.cik, self.name, self.asof = cik, name, to_date(asof)
        self.years = years                       # {fye iso: FiscalYear}
        self.cover = cover
        fyes = sorted(years)
        self.L_fye = fyes[-1] if fyes else None
        self.L = years[self.L_fye].year if fyes else None

    def rows(self, max_years=None):
        """{int fiscal year: row}; two period ends labelled with the same year keep the later one (counted in `label_collisions`)."""
        out, self.label_collisions = {}, 0
        for fye in sorted(self.years):
            y = self.years[fye]
            if y.year in out:
                self.label_collisions += 1
            out[y.year] = y.row()
        if max_years:
            out = {k: out[k] for k in sorted(out)[-max_years:]}
        return out

    def row_L(self):
        return self.years[self.L_fye].row() if self.L_fye else None

    def stub_months(self):
        """Months from the base fiscal year end to the valuation date."""
        return (self.asof - to_date(self.L_fye)).days / 30.4375 if self.L_fye else None


# ---- prices ---------------------------------------------------------------------------------------------------------------------------

class PricePoint:
    __slots__ = ("price", "bar", "flags")

    def __init__(self, price, bar, flags=()):
        self.price, self.bar, self.flags = price, bar, tuple(flags)


class PriceSource:
    """Interface.  `basis` names what `close_unadjusted` is: "traded_unadjusted" is the only basis a result may rest on."""
    basis = "traded_unadjusted"

    def has_key(self, key):
        raise NotImplementedError

    def close_unadjusted(self, key, asof):
        """PricePoint of the traded close on `asof` (not split- or dividend-adjusted), or None."""
        raise NotImplementedError

    def adj_close(self, key, asof):
        """PricePoint of the total-return-adjusted close on `asof`, or None.  Outcomes and momentum only."""
        raise NotImplementedError

    def splits(self, key):
        """[(date iso or 'YYYY-MM', ratio)] sorted; ratio 2.0 = 2-for-1.  None when the source cannot say (shares cannot then be put on the price's basis)."""
        raise NotImplementedError

    def last_date(self, key):
        raise NotImplementedError

    def target_date(self, asof, months):
        """The date `months` after `asof` at which a price is read: the same calendar day (a daily source takes the latest bar within its gap);
        a monthly source overrides this with the last weekday of that month."""
        return add_months(to_date(asof), months)


def _last_weekday_of_month(d):
    import calendar
    last = calendar.monthrange(d.year, d.month)[1]
    e = date(d.year, d.month, last)
    while e.weekday() >= 5:
        e -= timedelta(days=1)
    return e


class MonthlyRawPriceSource(PriceSource):
    """The earlier registered download: {"prices": {key: {"YYYY-MM": [Close (split-adjusted), Adj Close, Dividends, Stock Splits]}}}.
    A monthly bar is the month's last close, so a price is served only for a date on or after the month's last weekday (the proxy for the last
    trading day) - any other date is refused, never filled with the month-end.  The traded unadjusted close is the split-adjusted Close times the
    product of the split ratios dated in LATER months; a split in the bar's own month leaves the basis undetermined and is flagged."""

    def __init__(self, doc):
        self.prices = doc["prices"]
        self.meta = doc.get("meta", {})
        self._ev = {}

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def has_key(self, key):
        return key in self.prices

    def _bar(self, key, asof):
        d = to_date(asof)
        if d < _last_weekday_of_month(d):
            return None, None
        m = f"{d.year:04d}-{d.month:02d}"
        return m, (self.prices.get(key) or {}).get(m)

    def splits(self, key):
        if key not in self._ev:
            ev = []
            for m in sorted(self.prices.get(key) or {}):
                v = self.prices[key][m]
                r = v[3] if len(v) > 3 else None
                if is_num(r) and r != 0:
                    ev.append((m, float(r)))
            self._ev[key] = ev
        return self._ev[key]

    def close_unadjusted(self, key, asof):
        m, v = self._bar(key, asof)
        if v is None or not (is_num(v[0]) and v[0] > 0):
            return None
        later = 1.0
        for sm, r in self.splits(key):
            if sm > m:
                later *= r
        flags = ["split_in_bar_month"] if any(sm == m for sm, _ in self.splits(key)) else []
        return PricePoint(float(v[0]) * later, m, flags)

    def adj_close(self, key, asof):
        m, v = self._bar(key, asof)
        if v is None or not (is_num(v[1]) and v[1] > 0):
            return None
        return PricePoint(float(v[1]), m)

    def last_date(self, key):
        ms = sorted(self.prices.get(key) or {})
        return ms[-1] if ms else None

    def target_date(self, asof, months):
        return _last_weekday_of_month(add_months(to_date(asof), months))


class DailyPriceSource(PriceSource):
    """{key: {iso date: {"close": traded unadjusted close, "adj": total-return adjusted close}}} and {key: [(iso date, ratio)]} split events with
    exact ex-dates.  A close is served for `asof` itself or the latest earlier bar within `max_gap_days` (flagged `stale_bar`)."""

    def __init__(self, rows, splits=None, max_gap_days=5):
        self.rows, self._splits, self.max_gap = rows, splits or {}, max_gap_days
        self._sorted = {}

    def has_key(self, key):
        return key in self.rows

    def _find(self, key, asof):
        d = to_date(asof).isoformat()
        r = self.rows.get(key)
        if not r:
            return None, None
        if key not in self._sorted:
            self._sorted[key] = sorted(r)
        ds = self._sorted[key]
        import bisect
        i = bisect.bisect_right(ds, d) - 1
        if i < 0:
            return None, None
        bar = ds[i]
        gap = _days(bar, d)
        if gap is None or gap > self.max_gap:
            return None, None
        return bar, r[bar]

    def close_unadjusted(self, key, asof):
        bar, v = self._find(key, asof)
        if v is None or not (is_num(v.get("close")) and v["close"] > 0):
            return None
        return PricePoint(float(v["close"]), bar, ["stale_bar"] if bar != to_date(asof).isoformat() else [])

    def adj_close(self, key, asof):
        bar, v = self._find(key, asof)
        if v is None or not (is_num(v.get("adj")) and v["adj"] > 0):
            return None
        return PricePoint(float(v["adj"]), bar)

    def splits(self, key):
        return sorted((str(d), float(r)) for d, r in self._splits.get(key, ()))

    def last_date(self, key):
        ds = sorted(self.rows.get(key) or {})
        return ds[-1] if ds else None


class AdjustedOnlyMonthlySource(PriceSource):
    """PROXY for a smoke run when only a split- and dividend-adjusted monthly close exists ({"prices": {key: {"YYYY-MM": adjusted close}}}).
    `basis` is "adjusted_proxy": the level is not a traded price (a dividend payer's old closes sit below what traded) and the split events are
    unknown, so market caps and yields built on it are WRONG IN LEVEL.  Its total-return ratios are valid.  Never a basis for a result."""
    basis = "adjusted_proxy"

    def __init__(self, doc):
        self.prices = doc["prices"]

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def has_key(self, key):
        return key in self.prices

    def _val(self, key, asof):
        d = to_date(asof)
        if d < _last_weekday_of_month(d):
            return None, None
        m = f"{d.year:04d}-{d.month:02d}"
        v = (self.prices.get(key) or {}).get(m)
        return m, (float(v) if is_num(v) and v > 0 else None)

    def close_unadjusted(self, key, asof):
        m, v = self._val(key, asof)
        return None if v is None else PricePoint(v, m, ["PROXY_adjusted_close"])

    def adj_close(self, key, asof):
        m, v = self._val(key, asof)
        return None if v is None else PricePoint(v, m)

    def splits(self, key):
        return None

    def last_date(self, key):
        ms = sorted(self.prices.get(key) or {})
        return ms[-1] if ms else None

    def target_date(self, asof, months):
        return _last_weekday_of_month(add_months(to_date(asof), months))


def split_product(events, after, upto, month_dated=None):
    """Product of the ratios whose date is strictly after `after` and not after `upto` (ISO dates, or 'YYYY-MM' months for a monthly source: a
    month-dated event counts when its month is later than after's month and not later than upto's month).  Also returns whether any event falls
    in the month (monthly) or on the day (daily) of `after` - the ambiguity flag."""
    p, ambiguous = 1.0, False
    for d, r in events or ():
        if len(d) == 7:                       # month-dated
            if d > after[:7] and d <= upto[:7]:
                p *= r
            elif d == after[:7]:
                ambiguous = True
        else:
            if after < d <= upto:
                p *= r
            elif d == after:
                ambiguous = True
    return p, ambiguous


def _split_between(events, a, b):
    """True when a split falls after date `a` and on or before date `b` (months: a month from a's through b's)."""
    for d, _r in events or ():
        if len(d) == 7:
            if a[:7] <= d <= b[:7]:
                return True
        elif a < d <= b:
            return True
    return False


# ---- PitData ---------------------------------------------------------------------------------------------------------------------------

class PitData:
    """The data root handed to every engine: `engine(ticker, asof, data_root)` receives a PitData."""

    def __init__(self, store_dir, zip_path=None, price_source=None, id_map=None):
        self.store_dir = Path(store_dir)
        self.zip_path = Path(zip_path) if zip_path else None
        self.price_source = price_source
        self.id_map = {str(k).upper(): str(v).zfill(10) for k, v in (id_map or {}).items()}
        self._cik_ticker = {}
        self._cik_tickers = defaultdict(list)
        for t, c in sorted(self.id_map.items()):
            self._cik_ticker.setdefault(c, t)
            self._cik_tickers[c].append(t)
        self._cache = {}
        self._snap = {}

    @property
    def price(self):
        return self.price_source

    # -- identity --
    def cik_for(self, ticker_or_cik):
        s = str(ticker_or_cik).strip()
        if s.upper().startswith("CIK") and s[3:].isdigit():
            return s[3:].zfill(10)
        if s.isdigit() and len(s) >= 6:
            return s.zfill(10)
        return self.id_map.get(s.upper())

    def ticker_for(self, cik):
        """One ticker of the company (the alphabetically first): a share-class company has several; see `tickers_for`."""
        return self._cik_ticker.get(str(cik).zfill(10))

    def tickers_for(self, cik):
        return list(self._cik_tickers.get(str(cik).zfill(10), ()))

    # -- the store --
    def _path(self, cik):
        return self.store_dir / f"{cik}.json.gz"

    def build_company(self, cik):
        """Read one company's member from the archive and write its compact store file.  False when the archive has no such member."""
        if self.zip_path is None:
            return False
        name = f"CIK{cik}.json"
        with zipfile.ZipFile(self.zip_path) as z:
            try:
                raw = z.read(name)
            except KeyError:
                return False
        doc = compact_company(json.loads(raw))
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(self._path(cik), "wt", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
        return True

    def company(self, cik):
        cik = str(cik).zfill(10)
        if cik in self._cache:
            return self._cache[cik]
        p = self._path(cik)
        if not p.exists() and not self.build_company(cik):
            self._cache[cik] = None
            return None
        with gzip.open(p, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        self._cache[cik] = CompanyPit(doc)
        return self._cache[cik]

    def drop_cache(self):
        self._cache.clear()
        self._snap.clear()

    # -- as-of views --
    def fiscal_years(self, cik, asof, mode="first_filed"):
        c = self.company(cik)
        return {} if c is None else c.fiscal_years(asof, mode)

    def snapshot(self, cik, asof):
        """The Snapshot of a company at `asof` (cached until `drop_cache`); None when the company is not in the store or the archive."""
        k = (str(cik).zfill(10), to_date(asof).isoformat())
        if k not in self._snap:
            c = self.company(cik)
            self._snap[k] = None if c is None else Snapshot(c.cik, c.name, asof, c.fiscal_years(asof), c.cover_shares(asof))
        return self._snap[k]

    def rows(self, cik, asof):
        s = self.snapshot(cik, asof)
        return {} if s is None else s.rows()

    def outcome_fiscal_years(self, cik):
        """Every fiscal year, first-filed, with NO date cutoff.  For outcomes only: an engine that calls this has looked ahead."""
        c = self.company(cik)
        return {} if c is None else c.fiscal_years(None, "first_filed")

    # -- the universe --
    def universe(self, asof, ciks):
        """The ciks with an annual report whose own filing is before `asof`, and why the others are out."""
        keep, why = [], defaultdict(int)
        for cik in ciks:
            c = self.company(cik)
            if c is None:
                why["not_in_archive"] += 1
                continue
            fy = c.fiscal_years(asof)
            if not fy:
                why["no_annual_report_before_date"] += 1
                continue
            if not any(("revenue" in y.cells or "net_income" in y.cells or "total_assets" in y.cells) for y in fy.values()):
                why["no_usd_figures"] += 1
                continue
            keep.append(c.cik)
        return keep, dict(why)

    # -- price and share basis --
    def market_cap(self, cik, asof, key=None):
        """Market capitalisation on the traded unadjusted price with share counts on the same basis.

        shares: the latest periodic report's cover-page count before `asof`, times the split ratios with ex-dates after the cover date and on or
        before `asof`; else the base year's filed diluted weighted-average count, times the splits after that filing's date.  A split in the
        month/day of the count's date (or between a cover date and its filing) leaves the share basis undetermined (`share_basis_undetermined`:
        no cap); a cover count 100x or more from the filed diluted count (either way) is a scale slip (`share_count_scale_conflict`: no cap).
        A price source that cannot give split events (`splits()` is None) is treated as having none and the result carries `splits_unknown` and
        `market_cap_not_on_traded_basis`: the number is then not a result."""
        out = {"market_cap": None, "price": None, "price_date": None, "price_basis": None, "shares": None, "shares_basis": None,
               "cover_date": None, "flags": [], "reason": None}
        asof_d = to_date(asof)
        src = self.price_source
        if src is None:
            out["reason"] = "no_price_source"
            return out
        key = key or self.ticker_for(cik)
        if key is None or not src.has_key(key):
            out["reason"] = "no_price_key"
            return out
        pp = src.close_unadjusted(key, asof_d)
        if pp is None:
            out["reason"] = "no_close_on_date"
            return out
        out.update(price=pp.price, price_date=pp.bar, price_basis=src.basis)
        out["flags"] += list(pp.flags)
        ev = src.splits(key)
        if ev is None:
            out["flags"].append("splits_unknown")
            ev = []
        c = self.company(cik)
        snap = self.snapshot(cik, asof_d)
        asof_iso = asof_d.isoformat()
        cov_adj = cov_amb = None
        cov = snap.cover if snap else None
        if cov and cov.get("cover_date"):
            p, amb = split_product(ev, cov["cover_date"], asof_iso)
            cov_adj = cov["value"] * p
            cov_amb = amb or _split_between(ev, cov["cover_date"], cov["filed"])
            out["cover_date"] = cov["cover_date"]
        dil_adj = dil_amb = None
        if snap and snap.L_fye:
            fyL = snap.years[snap.L_fye]
            cell = fyL.cells.get("shares_diluted")
            if cell is not None and cell.val > 0:
                p, amb = split_product(ev, cell.filed, asof_iso)
                dil_adj, dil_amb = cell.val * p, amb
        if cov_adj is not None and dil_adj is not None:
            r = cov_adj / dil_adj
            if r >= SHARE_COUNT_RATIO or r <= 1.0 / SHARE_COUNT_RATIO:
                out["reason"] = "share_count_scale_conflict"
                return out
        if cov_adj is not None:
            out["shares"], out["shares_basis"], undetermined = cov_adj, "cover", cov_amb
        elif dil_adj is not None:
            out["shares"], out["shares_basis"], undetermined = dil_adj, "diluted_weighted_average", dil_amb
        else:
            out["reason"] = "no_shares"
            return out
        if undetermined:
            out["reason"] = "share_basis_undetermined"
            return out
        out["market_cap"] = out["price"] * out["shares"]
        if out["price_basis"] != "traded_unadjusted" or "splits_unknown" in out["flags"]:
            out["flags"].append("market_cap_not_on_traded_basis")
        return out

    def diluted_shares(self, cik, asof, key=None):
        """(shares, flags): the base year's filed diluted weighted-average count times the split ratios with ex-dates after that filing's date and
        on or before `asof`; None with a flag when there is no count or the split basis is undetermined (a split on the filing's day or month)."""
        asof_d = to_date(asof)
        key = key or self.ticker_for(cik)
        flags = []
        ev = None
        if self.price_source is not None and key is not None and self.price_source.has_key(key):
            ev = self.price_source.splits(key)
        if ev is None:
            flags.append("splits_unknown")
            ev = []
        snap = self.snapshot(cik, asof_d)
        if snap is None or not snap.L_fye:
            return None, flags + ["no_base_year"]
        cell = snap.years[snap.L_fye].cells.get("shares_diluted")
        if cell is None or not cell.val > 0:
            return None, flags + ["no_diluted_shares"]
        p, amb = split_product(ev, cell.filed, asof_d.isoformat())
        if amb:
            return None, flags + ["share_basis_undetermined"]
        return cell.val * p, flags

    def panel(self, ciks, fields=("revenue",)):
        """A Panel: the first-filed cells (value and filing date) of the given fields for every fiscal year of every company, with no cutoff,
        from which any as-of view is cut by filing date (`Panel.asof`).  Equivalent to calling `fiscal_years(cik, asof)` per date, built once."""
        return Panel(self, list(ciks), tuple(fields))

    def total_return(self, key, d0, d1):
        """Total return from `d0` to `d1` on the adjusted series, or None when either bar is missing."""
        a0, a1 = self.price_source.adj_close(key, d0), self.price_source.adj_close(key, d1)
        if a0 is None or a1 is None:
            return None
        return a1.price / a0.price - 1.0


class Panel:
    """First-filed cells of a field set across companies, with filing dates, cut to an as-of view without re-reading the archive.  A cell is in the
    view iff it was filed strictly before `asof` and its fiscal year exists at `asof` (own filing strictly before it): the same rule as
    `PitData.fiscal_years`, so a panel view and a direct read agree (tested)."""

    def __init__(self, pit, ciks, fields):
        self.fields = fields
        self.data = {}
        for cik in ciks:
            c = pit.company(cik)
            if c is None:
                continue
            fys = c.fiscal_years(None)
            self.data[c.cik] = [(fy.fye, fy.year, fy.exists_from,
                                 {f: (fy.cells[f].val, fy.cells[f].filed) for f in fields if f in fy.cells}) for fy in fys.values()]

    def asof(self, asof):
        """{cik: {int year: {field: value}}} for the fiscal years that exist before `asof`, cells filed before it."""
        a = to_date(asof).isoformat()
        out = {}
        for cik, years in self.data.items():
            d = {}
            for fye, year, exists_from, cells in years:
                if not exists_from < a:
                    continue
                d[year] = {f: v for f, (v, filed) in cells.items() if filed < a}
            if d:
                out[cik] = d
        return out
