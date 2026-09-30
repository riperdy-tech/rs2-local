"""Phase 4 E13 (joint FIX (c) review with Fable, 2026-09-25): one anchored terminal, and the equity
frame as the default.

FIX s1 and s2 had identical flows, growth, rate and shares; s2 published the exit leg at 16x
against the 19.84x the anchors imply, which alone made the 16.1% spread. Every flow the pack prints
is after interest and the pack anchors a cost of equity, so a firm frame on those flows counts the
debt twice at an invented WACC.
"""
import json
import math
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402

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


def _dcf(wacc, frame="equity", net_debt=None, **extra):
    """Revision 17: the exit multiple left the desk, so the helper takes none. `extra` passes a desk input such as
    terminal_ronic (math.inf reproduces the unfunded arithmetic the FIX s1 figure below was computed with)."""
    kw = dict(FLOW, wacc=wacc, valuation_frame=frame,
              rate_type="cost_of_equity" if frame == "equity" else "true_wacc", **extra)
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


def test_the_desk_result_carries_one_terminal_and_no_exit_fields():
    """FIX s1 (Gordon, 8.98%, unfunded terminal) is reproduced; the exit leg FIX s2 published (16x) cannot exist now."""
    # unlimited returns at both ends of the long run (the record's median return is +inf) is the unfunded arithmetic
    d = _dcf(0.0898, terminal_ronic=math.inf, long_run={"r_tc": math.inf})
    assert d["per_share_iv"] == 1891.0 and d["per_share_iv_gordon"] == 1891.0   # FIX s1, reproduced
    assert d["discount_rate_applied"] == 0.0898
    for gone in ("exit_implied_terminal_g", "exit_multiple_terminal", "per_share_iv_exit", "terminal_leg"):
        assert gone not in d
    md = fmt.format_model_results_markdown({"dcf_model": d})
    assert "exit" not in md.lower() and "Exit Multiple" not in md


# S3 A+B (brief §3.2, §3.3, §3.5 R6): price comes from context now; cash_flow_life and its reason
# are required. Revision 17: the batch table prints no exit-multiple line (there is no exit multiple).
def test_the_batch_table_prints_no_exit_multiple_lines():
    res = fmt.execute_financial_model({
        "valuation_frame": "equity", "rate_type": "cost_of_equity", "terminal_g": 0.0375,
        "fade_years": 5, "shares_diluted": 0.0352, "sbc_treatment": "deducted_in_cf",
        "cash_flow_life": "perpetual", "cash_flow_life_reason": "test",
        "base_cf_reason": "test", "terminal_reason": "test", "bear_above_price_reason": "test",
        "scenarios": [{"name": "Base", "prob": 0.5, "base_cf": 1.186, "growth_rates": FLOW["growth_rates"], "wacc": 0.0898},
                      # revision 16: a call that sends scenarios needs Bull too (not under test here)
                      {"name": "Bull", "prob": 0.25, "base_cf": 1.186 * 1.2, "growth_rates": FLOW["growth_rates"], "wacc": 0.0898},
                      {"name": "Bear", "prob": 0.25, "base_cf": 1.186, "growth_rates": [0.45, 0.08, 0.05, 0.04, 0.035],
                       "wacc": 0.1048}]},
        context={"price": 1643.39, "terminal_ronic": math.inf})
    md = fmt.format_model_results_markdown(res)
    assert "Batch Scenario DCF Valuation Table" in md
    assert "exit multiple" not in md and "implies terminal g" not in md


# S3 A+B (brief §3.3, §4.2): terminal_reason/interest_addback/wacc_reason are now call arguments
# on the desk's TOOLS schema, not contract fields typed into the TASK's JSON block; the "Valuation
# Frame"/"Terminal Growth And Multiple" doctrine is now the Frame/Terminal value sub-bullets of
# checklist item 3.
# S3 C (brief §5.3, §5.6): SECTION 6's NET DEBT line drops its "equity frame"/"firm frame" rule
# sentences; both rules live in the DEFAULTS block (§5.2) instead. Revision 17: SECTION 1.5 no longer
# prints a default exit multiple and the DEFAULTS block no longer carries one.
def test_the_pack_prints_no_default_exit_multiple_and_keeps_the_frame_rule(screener_data_stub):
    pack = str(cap.build_pack("GEV"))
    assert "exit multiple" not in pack.lower() and "default_exit_multiple" not in pack
    assert "Net income is after interest, so this is an equity flow" not in pack
    assert "The equity frame (the default) takes no net_debt" not in pack
    fm = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")
    props = fm["function"]["parameters"]["properties"]
    for field in ("terminal_reason", "interest_addback", "wacc_reason", "terminal_ronic"):
        assert field in props
    for gone in ("terminal_exit_multiple", "terminal_leg"):
        assert gone not in props
    assert "Frame: every flow in this pack is after interest, so value it in the equity frame." in cap.TASK
    assert "Terminal value: do not clamp terminal growth or impose multiple ceilings on durable compounders" in cap.TASK
    assert "exit multiple" not in cap.TASK and "terminal_leg" not in cap.TASK


