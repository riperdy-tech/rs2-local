"""tools/audit_202608/tests/test_contract_fill.py — Unit and integration tests for contract_fill.

Covers:
1. Synthetic calls: one per rule (joint, scenario-wise, no desk run, later non-joint,
   blend matched/not, leg nearest/primary, finite life, exit leg multiple/input, rate from input,
   capped Base applied path, coe_source gaps, shares_basis 1.0%/1.1%/None/0, verdict_label +-10%,
   skew Bear at/above price, typed value matches no desk value).
2. Three real samples: UGI s1, FIX s1, EZPW s1 verbatim desk calls against golden entries.
3. fiduciary_gate: payoff_skew against old inline logic across 20+ varied inputs.
4. disagrees: at each tolerance's edge.
5. main() integration with recorded-style mock.
"""
import copy
import json
from pathlib import Path
import random
import sys
import pytest

_HERE = Path(__file__).resolve().parent.parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))

import contract_fill
import fiduciary_gate as fg
import consensus_valuation as cv
import analyst_tools as at


# ==============================================================================
# Helper to build minimal synthetic calls
# ==============================================================================

def _make_call(tool="run_financial_model", scenarios=None, top_dcf=None,
               call_index=1, error=None, validation_error=None, mode=None,
               blended_per_share_iv=None, kelly=None, top_params=None):
    params = top_params or {}
    if mode:
        params["mode"] = mode
    p_scs = []
    sc_dcfs = []
    for sc in (scenarios or []):
        name = sc.get("name", "Base")
        param_entry = {"name": name}
        for k in ("prob", "base_cf", "explicit_growth", "growth_rates", "fade_years",
                  "wacc", "discount_rate", "valuation_frame", "terminal_exit_multiple",
                  "terminal_g", "finite_life_years", "shares_diluted"):
            if k in sc:
                param_entry[k] = sc[k]
        p_scs.append(param_entry)

        dcf = {}
        for k in ("per_share_iv", "per_share_iv_exit", "per_share_iv_gordon",
                  "explicit_growth", "fade_years", "discount_rate_applied",
                  "valuation_frame", "exit_multiple_terminal", "terminal_g",
                  "finite_life_years", "error"):
            if k in sc:
                dcf[k] = sc[k]
        sc_dcfs.append({"name": name, "dcf": dcf})

    if p_scs:
        params["scenarios"] = p_scs

    res = {}
    if sc_dcfs:
        res["scenario_dcfs"] = sc_dcfs
    if top_dcf:
        res["dcf_model"] = top_dcf
    if mode:
        res["mode"] = mode
    if blended_per_share_iv is not None:
        res["blended_per_share_iv"] = blended_per_share_iv
    if kelly is not None:
        res["kelly_sizing"] = {"quarter_kelly_pct": kelly}

    return {
        "tool": tool,
        "call_index": call_index,
        "params": params,
        "result": res,
        "error": error,
        "validation_error": validation_error,
    }


# ==============================================================================
# 1. Synthetic calls, one per rule
# ==============================================================================

def test_rule_joint():
    calls = [_make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "prob": 0.5, "base_cf": 1.0,
             "explicit_growth": [0.1], "fade_years": 5, "discount_rate_applied": 0.08,
             "valuation_frame": "equity", "terminal_g": 0.025, "shares_diluted": 1.0},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25, "shares_diluted": 1.0},
            {"name": "Bear", "per_share_iv": 70.0, "prob": 0.25, "shares_diluted": 1.0},
        ],
        kelly=12.5,
        call_index=1,
    )]
    facts = {"shares_outstanding": 1e9, "coe_anchor": 0.08}
    filled, prov = contract_fill.fill(calls, {}, facts, 90.0)
    assert prov["mode"] == "joint"
    assert prov["answer_call_index"] == 1
    assert filled["base_iv"] == 100.0
    assert filled["bull_iv"] == 150.0
    assert filled["bear_iv"] == 70.0
    assert filled["base_probability"] == 0.5
    assert filled["bull_probability"] == 0.25
    assert filled["bear_probability"] == 0.25
    assert filled["kelly_fraction_pct"] == 12.5
    assert filled["shares_basis"] == "diluted"


