"""WO_UV5 item 3: the IFRS interest expense where the finance-cost bundle gives a cost of debt outside the band (inputs.base), on hand-built facts.
Items 1 (one source per pooled series) and 2 (the offline family) are tested in test_value_uv3.py and tools/site/test_decided_shadow.py."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_facts import T, fy
from qwen_c.tests.test_value_inputs import base, series
from qwen_c.value import desk, facts

STAMP = "interest_ifrs_expense_for_finance_costs:refused=ifrs-full:FinanceCosts:used=ifrs-full:InterestExpense"


def ifrs(bundle=8, alt=1.0, tag="FinanceCosts", **over):
    """ti.facts: debt 20 at both year ends; the interest read is `bundle` under `tag` for the base year (40% of the debt at 8), the IFRS
    InterestExpense of the same year is `alt` (None: not filed)."""
    f = ti.facts(interest_expense=series([1, 1, 1, 1, bundle], tag=tag), **over)
    if alt is not None:
        f["interest_expense_ifrs"] = series([alt], tag="InterestExpense")
    return f


def test_the_ifrs_interest_expense_is_used_where_the_bundle_is_out_of_band_and_it_is_inside():
    b = base(ifrs())
    assert STAMP in b["stamps"] and "interest_from_filing_text" not in b["stamps"] and "interest_from_filing" not in b
    assert b["interest_ifrs_expense"] == {"value": 1.0, "refused_tag": "ifrs-full:FinanceCosts", "used_tag": "ifrs-full:InterestExpense",
                                          "tagged_value": 8.0, "kd_used": pytest.approx(1.0 / 20)}
    assert b["k0_interest"] == 1.0                                   # the interest that scales with revenue is the one used


def test_a_bundle_inside_the_band_is_not_touched_even_where_the_ifrs_interest_expense_is_filed():
    b = base(ifrs(bundle=1.5, alt=1.0))
    assert not any(s.startswith("interest_ifrs") for s in b["stamps"]) and "interest_ifrs_expense" not in b and b["k0_interest"] == 1.5


def test_the_result_with_the_swap_equals_the_base_of_the_same_company_whose_bundle_is_that_figure():
    """No other number moves: the base with the swap equals the base of a company whose interest read is the IFRS figure, in every key but the stamps."""
    swapped, plain = base(ifrs()), base(ifrs(bundle=1.0, alt=None))
    keep = lambda b: {k: v for k, v in b.items() if k not in ("stamps", "interest_ifrs_expense")}      # noqa: E731
    assert keep(swapped)["x0"] == plain["x0"] and keep(swapped)["k0_interest"] == plain["k0_interest"] and keep(swapped)["tau"] == plain["tau"]


def test_where_the_ifrs_interest_expense_is_also_outside_the_band_the_first_refusal_stands_and_says_so():
    with pytest.raises(desk.DeskRefusal) as e:
        base(ifrs(alt=9.0))
    assert e.value.code == "kd_out_of_band" and "ifrs-full:InterestExpense (9) for the same year is also outside" in str(e.value)
    assert e.value.figures["tag"] == "FinanceCosts" and e.value.figures["interest"] == 8.0


def test_where_it_is_not_filed_or_is_zero_the_refusal_stands_unchanged():
    for alt in (None, 0.0):
        with pytest.raises(desk.DeskRefusal) as e:
            base(ifrs(alt=alt))
        assert e.value.code == "kd_out_of_band" and "also outside" not in str(e.value)


def test_a_filer_whose_interest_is_not_the_finance_cost_bundle_is_not_swapped():
    with pytest.raises(desk.DeskRefusal) as e:
        base(ifrs(tag="InterestExpense"))
    assert e.value.code == "kd_out_of_band"


def test_a_stated_interest_override_is_not_swapped():
    with pytest.raises(desk.DeskRefusal) as e:
        inputs_base = ifrs()
        from qwen_c.value import inputs
        inputs.base(inputs_base, market_cap=180.0, bill_rate=0.04, interest_override=9.0)
    assert e.value.code == "kd_out_of_band"


def test_a_later_refusal_of_the_swapped_base_is_that_refusals_own():
    f = ifrs()
    f["debt_current"], f["debt_noncurrent"] = series([1, 1, 1, 1, 1], tag="LongTermDebtCurrent"), series([19, 19, 19, 19, 19])
    del f["cash"]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code != "kd_out_of_band"


def test_the_facts_carry_ifrs_interest_expense_as_an_auxiliary_concept_that_is_never_stale():
    assert "interest_expense_ifrs" in facts.AUX_CONCEPTS and facts.CONCEPTS["interest_expense_ifrs"][1] == [("ifrs-full", "InterestExpense", "USD")]
    acc = "0001-26-000010"
    cf = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fy(f"{y}-12-31", 100e6, acc) for y in range(2021, 2026)]}}},
                    "ifrs-full": {"InterestExpense": {"units": {"USD": [fy("2024-12-31", 90.0, acc)]}}}}}
    subs = {"filings": {"recent": {"accessionNumber": [acc], "form": ["10-K"], "filingDate": ["2026-02-20"], "acceptanceDateTime": ["2026-02-20T16:05:00.000Z"],
                                   "reportDate": ["2025-12-31"], "primaryDocument": ["x.htm"]}}}
    out = facts.annual_facts(cf, subs, T)
    assert [v["value"] for v in out["interest_expense_ifrs"]["values"]] == [90.0] and "interest_expense_ifrs" not in out["_stale"]
