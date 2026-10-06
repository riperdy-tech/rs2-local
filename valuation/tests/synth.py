"""Synthetic companyfacts for the tests: no network, no archive."""
import gzip
import json
from datetime import date, timedelta
from pathlib import Path

from valuation import pit_data as pd_

INSTANT_TAGS = {"Assets", "AssetsCurrent", "Liabilities", "LiabilitiesCurrent", "StockholdersEquity", "Equity", "CashAndCashEquivalentsAtCarryingValue",
                "LongTermDebtNoncurrent", "LongTermDebtCurrent", "ShortTermBorrowings", "PreferredStockValue", "Goodwill", "PropertyPlantAndEquipmentNet",
                "LiabilityForFuturePolicyBenefits", "StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"}


def _fact(tag, fye, filed, val, accn, form, unit="USD", taxo="us-gaap"):
    end = date.fromisoformat(fye)
    start = None if tag in INSTANT_TAGS else (end - timedelta(days=364)).isoformat()
    return [taxo, tag, unit, start, fye, val, accn, filed, form]


def annual_report(fye, filed, values, comparatives=None, form="10-K", accn=None, unit="USD"):
    """Facts of one annual report: `values` {tag: val} for the report's own year, `comparatives` {fye: {tag: val}} for earlier years."""
    accn = accn or f"acc-{form}-{filed}"
    out = [_fact(t, fye, filed, v, accn, form, unit) for t, v in values.items()]
    for f2, vals in (comparatives or {}).items():
        out += [_fact(t, f2, filed, v, accn, form, unit) for t, v in vals.items()]
    return out


def cover(end, filed, value, form="10-Q", accn=None):
    return ["dei", pd_.COVER_TAG, "shares", None, end, value, accn or f"cov-{filed}-{value}", filed, form]


def write_company(store_dir, cik, facts, name="Synthetic Co"):
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    nested = {}
    for taxo, tag, unit, start, end, val, accn, filed, form in facts:
        nested.setdefault(taxo, {}).setdefault(tag, {}).setdefault(unit, []).append([start, end, val, accn, filed, form])
    doc = {"cik": str(cik).zfill(10), "name": name, "facts": nested, "dropped_no_filed": 0, "layer_version": pd_.PIT_LAYER_VERSION}
    with gzip.open(store_dir / f"{str(cik).zfill(10)}.json.gz", "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    return str(cik).zfill(10)


def simple_company(store_dir, cik, years, base_rev=100.0, growth=0.1, margin=0.2, first_year=2015, fy_end="-12-31", lag_days=60, name="Synthetic Co",
                   extra=None):
    """A company with one annual report per year in [first_year, last year]: revenue base_rev*(1+growth)^i, operating income margin*revenue, net
    income 0.7*operating income, plus a balance sheet.  Filed lag_days after the year end."""
    facts = []
    for i, y in enumerate(range(first_year, first_year + years)):
        fye = f"{y}{fy_end}"
        filed = (date.fromisoformat(fye) + timedelta(days=lag_days)).isoformat()
        rev = base_rev * (1 + growth) ** i
        vals = {"Revenues": rev, "GrossProfit": rev * 0.5, "OperatingIncomeLoss": rev * margin, "NetIncomeLoss": rev * margin * 0.7,
                "NetCashProvidedByUsedInOperatingActivities": rev * margin * 0.9, "PaymentsToAcquirePropertyPlantAndEquipment": rev * 0.05,
                "DepreciationDepletionAndAmortization": rev * 0.04, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": rev * margin,
                "IncomeTaxExpenseBenefit": rev * margin * 0.3, "Assets": rev * 1.5, "StockholdersEquity": rev * 0.8,
                "CashAndCashEquivalentsAtCarryingValue": rev * 0.2, "LongTermDebtNoncurrent": rev * 0.3, "LongTermDebtCurrent": rev * 0.05,
                "AssetsCurrent": rev * 0.6, "LiabilitiesCurrent": rev * 0.25}
        vals.update(extra or {})
        facts += annual_report(fye, filed, vals, accn=f"{cik}-{y}")
    return write_company(store_dir, cik, facts, name)


def append_facts(store_dir, cik, facts):
    """Add flat facts [taxo, tag, unit, start, end, val, accn, filed, form] to an existing company file."""
    p = Path(store_dir) / f"{str(cik).zfill(10)}.json.gz"
    with gzip.open(p, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    for taxo, tag, unit, start, end, val, accn, filed, form in facts:
        doc["facts"].setdefault(taxo, {}).setdefault(tag, {}).setdefault(unit, []).append([start, end, val, accn, filed, form])
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(doc, f)


def drop_filed_on_or_after(store_dir, cik, date_iso):
    """Remove every fact filed on or after `date_iso` (as if the archive had been cut that day)."""
    p = Path(store_dir) / f"{str(cik).zfill(10)}.json.gz"
    with gzip.open(p, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    for tags in doc["facts"].values():
        for units in tags.values():
            for u in list(units):
                units[u] = [r for r in units[u] if r[4] < date_iso]
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(doc, f)
