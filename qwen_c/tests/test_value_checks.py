"""WO_Q5 / CROSS_CHECK_Q_RULINGS batch A: forecast.py and checks.py on canned valuation_inputs outputs. Every check has a pass case and a
fail case; the reviewer's bypasses (CROSS_CHECK_Q 1, 2, 11-14, 22) are fail cases here."""
import pytest

from qwen_c.value import checks, desk, forecast, inputs

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


ITEMS = {
    "G1": ("release", "2026-02-01", "The company expects revenue growth of 5% in 2026."),
    "R1": ("release", "2026-02-01", "Adjusted EBITDA margin was 25.0% for the year, excluding one-time items."),
    "A1": ("annual_section", "2024-12-31", "Our contracts with customers run for ten years and renew at expiry. Capital invested in our plants "
                                           "earns a return above our cost of capital. We expect the market for our products to grow with the economy."),
    "A2": ("annual_section", "2024-12-31", "Price increases lifted our operating margin to 17.5% in our largest segment."),
    "Q1": ("quarterly_section", "2025-09-30", "The operating margin of the largest segment was 17.8% in the quarter after price increases."),
    "Q0": ("quarterly_section", "2025-06-30", "The operating margin of the largest segment was 17.6% in the quarter after price increases."),
    "C1": ("annual_section", "2024-12-31", "We plan to build two new plants, raising capital expenditure to 9% of revenue from 2031."),
}


