"""WO_Q4 (SPEC_m3q §2): qwen_c/value/facts.py, point-in-time annual figures from companyfacts, on hand-built SEC documents."""
from datetime import datetime, timezone

from qwen_c.value import facts

T = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)


def subs():
    rows = [("0001-26-000010", "10-K", "2026-02-20", "2026-02-20T16:05:00.000Z"),     # effective 2026-02-23: eligible
            ("0001-26-000099", "10-K/A", "2026-03-10", "2026-03-10T16:05:00.000Z"),   # after T: not eligible
            ("0001-25-000010", "10-K", "2025-02-21", "2025-02-21T16:05:00.000Z"),
            ("0001-26-000050", "10-K/A", "2026-02-27", "2026-02-27T22:40:00.000Z")]   # after 17:30 ET Friday: effective Tue 03-03, after T
    cols = list(zip(*rows))
    return {"filings": {"recent": {"accessionNumber": list(cols[0]), "form": list(cols[1]), "filingDate": list(cols[2]),
                                   "acceptanceDateTime": list(cols[3])}}}


def fy(end, val, accn, form="10-K", filed="2026-02-20", fp="FY"):
    """A full-year fact ending `end` (a 365-day duration)."""
    return {"start": f"{int(end[:4]) - 1}{end[4:]}", "end": end, "val": val, "accn": accn, "form": form, "filed": filed, "fp": fp}


def cf(revenue_rows, extra=None):
    f = {"us-gaap": {"Revenues": {"units": {"USD": revenue_rows}}}}
    if extra:
        f["us-gaap"].update(extra)
    return {"facts": f}


def test_latest_eligible_filing_wins_and_later_restatement_is_ignored():
    rows = [fy("2025-12-31", 100.0, "0001-26-000010"), fy("2025-12-31", 90.0, "0001-26-000099", form="10-K/A", filed="2026-03-10"),
            fy("2024-12-31", 80.0, "0001-25-000010", filed="2025-02-21"), fy("2024-12-31", 82.0, "0001-26-000010")]
    out = facts.annual_facts(cf(rows), subs(), T)
    vals = {v["end"]: v["value"] for v in out["revenue"]["values"]}
    assert vals == {"2024-12-31": 82.0, "2025-12-31": 100.0}


def test_after_hours_amendment_effective_after_T_is_excluded():
    rows = [fy("2025-12-31", 100.0, "0001-26-000010"), fy("2025-12-31", 101.0, "0001-26-000050", form="10-K/A", filed="2026-02-27")]
    assert facts.annual_facts(cf(rows), subs(), T)["revenue"]["values"][-1]["value"] == 100.0


def test_quarterly_and_short_duration_facts_are_not_annual():
    rows = [fy("2025-12-31", 100.0, "0001-26-000010"),
            {"start": "2025-10-01", "end": "2025-12-31", "val": 30.0, "accn": "0001-26-000010", "form": "10-K", "filed": "2026-02-20", "fp": "FY"},
            {"start": "2025-01-01", "end": "2025-09-30", "val": 70.0, "accn": "0001-26-000010", "form": "10-Q", "filed": "2025-11-01", "fp": "Q3"}]
    vals = facts.annual_facts(cf(rows), subs(), T)["revenue"]["values"]
    assert [(v["end"], v["value"]) for v in vals] == [("2025-12-31", 100.0)]


def test_old_accession_outside_recent_counts_by_filed_date_and_is_stamped():
    rows = [fy("2019-12-31", 50.0, "0001-20-000001", filed="2020-02-25"), fy("2026-01-31", 9.0, "0001-26-777777", filed="2026-03-01")]
    vals = facts.annual_facts(cf(rows), subs(), T)["revenue"]["values"]
    assert [(v["end"], v["stamp"]) for v in vals] == [("2019-12-31", "acceptance_by_filed_date")]


def test_zero_is_a_value_and_missing_concepts_are_named():
    rows = [fy("2025-12-31", 0.0, "0001-26-000010")]
    out = facts.annual_facts(cf(rows), subs(), T)
    assert out["revenue"]["values"][0]["value"] == 0.0
    assert out["_absent"]["capex"].startswith("no eligible annual fact")