def test_rule_scenario_wise():
    call1 = _make_call(scenarios=[{"name": "Base", "per_share_iv": 100.0, "prob": 0.5, "shares_diluted": 1.0}], call_index=1)
    call2 = _make_call(scenarios=[{"name": "Bull", "per_share_iv": 150.0, "prob": 0.3, "shares_diluted": 1.0}], call_index=2)
    call3 = _make_call(scenarios=[{"name": "Bear", "per_share_iv": 60.0, "prob": 0.2, "shares_diluted": 1.0}], call_index=3)
    facts = {"shares_outstanding": 1e9, "coe_anchor": 0.08}
    filled, prov = contract_fill.fill([call1, call2, call3], {}, facts, 90.0)
    assert prov["mode"] == "scenario_wise"
    assert filled["base_iv"] == 100.0
    assert filled["bull_iv"] == 150.0
    assert filled["bear_iv"] == 60.0
    assert filled["kelly_fraction_pct"] is None


# S3 A+B (brief §3.8): FILLED grew from 19 to 32 entries (base_cf_basis, interest_addback and the
# 11 reasons).
def test_rule_no_desk_run():
    # No calls or only failed calls
    failed_call = _make_call(error="timeout")
    typed = {"base_iv": 123.4, "bull_iv": 200.0, "verdict_label": "undervalued"}
    facts = {"shares_outstanding": 1e9, "coe_anchor": 0.08}
    filled, prov = contract_fill.fill([failed_call], typed, facts, 100.0)
    assert prov["mode"] == "no_desk_run"
    assert filled == {}
    assert len(prov["unfilled"]) == 32
    assert prov["unfilled"] == list(contract_fill.FILLED)


def test_rule_later_non_joint_after_joint():
    call1 = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 70.0, "prob": 0.25},
        ],
        call_index=1,
    )
    call2 = _make_call(
        scenarios=[{"name": "Base", "per_share_iv": 105.0, "prob": 0.5}],
        call_index=2,
    )
    facts = {"shares_outstanding": 1e9, "coe_anchor": 0.08}
    filled, prov = contract_fill.fill([call1, call2], {}, facts, 90.0)
    assert prov["mode"] == "joint"
    assert prov["answer_call_index"] == 1
    assert filled["base_iv"] == 100.0


def test_rule_blend_matched_and_not():
    # Blend matched
    call1 = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 70.0, "prob": 0.25},
        ],
        call_index=1,
    )
    call2 = _make_call(mode="blend", blended_per_share_iv=112.5, call_index=2)
    facts = {"shares_outstanding": 1e9, "coe_anchor": 0.08}
    typed_match = {"base_iv": 112.5}
    filled_m, prov_m = contract_fill.fill([call1, call2], typed_match, facts, 100.0)
    assert filled_m["base_iv"] == 112.5
    assert prov_m["blend"] is True

    # Blend not matched within 1%
    typed_unmatched = {"base_iv": 100.0}
    filled_u, prov_u = contract_fill.fill([call1, call2], typed_unmatched, facts, 100.0)
    assert filled_u["base_iv"] == 100.0
    assert prov_u["blend"] is False


