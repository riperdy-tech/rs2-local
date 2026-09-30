"""Revision 17, brief C6: a refusal names every rule the obvious correction would trip (R13/R14), and the loop guard.

The DEFAULTS Bear and Bull values are checked against direct unbundled_dcf calls, not against the desk's own closure."""
import copy
import io
import json
import math
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from financial_model_tool import execute_financial_model, unbundled_dcf  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN, _ctx, _happy_params  # noqa: E402

GENERIC_TAIL = "Call again with the same inputs and these reasons, or change an input with dated evidence."
ADVISED_TAIL = "Call again with the same inputs and these reasons."


def _value(role_level_year2, wacc, cf=5.0, year1=5.25, tail=(0.02, 0.02, 0.02), tg=0.03, fade=0):
    """Direct desk arithmetic for a path with year 1 at the Base's level, year 2 at `role_level_year2` and years 3-5 the
    Base's (the DEFAULTS scenario of brief C6), on _ctx()'s defaults."""
    return unbundled_dcf(base_cf=cf, explicit_growth=[year1 / cf - 1, role_level_year2 / year1 - 1, *tail], wacc=wacc,
                         terminal_g=tg, shares_diluted=1.0, fade_years=fade, sbc_treatment="deducted_in_cf",
                         terminal_ronic=math.inf)["per_share_iv"]


CTX = _ctx()
BEAR_A, BEAR_B = _value(CTX["levels"]["bear2"], 0.10), _value(CTX["levels"]["bear2"] * 0.85, 0.10)          # 68.06, 58.57
BULL_A, BULL_B = _value(CTX["levels"]["bull2"], 0.075), _value(CTX["levels"]["bull2"] * 1.15, 0.075)        # 125.63, 143.74


def _params(mutate=None, reasons=()):
    p = _happy_params(**{k: "t" for k in reasons})
    if mutate:
        mutate(p)
    return p


def _refusal(price, reasons=(), ctx_over=None, mutate=None):
    return execute_financial_model(_params(mutate, reasons), context=_ctx(price=price, **(ctx_over or {})))


def _accepted_values(mutate=None, price=1000.0):
    """The per-share values of a call with every reason given (no refusal), by scenario name."""
    res = execute_financial_model(_params(mutate, _ALL_REASONS_GIVEN), context=_ctx(price=price))
    assert "error" not in res, res.get("error")
    return {s["name"]: s["dcf"]["per_share_iv"] for s in res["scenario_dcfs"]}


def _advice(res, reason):
    """The advice the desk computed for `reason`: kept in `_audit_advice`, which the harness does not show the model, and
    present exactly once in the refusal's text."""
    text = res["_audit_advice"][reason]
    assert res["error"].count(text) == 1
    assert all("advice" not in n for n in res["needs_reasons"])
    return text


def _money(x):
    return f"${x:,.2f}"


# ---- the numbers -----------------------------------------------------------------------------------------------

def test_the_reference_values_this_module_checks_against_are_the_expected_ones():
    assert (BEAR_A, BEAR_B) == (68.06, 58.57) and (BULL_A, BULL_B) == (125.63, 143.74)


def test_the_defaults_bear_is_what_a_bear_at_bear2_is_worth_in_the_desk_itself():
    """`a` and `b` are the per-share values the desk gives a Bear whose year 2 is bear2 and bear2 x 0.85."""
    for level, want in ((CTX["levels"]["bear2"], BEAR_A), (CTX["levels"]["bear2"] * 0.85, BEAR_B)):
        def mutate(p, level=level):
            for sc in p["scenarios"]:
                if sc["name"] == "Bear":
                    sc["explicit_growth"] = [5.25 / 5 - 1, level / 5.25 - 1, 0.02, 0.02, 0.02]
        assert _accepted_values(mutate)["Bear"] == want


# ---- Bear above the price ---------------------------------------------------------------------------------------

