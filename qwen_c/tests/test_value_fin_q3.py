"""CROSS_CHECK_Q3: each finding's bypass is a fail case here, with a pass case beside it."""
import copy

import pytest

from qwen_c.value import checks, desk, forecast, forecast_fin, inputs
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin import (ENDS, M, R, ROE21, ROE25, Y21, Y25, bank_facts, clean, ctx, reason, run_check,  # noqa: F401
                                         series)


def flags(res, key):
    return res["unsupported"].get(key, [])


# ---- 1: V3 on every explicit-year ROE, under hold and step; the operating twin
@pytest.mark.parametrize("transition", ["hold_then_linear", "step_at_year"])
def test_1_years_1_2_roe_outside_the_record_is_flagged(ctx, transition):
    out = clean()
    out["base"].update(roe=[0.60, 0.60], transition=transition, transition_year=5)
    out["base"]["normalized"]["year"] = 5
    out["bear"] = {}
    out["bull"] = {}
    out["reasons"] = [x for x in out["reasons"] if not x["input"].startswith(("bear.", "bull."))]
    res = run_check(out, ctx)
    assert res["status"] != "ok" and any("V3" in w for w in flags(res, "base.roe"))


def test_1_years_1_2_roe_inside_the_record_passes(ctx):
    res = run_check(clean(), ctx)
    assert not any("V3" in w for w in flags(res, "base.roe"))