def test_rule_leg_nearest_and_primary():
    # When typed is near Gordon, pick Gordon
    call = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "per_share_iv_exit": 100.0, "per_share_iv_gordon": 80.0, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "per_share_iv_exit": 150.0, "per_share_iv_gordon": 140.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 60.0, "per_share_iv_exit": 60.0, "per_share_iv_gordon": 50.0, "prob": 0.25},
        ]
    )
    typed = {"base_iv": 80.2, "bull_iv": 150.0, "bear_iv": 60.0}
    filled, prov = contract_fill.fill([call], typed, {}, 70.0)
    assert filled["base_iv"] == 80.0
    assert prov["legs"]["base"] == "gordon"

    # When typed does not match within 1%, take primary leg (exit multiple passed -> exit)
    typed_far = {"base_iv": 200.0, "bull_iv": 150.0, "bear_iv": 60.0}
    filled_p, prov_p = contract_fill.fill([call], typed_far, {}, 70.0)
    assert filled_p["base_iv"] == 100.0
    assert prov_p["legs"]["base"] == "exit"


def test_rule_finite_life():
    call = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 45.0, "finite_life_years": 15, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 60.0, "finite_life_years": 15, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 30.0, "finite_life_years": 15, "prob": 0.25},
        ]
    )
    filled, prov = contract_fill.fill([call], {}, {}, 40.0)
    assert filled["terminal_method"] == "finite_life"
    assert filled["terminal_multiple_or_g"] is None
    assert filled["cash_flow_life"] == 15
    assert prov["legs"]["base"] == "finite"


def test_rule_exit_leg_multiple_sources():
    # Multiple from exit_multiple_terminal
    call1 = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "per_share_iv_exit": 100.0,
             "exit_multiple_terminal": {"exit_multiple": 18.5}, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 60.0, "prob": 0.25},
        ]
    )
    filled1, _ = contract_fill.fill([call1], {}, {}, 80.0)
    assert filled1["terminal_method"] == "exit_multiple"
    assert filled1["terminal_multiple_or_g"] == 18.5

    # Multiple from input param when not echoed
    call2 = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "per_share_iv_exit": 100.0,
             "terminal_exit_multiple": 15.0, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 60.0, "prob": 0.25},
        ]
    )
    filled2, _ = contract_fill.fill([call2], {}, {}, 80.0)
    assert filled2["terminal_method"] == "exit_multiple"
    assert filled2["terminal_multiple_or_g"] == 15.0


def test_rule_rate_from_input_fallback():
    # When discount_rate_applied is absent, fallback to wacc, then discount_rate
    call1 = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "wacc": 0.092, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 60.0, "prob": 0.25},
        ]
    )
    filled1, _ = contract_fill.fill([call1], {}, {}, 80.0)
    assert filled1["coe_used"] == 0.092

    call2 = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0, "discount_rate": 0.088, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 60.0, "prob": 0.25},
        ]
    )
    filled2, _ = contract_fill.fill([call2], {}, {}, 80.0)
    assert filled2["coe_used"] == 0.088


def test_rule_capped_base_applied_growth_path():
    # When dcf carries explicit_growth (applied path), it wins over input param
    call = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 100.0,
             "explicit_growth": [0.20, 0.18, 0.12, 0.10, 0.08],  # dcf echo (applied)
             "prob": 0.5},
            {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 60.0, "prob": 0.25},
        ]
    )
    # Set input param to un-capped path
    call["params"]["scenarios"][0]["explicit_growth"] = [0.25, 0.25, 0.25, 0.25, 0.25]
    filled, _ = contract_fill.fill([call], {}, {}, 80.0)
    assert filled["stage1_growth_path"] == [0.20, 0.18, 0.12, 0.10, 0.08]


