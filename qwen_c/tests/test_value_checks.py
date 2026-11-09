"""F_SPEC_valuation_menu §3-§5 (F4, checks v11) on the canned company of WO_Q5: the reply errors, the evidence rules on departed keys
(V3, V3g, V4, V13, N6), the reverts to a fixed point (the cascade through a long run anchored on normalized), guidance read or
reverted, the code-built scenarios, the annotations and V1. Every rule has a pass case and a fail case."""
import copy

import pytest

from qwen_c.value import checks, desk, forecast, inputs, menu, task

ENDS = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
R = 0.09
M = 1e6
PROV = {"rf": 0.0505, "g_anchor": 0.03, "loading_adjusted": 1.25, "closure_erp": 0.0417}


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
    "G2": ("release", "2026-02-01", "The company expects revenue growth of 10% in 2026."),
    "G3": ("release", "2026-02-01", "Revenue is expected to decline 3% to 5% in 2026."),
    "C2": ("release", "2026-02-01", "Capital expenditure is expected to be about $9.0 million in 2026."),
    "R1": ("release", "2026-02-01", "Adjusted EBITDA margin was 25.0% for the year, excluding one-time items."),
    "A1": ("annual_section", "2024-12-31", "Our contracts with customers run for ten years and renew at expiry. Capital invested in our plants "
                                           "earns a return above our cost of capital. We expect the market for our products to grow with the economy."),
    "A2": ("annual_section", "2024-12-31", "Price increases lifted our operating margin to 17.5% in our largest segment."),
    "Q1": ("quarterly_section", "2025-09-30", "The operating margin of the largest segment was 17.8% in the quarter after price increases."),
    "Q0": ("quarterly_section", "2025-06-30", "The operating margin of the largest segment was 17.6% in the quarter after price increases."),
    "C1": ("annual_section", "2024-12-31", "We plan to build two new plants, raising capital expenditure to 9% of revenue from 2031."),
}
Y21, Y25 = "Y2021-12-31", "Y2025-12-31"