def test_a_tag_switch_keeps_one_series_by_priority_per_year():
    old_tag = {"SalesRevenueNet": {"units": {"USD": [fy("2024-12-31", 80.0, "0001-25-000010", filed="2025-02-21"),
                                                    fy("2025-12-31", 99.0, "0001-26-000010")]}}}
    new_tag = {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [fy("2025-12-31", 100.0, "0001-26-000010")]}}}
    out = facts.annual_facts({"facts": {"us-gaap": {**old_tag, **new_tag}}}, subs(), T)
    assert [(v["end"], v["value"], v["tag"]) for v in out["revenue"]["values"]] == [
        ("2024-12-31", 80.0, "SalesRevenueNet"), ("2025-12-31", 100.0, "RevenueFromContractWithCustomerExcludingAssessedTax")]


def test_profitloss_net_income_is_less_nci_and_a_stale_concept_is_named():
    g = {"Revenues": {"units": {"USD": [fy("2024-12-31", 80.0, "0001-25-000010", filed="2025-02-21"), fy("2025-12-31", 100.0, "0001-26-000010")]}},
         "NetIncomeLoss": {"units": {"USD": [fy("2024-12-31", 8.0, "0001-25-000010", filed="2025-02-21")]}},
         "ProfitLoss": {"units": {"USD": [fy("2024-12-31", 8.5, "0001-25-000010", filed="2025-02-21"), fy("2025-12-31", 11.0, "0001-26-000010")]}},
         "NetIncomeLossAttributableToNoncontrollingInterest": {"units": {"USD": [fy("2025-12-31", 1.0, "0001-26-000010")]}},
         "EarningsPerShareDiluted": {"units": {"USD/shares": [fy("2025-12-31", 2.0, "0001-26-000010")]}},
         "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fy("2024-12-31", 5.0, "0001-25-000010", filed="2025-02-21"),
                                                                                  fy("2025-12-31", 5.0, "0001-26-000010")]}},
         "AssetsCurrent": {"units": {"USD": [{"end": "2024-12-31", "val": 5.0, "accn": "0001-25-000010", "form": "10-K", "filed": "2025-02-21"}]}}}
    out = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)
    assert [(v["value"], v["tag"], v["stamp"]) for v in out["net_income"]["values"]] == [
        (8.0, "NetIncomeLoss", None), (10.0, "ProfitLoss", "profitloss_less_nci")]
    assert out["_stale"] == {"assets_current": "2024-12-31"}


def test_profitloss_already_attributable_is_kept_and_unreconciled_is_stamped():
    base = {"Revenues": {"units": {"USD": [fy("2025-12-31", 100.0, "0001-26-000010")]}},
            "ProfitLoss": {"units": {"USD": [fy("2025-12-31", 10.0, "0001-26-000010")]}},
            "NetIncomeLossAttributableToNoncontrollingInterest": {"units": {"USD": [fy("2025-12-31", 0.5, "0001-26-000010")]}},
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fy("2025-12-31", 5.0, "0001-26-000010")]}}}
    kept = dict(base, EarningsPerShareDiluted={"units": {"USD/shares": [fy("2025-12-31", 2.0, "0001-26-000010")]}})
    v = facts.annual_facts({"facts": {"us-gaap": kept}}, subs(), T)["net_income"]["values"][0]
    assert (v["value"], v["stamp"]) == (10.0, "profitloss_as_attributable")
    v = facts.annual_facts({"facts": {"us-gaap": base}}, subs(), T)["net_income"]["values"][0]
    assert (v["value"], v["stamp"]) == (10.0, "profitloss_basis_unverified")


def test_instants_take_fiscal_year_end_balances_only():
    cash = {"CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        {"end": "2025-12-31", "val": 5.0, "accn": "0001-26-000010", "form": "10-K", "filed": "2026-02-20", "fp": "FY"},
        {"end": "2025-09-30", "val": 4.0, "accn": "0001-25-000777", "form": "10-Q", "filed": "2025-11-01", "fp": "Q3"}]}}}
    out = facts.annual_facts(cf([fy("2025-12-31", 100.0, "0001-26-000010")], cash), subs(), T)
    assert [(v["end"], v["value"]) for v in out["cash"]["values"]] == [("2025-12-31", 5.0)]


