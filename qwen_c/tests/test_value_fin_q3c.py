"""CROSS_CHECK_Q3c: the record-neutral reference (Q3c-1..4), the per-share tolerance (Q3c-5), record_items before a preferred's first
filing (Q3c-6)."""
import pytest

from qwen_c.value import checks, forecast, forecast_fin, inputs
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin import ENDS, M, R, bank_facts, clean, ctx, run_check  # noqa: F401


def far(res, name):
    return any(a.startswith(f"value_far_from_record_neutral: {name} ") for a in res["annotations"])


def op_ctx():
    b = dict(inputs.base(OP.facts(), market_cap=180 * M, bill_rate=0.04), stub_days=0, g_anchor=0.03)
    bar = forecast.record_bar(b["record"]["op_margin"])
    items = {i["fact_id"]: i for i in forecast.record_items(OP.facts())}
    items.update({k: {"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in OP.ITEMS.items()})
    return b, bar, items


def test_neutral_reply_is_not_flagged(ctx):
    res = run_check(clean(), ctx)
    assert res["diagnostics"]["record_neutral"]["value"] > 0 and not any(far(res, n) for n in ("bear", "base", "bull"))


def test_Q3c2_terminal_growth_near_r_is_flagged(ctx):
    # the lever needs ROE above r: at r = 6% the canned bank's 10% ROE makes terminal growth near r worth a multiple
    b, bar, items = ctx
    out = clean()
    out["base"]["terminal_g"] = 0.055
    res = checks.check(out, items, "TB", set(), b, bar, 0.06, ENDS, route="financial")
    assert far(res, "base")
    assert not far(checks.check(clean(), items, "TB", set(), b, bar, 0.06, ENDS, route="financial"), "base")


def test_Q3c3_a_bull_far_above_neutral_is_flagged(ctx):
    out = clean()
    out["bull"] = {"roe": [0.40, 0.40], "long_run_roe": 0.40, "normalized": {"delta_pts": 30.0}}
    out["reasons"] = [x for x in out["reasons"] if x["input"] != "bull.roe"]
    assert far(run_check(out, ctx), "bull")


def test_Q3c1_operating_growth_lever_is_flagged():
    b, bar, items = op_ctx()
    out = OP.clean()
    out["base"]["rev_growth"] = [0.30, 0.30]
    out["base"]["normalized"]["rev_growth"] = 0.30
    out["base"]["fade_years"] = 30
    out["base"]["terminal_ronic"] = "unlimited"
    res = checks.check(out, items, "T", set(), b, bar, OP.R, OP.ENDS)
    assert far(res, "base")


def test_operating_clean_reply_has_a_neutral_reference():
    b, bar, items = op_ctx()
    res = checks.check(OP.clean(), items, "T", set(), b, bar, OP.R, OP.ENDS)
    assert res["diagnostics"]["record_neutral"]["value"] > 0


def test_no_anchor_is_annotated_not_flagged(ctx):
    b, bar, items = ctx
    res = checks.check(clean(), items, "TB", set(), dict(b, g_anchor=None), bar, R, ENDS, route="financial")
    assert any(a.startswith("record_neutral_unavailable") for a in res["annotations"])


def test_Q3c5_per_share_tolerance_is_relative_to_the_value(ctx):
    b, bar, _ = ctx
    inp = forecast_fin.assemble(clean()["base"], b, bar, r=R)
    v = forecast_fin.value(inp)
    with pytest.raises(AssertionError):
        checks._recompute_fin(inp, dict(v, value_per_share=v["value_per_share"] * 1.001), b)


def test_Q3c6_record_items_before_a_preferreds_first_filing():
    f = bank_facts()
    f["preferred_equity"] = {"values": [{"end": ENDS[-1], "value": 10 * M, "tag": "T", "form": "10-K"}]}
    f["preferred_dividends"] = {"values": [{"end": ENDS[-1], "value": 0.5 * M, "tag": "T", "form": "10-K"}]}
    b = inputs.base_financial(f)
    items = forecast_fin.record_items(f, b)
    assert "preferred stock $0.0 million" in items[0]["text"] and "common equity $118.0 million" in items[-1]["text"]


def test_Q3d1_a_non_positive_reference_is_one_annotation(ctx):
    res = {"values": {"bear": 1.0, "base": 2.0, "bull": 3.0}, "annotations": []}
    checks._annotate_neutral(res, (-8.0, "test"))
    assert len(res["annotations"]) == 1 and res["annotations"][0].startswith("record_neutral_not_positive")


def test_Q3d3_a_wrong_rollforward_factor_is_caught(ctx):
    b, bar, _ = ctx
    inp = dict(forecast_fin.assemble(clean()["base"], b, bar, r=R), stub_days=200)
    v = forecast_fin.value(inp)
    checks._recompute_fin(inp, v, b)
    with pytest.raises(AssertionError):
        checks._recompute_fin(inp, dict(v, rollforward_factor=1.0, value_per_share=v["equity_value"] / inp["shares"]), b)


def test_O1_terminal_growth_above_anchor_is_annotated(ctx):
    out = clean()
    out["base"]["terminal_g"] = 0.045
    assert any(a.startswith("terminal_g_above_anchor: base") for a in run_check(out, ctx)["annotations"])
