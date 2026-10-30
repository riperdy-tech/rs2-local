"""WO_Q5 part 1 (SPEC_m3q §2, V8): qwen_c/value/inputs.py on hand-built facts."""
import pytest

from qwen_c.value import desk, inputs

ENDS = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]


def series(vals, tag="T"):
    return {"values": [{"end": e, "value": v, "tag": tag} for e, v in zip(ENDS[-len(vals):], vals)]}


def facts(**over):
    f = {"revenue": series([80, 85, 90, 95, 100]), "operating_income": series([12, 13, 14, 15, 16]),
         "net_income": series([8, 8.5, 9, 9.5, 10]), "pretax_income": series([10, 11, 12, 12.5, 13]),
         "tax_provision": series([2, 2.2, 2.4, 2.5, 2.6]), "da": series([4, 4.2, 4.5, 4.7, 5]), "capex": series([5, 5, 5.5, 6, 6]),
         "amortization": series([1, 1, 1, 1, 1]), "interest_expense": series([1, 1, 1, 1, 1]), "diluted_shares": series([10, 10, 10, 10, 10]),
         "assets_current": series([30, 30, 30, 30, 32]), "liabilities_current": series([20, 20, 20, 20, 21]), "cash": series([5, 5, 5, 6, 7]),
         "debt_current": series([1, 1, 1, 1, 1]), "debt_noncurrent": series([19, 19, 19, 19, 19]), "equity": series([40, 41, 42, 44, 46]),
         "amort_next_1": series([1.0]), "amort_next_2": series([1.0]), "amort_next_3": series([0.8]), "amort_next_4": series([0.5]),
         "amort_next_5": series([0.5]), "amort_after_5": series([2.0]), "_absent": {}, "_stale": {}}
    f.update(over)
    return f


def test_base_measures_every_input():
    b = inputs.base(facts(), market_cap=180.0)
    tau = 2.6 / 13
    assert b["tau"] == pytest.approx(tau) and "tax_rate_measured" in b["stamps"]
    assert b["x0"] == pytest.approx(10 + 1 * (1 - tau))
    assert b["d_ratio"] == pytest.approx(sum(d - 1 for d in [4, 4.2, 4.5, 4.7, 5]) / 450)
    assert b["c_ratio"] == pytest.approx(27.5 / 450)
    assert b["w"] == pytest.approx(((32 - 7) - (21 - 1)) / 100)
    assert b["ronic0"] == pytest.approx((b["x0"] + 1 * (1 - tau)) / (44 + 20 - 6))
    assert b["delta"] == pytest.approx(20 / 200) and b["kd"] == pytest.approx(1 / 20)
    assert b["amort_schedule"] == [1.0, 1.0, 0.8, 0.5, 0.5] and b["amort_thereafter"] == 2.0
    assert b["shares"] == 10 and b["excess_cash"] == 7


def test_tax_out_of_band_uses_the_median_then_refuses():
    f = facts(tax_provision=series([2, 2.2, 2.4, 2.5, 6.0]))           # latest 46%
    b = inputs.base(f, market_cap=180.0)
    assert "tax_rate_multi_year_median" in b["stamps"] and b["tau"] == pytest.approx(sorted([0.2, 0.2, 0.2, 0.2])[1])
    f = facts(tax_provision=series([5, 5, 6, 6, 6.0]), pretax_income=series([10, 10, 10, 10, 10]))
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(f, market_cap=180.0)
    assert e.value.code == "tax_unavailable"


def test_zero_tax_is_a_measured_value():
    b = inputs.base(facts(tax_provision=series([0, 0, 0, 0, 0.0])), market_cap=180.0)
    assert b["tau"] == 0.0 and "tax_rate_measured" in b["stamps"]


def test_unfiled_schedule_is_a_consistent_zero():
    f = facts()
    del f["amort_next_3"]
    b = inputs.base(f, market_cap=180.0)
    assert b["x0"] == 10 and b["amort_schedule"] == [0.0] * 5 and "amortization_schedule_not_filed" in b["stamps"]
    assert b["d_ratio"] == pytest.approx(sum([4, 4.2, 4.5, 4.7, 5]) / 450)


def test_schedule_without_the_years_amortization_takes_no_add_back():
    f = facts(amortization={"values": [{"end": e, "value": 1} for e in ENDS[:-1]]})   # no amortization filed for the base year
    b = inputs.base(f, market_cap=180.0)
    assert b["x0"] == 10 and "amortization_schedule_not_filed" in b["stamps"]


@pytest.mark.parametrize("over,code", [
    ({"_stale": {"net_income": "2013-12-31"}}, "facts_stale"),
    ({"net_income": series([-8, -8, -9, -9, -12])}, "e0_not_positive"),
    ({"revenue": series([95, 100])}, "history_short"),
    ({"diluted_shares": {"values": [{"end": e, "value": 10} for e in ENDS[:-1]]}}, "shares_unavailable"),
])
def test_refusals_by_name(over, code):
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(facts(**over), market_cap=180.0)
    assert e.value.code == code


def test_market_cap_required():
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(facts(), market_cap=None)
    assert e.value.code == "market_cap_unavailable"


def test_bridge_reproduces_the_base_year_and_holds_k0_flat():
    b = inputs.base(facts(), market_cap=180.0)
    x = inputs.bridge_x_margin(b, [0.16], [100.0])[0]
    assert x == pytest.approx(b["m0"])                                  # op_0 at R_0 returns X_0
    k0 = 16 - b["x0"] / (1 - b["tau"])
    assert inputs.bridge_x_margin(b, [0.20], [200.0])[0] == pytest.approx((0.20 * 200 - k0) * (1 - b["tau"]) / 200)


def test_depreciation_only_tag_is_not_reduced_by_amortization():
    b = inputs.base(facts(da=series([3, 3.2, 3.5, 3.7, 4], tag="Depreciation")), market_cap=180.0)
    assert b["d_ratio"] == pytest.approx(sum([3, 3.2, 3.5, 3.7, 4]) / 450)
