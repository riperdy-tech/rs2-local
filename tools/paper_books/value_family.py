"""value_family.py - the valuation family of one company at a formation's T (F_SPEC_valuation_menu F10), for `python -m qwen_c.value.run
--family`. It is the E3 panel's census rule, ported: the engine classification (SIC families, the two balance-sheet tests, the pre-profit
test) and then the B7 desk route that confirms or overturns a financial family, combined as the E3 panel combined them.

    family(cf, subs, f, T) -> {"family", "classification", "route", "reason", "route_evidence", "sic", "base_end", "tests", "version"}

Inputs are the ones the valuation itself reads at T: the SEC companyfacts and submissions (qwen_c.value.facts.fetch) and the filed
facts built from them (facts.annual_facts), so every balance-sheet value is from an annual form effective by T (facts._series). The SIC
is the submissions' current assignment (SEC publishes no dated history; the census used the current code too).

THE CLASSIFICATION (rs2 engine v2.2 valuation/classification.py, rules 1-4):
1. SIC: real estate 6500-6599 and 6798, shells 6770, holding companies 6719/9990/9995, utilities and pipelines 4900-4949 are
   family_not_built (final); 6282 and 6411 are operating (fee businesses); 6000-6411 financial; the commodity ranges below commodity;
   everything else operating. No SIC: classified by the balance sheet, operating by default.
2. Balance sheet, on the latest fiscal year-end with total assets filed: insurance reserves (the sum of the three disjoint tags) >= 10%
   of assets, or loans (the first of LOAN_TAGS filed) >= 50% of assets AND debt plus deposits >= 50% of liabilities -> financial (wins
   over the SIC, except family_not_built). A financial SIC the tests do not confirm stays financial here (the route decides).
3. Pre-profit: an operating or commodity company with operating income <= 0 in at least 3 of its last 4 fiscal years -> family_not_built.
THE ROUTE (census_1a_addendum.route, B7): financial when insurance reserves >= 10% of assets, the widened lending book >= 50% of assets,
or deposits >= 50% of liabilities; a real-estate SIC is financial only as a mortgage REIT (lending >= 50% or repurchase funding >= 20%),
else operating_real_estate; a broker-dealer SIC 6211 is financial; a credit SIC 6020-6199 is financial when borrowings are >= 50% of
liabilities; an insurer SIC 6300-6399 when investments are >= 50% of assets; otherwise operating.
COMBINED (e3_panel.census_rows): classification financial or operating with route financial -> financial; classification financial with
route operating -> operating; otherwise the classification stands (commodity, family_not_built, None).

What the port changes against the census (asof 2026-10-18, harness store): the facts are point in time at T rather than as of one census
date; debt is qwen_c's inputs.debt_total (the valuation's own debt) rather than the engine's total_debt with its raw-tag fallbacks; the
base year is the latest year-end with Assets filed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from qwen_c import packet  # noqa: E402
from qwen_c.value import facts, inputs  # noqa: E402

FAMILY_VERSION = "f10.family.v1"

PRE_PROFIT_WINDOW, PRE_PROFIT_MIN_LOSS_YEARS = 4, 3
INSURANCE_RESERVE_SHARE, LENDING_BOOK_SHARE, FUNDING_SHARE, DEPOSITS_SHARE = 0.10, 0.50, 0.50, 0.50
REPO_SHARE, INVEST_SHARE = 0.20, 0.50

INSURANCE_TAGS = ("LiabilityForFuturePolicyBenefits", "LiabilityForUnpaidClaimsAndClaimsAdjustmentExpense", "UnearnedPremiums")
LOAN_TAGS = ("LoansAndLeasesReceivableNetReportedAmount", "LoansAndLeasesReceivableNetOfDeferredIncome",
             "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss", "LoansReceivableNet")
ROUTE_LOAN_TAGS = LOAN_TAGS + (
    "NotesAndLoansReceivableNetCurrent", "NotesAndLoansReceivableNetNoncurrent", "LoansReceivableFairValueDisclosure",
    "FinancingReceivableAfterAllowanceForCreditLoss", "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss",
    "MortgageLoansOnRealEstate", "MortgageLoansOnRealEstateCommercialAndConsumerNet", "LoansHeldForSaleFairValueDisclosure",
    "FinancingReceivablePurchasedWithCreditDeteriorationAmortizedCostBasis", "LoansAndLeasesReceivableGrossCarryingAmount",
    "ConsumerLoansNet", "FinanceReceivablesNet", "LoansAndAdvancesToCustomers", "NotesReceivableNet")
NOTES_PAIR = ("NotesAndLoansReceivableNetCurrent", "NotesAndLoansReceivableNetNoncurrent")

_NOT_BUILT = [((6500, 6599), "reit_or_real_estate"), ((6798, 6798), "reit_or_real_estate"), ((6770, 6770), "blank_check_shell"),
              ((6719, 6719), "conglomerate_or_holding_company"), ((9990, 9990), "conglomerate_or_holding_company"),
              ((9995, 9995), "conglomerate_or_holding_company"), ((4900, 4949), "regulated_utility_or_pipeline")]
_FINANCIAL_EXCEPTIONS = {6282: "investment advice: a fee business, valued as operating",
                         6411: "insurance agents and brokers: a fee business, valued as operating"}
_FINANCIAL = [(6000, 6411)]
_COMMODITY = [(1000, 1299), (1400, 1499), (1311, 1311), (1321, 1321), (1381, 1382), (2911, 2911), (2611, 2611), (2621, 2621),
              (2810, 2829), (2860, 2879), (3312, 3317), (3330, 3339), (4400, 4499)]


def _in(code, ranges):
    return any(a <= code <= b for a, b in ranges)


def sic_family(sic):
    """(family, note) from a SIC code string; (None, "no SIC code") when it is missing."""
    if sic is None or not str(sic).strip().isdigit():
        return None, "no SIC code"
    code = int(str(sic).strip())
    for (a, b), kind in _NOT_BUILT:
        if a <= code <= b:
            return "family_not_built", kind
    if code in _FINANCIAL_EXCEPTIONS:
        return "operating", _FINANCIAL_EXCEPTIONS[code]
    if _in(code, _FINANCIAL):
        return "financial", "banks, credit, brokers, insurers"
    if _in(code, _COMMODITY):
        return "commodity", "mining, oil and gas, refining, commodity chemicals, steel, shipping, pulp and paper"
    return "operating", "default"


def instants(cf, subs, T, tag):
    """{end: value} of one raw tag's annual-form instants effective by T (facts._series: the latest eligible filing per end), from the
    first taxonomy that files the tag, any unit (the census's convention: a company files one reporting currency)."""
    eligible = facts.eligible_accessions(subs, T)
    known = {r["accession"] for r in packet._filing_rows(subs)}
    for tax in ("us-gaap", "ifrs-full", "srt"):
        units = (((cf.get("facts") or {}).get(tax) or {}).get(tag) or {}).get("units") or {}
        best = {}
        for rows in units.values():
            for e, fct in facts._series(rows, "instant", eligible, known, T).items():
                key = (fct.get("filed") or "", fct.get("accn") or "")
                if e not in best or key > best[e][0]:
                    best[e] = (key, float(fct["val"]))
        if best:
            return {e: v for e, (_, v) in best.items()}
    return {}


def _share(num, den):
    return num / den if (num is not None and den) else None


def family(cf, subs, f, T):
    """The family record of one company at T (aware datetime). cf, subs: parsed companyfacts and submissions; f: facts.annual_facts."""
    sic = subs.get("sic") or None
    cache = {}

    def at(tag, end):
        if tag not in cache:
            cache[tag] = instants(cf, subs, T, tag)
        return cache[tag].get(end)

    at("Assets", None)
    assets_by_end = cache["Assets"]
    out = {"version": FAMILY_VERSION, "sic": sic, "family": None, "classification": None, "route": None, "reason": "",
           "route_evidence": None, "base_end": None, "tests": {}}
    flows = sorted({v["end"] for c in ("revenue", "net_income", "operating_income") for v in (f.get(c) or {}).get("values", [])})
    if not flows and not assets_by_end:
        out["reason"] = "unclassifiable: no annual report filed before T"
        return out
    end = max(assets_by_end) if assets_by_end else None
    out["base_end"] = end
    ta = assets_by_end.get(end) if end else None
    liab = at("Liabilities", end) if end else None
    ins_parts = [at(tg, end) for tg in INSURANCE_TAGS] if end else []
    ins = sum(v for v in ins_parts if v is not None) if any(v is not None for v in ins_parts) else None
    dep = at("Deposits", end) if end else None
    debt = inputs.debt_total(f, end)[0] if end else None
    if debt is None and end:                                              # engine total_debt: nothing filed and no interest charge is 0
        ie = {v["end"]: v["value"] for v in (f.get("interest_expense") or {}).get("values", [])}.get(end)
        debt = None if (ie is not None and ie > 0) else 0.0
    loans = next((v for v in (at(tg, end) for tg in LOAN_TAGS) if v is not None), None) if end else None
    t = out["tests"]
    t["insurance_reserve_share"] = _share(ins, ta) if (ta and ta > 0) else None
    t["deposits_share"] = _share(dep, liab) if (liab and liab > 0) else None
    lending_test = False
    if loans is not None and ta and ta > 0 and liab and liab > 0 and (debt is not None or dep is not None):
        funding = (debt or 0.0) + (dep or 0.0)
        t["lending_book_share"], t["funding_share"] = loans / ta, funding / liab
        lending_test = loans / ta >= LENDING_BOOK_SHARE and funding / liab >= FUNDING_SHARE
    ins_test = t["insurance_reserve_share"] is not None and t["insurance_reserve_share"] >= INSURANCE_RESERVE_SHARE

    fam_sic, note = sic_family(sic)                                       # the classification
    if fam_sic == "family_not_built":
        cls, why = "family_not_built", f"SIC {sic}: {note}; family not built"
    elif ins_test or lending_test:
        cls, why = "financial", "balance sheet: " + ("insurance reserves >= 10% of assets" if ins_test else "a lending book funded by borrowings")
    elif fam_sic == "financial":
        cls, why = "financial", f"SIC {sic}: {note}"
    else:
        cls = fam_sic or "operating"
        why = f"SIC {sic}: {note}" if fam_sic else "no SIC code; no balance-sheet financial profile"
        oi = {v["end"]: v["value"] for v in (f.get("operating_income") or {}).get("values", [])}
        window = flows[-PRE_PROFIT_WINDOW:]
        losses = sum(1 for e in window if e in oi and oi[e] <= 0)
        t["pre_profit_loss_years"] = losses
        if losses >= PRE_PROFIT_MIN_LOSS_YEARS:
            cls, why = "family_not_built", f"pre_profit: operating income <= 0 in {losses} of the last {len(window)} fiscal years"
    out["classification"] = cls

    lend = None                                                           # the B7 route
    if end and ta:
        vals = {tg: at(tg, end) for tg in ROUTE_LOAN_TAGS}
        vals = {k: v for k, v in vals.items() if v is not None}
        if vals:
            pair = sum(vals.get(k, 0.0) for k in NOTES_PAIR)
            lend = max([pair] + [v for k, v in vals.items() if k not in NOTES_PAIR]) / ta
    t["lending_share_widened"] = lend
    funding = _share(debt, liab) if (debt and liab) else None
    repo = _share(at("SecuritiesSoldUnderAgreementsToRepurchase", end), ta) if (end and ta) else None
    invest = _share(at("Investments", end), ta) if (end and ta) else None
    route, rwhy = _route(sic, t["insurance_reserve_share"], t["deposits_share"], lend, funding, repo, invest, cls)
    out["route"], out["route_evidence"] = route, rwhy

    if cls in ("financial", "operating") and route == "financial":
        out["family"] = "financial"
    elif cls == "financial" and route == "operating":
        out["family"] = "operating"
    else:
        out["family"] = cls
    out["reason"] = why if out["family"] == cls else f"{why}; route {route}: {rwhy}"
    return out


def _route(sic, ins, dep, lend, funding, repo, invest, cls):
    """census_1a_addendum.route: (route, evidence)."""
    code = int(sic) if sic and str(sic).strip().isdigit() else None
    ins, dep, lb = ins or 0.0, dep or 0.0, lend or 0.0
    if code is not None and (6500 <= code <= 6599 or code == 6798):
        if lb >= LENDING_BOOK_SHARE:
            return "financial", "mortgage REIT: lending book >= 50% of assets"
        if (repo or 0) >= REPO_SHARE:
            return "financial", f"mortgage REIT: repurchase-agreement funding {repo:.0%} of assets"
        return "operating_real_estate", "real-estate SIC"
    if ins >= INSURANCE_RESERVE_SHARE or lb >= LENDING_BOOK_SHARE or dep >= DEPOSITS_SHARE:
        return "financial", ("insurance reserves >= 10% of assets" if ins >= INSURANCE_RESERVE_SHARE else
                             "lending book >= 50% of assets" if lb >= LENDING_BOOK_SHARE else "deposits >= 50% of liabilities")
    if code == 6211:
        return "financial", "broker-dealer SIC 6211, no test contradicts"
    if code is not None and 6020 <= code <= 6199:
        if (funding or 0) >= FUNDING_SHARE:
            return "financial", f"credit SIC {code}, borrowings {funding:.0%} of liabilities"
        return "operating", f"financial_sic_not_confirmed: SIC {code}, borrowings {funding or 0:.0%} of liabilities"
    if code is not None and 6300 <= code <= 6399 and (invest or 0) >= INVEST_SHARE:
        return "financial", f"insurer SIC {code}, investments {invest:.0%} of assets (reserves not tagged)"
    if code is not None and 6000 <= code <= 6411 and cls == "financial":
        return "operating", f"financial_sic_not_confirmed: SIC {code} with no confirming balance sheet"
    return "operating", f"SIC {code}: default" if code else "no SIC: default"
