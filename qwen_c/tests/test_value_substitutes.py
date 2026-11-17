"""WO_NC1: labelled fact substitutes (revenue, period-end shares, interest) in qwen_c/value, on hand-built synthetic facts.
A substitute is consulted only after every exact tag failed, is stamped substitute:<concept>:<taxonomy>:<tag>, and the checks that
guard the exact figure (EPS reconciliation of the share count, the kd band) still run on it."""
import pytest

from qwen_c.tests import test_value_inputs as ti
from qwen_c.tests.test_value_facts import T, cf, fy, subs
from qwen_c.tests.test_value_inputs import ENDS, base, series
from qwen_c.value import desk, facts, inputs

STAMP_REV = "substitute:revenue:ifrs-full:RevenueFromRenderingOfServices"


# ---- revenue ----------------------------------------------------------------------------------------------------------------------

def ifrs(tag, rows):
    return {"ifrs-full": {tag: {"units": {"USD": rows}}}}


def lines(vals, ends=("2023-12-31", "2024-12-31", "2025-12-31")):
    return [fy(e, v, "0001-26-000010") for e, v in zip(ends, vals)]


def doc(*parts):
    f = {}
    for p in parts:
        for tax, d in p.items():
            f.setdefault(tax, {}).update(d)
    return {"facts": f}


def test_revenue_substitute_is_the_largest_line_of_one_tag_and_stamped():
    d = doc(ifrs("RevenueFromRenderingOfServices", lines([10, 20, 30])), ifrs("RevenueFromSaleOfGoods", lines([1, 2, 3])))
    out = facts.annual_facts(d, subs(), T, substitute_revenue=True)
    r = out["revenue"]
    assert r["tags"] == ["RevenueFromRenderingOfServices"] and [v["value"] for v in r["values"]] == [10.0, 20.0, 30.0]
    assert all(v["stamp"] == STAMP_REV for v in r["values"]) and "revenue" not in out["_absent"]


def test_revenue_substitute_never_mixes_tags_across_years():
    # the goods line is larger in an older year and has a year the services line lacks; the choice is by the latest year, one tag throughout
    d = doc(ifrs("RevenueFromRenderingOfServices", lines([10, 30], ends=("2024-12-31", "2025-12-31"))),
            ifrs("RevenueFromSaleOfGoods", lines([99, 5, 6])))
    r = facts.annual_facts(d, subs(), T, substitute_revenue=True)["revenue"]
    assert {v["tag"] for v in r["values"]} == {"RevenueFromRenderingOfServices"} and [v["end"] for v in r["values"]] == ["2024-12-31", "2025-12-31"]


def test_a_tag_that_stopped_years_ago_does_not_win_on_size():
    d = doc(ifrs("RevenueFromSaleOfGold", lines([500], ends=("2020-12-31",))), ifrs("RevenueFromSaleOfGoods", lines([1, 2, 3])))
    assert facts.annual_facts(d, subs(), T, substitute_revenue=True)["revenue"]["tags"] == ["RevenueFromSaleOfGoods"]


def test_exact_revenue_wins_and_no_substitute_is_consulted():
    d = doc(cf(lines([100, 110, 120]))["facts"], ifrs("RevenueFromSaleOfGoods", lines([1, 2, 3])))
    out = facts.annual_facts(d, subs(), T, substitute_revenue=True)
    assert out["revenue"]["tags"] == ["Revenues"] and not any(v.get("stamp") for v in out["revenue"]["values"])
    assert out == facts.annual_facts(d, subs(), T)                                   # the flag changes nothing where an exact tag resolves


def test_revenue_substitute_is_off_by_default_and_a_name_without_any_line_stays_absent():
    d = doc(ifrs("RevenueFromRenderingOfServices", lines([10, 20, 30])))
    off = facts.annual_facts(d, subs(), T)
    assert "revenue" not in off and "revenue" in off["_absent"]
    assert "revenue" not in facts.annual_facts(doc(ifrs("Unrelated", lines([1, 2, 3]))), subs(), T, substitute_revenue=True)