def test_bear_whose_defaults_and_band_edge_both_sit_above_the_price_gets_sentences_1_and_2():
    p = 50.0                                                            # above neither a nor b
    res = _refusal(p)
    adv = _advice(res, "bear_above_price_reason")
    assert adv == (f"The DEFAULTS Bear for this name is {_money(BEAR_A)}, above today's price {_money(p)}: keep the "
                   f"defaults and give bear_above_price_reason (why the downside is limited), or build a deeper Bear "
                   f"outside the band with scenario_deviation_reason and dated evidence. No Bear within 15% of bear2 "
                   f"lands below {_money(p)} (the band's lowest is {_money(BEAR_B)}); lowering it further needs "
                   f"scenario_deviation_reason as well.")
    err = res["error"]
    assert ("bear_above_price_reason needed: the Bear value is 23.1% above today's price. " + adv) in err
    assert err.endswith(" " + ADVISED_TAIL) and GENERIC_TAIL not in err


def test_bear_defaults_above_the_price_but_band_edge_below_gets_sentences_1_and_3():
    p = 60.0                                                            # BEAR_B (58.57) < 60 < BEAR_A (68.06)
    adv = _advice(_refusal(p), "bear_above_price_reason")
    assert adv == (f"The DEFAULTS Bear for this name is {_money(BEAR_A)}, above today's price {_money(p)}: keep the "
                   f"defaults and give bear_above_price_reason (why the downside is limited), or build a deeper Bear "
                   f"outside the band with scenario_deviation_reason and dated evidence. Lowering the Bear to "
                   f"{_money(BEAR_B)} or below within the band clears this without another reason.")


def test_a_bear_above_the_price_whose_defaults_clear_it_gets_sentence_3_alone():
    def richer(p):                                                      # a Bear valued above the DEFAULTS Bear (year 2 in band)
        for sc in p["scenarios"]:
            if sc["name"] == "Bear":
                sc["explicit_growth"] = [0.0, 0.0, 0.06, 0.06, 0.06]
    a, b = BEAR_A, BEAR_B
    bear_iv = _accepted_values(richer)["Bear"]
    price = (a + bear_iv) / 2                                           # the DEFAULTS Bear is below it; the call's Bear is not
    res = _refusal(price, mutate=richer)
    assert bear_iv > price > a                                          # the fixture is what it claims to be
    assert _advice(res, "bear_above_price_reason") == (
        f"Lowering the Bear to {_money(b)} or below within the band clears this without another reason.")


def test_bear_reasons_given_means_no_refusal_and_no_advice():
    res = _refusal(50.0, reasons=("bear_above_price_reason",))
    assert "error" not in res, res.get("error")


# ---- Bull below the price (the mirror) --------------------------------------------------------------------------

def test_bull_whose_defaults_and_band_edge_both_sit_below_the_price_gets_sentences_1_and_2():
    p = 160.0                                                           # above BULL_B (143.74)
    adv = _advice(_refusal(p), "bull_below_price_reason")
    assert adv == (f"The DEFAULTS Bull for this name is {_money(BULL_A)}, below today's price {_money(p)}: keep the "
                   f"defaults and give bull_below_price_reason (why the upside is limited), or build a higher Bull "
                   f"outside the band with scenario_deviation_reason and dated evidence. No Bull within 15% of bull2 "
                   f"lands above {_money(p)} (the band's highest is {_money(BULL_B)}); raising it further needs "
                   f"scenario_deviation_reason as well.")


def test_bull_defaults_below_the_price_but_band_edge_above_gets_sentences_1_and_3():
    p = 140.0                                                           # BULL_A (125.63) < 140 < BULL_B (143.74)
    adv = _advice(_refusal(p), "bull_below_price_reason")
    assert adv == (f"The DEFAULTS Bull for this name is {_money(BULL_A)}, below today's price {_money(p)}: keep the "
                   f"defaults and give bull_below_price_reason (why the upside is limited), or build a higher Bull "
                   f"outside the band with scenario_deviation_reason and dated evidence. Raising the Bull to "
                   f"{_money(BULL_B)} or above within the band clears this without another reason.")