def test_1_operating_twin_years_1_2_margin_outside_the_record_is_flagged():
    b = dict(inputs.base(OP.facts(), market_cap=180 * M, bill_rate=0.04), stub_days=0)
    bar = forecast.record_bar(b["record"]["op_margin"])
    items = {i["fact_id"]: i for i in forecast.record_items(OP.facts())}
    items.update({k: {"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in OP.ITEMS.items()})
    out = OP.clean()
    out["base"].update(op_margin=[0.60, 0.60], transition="hold_then_linear", transition_year=5)
    out["base"]["normalized"]["year"] = 5
    res = checks.check(out, items, "T", set(), b, bar, OP.R, OP.ENDS)
    assert any("V3" in w for w in flags(res, "base.op_margin"))


# ---- 2: book growth above the same year's ROE (implied issuance); TV share and implied P/B annotated
def test_2_book_growth_above_roe_needs_a_span(ctx):
    out = clean()
    out["base"]["book_growth"] = [0.12, 0.12]
    res = run_check(out, ctx)
    assert any("implied issuance" in w for w in flags(res, "base.book_growth"))


def test_2_book_growth_below_roe_is_not_issuance(ctx):
    res = run_check(clean(), ctx)
    assert not any("implied issuance" in w for w in flags(res, "base.book_growth"))
    d = res["diagnostics"]
    assert 0 < d["tv_share"] < 1 and d["implied_pb"] > 0 and d["record_neutral"]["value"] > 0


def test_2_v3g_record_is_net_of_issuance():
    f = bank_facts()
    f["equity"] = series([100, 105, 160, 166, 172, 178])          # 2022: +52% book on an ROE of 10.5% (new shares)
    b = inputs.base_financial(f)
    assert b["record"]["book_growth_max"] < 0.11


# ---- 3: the desk carries g5 (the truth fixtures reproduce to 0.01%, test_value_fin); a missing g5 is refused
def test_3_driver_book_needs_g5():
    with pytest.raises(desk.DeskRefusal) as e:
        desk.value_financial({"revenue": [100.0] * 6, "margin": [0.1] * 5, "r": 0.1, "g_T": 0.03, "F": 10, "ronic0": 0.1, "ronic_T": 0.1,
                              "m_long": 0.1, "shares": 1.0, "excess_cash": 0.0, "driver": "book"})
    assert e.value.code == "input_missing"


def test_3_year5_growth_enters_the_value(ctx):
    b, bar, _ = ctx
    sc = clean()["base"]
    v1 = forecast_fin.value(forecast_fin.assemble(sc, b, bar, r=R))
    sc2 = copy.deepcopy(sc)
    sc2["normalized"].update(year=5, book_growth=0.09)
    sc["normalized"]["year"] = 5
    v0 = forecast_fin.value(forecast_fin.assemble(sc, b, bar, r=R))
    v2 = forecast_fin.value(forecast_fin.assemble(sc2, b, bar, r=R))
    assert v2["value_per_share"] != v0["value_per_share"] and v1["value_per_share"] > 0


# ---- 4: the release lever
def test_4_book_growth_below_the_record_needs_a_span(ctx):
    out = clean()
    out["base"]["book_growth"] = [-0.5, -0.5]
    res = run_check(out, ctx)
    assert any("below the filed record" in w for w in flags(res, "base.book_growth"))
    assert any("V10" in w and "grows" in w for w in flags(res, "base.book_growth"))


def test_4_negative_terminal_growth_needs_a_span(ctx):
    out = clean()
    out["base"]["terminal_g"] = -0.02
    res = run_check(out, ctx)
    assert any("below zero" in w for w in flags(res, "base.terminal_g"))
    assert any("V10" in w for w in flags(res, "base.terminal_g"))


def test_4_growth_inside_the_record_passes(ctx):
    res = run_check(clean(), ctx)
    assert not flags(res, "base.book_growth") and not flags(res, "base.terminal_g")


# ---- 5: the operating base's data rules on the financial base
def test_5_unreconciled_profitloss_is_refused():
    f = bank_facts()
    f["net_income"]["values"][-1]["stamp"] = "profitloss_basis_unverified"
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base_financial(f)
    assert e.value.code == "profitloss_basis_unverified"


def test_5_income_per_share_must_match_filed_eps():
    f = bank_facts()
    f["eps_diluted"] = {"values": [{"end": ENDS[-1], "value": 0.88, "tag": "T", "form": "10-K"}]}   # 12.8M / 10M = 1.28, filed 0.88
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base_financial(f)
    assert e.value.code == "shares_scale_unverified"
    f["eps_diluted"]["values"][0]["value"] = 1.28
    assert "shares_unreconciled_no_eps" not in inputs.base_financial(f)["stamps"]


def test_5_staleness_on_the_routes_own_series():
    f = bank_facts()
    f["net_income"] = series([10, 10.5, 11.5, 12.0])                  # ends 2024; equity ends 2025
    f["net_income"]["values"] = [dict(v, end=e) for v, e in zip(f["net_income"]["values"], ENDS[1:5])]
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base_financial(f)
    assert e.value.code == "facts_stale"


def test_5_base_year_must_be_the_latest_annual():
    f = dict(bank_facts(), _latest_annual_period="2026-12-31")
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base_financial(f)
    assert e.value.code == "base_year_not_latest_annual"


# ---- 6: preferred stock out of book and income
def test_6_preferred_is_subtracted_from_book_and_its_dividends_from_income():
    f = bank_facts()
    f["preferred_equity"] = series([10, 10, 10, 10, 10, 10])
    f["preferred_dividends"] = series([0.5, 0.5, 0.5, 0.5, 0.5])
    b = inputs.base_financial(f)
    assert b["R1"] == pytest.approx(118 * M) and b["e0"] == pytest.approx(12.3 * M)
    assert b["roe0"] == pytest.approx(12.3 / 112) and "preferred_subtracted_at_carrying_value" in b["stamps"]
    items = forecast_fin.record_items(f, b)
    assert "common equity $118.0 million" in items[-1]["text"] and "return on opening equity 11.0%" in items[-1]["text"]


def test_6_income_to_common_is_used_when_filed():
    f = bank_facts()
    f["preferred_equity"] = series([10, 10, 10, 10, 10, 10])
    f["ni_common"] = series([9.6, 10.1, 11.1, 11.6, 12.4])
    assert inputs.base_financial(f)["e0"] == pytest.approx(12.4 * M)


def test_6_preferred_without_its_dividends_is_refused():
    f = bank_facts()
    f["preferred_equity"] = series([10, 10, 10, 10, 10, 10])
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base_financial(f)
    assert e.value.code == "preferred_dividends_unavailable"


# ---- 9: the own-value text by route; 11: AOCI stamped with its size
def test_9_input_value_text_by_route():
    out = OP.clean()
    out["base"]["normalized"]["book_growth"] = 0.37
    assert "4.0%" in checks.input_value_text(out, ("base", "normalized")) and "37.0%" not in checks.input_value_text(out, ("base", "normalized"))


def test_11_aoci_is_stamped_with_its_share_of_book():
    f = bank_facts()
    f["aoci"] = {"values": [{"end": ENDS[-1], "value": -9.6 * M, "tag": "T", "form": "10-K"}]}
    assert "aoci_in_book_not_separated:-0.075" in inputs.base_financial(f)["stamps"]


# ---- 12: explicit V4 and V10 pass cases
def test_12_v4_passes_with_a_filed_record_reason(ctx):
    assert not any("V4" in w for w in flags(run_check(clean(), ctx), "base.roe"))


def test_12_v10_passes_when_the_reason_agrees(ctx):
    assert not any("V10" in w for w in flags(run_check(clean(), ctx), "base.normalized"))