def test_inputs_carry_the_revenue_stamp_to_the_base():
    f = ti.facts()
    f["revenue"] = {"values": [dict(v, stamp=STAMP_REV) for v in f["revenue"]["values"]]}
    b = base(f)
    assert STAMP_REV in b["stamps"] and b["substitutes"] == [STAMP_REV]
    assert "substitutes" not in base() and not any(s.startswith("substitute:") for s in base()["stamps"])


def test_prepare_substitutes_revenue_on_the_operating_route_only(monkeypatch):
    from qwen_c.value import run
    seen = []

    def build(*a, **k):
        seen.append(k.get("substitute_revenue"))
        raise desk.DeskRefusal("history_short", "x")
    monkeypatch.setattr(facts, "build", build)
    for fam in ("operating", "commodity", "financial"):
        with pytest.raises(desk.DeskRefusal):
            run.prepare({"decision_time_utc": "2026-03-01T13:00:00Z"}, "1", "S", 1.0, online=False, family=fam)
    assert seen == [True, True, False]


# ---- diluted shares ---------------------------------------------------------------------------------------------------------------

def no_diluted(**over):
    f = ti.facts(**over)
    f["diluted_shares"] = {"values": [v for v in f["diluted_shares"]["values"] if v["end"] != ENDS[-1]]}
    return f


def period_end(value, tag="CommonStockSharesOutstanding", end=ENDS[-1]):
    return {"values": [{"end": end, "value": value, "tag": tag, "form": "10-K"}]}


def test_period_end_shares_stand_in_when_no_diluted_count_is_filed_and_reconcile_with_eps():
    b = base(no_diluted(shares_period_end=period_end(10.0)))
    lab = "substitute:diluted_shares:us-gaap:CommonStockSharesOutstanding"
    assert b["shares"] == 10.0 and lab in b["stamps"] and b["substitutes"] == [lab]
    assert "shares_period_end_not_weighted_average" in b["stamps"] and "shares_weighted_average_diluted" not in b["stamps"]


def test_ifrs_period_end_tag_is_named_by_its_taxonomy():
    assert base(no_diluted(shares_period_end=period_end(10.0, tag="NumberOfSharesOutstanding")))["substitutes"] == [
        "substitute:diluted_shares:ifrs-full:NumberOfSharesOutstanding"]


def test_exact_diluted_shares_win_over_a_substitute():
    b = base(ti.facts(shares_period_end=period_end(11.0)))
    assert "substitutes" not in b and "shares_weighted_average_diluted" in b["stamps"] and b["shares"] == 10
    assert b == base()


def test_a_substitute_count_that_fails_the_eps_reconciliation_is_refused_even_for_an_ads_filer():
    for form in ("10-K", "20-F"):
        f = no_diluted(shares_period_end=period_end(7.0))
        f["revenue"] = {"values": [dict(v, form=form) for v in f["revenue"]["values"]]}
        with pytest.raises(desk.DeskRefusal) as e:
            base(f)
        assert e.value.code == "shares_scale_unverified"


def test_a_substitute_count_needs_a_filed_diluted_eps():
    f = no_diluted(shares_period_end=period_end(10.0))
    del f["eps_diluted"]
    with pytest.raises(desk.DeskRefusal) as e:
        base(f)
    assert e.value.code == "shares_unavailable"


def test_cover_page_count_counts_only_within_120_days_after_the_year_end():
    def cover(end):
        return {"values": [{"end": end, "value": 10.0, "tag": "EntityCommonStockSharesOutstanding", "form": "10-K"}]}
    assert base(no_diluted(shares_cover=cover("2026-04-30")))["substitutes"] == ["substitute:diluted_shares:dei:EntityCommonStockSharesOutstanding"]
    for late in ("2026-05-01", "2025-12-31", "2025-12-01"):                  # 121 days, the year end itself, before it
        with pytest.raises(desk.DeskRefusal) as e:
            base(no_diluted(shares_cover=cover(late)))
        assert e.value.code == "shares_unavailable"


def test_period_end_count_is_preferred_to_the_cover_page_and_zero_is_not_a_count():
    cov = {"values": [{"end": "2026-02-20", "value": 99.0, "tag": "EntityCommonStockSharesOutstanding", "form": "10-K"}]}
    assert base(no_diluted(shares_period_end=period_end(10.0), shares_cover=cov))["shares"] == 10.0
    with pytest.raises(desk.DeskRefusal) as e:
        base(no_diluted(shares_period_end=period_end(0.0)))
    assert e.value.code == "shares_unavailable"
    with pytest.raises(desk.DeskRefusal):                                    # a filed zero diluted count is a value, not an absence
        base(ti.facts(diluted_shares=series([10, 10, 10, 10, 0]), shares_period_end=period_end(10.0)))


