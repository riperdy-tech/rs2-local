"""Revision 24 step 2b, items 3 and 5 (BRIEF_R24_S2b_ranges_gate.md): the SECTION 12 additions reach the verdict row, and the plausibility gate.

- extract_scorecard whitelists near_term_earnings, normalized_earnings, normalization_reason, the three classifications with their evidence
  pointers and input_rationale; the medoid summary and band_verdict carry them, with the Base's long_run_margin and the gate's record.
- the gate (fiduciary_gate.plausibility_gate, run by contract_fill.fill on the answer run when the pack withheld the long-run defaults): a
  supported outlier passes annotated; an unsupported one is rejected by name and the verdict is NOT_USABLE; terminal growth at or above the
  discount rate is rejected; an in-range value passes; nothing is clamped.
"""
import copy
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import consensus_valuation as cv  # noqa: E402
import contract_fill  # noqa: E402
import depth_pipeline as dp  # noqa: E402
import fiduciary_gate as fg  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import population_ranges as pr  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN  # noqa: E402
from test_rev24_s2b_ranges import fixture_tables, rec  # noqa: E402

INF = math.inf
R, GT = 0.10, 0.03
QUOTE = "Our backlog grew to a record level and the new plant runs at full capacity through 2028."
PACK = ("# DATA PACK - TEST   (pack revision 24)\n\n## DATA 5 - FISCAL-YEAR INCOME\n" + QUOTE + "\n\n## DEFAULTS   [x]\n- coe_anchor: 10.00% | x\n")
S12 = {"near_term_earnings": 1.2, "normalized_earnings": 1.0, "normalization_reason": "peak pricing fades by 2028 (PRIMARY P1)",
       "margin_persistence": "Partly_Structural", "margin_persistence_evidence": "PRIMARY P1, segment margins",
       "cycle_position": "PEAK", "cycle_position_evidence": "DATA 4 utilization", "growth_trajectory": "decelerating",
       "growth_trajectory_evidence": "GUIDANCE FY27 outlook"}


def _ranges():
    # the fixture cohort (step 2c): the long-run earnings margin P5 -6% .. P95 18%, the 10-year revenue CAGR P5 -25% .. P95 55%, the ROIC level five
    # years on P5 -24% .. P95 51%; terminal_g has no population range (its outlier threshold is the growth anchor)
    return pr.ranges_for(rec(roic=0.08), "2026-10-16", tables=fixture_tables())