@pytest.fixture(scope="module")
def ctx():
    f = facts()
    b = dict(inputs.base(f, market_cap=180 * M, bill_rate=0.04), stub_days=0)
    bar = forecast.record_bar(b["record"]["op_margin"])
    items = {i["fact_id"]: i for i in forecast.record_items(f)}
    items.update({k: {"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in ITEMS.items()})
    return b, bar, items


def reason(inp, claim, ids, quotes, numbers=()):
    return {"input": inp, "claim": claim, "fact_ids": list(ids), "quotes": list(quotes), "numbers": list(numbers), "confidence_basis": "filed"}


Y21, Y25 = "Y2021-12-31", "Y2025-12-31"
M15, M16 = "operating margin 15.0%", "operating margin 16.0%"


def clean():
    return {"task": "valuation_inputs",
            "base": {"rev_growth": [0.05, 0.05], "op_margin": [0.158, 0.158],
                     "normalized": {"year": 3, "baseline": "median", "delta_pts": 0.0, "rev_growth": 0.04},
                     "transition": "linear", "transition_year": None, "fade_years": 10, "long_run_op_margin": 0.155,
                     "terminal_ronic": 0.15, "terminal_g": 0.03, "margin_source": "record", "investment_path": None},
            "bear": {"op_margin": [0.15, 0.15]}, "bull": {"op_margin": [0.16, 0.16]},
            "prob": {"bear": 0.25, "base": 0.5, "bull": 0.25},
            "reasons": [
                reason("base.rev_growth", "The company expects revenue growth of 5% in 2026.", ["G1"], ["expects revenue growth of 5%"], ["5%"]),
                reason("base.op_margin", "The filed operating margin was 16.0% in the last year.", [Y25], [M16], ["16.0%"]),
                reason("base.normalized", "The filed operating margin moved from 15.0% to 16.0% over five years; it normalizes at the median.",
                       [Y21, Y25], [M15, M16], ["15.0%", "16.0%"]),
                reason("base.long_run_op_margin", "Over five filed years the operating margin stayed between 15.0% and 16.0%, a durable margin.",
                       [Y21, Y25], [M15, M16], ["15.0%", "16.0%"]),
                reason("base.fade_years", "Customer contracts run for ten years, which supports a ten-year fade.", ["A1"],
                       ["Our contracts with customers run for ten years"]),
                reason("base.terminal_ronic", "The company says capital invested in its plants earns a return above its cost of capital.",
                       ["A1"], ["Capital invested in our plants earns a return above our cost of capital"]),
                reason("base.terminal_g", "The company expects the market for its products to grow with the economy.", ["A1"],
                       ["We expect the market for our products to grow with the economy"]),
                reason("base.margin_source", "The operating margin rose from 15.0% to 16.0% inside the filed record.", [Y21, Y25], [M15, M16],
                       ["15.0%", "16.0%"]),
                reason("bear.op_margin", "In a weaker year the margin could return to the 15.0% of the earliest filed year.", [Y21], [M15],
                       ["15.0%"]),
                reason("bull.op_margin", "The margin reached 16.0% in the last filed year and could hold there.", [Y25], [M16], ["16.0%"])],
            "unknowns": []}


def without(out, inp):
    out["reasons"] = [x for x in out["reasons"] if x["input"] != inp]
    return out


def run(ctx, out):
    b, bar, items = ctx
    return checks.check(out, items, "TEST", set(), b, bar, R, ENDS)


def unsup(res, key):
    return res["unsupported"].get(key, [])


# ---- the clean output, and the stamps -----------------------------------------------------------------------------------------------

def test_clean_output_passes_every_check(ctx):
    res = run(ctx, clean())
    assert res["status"] == "ok", res["unsupported"]
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"]
    assert "v5_withdrawn_status_unenforced" in res["stamps"] and res["refused_reasons"] == []


# ---- V1 shape and robustness (rulings 11, 22) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda o: o["prob"].update(bull=0.5),
    lambda o: o.update(bull={"fade_years": 200}),
    lambda o: o.update(bull={"rev_growth": ["x", 0.1]}),
    lambda o: o["base"].update(transition="step_at_year", transition_year=None),
    lambda o: o["base"].update(investment_path=[{"year": 6, "capex_over_revenue": 0.1, "revenue_growth": 0.04}]),
    lambda o: o["reasons"].append("a string"),
    lambda o: o["base"].update(rev_growth=[-1.0, 0.05]),
    lambda o: o.update(bear={"margin_source": "decline"}),
])
def test_malformed_content_is_invalid_and_never_raises(ctx, mutate):
    out = clean()
    mutate(out)
    res = run(ctx, out)
    assert res["status"] == "invalid" and not res["values"]


def test_partial_scenario_normalized_merges_onto_base(ctx):
    out = clean()
    out["bull"] = {"normalized": {"delta_pts": 0.2}}
    out["reasons"].append(reason("bull.normalized", "Price increases could lift the margin by a fraction of a point.", ["A2"],
                                 ["Price increases lifted our operating margin to 17.5%"], ["17.5%"]))
    res = run(ctx, out)
    assert res["status"] == "ok", res["unsupported"]


def test_scenario_replacement_needs_its_own_reason(ctx):
    res = run(ctx, without(clean(), "bull.op_margin"))
    assert unsup(res, "bull.op_margin") == ["no supported reason for the scenario's own input"]


# ---- what a reason must be (rulings 1, 12) -------------------------------------------------------------------------------------------

def test_reason_without_quotes_does_not_count(ctx):
    out = without(clean(), "base.op_margin")
    out["reasons"].append(reason("base.op_margin", "The margin holds near the record.", [Y25], []))
    assert unsup(run(ctx, out), "base.op_margin")[0].startswith("no supported reason")


def test_unverified_quote_does_not_count(ctx):
    out = without(clean(), "base.rev_growth")
    out["reasons"].append(reason("base.rev_growth", "Revenue will grow 5%.", ["G1"], ["revenue will double"], ["5%"]))
    assert unsup(run(ctx, out), "base.rev_growth")[0].startswith("no supported reason")


def test_reason_must_address_its_input(ctx):
    out = without(clean(), "base.terminal_g")
    out["reasons"].append(reason("base.terminal_g", "The filed operating margin was 15.0% in the first year.", [Y21], [M15], ["15.0%"]))
    assert "does not address terminal_g" in unsup(run(ctx, out), "base.terminal_g")[0]


def test_one_claim_cannot_serve_two_inputs(ctx):
    out = clean()
    dup = dict(out["reasons"][2], input="base.margin_source")
    out = without(out, "base.margin_source")
    out["reasons"].append(dup)
    assert "already serves" in unsup(run(ctx, out), "base.margin_source")[0]


# ---- V3 (ruling 1) and V4 ------------------------------------------------------------------------------------------------------------

def _premium(out, ids, quotes, numbers):
    out = without(out, "base.long_run_op_margin")
    out["base"]["long_run_op_margin"] = 0.17                         # above the record max 0.16
    out["base"]["margin_source"] = "pricing_or_mix"
    out = without(out, "base.margin_source")
    out["reasons"].append(reason("base.margin_source", "Price increases lifted the margin of the largest segment.", ["A2"],
                                 ["Price increases lifted our operating margin to 17.5%"], ["17.5%"]))
    out["reasons"].append(reason("base.long_run_op_margin", "The largest segment's margin was 17.5% and 17.8% after price increases.",
                                 ids, quotes, numbers))
    return out


def test_v3_premium_spanning_two_fiscal_years_passes(ctx):
    out = _premium(clean(), ["A2", "Q1"], ["operating margin to 17.5%", "was 17.8% in the quarter"], ["17.5%", "17.8%"])
    assert "base.long_run_op_margin" not in run(ctx, out)["unsupported"]


def test_v3_half_year_of_one_fiscal_year_fails(ctx):
    out = _premium(clean(), ["Q0", "Q1"], ["was 17.6% in the quarter", "was 17.8% in the quarter"], ["17.6%", "17.8%"])
    out["reasons"][-1]["claim"] = "The largest segment's margin was 17.6% and 17.8% after price increases."
    assert any("V3" in w for w in unsup(run(ctx, out), "base.long_run_op_margin"))


def test_v3_cannot_be_carried_by_the_code_built_record(ctx):
    out = _premium(clean(), [Y21, Y25], [M15, M16], ["15.0%", "16.0%"])
    out["reasons"][-1]["claim"] = "The operating margin was 15.0% and 16.0% over the record, a durable margin."
    assert any("V3" in w for w in unsup(run(ctx, out), "base.long_run_op_margin"))


def test_v4_adjusted_basis_alone_fails(ctx):
    out = without(clean(), "base.op_margin")
    out["reasons"].append(reason("base.op_margin", "Adjusted EBITDA margin was 25.0% for the year.", ["R1"],
                                 ["Adjusted EBITDA margin was 25.0%"], ["25.0%"]))
    assert any(w.startswith("V4") for w in unsup(run(ctx, out), "base.op_margin"))


# ---- V10 (ruling 13) -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("claim,delta,bad", [
    ("The margin is set above the filed record median of 15.0% to 16.0%.", 0.1, False),
    ("The margin does not exceed the record maximum of 16.0% over 15.0% to 16.0%.", 0.0, False),
    ("The margin is set below its five-year median within 15.0% to 16.0%.", 0.3, True),
    ("The margin is set below the historical median within 15.0% to 16.0%.", 0.3, True),
    ("The margin is set below the median within 15.0% to 16.0%.", -0.2, False),
])
def test_v10_direction(ctx, claim, delta, bad):
    out = clean()
    out["base"]["normalized"]["delta_pts"] = delta
    out["reasons"].append(reason("base.normalized", claim, [Y21, Y25], [M15, M16], ["15.0%", "16.0%"]))
    got = any(w.startswith("V10") for w in unsup(run(ctx, out), "base.normalized"))
    assert got == bad


