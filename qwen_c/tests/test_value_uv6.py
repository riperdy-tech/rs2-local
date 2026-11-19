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
