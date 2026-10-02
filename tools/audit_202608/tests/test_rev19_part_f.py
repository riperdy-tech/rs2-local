"""Revision 19, Part F (AT10 fix items 2 and 3).

Fix 2: the printed levels hold a Base's years 1-2, bound a Bull and a Bear and set the harness's years12 ratio and flags whatever
the reference's status; only the reference's VALUE stays gated by `reference_in_force`.
Fix 3: the desk refuses an excess_cash above the base fiscal year's cash and short-term investments, whatever reason comes with it.

Fixtures are synthetic (numbers written for the test).
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
from test_rev18_part1 import B, _desk_call, _desk_ctx, _pack_with_bill_rate  # noqa: E402
from test_rev17f_redesign import _w9_reference  # noqa: E402

STATUSES = ("used", "outside_fence_above", "outside_fence_below", "not_meaningful")


# ---- fix 2: the levels, whatever the status ------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", STATUSES)
def test_the_base_hold_fires_for_every_status(status):
    ref = _w9_reference()
    path = list(ref["path"])
    path[1] = path[1] + 0.20                                     # a Base year 2 far above the printed level
    call = _desk_call(ref)
    call["scenarios"][0]["explicit_growth"] = path
    call.pop("guidance_deviation_reason", None)
    out = fmt.execute_financial_model(call, _desk_ctx(ref, reference_status=status))
    assert "error" not in out, out.get("error")
    assert out["years12_held"]["dcfs"][0]["name"] == "Base"
    base = out["scenario_dcfs"][0]["dcf"]
    assert base["years12_held"] is True and "years12_held_by_desk" in base["stamps"]
    held = out["years12_held"]["dcfs"][0]
    assert held["applied_per_share_iv"] < held["requested_per_share_iv"]
    # the held Base is the same number for every status: the hold does not read the reference's value
    ctx_used = fmt.execute_financial_model(call, _desk_ctx(ref, reference_status="used"))
    assert base["per_share_iv"] == ctx_used["scenario_dcfs"][0]["dcf"]["per_share_iv"]


@pytest.mark.parametrize("status", STATUSES)
def test_r11_bounds_a_bull_and_bear_for_every_status(status):
    ref = _w9_reference()
    call = _desk_call(ref)
    call["scenarios"][1]["explicit_growth"] = list(ref["path"][:1]) + [ref["path"][1] + 0.30] + list(ref["path"][2:])   # Bull year 2 high
    call.pop("scenario_deviation_reason")
    lv = {"year1": ref["levels"][0] / B, "year2": ref["levels"][1] / B, "bull2": ref["levels"][1] / B, "bear2": ref["levels"][1] / B}
    out = fmt.execute_financial_model(call, _desk_ctx(ref, levels=lv, reference_status=status))
    assert "scenario_deviation_reason needed" in out.get("error", "")
    assert "Bull year-2 cash flow" in out["error"]
    # given the reason, the call is accepted
    ok = fmt.execute_financial_model(dict(call, scenario_deviation_reason="d"), _desk_ctx(ref, levels=lv, reference_status=status))
    assert "error" not in ok


@pytest.mark.parametrize("status", STATUSES)
def test_the_reference_value_stays_gated_by_the_status(status):
    """R10 reads the reference's value only when it is in force: the two fenced statuses neither ask for a reason nor bound the Base
    (the existing rule, unchanged by fix 2)."""
    ref = _w9_reference()
    call = _desk_call(ref)
    call.pop("terminal_reason")
    far = ref["value"] * 3.0
    out = fmt.execute_financial_model(call, _desk_ctx(ref, consensus_implied_value=far, reference_status=status))
    if cr.reference_in_force(status):
        assert "guidance_deviation_reason" in out["error"]
    else:
        assert "error" not in out


@pytest.mark.parametrize("status", STATUSES)
def test_the_harness_years12_ratio_and_flag_are_on_the_levels_for_every_status(status):
    facts = dict(pack_facts.empty(), consensus_implied_value=100.0, reference_status=status,
                 levels={"year1": 5.0, "year2": 6.0, "bull2": 7.0, "bear2": 5.0})
    sc = {"base_iv": 40.0, "stage1_growth_path": [0.2, 0.0, 0.05, 0.05, 0.05], "base_cf_used": 5.0, "guidance_deviation_reason": None}
    # year-2 flow = 5.0 x 1.2 x 1.0 = 6.0: exactly the level
    assert cv.consensus_ratios(sc, None, None, facts=facts)["years12_ratio"] == 1.0
    # a path 30% above the level is flagged on the levels (the harness's own rule), for every status
    sc2 = dict(sc, stage1_growth_path=[0.2, 0.30, 0.05, 0.05, 0.05])
    assert cv.consensus_ratios(sc2, None, None, facts=facts)["years12_ratio"] == pytest.approx(1.3, abs=1e-3)
    flags = cv.check_sample_harness_rules(sc2, 90.0, desk_info={"desk_per_share_ivs": [40.0]}, enrich_data={}, facts=facts)[2]
    assert "years12_off_consensus_earnings" in flags
    ok = cv.check_sample_harness_rules(sc, 90.0, desk_info={"desk_per_share_ivs": [40.0]}, enrich_data={}, facts=facts)[2]
    assert "years12_off_consensus_earnings" not in ok
    # the value band is the reference's VALUE: gated by the status
    far = cv.check_sample_harness_rules(dict(sc, base_iv=10.0), 90.0, desk_info={"desk_per_share_ivs": [10.0]}, enrich_data={}, facts=facts)[2]
    assert ("base_far_from_consensus_implied" in far) == cr.reference_in_force(status)


@pytest.mark.parametrize("status", STATUSES)
def test_the_bull_bear_years12_stamps_are_on_the_levels_for_every_status(status, tmp_path):
    from test_scenario_checks import EST, PACK, _sc, _snapshot
    lv = {"year1": 7.578, "year2": 20.0, "bull2": 36.7967, "bear2": 12.0}
    facts = dict(pack_facts.empty(), reference_status=status, levels=lv)
    _, st = cv.scenario_checks(_snapshot(tmp_path, 1.6325), _sc(), {"estimates": EST}, PACK, 609.43, facts=facts)
    # Bull: 7.578 x 1.9664 x 2.4695 / 36.7967 on the levels
    assert st["bull_years12_ratio"] == pytest.approx(7.578 * 1.9664 * 2.4695 / 36.7967, abs=1e-3)
    assert st["bear_years12_ratio"] == pytest.approx(7.578 * 1.679 * 1.371 / 12.0, abs=1e-3)


# ---- fix 3: excess_cash is bounded by the base year's printed cash -------------------------------------------------------------

@pytest.mark.parametrize("fact", [10.307, 3.0])             # a non-financial name and a financial one (the fact is the cash for every sector)
def test_excess_cash_at_above_and_below_the_bound(fact):
    ref = _w9_reference()
    ctx = _desk_ctx(ref, excess_cash=0.0 if fact == 3.0 else 9.0, base_year_cash_and_investments_b=fact)
    # below the bound, with a reason: accepted (R15 is unchanged)
    ok = fmt.execute_financial_model(_desk_call(ref, excess_cash=fact * 0.5, excess_cash_reason="cash held abroad, per the 2026-08 10-Q"), ctx)
    assert "error" not in ok
    # at the bound: accepted; $1,000 above it (the printed precision): accepted; more than that: refused, a reason allows nothing
    at = fmt.execute_financial_model(_desk_call(ref, excess_cash=fact, excess_cash_reason="r"), ctx)
    assert "error" not in at
    edge = fmt.execute_financial_model(_desk_call(ref, excess_cash=fact + 1e-6, excess_cash_reason="r"), ctx)
    assert "error" not in edge
    above = fmt.execute_financial_model(_desk_call(ref, excess_cash=fact + 0.001, excess_cash_reason="a dated reason"), ctx)
    assert above["validation_error"] is True and above["needs_reasons"] == []
    assert f"excess_cash {fact + 0.001:.6f} B is above the base fiscal year's cash and short-term investments {fact:.6f} B" in above["error"]
    assert "cash received after the valuation date is already in the cash flows; no reason allows it" in above["error"]
    assert above["missing"] and above["missing"][0].startswith("excess_cash ")
    assert "scenario_dcfs" not in above                    # a refusal does not use a desk run


def test_the_bound_without_the_fact_is_the_defaults_excess_cash_else_zero():
    ref = _w9_reference()
    # no fact: the DEFAULTS excess_cash when numeric
    ctx = _desk_ctx(ref, excess_cash=2.0)
    assert "error" not in fmt.execute_financial_model(_desk_call(ref, excess_cash=2.0), ctx)
    refused = fmt.execute_financial_model(_desk_call(ref, excess_cash=2.5, excess_cash_reason="r"), ctx)
    assert "is above the base fiscal year's cash and short-term investments 2.000000 B" in refused["error"]
    # no fact and no DEFAULTS amount: 0
    ctx0 = _desk_ctx(ref)
    ctx0.pop("excess_cash", None)
    refused0 = fmt.execute_financial_model(_desk_call(ref, excess_cash=0.5, excess_cash_reason="r"), ctx0)
    assert "short-term investments 0.000000 B" in refused0["error"]
    # a 0.0 fact is a value, not an absence: it is the bound even when the DEFAULTS amount is higher
    ctxz = _desk_ctx(ref, excess_cash=5.0, base_year_cash_and_investments_b=0.0)
    assert "short-term investments 0.000000 B" in fmt.execute_financial_model(_desk_call(ref, excess_cash=1.0, excess_cash_reason="r"), ctxz)["error"]
    # no excess_cash given: nothing to refuse
    assert "error" not in fmt.execute_financial_model(_desk_call(ref), ctxz)


def test_an_excess_cash_in_dollars_is_read_in_billions_for_the_bound():
    ref = _w9_reference()
    ctx = _desk_ctx(ref, excess_cash=10.307, base_year_cash_and_investments_b=10.307)
    mu_s2 = fmt.execute_financial_model(_desk_call(ref, excess_cash=68.274e9, excess_cash_reason="net cash after the raise"), ctx)
    assert "excess_cash 68.274000 B is above" in mu_s2["error"] and "10.307000 B" in mu_s2["error"]
    assert "error" not in fmt.execute_financial_model(_desk_call(ref, excess_cash=10.307e9, excess_cash_reason="r"), ctx)


def test_r15_is_unchanged_at_or_below_the_bound():
    ref = _w9_reference()
    ctx = _desk_ctx(ref, excess_cash=1.0, base_year_cash_and_investments_b=3.0)
    needs = fmt.execute_financial_model(_desk_call(ref, excess_cash=2.0, excess_cash_reason=None), ctx)
    assert "excess_cash_reason needed" in needs["error"] and needs["needs_reasons"]


def test_the_pack_prints_and_parses_the_fact_for_every_sector(screener_data_stub, monkeypatch):
    """The fact is the base fiscal year's cash plus short-term investments, whatever the sector and whatever the bill rate."""
    c_l = 8.0 * B * 1.03 ** 11 * 0.10          # the synthetic base year (test_rev18_part1)
    for rate, sector in ((None, "Industrials"), (0.04, "Industrials"), (0.04, "Financial Services"), (None, "Financial Services")):
        pack = _pack_with_bill_rate(monkeypatch, rate, sector=sector)
        f = pack.facts
        assert f["base_year_cash_and_investments_b"] == pack_facts.q_b(c_l / B), (rate, sector)
        text = str(pack)
        assert (f"- base_year_cash_and_investments_b: {c_l / B:.6f} | the base fiscal year's cash and short-term investments as filed; "
                f"the desk refuses an excess_cash above it (cash after the valuation date is already in the cash flows)") in text
        assert "the desk refuses an amount above base_year_cash_and_investments_b" in text
        assert pack_facts.parity(f, pack_facts.from_text(text)) == []
        assert pack_facts.from_text(text)["base_year_cash_and_investments_b"] == f["base_year_cash_and_investments_b"]


