"""WO_NC9c: inputs.base(real_estate=True) and run.prepare(real_estate=True), the base of the decided method's real-estate family. The mode replaces two data
rules that real-estate filings fail structurally and relaxes nothing else; False (the default) is byte-identical to before. Hand-built facts, no network."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.value import desk, facts as vfacts, inputs, run as vrun

ENDS = ti.ENDS


def base(f=None, **kw):
    return inputs.base(f or ti.facts(), market_cap=180.0, bill_rate=ti.BILL, **kw)


def unclassified(**over):
    f = ti.facts(**over)
    del f["assets_current"], f["liabilities_current"]
    return f


def stale_oi(last="2024-12-31", **over):
    """The operating-income tag stops at `last` and the facts say so, as facts.annual_facts does for a concept ending before the latest revenue year."""
    f = ti.facts(**over)
    f["operating_income"] = ti.series([12, 13, 14, 15], ends=ENDS[:4])
    f["_stale"] = {"operating_income": last}
    return f


# ---- the default is unchanged ----------------------------------------------------------------------------------------------------------

def test_the_default_is_byte_identical_and_carries_no_trace_of_the_mode():
    a, b = base(), base(real_estate=False)
    assert a == b and "real_estate" not in a and "real_estate_base" not in a["stamps"] and not any("nwc_not_classified" in s or "stale_not_used" in s for s in a["stamps"])


def test_the_mode_on_a_company_that_needs_neither_rule_changes_only_its_marks():
    a, b = base(), base(real_estate=True)
    assert b["real_estate"] is True and "real_estate_base" in b["stamps"] and [s for s in b["stamps"] if s != "real_estate_base"] == a["stamps"]
    assert {k: v for k, v in b.items() if k not in ("stamps", "real_estate")} == {k: v for k, v in a.items() if k != "stamps"}


def test_without_the_mode_both_data_rules_still_refuse():
    with pytest.raises(desk.DeskRefusal) as e:
        base(unclassified())
    assert e.value.code == "input_missing" and "current assets and current liabilities" in str(e.value)
    with pytest.raises(desk.DeskRefusal) as e:
        base(stale_oi())
    assert e.value.code == "facts_stale" and "operating_income" in str(e.value)


# ---- rule 1: an unclassified balance sheet ----------------------------------------------------------------------------------------------

def test_an_unclassified_balance_sheet_takes_working_capital_as_zero_and_says_so():
    b = base(unclassified(), real_estate=True)
    assert b["w"] == 0.0 and "nwc_not_classified_taken_as_0" in b["stamps"] and "real_estate_base" in b["stamps"]
    classified = base()
    assert classified["w"] != 0.0 and "nwc_not_classified_taken_as_0" not in classified["stamps"]
    assert {k: v for k, v in b.items() if k not in ("stamps", "w", "real_estate")} == {k: v for k, v in classified.items() if k not in ("stamps", "w")}   # nothing else moves


def test_one_of_the_two_current_items_filed_is_still_refused_in_the_mode():
    for gone in ("assets_current", "liabilities_current"):
        f = ti.facts()
        del f[gone]
        with pytest.raises(desk.DeskRefusal) as e:
            base(f, real_estate=True)
        assert e.value.code == "input_missing"
    f = ti.facts(assets_current=ti.series([30, 30, 30, 30], ends=ENDS[:4]), liabilities_current=ti.series([20, 20, 20, 20], ends=ENDS[:4]))      # filed, but not for the base year
    assert base(f, real_estate=True)["w"] == 0.0                                                                                                 # neither is filed for the base year


# ---- rule 2: a stale operating-income tag ------------------------------------------------------------------------------------------------

def test_a_stale_operating_income_tag_gives_pretax_plus_interest_in_every_year_and_says_so():
    b = base(stale_oi(), real_estate=True)
    pt, ie = [10, 11, 12, 12.5, 13], 1
    assert b["oi0"] == 13 + ie and b["op_margin0"] == pytest.approx(14 / 100)
    assert b["record"]["op_margin"] == pytest.approx({e: (p + ie) / r for e, p, r in zip(ENDS, pt, [80, 85, 90, 95, 100])})
    assert "oi_from_pretax_plus_interest" in b["stamps"] and "operating_income_tag_stale_not_used" in b["stamps"]
    assert b["k0"] == pytest.approx(14 - (13 - 7 * ti.BILL))                                      # K_0 = OI_0 - pt_ex, as when the tag is never filed


def test_a_stale_tag_in_the_mode_equals_the_base_with_the_tag_never_filed_but_for_the_stamps():
    never = ti.facts()
    del never["operating_income"]
    a, b = base(never), base(stale_oi(), real_estate=True)
    assert {k: v for k, v in a.items() if k not in ("stamps", "record")} == {k: v for k, v in b.items() if k not in ("stamps", "record", "real_estate")}
    assert a["record"] == b["record"] and a["stamps"] == [s for s in b["stamps"] if s not in ("real_estate_base", "operating_income_tag_stale_not_used")]


def test_a_stale_tag_still_needs_interest_expense_for_the_base_year():
    f = stale_oi(interest_expense=ti.series([1, 1, 1, 1], ends=ENDS[:4]))
    with pytest.raises(desk.DeskRefusal) as e:
        base(f, real_estate=True)
    assert e.value.code == "bridge_unavailable"


def test_a_fresh_operating_income_tag_is_used_in_the_mode():
    b = base(real_estate=True)
    assert b["oi0"] == 16 and "oi_from_pretax_plus_interest" not in b["stamps"]


# ---- nothing else is relaxed -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("concept", ["net_income", "capex", "da", "pretax_income"])
def test_another_stale_concept_still_refuses_in_the_mode(concept):
    f = ti.facts()
    f["_stale"] = {concept: "2024-12-31"}
    with pytest.raises(desk.DeskRefusal) as e:
        base(f, real_estate=True)
    assert e.value.code == "facts_stale"


def test_a_stale_operating_income_tag_and_another_stale_concept_refuse_on_the_other():
    f = stale_oi()
    f["_stale"] = {"operating_income": "2024-12-31", "pretax_income": "2024-12-31"}
    with pytest.raises(desk.DeskRefusal) as e:
        base(f, real_estate=True)
    assert e.value.code == "facts_stale" and "pretax_income" in str(e.value) and "operating_income" not in str(e.value)


def test_cash_shares_and_borrowing_cost_rules_are_the_same_in_the_mode():
    f = ti.facts()
    del f["cash"]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f, real_estate=True)
    assert e.value.code == "input_missing"
    f = ti.facts()
    del f["diluted_shares"]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f, real_estate=True)
    assert e.value.code == "shares_unavailable"
    f = ti.facts(interest_expense=ti.series([6, 6, 6, 6, 6]))                                     # kd far above the band
    with pytest.raises(desk.DeskRefusal) as e:
        base(f, real_estate=True)
    assert e.value.code == "kd_out_of_band"


def test_the_two_new_concepts_are_auxiliary_and_listed_in_priority_order():
    assert {"re_gain_on_sales", "re_impairment"} <= vfacts.AUX_CONCEPTS and {"re_gain_on_sales", "re_impairment"} <= set(vfacts.CONCEPTS)
    assert [t[1] for t in vfacts.CONCEPTS["re_gain_on_sales"][1]] == ["GainLossOnSaleOfProperties", "GainsLossesOnSalesOfInvestmentRealEstate", "GainLossOnDispositionOfAssets",
                                                                       "GainLossOnSaleOfPropertyPlantEquipment", "GainLossOnDispositionOfAssets1", "GainsLossesOnSalesOfOtherRealEstate"]
    assert [t[1] for t in vfacts.CONCEPTS["re_impairment"][1]] == ["ImpairmentOfRealEstate", "AssetImpairmentCharges", "ImpairmentOfLongLivedAssetsHeldForUse"]


# ---- run.prepare ---------------------------------------------------------------------------------------------------------------------------

def stub_prepare(monkeypatch, f):
    monkeypatch.setattr(vrun.facts, "build", lambda *a, **k: f)
    monkeypatch.setattr(vrun.rs2_data, "bill_rate_mean", lambda a, b: (ti.BILL, "test"))
    monkeypatch.setattr(vrun.forecast, "record_items", lambda f: [])                             # the menu's record text needs accession numbers the hand-built facts do not carry
    monkeypatch.setattr(vrun.coe, "cost_of_equity", lambda *a, **k: (0.09, {"g_anchor": 0.03}))
    return {"decision_time_utc": "2026-03-01T13:00:00Z"}


def prepare(pk, **k):
    return vrun.prepare(pk, "1", "S", 180.0, online=False, **k)


def test_prepare_takes_the_real_estate_family_only_with_the_mode_and_only_that_family(monkeypatch):
    pk = stub_prepare(monkeypatch, unclassified())
    f, b, *_ = prepare(pk, family="real_estate", real_estate=True)
    assert b["real_estate"] is True and b["w"] == 0.0 and "nwc_not_classified_taken_as_0" in b["stamps"] and b["g_anchor"] == 0.03
    for k in ({"family": "real_estate"}, {"family": "operating", "real_estate": True}, {"family": "financial", "real_estate": True}, {"family": "family_not_built", "real_estate": True}):
        with pytest.raises(desk.DeskRefusal) as e:
            prepare(pk, **k)
        assert e.value.code == "family_not_routed"
    with pytest.raises(desk.DeskRefusal) as e:
        prepare(pk, family="operating")                                  # the unclassified balance sheet refuses on the menu route, as before
    assert e.value.code == "input_missing"


def test_prepare_substitutes_items_for_the_real_estate_family_as_for_the_operating_route(monkeypatch):
    seen = []
    pk = stub_prepare(monkeypatch, ti.facts())
    monkeypatch.setattr(vrun.facts, "build", lambda *a, **k: seen.append((k.get("substitute_revenue"), k.get("substitute_items"))) or ti.facts())
    prepare(pk, family="real_estate", real_estate=True)
    assert seen == [(True, True)]
