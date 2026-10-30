"""WO_Q5 (SPEC_m3q §4): forecast.py and checks.py on canned valuation_inputs outputs. Each of rev 26's recorded faults, rebuilt here,
must fail its own check; a clean output must pass every check."""
import pytest

from qwen_c.value import checks, forecast, inputs

ENDS = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
R = 0.09
M = 1e6


def series(vals, tag="T"):
    return {"values": [{"end": e, "value": v, "tag": tag, "form": "10-K", "accn": f"0001-{e[2:4]}-000010"}
                       for e, v in zip(ENDS[-len(vals):], vals)]}


def facts():
    s = lambda *v: series([x * M for x in v])
    return {"revenue": s(80, 85, 90, 95, 100), "operating_income": s(12, 13, 14, 15, 16), "net_income": s(8, 8.5, 9, 9.5, 10),
            "pretax_income": s(10, 11, 12, 12.5, 13), "tax_provision": s(2, 2.2, 2.4, 2.5, 2.6), "da": s(4, 4.2, 4.5, 4.7, 5),
            "capex": s(5, 5, 5.5, 6, 6), "interest_expense": s(1, 1, 1, 1, 1), "diluted_shares": s(10, 10, 10, 10, 10),
            "assets_current": s(30, 30, 30, 30, 32), "liabilities_current": s(20, 20, 20, 20, 21), "cash": s(5, 5, 5, 6, 7),
            "debt_current": s(1, 1, 1, 1, 1), "debt_noncurrent": s(19, 19, 19, 19, 19), "equity": s(40, 41, 42, 44, 46),
            "_absent": {}, "_stale": {}}


@pytest.fixture(scope="module")
def ctx():
    f = facts()
    b = inputs.base(f, market_cap=180 * M)
    bar = forecast.record_bar(b["record"]["op_margin"])
    items = {i["fact_id"]: i for i in forecast.record_items(f)}
    items["R1"] = {"fact_id": "R1", "kind": "release", "period": "2026-02-01",
                   "text": "Adjusted EBITDA margin was 25.0% for the year, excluding one-time items."}
    items["G1"] = {"fact_id": "G1", "kind": "release", "period": "2026-02-01", "text": "The company expects revenue growth of 5% in 2026."}
    return b, bar, items


def reason(inp, claim, ids, quotes, numbers):
    return {"input": inp, "claim": claim, "fact_ids": ids, "quotes": quotes, "numbers": numbers, "confidence_basis": "filed"}


SPAN = reason("base.normalized", "The filed operating margin moved from 15.0% to 16.0% over five years.", ["Y2021-12-31", "Y2025-12-31"],
              ["operating margin 15.0%", "operating margin 16.0%"], ["15.0%", "16.0%"])


def clean():
    others = ("base.long_run_op_margin", "base.fade_years", "base.terminal_ronic", "base.terminal_g", "base.margin_source", "bear.op_margin",
              "bull.op_margin")
    return {"task": "valuation_inputs",
            "base": {"rev_growth": [0.05, 0.05], "op_margin": [0.158, 0.158],
                     "normalized": {"year": 3, "baseline": "median", "delta_pts": 0.0, "rev_growth": 0.04},
                     "transition": "linear", "fade_years": 10, "long_run_op_margin": 0.155, "terminal_ronic": 0.15, "terminal_g": 0.03,
                     "margin_source": "record", "investment_path": None},
            "bear": {"op_margin": [0.15, 0.15]}, "bull": {"op_margin": [0.16, 0.16]},
            "prob": {"bear": 0.25, "base": 0.5, "bull": 0.25},
            "reasons": [reason("base.rev_growth", "The company expects revenue growth of 5% in 2026.", ["G1"], ["expects revenue growth of 5%"], ["5%"]),
                        reason("base.op_margin", "The filed operating margin was 16.0% in the last year.", ["Y2025-12-31"],
                               ["operating margin 16.0%"], ["16.0%"]), SPAN] + [dict(SPAN, input=k) for k in others],
            "unknowns": []}


def without(out, inp):
    out["reasons"] = [x for x in out["reasons"] if x["input"] != inp]
    return out


def run(ctx, out):
    b, bar, items = ctx
    return checks.check(out, items, "TEST", set(), b, bar, R)


def test_clean_output_passes_every_check(ctx):
    res = run(ctx, clean())
    assert res["status"] == "ok", res["unsupported"]
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"]
    assert res["labels"]["growth_trajectory"] == "growing"


def test_shape_failure_is_invalid_and_computes_nothing(ctx):
    out = clean()
    out["prob"]["bull"] = 0.5
    res = run(ctx, out)
    assert res["status"] == "invalid" and not res["values"]