def test_the_fact_is_none_when_cash_is_null_and_short_term_investments_count_zero_when_null():
    assert cr.cash_and_investments({"cash": 4.0e9, "st_investments": None}) == 4.0e9
    assert cr.cash_and_investments({"cash": 4.0e9, "st_investments": 1.5e9}) == 5.5e9
    assert cr.cash_and_investments({"cash": 0.0, "st_investments": 2.0e9}) == 2.0e9
    assert cr.cash_and_investments({"cash": 0.0}) == 0.0
    assert cr.cash_and_investments({"cash": None, "st_investments": 2.0e9}) is None
    assert cr.cash_and_investments({}) is None
    assert cr.cash_and_investments({"cash": float("nan")}) is None


def test_an_older_block_or_sidecar_reads_the_fact_as_none(tmp_path):
    text = ("# DATA PACK - X   (pack revision 18)\n\n" + pack_facts.render_defaults_block(pack_facts.empty()))
    line = next(l for l in text.splitlines() if l.startswith("- base_year_cash_and_investments_b:"))
    older = text.replace(line + "\n", "")
    assert pack_facts.from_text(older)["base_year_cash_and_investments_b"] is None
    d = tmp_path / "run"
    d.mkdir()
    facts = pack_facts.empty()
    facts.pop("base_year_cash_and_investments_b")
    (d / pack_facts.SIDECAR).write_text(json.dumps(facts), encoding="utf-8")
    assert pack_facts.read_sidecar(d)["base_year_cash_and_investments_b"] is None