# ---- V7 -----------------------------------------------------------------------------------------------------------------------------

def _shrinking(out):
    out["base"]["rev_growth"] = [-0.05, -0.04]
    out["base"]["normalized"]["rev_growth"] = -0.02
    out["bear"], out["bull"] = {}, {}
    out["reasons"] = [x for x in out["reasons"] if not x["input"].startswith(("bear", "bull"))]
    return out


def test_v7_shrinking_with_positive_terminal_growth_needs_a_growth_reason(ctx):
    res = run(ctx, without(_shrinking(clean()), "base.terminal_g"))
    assert any(w.startswith("V7") for w in unsup(res, "base.terminal_g")) and res["labels"]["growth_trajectory"] == "shrinking"


def test_v7_passes_with_a_supported_growth_reason(ctx):
    res = run(ctx, _shrinking(clean()))
    assert "base.terminal_g" not in res["unsupported"]


# ---- V11 and the investment path (ruling 2) ------------------------------------------------------------------------------------------

def _invest(out, capex=0.09, margins=(0.156, 0.157)):
    out["base"]["margin_source"] = "investment_after_year5"
    out["base"]["long_run_op_margin"] = 0.157
    out["base"]["investment_path"] = [{"year": 6 + j, "capex_over_revenue": capex, "revenue_growth": 0.04, "op_margin": m}
                                      for j, m in enumerate(margins)]
    out = without(out, "base.margin_source")
    out["reasons"].append(reason("base.margin_source", "Two new plants are planned, an investment programme behind the margin.", ["C1"],
                                 ["We plan to build two new plants"]))
    out["reasons"].append(reason("base.investment_path", "Capital expenditure rises to 9% of revenue to build two new plants.", ["C1"],
                                 ["raising capital expenditure to 9% of revenue"], ["9%"]))
    return out


def test_investment_path_with_reasons_extends_the_levels_leg(ctx):
    res = run(ctx, _invest(clean()))
    assert "base.investment_path" not in res["unsupported"] and "base.margin_source" not in res["unsupported"], res["unsupported"]
    assert res["results"]["base"]["levels_years"] == 7 and res["results"]["base"]["wedge_applied"] is False


