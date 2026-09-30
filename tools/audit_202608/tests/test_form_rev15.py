"""tools/audit_202608/tests/test_form_rev15.py — S3 Package B: the 13-field form, the TASK
checklist and the TOOLS schema (brief section 4, section 6 item 4).
"""
import re
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent.parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))

import analyst_tools as at
import capability_test as cap
import consensus_valuation as cv

RETIRED_FIELD_NAMES = (
    "base_iv", "bull_iv", "bear_iv", "base_probability", "bull_probability", "bear_probability",
    "base_cf_used", "base_cf_basis", "base_cf_reason", "kelly_fraction_pct", "asymmetric_payoff_skew",
    "coe_used", "coe_source", "coe_adjustment_reason", "valuation_frame", "terminal_method",
    "terminal_multiple_or_g", "fade_years", "stage1_growth_path", "guidance_deviation_reason",
    "verdict_label", "shares_basis", "shares_reason", "net_debt_reason", "scenario_deviation_reason",
    "terminal_reason", "interest_addback", "wacc_reason", "cash_flow_life", "cash_flow_life_reason",
    "finite_life_years", "bull_below_price_reason", "bear_above_price_reason",
)


def _task_contract_keys():
    m = re.search(r"```json:underwriting\s*(\{.*?\})\s*```", cap.TASK, re.DOTALL)
    assert m, "TASK has no ```json:underwriting block"
    return re.findall(r'^\s*"(\w+)":', m.group(1), re.MULTILINE)


def test_form_fields_tuple():
    assert cap.FORM_FIELDS == (
        "catalysts", "conviction_score", "business_quality_moat", "cycle_evidence", "momentum_view",
        "entry_timing", "position_basis", "momentum_evidence", "momentum_flip_condition",
        "momentum_break_rule", "invalidation_rules", "reentry_tranches", "thesis_invalidation_trigger",
    )


def test_task_contract_keys_equal_form_fields_in_order():
    assert _task_contract_keys() == list(cap.FORM_FIELDS)


def test_extract_scorecard_whitelist_still_accepts_every_form_field():
    """extract_scorecard's whitelist (unchanged, 4.1) still accepts every FORM_FIELDS key, so a
    revision-15 report's contract still parses."""
    card = cv.extract_scorecard("", 100.0)
    for f in cap.FORM_FIELDS:
        assert f in card, f"extract_scorecard no longer whitelists {f}"


def test_task_contains_no_retired_field_name():
    for name in RETIRED_FIELD_NAMES:
        assert name not in cap.TASK, f"TASK still mentions retired field {name!r}"


def test_task_precedence_and_checklist_markers():
    assert "YOU OWN THE UNDERWRITING; THE DESK DOES THE ARITHMETIC." in cap.TASK
    # revision 17: the terminal leg left the desk; checklist item 3 names terminal_ronic in its place
    assert "terminal_ronic" in cap.TASK and "terminal_leg" not in cap.TASK
    assert "cash-flow life" in cap.TASK
    for n in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8."):
        assert f"\n{n} " in cap.TASK or cap.TASK.startswith(n)


def test_research_addendum_leading_blank_lines_and_fence():
    assert cap.RESEARCH_ADDENDUM.startswith("\n\n")
    assert "```json:underwriting" in cap.RESEARCH_ADDENDUM


def test_continuation_prompt_names_every_form_field():
    """C6 (4.5): continue_report's instruction 3 is built from FORM_FIELDS at call time, and no
    longer lists the old typed fields in its source."""
    import inspect
    source = inspect.getsource(cv.continue_report)
    assert "cap.FORM_FIELDS" in source
    # The retired field list may still appear in a comment recording the old literal; it must not
    # appear as executable prompt text any more (outside the "Old literal" note).
    code_only = "\n".join(l for l in source.splitlines() if not l.strip().startswith("#"))
    assert "base_iv, bull_iv, bear_iv" not in code_only

    # Build the same instruction-3 text continue_report builds, without the network call.
    continuation_prompt = (
        "3. Conclude with SECTION 12 and the complete ```json:underwriting contract with these fields: "
        + ", ".join(cap.FORM_FIELDS) + ". The values, probabilities and Kelly size come from your desk runs; do not type them into the contract.\n\n"
    )
    for f in cap.FORM_FIELDS:
        assert f in continuation_prompt