def test_rule_coe_source_gaps():
    def get_source(coe_used, coe_anchor):
        call = _make_call(
            scenarios=[
                {"name": "Base", "per_share_iv": 100.0, "discount_rate_applied": coe_used, "prob": 0.5},
                {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
                {"name": "Bear", "per_share_iv": 60.0, "prob": 0.25},
            ]
        )
        filled, _ = contract_fill.fill([call], {}, {"coe_anchor": coe_anchor}, 80.0)
        return filled["coe_source"]

    # Using 0.0 allows exact representation of gaps
    anchor = 0.0
    assert get_source(0.0005, anchor) == "anchor"          # gap 0.0005 <= 0.0005
    assert get_source(0.0006, anchor) == "anchor_adjusted" # gap 0.0006 <= 0.015
    assert get_source(0.0150, anchor) == "anchor_adjusted" # gap 0.0150 <= 0.015
    assert get_source(0.0151, anchor) == "own"             # gap 0.0151 > 0.015
    assert get_source(0.1000, None) == "own"               # anchor None -> own


def test_rule_shares_basis():
    def get_basis(pack_shares, base_shares):
        call = _make_call(
            scenarios=[
                {"name": "Base", "per_share_iv": 100.0, "shares_diluted": base_shares, "prob": 0.5},
                {"name": "Bull", "per_share_iv": 150.0, "shares_diluted": base_shares, "prob": 0.25},
                {"name": "Bear", "per_share_iv": 60.0, "shares_diluted": base_shares, "prob": 0.25},
            ]
        )
        filled, _ = contract_fill.fill([call], {}, {"shares_outstanding": pack_shares}, 80.0)
        return filled.get("shares_basis")

    pack = 1_000_000_000.0  # 1.0B
    # 1.0% gap (within 1%)
    assert get_basis(pack, 1.0099e9) == "diluted"
    # 1.1% gap (beyond 1%)
    assert get_basis(pack, 1.011e9) == "diluted_plus_contingent"
    # None pack count -> not filled
    assert get_basis(None, 1.0e9) is None
    # 0 pack count -> not filled
    assert get_basis(0, 1.0e9) is None


def test_rule_verdict_label_thresholds():
    def get_label(base_iv, price):
        call = _make_call(
            scenarios=[
                {"name": "Base", "per_share_iv": base_iv, "prob": 0.5},
                {"name": "Bull", "per_share_iv": 150.0, "prob": 0.25},
                {"name": "Bear", "per_share_iv": 50.0, "prob": 0.25},
            ]
        )
        filled, _ = contract_fill.fill([call], {}, {}, price)
        return filled["verdict_label"]

    price = 100.0
    assert get_label(110.1, price) == "undervalued"  # 110.1/100 - 1 = +0.101
    assert get_label(109.9, price) == "hold"         # 109.9/100 - 1 = +0.099
    assert get_label(89.9, price) == "overvalued"    # 89.9/100 - 1 = -0.101
    assert get_label(90.1, price) == "hold"          # 90.1/100 - 1 = -0.099


def test_rule_skew_bear_at_and_above_price():
    def get_skew(bull, bear, price):
        call = _make_call(
            scenarios=[
                {"name": "Base", "per_share_iv": 100.0, "prob": 0.5},
                {"name": "Bull", "per_share_iv": bull, "prob": 0.25},
                {"name": "Bear", "per_share_iv": bear, "prob": 0.25},
            ]
        )
        filled, _ = contract_fill.fill([call], {}, {}, price)
        return filled["asymmetric_payoff_skew"]

    price = 100.0
    # Bear at price (downside = 0), upside > 0 -> 99.9
    assert get_skew(120.0, 100.0, price) == 99.9
    # Bear above price (downside < 0), upside > 0 -> 99.9
    assert get_skew(120.0, 105.0, price) == 99.9
    # Bear at price, upside <= 0 -> 0.0
    assert get_skew(95.0, 100.0, price) == 0.0
    # Bear above price, upside <= 0 -> 0.0
    assert get_skew(95.0, 105.0, price) == 0.0


def test_rule_typed_value_matches_no_desk_value():
    call = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 50.0, "prob": 0.5},
            {"name": "Bull", "per_share_iv": 75.0, "prob": 0.25},
            {"name": "Bear", "per_share_iv": 30.0, "prob": 0.25},
        ]
    )
    typed = {"base_iv": 999.0, "bull_iv": 888.0, "bear_iv": 111.0}
    filled, _ = contract_fill.fill([call], typed, {}, 45.0)
    assert filled["base_iv"] == 50.0
    assert filled["bull_iv"] == 75.0
    assert filled["bear_iv"] == 30.0


