"""CROSS_CHECK_Q3b: each new finding's failure scenario is a test here."""
import pytest

from qwen_c.value import checks, forecast, inputs
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin import ENDS, M, bank_facts, clean, ctx, run_check, series  # noqa: F401


def flags(res, key):
    return res["unsupported"].get(key, [])


# N1: full retention (book growth = ROE) and a typed ROE of 0 are valued, not engine defects or invalid
@pytest.mark.parametrize("g", [0.104, 0.05])
def test_N1_full_retention_is_valued(ctx, g):
    out = clean()
    out["base"]["book_growth"] = [g, g]
    out["base"]["roe"] = [g, g] if g != 0.104 else [0.104, 0.104]
    res = run_check(out, ctx)
    assert res["status"] in ("ok", "valuation_incomplete") and "base" in res["values"]


def test_N1_an_roe_of_zero_is_valued(ctx):
    out = clean()
    out["bear"] = {"roe": [0.0, 0.0]}
    res = run_check(out, ctx)
    assert res["status"] != "invalid" and "bear" in res["values"]


# N2: a cumulative release inside the record, at an ROE below r, is annotated
def test_N2_cumulative_release_is_annotated(ctx):
    out = clean()
    out["base"]["book_growth"] = [-0.04, -0.04]
    out["base"]["normalized"]["book_growth"] = -0.10
    out["base"]["roe"] = [0.09, 0.09]                                     # below r: a release adds value only then
    res = run_check(out, ctx)
    assert any(a.startswith("book_release_cumulative: base") for a in res["annotations"])


def test_N2_no_release_no_annotation(ctx):
    assert not any(a.startswith("book_release_cumulative") for a in run_check(clean(), ctx)["annotations"])


# N3: a peak ROE held long run is annotated, against a perpetuity at the record median; the operating analogue
def test_N3_peak_roe_held_is_annotated(ctx):
    b, bar, _ = ctx
    out = clean()
    out["base"]["long_run_roe"] = bar["max"]
    res = run_check(out, ctx)
    assert any(a.startswith("roe_at_record_peak: long_run_roe") for a in res["annotations"])
    assert "pb_record_median_perpetuity" in res["diagnostics"]


def test_N3_operating_peak_margin_is_annotated():
    b = dict(inputs.base(OP.facts(), market_cap=180 * M, bill_rate=0.04), stub_days=0)
    bar = forecast.record_bar(b["record"]["op_margin"])
    items = {i["fact_id"]: i for i in forecast.record_items(OP.facts())}
    items.update({k: {"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in OP.ITEMS.items()})
    out = OP.clean()
    out["base"]["long_run_op_margin"] = bar["max"]
    res = checks.check(out, items, "T", set(), b, bar, OP.R, OP.ENDS)
    assert any(a.startswith("margin_at_record_peak: long_run_op_margin") for a in res["annotations"])


# N4: an unverified ProfitLoss on the opening year only does not refuse the name
def test_N4_opening_year_stamp_is_not_used():
    f = bank_facts()
    f["net_income"] = series([9.0, 10, 10.5, 11.5, 12.0, 12.8])
    f["net_income"]["values"][0]["stamp"] = "profitloss_basis_unverified"
    assert inputs.base_financial(f)["e0"] == pytest.approx(12.8 * M)


# N5: a preferred carried in APIC (filed value 0) is taken at its liquidation preference, stamped
def test_N5_preferred_at_liquidation_preference():
    f = bank_facts()
    f["preferred_equity"] = series([0, 0, 0, 0, 0, 0])
    f["preferred_liquidation"] = {"values": [{"end": e, "value": 10 * M, "tag": "T", "form": "10-K"} for e in ENDS]}
    f["preferred_dividends"] = series([0.5, 0.5, 0.5, 0.5, 0.5])
    b = inputs.base_financial(f)
    assert b["R1"] == pytest.approx(118 * M) and "preferred_subtracted_at_liquidation_preference" in b["stamps"]


# N7: a slowdown with a positive record minimum is not a release
def test_N7_slowdown_is_not_flagged(ctx):
    out = clean()
    out["base"]["book_growth"] = [0.02, 0.02]
    assert not any("below the filed record" in w for w in flags(run_check(out, ctx), "base.book_growth"))


# N8: a stray instant (a changed year-end or a quarter) is not a fiscal year
def test_N8_year_chain_skips_a_stray_instant():
    assert inputs._year_chain(["2020-12-31", "2021-11-30", "2021-12-31", "2022-12-31"]) == ["2020-12-31", "2021-12-31", "2022-12-31"]
    assert inputs._year_chain(["2019-12-31", "2022-12-31", "2023-12-31"]) == ["2022-12-31", "2023-12-31"]


def test_b4_preferred_first_issued_in_the_record():
    f = bank_facts()
    f["preferred_equity"] = {"values": [{"end": ENDS[-1], "value": 10 * M, "tag": "T", "form": "10-K"}]}
    f["preferred_dividends"] = {"values": [{"end": ENDS[-1], "value": 0.5 * M, "tag": "T", "form": "10-K"}]}
    b = inputs.base_financial(f)
    assert b["R1"] == pytest.approx(118 * M) and b["R0"] == pytest.approx(122 * M) and b["e0"] == pytest.approx(12.3 * M)
    assert f"preferred_first_filed:{ENDS[-1]}" in b["stamps"]