def ctx_of(g_anchor=0.03, items=ITEMS):
    f = facts()
    b = dict(inputs.base(f, market_cap=180 * M, bill_rate=0.04), stub_days=0, g_anchor=g_anchor)
    bar = forecast.record_bar(b["record"]["op_margin"])
    pk = {"evidence": [{"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in items.items()]}
    return b, bar, task.evidence_ids(pk, forecast.record_items(f), b, bar, R, dict(PROV, g_anchor=g_anchor))


@pytest.fixture(scope="module")
def ctx():
    return ctx_of()


def clean():
    """The record-neutral reply: no departure, uncertain about the normalized margin and terminal growth."""
    return {"task": "valuation_inputs", "base": menu.neutral_base("operating"), "guidance": {}, "departures": [],
            "uncertain": ["normalized.margin", "terminal_g"], "unknowns": ["the order book is not disclosed"]}


def depart(out, key, opt, driver=None, evidence=None, guidance=None):
    out["base"] = menu.set_option(out["base"], key, opt)
    if guidance:
        out["guidance"][key] = guidance
    if driver:
        out["departures"].append({"input": key, "driver": driver, "evidence": list(evidence)})
    return out


def run(ctx, out):
    b, bar, ids = ctx
    return checks.check(out, ids, b, bar, R, ENDS)


# ---- the neutral reply ---------------------------------------------------------------------------------------------------------------

def test_neutral_reply_is_ok_and_values_at_the_record_neutral(ctx):
    res = run(ctx, clean())
    assert res["status"] == "ok" and res["departures"] == [] and res["reverts"] == [] and not res["errors"]
    assert res["values"]["base"] == res["diagnostics"]["record_neutral"]["value"]
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"] and res["prob"] == checks.PROB
    assert set(res["scenarios"]["keys"]) == {"normalized.margin", "terminal_g"} and "v5_withdrawn_status_unenforced" in res["stamps"]


def test_normalized_year_is_not_a_departure_key(ctx):
    out = clean()
    out["base"]["normalized"]["year"] = 5
    res = run(ctx, out)
    assert res["status"] == "ok" and res["year"] == 5 and res["departures"] == [] and not res["errors"]


# ---- reply errors (§4) -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mutate,key", [
    (lambda o: o["base"]["rev_growth"].update(y1="double"), "rev_growth.y1"),
    (lambda o: o["base"].update(terminal_g="decline"), "terminal_g"),                       # not available
    (lambda o: o["base"]["normalized"].update(step=0.7), "normalized.margin"),
    (lambda o: o["base"]["normalized"].update(year=6), "normalized.year"),
    (lambda o: o["base"].update(fade_years=12), "fade_years"),
    (lambda o: o["base"].pop("capex"), "capex"),
    (lambda o: o["base"]["op_margin"].update(y1="last"), "op_margin.y1"),                  # a departure without its entry
    (lambda o: depart(o, "op_margin.y1", "last", "pricing", ["X9.s1"]), "op_margin.y1"),   # an ID that does not exist
    (lambda o: depart(o, "op_margin.y1", "last", "pricing", ["V0"]), "op_margin.y1"),      # only [V0]
    (lambda o: depart(o, "op_margin.y1", "last", "luck", [Y25]), "departures[0]"),
    (lambda o: depart(depart(o, "op_margin.y1", "last", "pricing", [Y25]), "op_margin.y1", "last", "mix", [Y25]), "op_margin.y1"),
    (lambda o: o["base"]["rev_growth"].update(y1="guidance"), "rev_growth.y1"),            # guidance without its entry
    (lambda o: depart(o, "rev_growth.y1", "guidance", "guidance", ["G1.s1"],
                      {"evidence": "G1.s1", "metric": "op_margin", "sign": "as_printed", "ordinal": 1}), "guidance.rev_growth.y1"),
    (lambda o: o.update(uncertain=[]), "uncertain"),
    (lambda o: o.update(uncertain=["normalized"]), "uncertain"),
    (lambda o: o.update(uncertain=["fade_years", "capex", "terminal_g", "terminal_ronic"]), "uncertain"),
])
def test_reply_errors_are_named_by_key_and_nothing_is_valued(ctx, mutate, key):
    out = clean()
    mutate(out)
    res = run(ctx, out)
    assert res["status"] == "reply_invalid" and key in res["errors"] and not res["values"], res["errors"]


@pytest.mark.parametrize("reply", [None, [], {"base": 3}, {"base": {"rev_growth": [0.05, 0.05]}}, {"base": {}, "departures": "x"}])
def test_malformed_content_is_reply_invalid_and_never_raises(ctx, reply):
    assert run(ctx, reply)["status"] == "reply_invalid"


def test_last_within_tolerance_of_the_median_is_not_a_departure_and_its_entry_is_dropped(ctx):
    b, bar, ids = ctx
    out = depart(clean(), "op_margin.y1", "last", "record_persistence", [Y25])
    res = checks.check(out, ids, b, dict(bar, last=bar["persist"] + 0.0009), R, ENDS)    # menu v6: within tolerance of the neutral (persist)
    assert res["status"] == "ok" and res["departures"] == [] and "departure_superfluous: op_margin.y1" in res["annotations"]


# ---- the evidence rules (§4) -------------------------------------------------------------------------------------------------------

def reverted(res, key):
    return [x.split()[-1] for x in res["reverts"] if x.startswith(f"departure_reverted: {key} ")]


def test_v4_a_margin_departure_needs_a_filed_basis(ctx):
    res = run(ctx, depart(clean(), "op_margin.y1", "last", "pricing", ["R1.s1"]))
    assert res["status"] == "ok_with_reverts" and reverted(res, "op_margin.y1") == ["V4"]
    assert res["numbers"]["op_margin.y1"] == res["neutral"]["op_margin.y1"] and res["options"]["op_margin.y1"] == "persist"
    res = run(ctx, depart(clean(), "op_margin.y1", "last", "pricing", [Y25, "R1.s1"]))
    assert res["status"] == "ok" and res["departures"][0]["input"] == "op_margin.y1" and res["directions"]["op_margin.y1"] == "up"


@pytest.mark.parametrize("evidence,rule", [
    (["A2.s1", "Q1.s1"], None),                 # the 2024 10-K and the 2025 10-Q: two fiscal years
    (["Q0.s1", "Q1.s1"], "V3"),                 # two quarters of one fiscal year
    ([Y21, Y25], "V3"),                         # the code-built record cannot carry the span
])
def test_v3_a_margin_outside_the_record_needs_filed_evidence_of_two_fiscal_years(ctx, evidence, rule):
    res = run(ctx, depart(clean(), "long_run_op_margin", ("p75", 1), "pricing", evidence))      # 0.1679 above the record max 0.16
    assert reverted(res, "long_run_op_margin") == ([rule] if rule else [])


def test_v13_returns_fade_and_a_rising_long_run_need_a_filed_item(ctx):
    res = run(ctx, depart(clean(), "terminal_ronic", "half", "competition", [Y25]))
    assert reverted(res, "terminal_ronic") == ["V13"]
    assert reverted(run(ctx, depart(clean(), "terminal_ronic", "half", "competition", ["A1.s2"])), "terminal_ronic") == []
    assert reverted(run(ctx, depart(clean(), "fade_years", 20, "competition", ["R1.s1"])), "fade_years") == ["V13"]
    assert reverted(run(ctx, depart(clean(), "fade_years", 5, "competition", ["R1.s1"])), "fade_years") == []          # down: no V13
    # menu v6: the neutral long run is persist 0.1578; p75 0.1579 is within tolerance, last 0.1600 rises inside the record
    assert reverted(run(ctx, depart(clean(), "long_run_op_margin", ("last", 0), "pricing", [Y25])), "long_run_op_margin") == ["V13"]
    assert reverted(run(ctx, depart(clean(), "long_run_op_margin", ("p25", 0), "pricing", [Y25])), "long_run_op_margin") == []    # down


def test_v3g_guidance_above_the_record_maximum_is_kept_and_annotated(ctx):
    # F_SPEC v1.2: the company's own forward figure is its evidence; V3g's two-fiscal-year span is not asked of it
    g = {"evidence": "G2.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}
    res = run(ctx, depart(clean(), "rev_growth.y1", "guidance", "guidance", ["G2.s1"], g))          # 10% above the record's 6.25%
    assert reverted(res, "rev_growth.y1") == [] and res["numbers"]["rev_growth.y1"] == 0.10
    assert "guidance_outside_record: rev_growth.y1 0.1000" in res["annotations"]
    res = run(ctx, depart(clean(), "rev_growth.y1", "record_median", "record_persistence", [Y21, Y25]))
    assert res["status"] == "ok" and res["numbers"]["rev_growth.y1"] == pytest.approx(0.0572, abs=1e-4)


def test_n6_capex_outside_the_record_ratios(ctx):
    g = {"evidence": "C2.s1", "metric": "capex_level", "sign": "as_printed", "ordinal": 1}
    res = run(ctx, depart(clean(), "capex", "guidance", "capex_program", ["C2.s1"], g))             # $9.0m on year-1 revenue: 8.7%
    assert reverted(res, "capex") == ["N6"]
    res = run(ctx, depart(clean(), "capex", "record_max", "capex_program", [Y25]))
    assert res["status"] == "ok" and res["results"]["base"]["value_per_share"] == res["values"]["base"]


def test_guidance_is_read_and_departs(ctx):
    g = {"evidence": "G1.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}
    res = run(ctx, depart(clean(), "rev_growth.y1", "guidance", "guidance", ["G1.s1"], g))
    assert res["status"] == "ok" and res["numbers"]["rev_growth.y1"] == 0.05 and res["guided"] == {"rev_growth.y1": 0.05}
    assert res["evidence"]["G1.s1"]["text"] == "The company expects revenue growth of 5% in 2026."


def test_unreadable_guidance_reverts_with_its_stamp(ctx):
    g = {"evidence": "G1.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 2}
    res = run(ctx, depart(clean(), "rev_growth.y1", "guidance", "guidance", ["G1.s1"], g))
    assert res["status"] == "ok_with_reverts" and res["reverts"] == ["guidance_unreadable: rev_growth.y1 ordinal 2 of 1 figures in the unit"]
    assert res["numbers"]["rev_growth.y1"] == res["neutral"]["rev_growth.y1"] and res["departures"] == []
    g = dict(g, evidence="A2.s1", ordinal=1)                                                    # a 2024 item: older than the base year
    assert run(ctx, depart(clean(), "rev_growth.y1", "guidance", "guidance", ["A2.s1"], g))["reverts"][0].startswith("guidance_unreadable")


# ---- reverts to a fixed point --------------------------------------------------------------------------------------------------------

def test_revert_cascade_through_a_long_run_anchored_on_normalized(ctx):
    out = depart(clean(), "normalized.margin", ("p75", 2), "pricing", ["A2.s1"])                # 0.1779: V3 with one fiscal year
    out = depart(out, "long_run_op_margin", ("normalized", 0), "pricing", ["A2.s1", "Q1.s1"])   # departs with it, two fiscal years
    res = run(ctx, out)
    assert res["reverts"] == ["departure_reverted: normalized.margin V3"]
    assert res["numbers"]["long_run_op_margin"] == res["neutral"]["long_run_op_margin"] and res["departures"] == []


def test_a_key_departed_only_by_a_revert_without_its_entry_reverts_too(ctx):
    b, bar, ids = ctx
    out = depart(clean(), "normalized.margin", ("persist", 2), "pricing", ["A2.s1"])           # 0.1778 > max: V3 (menu v6 anchor)
    out = depart(out, "long_run_op_margin", ("normalized", -2), None)                           # 0.1578: persist, no departure
    res = run(ctx, out)
    assert res["reverts"] == ["departure_reverted: normalized.margin V3", "departure_reverted: long_run_op_margin no_entry_after_revert"]
    assert res["numbers"]["long_run_op_margin"] == bar["persist"] and res["status"] == "ok_with_reverts"


# ---- scenarios and annotations (§4, §5) ------------------------------------------------------------------------------------------------

def test_v7_shrinking_base_is_annotated_unless_a_growth_driver_departs(ctx):
    g = {"evidence": "G3.s1", "metric": "revenue_growth", "sign": "negative", "ordinal": 1}
    out = depart(clean(), "rev_growth.y1", "guidance", "guidance", ["G3.s1"], g)
    out = depart(out, "rev_growth.y2", "guidance", "guidance", ["G3.s1"], g)
    res = run(ctx, out)
    assert res["numbers"]["rev_growth.y1"] == pytest.approx(-0.04) and any(a.startswith("V7 ") for a in res["annotations"])
    out["departures"][1]["driver"] = "cycle_recovery"
    assert not any(a.startswith("V7 ") for a in run(ctx, out)["annotations"])


def test_bear_and_bull_come_from_the_uncertain_keys(ctx):
    res = run(ctx, clean())
    log = res["scenarios"]["keys"]
    assert log["terminal_g"]["bear"] == 0.015 and log["terminal_g"]["bull"] is None             # the anchor is the top of its menu
    assert res["scenarios"]["bear"] == {"normalized.margin": log["normalized.margin"]["bear"], "terminal_g": 0.015}


def test_desk_refusal_of_base_is_a_no_call_and_no_anchor_too(ctx):
    b, bar, ids = ctx
    assert checks.check(clean(), ids, dict(b, shares=0), bar, R, ENDS)["reason"] == "shares_unavailable"
    res = checks.check(clean(), ids, dict(b, g_anchor=None), bar, R, ENDS)
    assert res["status"] == "no_call" and res["reason"] == "record_neutral_unavailable"


def test_peak_and_spread_are_annotated_never_gates(ctx):
    out = depart(clean(), "long_run_op_margin", ("p75", 0), "pricing", ["A2.s1"])
    res = run(ctx, out)
    assert res["status"] == "ok" and any(a.startswith("margin_at_record_peak: long_run_op_margin") for a in res["annotations"])
    b, bar, ids = ctx_of(g_anchor=0.075)
    assert any(a.startswith("terminal_spread_thin") for a in checks.check(clean(), ids, b, bar, R, ENDS)["annotations"])


def test_market_delta_sensitivity_is_reported_for_levered_names(ctx):
    s = run(ctx, clean()).get("sensitivity")
    assert s and s["value_at_delta_market"] is not None and s["delta_book"] > s["delta_market"]


# ---- V1 recompute (ruling 16) and the record ---------------------------------------------------------------------------------------

def test_v1_recompute_catches_an_engine_defect(ctx, monkeypatch):
    real = desk.d2_flow
    monkeypatch.setattr(desk, "d2_flow", lambda x, capex, da_org, dnwc, *a: real(x, capex, da_org, -dnwc, *a))
    with pytest.raises(AssertionError, match="V1"):
        run(ctx, clean())


def test_record_items_and_bar(ctx):
    b, bar, ids = ctx
    assert bar["max"] == pytest.approx(0.16) and bar["min"] == pytest.approx(0.15)
    assert "operating margin 16.0%" in ids[Y25]["text"] and ids[Y25]["kind"] == "filed_record" and ids["V0"]["kind"] == "code_base"


def test_fiscal_year_mapping():
    assert checks.fiscal_year_of("2025-09-30", ENDS) == "2025-12-31"
    assert checks.fiscal_year_of("2024-12-31", ENDS) == "2024-12-31"
    assert checks.fiscal_year_of("2026-03-31", ENDS) == "2026-12-31"      # the 10-Q after FY0 (N1)
    assert checks.fiscal_year_of("2027-06-30", ENDS) is None


def test_no_regex_on_model_prose_and_the_deleted_classes_are_gone():
    src = open(checks.__file__, encoding="utf-8").read() + open(menu.__file__, encoding="utf-8").read()
    assert "import re" not in src and "re.compile" not in src
    for name in ("_KEYWORDS", "_FIN_KEYWORDS", "_DIRECTION", "_STATED", "_v12", "input_value_text", "reasons_by_input", "check_claim",
                 "margin_source", "investment_path\":"):
        assert name not in src, name
    assert len(open(checks.__file__, encoding="utf-8").read().splitlines()) <= 450


# ---- spec F v1.4 (E4): field-name aliases of the normalized key, the long run inheriting its entry -----------------------------------

def test_normalized_field_names_are_read_as_the_normalized_key_and_annotated(ctx):
    out = depart(clean(), "normalized.margin", ("p25", 0), "pricing", ["A2.s1"])                # down: V4 only (A2 is filed)
    out["departures"][0]["input"] = "normalized.anchor"
    out["departures"].append({"input": "normalized.step", "driver": "pricing", "evidence": ["A2.s1"]})
    out["departures"].append({"input": "normalized.year", "driver": "pricing", "evidence": ["A2.s1"]})
    out["uncertain"] = ["normalized.anchor", "terminal_g"]
    res = run(ctx, out)
    assert res["status"] in ("ok", "ok_with_reverts") and [d["input"] for d in res["departures"]] == ["normalized.margin", "long_run_op_margin"]
    assert "departure_key_alias: normalized.anchor read as normalized.margin" in res["annotations"]
    assert "departure_alias_duplicate_dropped: normalized.step" in res["annotations"]
    assert "departure_not_a_key_dropped: normalized.year" in res["annotations"]
    assert set(res["scenarios"]["keys"]) == {"normalized.margin", "terminal_g"}


def test_a_long_run_anchored_on_normalized_inherits_its_entry(ctx):
    out = depart(clean(), "normalized.margin", ("p25", 0), "pricing", ["A2.s1"])                # the long run follows at (normalized, 0)
    res = run(ctx, out)
    assert res["status"] == "ok" and "long_run_op_margin" not in res["errors"]
    assert res["directions"]["long_run_op_margin"] == "down"


def test_guided_capex_that_survives_n6_is_not_held_to_the_margin_bar(ctx):
    # J2 2026-11-04: a guided capex departure kept by two fiscal years of filed evidence reached the outside-record annotation, which
    # compared the operating-margin bar with capex's yearly tuple (TypeError, engine_defect). Capex has its own span rule (N6), no bar.
    g = {"evidence": "C2.s1", "metric": "capex_level", "sign": "as_printed", "ordinal": 1}
    res = run(ctx, depart(clean(), "capex", "guidance", "capex_program", ["C2.s1", "A2.s1", "Q1.s1"], g))
    assert res["status"] == "ok" and reverted(res, "capex") == [] and res["guided"].get("capex") is not None
    assert not any(a.startswith("guidance_outside_record: capex") for a in res["annotations"])