def test_investment_path_without_a_reason_is_unsupported(ctx):
    out = without(_invest(clean()), "base.investment_path")
    assert unsup(run(ctx, out), "base.investment_path")[0].startswith("no supported reason")


def test_investment_path_margin_outside_the_record_needs_v3(ctx):
    res = run(ctx, _invest(clean(), margins=(0.40, 0.40)))
    assert any("V3" in w for w in unsup(res, "base.investment_path"))


def test_investment_path_at_maintenance_capex_is_not_a_programme(ctx):
    b = ctx[0]
    res = run(ctx, _invest(clean(), capex=b["c_ratio"]))
    assert any("not an investment programme" in w for w in unsup(res, "base.investment_path"))


def test_v11_investment_after_year5_needs_a_path(ctx):
    out = clean()
    out["base"]["margin_source"] = "investment_after_year5"
    assert any(w.startswith("V11") for w in unsup(run(ctx, out), "base.margin_source"))


def test_v11_record_source_cannot_carry_a_rising_long_run_margin(ctx):
    out = clean()
    out["base"]["long_run_op_margin"] = 0.159
    assert any(w.startswith("V11") for w in unsup(run(ctx, out), "base.margin_source"))


# ---- V9 ----------------------------------------------------------------------------------------------------------------------------

def test_v9_bear_above_base_needs_its_reason_to_say_why(ctx):
    out = without(clean(), "bear.op_margin")
    out["bear"] = {"op_margin": [0.17, 0.17]}
    res = run(ctx, out)
    assert any(w.startswith("V9") for w in unsup(res, "bear.op_margin"))


# ---- V6 percentile (ruling 14) -------------------------------------------------------------------------------------------------------

def test_v6_cycle_position_is_the_record_percentile(ctx):
    b, bar, _ = ctx
    out = clean()
    out["base"]["normalized"]["baseline"] = "p75"                     # above 3 of 5 record years
    out["base"]["normalized"]["delta_pts"] = 0.05
    res = run(ctx, out)
    rec = sorted(b["record"]["op_margin"].values())
    m_n = bar["p75"] + 0.0005
    share = sum(1 for m in rec if m < m_n) / len(rec)
    assert res["labels"]["cycle_position"] == ("peak" if share > 2 / 3 else "mid")


# ---- V1 recompute (ruling 16) ------------------------------------------------------------------------------------------------------

def test_v1_recompute_catches_an_engine_defect(ctx, monkeypatch):
    real = desk.d2_flow
    monkeypatch.setattr(desk, "d2_flow", lambda x, capex, da_org, dnwc, *a: real(x, capex, da_org, -dnwc, *a))
    with pytest.raises(AssertionError, match="V1"):
        run(ctx, clean())


# ---- the record ---------------------------------------------------------------------------------------------------------------------

def test_record_items_and_bar(ctx):
    b, bar, items = ctx
    assert bar["max"] == pytest.approx(0.16) and bar["min"] == pytest.approx(0.15)
    assert "operating margin 16.0%" in items[Y25]["text"] and items[Y25]["kind"] == "filed_record"


def test_fiscal_year_mapping():
    assert checks.fiscal_year_of("2025-09-30", ENDS) == "2025-12-31"
    assert checks.fiscal_year_of("2024-12-31", ENDS) == "2024-12-31"
    assert checks.fiscal_year_of("2026-03-31", ENDS) == "2026-12-31"      # the 10-Q after FY0 (N1)
    assert checks.fiscal_year_of("2027-06-30", ENDS) is None



# ---- CROSS_CHECK_Q2 -----------------------------------------------------------------------------------------------------------------

REAL = {"K0": ("annual_section", "2025-12-31", "Price increases lifted our operating margin to 17.5% in our largest segment."),
        "Q9": ("quarterly_section", "2026-03-31", "The operating margin of the largest segment was 17.8% in the quarter after price increases.")}