# ==============================================================================
# 2. Three real samples
# ==============================================================================

# S3 A+B (brief §3.8): these are older (pre-revision-15) recorded calls, so `filled` and
# `disagrees` are unchanged (S2's rules apply as before) — only `prov["unfilled"]` grows, by the 13
# fields FILLED gained (base_cf_basis, interest_addback, the 11 reasons). The golden fixture file
# itself is not regenerated; the 13 names are appended to the loaded expectation in this test only.
def test_real_samples():
    fix_dir = _HERE / "tests" / "fixture_data" / "contract_fill"
    golden_file = fix_dir / "golden_3_samples.json"
    golden = json.loads(golden_file.read_text(encoding="utf-8"))
    new_fields = list(contract_fill.FILLED[19:])
    assert len(new_fields) == 13

    for e in golden:
        fixture_path = fix_dir / f"{e['run']}_s{e['sample']}.json"
        assert fixture_path.exists(), f"Fixture file missing: {fixture_path}"
        desk_calls = json.loads(fixture_path.read_text(encoding="utf-8"))

        facts = {"shares_outstanding": e["facts"]["shares"], "coe_anchor": e["facts"]["coe_anchor"]}
        filled, prov = contract_fill.fill(desk_calls, e["typed"], facts, e["price"])
        assert filled == e["filled"], f"{e['run']} filled mismatch"
        expected_prov = dict(e["prov"])
        expected_prov["unfilled"] = list(e["prov"]["unfilled"]) + new_fields
        assert prov == expected_prov, f"{e['run']} prov mismatch"
        dis = contract_fill.disagrees(e["typed"], filled)
        assert dis == e["disagrees"], f"{e['run']} disagrees mismatch"


# ==============================================================================
# 3. fiduciary_gate: payoff_skew against old inline logic
# ==============================================================================

def _old_inline_skew(bull_iv, bear_iv, price):
    if price and price > 0 and bull_iv is not None and bear_iv is not None:
        downside = price - bear_iv
        upside = bull_iv - price
        if downside <= 0:
            return 99.9 if upside > 0 else 0.0
        else:
            return round(upside / downside, 2)
    return None


def test_fiduciary_gate_payoff_skew():
    # Edge cases
    assert fg.payoff_skew(None, 50.0, 100.0) is None
    assert fg.payoff_skew(150.0, None, 100.0) is None
    assert fg.payoff_skew(150.0, 50.0, None) is None
    assert fg.payoff_skew(150.0, 50.0, 0.0) is None
    assert fg.payoff_skew(150.0, 50.0, -10.0) is None
    assert fg.payoff_skew(120.0, 100.0, 100.0) == 99.9
    assert fg.payoff_skew(90.0, 100.0, 100.0) == 0.0

    # 20+ varied / pseudo-random tests
    rng = random.Random(42)
    for _ in range(30):
        px = rng.uniform(10.0, 500.0)
        bull = rng.uniform(px * 0.5, px * 2.0)
        bear = rng.uniform(px * 0.2, px * 1.5)
        expected = _old_inline_skew(bull, bear, px)
        actual = fg.payoff_skew(bull, bear, px)
        assert actual == expected, f"Mismatch on bull={bull}, bear={bear}, px={px}"


# ==============================================================================
# 4. disagrees at each tolerance's edge
# ==============================================================================