def test_a_bull_below_the_price_whose_defaults_clear_it_gets_sentence_3_alone():
    def poorer(p):                                                      # a Bull valued below the DEFAULTS Bull
        for sc in p["scenarios"]:
            if sc["name"] == "Bull":
                sc["explicit_growth"] = [0.10, 0.0909, 0.0, 0.0, 0.0]
    a, b = _value(CTX["levels"]["bull2"], 0.075), _value(CTX["levels"]["bull2"] * 1.15, 0.075)
    bull_iv = _accepted_values(poorer)["Bull"]
    price = (bull_iv + a) / 2
    assert bull_iv < price < a
    assert _advice(_refusal(price, mutate=poorer), "bull_below_price_reason") == (
        f"Raising the Bull to {_money(b)} or above within the band clears this without another reason.")


# ---- what the refusal lists and how it ends -----------------------------------------------------------------------

def test_every_reason_is_still_listed_at_once_and_the_generic_clause_goes_when_advice_applies():
    def wide(p):
        for sc in p["scenarios"]:
            if sc["name"] == "Base":
                sc["wacc"] = 0.12                                       # Base rate 4 points from the anchor: R4
    res = _refusal(50.0, mutate=wide)
    reasons = [n["reason"] for n in res["needs_reasons"]]
    assert "coe_adjustment_reason" in reasons and "bear_above_price_reason" in reasons
    assert res["error"].endswith(" " + ADVISED_TAIL) and GENERIC_TAIL not in res["error"]
    assert set(res["_audit_advice"]) == {"bear_above_price_reason"}


def test_a_refusal_with_no_computed_alternative_keeps_the_generic_clause():
    def wide(p):
        for sc in p["scenarios"]:
            if sc["name"] == "Base":
                sc["wacc"] = 0.12
    res = _refusal(100.0, reasons=("bear_above_price_reason", "bull_below_price_reason"), mutate=wide)
    reasons = [n["reason"] for n in res["needs_reasons"]]
    assert "coe_adjustment_reason" in reasons and not {"bear_above_price_reason", "bull_below_price_reason"} & set(reasons)
    assert res["error"].endswith(GENERIC_TAIL)
    missing = _happy_params()
    del missing["cash_flow_life"]
    assert execute_financial_model(missing, context=CTX)["error"].endswith(GENERIC_TAIL)


def test_no_printed_levels_means_nothing_computed_and_the_old_text():
    res = _refusal(50.0, ctx_over={"levels": {}})
    assert "_audit_advice" not in res
    assert res["error"].endswith(GENERIC_TAIL)
    only_year2 = _refusal(50.0, ctx_over={"levels": {"year1": 5.25, "year2": 5.5125}})
    assert "_audit_advice" not in only_year2


def test_the_advice_is_shown_to_the_model_once_and_the_audit_copy_is_not():
    res = _refusal(50.0)
    msg, _ = at.tool_message("run_financial_model", {}, res)
    assert msg.count("The DEFAULTS Bear for this name is") == 1 and "_audit_advice" not in msg


def test_the_reason_text_itself_is_unchanged_and_carries_no_per_share_value():
    res = _refusal(50.0)
    why = next(n["why"] for n in res["needs_reasons"] if n["reason"] == "bear_above_price_reason")
    assert why == "the Bear value is 23.1% above today's price"


def test_advice_never_leaves_a_compute_error_behind():
    """The DEFAULTS run can fail (a wacc at or below terminal_g, say): the refusal is then the old one, not a refusal
    for the failure."""
    # the DEFAULTS run uses terminal_g_default (0.11 here), above the Bear's own rate (0.10): it cannot be valued
    res = _refusal(50.0, reasons=("terminal_reason",), ctx_over={"terminal_g_default": 0.11})
    assert res["validation_error"] is True and not res["missing"]
    assert [n["reason"] for n in res["needs_reasons"]] == ["bear_above_price_reason"]
    assert "_audit_advice" not in res
    assert res["error"].endswith(GENERIC_TAIL)


# ---- the loop guard ---------------------------------------------------------------------------------------------

