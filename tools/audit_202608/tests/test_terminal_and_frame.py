"""Phase 4 E13 (joint FIX (c) review with Fable, 2026-09-25): one anchored terminal, and the equity
frame as the default.

FIX s1 and s2 had identical flows, growth, rate and shares; s2 published the exit leg at 16x
against the 19.84x the anchors imply, which alone made the 16.1% spread. Every flow the pack prints
is after interest and the pack anchors a cost of equity, so a firm frame on those flows counts the
debt twice at an invented WACC.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402

PACK = ("- Long-run nominal growth anchor for terminal_g: 3.75%  (asof 2026-09-23)\n"
        "- Shares outstanding: 35,200,000   [source: vendor financials]\n"
        "| FY | revenue | net income | interest expense | owner CF [Arithmetic] |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 2024 | $7.0B | $0.52B | $0.310B | $0.60B |\n"
        "| 2025 | $8.3B | $0.75B | $0.400B | $0.90B |\n"
        "\n"
        "- [Arithmetic] NET DEBT (net_debt for the firm frame, which needs a pre-interest flow): total debt "
        "$0.100B − cash $0.943B − short-term investments $0.000B (none filed) = -$0.843B (negative = net cash).\n")
FLOW = dict(base_cf=1.186, growth_rates=[0.697, 0.228, 0.167, 0.145, 0.122], terminal_g=0.0375,
            fade_years=5, shares_diluted=0.0352, sbc_treatment="deducted_in_cf")


def _dcf(wacc, exit_multiple=None, frame="equity", net_debt=None):
    kw = dict(FLOW, wacc=wacc, terminal_exit_multiple=exit_multiple, valuation_frame=frame,
              rate_type="cost_of_equity" if frame == "equity" else "true_wacc")
    if net_debt is not None:
        kw["net_debt"] = net_debt
    return fmt.unbundled_dcf(**kw)


def _snapshot(tmp_path, base, bull=None, bear=None, frame="equity", params_extra=None):
    """One desk call whose scenario results are the given desk dicts (the recorder's layout)."""
    scen = [("Base", base), ("Bull", bull), ("Bear", bear)]
    params = {"price": 1643.39, "valuation_frame": frame, "shares_diluted": 0.0352, "base_cf": 1.186,
              "scenarios": [{"name": n, "wacc": d["discount_rate_applied"]} for n, d in scen if d]}
    params.update(params_extra or {})
    call = {"tool": "run_financial_model", "params": params,
            "scenario_dcfs": [{"name": n, "dcf": d} for n, d in scen if d]}
    (tmp_path / "_research_snapshot.json").write_text(json.dumps({"calls": [call]}), encoding="utf-8")
    return tmp_path


def test_the_desk_returns_the_terminal_growth_an_exit_multiple_implies():
    d = _dcf(0.0898, 16.0)
    assert d["per_share_iv"] == 1650.07 and d["per_share_iv_gordon"] == 1891.0   # FIX s2, reproduced
    assert d["exit_implied_terminal_g"] == 0.0257 and d["exit_multiple_terminal"]["implied_terminal_g"] == 0.0257
    assert d["discount_rate_applied"] == 0.0898
    assert "exit_implied_terminal_g" not in _dcf(0.0898)                          # Gordon only
    md = fmt.format_model_results_markdown({"dcf_model": d})
    assert "implies terminal g 2.57% vs 3.75% in the Gordon leg" in md


def test_the_batch_table_prints_each_scenarios_implied_growth():
    res = fmt.execute_financial_model({
        "price": 1643.39, "valuation_frame": "equity", "rate_type": "cost_of_equity", "terminal_g": 0.0375,
        "fade_years": 5, "shares_diluted": 0.0352, "terminal_exit_multiple": 16, "sbc_treatment": "deducted_in_cf",
        "scenarios": [{"name": "Base", "prob": 0.5, "base_cf": 1.186, "growth_rates": FLOW["growth_rates"], "wacc": 0.0898},
                      {"name": "Bear", "prob": 0.5, "base_cf": 1.186, "growth_rates": [0.45, 0.08, 0.05, 0.04, 0.035],
                       "wacc": 0.1048}]})
    md = fmt.format_model_results_markdown(res)
    assert "- Base: 16.0x exit multiple implies terminal g 2.57% vs 3.75% in the Gordon leg" in md
    assert "- Bear: 16.0x exit multiple implies terminal g 3.98%" in md


def test_the_pack_line_gives_the_multiple_consistent_with_the_anchors():
    import capability_test as cap
    line = cap._default_exit_multiple_line(8.98, 0.0375)
    assert "(1 + 3.75%) / (8.98% − 3.75%) = 19.84×" in line and "terminal_reason" in line
    assert "not available" in cap._default_exit_multiple_line(None, 0.0375)
    assert "not available" in cap._default_exit_multiple_line(3.0, 0.0375)       # rate below g


def test_the_pack_prints_the_default_exit_multiple_and_the_frame_rule(screener_data_stub):
    import capability_test as cap
    pack = str(cap.build_pack("GEV"))
    assert "DEFAULT EXIT MULTIPLE" in pack
    assert "Net income is after interest, so this is an equity flow" in pack
    assert "The equity frame (the default) takes no net_debt" in pack
    for field in ('"terminal_reason":', '"interest_addback":', '"wacc_reason":'):
        assert field in cap.TASK
    assert "* Valuation Frame:" in cap.TASK and "* Terminal Growth And Multiple:" in cap.TASK


def test_fix_s2_the_16x_exit_leg_is_flagged_without_a_reason(tmp_path):
    snap = _snapshot(tmp_path, _dcf(0.0898, 16.0))
    flags, st = cv.scenario_checks(snap, {"base_iv": 1650.07}, None, PACK, 1643.39)
    assert st["base_exit_g_gap_bp"] == -118 and st["base_exit_to_gordon_multiple"] == 0.806
    assert "exit_multiple_off_default_without_reason" in flags
    flags, st = cv.scenario_checks(snap, {"base_iv": 1650.07, "terminal_multiple_reason": "peer EV/FCF 16x, dated"},
                                   None, PACK, 1643.39)
    assert "exit_multiple_off_default_without_reason" not in flags and st["base_exit_g_gap_bp"] == -118


def test_an_exit_multiple_at_the_anchor_rounding_is_clean(tmp_path):
    # AMD (c): 15x against the 15.49x the anchors imply at 10.45% -> 3.55%, 20 bp from 3.75%
    snap = _snapshot(tmp_path, _dcf(0.1045, 15.0))
    iv = _dcf(0.1045, 15.0)["per_share_iv"]
    flags, st = cv.scenario_checks(snap, {"base_iv": iv}, None, PACK, 1643.39)
    assert st["base_exit_g_gap_bp"] == -20 and "exit_multiple_off_default_without_reason" not in flags


def test_publishing_the_gordon_leg_of_a_call_with_an_exit_multiple_is_not_an_exit_choice(tmp_path):
    d = _dcf(0.0898, 16.0)
    flags, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv_gordon"]}, None, PACK, 1643.39)
    assert st["base_exit_g_gap_bp"] is None and "exit_multiple_off_default_without_reason" not in flags


def test_bull_and_bear_are_stamped_at_their_own_rates(tmp_path):
    base, bear = _dcf(0.0898, 16.0), _dcf(0.1048, 16.0)
    _, st = cv.scenario_checks(_snapshot(tmp_path, base, bear=bear),
                               {"base_iv": base["per_share_iv"], "bear_iv": bear["per_share_iv"]}, None, PACK, 1643.39)
    assert st["bear_exit_g_gap_bp"] == 23          # 16x at 10.48% implies 3.98%


def test_a_call_recorded_before_e13_still_gets_its_rate_from_the_gordon_multiple(tmp_path):
    d = _dcf(0.0898, 16.0)
    d.pop("discount_rate_applied")
    call = {"tool": "run_financial_model", "params": {"valuation_frame": "equity"}, "dcf_model": d}
    (tmp_path / "_research_snapshot.json").write_text(json.dumps({"calls": [call]}), encoding="utf-8")
    flags, st = cv.scenario_checks(tmp_path, {"base_iv": 1650.07}, None, PACK, 1643.39)
    assert st["base_exit_g_gap_bp"] == -118 and "exit_multiple_off_default_without_reason" in flags


def test_the_firm_frame_on_an_after_interest_flow_is_flagged(tmp_path):
    d = _dcf(0.0898, frame="firm", net_debt=-0.843)
    snap = _snapshot(tmp_path, d, frame="firm", params_extra={"net_debt": -0.843})
    flags, _ = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39)
    assert "firm_frame_on_equity_flow" in flags and "firm_frame_without_wacc_reason" in flags
    flags, _ = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"], "interest_addback": 0.30,
                                         "wacc_reason": "COE anchor 8.98%, Kd 6%, tax 21%, D/V 2%"},
                                  None, PACK, 1643.39)
    assert not {"firm_frame_on_equity_flow", "firm_frame_without_wacc_reason",
                "interest_addback_above_filed"} & set(flags)
    flags, _ = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"], "interest_addback": 0.55,
                                         "wacc_reason": "..."}, None, PACK, 1643.39)
    assert "interest_addback_above_filed" in flags   # more than the $0.400B filed


