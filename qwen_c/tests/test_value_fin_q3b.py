"""CROSS_CHECK_Q3b: each finding's failure scenario is a test here (rules restated on prompt fin.v6's menus)."""
import pytest

from qwen_c.value import inputs
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin import (ENDS, M, Y21, Y25, bank_facts, clean, ctx, depart, grow, run_check,  # noqa: F401
                                         series)


# N1: book growth at the year's ROE (full retention) is valued, not an engine defect or invalid
def test_N1_full_retention_is_valued(ctx):
    b, bar, ids = ctx
    rec = dict(b["record"], book_growth_max=0.5)
    out = depart(clean(), "book_growth.y1", "anchor", "record_persistence", [Y25])
    res = run_check(out, (dict(b, record=rec), bar, ids))
    assert res["status"] == "ok" and "base" in res["values"]


# N2: a cumulative release of more than a quarter of book at an ROE below r is annotated; none without a release
def test_N2_cumulative_release_is_annotated(ctx):
    b, bar, ids = ctx
    ids = dict(ids, **{"B9.s1": {"fact_id": "B9", "kind": "annual_section", "period": "2025-12-31",
                                 "text": "Book value is expected to decline 20% a year as the portfolio runs off.", "sentence": True}})
    out = clean()
    for k in ("book_growth.y1", "book_growth.y2", "normalized.book_growth"):
        out = depart(out, k, "guidance", "guidance", ["B9.s1", "A2.s1", "Q2.s1"], grow("B9.s1", "negative"))
    res = run_check(out, (b, bar, ids), r=0.12)                          # every ROE below r
    assert res["numbers"]["book_growth.y1"] == pytest.approx(-0.20) and not res["reverts"]
    assert any(a.startswith("book_release_cumulative") for a in res["annotations"])
    assert not any(a.startswith("book_release_cumulative") for a in run_check(clean(), ctx)["annotations"])


# N3: a peak ROE held long run is annotated
def test_N3_peak_roe_held_is_annotated(ctx):
    res = run_check(depart(clean(), "long_run_roe", ("last", 0), "competition", ["A2.s1"]), ctx)
    assert any(a.startswith("roe_at_record_peak: long_run_roe") for a in res["annotations"]) and "record_neutral" in res["diagnostics"]


def test_N3_operating_peak_margin_is_annotated():
    res = OP.run(OP.ctx_of(), OP.depart(OP.clean(), "long_run_op_margin", ("last", 0), "pricing", ["A2.s1"]))
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
def test_N7_slowdown_is_not_a_release(ctx):
    res = run_check(depart(clean(), "book_growth.y1", "last", "record_persistence", [Y25]), ctx)        # 4.9%, inside the record
    assert res["status"] == "ok" and not res["reverts"]


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