DEFAULT_RONIC_FACTS = {"terminal_ronic": 0.10, "terminal_g_default": 0.0375}


def test_a_base_terminal_ronic_more_than_two_points_off_the_default_is_flagged_without_a_reason(tmp_path):
    """Revision 17 (brief B 6): terminal_ronic_off_default_without_reason replaces the exit-multiple flag."""
    d = _dcf(0.0898, terminal_ronic=0.20)
    snap = _snapshot(tmp_path, d)
    facts = dict(pack_facts.empty(), **DEFAULT_RONIC_FACTS)
    flags, st = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=facts)
    assert st["terminal_ronic"] == 0.2 and st["terminal_ronic_gap_pts"] == 10.0
    assert "terminal_ronic_off_default_without_reason" in flags
    flags, _ = cv.scenario_checks(snap, {"base_iv": d["per_share_iv"], "terminal_reason": "returns above 20% for a decade"},
                                  None, PACK, 1643.39, facts=facts)
    assert "terminal_ronic_off_default_without_reason" not in flags


def test_a_terminal_ronic_within_two_points_is_clean_and_an_unlimited_one_is_stamped(tmp_path):
    facts = dict(pack_facts.empty(), **DEFAULT_RONIC_FACTS)
    d = _dcf(0.0898, terminal_ronic=0.11)
    flags, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=facts)
    assert st["terminal_ronic_gap_pts"] == 1.0 and "terminal_ronic_off_default_without_reason" not in flags
    d = _dcf(0.0898, terminal_ronic=math.inf)               # the desk echoes "unlimited", never a bare infinity
    assert d["terminal_ronic"] == "unlimited"
    flags, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=facts)
    assert st["terminal_ronic"] == "unlimited" and st["terminal_ronic_gap_pts"] == "unlimited"
    assert "terminal_ronic_off_default_without_reason" in flags
    # an unlimited default and an unlimited Base agree
    facts_inf = dict(facts, terminal_ronic=math.inf)
    flags, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=facts_inf)
    assert st["terminal_ronic_gap_pts"] is None and "terminal_ronic_off_default_without_reason" not in flags


def test_the_revision_17_stamps_are_carried_from_the_desk_and_the_facts(tmp_path):
    facts = dict(pack_facts.empty(), terminal_ronic=0.10, base_year_cap={"removed": 0.1, "ni_filed": 0.4,
                                                                          "ni_capped": 0.3, "eps_filed": 5.78,
                                                                          "eps_vendor": 5.08},
                 long_run={"cycle": True, "e5": 1.0})
    d = _dcf(0.0898, terminal_ronic=0.10, working_capital=[0.01, 0.02, 0.03, 0.04, 0.05])
    d["stamps"].append("years12_held_by_desk")
    _, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=facts)
    assert st["working_capital_deducted"] == [0.01, 0.02, 0.03, 0.04, 0.05]
    assert st["years12_held_by_desk"] is True and st["base_year_capped"] is True
    assert st["long_run_facts"] == {"cycle": True, "e5": 1.0}
    assert "years12_held_by_desk" in st["desk_stamps"] and "working_capital_deducted" in st["desk_stamps"]
    # a return on negative tangible equity is +inf in the facts; the verdict is JSON the site parses (no Infinity)
    inf_facts = dict(facts, long_run={"cycle": False, "r_tc": math.inf})
    _, st_inf = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39, facts=inf_facts)
    assert st_inf["long_run_facts"] == {"cycle": False, "r_tc": "+inf"}
    json.dumps(st_inf, allow_nan=False)
    # no snapshot: the stamps exist and are empty, the facts' are still carried
    _, none = cv.scenario_checks(tmp_path / "nowhere", {"base_iv": 1.0}, None, PACK, 1.0, facts=facts)
    assert none["terminal_ronic"] is None and none["years12_held_by_desk"] is None
    assert none["base_year_capped"] is True and none["long_run_facts"] == {"cycle": True, "e5": 1.0}


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
    # the contract's old field name still counts as a reason for a terminal_g departure
    d2 = _dcf_g(0.0893, 0.025)
    flags, _ = cv.scenario_checks(_snapshot(tmp_path, d2), {"base_iv": d2["per_share_iv"],
                                                            "terminal_multiple_reason": "peer data"}, None, PACK, 98.64)
    assert "terminal_g_off_anchor_without_reason" not in flags


