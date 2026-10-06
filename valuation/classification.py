"""classification.py - SPEC 2: the economic family of a company, by rules stated in words, with every assignment's reason recorded.

classification(ticker, asof, data) -> {"family", "reason", "conflicts", "sic", "tests", "notes"}
  family: "financial" | "commodity" | "operating" | "family_not_built" | None (unclassifiable: no annual report filed before asof)
  `data` is a common.CompanyPIT: the SIC from SEC submissions, the annual fields and concepts filed strictly before asof.

THE RULES
1. The SIC code (SEC submissions) gives a first family:
   * REIT / real estate (6500-6599, 6798) and conglomerate / holding shells (6719, 9990, 9995) and blank-check shells (6770):
     "family_not_built" (SPEC 2: out of scope in this build; classified and annotated, never valued). A balance-sheet test never
     overrides this: a mortgage REIT stays "family_not_built".
   * financial: banks, savings institutions, credit and finance companies, mortgage bankers, brokers and dealers, insurers
     (6000-6411 less the exceptions below). Exceptions that are fee businesses valued as operating companies: 6282 investment advice
     (asset managers) and 6411 insurance agents and brokers.
   * commodity / asset-heavy: metal and coal mining and non-metallic minerals (1000-1299, 1400-1499), crude petroleum and natural gas (1311,
     1321), oil and gas drilling and exploration services (1381, 1382), petroleum refining (2911), pulp and paper mills (2611, 2621),
     industrial inorganic, plastics and resins, industrial organic and agricultural chemicals (2810-2829, 2860-2879), steel works and
     primary non-ferrous smelting (3312-3317, 3330-3339), deep sea and other water transportation (4400-4499).
   * operating: everything else (the default; oilfield services 1389 is operating by this rule).
2. Two balance-sheet tests on the base-year filing, in words:
   * insurance_reserves is material against total assets (>= INSURANCE_RESERVE_SHARE) -> financial;
   * a lending book funded by borrowings: loans and financing receivables are a majority of total assets (>= LENDING_BOOK_SHARE) AND
     borrowings plus deposits are a majority of total liabilities (>= FUNDING_SHARE) -> financial.
   A test whose inputs are not filed is listed under tests.not_evaluated (it never passes by default).
3. A conflict (the SIC family differs from the balance-sheet family) is recorded in `conflicts`; the balance sheet wins, except that
   "family_not_built" by SIC is final. A financial SIC that the balance sheet does not confirm stays financial and is annotated.

THRESHOLDS are classification conventions stated here, not tuned parameters; the report gives the corpus measurement behind the
insurance threshold. SEC publishes only the CURRENT SIC, so the SIC is not point in time: `sic.point_in_time` says so and a company
that changed industry is classified by its current code (a stamp, listed in the report's gaps).
"""
from __future__ import annotations

from typing import Optional

from .common import CompanyPIT, num, total_debt, parse_date
from . import common

INSURANCE_RESERVE_SHARE = 0.10
LENDING_BOOK_SHARE = 0.50
FUNDING_SHARE = 0.50

LOAN_TAGS = ("LoansAndLeasesReceivableNetReportedAmount", "LoansAndLeasesReceivableNetOfDeferredIncome",
             "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss", "LoansReceivableNet")
DEPOSIT_TAGS = ("Deposits",)

_NOT_BUILT = [((6500, 6599), "reit_or_real_estate"), ((6798, 6798), "reit_or_real_estate"), ((6770, 6770), "blank_check_shell"),
              ((6719, 6719), "conglomerate_or_holding_company"), ((9990, 9990), "conglomerate_or_holding_company"),
              ((9995, 9995), "conglomerate_or_holding_company")]
_FINANCIAL_EXCEPTIONS = {6282: "investment advice: a fee business, valued as operating", 6411: "insurance agents and brokers: a fee business, valued as operating"}
_FINANCIAL = [(6000, 6411)]
_COMMODITY = [(1000, 1299), (1400, 1499), (1311, 1311), (1321, 1321), (1381, 1382), (2911, 2911), (2611, 2611), (2621, 2621),
              (2810, 2829), (2860, 2879), (3312, 3317), (3330, 3339), (4400, 4499)]


def _in(code: int, ranges) -> bool:
    return any(a <= code <= b for a, b in ranges)


def sic_family(sic: Optional[str]):
    """(family, kind_or_note) from a SIC code string; ("operating", "...") for the default and when the code is missing."""
    if sic is None or not str(sic).strip().isdigit():
        return None, "no SIC code"
    code = int(str(sic).strip())
    for rng, kind in _NOT_BUILT:
        if rng[0] <= code <= rng[1]:
            return "family_not_built", kind
    if code in _FINANCIAL_EXCEPTIONS:
        return "operating", _FINANCIAL_EXCEPTIONS[code]
    if _in(code, _FINANCIAL):
        return "financial", "banks, credit, brokers, insurers"
    if _in(code, _COMMODITY):
        return "commodity", "mining, oil and gas, refining, commodity chemicals, steel, shipping, pulp and paper"
    return "operating", "default"


def _latest(series: dict):
    return series[max(series)] if series else None