def _base_dcf(lrm=0.12, tg=GT, ronic=0.2, wacc=R):
    lr = {"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF, "x_L": 0.09, "rev_L": 600.0}
    return fmt.unbundled_dcf(base_cf=100.0 / 1.05 ** 5, explicit_growth=[0.05] * 5, wacc=wacc, terminal_g=tg, shares_diluted=1.0, fade_years=5,
                             sbc_treatment="deducted_in_cf", terminal_ronic=ronic, long_run=lr, long_run_margin=lrm)


def _rationale(cite=None, on="long_run_margin"):
    r = {k: {"value": 0.1, "within_p10_p90": True, "rationale": "tied to the record", "citation": None}
         for k in ("long_run_margin", "growth_years_3_5", "fade_years", "terminal_g", "terminal_ronic")}
    if cite:
        r[on].update(within_p10_p90=False, citation=cite)
    return r


# ---- the gate ------------------------------------------------------------------------------------------------------------------------------

def test_an_in_range_trajectory_passes():
    g = fg.plausibility_gate(_base_dcf(lrm=0.12), _ranges(), _rationale(), PACK, growth_anchor=0.0375)
    assert g["verdict"] == "pass" and g["reasons"] == []
    assert g["metrics"]["long_run_margin"]["status"] == "within" and g["metrics"]["terminal_g"]["status"] == "within"
    assert g["metrics"]["terminal_ronic"]["status"] == "within"
    assert "plausibility_not_measured:earnings_ratio_10y" in g["annotations"]          # no cohort measures it: annotated, never rejected


def test_an_unsupported_outlier_is_rejected_by_name_and_never_clamped():
    # step 2c (cross-check 19, ruling B): the rejection is shown on terminal_ronic (the long-run margin's year-5 range only annotates)
    d = _base_dcf(ronic=0.9)                                           # 90% against the ROIC level's P95 of 51%
    g = fg.plausibility_gate(d, _ranges(), _rationale(), PACK)
    assert g["verdict"] == "reject" and g["reasons"] == ["implausible_unsupported_terminal_ronic"]
    assert g["metrics"]["terminal_ronic"]["value"] == 0.9 and d["terminal_ronic"] == 0.9                       # the input is as given
    # a citation that does not resolve (a quote the source does not hold, or a URL not fetched in the session) is no support
    for bad in ({"source": "DATA 5", "date": "2026-09-01", "quote": "a sentence the filing never wrote, long enough to count"},
                {"source": "https://example.com/blog", "date": "2026-09-01", "quote": QUOTE}):
        assert fg.plausibility_gate(d, _ranges(), _rationale(bad, on="terminal_ronic"), PACK)["reasons"] == ["implausible_unsupported_terminal_ronic"]


def test_a_long_run_margin_outside_its_year_5_range_is_annotated_never_rejected():
    """Cross-check 19, ruling B: the range is measured five years out, long_run_margin is the margin at the end of the fade."""
    d = _base_dcf(lrm=0.35)                                            # 35% against a year-5 P95 of 16%
    g = fg.plausibility_gate(d, _ranges(), _rationale(), PACK)
    assert g["verdict"] == "pass" and g["reasons"] == [] and "long_run_margin_outside_year5_range_unsupported" in g["annotations"]
    assert g["metrics"]["long_run_margin"]["status"] == "outside_year5_range_unsupported"
    assert g["within_p10_p90"]["long_run_margin"]["computed"] is False and "outlier_citation_missing:long_run_margin" in g["annotations"]


def test_a_supported_outlier_passes_annotated():
    d = _base_dcf(lrm=0.35)
    g = fg.plausibility_gate(d, _ranges(), _rationale({"source": "DATA 5", "date": "2026-09-01", "quote": QUOTE}), PACK)
    assert g["verdict"] == "pass" and "implausible_supported_long_run_margin" in g["annotations"]
    assert g["metrics"]["long_run_margin"]["status"] == "supported" and g["metrics"]["long_run_margin"]["citation"][0]["quote_found"] is True
    d = _base_dcf(ronic=0.9)
    g = fg.plausibility_gate(d, _ranges(), _rationale({"source": "DATA 5", "date": "2026-09-01", "quote": QUOTE}, on="terminal_ronic"), PACK)
    assert g["verdict"] == "pass" and "implausible_supported_terminal_ronic" in g["annotations"]


def test_terminal_growth_at_or_above_the_rate_is_rejected():
    d = _base_dcf()
    for tg in (R, R + 0.01):
        bad = dict(d, terminal_g=tg)
        g = fg.plausibility_gate(bad, _ranges(), _rationale(), PACK)
        assert g["verdict"] == "reject" and "terminal_growth_not_below_rate" in g["reasons"]


def test_an_unlimited_terminal_return_is_an_outlier_and_a_finite_life_is_not_gated():
    g = fg.plausibility_gate(_base_dcf(ronic=INF), _ranges(), _rationale(), PACK)
    assert "implausible_unsupported_terminal_ronic" in g["reasons"]
    fin = fmt.unbundled_dcf(base_cf=10.0, explicit_growth=[0.05] * 5, wacc=R, terminal_g=GT, shares_diluted=1.0, fade_years=0,
                            sbc_treatment="deducted_in_cf", finite_life_years=15)
    assert fg.plausibility_gate(fin, _ranges(), _rationale(), PACK)["verdict"] == "not_applicable"


def test_without_ranges_only_the_mathematics_is_checked():
    g = fg.plausibility_gate(_base_dcf(lrm=0.35), {"inputs": {}, "unavailable": "x"}, None, PACK)
    assert g["verdict"] == "pass" and all(m["status"] == "not_measured" for m in g["metrics"].values())
    assert "terminal_g_anchor_not_available" in g["annotations"]


# ---- the gate in the fill, and the verdict ----------------------------------------------------------------------------------------------

def _answer_call(lrm, ronic=0.2):
    p = dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="perpetual franchise, 10-K 2025", fade_years=5, terminal_g=GT,
             sbc_treatment="deducted_in_cf", long_run_margin=lrm, terminal_ronic=ronic,
             scenarios=[{"name": n, "prob": pb, "base_cf": 100.0 / 1.05 ** 5, "explicit_growth": [g] * 5, "wacc": R}
                        for n, pb, g in (("Base", 0.5, 0.05), ("Bull", 0.25, 0.08), ("Bear", 0.25, 0.0))])
    ctx = {"price": 500.0, "shares_default_b": 1.0, "coe_anchor": R, "terminal_g_anchor": GT, "owner_earnings_default_b": 100.0 / 1.05 ** 5,
           "long_run": {"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF, "x_L": 0.09, "rev_L": 600.0}, "long_run_defaults_withheld": True}
    res = fmt.execute_financial_model(copy.deepcopy(p), ctx)
    assert "error" not in res, res.get("error")
    return {"tool": "run_financial_model", "params": p, "result": res, "call_index": 1}


def _fill(lrm, facts_over=None, typed_over=None, ronic=0.2):
    facts = {"shares_outstanding": 1e9, "coe_anchor": R, "long_run_defaults_withheld": True, "population_ranges": _ranges(), "terminal_g_anchor": 0.0375}
    facts.update(facts_over or {})
    typed = dict(S12, input_rationale=_rationale())
    typed.update(typed_over or {})
    return contract_fill.fill([_answer_call(lrm, ronic)], typed, facts, 500.0, ticker="TEST", pack_text=PACK, company="Test Co")


def test_the_fill_runs_the_gate_on_the_answer_runs_base_and_records_its_long_run_margin():
    filled, prov = _fill(0.12)
    assert filled["long_run_margin"] == 0.12 and filled["plausibility_gate"]["verdict"] == "pass"
    filled, _ = _fill(0.12, ronic=0.9)
    assert filled["plausibility_gate"]["reasons"] == ["implausible_unsupported_terminal_ronic"]
    # the rev22 arm (and an older pack) is not gated
    filled, _ = _fill(0.35, facts_over={"long_run_defaults_withheld": None})
    assert filled["plausibility_gate"] is None and filled["long_run_margin"] == 0.35


def test_the_section_12_fields_are_whitelisted_and_reach_the_verdict_row():
    contract = dict(S12, input_rationale=_rationale({"source": "DATA 5", "date": "2026-09-01", "quote": QUOTE}), catalysts=[],
                    conviction_score=8.0, business_quality_moat=3.0)
    report = "SECTION 12\n```json:underwriting\n" + json.dumps(contract) + "\n```\n"
    card = cv.extract_scorecard(report, 500.0)
    for k in S12:
        assert k in card
    assert card["margin_persistence"] == "partly_structural" and card["cycle_position"] == "peak" and card["near_term_earnings"] == 1.2
    assert card["input_rationale"]["long_run_margin"]["citation"]["source"] == "DATA 5"
    filled, _ = _fill(0.12)
    sc = dict(card, **filled)
    runs = [{"sample": 1, "iv": sc["base_iv"], "plausible": True, "basis": True, "scorecard": sc, "flags": []}]
    medoid, summary = cv.select_medoid_scorecard(runs, 500.0)
    for k in cv.S12_SUMMARY_KEYS:
        assert k in summary, k
    assert summary["long_run_margin"] == 0.12 and summary["cycle_position"] == "peak" and summary["plausibility_gate"]["verdict"] == "pass"
    v = dp.band_verdict({"ticker": "TEST", "price": 500.0, "runs": runs, "scorecard": summary, "median_iv": sc["base_iv"], "spread_pct": None})
    for k in cv.S12_SUMMARY_KEYS:
        assert v[k] == summary[k], k
    assert v["plausibility_by_sample"] == [{"sample": 1, "verdict": "pass", "reasons": [], "annotations": ["plausibility_not_measured:earnings_ratio_10y"]}]
    # the long-run inputs the analyst chose are on the row
    assert v["long_run_margin"] == 0.12 and v["fade_years"] == 5 and v["terminal_multiple_or_g"] == GT and v["stage1_growth_path"] == [0.05] * 5
    # every empty and fallback summary carries the keys too
    _, empty = cv.select_medoid_scorecard([], 500.0)
    assert all(k in empty for k in cv.S12_SUMMARY_KEYS)


def test_a_rejected_gate_makes_the_verdict_not_usable_with_its_reason():
    filled, _ = _fill(0.12, ronic=0.9)
    sc = dict(S12, input_rationale=_rationale(), **filled)
    runs = [{"sample": 1, "iv": sc["base_iv"], "plausible": True, "basis": True, "scorecard": sc, "flags": []}]
    _, summary = cv.select_medoid_scorecard(runs, 500.0)
    v = dp.band_verdict({"ticker": "TEST", "price": 500.0, "runs": runs, "scorecard": summary, "median_iv": sc["base_iv"], "spread_pct": None})
    assert v["direction"] == "NOT_USABLE" and v["not_usable_reason"] == "implausible_unsupported_terminal_ronic"
    assert "implausible_unsupported_terminal_ronic" in v["flags"] and "PLAUSIBILITY_REJECTED" in v["flags"]
    assert v["kelly_fraction_pct"] == 0.0 and v["size_hint"] is None and "the valuation is not usable" in v["reason"]
    import depth_gates
    actionable, reasons = depth_gates.assess(v)
    assert actionable is False and "not_usable" in reasons
    # a supported outlier publishes, flagged
    typed = {"input_rationale": _rationale({"source": "DATA 5", "date": "2026-09-01", "quote": QUOTE})}
    filled, _ = _fill(0.35, typed_over=typed)
    sc = dict(S12, **typed, **filled)
    runs = [{"sample": 1, "iv": sc["base_iv"], "plausible": True, "basis": True, "scorecard": sc, "flags": []}]
    _, summary = cv.select_medoid_scorecard(runs, 500.0)
    v = dp.band_verdict({"ticker": "TEST", "price": 500.0, "runs": runs, "scorecard": summary, "median_iv": sc["base_iv"], "spread_pct": None})
    assert v["direction"] != "NOT_USABLE" and "implausible_supported_long_run_margin" in v["flags"]