def test_disagrees_tolerances():
    # values: 1% relative
    assert contract_fill.disagrees({"base_iv": 101.0}, {"base_iv": 100.0}) == []
    assert contract_fill.disagrees({"base_iv": 101.01}, {"base_iv": 100.0}) == ["base_iv"]

    # probabilities: 0.005
    assert contract_fill.disagrees({"base_probability": 0.505}, {"base_probability": 0.500}) == []
    assert contract_fill.disagrees({"base_probability": 0.5051}, {"base_probability": 0.500}) == ["base_probability"]

    # kelly: 0.05
    assert contract_fill.disagrees({"kelly_fraction_pct": 10.05}, {"kelly_fraction_pct": 10.00}) == []
    assert contract_fill.disagrees({"kelly_fraction_pct": 10.051}, {"kelly_fraction_pct": 10.00}) == ["kelly_fraction_pct"]

    # skew: 0.1
    assert contract_fill.disagrees({"asymmetric_payoff_skew": 1.50}, {"asymmetric_payoff_skew": 1.40}) == []
    assert contract_fill.disagrees({"asymmetric_payoff_skew": 1.51}, {"asymmetric_payoff_skew": 1.40}) == ["asymmetric_payoff_skew"]

    # base_cf_used: 2% relative
    assert contract_fill.disagrees({"base_cf_used": 102.0}, {"base_cf_used": 100.0}) == []
    assert contract_fill.disagrees({"base_cf_used": 102.01}, {"base_cf_used": 100.0}) == ["base_cf_used"]

    # growth path: 0.01 per element (rescaling 15 vs 0.15)
    assert contract_fill.disagrees({"stage1_growth_path": [15.0, 10.0]}, {"stage1_growth_path": [0.15, 0.10]}) == []
    assert contract_fill.disagrees({"stage1_growth_path": [0.16, 0.10]}, {"stage1_growth_path": [0.15, 0.10]}) == []
    assert contract_fill.disagrees({"stage1_growth_path": [0.161, 0.10]}, {"stage1_growth_path": [0.15, 0.10]}) == ["stage1_growth_path"]
    assert contract_fill.disagrees({"stage1_growth_path": [0.15]}, {"stage1_growth_path": [0.15, 0.10]}) == ["stage1_growth_path"]

    # fade: exact int
    assert contract_fill.disagrees({"fade_years": 5}, {"fade_years": 5}) == []
    assert contract_fill.disagrees({"fade_years": "5"}, {"fade_years": 5}) == []
    assert contract_fill.disagrees({"fade_years": 6}, {"fade_years": 5}) == ["fade_years"]

    # coe_used: 0.0005 (with rescaling)
    assert contract_fill.disagrees({"coe_used": 8.0}, {"coe_used": 0.08}) == []
    assert contract_fill.disagrees({"coe_used": 0.0805}, {"coe_used": 0.0800}) == []
    assert contract_fill.disagrees({"coe_used": 0.0806}, {"coe_used": 0.0800}) == ["coe_used"]

    # terminal_multiple_or_g: 2% relative
    assert contract_fill.disagrees({"terminal_multiple_or_g": 15.3}, {"terminal_multiple_or_g": 15.0}) == []
    assert contract_fill.disagrees({"terminal_multiple_or_g": 15.31}, {"terminal_multiple_or_g": 15.0}) == ["terminal_multiple_or_g"]

    # cash_flow_life: string case-insensitive
    assert contract_fill.disagrees({"cash_flow_life": "Perpetual"}, {"cash_flow_life": "perpetual"}) == []
    assert contract_fill.disagrees({"cash_flow_life": 15}, {"cash_flow_life": 15}) == []
    assert contract_fill.disagrees({"cash_flow_life": 10}, {"cash_flow_life": 15}) == ["cash_flow_life"]

    # verdict_label: "fair" == "hold"
    assert contract_fill.disagrees({"verdict_label": "fair"}, {"verdict_label": "hold"}) == []
    assert contract_fill.disagrees({"verdict_label": "HOLD"}, {"verdict_label": "hold"}) == []
    assert contract_fill.disagrees({"verdict_label": "undervalued"}, {"verdict_label": "hold"}) == ["verdict_label"]

    # other strings: case-insensitive
    assert contract_fill.disagrees({"valuation_frame": "EQUITY"}, {"valuation_frame": "equity"}) == []
    assert contract_fill.disagrees({"shares_basis": "DILUTED"}, {"shares_basis": "diluted"}) == []
    assert contract_fill.disagrees({"shares_basis": "diluted_plus_contingent"}, {"shares_basis": "diluted"}) == ["shares_basis"]


