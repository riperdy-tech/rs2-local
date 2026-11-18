"""WO_UV2: recover the names the engine refuses for figures that ARE filed (stage 1), on synthetic facts only.
For each reading: the accepted case, the case whose verification fails (the old refusal stands), and that a company that passed before is unchanged."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_facts import T, cf, fy, subs
from qwen_c.tests.test_value_fin import bank_facts
from qwen_c.tests.test_value_inputs import ENDS, base, series
from qwen_c.tests.test_value_substitutes import no_interest, one
from qwen_c.value import desk, facts, inputs

M = 1e6


def refusal(fn, *a, **k):
    with pytest.raises(desk.DeskRefusal) as e:
        fn(*a, **k)
    return e.value


def doc(**tags):
    """A companyfacts document: {tag: (unit, rows)} under us-gaap."""
    return {"facts": {"us-gaap": {t: {"units": {u: rows}} for t, (u, rows) in tags.items()}}}


A = "0001-26-000010"
Y3 = ("2023-12-31", "2024-12-31", "2025-12-31")


def rows(vals, ends=Y3):
    return [fy(e, v, A) for e, v in zip(ends, vals)]


# ---- senior-notes debt tags -------------------------------------------------------------------------------------------------------------

def senior_facts(tot=(20, 20), nc=(18, 19), cur=(2, 1), loc=None, **over):
    f = ti.facts(**over)
    f.pop("debt_current"), f.pop("debt_noncurrent")
    f["debt_senior_total"], f["debt_senior_noncurrent"] = series(list(tot)), series(list(nc))
    if cur is not None:
        f["debt_senior_current"] = series(list(cur))
    if loc is not None:
        f["line_of_credit_noncurrent"] = series(list(loc))
    return f


def test_senior_notes_are_the_debt_where_no_debt_tag_resolves_and_the_parts_sum_to_the_total():
    b = base(senior_facts())
    assert b["debt0"] == 20 and b["debt_basis"] == "SeniorNotes" and b["kd"] == pytest.approx(1 / 20)
    assert "debt_from_senior_notes_tags_parts_reconciled" in b["stamps"]


def test_a_line_of_credit_filed_apart_from_the_notes_is_added():
    b = base(senior_facts(tot=(20, 18), nc=(18, 18), cur=(2, 0), loc=(3, 0)))
    assert b["debt0"] == 18 and b["debt_basis"] == "SeniorNotes+LongTermLineOfCredit"
    assert base(senior_facts(loc=(3, 2)))["debt0"] == 22


def test_senior_notes_whose_parts_do_not_sum_to_the_total_are_not_read():
    e = refusal(base, senior_facts(nc=(10, 10), cur=(2, 1)))
    assert e.code == "debt_unavailable"


def test_a_senior_total_with_no_non_current_part_cannot_be_checked_and_is_not_read():
    f = senior_facts()
    f.pop("debt_senior_noncurrent")
    assert refusal(base, f).code == "debt_unavailable"


def test_a_current_part_not_filed_is_none_and_the_non_current_part_must_equal_the_total():
    assert base(senior_facts(cur=None, nc=(20, 20)))["debt0"] == 20
    assert refusal(base, senior_facts(cur=None, nc=(18, 19))).code == "debt_unavailable"


def test_the_sum_is_checked_to_the_rounding_of_the_filed_figures():
    m = lambda *v: {"debt_senior_total": series([v[0] * M]), "debt_senior_noncurrent": series([v[1] * M]), "debt_senior_current": series([v[2] * M])}  # noqa: E731
    assert inputs.senior_debt(m(2714, 2296, 419), ENDS[-1])[0] == 2714 * M              # 2,715 against 2,714: millions, three figures: 1.5 million allowed
    assert inputs.senior_debt(m(2714, 2296, 421), ENDS[-1]) == (None, None)             # 2 million off
    exact = {"debt_senior_total": series([2714000000.0]), "debt_senior_noncurrent": series([2296000000.0]), "debt_senior_current": series([418000001.0])}
    assert inputs.senior_debt(exact, ENDS[-1])[0] == 2714000000.0                       # printed to the dollar: 1 dollar apart is inside 1.5 dollars
    off = {"debt_senior_total": series([2714000007.0]), "debt_senior_noncurrent": series([2296000000.0]), "debt_senior_current": series([418000001.0])}
    assert inputs.senior_debt(off, ENDS[-1]) == (None, None)


def test_a_company_with_a_debt_tag_is_unchanged_by_senior_notes_tags():
    plain = base()
    other = base(ti.facts(debt_senior_total=series([99, 99]), debt_senior_noncurrent=series([99, 99])))
    assert other == plain


def test_a_company_whose_old_path_passed_without_a_debt_tag_is_unchanged():
    f = senior_facts(cash=series([5, 5, 5, 6, 200]))                                  # interest 1 / 0.01 = 100 <= cash 200: no_debt_filed, as before
    g = {k: v for k, v in f.items() if not k.startswith("debt_senior")}
    assert base(f) == base(g) and "no_debt_filed" in base(f)["stamps"]


# ---- cash interest: the gross tag, and the interest of a derived operating income ----------------------------------------------------------

def test_gross_interest_paid_is_read_only_after_the_listed_tags():
    d = doc(Revenues=("USD", rows([100, 110, 120])), InterestPaid=("USD", rows([5, 6, 7])), InterestPaidNet=("USD", rows([4, 4, 4])))
    assert facts.annual_facts(d, subs(), T)["interest_paid"]["tags"] == ["InterestPaidNet"]
    d = doc(Revenues=("USD", rows([100, 110, 120])), InterestPaid=("USD", rows([5, 6, 7])))
    assert facts.annual_facts(d, subs(), T)["interest_paid"]["tags"] == ["InterestPaid"]


def no_oi(**over):
    f = no_interest(**over)
    f.pop("operating_income")
    return f


def test_cash_interest_supplies_the_interest_of_a_derived_operating_income_and_is_labelled():
    b = base(no_oi(interest_paid=one(1.0, "InterestPaid")))
    assert b["oi0"] == pytest.approx(13 + 1.0) and "oi_interest_from_cash_interest_paid" in b["stamps"]
    assert b["substitutes"] == ["substitute:interest_expense:us-gaap:InterestPaid"]          # the later debt block names the same figure once
    assert b["kd"] == pytest.approx(1 / 20)


def test_without_cash_interest_the_derived_operating_income_still_refuses():
    assert refusal(base, no_oi()).code == "bridge_unavailable"


def test_a_gross_interest_filed_for_the_base_year_is_never_replaced():
    f = ti.facts(interest_paid=one(9.0, "InterestPaid"))
    f.pop("operating_income")
    b = base(f)
    assert b["oi0"] == pytest.approx(13 + 1.0) and "oi_interest_from_cash_interest_paid" not in b["stamps"]


# ---- an unclassified balance sheet, every family ---------------------------------------------------------------------------------------

def unclassified(totals=True, **over):
    f = ti.facts(**over)
    f.pop("assets_current"), f.pop("liabilities_current")
    if totals:
        f["assets_total"], f["liabilities_total"] = series([0, 0, 0, 0, 90]), series([0, 0, 0, 0, 50])
    return f


def test_an_unclassified_balance_sheet_gives_working_capital_zero_for_every_family_and_says_so():
    b = base(unclassified())
    assert b["w"] == 0.0 and "nwc_not_classified_taken_as_0" in b["stamps"] and "working_capital_unclassified_balance_sheet" in b["stamps"]


def test_without_total_assets_and_liabilities_the_balance_sheet_is_a_missing_statement():
    assert refusal(base, unclassified(totals=False)).code == "input_missing"
    f = unclassified()
    f.pop("liabilities_total")
    assert refusal(base, f).code == "input_missing"


def test_one_current_item_filed_still_refuses():
    f = unclassified()
    f["assets_current"] = series([30, 30, 30, 30, 32])
    assert refusal(base, f).code == "input_missing"


def test_real_estate_keeps_its_rule_without_totals_and_a_classified_sheet_is_unchanged():
    b = inputs.base(unclassified(totals=False), market_cap=180.0, bill_rate=ti.BILL, real_estate=True)
    assert b["w"] == 0.0 and "working_capital_unclassified_balance_sheet" in b["stamps"]
    assert "working_capital_unclassified_balance_sheet" not in base()["stamps"] and base()["w"] != 0.0
    plain = ti.facts(assets_total=series([0, 0, 0, 0, 90]), liabilities_total=series([0, 0, 0, 0, 50]))
    assert base(plain) == base()


# ---- partnership units with per-unit EPS -----------------------------------------------------------------------------------------------

def lp_facts(units=10.0, epu=1.04, **over):
    f = ti.facts(**over)
    f.pop("diluted_shares")
    f["lp_units_diluted"] = {"values": [{"end": ENDS[-1], "value": units, "tag": "T", "form": "10-K"}]}
    if epu is not None:
        f["eps_lp_diluted"] = {"values": [{"end": ENDS[-1], "value": epu, "tag": "T", "form": "10-K"}]}
    return f


def test_partnership_units_are_the_diluted_count_when_they_reconcile_with_the_per_unit_eps():
    b = base(lp_facts())
    assert b["shares"] == 10.0 and "shares_from_partnership_units_reconciled_with_per_unit_eps" in b["stamps"]
    assert "shares_weighted_average_diluted" in b["stamps"]


def test_units_that_do_not_reconcile_are_not_used():
    e = refusal(base, lp_facts(epu=2.0))
    assert e.code == "shares_unavailable" and "partnership units" in str(e)


def test_units_without_a_per_unit_eps_are_not_used():
    assert refusal(base, lp_facts(epu=None)).code == "shares_unavailable"


def test_a_filed_diluted_count_is_never_replaced_by_units():
    f = ti.facts(lp_units_diluted={"values": [{"end": ENDS[-1], "value": 3.0, "tag": "T"}]}, eps_lp_diluted={"values": [{"end": ENDS[-1], "value": 3.47, "tag": "T"}]})
    assert base(f) == base()


# ---- redeemable noncontrolling interest income -------------------------------------------------------------------------------------------

def nci_doc(eps_last, plain_nci=None):
    t = dict(Revenues=("USD", rows([100, 110, 120])), ProfitLoss=("USD", rows([100, 110, -30])),
             EarningsPerShareDiluted=("USD/shares", rows([1.0, 1.1, eps_last])), WeightedAverageNumberOfDilutedSharesOutstanding=("shares", rows([100, 100, 100])),
             NetIncomeLossAttributableToRedeemableNoncontrollingInterest=("USD", rows([10, 10, 68])))
    if plain_nci is not None:
        t["NetIncomeLossAttributableToNoncontrollingInterest"] = ("USD", rows(plain_nci))
    return doc(**t)


def test_redeemable_nci_income_is_taken_out_where_that_is_what_reconciles_with_eps_and_joins_the_nci_series():
    out = facts.annual_facts(nci_doc(-0.98), subs(), T)
    last = out["net_income"]["values"][-1]
    assert last["value"] == pytest.approx(-98) and last["stamp"] == "profitloss_less_redeemable_nci"
    assert [v["value"] for v in out["net_income"]["values"][:2]] == [100, 110]                  # the plain basis fits there: untouched
    nci = out["nci_income"]["values"]
    assert [(v["end"], v["value"]) for v in nci] == [("2025-12-31", 68)] and "nci_income_includes_redeemable_nci" in nci[0]["stamp"]


def test_redeemable_nci_that_does_not_reconcile_is_not_used():
    out = facts.annual_facts(nci_doc(-0.50), subs(), T)
    assert out["net_income"]["values"][-1]["stamp"] == "profitloss_basis_unverified" and "nci_income" not in out


def test_redeemable_nci_is_added_to_the_plain_nci_where_both_are_needed():
    out = facts.annual_facts(nci_doc(-0.98 - 0.02, plain_nci=[1, 1, 2]), subs(), T)
    assert out["net_income"]["values"][-1]["stamp"] == "profitloss_less_nci_and_redeemable_nci"
    assert out["nci_income"]["values"][-1]["value"] == pytest.approx(70)


def test_a_company_whose_profitloss_basis_already_reconciles_ignores_the_redeemable_tag():
    d = nci_doc(-0.30)                                                                           # -30 / 100: ProfitLoss as attributable fits
    out = facts.annual_facts(d, subs(), T)
    assert out["net_income"]["values"][-1]["stamp"] == "profitloss_as_attributable" and "nci_income" not in out


# ---- pretax income derived from net income, NCI income and the tax provision --------------------------------------------------------------

def pt_doc(pretax=None, nci=None, tax=(10, 12, 14), extra=None, ends=Y3):
    t = dict(Revenues=("USD", rows([100, 110, 120])), NetIncomeLoss=("USD", rows([50, 60, 70])))
    if pretax:
        t["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"] = ("USD", rows(pretax[1], pretax[0]))
    if nci:
        t["NetIncomeLossAttributableToNoncontrollingInterest"] = ("USD", rows(nci[1], nci[0]))
    if tax:
        t["IncomeTaxExpenseBenefit"] = ("USD", rows(tax))
    t.update(extra or {})
    return doc(**t)


def pretax(out):
    return {v["end"]: (v["value"], v.get("stamp")) for v in out["pretax_income"]["values"]}


def test_pretax_is_derived_where_its_tag_is_absent_and_the_year_is_stamped():
    out = facts.annual_facts(pt_doc(nci=(Y3, [1, 1, 1])), subs(), T)
    assert pretax(out) == {e: (v, "pretax_derived_from_net_income_nci_tax") for e, v in zip(Y3, [61, 73, 85])} and "pretax_income" not in out["_stale"]


def test_pretax_is_derived_only_for_the_years_after_a_stale_tag():
    out = facts.annual_facts(pt_doc(pretax=(Y3[:1], [60]), nci=(Y3, [1, 1, 1])), subs(), T)
    assert pretax(out) == {Y3[0]: (60, None), Y3[1]: (73, "pretax_derived_from_net_income_nci_tax"), Y3[2]: (85, "pretax_derived_from_net_income_nci_tax")}


def test_a_filed_pretax_tag_that_reaches_the_latest_year_is_never_replaced():
    out = facts.annual_facts(pt_doc(pretax=(Y3, [55, 66, 77]), nci=(Y3, [1, 1, 1])), subs(), T)
    assert {e: v for e, (v, s) in pretax(out).items()} == dict(zip(Y3, [55, 66, 77])) and all(s is None for _, s in pretax(out).values())


def test_a_year_with_a_discontinued_operation_is_not_derived():
    d = pt_doc(nci=(Y3, [1, 1, 1]), extra={"IncomeLossFromDiscontinuedOperationsNetOfTax": ("USD", rows([0, 0, 5]))})
    out = facts.annual_facts(d, subs(), T)
    assert set(pretax(out)) == set(Y3[:2]) and out["_stale"]["pretax_income"] == Y3[1]          # a filed 0 is no operation; the 5 is


def test_a_year_without_a_filed_provision_is_not_derived():
    d = pt_doc(nci=(Y3, [1, 1, 1]), tax=None, extra={"CurrentIncomeTaxExpenseBenefit": ("USD", rows([8, 9, 10]))})          # income tax is reported, the provision tag is not
    assert "pretax_income" not in facts.annual_facts(d, subs(), T)


def test_consolidated_profit_stands_in_for_net_income_plus_nci_where_nci_is_not_filed_for_the_year():
    d = pt_doc(nci=(Y3[:2], [1, 1]), extra={"ProfitLoss": ("USD", rows([51, 61, 68.5]))})
    out = facts.annual_facts(d, subs(), T)
    assert pretax(out)[Y3[2]][0] == pytest.approx(68.5 + 14)


def test_nci_filed_for_other_years_but_not_this_one_and_no_consolidated_profit_is_not_derived():
    out = facts.annual_facts(pt_doc(nci=(Y3[:2], [1, 1])), subs(), T)
    assert set(pretax(out)) == set(Y3[:2])


def test_no_nci_filed_anywhere_means_none_is_attributed():
    out = facts.annual_facts(pt_doc(), subs(), T)
    assert [v for v, _ in pretax(out).values()] == [60, 72, 84]


def test_the_base_carries_the_derived_pretax_flag():
    f = ti.facts()
    f["pretax_income"]["values"][-1]["stamp"] = "pretax_derived_from_net_income_nci_tax"
    assert "pretax_derived_from_net_income_nci_tax" in base(f)["stamps"] and "pretax_derived_from_net_income_nci_tax" not in base()["stamps"]


# ---- preferred stock: a filed zero is a value, and dividends none where EPS x shares reconciles ------------------------------------------

def ser(by_year, scale=M):
    return {"values": [{"end": f"{y}-12-31", "value": v * scale, "tag": "T", "form": "10-K", "accn": f"0001-{str(y)[2:]}-000010"} for y, v in by_year.items()]}


def pref_facts(carry, pdiv=None, nic=None, eps=None):
    f = bank_facts()
    f["preferred_equity"] = ser(carry)
    for key, m in (("preferred_dividends", pdiv), ("ni_common", nic)):
        if m is not None:
            f[key] = ser(m)
    if eps is not None:
        f["eps_diluted"] = ser(eps, scale=1.0)
    return f


LAST = "2025-12-31"
FIVE = {2020: 10, 2021: 10, 2022: 10, 2023: 10, 2024: 10}
DIV4 = {2021: 0.5, 2022: 0.5, 2023: 0.5, 2024: 0.5}


def test_a_preferred_balance_filed_as_zero_counts_as_filed():
    b = inputs.base_financial(pref_facts({**FIVE, 2025: 0}, pdiv={**DIV4, 2025: 0.0}))
    assert b["record"]["preferred"][LAST] == 0.0 and b["e0"] == pytest.approx(12.8 * M)


def test_after_a_filed_zero_a_year_with_no_balance_is_zero_when_its_dividends_are_filed_as_zero():
    b = inputs.base_financial(pref_facts({**FIVE, 2024: 0}, pdiv={**DIV4, 2025: 0.0}))
    assert b["record"]["preferred"][LAST] == 0.0 and f"preferred_balance_not_filed_taken_as_0:{LAST}" in b["stamps"]


def test_after_a_filed_zero_a_year_with_no_balance_is_zero_when_income_to_common_equals_net_income():
    f = pref_facts({**FIVE, 2024: 0}, pdiv=DIV4, nic={2021: 9.5, 2022: 10, 2023: 11, 2024: 11.5, 2025: 12.8})
    assert inputs.base_financial(f)["e0"] == pytest.approx(12.8 * M)
    f = pref_facts({**FIVE, 2024: 0}, pdiv=DIV4, nic={2021: 9.5, 2022: 10, 2023: 11, 2024: 11.5, 2025: 12.0})              # 0.8 apart: not equal
    assert refusal(inputs.base_financial, f).code == "preferred_series_incomplete"


def test_a_missing_balance_with_dividends_still_paid_is_still_refused():
    assert refusal(inputs.base_financial, pref_facts({**FIVE, 2024: 0}, pdiv={**DIV4, 2025: 0.3})).code == "preferred_series_incomplete"


def test_a_missing_balance_that_never_followed_a_filed_zero_is_still_refused():
    assert refusal(inputs.base_financial, pref_facts(FIVE, pdiv={**DIV4, 2025: 0.0})).code == "preferred_series_incomplete"


def test_a_zero_before_the_first_preferred_changes_nothing():
    f = pref_facts({2020: 0, 2021: 0, 2022: 0, 2023: 10, 2024: 10, 2025: 10}, pdiv={2023: 0.5, 2024: 0.5, 2025: 0.5})
    b = inputs.base_financial(f)
    assert "preferred_first_filed:2023-12-31" in b["stamps"] and not any(s.startswith("preferred_balance_not_filed") for s in b["stamps"])


EPS5 = {2021: 1.0, 2022: 1.05, 2023: 1.15, 2024: 1.2, 2025: 1.28}


def test_dividends_not_filed_are_none_where_eps_times_shares_reconciles_and_every_such_year_is_flagged():
    b = inputs.base_financial(pref_facts({**FIVE, 2025: 10}, eps=EPS5))
    assert b["e0"] == pytest.approx(12.8 * M)
    assert [s for s in b["stamps"] if s.startswith("preferred_dividends_taken_as_0")] == [
        f"preferred_dividends_taken_as_0_eps_times_shares_reconciles:{y}-12-31" for y in range(2021, 2026)]


def test_dividends_not_filed_and_eps_that_does_not_reconcile_stay_refused():
    assert refusal(inputs.base_financial, pref_facts({**FIVE, 2025: 10}, eps={**EPS5, 2023: 0.9})).code == "preferred_dividends_unavailable"
    assert refusal(inputs.base_financial, pref_facts({**FIVE, 2025: 10})).code == "preferred_dividends_unavailable"


def test_filed_dividends_are_never_second_guessed_by_eps():
    f = pref_facts({**FIVE, 2025: 10}, pdiv={**DIV4, 2025: 0.5}, eps=EPS5)
    b = inputs.base_financial(f)
    assert b["e0"] == pytest.approx(12.3 * M) and not any(s.startswith("preferred_dividends_taken_as_0") for s in b["stamps"])


# ---- the side finding: no EPS to prove the share count ---------------------------------------------------------------------------------------

def test_no_eps_leaves_the_stamp_and_the_count_is_still_used():
    f = ti.facts()
    f.pop("eps_diluted")
    b = base(f)
    assert "shares_unreconciled_no_eps" in b["stamps"] and b["shares"] == 10
