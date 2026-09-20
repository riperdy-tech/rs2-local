#!/usr/bin/env python3
"""tag_coverage_census.py — how much filed data is our extractor failing to read, corpus-wide?

NOT a D&A patch. The D&A gap turned out to be a two-tag omission (`Depreciation`,
`AmortizationOfIntangibleAssets`) plus a whole missing namespace (`ifrs-full`, which is why all
10 remaining names were foreign filers). Nothing about that bug is specific to D&A or to the 41
names that happened to have ZERO years — the same class silently nulls ANY field on ANY ticker,
including the ~48 names with PARTIAL gaps and the 10,333-name universe whose factor scores decide
what RS2 ever looks at.

So: census every field against every namespace, and for each null, report what IS filed.

Output per field:
  * ticker-years currently null
  * of those, how many have a candidate tag present but UNMAPPED (i.e. recoverable)
  * which unmapped tags would rescue the most, ranked

That ranked list is the input to the mapping decision — the model proposes names for it, a human
freezes it, and the extractor then reads FILED values. No inference, no override.

  python tools/audit_202608/tag_coverage_census.py [--limit N] [--book-only]
"""
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

SCR = Path(r"C:\Users\riper\Downloads\Stock Screener\Stock Screener")
HERE = Path(__file__).resolve().parents[2]
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = HERE / "audit" / "C_experiments" / "tag_coverage_census.json"

# What our extractor currently maps (build_fundamentals_history.py DURATION_TAGS/INSTANT_TAGS).
MAPPED = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "Revenue", "RevenueFromContractsWithCustomers"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortisationExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}

# Concept -> what a tag for this concept plausibly looks like, in ANY namespace. Deliberately
# generous: this is a CANDIDATE finder whose output a human ranks, not an auto-applier.
CANDIDATE = {
    "revenue": re.compile(r"(?<!Deferred)(Revenue|Sales)(?!.*(Deferred|Unearned|Remaining|Cost))", re.I),
    "net_income": re.compile(r"^(ProfitLoss|NetIncomeLoss|IncomeLossFrom.*)$"),
    "ocf": re.compile(r"CashFlowsFromUsedInOperating|NetCashProvidedByUsedInOperating", re.I),
    "capex": re.compile(r"(PaymentsToAcquire|PurchaseOf).*(PropertyPlantAndEquipment|ProductiveAssets|Intangible)", re.I),
    "da": re.compile(r"(?<!Accumulated)(Depreciation|Amorti[sz]ation)(?!.*(Accumulated|Unamortized|Debt|Discount|Premium|AfterYear|NextTwelve|RemainderOf|YearTwo|YearThree|YearFour|YearFive))", re.I),
    "operating_income": re.compile(r"^(OperatingIncomeLoss|ProfitLossFromOperatingActivities)$"),
    "pretax_income": re.compile(r"(BeforeIncomeTax|BeforeTax|ProfitLossBeforeTax)", re.I),
    "equity": re.compile(r"^(StockholdersEquity.*|Equity|EquityAttributableToOwnersOfParent)$"),
}


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    book_only = "--book-only" in sys.argv

    cik = json.loads((SCR / "public/data/cik_map.json").read_text(encoding="utf-8")).get("map", {})
    hist = json.loads((SCR / "public/data/fundamentals_history.json")
                      .read_text(encoding="utf-8-sig"))["tickers"]
    if book_only:
        st = json.loads((HERE / "cache/analysis_state.json").read_text(encoding="utf-8-sig"))
        universe = [t for t in sorted(st) if t in cik]
    else:
        universe = sorted(cik)
    if limit:
        universe = universe[:limit]

    z = zipfile.ZipFile(SCR / "companyfacts.zip")
    names = set(z.namelist())

    null_years = Counter()          # field -> ticker-years currently null
    total_years = Counter()
    recoverable = defaultdict(Counter)   # field -> unmapped tag -> tickers it would rescue
    ns_seen = Counter()
    ifrs_only = []
    scanned = 0

    for t in universe:
        h = hist.get(t)
        if not h:
            continue
        fn = f"CIK{cik[t]}.json"
        if fn not in names:
            continue
        try:
            facts = json.loads(z.read(fn).decode("utf-8")).get("facts", {})
        except Exception:
            continue
        scanned += 1
        for ns in facts:
            ns_seen[ns] += 1
        if "us-gaap" not in facts and "ifrs-full" in facts:
            ifrs_only.append(t)
        alltags = {ns: set(facts[ns].keys()) for ns in facts}

        for field, mapped in MAPPED.items():
            missing_years = [y for y, row in h.items()
                             if isinstance(row, dict) and row.get(field) is None]
            total_years[field] += len(h)
            null_years[field] += len(missing_years)
            if not missing_years:
                continue
            pat = CANDIDATE[field]
            for ns, tags in alltags.items():
                for tag in tags:
                    if tag in mapped:
                        continue
                    if pat.search(tag):
                        recoverable[field][f"{ns}:{tag}"] += 1
        if scanned % 250 == 0:
            print(f"  ...{scanned} scanned", flush=True)

    doc = {"scanned": scanned, "book_only": book_only,
           "namespaces": dict(ns_seen.most_common()),
           "ifrs_only_tickers": len(ifrs_only), "ifrs_only_sample": ifrs_only[:25],
           "fields": {}}
    print(f"\nscanned {scanned} tickers | namespaces: {dict(ns_seen.most_common(4))}")
    print(f"IFRS-only filers (no us-gaap at all): {len(ifrs_only)}\n")
    print(f"{'field':<18}{'null ticker-yrs':>16}{'of total':>11}   top unmapped candidate tags")
    for field in MAPPED:
        top = recoverable[field].most_common(4)
        doc["fields"][field] = {
            "null_ticker_years": null_years[field], "total_ticker_years": total_years[field],
            "null_pct": round(100 * null_years[field] / total_years[field], 1) if total_years[field] else None,
            "top_unmapped_candidates": [{"tag": k, "tickers": v} for k, v in
                                        recoverable[field].most_common(15)]}
        pct = doc["fields"][field]["null_pct"]
        print(f"{field:<18}{null_years[field]:>16,}{str(pct)+'%':>11}   "
              + ", ".join(f"{k.split(':')[-1][:34]}({v})" for k, v in top[:2]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