# ==============================================================================
# 5. main() integration with recorded-style mock
# ==============================================================================

def test_main_integration_mock(monkeypatch, tmp_path):
    # Minimal pack with sidecar facts
    d_pack = tmp_path / "mock_pack"
    d_pack.mkdir()
    pack_file = d_pack / "_pack.md"
    pack_file.write_text("Test pack for GEV\nShares outstanding: 1,000,000,000\nCOE ANCHOR for this name: 8.0%\n", encoding="utf-8")

    sidecar = {
        "source": "build",
        "shares_outstanding": 1e9,
        "coe_anchor": 0.08,
        "next_fy_revenue_growth": 0.10,
    }
    (d_pack / "_pack_facts.json").write_text(json.dumps(sidecar), encoding="utf-8")

    sample_report = """# Report
```json:underwriting
{
  "base_iv": 50.0,
  "bull_iv": 80.0,
  "bear_iv": 30.0,
  "verdict_label": "hold",
  "business_quality_moat": 4.0,
  "conviction_score": 12
}
```
"""
    desk_call = _make_call(
        scenarios=[
            {"name": "Base", "per_share_iv": 55.0, "prob": 0.5, "base_cf": 2.0,
             "explicit_growth": [0.1], "fade_years": 5, "discount_rate_applied": 0.08,
             "valuation_frame": "equity", "terminal_g": 0.025, "shares_diluted": 1.0},
            {"name": "Bull", "per_share_iv": 85.0, "prob": 0.25, "shares_diluted": 1.0},
            {"name": "Bear", "per_share_iv": 35.0, "prob": 0.25, "shares_diluted": 1.0},
        ],
        kelly=10.0,
        call_index=1,
    )

    def mock_chat_with_tools(model, pack, sd_i, **kw):
        sd = Path(sd_i)
        sd.mkdir(parents=True, exist_ok=True)
        snap_content = {"calls": [desk_call], "turns": [1]}
        (sd / "_research_snapshot.json").write_text(json.dumps(snap_content), encoding="utf-8")
        return sample_report, "Thinking trace", {"done_reason": "stop", "eval_count": 100, "prompt_eval_count": 50}

    monkeypatch.setattr(at, "chat_with_tools", mock_chat_with_tools)
    monkeypatch.setattr(cv, "snapshot_research_brief", lambda *a, **k: cv.ResearchSnapshot(None, None, False, False))

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "50.0", "--samples", "1",
        "--tools", "--no-early-stop", "--pack-file", str(pack_file), "--out-dir", str(out_dir)
    ])
    cv.main()

    res_dirs = list(out_dir.glob("GEV_*"))
    assert len(res_dirs) == 1
    consensus_file = res_dirs[0] / "consensus.json"
    assert consensus_file.exists()
    doc = json.loads(consensus_file.read_text(encoding="utf-8"))

    run0 = doc["runs"][0]
    sc = run0["scorecard"]

    # S3 A+B (brief §3.8 retirement): the typed shadow (typed_contract, typed_contract_disagrees)
    # is gone — no typed values remain to compare the desk against.
    assert "typed_contract" not in sc
    assert "typed_contract_disagrees" not in sc
    assert "code_fill" in sc
    assert sc["code_fill"]["mode"] == "joint"
    # The run's iv should equal the desk value (55.0), overriding the typed 50.0.
    assert run0["iv"] == 55.0
    assert sc["base_iv"] == 55.0
    assert doc["scorecard"]["code_fill_mode"] == "joint"