def test_msge_premium_above_the_record_without_span_fails_v3(ctx):
    out = without(clean(), "base.long_run_op_margin")
    out["base"]["long_run_op_margin"] = 0.165                         # above the record max 0.16
    out["base"]["margin_source"] = "pricing_or_mix"
    out["reasons"].append(reason("base.long_run_op_margin", "The filed operating margin was 16.0% in the last year.", ["Y2025-12-31"],
                                 ["operating margin 16.0%"], ["16.0%"]))
    res = run(ctx, out)
    assert any("V3 unsupported_premium" in w for w in res["unsupported"]["base.long_run_op_margin"])
    assert res["status"] == "valuation_incomplete" and "base" in res["values"]      # still computed and reported


def test_dar_adjusted_basis_alone_fails_v4(ctx):
    out = without(clean(), "base.op_margin")
    out["reasons"].append(reason("base.op_margin", "Adjusted EBITDA margin was 25.0% for the year.", ["R1"],
                                 ["Adjusted EBITDA margin was 25.0%"], ["25.0%"]))
    assert any(w.startswith("V4") for w in run(ctx, out)["unsupported"]["base.op_margin"])


def test_dac_reason_direction_contradiction_fails_v10(ctx):
    out = clean()
    out["base"]["normalized"]["delta_pts"] = 0.3                     # above the median
    out["reasons"].append(reason("base.normalized", "The margin is set below the median of the filed record of 15.0% to 16.0%.",
                                 ["Y2021-12-31", "Y2025-12-31"], ["operating margin 15.0%", "operating margin 16.0%"], ["15.0%", "16.0%"]))
    assert any(w.startswith("V10") for w in run(ctx, out)["unsupported"]["base.normalized"])


def test_vsnt_shrinking_with_positive_terminal_growth_fails_v7(ctx):
    out = without(clean(), "base.terminal_g")
    out["base"]["rev_growth"] = [-0.05, -0.04]
    out["base"]["normalized"]["rev_growth"] = -0.02
    res = run(ctx, out)
    assert any(w.startswith("V7") for w in res["unsupported"]["base.terminal_g"])
    assert res["labels"]["growth_trajectory"] == "shrinking"


def test_unverified_quote_leaves_the_input_unsupported(ctx):
    out = without(clean(), "base.rev_growth")
    out["reasons"].append(reason("base.rev_growth", "Revenue will grow 5%.", ["G1"], ["revenue will double"], ["5%"]))
    assert run(ctx, out)["unsupported"]["base.rev_growth"] == ["no supported reason"]


def test_v11_investment_after_year5_needs_a_path(ctx):
    out = clean()
    out["base"]["margin_source"] = "investment_after_year5"
    assert any(w.startswith("V11") for w in run(ctx, out)["unsupported"]["base.margin_source"])


def test_v11_record_source_cannot_carry_a_rising_long_run_margin(ctx):
    out = clean()
    out["base"]["long_run_op_margin"] = 0.159                         # inside the record, above year 5
    assert any(w.startswith("V11") for w in run(ctx, out)["unsupported"]["base.margin_source"])


def test_v9_bear_above_base_without_a_reason(ctx):
    out = without(clean(), "bear.op_margin")
    out["bear"] = {"op_margin": [0.17, 0.17]}
    assert any(w.startswith("V9") for w in run(ctx, out)["unsupported"]["bear.op_margin"])


def test_investment_path_extends_the_levels_leg(ctx):
    out = clean()
    out["base"]["margin_source"] = "investment_after_year5"
    out["base"]["long_run_op_margin"] = 0.157
    out["base"]["investment_path"] = [{"year": 6, "capex_over_revenue": 0.08, "revenue_growth": 0.04, "op_margin": 0.156},
                                      {"year": 7, "capex_over_revenue": 0.08, "revenue_growth": 0.04, "op_margin": 0.157}]
    res = run(ctx, out)
    assert "base.margin_source" not in res["unsupported"], res["unsupported"]
    assert res["results"]["base"]["levels_years"] == 7 and res["results"]["base"]["wedge_applied"] is False


def test_record_items_and_bar(ctx):
    b, bar, items = ctx
    assert bar["max"] == pytest.approx(0.16) and bar["min"] == pytest.approx(0.15)
    assert "operating margin 16.0%" in items["Y2025-12-31"]["text"] and items["Y2025-12-31"]["kind"] == "filed_record"


def test_zero_delta_is_the_baseline_itself(ctx):
    b, bar, _ = ctx
    assert forecast.build_path(clean()["base"], bar, b["R0"])[1] == bar["median"]