def test_urls():
    assert facts.companyfacts_url(320193) == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    assert facts.submissions_url("0000320193") == "https://data.sec.gov/submissions/CIK0000320193.json"


def test_latest_filing_first_then_tag_priority():
    # an older filing's high-priority tag loses to the latest filing's lower-priority tag for the same year (ruling 28)
    g = {"OperatingIncomeLoss": {"units": {"USD": [fy("2024-12-31", 10.0, "0001-25-000010", filed="2025-02-21")]}}}
    i = {"ProfitLossFromOperatingActivities": {"units": {"USD": [fy("2024-12-31", 11.0, "0001-26-000010")]}}}
    out = facts.annual_facts({"facts": {"us-gaap": g, "ifrs-full": i}}, subs(), T)
    assert out["operating_income"]["values"][0]["value"] == 11.0


def test_revenue_takes_the_total_line_within_a_filing():
    g = {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [fy("2025-12-31", 936.0, "0001-26-000010")]}},
         "Revenues": {"units": {"USD": [fy("2025-12-31", 10645.0, "0001-26-000010")]}}}
    v = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)["revenue"]["values"][0]
    assert (v["value"], v["tag"], v["stamp"]) == (10645.0, "Revenues", "revenue_largest_of_tags")


def test_latest_annual_period_from_the_submissions():
    s = subs()
    s["filings"]["recent"]["reportDate"] = ["2025-12-31", "2025-12-31", "2024-12-31", "2025-12-31"]
    assert facts.latest_annual_period(s, T) == "2025-12-31"


def test_companyfacts_is_refetched_online():
    from qwen_c import sec_store
    assert facts.companyfacts_url(1).startswith(sec_store.MUTABLE_PREFIXES)


def test_ifrs_profitloss_is_net_income_reconciled_with_ifrs_nci_and_eps():
    # RR_Q7 3 (FRO, CPA): an IFRS filer with consolidated ProfitLoss only; the NCI and diluted EPS come from their IFRS tags
    a = "0001-26-000010"
    f = {"ifrs-full": {"Revenue": {"units": {"USD": [fy("2025-12-31", 1000.0, a)]}},
                       "ProfitLoss": {"units": {"USD": [fy("2025-12-31", 110.0, a)]}},
                       "ProfitLossAttributableToNoncontrollingInterests": {"units": {"USD": [fy("2025-12-31", 10.0, a)]}},
                       "DilutedEarningsLossPerShare": {"units": {"USD/shares": [fy("2025-12-31", 1.0, a)]}},
                       "AdjustedWeightedAverageShares": {"units": {"shares": [fy("2025-12-31", 100.0, a)]}}}}
    v = facts.annual_facts({"facts": f}, subs(), T)["net_income"]["values"][-1]
    assert (v["tag"], v["value"], v["stamp"]) == ("ProfitLoss", 100.0, "profitloss_less_nci")


def test_ifrs_ordinary_holders_net_income_and_depreciation_adjustment():
    # RR_Q7 3 (ECO, IHS)
    a = "0001-26-000010"
    f = {"ifrs-full": {"Revenue": {"units": {"USD": [fy("2025-12-31", 1000.0, a)]}},
                       "ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity": {"units": {"USD": [fy("2025-12-31", 90.0, a)]}},
                       "AdjustmentsForDepreciationExpense": {"units": {"USD": [fy("2025-12-31", 40.0, a)]}}}}
    out = facts.annual_facts({"facts": f}, subs(), T)
    assert out["net_income"]["values"][-1]["value"] == 90.0
    assert out["da"]["values"][-1]["tag"] in facts.DA_EXCLUDES_AMORTIZATION


# ---- F6 (F_SPEC_valuation_menu §8): derived series, each value stamped, from eligible facts only ------------------------------------

A26, A25 = "0001-26-000010", "0001-25-000010"


def ifrs(**tags):
    return {"facts": {"ifrs-full": {k: {"units": {"shares" if "Shares" in k or "Dilutive" in k else
                                                 "USD/shares" if "PerShare" in k else "USD": v}} for k, v in tags.items()}}}


