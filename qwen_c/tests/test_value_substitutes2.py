"""WO_NC2: labelled fact substitutes, second round (equity, capex, D&A, current items, pretax income), on hand-built synthetic facts.
A substitute is consulted only where the exact concept lacks a year the valuation reads, takes one tag for every year, is stamped
substitute:<concept>:<taxonomy>:<tag> (plus substitute_scope:<concept>:<scope> where the tag differs in kind), and the refusals stay where no
tag qualifies."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_facts import T, fy, subs
from qwen_c.tests.test_value_inputs import ENDS, base
from qwen_c.value import desk, facts, inputs

ACC = "0001-26-000010"
PCAP = "substitute:equity:us-gaap:PartnersCapital"


def yrs(vals, ends=ENDS):
    return [fy(e, v, ACC) for e, v in zip(ends[-len(vals):], vals)]


INSTANTS = {"PartnersCapital", "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "CurrentAssets",
            "CurrentAssetsOtherThanAssetsOrDisposalGroupsClassifiedAsHeldForSaleOrAsHeldForDistributionToOwners",
            "CurrentLiabilitiesOtherThanLiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale"}


def put(tax, tag, vals, unit="USD", ends=ENDS):
    rows = yrs(vals, ends)
    if tag in INSTANTS:                                                    # a balance is an instant: no start date
        rows = [{k: v for k, v in r.items() if k not in ("start", "fp")} for r in rows]
    return {tax: {tag: {"units": {unit: rows}}}}


def doc(*parts):
    f = {}
    for p in parts:
        for tax, d in p.items():
            f.setdefault(tax, {}).update(d)
    return {"facts": f}


REV = put("us-gaap", "Revenues", [80, 85, 90, 95, 100])


def run(d, items=True):
    return facts.annual_facts(d, subs(), T, substitute_items=items)


def stamps(out, concept):
    return {v["stamp"] for v in out[concept]["values"]}


# ---- equity -----------------------------------------------------------------------------------------------------------------------

def test_partners_capital_stands_in_for_absent_equity_and_is_stamped():
    out = run(doc(REV, put("us-gaap", "PartnersCapital", [40, 41, 42, 44, 46])))
    assert out["equity"]["tags"] == ["PartnersCapital"] and [v["value"] for v in out["equity"]["values"]] == [40.0, 41.0, 42.0, 44.0, 46.0]
    assert stamps(out, "equity") == {PCAP} and "equity" not in out["_absent"] and "equity" not in out["_stale"]


def test_total_equity_with_nci_stamps_its_scope_when_the_nci_balance_is_not_filed():
    # NCI income is filed (not 0) and no NCI balance: facts._derive cannot take the total as the parent's equity, so the substitute is read
    d = doc(REV, put("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", [40, 41, 42, 44, 46]),
            put("us-gaap", "NetIncomeLossAttributableToNoncontrollingInterest", [1, 1, 1, 1, 1]))
    out = run(d)
    lab = "substitute:equity:us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    assert stamps(out, "equity") == {f"{lab};substitute_scope:equity:includes_nci"}
    assert "equity" not in run(d, items=False)


def test_exact_equity_wins_and_the_flag_changes_nothing():
    d = doc(REV, put("us-gaap", "StockholdersEquity", [40, 41, 42, 44, 46]), put("us-gaap", "PartnersCapital", [1, 1, 1, 1, 1]))
    out = run(d)
    assert out["equity"]["tags"] == ["StockholdersEquity"] and out == run(d, items=False)


def test_one_equity_tag_for_every_year_never_a_mix():
    # the exact tag lacks the base year: the substitute replaces the series whole
    d = doc(REV, put("us-gaap", "StockholdersEquity", [40, 41, 42, 44], ends=ENDS[:4]), put("us-gaap", "PartnersCapital", [50, 51, 52, 54, 56]))
    out = run(d)
    assert out["equity"]["tags"] == ["PartnersCapital"] and [v["value"] for v in out["equity"]["values"]] == [50.0, 51.0, 52.0, 54.0, 56.0]
    # the substitute lacks the opening year (it is read as the opening capital): no substitution, the exact series stays
    d = doc(REV, put("us-gaap", "StockholdersEquity", [40, 41, 42, 44], ends=ENDS[:4]), put("us-gaap", "PartnersCapital", [56], ends=ENDS[-1:]))
    assert run(d)["equity"]["tags"] == ["StockholdersEquity"]


def test_a_filed_zero_equity_is_a_value_not_an_absence():
    d = doc(REV, put("us-gaap", "StockholdersEquity", [0, 0, 0, 0, 0]), put("us-gaap", "PartnersCapital", [40, 41, 42, 44, 46]))
    out = run(d)
    assert out["equity"]["tags"] == ["StockholdersEquity"] and {v["value"] for v in out["equity"]["values"]} == {0.0}


def test_equity_stays_absent_when_no_listed_tag_is_filed():
    out = run(doc(REV, put("us-gaap", "SomethingElse", [1, 2, 3, 4, 5])))
    assert "equity" not in out and "equity" in out["_absent"]


# ---- capex ------------------------------------------------------------------------------------------------------------------------

def test_capex_substitutes_are_stamped_and_the_priority_is_the_listing_order():
    d = doc(REV, put("ifrs-full", "PurchaseOfMiningAssets", [5, 5, 6, 6, 7]), put("us-gaap", "PropertyPlantAndEquipmentAdditions", [9, 9, 9, 9, 9]))
    out = run(d)
    assert out["capex"]["tags"] == ["PurchaseOfMiningAssets"] and stamps(out, "capex") == {"substitute:capex:ifrs-full:PurchaseOfMiningAssets"}
    out = run(doc(REV, put("us-gaap", "PropertyPlantAndEquipmentAdditions", [9, 9, 9, 9, 9])))
    assert stamps(out, "capex") == {"substitute:capex:us-gaap:PropertyPlantAndEquipmentAdditions"}


def test_net_capex_is_stamped_net_and_used_only_while_a_net_outflow_in_every_year_read():
    tag = "PaymentsForProceedsFromProductiveAssets"
    out = run(doc(REV, put("us-gaap", tag, [5, 5, 6, 6, 7])))
    assert stamps(out, "capex") == {f"substitute:capex:us-gaap:{tag};substitute_scope:capex:net"}
    for vals in ([5, 5, 6, 6, -7], [5, -5, 6, 6, 7], [5, 5, 6, 6, 0]):            # a net inflow (or nil) in any year read: the refusal stands
        out = run(doc(REV, put("us-gaap", tag, vals)))
        assert "capex" not in out and "capex" in out["_absent"]


def test_capex_substitute_needs_the_base_year_and_the_pool_minimum():
    out = run(doc(REV, put("ifrs-full", "PurchaseOfMiningAssets", [5, 5, 6, 6], ends=ENDS[:4])))             # not the base year
    assert "capex" not in out
    out = run(doc(REV, put("ifrs-full", "PurchaseOfMiningAssets", [6, 7], ends=ENDS[3:])))                   # two years: under the pool minimum
    assert "capex" not in out
    assert "capex" in run(doc(REV, put("ifrs-full", "PurchaseOfMiningAssets", [6, 6, 7], ends=ENDS[2:])))


def test_exact_capex_wins_and_the_substitute_clears_a_stale_exact_series():
    d = doc(REV, put("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", [5, 5, 6, 6, 7]), put("ifrs-full", "PurchaseOfMiningAssets", [1, 1, 1, 1, 1]))
    assert run(d)["capex"]["tags"] == ["PaymentsToAcquirePropertyPlantAndEquipment"] and run(d) == run(d, items=False)
    d = doc(REV, put("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", [5, 5, 6], ends=ENDS[:3]), put("ifrs-full", "PurchaseOfMiningAssets", [4, 4, 5, 6, 7]))
    assert "capex" in run(d, items=False)["_stale"] and "capex" not in run(d)["_stale"] and run(d)["capex"]["tags"] == ["PurchaseOfMiningAssets"]


# ---- D&A --------------------------------------------------------------------------------------------------------------------------

def test_combined_results_of_operations_tag_stands_in_for_da():
    tag = "ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion"
    out = run(doc(REV, put("us-gaap", tag, [4, 4, 5, 5, 6])))
    assert out["da"]["tags"] == [tag] and stamps(out, "da") == {f"substitute:da:us-gaap:{tag};substitute_scope:da:producing_activities_only"}


def test_amortization_alone_and_depletion_alone_are_not_da():
    for tag in ("AmortizationOfIntangibleAssets", "Depletion", "DepletionOfOilAndGasProperties"):
        out = run(doc(REV, put("us-gaap", tag, [4, 4, 5, 5, 6])))
        assert "da" not in out and "da" in out["_absent"], tag


def test_exact_da_wins_and_a_filed_zero_stays():
    d = doc(REV, put("us-gaap", "DepreciationDepletionAndAmortization", [0, 0, 0, 0, 0]),
            put("us-gaap", "ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion", [4, 4, 5, 5, 6]))
    out = run(d)
    assert out["da"]["tags"] == ["DepreciationDepletionAndAmortization"] and out == run(d, items=False)


# ---- current assets and liabilities ----------------------------------------------------------------------------------------------

def test_held_for_sale_variants_of_the_current_items_are_stamped():
    a = "CurrentAssetsOtherThanAssetsOrDisposalGroupsClassifiedAsHeldForSaleOrAsHeldForDistributionToOwners"
    li = "CurrentLiabilitiesOtherThanLiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale"
    out = run(doc(REV, put("ifrs-full", a, [30, 30, 31, 32, 33]), put("ifrs-full", li, [20, 20, 21, 21, 22])))
    assert stamps(out, "assets_current") == {f"substitute:assets_current:ifrs-full:{a};substitute_scope:assets_current:excludes_held_for_sale"}
    assert stamps(out, "liabilities_current") == {f"substitute:liabilities_current:ifrs-full:{li};substitute_scope:liabilities_current:excludes_held_for_sale"}


def test_exact_current_items_win_over_the_held_for_sale_variants():
    a = "CurrentAssetsOtherThanAssetsOrDisposalGroupsClassifiedAsHeldForSaleOrAsHeldForDistributionToOwners"
    d = doc(REV, put("ifrs-full", "CurrentAssets", [30, 30, 31, 32, 33]), put("ifrs-full", a, [1, 1, 1, 1, 1]))
    assert run(d)["assets_current"]["tags"] == ["CurrentAssets"] and run(d) == run(d, items=False)


# ---- pretax income ----------------------------------------------------------------------------------------------------------------

DOM, FOR = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign"


def test_domestic_plus_foreign_pretax_income_is_summed_and_names_both_tags():
    out = run(doc(REV, put("us-gaap", DOM, [6, 6, 7, 7, 8]), put("us-gaap", FOR, [4, 5, 5, 6, 6])))
    assert [v["value"] for v in out["pretax_income"]["values"]] == [10.0, 11.0, 12.0, 13.0, 14.0]
    assert stamps(out, "pretax_income") == {f"substitute:pretax_income:us-gaap:{DOM}+{FOR}"} and out["pretax_income"]["tags"] == [f"{DOM}+{FOR}"]


def test_one_of_the_two_pretax_parts_is_no_substitute():
    dom, for_ = put("us-gaap", DOM, [6, 6, 7, 7, 8]), put("us-gaap", FOR, [4, 5, 5, 6, 6])
    short = put("us-gaap", FOR, [4, 5, 5, 6], ends=ENDS[:4])                                         # lacks the base year
    for parts in ((dom,), (for_,), (dom, short)):
        out = run(doc(REV, *parts))
        assert "pretax_income" not in out or not any(v["end"] == ENDS[-1] for v in out["pretax_income"]["values"])


def test_exact_pretax_wins_and_a_zero_sum_is_a_value():
    d = doc(REV, put("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", [10, 11, 12, 13, 14]),
            put("us-gaap", DOM, [1, 1, 1, 1, 1]), put("us-gaap", FOR, [1, 1, 1, 1, 1]))
    assert run(d)["pretax_income"]["tags"][0].startswith("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinary") and run(d) == run(d, items=False)
    out = run(doc(REV, put("us-gaap", DOM, [0, 0, 0, 0, 0]), put("us-gaap", FOR, [0, 0, 0, 0, 0])))
    assert {v["value"] for v in out["pretax_income"]["values"]} == {0.0}


# ---- off by default, the base and the route --------------------------------------------------------------------------------------

def test_the_flag_is_off_by_default():
    d = doc(REV, put("us-gaap", "PartnersCapital", [40, 41, 42, 44, 46]))
    assert "equity" not in facts.annual_facts(d, subs(), T) and "equity" in run(d)


def test_base_carries_the_substitute_labels_and_scope_stamps():
    f = ti.facts()
    lab, scope = "substitute:capex:us-gaap:PaymentsForProceedsFromProductiveAssets", "substitute_scope:capex:net"
    f["capex"] = {"values": [dict(v, stamp=f"{lab};{scope}") for v in f["capex"]["values"]]}
    f["equity"] = {"values": [dict(v, stamp=PCAP) for v in f["equity"]["values"]]}
    b = base(f)
    assert {lab, scope, PCAP} <= set(b["stamps"]) and b["substitutes"] == sorted([lab, PCAP])
    assert "substitutes" not in base() and not any(s.startswith("substitute") for s in base()["stamps"])


def test_a_substituted_equity_runs_through_the_base_like_an_exact_one():
    f = ti.facts()
    f["equity"] = {"values": [dict(v, stamp=PCAP) for v in f["equity"]["values"]]}
    b = base(f)
    exact = base()
    assert {k: v for k, v in b.items() if k not in ("stamps", "substitutes")} == {k: v for k, v in exact.items() if k != "stamps"}


def test_prepare_substitutes_items_on_the_operating_route_only(monkeypatch):
    from qwen_c.value import run as runner

    seen = []

    def build(*a, **k):
        seen.append(k.get("substitute_items"))
        raise desk.DeskRefusal("history_short", "x")
    monkeypatch.setattr(facts, "build", build)
    for fam in ("operating", "commodity", "financial"):
        with pytest.raises(desk.DeskRefusal):
            runner.prepare({"decision_time_utc": "2026-03-01T13:00:00Z"}, "1", "S", 1.0, online=False, family=fam)
    assert seen == [True, True, False]


def test_versions_are_bumped():
    assert facts.FACTS_VERSION == "m3q.facts.v12" and inputs.INPUTS_VERSION == "m3q.inputs.v16"
