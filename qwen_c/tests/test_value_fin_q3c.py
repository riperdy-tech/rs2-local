"""CROSS_CHECK_Q3c: the record-neutral reference (Q3c-1..4), the per-share tolerance (Q3c-5), record_items before a preferred's first
filing (Q3c-6); rules restated on prompt v8 / fin.v6's menus."""
import pytest

from qwen_c.value import checks, forecast_fin, menu
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_fin import ENDS, M, R, Y25, bank_facts, clean, ctx, ctx_of, depart, run_check  # noqa: F401


def far(res, name):
    return any(a.startswith(f"value_far_from_record_neutral: {name} ") for a in res["annotations"])


def op_ctx():
    return OP.ctx_of()


def neutral_sc(ctx):
    b, bar, _ = ctx
    m = menu.menus(b, bar, R, "financial")
    base = menu.neutral_base("financial")
    return menu.scenario(base, menu.resolve(base, {}, m), m)


def test_neutral_reply_is_not_flagged(ctx):
    res = run_check(clean(), ctx)
    assert res["diagnostics"]["record_neutral"]["value"] > 0 and not any(far(res, n) for n in ("bear", "base", "bull"))
    assert res["diagnostics"]["value_over_record_neutral"]["base"] == 1.0


def test_Q3c2_the_levers_are_measured_against_the_neutral(ctx):
    # at r = 6% the canned bank's long run at the record p75 + 3 points over a 20-year fade: the menu's largest levers stay inside the
    # band here; the ratio is recorded either way
    out = depart(clean(), "long_run_roe", ("p75", 3), "competition", ["A2.s1", "Q2.s1"])
    out = depart(out, "fade_years", 20, "competition", ["A1.s1"])
    res = run_check(out, ctx_of(r=0.06), r=0.06)
    assert not res["reverts"] and res["diagnostics"]["value_over_record_neutral"]["base"] > 1.2


def test_Q3c1_operating_levers_are_measured_and_a_value_outside_the_band_is_flagged():
    b, bar, ids = op_ctx()
    out = OP.depart(OP.clean(), "terminal_ronic", "ronic0", "competition", ["A1.s2"])
    out = OP.depart(out, "fade_years", 20, "competition", ["A1.s1"])
    out = OP.depart(out, "long_run_op_margin", ("p75", 3), "pricing", ["A2.s1", "Q1.s1"])
    res = checks.check(out, ids, b, bar, OP.R, OP.ENDS)
    assert not res["reverts"] and res["diagnostics"]["value_over_record_neutral"]["base"] > 1.2
    res = {"values": {"bear": 9.0, "base": 30.0, "bull": 31.0}, "annotations": []}
    checks._annotate_neutral(res, (10.0, "test"))
    assert far(res, "base") and far(res, "bull") and not far(res, "bear")


def test_operating_clean_reply_has_a_neutral_reference():
    b, bar, ids = op_ctx()
    assert checks.check(OP.clean(), ids, b, bar, OP.R, OP.ENDS)["diagnostics"]["record_neutral"]["value"] > 0


def test_no_anchor_is_a_no_call(ctx):
    b, bar, ids = ctx
    res = checks.check(clean(), ids, dict(b, g_anchor=None), bar, R, ENDS, route="financial")
    assert res["status"] == "no_call" and res["reason"] == "record_neutral_unavailable"
    assert checks._neutral_fin(dict(b, g_anchor=None), bar, R)[1].startswith("record_neutral_unavailable")


def test_Q3c5_per_share_tolerance_is_relative_to_the_value(ctx):
    b, bar, _ = ctx
    inp = forecast_fin.assemble(neutral_sc(ctx), b, bar, r=R)
    v = forecast_fin.value(inp)
    with pytest.raises(AssertionError):
        checks._recompute_fin(inp, dict(v, value_per_share=v["value_per_share"] * 1.001), b)


def test_Q3c6_record_items_before_a_preferreds_first_filing():
    from qwen_c.value import inputs
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
    inp = dict(forecast_fin.assemble(neutral_sc(ctx), b, bar, r=R), stub_days=200)
    v = forecast_fin.value(inp)
    checks._recompute_fin(inp, v, b)
    with pytest.raises(AssertionError):
        checks._recompute_fin(inp, dict(v, rollforward_factor=1.0, value_per_share=v["equity_value"] / inp["shares"]), b)


def test_O1_terminal_growth_cannot_exceed_the_anchor_on_the_menu(ctx):
    b, bar, _ = ctx
    m = menu.menus(b, bar, R, "financial")
    assert max(v for v in m["terminal_g"].values() if v is not None) == b["g_anchor"]