def test_no_income_tax_filed_derives_pretax_from_continuing_income_and_skips_a_discontinued_year():
    g = {"Revenues": {"units": {"USD": [fy("2024-12-31", 90.0, A25, filed="2025-02-21"), fy("2025-12-31", 100.0, A26)]}},
         "NetIncomeLoss": {"units": {"USD": [fy("2024-12-31", 9.0, A25, filed="2025-02-21"), fy("2025-12-31", 8.0, A26)]}},
         "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest": {"units": {"USD": [fy("2025-12-31", 10.0, A26)]}},
         "IncomeLossFromDiscontinuedOperationsNetOfTax": {"units": {"USD": [fy("2024-12-31", -1.0, A25, filed="2025-02-21"),
                                                                            fy("2025-12-31", -2.0, A26)]}}}
    out = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)
    # 2024 has a discontinued operation and no continuing line: no pretax for it; 2025 is the continuing income, stamped
    assert [(v["end"], v["value"], v["stamp"]) for v in out["pretax_income"]["values"]] == [("2025-12-31", 10.0, facts.PRETAX_FROM_NI)]
    assert "pretax_income" not in out["_absent"]


def test_any_income_tax_fact_filed_by_T_blocks_the_derived_pretax_but_one_filed_after_T_does_not():
    g = {"Revenues": {"units": {"USD": [fy("2025-12-31", 100.0, A26)]}},
         "NetIncomeLoss": {"units": {"USD": [fy("2025-12-31", 8.0, A26)]}}}
    taxed = dict(g, DeferredTaxLiabilities={"units": {"USD": [{"end": "2025-12-31", "val": 0.0, "accn": A26, "form": "10-K", "filed": "2026-02-20"}]}})
    assert "pretax_income" not in facts.annual_facts({"facts": {"us-gaap": taxed}}, subs(), T)
    late = dict(g, IncomeTaxesPaidNet={"units": {"USD": [fy("2025-12-31", 1.0, "0001-26-000099", form="10-K/A", filed="2026-03-10")]}})
    v = facts.annual_facts({"facts": {"us-gaap": late}}, subs(), T)["pretax_income"]["values"][0]
    assert (v["value"], v["tag"], v["stamp"]) == (8.0, "NetIncomeLoss", facts.PRETAX_FROM_NI)


def test_ifrs_diluted_shares_are_basic_plus_the_dilutive_effect_only_when_they_reconcile_with_diluted_eps():
    base = dict(Revenue=[fy("2025-12-31", 1000.0, A26)], ProfitLossAttributableToOwnersOfParent=[fy("2025-12-31", 42.0, A26)],
                WeightedAverageShares=[fy("2025-12-31", 100.0, A26)],
                DilutiveEffectOfShareOptionsOnNumberOfOrdinaryShares=[fy("2025-12-31", 5.0, A26)])
    v = facts.annual_facts(ifrs(**base, DilutedEarningsLossPerShare=[fy("2025-12-31", 0.4, A26)]), subs(), T)["diluted_shares"]["values"][0]
    assert (v["value"], v["stamp"]) == (105.0, "diluted_shares_from_basic_plus_dilutive_effect")
    assert v["tag"] == "WeightedAverageShares+DilutiveEffectOfShareOptionsOnNumberOfOrdinaryShares"
    off = facts.annual_facts(ifrs(**base, DilutedEarningsLossPerShare=[fy("2025-12-31", 0.42, A26)]), subs(), T)   # 0.4 on 105: 5% off
    assert "diluted_shares" not in off


def test_ifrs_diluted_shares_with_no_dilutive_effect_filed_are_the_basic_when_eps_reconciles():
    f = ifrs(Revenue=[fy("2025-12-31", 1000.0, A26)], ProfitLossAttributableToOwnersOfParent=[fy("2025-12-31", -50.0, A26)],
             WeightedAverageShares=[fy("2025-12-31", 100.0, A26)], DilutedEarningsLossPerShare=[fy("2025-12-31", -0.5, A26)])
    v = facts.annual_facts(f, subs(), T)["diluted_shares"]["values"][0]
    assert (v["value"], v["tag"]) == (100.0, "WeightedAverageShares+no_dilutive_effect_filed")