GUARD = "The same rules fired after you changed inputs; give the reasons named above with the inputs you have."


def _refused(*reasons):
    return {"error": "Not accepted as a desk run. x.", "validation_error": True,
            "needs_reasons": [{"reason": r, "why": "w"} for r in reasons]}


def test_the_guard_fires_on_the_same_reasons_after_changed_inputs_only():
    g = at.desk_loop_guard
    first, prev = g(_refused("bear_above_price_reason"), "call-1", None)
    assert GUARD not in first["error"]
    second, prev = g(_refused("bear_above_price_reason"), "call-2", prev)
    assert second["error"].endswith(" " + GUARD)
    assert at.DESK_LOOP_GUARD == GUARD
    third, prev = g(_refused("bear_above_price_reason"), "call-2", prev)                # the same inputs again: no walk
    assert GUARD not in third["error"]
    fourth, prev = g(_refused("scenario_deviation_reason"), "call-3", prev)             # another reason set
    assert GUARD not in fourth["error"]
    fifth, prev = g(_refused("scenario_deviation_reason", "bear_above_price_reason"), "call-4", prev)
    assert GUARD not in fifth["error"]
    sixth, prev = g(_refused("bear_above_price_reason", "scenario_deviation_reason"), "call-5", prev)   # same set, any order
    assert sixth["error"].endswith(" " + GUARD)


def test_a_refusal_without_reasons_is_not_tracked_and_breaks_the_run():
    g = at.desk_loop_guard
    _, prev = g(_refused("bear_above_price_reason"), "call-1", None)
    missing_only = {"error": "Not accepted. missing x.", "validation_error": True, "missing": ["x"], "needs_reasons": []}
    res, prev = g(missing_only, "call-2", prev)
    assert res is missing_only and prev is None
    again, prev = g(_refused("bear_above_price_reason"), "call-3", prev)
    assert GUARD not in again["error"]


def test_the_guard_in_the_analyst_loop_resets_on_an_accepted_call(monkeypatch, tmp_path):
    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def bear(growth3):
        p = _happy_params()
        for sc in p["scenarios"]:
            if sc["name"] == "Bear":
                sc["explicit_growth"] = [0.0, 0.0, growth3, growth3, growth3]
        return p

    ok = _happy_params(**_ALL_REASONS_GIVEN)
    calls = [bear(-0.02), bear(-0.01), bear(-0.01), ok, bear(-0.02), bear(-0.03)]   # refused x3, accepted, refused x2
    turns = [{"message": {"content": "", "tool_calls": [{"function": {"name": "run_financial_model",
                                                                     "arguments": copy.deepcopy(c)}}]},
              "done_reason": "stop", "eval_count": 10, "eval_duration": 100_000_000} for c in calls]
    turns.append({"message": {"content": "# MEMO\n" + "x" * 6000, "tool_calls": []}, "done_reason": "stop",
                  "eval_count": 500, "eval_duration": 1_000_000_000})
    idx = [0]

    def fake_urlopen(req, timeout=None):
        i = idx[0]
        idx[0] += 1
        return _FakeResp(json.dumps(turns[min(i, len(turns) - 1)]).encode("utf-8"))

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    at.chat_with_tools("test-model", "test-pack", tmp_path, verbose=False, desk_context=_ctx(price=50.0))
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    errors = [c.get("error") or "" for c in snap]
    assert len(snap) == 6
    assert GUARD not in errors[0]                       # first refusal
    assert errors[1].endswith(GUARD)                    # same reasons, inputs changed
    assert GUARD not in errors[2]                       # identical to the call before: a repeat, not a walk
    assert not errors[3]                                # accepted: the run of refusals ends
    assert GUARD not in errors[4]                       # a refusal again, but the first of a new run
    assert errors[5].endswith(GUARD)


# ---- the preview's UGI sample 1: the four refusals, replayed through this desk --------------------------------------

UGI = json.loads((Path(__file__).resolve().parent / "fixture_data" / "ugi_preview_desk_calls.json").read_text(encoding="utf-8"))


