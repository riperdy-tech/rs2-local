"""valuation/pit_data.py - the ONE shared point-in-time data layer (SPEC_rebuild.md, Addenda A and B).

Source: the SEC companyfacts archive, per filing: every fact carries its value, its filing date and its accession.  Nothing here reads
`fundamentals_history.json`, a screener snapshot, a vendor field or a current anchor.

RULES (Addenda A and C, binding)
  * DECISION TIME.  The decision timestamp is 16:00 US Eastern on the valuation date T.  A filing is eligible when its EDGAR acceptance timestamp
    (SEC submissions `acceptanceDateTime`, given to the layer by an `AcceptanceSource`) is at or before that moment; simulated trades happen at the
    next session.  A filing with no acceptance timestamp is eligible when filed on an earlier date, AMBIGUOUS (and not used) when filed on T itself,
    and ineligible later.  companyfacts carries only a filing DATE: without submissions data the layer is conservative, never generous.
  * INPUT at T (the default `mode="as_known"`): the latest filing known at T, amendments included.  A 10-K/A eligible at T replaces the 10-K's value;
    one accepted after T is invisible.  A restated comparative column in a later eligible report is the value known at T.  The cell says so: its
    provenance state is RESTATED when the value known at T differs from the period's first-filed value.
  * OUTCOME for a period (`mode="first_filed"`, `outcome_fiscal_years`): the first value reported for that period (its own annual report), never a
    later restatement.  Two different rules; the harness uses each in its place.
  * A fiscal year exists only from its OWN annual report (10-K, 10-K405, 10-KT, 20-F, 40-F; a 10-K/A counts only where the archive holds no
    original).  S-1 / F-1 data is never stored; a comparative column of a company's first annual report is not a fiscal year.  A company whose first
    annual report is not eligible at T has no fiscal year at T.
  * Every stored fact keeps CIK, taxonomy, tag, unit, value, start, end, instant, form, filed, accession, amendment flag, fy and fp (companyfacts holds
    no dimensional facts: `dimensions` is always empty); `facts_table(asof)` adds `accepted_at` and a provenance state per record: PIT_VALID,
    PIT_INVALID (accepted after T), RESTATED (superseded by a later eligible value), AMBIGUOUS (filed on T with no timestamp), and the cell-level
    MISSING and CORPORATE_ACTION_UNRESOLVED (share basis that cannot be put on the price's split basis).  Engines refuse PIT_INVALID and AMBIGUOUS.
  * Delisted companies are kept: the archive holds every XBRL filer.
  * The valuation-date price is the TRADED, UNADJUSTED close with share counts on the same basis; total-return series are for outcomes and
    for past-return signals only.
  * Nothing is filled from today: a missing value is None.

THE EXTRACTION IS THE SCREENER'S PRODUCTION EXTRACTOR (Addendum B).  `valuation/vendored/build_fundamentals_history.py` is a byte-identical copy of
the screener-publish script (sha256 in valuation/vendored/MANIFEST.json, checked by a test): its tag ladders, accession votes, per-filer denies,
scale corrections, noncontrolling-interest / restricted-cash scopes, capex investing closure and bank-revenue rules run UNCHANGED on a
companyfacts document that has been cut to what was knowable at T (inputs: every eligible fact; outcomes: own-period, first-filed facts).  Nothing imports the screener
repository; the copy is data.  Re-copy it when the screener's extractor changes (the test names the file to compare).
Two documented additions sit ON TOP of the extractor and never alter a value it produced: (1) a `SUPPLEMENTS` ladder for fields the extractor
leaves empty (E&P revenue and capex tags, preferred equity), each cell flagged `pit_supplement`; (2) a non-USD reporting currency is carried in its
own units (the unit is relabelled to USD for the extractor and the company is stamped `reporting_currency`: its values are NOT dollars).

QUARTERS (Addendum E 3): `pit.quarterly(cik, asof)` returns the quarterly facts of a company AS KNOWN at T under the same eligibility rule (16:00 ET
acceptance; filing dates alone are conservative): every three-month value a 10-Q reports, the quarters that only a year-to-date figure gives (Q2 = six
months - Q1, Q3 = nine months - six months), and the fourth quarter derived from the 10-K (FY - nine months).  Each record carries its tag, unit, period,
value, kind (reported_3m | derived_ytd_difference | derived_q4 | reported_instant), form, filed, accepted_at, accession, amended, fy, fp, its source
accessions, the first-reported value, and a provenance state (PIT_VALID, or RESTATED when a later eligible comparative changed the value).  `mode="first_filed"`
gives each quarter's value from its own 10-Q (outcomes).  `pit.quarterly_rows(cik, asof, fields, max_quarters)` returns the shape the Muse layer's
`CompanyFactsQuarters.quarters()` returns, so `PitQuarterSource(pit)` replaces that stopgap.  Quarterly facts are stored only for the tags in
`quarter_fields()` (the production extractor's ladders for the income statement, cash flow and balance sheet); a store built before this addition has no
`qfacts` and the call says so in its notes.

API (dates are `datetime.date` or ISO strings; `asof` is the valuation date):

    pit = PitData(store_dir, zip_path=None, price_source=None, id_map=None, sic_source=None)
    pit.cik_for(ticker_or_cik) / ticker_for(cik) / tickers_for(cik)
    pit.company(cik)                                -> CompanyPit or None
    pit.fiscal_years(cik, asof, mode="as_known")    -> {fye iso: FiscalYear}   (own annual report eligible at asof; values as known at asof)
    pit.snapshot(cik, asof)                         -> Snapshot  (rows, base year L, cover shares, stub months, currency)
    pit.rows(cik, asof)                             -> {int fiscal year: row dict}, the extractor's field names plus 'fcf'
    pit.company_pit(cik, asof)                      -> the engines' CompanyPIT: series[field][period_end] -> Filed(value, period_end, filed,
                                                       accession, form, tag), concepts[name][period_end], annual_reports, sic, cover shares
    pit.outcome_fiscal_years(cik)                   -> every fiscal year, first filed, NO cutoff (OUTCOMES only)
    pit.universe(asof, ciks)                        -> (ciks with an annual report before asof, {reason: count})
    pit.market_cap(cik, asof, key=None)             -> {"market_cap", "price", "shares", ... "flags", "reason"}
    pit.panel(ciks, fields)                         -> Panel; Panel.asof(date) -> {cik: {year: {field: value}}}
    pit.price_source                                -> a PriceSource (unadjusted close, split events, total-return index)

`mode="as_known"` is the input rule above (the production extractor on everything eligible at T).  `mode="first_filed"` is the outcome rule.
"""
import gzip
import importlib.util
import json
import math
import sys
import zipfile
from collections import defaultdict, namedtuple
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PIT_LAYER_VERSION = "2"

ANNUAL_ORIGINAL = ("10-K", "10-K405", "10-KT", "20-F", "40-F")
ANNUAL_AMENDMENT = ("10-K/A", "10-K405/A", "10-KT/A", "20-F/A", "40-F/A")
ANNUAL_FORMS = ANNUAL_ORIGINAL + ANNUAL_AMENDMENT
COVER_FORMS = ANNUAL_FORMS + ("10-Q", "10-Q/A", "10-QT")
COVER_TAG = "EntityCommonStockSharesOutstanding"
STORE_TAXONOMIES = ("us-gaap", "ifrs-full", "srt", "dei")
QUARTER_FORMS = ("10-Q", "10-Q/A", "10-QT")
DAYS_LO, DAYS_HI = 350, 380          # a fiscal-year duration (52/53-week years included)
FYE_CLUSTER_DAYS = 10                # period ends this close are the same fiscal year
SHARE_COUNT_RATIO = 100.0            # a cover count 100x from the filed diluted count is a scale slip
VENDORED_DIR = Path(__file__).resolve().parent / "vendored"


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


def _nth_weekday(year, month, weekday, n):
    """The n-th (1-based; -1 = last) given weekday (Mon=0) of a month."""
    import calendar
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == weekday]
    return date(year, month, days[n - 1] if n > 0 else days[-1])


def et_is_dst(d):
    """US Eastern daylight time on date `d` at 16:00 (the rule in force: from 2007 the second Sunday of March to the first Sunday of November;
    before, the first Sunday of April to the last Sunday of October)."""
    if d.year >= 2007:
        return _nth_weekday(d.year, 3, 6, 2) <= d < _nth_weekday(d.year, 11, 6, 1)
    return _nth_weekday(d.year, 4, 6, 1) <= d < _nth_weekday(d.year, 10, 6, -1)


def decision_time_utc(d):
    """16:00 US Eastern on date `d`, as a UTC datetime (the decision timestamp of a valuation date)."""
    d = to_date(d)
    return datetime(d.year, d.month, d.day, 16 + (4 if et_is_dst(d) else 5), 0, 0, tzinfo=timezone.utc)