def _run_financial_model_tool():
    return next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")


def test_tools_schema_removed_arguments():
    fm = _run_financial_model_tool()
    props = fm["function"]["parameters"]["properties"]
    for removed in ("price", "coe_anchor", "terminal_g_anchor", "base_rate_table",
                    "demonstrated_cagr_5y", "sector_multiple_band"):
        assert removed not in props, f"{removed} should have left the schema"
    assert "finite_life_years" not in props["scenarios"]["items"]["properties"]


def test_tools_schema_new_top_level_arguments_verbatim():
    fm = _run_financial_model_tool()
    props = fm["function"]["parameters"]["properties"]
    expected = {
        "cash_flow_life_reason": "Required. One dated sentence: for a finite life, the filed reserves and production rate or the remaining term; where revenue follows a commodity price, the price deck your flows assume and its source.",
        # revision 17: the BASE WINDOW CHECK sentence left (the window no longer changes the Base's arithmetic)
        "base_cf_reason": "Why a Base base_cf more than 2% from the DEFAULTS owner earnings is more representative, with the filing behind it.",
        # revision 17: a Base year 2 more than 5% from the level is held by the desk unless this reason is given
        "guidance_deviation_reason": "Dated evidence for a Base that departs from consensus: a year-2 cash flow more than 5% from the DEFAULTS year-2 level (without it the desk holds years 1-2 at the DEFAULTS levels), a Base value outside 0.75-1.33 of the reference, or Base years 3-5 above next-FY revenue growth (without it the desk holds those years at that growth).",
        "scenario_deviation_reason": "Why a Bull or Bear year-2 cash flow is more than 15% from the DEFAULTS bull2 or bear2 level.",
        "coe_adjustment_reason": "Why the Base discount rate is more than 1.5 points from the COE ANCHOR.",
        "shares_reason": "The instrument and its vesting condition, when any scenario's shares_diluted differs from the pack's count by more than 1%. Add contingent shares only in the scenarios where they vest.",
        "net_debt_reason": "Firm frame: why net_debt differs from the DEFAULTS net debt.",
        "wacc_reason": "Firm frame, required: the COE ANCHOR, the cost of debt (filed interest over debt), the tax rate and the weights behind the WACC.",
        "interest_addback": "Firm frame, required: the after-tax interest expense in $B that makes the flow pre-interest. base_cf already includes it.",
        "bull_below_price_reason": "When the Bull value is below today's price: the assumption of the market-implied path you reject, with dated evidence; when Bull is also below the lowest analyst target, what every analyst is missing.",
        "bear_above_price_reason": "When the Bear value is above today's price: why even the downside case is worth more than the price, with dated evidence.",
    }
    for name, desc in expected.items():
        assert name in props, f"missing new argument {name}"
        assert props[name]["description"] == desc, f"{name} description not verbatim"
    assert "cash_flow_life" in props
    assert props["cash_flow_life"]["type"] in ("string", ["string", "integer"])


