"""WO_UV3 part A: a company whose filings show a real estate investment trust is routed as real estate whatever its SIC (value_family), on synthetic
companyfacts only. The evidence is two filed facts from different statements; one alone is nothing; a real-estate SIC, a shell and a holding company
are unchanged; the mortgage-REIT test that follows the SIC route applies to these too."""
from datetime import datetime, timezone

import pytest

import value_family as VF  # noqa: E402

T_ = datetime(2026, 12, 1, tzinfo=timezone.utc)
END = "2025-12-31"
REIT = {"RealEstateGrossAtCarryingValue": 900.0, "RealEstateAccumulatedDepreciation": 200.0, "RealEstateInvestmentPropertyNet": 700.0}


def _facts(ai):
    rows = lambda v: {"units": {"USD": [{"end": END, "val": v, "accn": "A1", "form": "10-K", "filed": "2026-02-01"}]}}   # noqa: E731
    return {"facts": {"us-gaap": {k: rows(v) for k, v in ai.items()}}}


def _subs(sic):
    return {"sic": sic, "filings": {"recent": {"form": ["10-K"], "accessionNumber": ["A1"], "filingDate": ["2026-02-01"],
                                               "acceptanceDateTime": ["2026-02-01T16:00:00.000Z"], "reportDate": [END]}}}


def _f(oi=((END, 10.0),)):
    vals = lambda xs: {"values": [{"end": e, "value": v} for e, v in xs]}   # noqa: E731
    return {"operating_income": vals(oi), "revenue": vals([(e, 100.0) for e, _ in oi])}


def fam(sic, extra=None, base=None):
    ai = {"Assets": 1000.0, "Liabilities": 500.0, **(base or {}), **(REIT if extra is None else extra)}
    return VF.family(_facts(ai), _subs(sic), _f(), T_)


def test_a_hotel_reit_with_a_hotel_sic_is_routed_as_real_estate_with_its_evidence_recorded():
    r = fam("7011")
    assert (r["classification"], r["family"], r["route"]) == ("family_not_built", "family_not_built", "operating_real_estate")
    assert r["reit_evidence"] == {"fiscal_year_end": END, "schedule_iii": {"RealEstateGrossAtCarryingValue": 900.0, "RealEstateAccumulatedDepreciation": 200.0},
                                  "balance_sheet": {"RealEstateInvestmentPropertyNet": 700.0}}
    assert "real estate investment trust" in r["reason"] and r["version"] == "f10.family.v2" == VF.FAMILY_VERSION
    assert r["route_evidence"] == "filed evidence of a real estate investment trust"


@pytest.mark.parametrize("missing", sorted(REIT))
def test_one_of_the_three_facts_alone_or_two_of_them_is_not_evidence(missing):
    only = {k: v for k, v in REIT.items() if k != missing}
    r = fam("7011", only)
    assert r["family"] == "operating" and "reit_evidence" not in r


def test_a_fact_that_is_zero_or_filed_for_another_year_is_not_evidence():
    assert fam("7011", dict(REIT, RealEstateInvestmentPropertyNet=0.0))["family"] == "operating"
    other = _facts({"Assets": 1000.0, "Liabilities": 500.0})
    other["facts"]["us-gaap"].update({k: {"units": {"USD": [{"end": "2024-12-31", "val": 1.0, "accn": "A1", "form": "10-K", "filed": "2026-02-01"}]}} for k in REIT})
    assert VF.family(other, _subs("7011"), _f(), T_)["family"] == "operating"


def test_a_real_estate_sic_is_unchanged_with_or_without_the_evidence_and_records_none():
    with_ev, without = fam("6798"), fam("6798", {})
    assert with_ev["family"] == without["family"] == "family_not_built" and "reit_evidence" not in with_ev
    assert with_ev["route"] == without["route"] == "operating_real_estate" and with_ev["route_evidence"] == "real-estate SIC"


def test_a_shell_and_a_holding_company_are_not_rerouted():
    for sic, kind in (("6770", "blank_check_shell"), ("6719", "conglomerate_or_holding_company")):
        r = fam(sic)
        assert r["family"] == "family_not_built" and kind in r["reason"] and "reit_evidence" not in r


def test_the_mortgage_reit_test_applies_to_a_reit_by_evidence():
    r = fam("7011", base={"MortgageLoansOnRealEstate": 600.0})                       # a lending book of 60% of assets
    assert r["route"] == "financial" and r["family"] == "family_not_built" and "mortgage REIT" in r["route_evidence"]
    r = fam("7011", base={"SecuritiesSoldUnderAgreementsToRepurchase": 300.0})       # repurchase funding of 30% of assets
    assert r["route"] == "financial" and "repurchase" in r["route_evidence"]


def test_a_financial_company_without_the_evidence_is_unchanged():
    r = VF.family(_facts({"Assets": 100.0, "Liabilities": 90.0, "Deposits": 60.0}), _subs("6022"), _f(), T_)
    assert r["family"] == "financial" and "reit_evidence" not in r


def test_the_evidence_of_a_filing_accepted_after_T_is_not_read():
    late = _subs("7011")
    late["filings"]["recent"]["acceptanceDateTime"], late["filings"]["recent"]["filingDate"] = ["2026-12-05T16:00:00.000Z"], ["2026-12-05"]
    cf = _facts({"Assets": 1000.0, "Liabilities": 500.0, **REIT})
    for r in cf["facts"]["us-gaap"].values():
        r["units"]["USD"][0]["filed"] = "2026-12-05"
    out = VF.family(cf, late, _f(), T_)
    assert out["base_end"] is None and "reit_evidence" not in out