def test_equity_from_the_total_less_nci_or_the_total_when_nothing_is_attributed_to_nci():
    inst = lambda end, val, a=A26, filed="2026-02-20": {"end": end, "val": val, "accn": a, "form": "10-K", "filed": filed}
    g = {"Revenues": {"units": {"USD": [fy("2024-12-31", 90.0, A25, filed="2025-02-21"), fy("2025-12-31", 100.0, A26)]}},
         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": {"units": {"USD": [
             inst("2024-12-31", 50.0, A25, "2025-02-21"), inst("2025-12-31", 60.0)]}},
         "MinorityInterest": {"units": {"USD": [inst("2024-12-31", 0.0, A25, "2025-02-21")]}},
         "NetIncomeLoss": {"units": {"USD": [fy("2025-12-31", 7.0, A26)]}},
         "ProfitLoss": {"units": {"USD": [fy("2025-12-31", 7.0, A26)]}}}
    vals = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)["equity"]["values"]
    assert [(v["end"], v["value"], v["stamp"]) for v in vals] == [("2024-12-31", 50.0, "equity_total_less_nci"),
                                                                 ("2025-12-31", 60.0, "equity_total_no_nci_income")]
    # a nonzero NCI balance filed before, or consolidated profit unlike net income, leaves the year absent
    g2 = dict(g, MinorityInterest={"units": {"USD": [inst("2024-12-31", 3.0, A25, "2025-02-21")]}})
    assert [v["end"] for v in facts.annual_facts({"facts": {"us-gaap": g2}}, subs(), T)["equity"]["values"]] == ["2024-12-31"]
    g3 = dict(g, ProfitLoss={"units": {"USD": [fy("2025-12-31", 7.5, A26)]}})
    assert [v["end"] for v in facts.annual_facts({"facts": {"us-gaap": g3}}, subs(), T)["equity"]["values"]] == ["2024-12-31"]


def test_the_cost_of_sales_da_line_counts_only_beside_cost_excluding_da_and_a_tag_switch_stays_visible():
    g = {"Revenues": {"units": {"USD": [fy("2024-12-31", 90.0, A25, filed="2025-02-21"), fy("2025-12-31", 100.0, A26)]}},
         "DepreciationDepletionAndAmortization": {"units": {"USD": [fy("2024-12-31", 6.0, A25, filed="2025-02-21")]}},
         "CostOfGoodsAndServicesSoldDepreciationAndAmortization": {"units": {"USD": [fy("2025-12-31", 7.0, A26)]}},
         "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization": {"units": {"USD": [fy("2025-12-31", 70.0, A26)]}}}
    da = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)["da"]
    assert [(v["tag"], v["stamp"]) for v in da["values"]] == [("DepreciationDepletionAndAmortization", None),
                                                            (facts.DA_COST_LINE, "da_from_cost_of_sales_line")]
    assert da["tags"] == sorted(["DepreciationDepletionAndAmortization", facts.DA_COST_LINE])
    alone = dict(g)
    del alone["CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]
    out = facts.annual_facts({"facts": {"us-gaap": alone}}, subs(), T)
    assert [v["end"] for v in out["da"]["values"]] == ["2024-12-31"] and out["_stale"]["da"] == "2024-12-31"


def test_a_cost_of_sales_line_never_outranks_a_total_in_the_same_filing():
    g = {"Revenues": {"units": {"USD": [fy("2025-12-31", 100.0, A26)]}},
         "DepreciationAndAmortization": {"units": {"USD": [fy("2025-12-31", 9.0, A26)]}},
         "CostOfGoodsAndServicesSoldDepreciationAndAmortization": {"units": {"USD": [fy("2025-12-31", 7.0, A26)]}},
         "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization": {"units": {"USD": [fy("2025-12-31", 70.0, A26)]}}}
    v = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)["da"]["values"][0]
    assert (v["value"], v["tag"], v["stamp"]) == (9.0, "DepreciationAndAmortization", None)


def test_auxiliary_concepts_are_never_named_stale():
    g = {"Revenues": {"units": {"USD": [fy("2024-12-31", 90.0, A25, filed="2025-02-21"), fy("2025-12-31", 100.0, A26)]}},
         "FinancingInterestExpense": {"units": {"USD": [fy("2024-12-31", 3.0, A25, filed="2025-02-21")]}}}
    assert facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)["_stale"] == {}