def _ugi_context():
    f = UGI["facts"]
    return {"price": UGI["price"], "shares_default_b": f["shares_default"] / 1e9, "coe_anchor": f["coe_anchor"],
            "terminal_g_default": f["terminal_g_default"], "terminal_g_anchor": f["terminal_g_anchor"],
            "base_rate_table": f["base_rate_5y"], "revenue_cagr_5y_pct": f["revenue_cagr_5y_pct"],
            "net_debt_default_b": f["net_debt_b"], "interest_expense_latest_b": f["interest_expense_latest_b"],
            "owner_earnings_default_b": f["owner_earnings_default_b"], "base_window": f["base_window"],
            "consensus_implied_value": f["consensus_implied_value"], "levels": f["levels"],
            # the revision-16 pack has no through-cycle facts: +inf on both returns is the unfunded arithmetic the
            # revision-16 desk computed, so the calls value as they did in the preview
            "terminal_ronic": math.inf, "long_run": {"r_tc": math.inf}, "working_capital": None,
            "cash_basis_b": f["cash_basis_b"], "years35_cap": f["next_fy_revenue_growth"],
            "shares_warning": f["shares_warning"]}


def test_ugis_four_refusals_replay_to_the_preview_percentages_and_the_new_texts():
    ctx = _ugi_context()
    lv = ctx["levels"]
    # the DEFAULTS Bear by hand: year 1 and the Base's years 3-5 as in the calls (0.055 x 3), fade 5, the default terminal_g
    def bear(year2):
        return unbundled_dcf(base_cf=0.357, explicit_growth=[lv["year1"] / 0.357 - 1, year2 / lv["year1"] - 1, 0.055, 0.055, 0.055],
                             wacc=0.0772, terminal_g=ctx["terminal_g_default"], shares_diluted=ctx["shares_default_b"],
                             fade_years=5, sbc_treatment="deducted_in_cf", terminal_ronic=math.inf,
                             long_run={"r_tc": math.inf})["per_share_iv"]
    a, b = bear(lv["bear2"]), bear(lv["bear2"] * 0.85)
    assert a > UGI["price"] and b > UGI["price"]                       # UGI's own DEFAULTS Bear sits above its price
    sentence_1 = (f"The DEFAULTS Bear for this name is {_money(a)}, above today's price $36.51: keep the defaults and "
                  f"give bear_above_price_reason (why the downside is limited), or build a deeper Bear outside the "
                  f"band with scenario_deviation_reason and dated evidence.")
    sentence_2 = (f"No Bear within 15% of bear2 lands below $36.51 (the band's lowest is {_money(b)}); lowering it "
                  f"further needs scenario_deviation_reason as well.")
    last, results = None, []
    for call in UGI["calls"]:
        p = copy.deepcopy(call["params"])
        key = json.dumps(p, sort_keys=True, default=str)
        res = execute_financial_model(p, context=ctx)
        res, last = at.desk_loop_guard(res, key, last)
        results.append((call["recorded_error"], res["error"]))
    pct = [("9.4%", "above"), ("19.9%", "from"), ("3.5%", "above"), ("28.3%", "from")]
    for (before, after), (p, _) in zip(results, pct):
        assert p in before and p in after                               # the replay reproduces the preview's numbers
    # refusals 1 and 3 (the Bear above the price): both sentences, and no generic clause
    for i in (0, 2):
        after = results[i][1]
        assert "bear_above_price_reason needed: the Bear value is" in after
        assert sentence_1 + " " + sentence_2 in after
        assert after.endswith(" " + ADVISED_TAIL) and GENERIC_TAIL not in after
        assert results[i][0].endswith(GENERIC_TAIL)                     # what the preview's refusal said
    # refusals 2 and 4 (the Bear lowered outside the band): the year-2 rule alone, as before; no rule above applies
    for i in (1, 3):
        assert results[i][1] == results[i][0]
        assert GUARD not in results[i][1]                               # the reasons alternate: nothing to guard