def test_financial_base_takes_the_same_substitute():
    b = inputs.base_financial(no_diluted(shares_period_end=period_end(10.0)))
    lab = "substitute:diluted_shares:us-gaap:CommonStockSharesOutstanding"
    assert b["shares"] == 10.0 and b["substitutes"] == [lab] and lab in b["stamps"] and "shares_weighted_average_diluted" not in b["stamps"]
    assert "substitutes" not in inputs.base_financial(ti.facts())


# ---- interest expense -------------------------------------------------------------------------------------------------------------

def no_interest(**over):
    f = ti.facts(**over)
    f["interest_expense"] = {"values": [v for v in f["interest_expense"]["values"] if v["end"] != ENDS[-1]]}
    return f


def one(value, tag):
    return {"values": [{"end": ENDS[-1], "value": value, "tag": tag, "form": "10-K"}]}


def test_interest_paid_stands_in_for_a_missing_interest_expense_and_is_stamped():
    b = base(no_interest(interest_paid=one(1.0, "InterestPaidNet")))
    lab = "substitute:interest_expense:us-gaap:InterestPaidNet"
    assert lab in b["stamps"] and b["substitutes"] == [lab]
    assert b["kd"] == pytest.approx(1.0 / 20) and b["k0_interest"] == 1.0
    assert b["ronic0"] == pytest.approx(base()["ronic0"])                    # the same interest as the exact fixture's FY0 value


def test_an_ifrs_interest_paid_tag_is_named_by_its_taxonomy():
    b = base(no_interest(interest_paid=one(1.0, "InterestPaidClassifiedAsFinancingActivities")))
    assert b["substitutes"] == ["substitute:interest_expense:ifrs-full:InterestPaidClassifiedAsFinancingActivities"] and b["kd"] == pytest.approx(0.05)


def test_cash_interest_paid_that_is_not_positive_is_no_substitute():
    with pytest.raises(desk.DeskRefusal) as e:
        base(no_interest(interest_paid=one(0.0, "InterestPaidNet")))
    assert e.value.code == "debt_without_interest"


def test_the_kd_band_still_refuses_a_substituted_interest():
    for v in (8.0, 0.1):
        with pytest.raises(desk.DeskRefusal) as e:
            base(no_interest(interest_paid=one(v, "InterestPaidNet")))
        assert e.value.code == "kd_out_of_band"


def test_exact_interest_wins_and_a_filed_zero_or_no_excess_debt_is_unchanged():
    exact = base(ti.facts(interest_paid=one(5.0, "InterestPaidNet")))
    assert "substitutes" not in exact and exact["kd"] == pytest.approx(0.05)
    zero = ti.facts(interest_paid=one(1.0, "InterestPaidNet"))
    zero["interest_expense"] = series([1, 1, 1, 1, 0])
    with pytest.raises(desk.DeskRefusal) as e:                              # a filed 0 is a value: the refusal as before
        base(zero)
    assert e.value.code == "debt_without_interest"
    b = base(no_interest(interest_paid=one(1.0, "InterestPaidNet"), cash=series([5, 5, 5, 6, 40])))       # debt 20 <= cash 40
    assert "kd_unused_delta_zero" in b["stamps"] and "substitutes" not in b


def test_without_any_substitute_the_refusal_keeps_its_code():
    with pytest.raises(desk.DeskRefusal) as e:
        base(no_interest())
    assert e.value.code == "debt_without_interest"


def test_the_new_concepts_are_auxiliary_and_never_named_stale():
    d = doc(cf(lines([100, 110, 120]))["facts"], {"us-gaap": {"InterestPaidNet": {"units": {"USD": lines([1], ends=("2023-12-31",))}}}})
    out = facts.annual_facts(d, subs(), T)
    assert "interest_paid" not in out["_stale"] and out["interest_paid"]["values"][0]["tag"] == "InterestPaidNet"