def balance_sheet_tests(pit: CompanyPIT) -> dict:
    per = pit.periods()
    out = {"base_period": None, "insurance_reserve_share": None, "lending_book_share": None, "funding_share": None,
           "insurance_test": None, "lending_test": None, "evaluated": [], "not_evaluated": []}
    if not per:
        out["not_evaluated"] = ["insurance_reserves", "lending_book"]
        return out
    bp = per[-1]
    out["base_period"] = bp
    row = pit.row(bp)
    ta, ir = num(row["total_assets"]), num(row["insurance_reserves"])
    if ta is not None and ta > 0 and ir is not None:
        out["insurance_reserve_share"] = ir / ta
        out["insurance_test"] = ir / ta >= INSURANCE_RESERVE_SHARE
        out["evaluated"].append("insurance_reserves")
    else:
        out["not_evaluated"].append("insurance_reserves (insurance_reserves or total_assets not filed)")
    loans = None
    for tag in LOAN_TAGS:
        f = pit.concepts.get(tag, {}).get(bp)
        if f is not None:
            loans = f.value
            break
    liab = num(row["total_liabilities"])
    dep = pit.concepts.get("Deposits", {}).get(bp)
    debt = total_debt(row)
    if loans is not None and ta is not None and ta > 0 and liab is not None and liab > 0 and (debt is not None or dep is not None):
        funding = (0.0 if debt is None else debt) + (0.0 if dep is None else dep.value)
        out["lending_book_share"] = loans / ta
        out["funding_share"] = funding / liab
        out["lending_test"] = (loans / ta >= LENDING_BOOK_SHARE) and (funding / liab >= FUNDING_SHARE)
        out["evaluated"].append("lending_book")
    else:
        out["not_evaluated"].append("lending_book (a loans/financing-receivables concept, total assets, total liabilities or funding "
                                    "is not filed for the base period)")
    return out


def classification(ticker: str, asof, data: CompanyPIT) -> dict:
    asof_d = parse_date(asof)
    if data.asof != asof_d:
        raise ValueError(f"data is as of {data.asof}, asked for {asof_d}")
    data.check()
    sic = data.sic.code if data.sic else None
    out = {"ticker": ticker, "asof": asof_d.isoformat(), "family": None, "reason": "", "conflicts": [], "notes": [],
           "sic": {"code": sic, "description": data.sic.description if data.sic else "", "source": data.sic.source if data.sic else "",
                   "point_in_time": bool(data.sic and data.sic.point_in_time)}}
    if data.sic is not None and not data.sic.point_in_time:
        out["notes"].append("SIC is the current SEC assignment, not a dated history")
    if not data.periods():
        out["reason"] = "unclassifiable: no annual report filed before the valuation date"
        out["tests"] = balance_sheet_tests(data)
        return out
    fam_sic, sic_note = sic_family(sic)
    tests = balance_sheet_tests(data)
    out["tests"] = tests
    if fam_sic is None:
        out["notes"].append("no SIC code on file: classified by the balance sheet only, operating by default")
    if fam_sic == "family_not_built":
        out["family"] = "family_not_built"
        out["reason"] = f"SIC {sic}: {sic_note}; family not built (SPEC 2)"
        if tests["insurance_test"] or tests["lending_test"]:
            out["conflicts"].append(f"SIC {sic} ({sic_note}) but the balance sheet shows a financial profile "
                                    f"(insurance reserves {tests['insurance_reserve_share']}, lending book {tests['lending_book_share']}); "
                                    "family not built is final")
        return out
    bs_fin = bool(tests["insurance_test"]) or bool(tests["lending_test"])
    if bs_fin:
        why = []
        if tests["insurance_test"]:
            why.append(f"insurance reserves are {tests['insurance_reserve_share']:.1%} of total assets (>= {INSURANCE_RESERVE_SHARE:.0%})")
        if tests["lending_test"]:
            why.append(f"loans and financing receivables are {tests['lending_book_share']:.1%} of assets, funded {tests['funding_share']:.1%} "
                       "by borrowings and deposits")
        out["family"] = "financial"
        out["reason"] = "balance sheet: " + "; ".join(why)
        if fam_sic not in (None, "financial"):
            out["conflicts"].append(f"SIC {sic} says {fam_sic} ({sic_note}); the balance sheet says financial and wins")
        return out
    if fam_sic == "financial":
        out["family"] = "financial"
        out["reason"] = f"SIC {sic}: {sic_note}"
        if tests["not_evaluated"] and len(tests["not_evaluated"]) == 2:
            out["notes"].append("financial by SIC; neither balance-sheet test could be evaluated")
        else:
            out["conflicts"].append(f"SIC {sic} says financial but the balance-sheet tests do not confirm it "
                                    f"(insurance reserves {tests['insurance_reserve_share']}, lending book {tests['lending_book_share']}); "
                                    "kept financial: the tests only confirm, they cannot establish operating")
        return out
    out["family"] = fam_sic if fam_sic is not None else "operating"
    out["reason"] = f"SIC {sic}: {sic_note}" if fam_sic is not None else "no SIC code; no balance-sheet financial profile"
    return out