def test_tools_schema_changed_descriptions_verbatim():
    fm = _run_financial_model_tool()
    props = fm["function"]["parameters"]["properties"]
    assert props["valuation_frame"]["description"] == (
        "'equity' (the default) discounts the pack's after-interest flows at the cost of equity; "
        "nonzero net_debt is refused. 'firm' discounts a pre-interest flow at a WACC and needs "
        "interest_addback, wacc_reason and net debt (default: the DEFAULTS net debt)."
    )
    # revision 17: the exit multiple left the schema; terminal_ronic replaces it
    assert "terminal_exit_multiple" not in props and "terminal_leg" not in props
    assert props["terminal_ronic"]["description"] == (
        "The return on new investment (a fraction, e.g. 0.12) that pays for growth from year 6 and in the "
        "terminal value. Default: the DEFAULTS terminal_ronic. A Base value more than 2 points from it needs "
        "terminal_reason."
    )
    assert props["terminal_reason"]["description"] == (
        "Dated evidence for a Base terminal_g more than 0.5 points from the DEFAULTS terminal-growth default, "
        "or for a Base terminal_ronic more than 2 points from the DEFAULTS terminal_ronic."
    )
    assert props["sbc_dilution"]["description"] == (
        "Share dilution from SBC when sbc_treatment is 'add_back_dilution': a fraction below 1 (0.02 = 2%) or a "
        "whole number of new shares. Must NOT be passed if sbc_treatment is 'deducted_in_cf'."
    )
    assert props["fade_years"]["description"] == (
        "Duration of Stage 2 linear fade in years (integer >= 0). Fades linearly from the last explicit rate to "
        "terminal_g; the return on new investment and a cyclical margin move to their long-run values over the "
        "same years."
    )
    assert props["shares_diluted"]["description"] == (
        # S3 C review (2026-09-28): 5.11 made the desk's default the DEFAULTS shares_default.
        # Revision 16 (brief_rev16.md): the text says what the pack says about the count's unit.
        "Optional. The desk uses the DEFAULTS block's shares_default when you leave it out. "
        "shares_default is a whole share count, for example 79,364,362; billions are also accepted. "
        "Pass it only for a different count, with shares_reason."
    )
    assert props["net_debt"]["description"] == (
        "Firm frame only, in $B; default: the DEFAULTS net debt. Must be 0 or omitted in the equity frame."
    )
    # Revision 16 (brief_rev16.md): exactly three entries, one each with role Base, Bull and Bear.
    assert props["scenarios"]["description"] == (
        "Exactly three entries, one each with role Base, Bull and Bear. Each entry: name, prob, "
        "base_cf ($B), explicit_growth (5 annual growth rates of base_cf, cash flow not revenue), "
        "fade_years, wacc (the discount rate), terminal_g, and optionally terminal_ronic "
        "and shares_diluted. The desk computes every value, the reverse DCF and Kelly "
        "sizing in one call."
    )
    sc_props = props["scenarios"]["items"]["properties"]
    assert sc_props["shares_diluted"]["description"] == (
        "Only for a contingent instrument that vests in this scenario, as a whole share count, for "
        "example 79,364,362; billions are also accepted. Needs shares_reason."
    )
    assert "terminal_exit_multiple" not in sc_props and "terminal_leg" not in sc_props
    assert sc_props["terminal_ronic"]["description"] == (
        "Return on new investment for this scenario, as a fraction. Default: the DEFAULTS terminal_ronic."
    )


def test_tools_schema_required_list():
    fm = _run_financial_model_tool()
    assert fm["function"]["parameters"]["required"] == [
        "cash_flow_life", "cash_flow_life_reason", "terminal_g", "fade_years", "sbc_treatment"
    ]


def test_tools_run_financial_model_description_verbatim():
    fm = _run_financial_model_tool()
    assert fm["function"]["description"] == (
        "Run the Python desk. One call values Base, Bull and Bear together: each scenario's "
        "base_cf, five years of cash-flow growth, fade, discount rate and terminal growth (with an "
        "optional terminal_ronic) give its per-share value. The desk also returns the reverse DCF "
        "(the growth today's price implies, under your structure and under the neutral reference) "
        "and quarter-Kelly sizing. The harness supplies today's price, the pack's share count, the "
        "anchors and the base-rate table; pass only your decisions. An input that departs from its "
        "DEFAULT needs its reason argument: the desk names any that are missing, and a refused call "
        "does not use one of your desk runs. The desk holds Base years 3-5 at next-FY consensus "
        "revenue growth unless guidance_deviation_reason is given, and shows the value on your path "
        "beside it. It holds the Base's years 1-2 at the DEFAULTS cash-flow levels the same way (a "
        "Base year 2 more than 5% away). It deducts the DEFAULTS working capital in years 1-5 (not "
        "when base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or "
        "reference_base_b) and pays for growth from year 6 at terminal_ronic. "
        "It values at the base fiscal year end and rolls the value forward to today. The firm frame "
        "uses the same long run, an approximation: the return on new investment is measured on "
        "tangible invested capital before interest and applied to equity earnings, which is conservative "
        "for a levered company. Base is every scenario not named Bull or Bear. "
        "Blend mode combines named desk legs for display; it is never your answer."
    )


def test_research_tools_unchanged():
    """search_web and fetch_page (research_tools()) are untouched by this step."""
    names = [t["function"]["name"] for t in at.research_tools()]
    assert names == ["search_web", "fetch_page"]