def test_the_equity_frame_raises_no_frame_flag(tmp_path):
    d = _dcf(0.0898)
    flags, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39)
    assert st["desk_frame"] == "equity"
    assert not [f for f in flags if f.startswith("firm_frame") or f.startswith("interest_addback")]


def test_the_pack_parsers():
    assert cv._pack_terminal_g(PACK) == 0.0375
    assert cv._pack_interest_expense_b(PACK) == 0.4
    assert cv._pack_net_debt_b(PACK) == -0.843
    old = ("- [Arithmetic] NET DEBT (default net_debt for the firm frame): total debt $2.348B − cash $5.539B "
           "− short-term investments $4.139B = -$7.330B (negative = net cash).")
    assert cv._pack_net_debt_b(old) == -7.33          # revision-8 packs still parse
    assert cv._pack_terminal_g("") is None and cv._pack_interest_expense_b("") is None


def test_the_scorecard_keeps_the_new_contract_fields():
    report = ('```json:underwriting\n{"base_iv": 100.0, "terminal_multiple_reason": "peer EV/FCF", '
              '"interest_addback": 0.3, "wacc_reason": "COE 8.98%"}\n```')
    card = cv.extract_scorecard(report, 100.0)
    assert card["terminal_multiple_reason"] == "peer EV/FCF" and card["interest_addback"] == 0.3
    assert card["wacc_reason"] == "COE 8.98%"