def test_terminal_growth_default_parser_and_gap_measuring(tmp_path):
    """T1: _pack_terminal_g returns default when present, else anchor;
    terminal_g_gap_bp and terminal_g_off_anchor_without_reason measure against default."""
    pack_with_default = (
        "- Long-run nominal growth anchor for terminal_g: 3.75%  (asof 2026-09-23)\n"
        "- TERMINAL-GROWTH DEFAULT for this name: 2.34% — next-FY consensus revenue growth (0.9%) is below the anchor, "
        "so the default is the year-5 growth floored at zero real growth (10-year breakeven inflation 2.34%). "
        "terminal_g more than 0.5 points above or below it needs terminal_reason with dated evidence.\n"
        "- Shares outstanding: 35,200,000   [source: vendor financials]\n"
    )
    # Parser returns default (2.34%) when printed
    assert cv._pack_terminal_g(pack_with_default) == pytest.approx(0.0234)
    # Parser falls back to anchor (3.75%) when default is not printed
    assert cv._pack_terminal_g(PACK) == 0.0375

    # At the default (2.34%), terminal_g_gap_bp is 0 and no flag fires
    d_at_default = _dcf_g(0.0893, 0.0234)
    snap_def = _snapshot(tmp_path, d_at_default)
    flags, st = cv.scenario_checks(snap_def, {"base_iv": d_at_default["per_share_iv"]}, None, pack_with_default, 98.64)
    assert st["terminal_g_gap_bp"] == 0
    assert "terminal_g_off_anchor_without_reason" not in flags

    # At the old anchor (3.75%), which is +141 bp from default 2.34%, flag fires without reason
    d_at_anchor = _dcf_g(0.0893, 0.0375)
    snap_anc = _snapshot(tmp_path, d_at_anchor)
    flags, st = cv.scenario_checks(snap_anc, {"base_iv": d_at_anchor["per_share_iv"]}, None, pack_with_default, 98.64)
    assert st["terminal_g_gap_bp"] == 141
    assert "terminal_g_off_anchor_without_reason" in flags

    # Providing terminal_reason clears the flag
    flags, _ = cv.scenario_checks(snap_anc, {"base_iv": d_at_anchor["per_share_iv"], "terminal_reason": "secular volume rebound"},
                                  None, pack_with_default, 98.64)
    assert "terminal_g_off_anchor_without_reason" not in flags


def test_mo_pack_terminal_growth_default():
    """T1 verification on saved pack scratchpad/draw_previews/MO_pack.md inputs: MO's default is 2.34% (the
    consensus fallback rule; revision 17 keeps it for a name with no revenue trend). The exit multiple this
    test also checked left the desk and the pack in revision 17."""
    import consensus_reference as cref

    # MO inputs: anchor 0.0375, breakeven 0.0234, rev_g2 0.009, median_5y 0.043, COE 7.51%
    mo_anchor = 0.0375
    mo_breakeven = 0.0234
    mo_rev_g2 = 0.009
    mo_median_5y = 0.043

    val, reason = cref.terminal_default(mo_anchor, mo_breakeven, mo_rev_g2, mo_median_5y)
    assert val == 0.0234
    assert reason == "next-FY consensus revenue growth (0.9%) is below the anchor"

    # Reading the saved pack file directly if available
    mo_pack_path = Path(__file__).resolve().parents[4] / "draw_previews" / "MO_pack.md"
    if mo_pack_path.exists():
        mo_text = mo_pack_path.read_text(encoding="utf-8")
        assert cv.next_fy_revenue_growth(mo_text) == 0.009
        assert "10-Year Breakeven Inflation Rate: 2.34%" in mo_text
        assert "COE ANCHOR for this name: rf 5.01% + adjusted loading 0.575× (Blume: 0.67 × raw 0.365 + 0.33) × implied ERP 4.35% = 7.51%" in mo_text
