"""CROSS_CHECK_Q3: each finding's bypass is a fail case here, with a pass case beside it (rules restated on prompt fin.v6's menus)."""
import copy

import pytest

from qwen_c.value import checks, desk, forecast_fin, inputs, menu
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin import (ENDS, M, R, Y21, Y25, bank_facts, clean, ctx, depart, grow, reverted, run_check,  # noqa: F401
                                         series)


# ---- 1: V3 on every ROE outside the filed record; the operating twin
def test_1_an_roe_outside_the_record_is_reverted_without_two_fiscal_years(ctx):
    out = depart(clean(), "long_run_roe", ("median", 0))                     # held at the median: the long run does not follow
    res = run_check(depart(out, "normalized.roe", ("p25", -3), "cycle_downturn", [Y21, Y25]), ctx)      # 0.07 < min 0.10
    assert reverted(res, "normalized.roe") == ["V3"] and res["status"] == "ok_with_reverts"


def test_1_an_roe_inside_the_record_passes(ctx):
    res = run_check(depart(clean(), "roe.y1", "last", "record_persistence", [Y25]), ctx)
    assert res["status"] == "ok" and not res["reverts"]


def test_1_operating_twin_a_margin_outside_the_record_is_reverted():
    out = OP.depart(OP.clean(), "long_run_op_margin", ("median", 0))
    res = OP.run(OP.ctx_of(), OP.depart(out, "normalized.margin", ("p25", -3), "cycle_downturn", [OP.Y21, OP.Y25]))
    assert reverted(res, "normalized.margin") == ["V3"]


# ---- 2: book growth above the same year's ROE (issuance, test_value_fin); TV share and implied P/B annotated
def test_2_tv_share_and_implied_pb_are_reported(ctx):
    d = run_check(clean(), ctx)["diagnostics"]
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
    m = menu.menus(b, bar, R, "financial")
    base = menu.neutral_base("financial")
    base["normalized"]["year"] = 5
    sc = menu.scenario(base, menu.resolve(base, {}, m), m)
    sc2 = copy.deepcopy(sc)
    sc2["normalized"]["book_growth"] = 0.09
    v0 = forecast_fin.value(forecast_fin.assemble(sc, b, bar, r=R))
    v2 = forecast_fin.value(forecast_fin.assemble(sc2, b, bar, r=R))
    assert v2["value_per_share"] != v0["value_per_share"] and v0["value_per_share"] > 0


# ---- 4: the release lever (test_value_fin: release needs two fiscal years); a slowdown is not a release
def test_4_growth_inside_the_record_passes(ctx):
    res = run_check(depart(clean(), "book_growth.y1", "record_median", "record_persistence", [Y21, Y25]), ctx)
    assert res["status"] == "ok" and res["numbers"]["book_growth.y1"] == pytest.approx(0.05)


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


# ---- 11: AOCI stamped with its size; 12: V4 passes with a filed record item
def test_11_aoci_is_stamped_with_its_share_of_book():
    f = bank_facts()
    f["aoci"] = {"values": [{"end": ENDS[-1], "value": -9.6 * M, "tag": "T", "form": "10-K"}]}
    assert "aoci_in_book_not_separated:-0.075" in inputs.base_financial(f)["stamps"]


def test_12_v4_passes_with_a_filed_record_item(ctx):
    assert reverted(run_check(depart(clean(), "roe.y2", "p25", "cycle_downturn", [Y25]), ctx), "roe.y2") == []