def _dcf_g(wacc, terminal_g):
    kw = dict(FLOW, wacc=wacc, valuation_frame="equity", rate_type="cost_of_equity")
    kw["terminal_g"] = terminal_g
    return fmt.unbundled_dcf(**kw)


def test_au_s1_terminal_growth_below_the_anchor_needs_a_reason(tmp_path):
    # revision 10: AU (b) s1 cut terminal_g to 2.5% against the 3.75% anchor; E13 pinned only the
    # exit multiple, so the 35% spread came from a knob nothing stamped
    d = _dcf_g(0.0893, 0.025)
    snap = _snapshot(tmp_path, d)
    flags, st = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"]}, None, PACK, 98.64)
    assert st["terminal_g_gap_bp"] == -125 and "terminal_g_off_anchor_without_reason" in flags
    flags, _ = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"], "terminal_reason": "dated evidence"},
                                  None, PACK, 98.64)
    assert "terminal_g_off_anchor_without_reason" not in flags


def test_terminal_growth_at_the_anchor_is_clean_and_the_old_field_name_still_counts(tmp_path):
    d = _dcf_g(0.0893, 0.0375)
    flags, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 98.64)
    assert st["terminal_g_gap_bp"] == 0 and "terminal_g_off_anchor_without_reason" not in flags
    x = _dcf(0.0898, 16.0)
    flags, _ = cv.scenario_checks(_snapshot(tmp_path, x), {"base_iv": 1650.07, "terminal_multiple_reason": "peer data"},
                                  None, PACK, 1643.39)
    assert "exit_multiple_off_default_without_reason" not in flags
