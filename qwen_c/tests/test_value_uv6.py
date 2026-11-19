"""Finance-lease liabilities as the debt of a company with no other borrowing (2026-11-19), on synthetic facts only: the accepted readings,
the readings a filed part contradicts (the old refusal stands), and that a company with a debt tag is unchanged."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_inputs import base, series
from qwen_c.tests.test_value_uv2 import refusal


def lease_facts(**lease):
    f = ti.facts()
    f.pop("debt_current"), f.pop("debt_noncurrent")
    for k, v in lease.items():
        f[f"finance_lease_{k}"] = series(list(v))
    return f


def test_the_filed_finance_lease_total_is_the_debt_where_no_debt_tag_resolves():
    b = base(lease_facts(total=(20, 20), noncurrent=(18, 19), current=(2, 1)))
    assert b["debt0"] == 20 and b["debt_basis"] == "FinanceLeaseLiability" and b["kd"] == pytest.approx(1 / 20)
    assert "debt_from_finance_lease_liability" in b["stamps"]


def test_without_a_total_the_present_value_of_the_filed_payments_is_the_debt():
    b = base(lease_facts(payments_due=(22, 23), undiscounted_excess=(2, 3), noncurrent=(12, 11)))
    assert b["debt0"] == 20 and b["debt_basis"] == "FinanceLeaseLiabilityPaymentsDue-UndiscountedExcessAmount"
    assert base(lease_facts(noncurrent=(18, 19), current=(2, 1)))["debt_basis"] == "FinanceLeaseLiabilityNoncurrent+Current"


@pytest.mark.parametrize("lease", [dict(total=(20, 20), noncurrent=(10, 10), current=(2, 1)),          # the parts do not sum to the total
                                   dict(payments_due=(22, 23), undiscounted_excess=(2, 3), noncurrent=(30, 30)),   # a part above the whole
                                   dict(noncurrent=(18, 19)),                                           # one part alone is not the debt
                                   dict(payments_due=(22, 23))])                                        # undiscounted payments are not the debt
def test_a_finance_lease_figure_a_filed_part_contradicts_is_not_read(lease):
    assert refusal(base, lease_facts(**lease)).code == "debt_unavailable"


def test_a_company_with_a_debt_tag_is_unchanged_by_finance_lease_facts():
    f = ti.facts()
    f["finance_lease_total"] = series([5, 5])
    assert base(f) == base(ti.facts())


# ---- available-for-sale debt securities maturing within one year as the short-term investments -------------------------------------------

def afs_facts(within=(4, 6), total=(9, 9), sti=None):
    f = ti.facts()
    f.pop("st_investments", None)
    if sti is not None:
        f["st_investments"] = series(list(sti))
    if within is not None:
        f["afs_debt_within_one_year"] = series(list(within))
    if total is not None:
        f["afs_debt_total"] = series(list(total))
    return f


def test_afs_debt_maturing_within_one_year_is_the_short_term_investment_where_no_tag_is_filed():
    plain, b = base(afs_facts(within=None, total=None)), base(afs_facts())
    assert "st_investments_not_filed_taken_as_0" in plain["stamps"] and "st_investments_not_filed_taken_as_0" not in b["stamps"]
    assert "st_investments_from_afs_debt_maturing_within_one_year" in b["stamps"]
    assert b["excess_cash"] == plain["excess_cash"] + 6


def test_the_within_one_year_figure_is_capped_at_the_filed_total_and_a_total_alone_is_not_read():
    assert base(afs_facts(within=(4, 12)))["excess_cash"] == base(afs_facts(within=None, total=None))["excess_cash"] + 9
    assert base(afs_facts(within=None)) == base(afs_facts(within=None, total=None))


def test_a_company_with_a_short_term_investment_tag_is_unchanged_by_the_afs_figures():
    assert base(afs_facts(sti=(1, 2))) == base(afs_facts(within=None, total=None, sti=(1, 2)))