@pytest.fixture(scope="module")
def ctx_real(ctx):
    b, bar, items = ctx
    items = dict(items)
    items.update({k: {"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in REAL.items()})
    return b, bar, items


def test_n1_v3_passes_on_the_real_packet_layout(ctx_real):
    # the FY0 10-K section and the 10-Q filed after it: two fiscal years (2025, 2026)
    out = _premium(clean(), ["K0", "Q9"], ["operating margin to 17.5%", "was 17.8% in the quarter"], ["17.5%", "17.8%"])
    assert "base.long_run_op_margin" not in run(ctx_real, out)["unsupported"]


def test_n2_span_counts_quoted_items_only(ctx_real):
    # cites two filed items but quotes only the [Y] record: no span
    out = _premium(clean(), ["K0", "Q9", Y25], [M16], ["16.0%"])
    out["reasons"][-1]["claim"] = "The operating margin was 16.0% and can rise with price increases."
    assert any("V3" in w for w in unsup(run(ctx_real, out), "base.long_run_op_margin"))


def test_n3_v7_decline_words_do_not_support_positive_terminal_growth(ctx):
    out = without(_shrinking(clean()), "base.terminal_g")
    out["reasons"].append(reason("base.terminal_g", "Revenue declined as the market shrinks; terminal growth stays positive.", ["A1"],
                                 ["We expect the market for our products to grow with the economy"]))
    assert any(w.startswith("V7") for w in unsup(run(ctx, out), "base.terminal_g"))


def test_n4_scenario_margin_outside_the_record_needs_v3(ctx):
    out = without(clean(), "bull.op_margin")
    out["bull"] = {"long_run_op_margin": 0.60}
    out["reasons"].append(reason("bull.long_run_op_margin", "The margin could rise far above the record with pricing.", [Y25], [M16], ["16.0%"]))
    res = run(ctx, out)
    assert any("V3" in w for w in unsup(res, "bull.long_run_op_margin"))


def test_n4_negative_scenario_value_is_annotated(ctx):
    out = without(clean(), "bear.op_margin")
    out["bear"] = {"op_margin": [-0.40, -0.40], "long_run_op_margin": -0.30}
    out["reasons"].append(reason("bear.op_margin", "In a collapse the margin could fall far below the 15.0% of the first year.", [Y21], [M15],
                                 ["15.0%"]))
    out["reasons"].append(reason("bear.long_run_op_margin", "A collapsed market could keep the margin far below the record low of 15.0%.",
                                 [Y21], [M15], ["15.0%"]))
    res = run(ctx, out)
    assert any(a.startswith("value_not_positive") for a in res["annotations"])


def test_n5_v10_reads_year_margin_reasons_and_skips_named_years(ctx):
    out = without(clean(), "base.op_margin")
    out["reasons"].append(reason("base.op_margin", "The near-term margin is set below the median of the filed record of 15.0% to 16.0%.",
                                 [Y21, Y25], [M15, M16], ["15.0%", "16.0%"]))
    assert any(w.startswith("V10") for w in unsup(run(ctx, out), "base.op_margin"))
    out = without(clean(), "base.op_margin")
    out["reasons"].append(reason("base.op_margin", "In 2021 the operating margin of 15.0% was below the median; it is now 16.0%.",
                                 [Y21, Y25], [M15, M16], ["15.0%", "16.0%"]))
    assert "base.op_margin" not in run(ctx, out)["unsupported"]


def test_n6_capex_path_outside_the_record_needs_a_span(ctx):
    out = clean()
    out["base"]["capex_path"] = [0.0, 0.0, 0.0, 0.0, 0.0]
    out["reasons"].append(reason("base.capex_path", "Capital spending stops while existing plants run.", ["C1"],
                                 ["We plan to build two new plants"]))
    assert any("outside the filed record" in w for w in unsup(run(ctx, out), "base.capex_path"))


def test_n7_terminal_growth_near_the_rate_is_annotated(ctx):
    b, bar, items = ctx
    out = clean()
    out["base"]["terminal_g"] = 0.08
    res = checks.check(out, items, "TEST", set(), dict(b, g_anchor=0.0375), bar, R, ENDS)
    assert any(w.startswith("V3g terminal_g") for w in res["unsupported"]["base.terminal_g"])
    assert any(a.startswith("terminal_spread_thin") for a in res["annotations"])


def test_v3g_growth_above_the_filed_record_needs_a_span(ctx):
    out = clean()
    out["base"]["normalized"]["rev_growth"] = 0.15                    # the record's maximum growth is 6.25%
    assert any(w.startswith("V3g revenue growth") for w in run(ctx, out)["unsupported"]["base.normalized"])


def test_equity_return_not_above_terminal_growth_is_refused(ctx):
    out = clean()
    out["base"]["terminal_ronic"] = 0.025                             # below g_T 3%
    assert any("ronic_not_above_growth" in w for w in run(ctx, out)["unsupported"]["base.desk"])