def parse_accepted(s):
    """An EDGAR acceptance timestamp ('2019-03-01T21:15:34.000Z' or a header's '20190301161534' in Eastern time) as a UTC datetime, or None."""
    if not s:
        return None
    s = str(s).strip()
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        if s.isdigit() and len(s) == 14:               # SGML header: Eastern wall-clock time
            d = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]), int(s[12:14]))
            return (d + timedelta(hours=4 if et_is_dst(d.date()) else 5)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return None


class SubmissionsAcceptance:
    """Acceptance timestamps from SEC submissions JSON files in a directory: `CIK##########.json` (filings.recent) and the files it lists under
    filings.files.  `__call__(cik)` -> {accession: UTC datetime}."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def __call__(self, cik):
        out = {}
        p = self.dir / f"CIK{str(cik).zfill(10)}.json"
        if not p.exists():
            return out
        doc = json.loads(p.read_text(encoding="utf-8"))
        blocks = [(doc.get("filings") or {}).get("recent") or {}]
        for f in (doc.get("filings") or {}).get("files") or []:
            q = self.dir / f.get("name", "")
            if q.is_file():
                blocks.append(json.loads(q.read_text(encoding="utf-8")))
        for b in blocks:
            for accn, acc in zip(b.get("accessionNumber") or [], b.get("acceptanceDateTime") or []):
                t = parse_accepted(acc)
                if t is not None:
                    out[accn] = t
        return out


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


# ---- the production extractor, vendored -------------------------------------------------------------------------------------------------

_BFH = None


def extractor():
    """The vendored production extractor module (loaded once)."""
    global _BFH
    if _BFH is None:
        sys.path.insert(0, str(VENDORED_DIR))
        try:
            spec = importlib.util.spec_from_file_location("vendored_build_fundamentals_history", VENDORED_DIR / "build_fundamentals_history.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["vendored_build_fundamentals_history"] = mod
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(str(VENDORED_DIR))
        _BFH = mod
    return _BFH


# Supplements: ladders for fields the extractor leaves empty, applied ONLY where its cell is None, from the same own-period facts, never
# replacing an extracted value.  Every cell they fill is flagged `pit_supplement` and says so in its tag.  (Addendum B: E&P revenue and capex,
# preferred equity.)  A rung that is a COMPONENT rather than a total says so in its flag.
SUPPLEMENTS = {
    "revenue": ("duration", [("OilAndGasRevenue", None), ("OilAndGasSalesRevenue", None), ("ExplorationAndProductionRevenue", None),
                             ("ResultsOfOperationsRevenueFromOilAndGasProducingActivities", "revenue_is_producing_activities_component")]),
    "capex": ("duration", [("PaymentsToExploreAndDevelopOilAndGasProperties", "capex_ep_exploration_and_development_unproven_total"),
                           ("PaymentsToAcquireOilAndGasPropertyAndEquipment", "capex_ep_acquisition_line_may_be_component")]),
    "preferred_equity": ("instant", [("PreferredStockValue", None), ("PreferredStockValueOutstanding", None)]),
}

# raw concepts carried by name (insurer decomposition, ASC 932 standardized measure, lending book, deposits)
CONCEPT_TAGS = ("PremiumsEarnedNet", "PremiumsEarnedNetPropertyAndCasualty", "PremiumsEarnedNetLife", "PolicyholderBenefitsAndClaimsIncurredNet",
                "PolicyholderBenefitsAndClaimsIncurredGross", "DeferredPolicyAcquisitionCostAmortizationExpense", "NetInvestmentIncome",
                "StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves",
                "DiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReservesStandardizedMeasure",
                "StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserveQuantities",
                "LoansAndLeasesReceivableNetReportedAmount", "LoansAndLeasesReceivableNetOfDeferredIncome",
                "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss", "LoansReceivableNet", "Deposits",
                "LiabilityForFuturePolicyBenefits", "LiabilityForClaimsAndClaimsAdjustmentExpense", "UnearnedPremiums",
                "PolicyholderContractDeposits")

# the 29 fields the engines read (valuation/common.py FIELDS on the engines branch)
ENGINE_FIELDS = (
    "revenue", "operating_income", "pretax_income", "tax_provision", "net_income", "da", "capex", "ppe_net",
    "cash", "st_investments", "lt_investments", "debt_current", "short_term_borrowings_separate", "debt_lt_noncurrent",
    "finance_lease_liability", "operating_lease_liability", "equity", "equity_incl_nci", "goodwill",
    "intangibles_ex_goodwill", "amortization_intangibles", "interest_expense", "total_assets", "total_liabilities",
    "current_assets", "current_liabilities", "insurance_reserves", "preferred_equity", "ocf",
)
DURATION_FIELDS = {"revenue", "operating_income", "pretax_income", "tax_provision", "net_income", "da", "capex", "amortization_intangibles",
                   "interest_expense", "ocf", "gross_profit", "sga", "sbc", "shares_diluted", "eps_diluted"}

Cell = namedtuple("Cell", "val tag unit accn filed form own flags")

_QUARTER_FIELDS = None


def quarter_fields():
    """{field: ("duration"|"instant", [tags in ladder order])}: the quarterly fields, taken from the production extractor's own ladders."""
    global _QUARTER_FIELDS
    if _QUARTER_FIELDS is None:
        B = extractor()

        def combined(f):
            spec = B.FIELD_SPECS.get(f)
            return list(spec["COMBINED"]) if spec else list(B.DURATION_TAGS[f])

        dur = {f: ("duration", combined(f)) for f in ("revenue", "gross_profit", "operating_income", "pretax_income", "tax_provision", "ocf", "capex", "da")}
        dur["net_income"] = ("duration", ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"])
        for f in ("interest_expense", "sga", "sbc"):
            dur[f] = ("duration", list(B.DURATION_TAGS[f]))
        inst = {f: ("instant", list(B.INSTANT_TAGS[f])) for f in ("total_assets", "current_assets", "current_liabilities", "total_liabilities", "cash",
                                                                   "receivables", "inventory", "ppe_net")}
        inst["equity"] = ("instant", ["StockholdersEquity", "EquityAttributableToOwnersOfParent",
                                      "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
        for f in ("debt_lt_noncurrent", "debt_current"):
            inst[f] = ("instant", list(B.INSTANT_FIELD_SPECS[f]["COMBINED"]))
        _QUARTER_FIELDS = {**dur, **inst}
    return _QUARTER_FIELDS


def quarter_tags():
    return {t for _k, tags in quarter_fields().values() for t in tags}


# ---- the store: companyfacts reduced to annual-report facts --------------------------------------------------------------------------

def compact_company(obj):
    """One companyfacts member -> {"cik", "name", "facts": {taxonomy: {tag: {unit: [[start, end, val, accn, filed, form, fy, fp], ...]}}}}.

    Keeps every tag of the annual-report forms (the extractor reads many tags, including whole families for its closure tests) and the dei cover-page
    share count of periodic reports.  A fact with no filing date cannot be placed in time and is dropped (counted); S-1 / F-1 and quarterly facts
    are not kept."""
    facts, no_filed = {}, 0
    qfacts, qtags = {}, quarter_tags()
    for taxo in ("us-gaap", "ifrs-full"):
        for tag, cb in ((obj.get("facts") or {}).get(taxo) or {}).items():
            if tag not in qtags:
                continue
            for unit, vals in ((cb or {}).get("units") or {}).items():
                for v in vals:
                    if v.get("form") in QUARTER_FORMS and v.get("filed") and v.get("val") is not None:
                        qfacts.setdefault(taxo, {}).setdefault(tag, {}).setdefault(unit, []).append(
                            [v.get("start"), v.get("end"), v["val"], v.get("accn") or "", v["filed"], v["form"], v.get("fy"), v.get("fp")])
    for taxo in STORE_TAXONOMIES:
        for tag, cb in ((obj.get("facts") or {}).get(taxo) or {}).items():
            for unit, vals in ((cb or {}).get("units") or {}).items():
                for v in vals:
                    form = v.get("form")
                    if taxo == "dei":
                        if tag != COVER_TAG or form not in COVER_FORMS:
                            continue
                    elif form not in ANNUAL_FORMS:
                        continue
                    if v.get("val") is None:
                        continue
                    if not v.get("filed"):
                        no_filed += 1
                        continue
                    facts.setdefault(taxo, {}).setdefault(tag, {}).setdefault(unit, []).append(
                        [v.get("start"), v.get("end"), v["val"], v.get("accn") or "", v["filed"], form, v.get("fy"), v.get("fp")])
    return {"cik": str(obj.get("cik", "")).zfill(10), "name": obj.get("entityName"), "facts": facts, "qfacts": qfacts, "dropped_no_filed": no_filed,
            "layer_version": PIT_LAYER_VERSION}


def _fact_dict(a):
    return {"start": a[0], "end": a[1], "val": a[2], "accn": a[3], "filed": a[4], "form": a[5]}


def _unpack(r):
    """(start, end, val, accn, filed, form) of a stored row (rows written before fy/fp were stored have six elements)."""
    return r[0], r[1], r[2], r[3], r[4], r[5]


PIT_VALID, PIT_INVALID, MISSING, AMBIGUOUS, RESTATED, CORPORATE_ACTION_UNRESOLVED = (
    "PIT_VALID", "PIT_INVALID", "MISSING", "AMBIGUOUS", "RESTATED", "CORPORATE_ACTION_UNRESOLVED")
INPUT_MODE, OUTCOME_MODE = "as_known", "first_filed"


class Extraction:
    """The extractor's output for one (company, date, mode) and what is needed to say where each cell came from."""

    def __init__(self, history, bundle, facts, own, currency, notes):
        self.history, self.bundle, self.facts, self.own, self.currency, self.notes = history, bundle, facts, own, currency, notes


class CompanyPit:
    """One company's stored facts and the as-of logic over them."""

    def __init__(self, doc, ticker=None, acceptance=None):
        self.acceptance = acceptance or {}              # {accession: UTC datetime of EDGAR acceptance}
        self.cik = doc["cik"]
        self.name = doc.get("name")
        self.ticker = ticker
        self.facts = doc["facts"]
        self.qfacts = doc.get("qfacts")                 # None: a store built before quarterly facts were kept
        self._acc = None
        self._ext = {}

    # -- annual accessions --
    def accessions(self):
        """{accn: {"filed", "form", "period"}} of the annual-report accessions: period of report = the latest end among the accession's
        fiscal-year-length duration facts (the latest instant end when it has none)."""
        if self._acc is None:
            acc, inst = {}, {}
            for taxo, tags in self.facts.items():
                if taxo == "dei":
                    continue
                for tag, units in tags.items():
                    for unit, rows in units.items():
                        for row_ in rows:
                            start, end, _v, accn, filed, form = _unpack(row_)
                            if end is None:
                                continue
                            a = acc.setdefault(accn, {"filed": filed, "form": form, "period": None})
                            if filed < a["filed"]:
                                a["filed"] = filed
                            if start is not None:
                                d = _days(start, end)
                                if d is not None and DAYS_LO <= d <= DAYS_HI and (a["period"] is None or end > a["period"]):
                                    a["period"] = end
                            elif accn not in inst or end > inst[accn]:
                                inst[accn] = end
            for accn, a in acc.items():
                if a["period"] is None:
                    a["period"] = inst.get(accn)
                    a["period_from_instant"] = True
            self._acc = {k: v for k, v in acc.items() if v["period"] is not None}
        return self._acc

    def fiscal_year_index(self):
        """[{"fye", "own_accn", "own_filed", "own_form", "own_is_amendment"}] sorted: one per period of report (period ends within
        FYE_CLUSTER_DAYS are one year); the own filing is the earliest-filed ORIGINAL annual report (an amendment only when none is held)."""
        items = sorted((a["period"], a["filed"], accn, a["form"]) for accn, a in self.accessions().items())
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
            own = min(originals or cl, key=lambda c: (c[1], c[2]))
            idx.append({"fye": own[0], "own_accn": own[2], "own_filed": own[1], "own_form": own[3], "own_is_amendment": not originals,
                        "accns": {c[2] for c in cl}})
        return idx

    # -- eligibility: the decision timestamp is 16:00 ET on the valuation date --
    def eligibility(self, asof_iso):
        """f(accession, filed) -> "ok" | "invalid" | "ambiguous" at valuation date `asof_iso` (None: everything is ok).  With an acceptance
        timestamp: ok iff accepted at or before 16:00 ET on the date.  Without one: ok when filed on an earlier date, ambiguous when filed on the
        date itself (the time of day is unknown), invalid when later."""
        if asof_iso is None:
            return lambda accn, filed: "ok"
        cut = decision_time_utc(asof_iso)
        acc = self.acceptance

        def f(accn, filed):
            t = acc.get(accn)
            if t is not None:
                return "ok" if t <= cut else "invalid"
            if filed < asof_iso:
                return "ok"
            return "ambiguous" if filed == asof_iso else "invalid"
        return f

    # -- the cut: what was knowable at T --
    def _facts_cut(self, asof_iso, mode):
        """{tag: {"units": {unit: [fact dict]}}} merged (ifrs-full under us-gaap) + the dei dict + srt, from the facts that count at `asof_iso`
        (None: no cutoff).  mode "first_filed" (outcomes): own-period facts only, earliest filing per (tag, unit, period); "as_known" (inputs): every
        eligible fact, so the latest filing known at the date, amendments and restated comparatives included (what the production extractor reads)."""
        acc = self.accessions() if mode == OUTCOME_MODE else None
        elig = self.eligibility(asof_iso)
        out = {}
        for taxo, tags in self.facts.items():
            if taxo == "dei":
                continue
            tgt = out.setdefault(taxo, {})
            for tag, units in tags.items():
                for unit, rows in units.items():
                    keep = {}
                    for r in rows:
                        start, end, _v, accn, filed, form = _unpack(r)
                        if elig(accn, filed) != "ok":
                            continue
                        if mode == OUTCOME_MODE:
                            a = acc.get(accn)
                            if a is None or end is None or abs(_days(a["period"], end)) > FYE_CLUSTER_DAYS:
                                continue
                            k = (start, end)
                            key = (filed, form in ANNUAL_AMENDMENT, accn)
                            if k not in keep or key < keep[k][0]:
                                keep[k] = (key, r)
                        else:
                            keep[(start, end, accn)] = ((filed,), r)
                    if keep:
                        tgt.setdefault(tag, {"units": {}})["units"][unit] = [_fact_dict(r) for _k, r in keep.values()]
        dei = {}
        for tag, units in ((self.facts.get("dei") or {}).items()):
            for unit, rows in units.items():
                lst = [_fact_dict(r) for r in rows if elig(r[3], r[4]) == "ok"]
                if lst:
                    dei.setdefault(tag, {"units": {}})["units"][unit] = lst
        return out, dei

    @staticmethod
    def _currency(us, ifrs):
        """USD when the company files any dollar fact for the balance-sheet and income tags below (the production extractor reads dollars only, so a
        foreign filer's USD convenience translation is what it reads); otherwise the unit of those tags with the most facts (shares, ratios and
        per-share units excluded), which is then carried in its own currency and stamped."""
        count = defaultdict(int)
        for src in (ifrs, us):
            for tag in ("Assets", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss", "ProfitLoss", "Equity",
                        "StockholdersEquity", "Liabilities"):
                for unit, rows in ((src.get(tag) or {}).get("units") or {}).items():
                    if "/" not in unit and unit not in ("shares", "pure"):
                        count[unit] += len(rows)
        if not count:
            return "USD"
        if count.get("USD", 0) > 0:
            return "USD"           # a filer with dollar facts (a 20-F convenience translation included) is read in dollars, as the production extractor reads it
        return max(count, key=count.get)

    def extract(self, asof, mode=INPUT_MODE):
        """The Extraction at `asof` (cached).  Runs the vendored production extractor on the cut document."""
        asof_iso = None if asof is None else to_date(asof).isoformat()
        key = (asof_iso, mode)
        if key in self._ext:
            return self._ext[key]
        B = extractor()
        cut, dei = self._facts_cut(asof_iso, mode)
        us, ifrs, srt = cut.get("us-gaap", {}), cut.get("ifrs-full", {}), cut.get("srt", {})
        currency = self._currency(us, ifrs)
        notes = []
        if currency != "USD":
            notes.append(f"reporting_currency:{currency}")
            for src in (us, ifrs, srt):
                for cb in src.values():
                    units = cb["units"]
                    for u in list(units):
                        if u == currency:
                            units["USD"] = units.pop(u)
                        elif u == f"{currency}/shares":
                            units["USD/shares"] = units.pop(u)
        facts = dict(ifrs)
        facts.update(us)
        for tag in B.SRT_TAGS:
            if tag in srt:
                facts["srt:" + tag] = srt[tag]
        try:
            history, bundle = B.extract_history(facts, self.ticker, dei)
        except Exception as exc:                     # an extractor failure is stated, never papered over
            history, bundle = {}, None
            notes.append(f"extractor_error:{type(exc).__name__}:{exc}")
        own = {fy["fye"]: fy for fy in self.fiscal_year_index()}
        ext = Extraction(history or {}, bundle or {}, facts, own, currency, notes)
        self._ext[key] = ext
        return ext

    # -- cells --
    def _find_fact(self, ext, tag, end, want_duration, val=None):
        """The fact behind a cell: the tag, a period end within FYE_CLUSTER_DAYS of `end`, and (when given) the cell's value; of several, the
        earliest filed (the filing in which that value first appeared).  Falls back to the earliest filed fact of the tag and period when no fact
        carries the value (a scale-corrected or summed cell)."""
        best = fallback = None
        for t in str(tag).split("+"):
            for unit, rows in ((ext.facts.get(t) or {}).get("units") or {}).items():
                for f in rows:
                    if f.get("end") is None or abs(_days(end, f["end"])) > FYE_CLUSTER_DAYS:
                        continue
                    if want_duration and f.get("start") is None:
                        continue
                    k = (f["filed"], f["accn"])
                    if fallback is None or k < fallback[0]:
                        fallback = (k, f, unit)
                    if val is not None and is_num(f["val"]) and abs(f["val"] - val) <= 1e-9 * max(1.0, abs(val)) and (best is None or k < best[0]):
                        best = (k, f, unit)
        return best or fallback

    def fiscal_years(self, asof, mode=INPUT_MODE, states=False):
        """{fye iso: FiscalYear}: the fiscal years that exist at `asof` (own annual report eligible at the decision time); asof None = no cutoff.
        states=True marks each cell whose as-known value differs from the period's first-filed value with the flag RESTATED (a second extraction)."""
        ext = self.extract(asof, mode)
        out = {}
        B = extractor()
        idx = {fy["fye"]: fy for fy in self.fiscal_year_index()}
        for y, row in ext.history.items():
            pe = ext.bundle.get("period_end", {}).get(str(y))
            if pe is None:
                continue
            own = next((fy for f, fy in idx.items() if abs(_days(f, pe)) <= FYE_CLUSTER_DAYS), None)
            if own is None:
                continue
            cells = {}
            tags = ext.bundle.get("tags", {})
            overrides = (ext.bundle.get("overrides") or {}).get(str(y), {})
            for field, val in row.items():
                if not is_num(val):
                    continue
                tag = (tags.get(field) or {}).get(y)
                if field == "fcf":
                    parts = [cells.get("ocf"), cells.get("capex")]
                    if all(parts):
                        cells[field] = Cell(float(val), "derived:ocf-capex", "USD", own["own_accn"], max(p.filed for p in parts), own["own_form"],
                                            True, ("derived",))
                    continue
                hit = self._find_fact(ext, tag, pe, field in DURATION_FIELDS, val) if tag else None
                if hit is not None:
                    _k, f, unit = hit
                    accn = overrides.get(field) or f["accn"]
                    flags = ["from_amendment"] if f["form"] in ANNUAL_AMENDMENT else []
                    cells[field] = Cell(float(val), str(tag), unit, accn, f["filed"], f["form"], accn in own["accns"], tuple(flags))
                else:
                    cells[field] = Cell(float(val), str(tag) if tag else "unknown", "USD", own["own_accn"], own["own_filed"], own["own_form"], True,
                                        ("fact_not_located",))
            self._supplement(ext, pe, row, cells, own)
            if not cells:
                continue
            stamps = ["own_filing_is_amendment"] if own["own_is_amendment"] else []
            stamps += [n for n in ext.notes if n.startswith("reporting_currency")]
            out[pe] = FiscalYear(pe, int(y), own["own_filed"], own["own_accn"], own["own_form"], cells, tuple(stamps),
                                 {k: v for k, v in row.items()}, ext.currency)
        if states and mode == INPUT_MODE and out:
            first = self.fiscal_years(asof, OUTCOME_MODE)
            for pe, fy in out.items():
                f1 = first.get(pe)
                for field, c in list(fy.cells.items()):
                    c1 = f1.cells.get(field) if f1 else None
                    if c1 is not None and c1.val != c.val:
                        fy.cells[field] = c._replace(flags=c.flags + (RESTATED,))
        return dict(sorted(out.items()))

    def _supplement(self, ext, pe, row, cells, own):
        for field, (kind, ladder) in SUPPLEMENTS.items():
            if is_num(row.get(field)):
                continue
            for tag, flag in ladder:
                hit = None
                for unit, rows in ((ext.facts.get(tag) or {}).get("units") or {}).items():
                    if unit != "USD":
                        continue
                    for f in rows:
                        if f.get("end") is None or abs(_days(pe, f["end"])) > FYE_CLUSTER_DAYS or not is_num(f["val"]):
                            continue
                        d = _days(f["start"], f["end"]) if f.get("start") else None
                        if kind == "duration" and (d is None or not DAYS_LO <= d <= DAYS_HI):
                            continue
                        if kind == "instant" and f.get("start") is not None:
                            continue
                        k = (f["filed"], f["accn"])
                        if hit is None or k < hit[0]:
                            hit = (k, f)
                if hit is not None:
                    f = hit[1]
                    flags = ("pit_supplement",) + ((flag,) if flag else ())
                    cells[field] = Cell(float(f["val"]), tag, "USD", f["accn"], f["filed"], f["form"], f["accn"] in own["accns"], flags)
                    row[field] = float(f["val"])
                    break
        ocf, cx = row.get("ocf"), row.get("capex")
        if "fcf" not in cells and is_num(ocf) and is_num(cx):
            row["fcf"] = ocf - cx

    def concepts(self, asof, names=CONCEPT_TAGS, mode=INPUT_MODE):
        """{name: {period_end: Cell}}: raw concepts by name, as known at `asof` (mode first_filed: own-period, first filed), annual-length flows or
        instants.  The value of a period is that of the latest eligible filing (as_known) or the first (first_filed)."""
        ext = self.extract(asof, mode)
        out = {}
        for name in names:
            per = {}
            for unit, rows in ((ext.facts.get(name) or {}).get("units") or {}).items():
                for f in rows:
                    if f.get("end") is None or not is_num(f["val"]):
                        continue
                    if f.get("start") is not None:
                        d = _days(f["start"], f["end"])
                        if d is None or not DAYS_LO <= d <= DAYS_HI:
                            continue
                    k = (f["filed"], f["accn"])
                    better = f["end"] not in per or (k < per[f["end"]][0] if mode == OUTCOME_MODE else k > per[f["end"]][0])
                    if better:
                        per[f["end"]] = (k, f, unit)
            if per:
                out[name] = {pe: Cell(float(f["val"]), name, unit, f["accn"], f["filed"], f["form"], True, ()) for pe, (_k, f, unit) in per.items()}
        return out

    # -- quarterly facts --
    def _quarter_candidates(self, field, asof_iso, mode):
        """{(start, end): (value, meta)} for one field: of the ladder's tags the first that has the period; of that tag's eligible filings the latest
        (as_known) or the earliest (first_filed); annual-report facts (12-month and instants) and 10-Q facts together."""
        kind, ladder = quarter_fields()[field]
        elig = self.eligibility(asof_iso)
        pools = [self.qfacts or {}, self.facts]
        best = {}
        for rank, tag in enumerate(ladder):
            for taxo in ("us-gaap", "ifrs-full"):
                for pool in pools:
                    for unit, rows in (((pool.get(taxo) or {}).get(tag)) or {}).items():
                        if unit != "USD":
                            continue
                        for r in rows:
                            start, end, val, accn, filed, form = _unpack(r)
                            if end is None or not is_num(val) or elig(accn, filed) != "ok":
                                continue
                            if (kind == "duration") != (start is not None):
                                continue
                            k = (start, end)
                            cur = best.get(k)
                            if cur is not None and cur[2] < rank:
                                continue                    # a higher-priority tag already has the period
                            key = (filed, accn)
                            newer = cur is None or cur[2] > rank or (key < cur[1] if mode == OUTCOME_MODE else key > cur[1])
                            if newer:
                                best[k] = (val, key, rank, tag, form, r)
        return best

    def quarters(self, asof, fields=None, mode=INPUT_MODE):
        """The quarterly records at `asof` (see the module docstring); [] with a note-bearing first element never: use `quarterly_notes`."""
        asof_iso = None if asof is None else to_date(asof).isoformat()
        acc = self.acceptance
        out = []
        for field, (kind, _ladder) in quarter_fields().items():
            if fields is not None and field not in fields:
                continue
            latest = self._quarter_candidates(field, asof_iso, mode)
            first = self._quarter_candidates(field, asof_iso, OUTCOME_MODE) if mode == INPUT_MODE else latest

            def rec(start, end, value, qkind, sources, st, tag, unit="USD"):
                src = [x for x in sources if x]
                filed = max(x["filed"] for x in src)
                last = max(src, key=lambda x: (x["filed"], x["accn"]))
                t = acc.get(last["accn"])
                restated = any(x.get("restated") for x in src)
                return {"cik": self.cik, "field": field, "tag": tag, "unit": unit, "period_start": start, "period_end": end, "value": value, "kind": qkind,
                        "form": last["form"], "filed": filed, "accepted_at": None if t is None else t.isoformat(), "accession": last["accn"],
                        "amended": last["form"].endswith("/A"), "fy": last.get("fy"), "fp": last.get("fp"), "sources": sorted({x["accn"] for x in src}),
                        "first_value": st, "state": RESTATED if restated else PIT_VALID}

            def meta(k):
                v = latest[k]
                r = v[5]
                f1 = first.get(k)
                return {"value": v[0], "filed": v[1][0], "accn": v[1][1], "form": v[4], "tag": v[3], "fy": r[6] if len(r) > 6 else None,
                        "fp": r[7] if len(r) > 7 else None, "restated": f1 is not None and f1[0] != v[0], "first": None if f1 is None else f1[0]}

            if kind == "instant":
                for (start, end) in latest:
                    m = meta((start, end))
                    out.append(rec(start, end, m["value"], "reported_instant", [m], m["first"], m["tag"]))
                continue
            keys = sorted(latest)

            def dur(k):
                return _days(k[0], k[1])

            q3m = [k for k in keys if 80 <= (dur(k) or 0) <= 100]
            ytd = [k for k in keys if (dur(k) or 0) > 100 and (dur(k) or 0) < 350]
            fy = [k for k in keys if DAYS_LO <= (dur(k) or 0) <= DAYS_HI]
            for k in q3m:
                m = meta(k)
                out.append(rec(k[0], k[1], m["value"], "reported_3m", [m], m["first"], m["tag"]))

            def near(a, b, tol=12):
                return a is not None and b is not None and abs(_days(a, b)) <= tol

            have = {(r["period_start"], r["period_end"]) for r in out if r["field"] == field}

            def known(start, end):
                for k in keys:
                    if near(k[0], start) and near(k[1], end):
                        return k
                return None
            for y in ytd + fy:                                 # a year-to-date or full-year figure: difference against the shorter period that ends where it starts
                for z in keys:
                    if z == y or not near(z[0], y[0]):
                        continue
                    d_y, d_z = dur(y), dur(z)
                    if d_z is None or d_y is None or not (80 <= d_y - d_z <= 100):
                        continue
                    if not (80 <= d_z <= 290):
                        continue
                    q = (z[1], y[1])                           # the quarter after z, to y's end
                    if any(near(q[0], h[0], 3) and near(q[1], h[1], 12) for h in have):
                        continue
                    mq = meta(y)
                    mz = meta(z)
                    qkind = "derived_q4" if y in fy else "derived_ytd_difference"
                    first_v = None if (mq["first"] is None or mz["first"] is None) else mq["first"] - mz["first"]
                    out.append(rec(q[0], q[1], mq["value"] - mz["value"], qkind, [mq, mz], first_v, mq["tag"] if mq["tag"] == mz["tag"] else mq["tag"] + "-" + mz["tag"]))
                    have.add(q)
        return sorted(out, key=lambda r: (r["period_end"], r["field"]))

    def facts_table(self, asof, tags=None):
        """Every stored fact as a record with its provenance state at `asof`: {cik, taxonomy, tag, unit, value, start, end, instant, dimensions, form,
        filed, accepted_at, accession, amended, fy, fp, state}.  state: PIT_INVALID (accepted after the decision time), AMBIGUOUS (filed on the date
        with no acceptance timestamp), RESTATED (eligible but superseded by a later eligible filing with a different value), else PIT_VALID.
        `tags`: restrict to these tags.  The snapshot is built from the PIT_VALID and RESTATED-superseding records, so a number can name its accession."""
        asof_iso = to_date(asof).isoformat()
        elig = self.eligibility(asof_iso)
        recs = []
        for taxo, tg in self.facts.items():
            for tag, units in tg.items():
                if tags is not None and tag not in tags:
                    continue
                for unit, rows in units.items():
                    for r in rows:
                        start, end, val, accn, filed, form = _unpack(r)
                        e = elig(accn, filed)
                        t = self.acceptance.get(accn)
                        recs.append({"cik": self.cik, "taxonomy": taxo, "tag": tag, "unit": unit, "value": val, "start": start, "end": end,
                                     "instant": start is None, "dimensions": None, "form": form, "filed": filed,
                                     "accepted_at": None if t is None else t.isoformat(), "accession": accn, "amended": form in ANNUAL_AMENDMENT,
                                     "fy": r[6] if len(r) > 6 else None, "fp": r[7] if len(r) > 7 else None,
                                     "state": {"ok": PIT_VALID, "invalid": PIT_INVALID, "ambiguous": AMBIGUOUS}[e]})
        latest = {}
        for x in recs:
            if x["state"] == PIT_VALID:
                k = (x["taxonomy"], x["tag"], x["unit"], x["start"], x["end"])
                if k not in latest or (x["filed"], x["accession"]) > (latest[k]["filed"], latest[k]["accession"]):
                    latest[k] = x
        for x in recs:
            if x["state"] == PIT_VALID:
                top = latest[(x["taxonomy"], x["tag"], x["unit"], x["start"], x["end"])]
                if top is not x and top["value"] != x["value"]:
                    x["state"] = RESTATED
        return recs

    def cover_shares(self, asof):
        """The cover-page share count of the latest periodic report filed strictly before `asof`: every class entry of that filing summed.
        {"value", "cover_date", "filed", "accn", "form", "n_entries"} or None."""
        asof_iso = to_date(asof).isoformat()
        elig = self.eligibility(asof_iso)
        c = []
        for unit, rows in (((self.facts.get("dei") or {}).get(COVER_TAG)) or {}).items():
            if unit != "shares":
                continue
            c += [r for r in rows if elig(r[3], r[4]) == "ok" and is_num(r[2]) and r[2] > 0]
        if not c:
            return None
        last = max(r[4] for r in c)
        uniq = {(r[3], r[1], r[2]): r for r in c if r[4] == last}
        entries = list(uniq.values())
        end = max((r[1] for r in entries if r[1]), default=None)
        sel = [r for r in entries if r[1] == end] if end else entries
        return {"value": float(sum(r[2] for r in sel)), "cover_date": end, "filed": last, "accn": entries[0][3], "form": entries[0][5],
                "n_entries": len(entries)}


def fiscal_label(fye_iso):
    """The integer fiscal year of a period end: its calendar year, except a 52/53-week year ending Jan 1-7, which belongs to the year before."""
    d = date.fromisoformat(fye_iso)
    return d.year - 1 if (d.month == 1 and d.day <= 7) else d.year


class FiscalYear:
    __slots__ = ("fye", "year", "exists_from", "own_accn", "own_form", "cells", "stamps", "_row", "currency")

    def __init__(self, fye, year, exists_from, own_accn, own_form, cells, stamps, row=None, currency="USD"):
        self.fye, self.year, self.exists_from, self.own_accn, self.own_form = fye, year, exists_from, own_accn, own_form
        self.cells, self.stamps, self._row, self.currency = cells, stamps, row, currency

    def row(self):
        """{field: value} in the extractor's names (plus supplements and 'fcf'); a field not filed is None."""
        return dict(self._row) if self._row is not None else {f: c.val for f, c in self.cells.items()}

    def provenance(self):
        return {f: {"tag": c.tag, "accn": c.accn, "filed": c.filed, "form": c.form, "own_filing": c.own, "flags": list(c.flags)}
                for f, c in self.cells.items()}


class Snapshot:
    """Everything the layer knows about one company at one valuation date."""

    def __init__(self, cik, name, asof, years, cover, currency="USD"):
        self.cik, self.name, self.asof = cik, name, to_date(asof)
        self.years = years                       # {fye iso: FiscalYear}
        self.cover = cover
        self.currency = currency
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


# ---- SIC (not in companyfacts) ---------------------------------------------------------------------------------------------------------

SicRecord = namedtuple("SicRecord", "code description source point_in_time")


class SubmissionsDirSic:
    """SIC from SEC submissions JSON files (`CIK##########.json` with "sic" and "sicDescription") in a directory.  SEC publishes only the CURRENT
    assignment: `point_in_time` is False, and the engines stamp it."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def __call__(self, cik):
        p = self.dir / f"CIK{str(cik).zfill(10)}.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        code = str(d.get("sic") or "").strip() or None
        return SicRecord(code, str(d.get("sicDescription") or ""), "SEC submissions JSON (current assignment)", False)


_HDR = {
    "accession": r"ACCESSION NUMBER:\s*(\S+)", "form": r"CONFORMED SUBMISSION TYPE:\s*(\S+)", "period": r"CONFORMED PERIOD OF REPORT:\s*(\d{8})",
    "filed": r"FILED AS OF DATE:\s*(\d{8})", "name": r"COMPANY CONFORMED NAME:\s*(.+)", "cik": r"CENTRAL INDEX KEY:\s*(\d+)",
}


def parse_sec_header(text):
    """The fields of an EDGAR filing header (the SGML header of a submission, `<accession>.hdr.sgml` or the top of the `.txt`): accession, form,
    period, filed date, acceptance timestamp (UTC), company name, CIK, SIC code and description as filed.  Missing fields are None."""
    import re
    out = {k: None for k in list(_HDR) + ["accepted_at", "sic", "sic_description"]}
    for k, pat in _HDR.items():
        m = re.search(pat, text)
        if m:
            out[k] = m.group(1).strip()
    m = re.search(r"ACCEPTANCE-DATETIME>?:?\s*(\d{14})", text)
    out["accepted_at"] = parse_accepted(m.group(1)) if m else None
    m = re.search(r"STANDARD INDUSTRIAL CLASSIFICATION:\s*(.*?)\[(\d{4})\]", text)
    if m:
        out["sic_description"], out["sic"] = m.group(1).strip(), m.group(2)
    if out["cik"]:
        out["cik"] = out["cik"].zfill(10)
    for k in ("period", "filed"):
        if out[k]:
            out[k] = f"{out[k][:4]}-{out[k][4:6]}-{out[k][6:8]}"
    return out


class HeaderSic:
    """The SIC code and the company name AS FILED at T, from EDGAR filing headers: the header of the latest filing accepted at or before the decision
    time (16:00 ET) of the date.  `records` are `parse_sec_header` dicts (a directory of header files via `from_dir`).  Returns None before the first
    header on record: today's SIC is never substituted."""

    def __init__(self, records):
        self.by_cik = defaultdict(list)
        for r in records:
            if r.get("cik") and r.get("accepted_at") is not None:
                self.by_cik[r["cik"]].append(r)
        for v in self.by_cik.values():
            v.sort(key=lambda r: r["accepted_at"])

    @classmethod
    def from_dir(cls, directory):
        recs = []
        for p in sorted(Path(directory).iterdir()):
            if p.is_file() and (p.name.endswith(".hdr.sgml") or p.suffix in (".txt", ".hdr")):
                recs.append(parse_sec_header(p.read_text(encoding="utf-8", errors="replace")))
        return cls(recs)

    def _latest(self, cik, asof, need=None):
        cut = decision_time_utc(asof)
        best = None
        for r in self.by_cik.get(str(cik).zfill(10), ()):
            if r["accepted_at"] <= cut and (need is None or r.get(need)):
                best = r
        return best

    def __call__(self, cik, asof):
        r = self._latest(cik, asof, "sic")
        return None if r is None else SicRecord(r["sic"], r["sic_description"] or "", f"EDGAR filing header {r['accession']} (as filed at the date)", True)

    def name_asof(self, cik, asof):
        r = self._latest(cik, asof, "name")
        return None if r is None else r["name"]


# ---- the engines' CompanyPIT --------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PitFiled:
    """Same fields as valuation.common.Filed on the engines branch (used when that module is not importable)."""
    value: float
    period_end: str
    filed: str
    accession: str
    form: str = ""
    tag: str = ""
    period_start: str = None


def _engine_types():
    try:
        from valuation import common as c
        return c.CompanyPIT, c.Filed, c.SicInfo
    except Exception:
        return None, PitFiled, None


class PitCompany:
    """Fallback for valuation.common.CompanyPIT (same attributes and methods) when that module is not importable."""

    def __init__(self, ticker, asof, series, concepts, annual_reports, sic, cik, shares_outstanding, notes):
        self.ticker, self.asof, self.series, self.concepts = ticker, to_date(asof), series, concepts
        self.annual_reports, self.sic, self.cik, self.shares_outstanding, self.notes = annual_reports, sic, cik, shares_outstanding, notes
        self.check()

    def check(self):
        bad = [(n, pe, f.filed) for tab in (self.series, self.concepts) for n, per in tab.items() for pe, f in per.items()
               if to_date(f.filed) >= self.asof]
        bad += [("annual_report", a[0], a[1]) for a in self.annual_reports if to_date(a[1]) >= self.asof]
        if bad:
            raise ValueError(f"{self.ticker}: {len(bad)} value(s) filed on or after {self.asof}: {bad[:5]}")

    def periods(self):
        return sorted({a[0] for a in self.annual_reports})

    def row(self, period_end):
        return {f: (self.series[f][period_end].value if period_end in self.series.get(f, {}) else None) for f in ENGINE_FIELDS}

    def rows(self):
        return {pe: self.row(pe) for pe in self.periods()}

    def concept_values(self, name):
        return {pe: f.value for pe, f in sorted(self.concepts.get(name, {}).items())}

    def filing_trail(self, field_name, period_end):
        return self.series.get(field_name, {}).get(period_end)


# ---- prices: the PriceProvider interface ---------------------------------------------------------------------------------------------------

QUALITY_VERIFIED, QUALITY_UNVERIFIED, QUALITY_MISSING = "verified", "unverified", "missing"


class PricePoint:
    __slots__ = ("price", "bar", "flags", "quality")

    def __init__(self, price, bar, flags=(), quality=QUALITY_VERIFIED):
        self.price, self.bar, self.flags, self.quality = price, bar, tuple(flags), quality


class PriceSource:
    """The PriceProvider interface (Addendum C 4).  `basis` names what `close_unadjusted` is: "traded_unadjusted" is the only basis a result may rest
    on.  Every price carries `quality`: VERIFIED (a traded unadjusted close on the exact session, with the provider's split and dividend actions in
    hand), UNVERIFIED (derived or approximate: a month-end bar standing for the last session, a stale bar, an adjusted-only proxy, unknown splits) or
    MISSING (no price: `close_unadjusted` returns None, `price_quality` says why)."""
    basis = "traded_unadjusted"
    delistings = None            # {key: {"date", "type", ...}} corporate-action events that end a security's price history

    def has_key(self, key):
        raise NotImplementedError

    def close_unadjusted(self, key, asof):
        """PricePoint of the traded close on `asof` (not split- or dividend-adjusted), or None."""
        raise NotImplementedError

    def adj_close(self, key, asof):
        """PricePoint of the total-return-adjusted close on `asof`, or None.  Outcomes and past-return signals only."""
        raise NotImplementedError

    def splits(self, key):
        """[(date iso or 'YYYY-MM', ratio)] sorted; ratio 2.0 = 2-for-1.  None when the source cannot say (shares cannot then be put on the price's basis)."""
        raise NotImplementedError

    def last_date(self, key):
        raise NotImplementedError

    def last_session(self, key):
        """The date of the security's last bar, usable as `asof` for `adj_close` / `close_unadjusted`; None without bars."""
        d = self.last_date(key)
        if d is None:
            return None
        return _last_weekday_of_month(date(int(d[:4]), int(d[5:7]), 1)) if len(d) == 7 else to_date(d)

    def target_date(self, asof, months):
        """The date `months` after `asof` at which a price is read: the same calendar day (a daily source takes the latest bar within its gap);
        a monthly source overrides this with the last weekday of that month."""
        return add_months(to_date(asof), months)

    def entry_point(self, key, asof):
        """The total-return price at which a position decided at the 16:00 ET decision time on `asof` is entered: the NEXT session's adjusted close.
        A source with no sessions of its own (monthly bars) returns the decision bar and flags `no_next_session_in_monthly_data`."""
        p = self.adj_close(key, asof)
        if p is None:
            return None
        return PricePoint(p.price, p.bar, tuple(p.flags) + ("no_next_session_in_monthly_data",), QUALITY_UNVERIFIED)

    def price_quality(self, key, asof):
        """(quality, reason) of the valuation price for `key` on `asof`."""
        if not self.has_key(key):
            return QUALITY_MISSING, "ticker_not_in_provider"
        p = self.close_unadjusted(key, asof)
        if p is None:
            return QUALITY_MISSING, "no_close_on_date"
        return p.quality, ",".join(p.flags) or "exact_session"

    def delisting(self, key):
        """The corporate-action event that ended the security's history (acquisition, bankruptcy, otc_continuation, other) or None."""
        return (self.delistings or {}).get(key)


PriceProvider = PriceSource


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
    trading day) - any other date is refused, never filled with the month-end; its quality is UNVERIFIED (the last weekday may be a holiday).  The
    traded unadjusted close is the split-adjusted Close times the product of the split ratios dated in LATER months; a split in the bar's own month
    leaves the basis undetermined and is flagged."""

    def __init__(self, doc, delistings=None):
        self.prices = doc["prices"]
        self.meta = doc.get("meta", {})
        self.delistings = delistings
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
        flags = ["month_end_bar_for_last_session"] + (["split_in_bar_month"] if any(sm == m for sm, _ in self.splits(key)) else [])
        return PricePoint(float(v[0]) * later, m, flags, QUALITY_UNVERIFIED)

    def adj_close(self, key, asof):
        m, v = self._bar(key, asof)
        if v is None or not (is_num(v[1]) and v[1] > 0):
            return None
        return PricePoint(float(v[1]), m, (), QUALITY_UNVERIFIED)

    def last_date(self, key):
        ms = sorted(self.prices.get(key) or {})
        return ms[-1] if ms else None

    def target_date(self, asof, months):
        return _last_weekday_of_month(add_months(to_date(asof), months))


class DailyPriceSource(PriceSource):
    """{key: {iso date: {"close": traded unadjusted close, "adj": total-return adjusted close}}} and {key: [(iso date, ratio)]} split events with
    exact ex-dates.  A close is served for `asof` itself (VERIFIED when the split events are in hand) or the latest earlier bar within
    `max_gap_days` (UNVERIFIED, flagged `stale_bar`)."""

    def __init__(self, rows, splits=None, max_gap_days=5, delistings=None):
        self.rows, self._splits, self.max_gap = rows, splits, max_gap_days
        self.delistings = delistings
        self._sorted = {}

    def has_key(self, key):
        return key in self.rows

    def _keys(self, key):
        if key not in self._sorted:
            self._sorted[key] = sorted(self.rows.get(key) or {})
        return self._sorted[key]

    def _find(self, key, asof):
        d = to_date(asof).isoformat()
        r = self.rows.get(key)
        if not r:
            return None, None
        import bisect
        ds = self._keys(key)
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
        flags = [] if bar == to_date(asof).isoformat() else ["stale_bar"]
        if self._splits is None:
            flags.append("splits_unknown")
        return PricePoint(float(v["close"]), bar, flags, QUALITY_VERIFIED if not flags else QUALITY_UNVERIFIED)

    def adj_close(self, key, asof):
        bar, v = self._find(key, asof)
        if v is None or not (is_num(v.get("adj")) and v["adj"] > 0):
            return None
        return PricePoint(float(v["adj"]), bar)

    def entry_point(self, key, asof):
        """The first session strictly after `asof`: the adjusted close of the next bar (within the source's gap)."""
        import bisect
        d = to_date(asof).isoformat()
        ds = self._keys(key)
        i = bisect.bisect_right(ds, d)
        if i >= len(ds) or _days(d, ds[i]) is None or _days(d, ds[i]) > self.max_gap:
            return None
        v = self.rows[key][ds[i]]
        if not (is_num(v.get("adj")) and v["adj"] > 0):
            return None
        return PricePoint(float(v["adj"]), ds[i])

    def splits(self, key):
        if self._splits is None:
            return None
        return sorted((str(d), float(r)) for d, r in self._splits.get(key, ()))

    def last_date(self, key):
        ds = self._keys(key)
        return ds[-1] if ds else None


class AdjustedOnlyMonthlySource(PriceSource):
    """PROXY for a smoke run when only a split- and dividend-adjusted monthly close exists ({"prices": {key: {"YYYY-MM": adjusted close}}}).
    `basis` is "adjusted_proxy": the level is not a traded price (a dividend payer's old closes sit below what traded) and the split events are
    unknown, so market caps and yields built on it are WRONG IN LEVEL and its quality is UNVERIFIED.  Its total-return ratios are valid.  Never a
    basis for a result."""
    basis = "adjusted_proxy"

    def __init__(self, doc, delistings=None):
        self.prices = doc["prices"]
        self.delistings = delistings

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
        return None if v is None else PricePoint(v, m, ["PROXY_adjusted_close"], QUALITY_UNVERIFIED)

    def adj_close(self, key, asof):
        m, v = self._val(key, asof)
        return None if v is None else PricePoint(v, m, (), QUALITY_UNVERIFIED)

    def splits(self, key):
        return None

    def last_date(self, key):
        ms = sorted(self.prices.get(key) or {})
        return ms[-1] if ms else None

    def target_date(self, asof, months):
        return _last_weekday_of_month(add_months(to_date(asof), months))


class NetworkNotAllowed(RuntimeError):
    pass


class YahooPriceProvider:
    """Yahoo Finance as the first PriceProvider (Addendum C 4): `history(auto_adjust=False, actions=True)` per ticker, cached on disk, then served as a
    `DailyPriceSource`.  Yahoo's "Close" is split-adjusted but not dividend-adjusted; the traded unadjusted close is Close times the product of the split
    ratios with ex-dates after the bar.  NOTHING here touches the network unless `allow_network=True` (the operator's permission to download) or a
    `downloader` is injected (tests).  `downloader(key, start, end)` -> [{"date", "close", "adj_close", "dividend", "split"}, ...] (split 0 or None
    when there is none).  A ticker Yahoo cannot serve is recorded as empty and counted: `unpriceable(keys)`."""

    def __init__(self, cache_dir, allow_network=False, downloader=None):
        self.cache = Path(cache_dir)
        self.allow_network = allow_network
        self.downloader = downloader

    def _path(self, key):
        return self.cache / f"{key}.json"

    def _download(self, key, start, end):
        if self.downloader is not None:
            return self.downloader(key, start, end)
        if not self.allow_network:
            raise NetworkNotAllowed(f"Yahoo download of {key} refused: allow_network is False (a download needs the operator's permission)")
        import yfinance as yf                                     # imported only when a download is actually permitted
        df = yf.Ticker(key).history(start=start, end=end, auto_adjust=False, actions=True)
        return [{"date": ts.date().isoformat(), "close": float(r["Close"]), "adj_close": float(r["Adj Close"]),
                 "dividend": float(r.get("Dividends", 0.0) or 0.0), "split": float(r.get("Stock Splits", 0.0) or 0.0)} for ts, r in df.iterrows()]

    def fetch(self, keys, start, end):
        self.cache.mkdir(parents=True, exist_ok=True)
        for k in keys:
            if self._path(k).exists():
                continue
            rows = self._download(k, start, end)
            self._path(k).write_text(json.dumps({"key": k, "start": start, "end": end, "rows": rows}), encoding="utf-8")

    def load(self, keys, delistings=None):
        """A DailyPriceSource over the cached tickers (a ticker with no cached rows has no key: the caller counts it as unpriceable)."""
        rows, splits = {}, {}
        for k in keys:
            if not self._path(k).exists():
                continue
            doc = json.loads(self._path(k).read_text(encoding="utf-8"))
            if not doc["rows"]:
                continue
            ev = [(r["date"], float(r["split"])) for r in doc["rows"] if is_num(r.get("split")) and r["split"] not in (0, 0.0)]
            rr = {}
            for r in doc["rows"]:
                later = 1.0
                for d, ratio in ev:
                    if d > r["date"]:
                        later *= ratio
                rr[r["date"]] = {"close": r["close"] * later, "adj": r["adj_close"]}
            rows[k], splits[k] = rr, ev
        return DailyPriceSource(rows, splits, delistings=delistings)

    def unpriceable(self, keys):
        """The keys with no cached price rows (Yahoo cannot serve them, or they were never fetched)."""
        return [k for k in keys if not self._path(k).exists() or not json.loads(self._path(k).read_text(encoding="utf-8"))["rows"]]


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

    def __init__(self, store_dir, zip_path=None, price_source=None, id_map=None, sic_source=None, acceptance_source=None, sic_history=None):
        self.sic_source = sic_source
        self.sic_history = sic_history                    # HeaderSic: the SIC and name as filed at T
        self.acceptance_source = acceptance_source        # cik -> {accession: UTC acceptance datetime}; None: filing dates only
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
        self._cache[cik] = CompanyPit(doc, ticker=self.ticker_for(cik),
                                      acceptance=self.acceptance_source(cik) if self.acceptance_source is not None else None)
        return self._cache[cik]

    def drop_cache(self):
        self._cache.clear()
        self._snap.clear()

    def evict(self, cik, keep_snapshots=False):
        """Forget one company's loaded facts and extraction (the memory hog: every cut document of every date) and, unless `keep_snapshots`, its
        snapshots.  A pass over thousands of companies must evict as it goes."""
        cik = str(cik).zfill(10)
        self._cache.pop(cik, None)
        if not keep_snapshots:
            for k in [k for k in self._snap if k[0] == cik]:
                del self._snap[k]

    # -- as-of views --
    def fiscal_years(self, cik, asof, mode=INPUT_MODE):
        c = self.company(cik)
        return {} if c is None else c.fiscal_years(asof, mode)

    def snapshot(self, cik, asof, mode=INPUT_MODE):
        """The Snapshot of a company at `asof` (cached until `drop_cache`); None when the company is not in the store or the archive."""
        k = (str(cik).zfill(10), to_date(asof).isoformat(), mode)
        if k not in self._snap:
            c = self.company(cik)
            self._snap[k] = None if c is None else Snapshot(c.cik, c.name, asof, c.fiscal_years(asof, mode), c.cover_shares(asof),
                                                            c.extract(asof, mode).currency)
        return self._snap[k]

    def rows(self, cik, asof):
        s = self.snapshot(cik, asof)
        return {} if s is None else s.rows()

    def outcome_fiscal_years(self, cik):
        """Every fiscal year, first-filed, with NO date cutoff.  For outcomes only: an engine that calls this has looked ahead."""
        c = self.company(cik)
        return {} if c is None else c.fiscal_years(None, "first_filed")

    # -- SIC and the engines' view --
    def sic(self, cik, asof=None):
        """SicRecord of the company.  With a `sic_history` (filing headers) and a date: the SIC as filed at that date (point_in_time True), None when
        no header is on record before it - today's record is never substituted.  Without a history: the CURRENT assignment from `sic_source`
        (point_in_time False, stamped), which an as-of use must treat as a look-ahead label."""
        cik = str(cik).zfill(10)
        if self.sic_history is not None and asof is not None:
            return self.sic_history(cik, asof)
        return None if self.sic_source is None else self.sic_source(cik)

    def company_pit(self, cik, asof, ticker=None):
        """The engines' CompanyPIT at `asof` (valuation.common.CompanyPIT when importable, else an equivalent PitCompany): series[field][period_end] ->
        Filed for the 29 engine fields, concepts[name][period_end], the annual-report list, SIC, and the cover-page share count.  Every value is
        first filed, from its own annual report, filed strictly before `asof`.  None when the company is not in the store or the archive."""
        cik = str(cik).zfill(10)
        c = self.company(cik)
        if c is None:
            return None
        CPIT, Filed, SicInfo = _engine_types()
        asof_d = to_date(asof)
        fys = c.fiscal_years(asof_d, INPUT_MODE, states=True)
        series = {f: {} for f in ENGINE_FIELDS}
        reports = []
        for pe, fy in fys.items():
            reports.append((pe, fy.exists_from, fy.own_accn, fy.own_form))
            for f in ENGINE_FIELDS:
                cell = fy.cells.get(f)
                if cell is not None:
                    series[f][pe] = Filed(cell.val, pe, cell.filed, cell.accn, cell.form, cell.tag)
        concepts = {n: {pe: Filed(x.val, pe, x.filed, x.accn, x.form, x.tag) for pe, x in per.items()} for n, per in c.concepts(asof_d).items()}
        cov = c.cover_shares(asof_d)
        shares = None if cov is None else Filed(cov["value"], cov["cover_date"] or cov["filed"], cov["filed"], cov["accn"], cov["form"], COVER_TAG)
        sr = self.sic(cik, asof_d)
        notes = list(c.extract(asof_d).notes)
        ticker = ticker or self.ticker_for(cik) or f"CIK{cik}"
        prov = {(f, pe): (RESTATED if RESTATED in fy.cells[f].flags else PIT_VALID) for pe, fy in fys.items() for f in ENGINE_FIELDS if f in fy.cells}
        if CPIT is None:
            obj = PitCompany(ticker, asof_d, series, concepts, reports, sr, cik, shares, notes)
        else:
            sic = None if sr is None else SicInfo(sr.code, sr.description, sr.source, sr.point_in_time)
            obj = CPIT(ticker, asof_d, series=series, concepts=concepts, annual_reports=reports, sic=sic, cik=cik, shares_outstanding=shares,
                       notes=notes)
        obj.provenance = prov           # {(field, period_end): PIT_VALID | RESTATED}; a field/period not in it is MISSING
        return obj

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
            self.evict(cik, keep_snapshots=True)
            if not fy:
                why["no_annual_report_before_date"] += 1
                continue
            if not any(("revenue" in y.cells or "net_income" in y.cells or "total_assets" in y.cells) for y in fy.values()):
                why["no_figures"] += 1
                continue
            keep.append(c.cik)
        return keep, dict(why)

    # -- price and share basis --
    def market_cap(self, cik, asof, key=None):
        """`_market_cap` plus `price_quality` (verified / unverified / missing), its reason, and `provenance_state`: PIT_VALID, MISSING (no price, no
        shares, or a company that does not report in dollars), AMBIGUOUS (share basis undetermined: a split on the count's day) or
        CORPORATE_ACTION_UNRESOLVED (split events unknown, or a cover count 100x from the filed count)."""
        out = self._market_cap(cik, asof, key)
        src = self.price_source
        k = key or self.ticker_for(cik)
        if src is None or k is None:
            q, why = QUALITY_MISSING, "no_price_source" if src is None else "no_price_key"
        else:
            q, why = src.price_quality(k, asof)
        out["price_quality"], out["price_quality_reason"] = q, why
        r = out.get("reason")
        if r == "share_basis_undetermined":
            st = AMBIGUOUS
        elif r == "share_count_scale_conflict" or "splits_unknown" in out["flags"]:
            st = CORPORATE_ACTION_UNRESOLVED
        elif r is not None:
            st = MISSING
        else:
            st = PIT_VALID
        out["provenance_state"] = st
        return out

    def _market_cap(self, cik, asof, key=None):
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
        snap = self.snapshot(cik, asof_d)
        asof_iso = asof_d.isoformat()
        if snap is not None and snap.currency != "USD":
            out["flags"].append(f"reporting_currency_{snap.currency}")
            out["reason"] = "reporting_currency_not_usd"
            return out
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

    def quarterly(self, cik, asof, fields=None, mode=INPUT_MODE):
        """The quarterly records of a company at `asof` (see the module docstring): {"records": [...], "notes": [...]}.  Notes say when the store has
        no quarterly facts (built before they were kept) or the company is unknown."""
        c = self.company(cik)
        if c is None:
            return {"records": [], "notes": ["company_not_in_store"]}
        if c.qfacts is None:
            return {"records": [], "notes": ["store_has_no_quarterly_facts_rebuild_it"]}
        return {"records": c.quarters(asof, fields, mode), "notes": []}

    def quarterly_rows(self, cik, asof, fields=("revenue", "operating_income", "net_income"), max_quarters=6, mode=INPUT_MODE):
        """The latest quarters as {"period_end", "filed", "accession", "accepted_at", "values": {field: value}, "prior_year": {field: value of the same
        quarter a year earlier}, "kinds": {field: kind}, "states": {field: provenance state}} - the shape of the Muse layer's `CompanyFactsQuarters.quarters()`,
        newest last.  A quarter is listed when any requested field has it (a quarter not yet derivable is absent)."""
        recs = [r for r in self.quarterly(cik, asof, fields, mode)["records"] if r["kind"] != "reported_instant" and 80 <= (_days(r["period_start"], r["period_end"]) or 0) <= 100]
        by = defaultdict(dict)
        for r in recs:
            by[r["period_end"]][r["field"]] = r
        ends = sorted(by)
        out = []
        for e in ends:
            tgt = date.fromisoformat(e) - timedelta(days=365)
            prior = {}
            for f in by[e]:
                for pe in ends:
                    if f in by[pe] and abs((date.fromisoformat(pe) - tgt).days) <= 12:
                        prior[f] = by[pe][f]["value"]
            first = min(by[e].values(), key=lambda r: (r["kind"] != "reported_3m", r["filed"]))
            out.append({"period_end": e, "filed": first["filed"], "accession": first["accession"], "accepted_at": first["accepted_at"],
                        "values": {f: r["value"] for f, r in by[e].items()}, "prior_year": prior,
                        "kinds": {f: r["kind"] for f, r in by[e].items()}, "states": {f: r["state"] for f, r in by[e].items()}})
        return out[-max_quarters:]

    def panel(self, ciks, fields=("revenue",)):
        """A Panel of the given fields over `ciks`: `Panel.asof(date)` is every company's rows as of that date (cached per date)."""
        return Panel(self, list(ciks), tuple(fields))

    def total_return(self, key, d0, d1):
        """Total return from `d0` to `d1` on the adjusted series, or None when either bar is missing."""
        a0, a1 = self.price_source.adj_close(key, d0), self.price_source.adj_close(key, d1)
        if a0 is None or a1 is None:
            return None
        return a1.price / a0.price - 1.0


class Panel:
    """A cache of as-of views of a field set across companies: `asof(date)` -> {cik: {int year: {field: value}}}, each company read through
    `PitData.snapshot(cik, date)` (one extraction per company per date, kept), so a panel view and a direct read agree by construction.  For
    corpus statistics (base rates, priors) that need every company as of a date."""

    def __init__(self, pit, ciks, fields):
        self.pit, self.ciks, self.fields = pit, [str(c).zfill(10) for c in ciks], tuple(fields)
        self._views = {}

    def asof(self, asof):
        a = to_date(asof).isoformat()
        if a not in self._views:
            view = {}
            for cik in self.ciks:
                snap = self.pit.snapshot(cik, a)
                if snap is not None and snap.years:
                    view[cik] = {y: {f: row.get(f) for f in self.fields} for y, row in snap.rows().items()}
                self.pit.evict(cik)
            self._views[a] = view
        return self._views[a]



class PitQuarterSource:
    """The Muse layer's `QuarterSource` interface over the shared layer: `quarters(cik, asof)` -> `PitData.quarterly_rows`.  Replaces
    `CompanyFactsQuarters` (valuation/muse/documents.py on the muse branch)."""

    def __init__(self, pit, fields=("revenue", "operating_income", "net_income"), max_quarters=6):
        self.pit, self.fields, self.max_quarters = pit, tuple(fields), max_quarters

    def quarters(self, cik, asof):
        return self.pit.quarterly_rows(cik, asof, self.fields, self.max_quarters)
