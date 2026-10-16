"""Revision 24 step 2c (BRIEF_R24_S2c_ranges_fix.md items 7 and 8; PHASE_4_AMENDMENTS.md "Revision 24 step 2b" rulings 10 and 12; the coordinator's
pack_revision addition):

- the rev22 control desk: under pilot_arm rev22 the long run is valued as revision 22 valued it (the generator's margin path, the facts'
  margin_ratio; long_run_margin not required), with the revision-22 defaults, holds and cap; D2-D4 stay; stamped rev22_control_desk; the tool the
  arm is offered is revision 22's (git 412578d). A revision-22-style call values on the 3 saved packs under rev22 and is refused under the iii arms;
- working capital follows each scenario's own revenue path (the consensus revenue scaled by the scenario's owner earnings), never the reference's
  schedule for every scenario: hand-computed values;
- a frozen --pack-file pack is stamped with its own revision, and the code's constant beside it when they differ.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import depth_pipeline as dp  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN  # noqa: E402
from test_rev24_s2b_pack import rebuild_rev22  # noqa: E402
from test_rev24_stage_a_pack import REAL, _saved  # noqa: E402

S2B = HERE / "fixture_data" / "rev24_s2b"


def _with_revenue_path(f):
    """The saved packs predate the unprinted long_run members revenue_path and oe_path: rebuilt from their own facts (R_5 = e5 / m5, R_{t-1} = R_t
    - w_t / nwc_intensity; the owner earnings reference_base_b compounded at reference_path), which reproduce the saved schedule."""
    lr, wc = f["long_run"], f.get("working_capital")
    if wc and lr.get("nwc_intensity") and lr.get("m5"):
        R = [None] * 6
        R[5] = lr["e5"] / lr["m5"]
        for t in range(5, 0, -1):
            R[t - 1] = R[t] - wc[t - 1] / lr["nwc_intensity"]
        oe, x = [], f["reference_base_b"]
        for g in f["reference_path"]:
            x *= 1 + g
            oe.append(x)
        assert oe[4] == pytest.approx(lr["oe5"], rel=1e-4)
        lr.update(revenue_path=R, oe_path=oe)
    return f


def _rev22_call(f):
    """A revision-22-style call at the DEFAULTS path: no long_run_margin and no terminal_ronic (the revision-22 default applies)."""
    return {**_ALL_REASONS_GIVEN, "cash_flow_life": "perpetual", "cash_flow_life_reason": "x", "sbc_treatment": "deducted_in_cf", "fade_years": 5,
            "terminal_g": f["terminal_g_default"],
            "scenarios": [{"name": n, "prob": p, "base_cf": f["reference_base_b"], "explicit_growth": [x + d for x in f["reference_path"]],
                           "wacc": f["coe_anchor"]} for n, p, d in (("Base", 0.5, 0.0), ("Bull", 0.25, 0.03), ("Bear", 0.25, -0.03))]}


def _arm(saved, arm):
    if arm == "rev22":
        return _with_revenue_path(dict(copy.deepcopy(saved), pilot_arm="rev22", long_run_defaults_withheld=None, reference_withheld=None))
    return dict(copy.deepcopy(saved), pilot_arm=arm, long_run_defaults_withheld=True, reference_withheld=True)


# ---- the rev22 control desk (ruling 10) ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("t", REAL)
def test_a_revision_22_style_call_values_under_rev22_and_is_refused_under_the_iii_arms(t):
    saved, _ = _saved(t)
    f = _arm(saved, "rev22")
    ctx = cv.build_desk_context(f, saved["price_implied_price"], t, t, "2026-10-05")
    assert ctx["pilot_arm"] == "rev22"
    res = fmt.execute_financial_model(_rev22_call(f), ctx)
    assert "error" not in res, res.get("error")
    assert res["desk_stamps"] == ["rev22_control_desk"]
    base = next(s["dcf"] for s in res["scenario_dcfs"] if s["name"] == "Base")
    assert "margin_from_generator" in base["stamps"]
    # at the DEFAULTS path the control desk is revision 22's: the CONSENSUS-IMPLIED VALUE to the cent (the generator's margin path; on the consensus
    # owner earnings the own-path working capital is the consensus schedule)
    assert base["per_share_iv"] == pytest.approx(saved["consensus_implied_value"], abs=0.005)
    assert base["long_run"]["margin_ratio"] == (round(saved["long_run"]["margin_ratio"], 4) if saved["long_run"].get("margin_ratio") is not None else None)
    for arm in ("iii_p50", "iii_no_p50"):
        g = _arm(saved, arm)
        res = fmt.execute_financial_model(_rev22_call(g), cv.build_desk_context(g, saved["price_implied_price"], t, t, "2026-10-05"))
        assert res["validation_error"] is True
        named = " ".join(res["missing"])
        assert "long_run_margin (" in named and "terminal_ronic (" in named and "desk_stamps" not in res


def test_the_control_desk_reads_no_long_run_margin_and_says_so():
    saved, _ = _saved("AMD")
    f = _arm(saved, "rev22")
    ctx = cv.build_desk_context(f, saved["price_implied_price"], "AMD", "AMD", "2026-10-05")
    plain = fmt.execute_financial_model(_rev22_call(f), ctx)
    given = fmt.execute_financial_model(dict(_rev22_call(f), long_run_margin=0.40), ctx)
    b0 = next(s["dcf"] for s in plain["scenario_dcfs"] if s["name"] == "Base")
    b1 = next(s["dcf"] for s in given["scenario_dcfs"] if s["name"] == "Base")
    assert b1["per_share_iv"] == b0["per_share_iv"] and "long_run_margin_not_read_rev22_control" in b1["stamps"]


def test_the_rev22_arm_is_offered_revision_22s_desk_tool():
    rev22 = json.loads((S2B / "tools_rev22.json").read_text(encoding="utf-8"))      # git show 412578d's TOOLS
    assert at.tools_for({"pilot_arm": "rev22"}) == rev22
    desk = next(x for x in at.tools_for({"pilot_arm": "rev22"}) if x["function"]["name"] == "run_financial_model")["function"]
    assert "long_run_margin" not in json.dumps(desk)
    assert at.tools_for({"pilot_arm": "iii_p50", "long_run_defaults_withheld": True}) != rev22


def test_the_rev22_control_stamp_reaches_the_sample_record_and_the_verdict_row():
    import contract_fill
    saved, _ = _saved("AMD")
    f = _arm(saved, "rev22")
    ctx = cv.build_desk_context(f, saved["price_implied_price"], "AMD", "AMD", "2026-10-05")
    p = _rev22_call(f)
    call = {"tool": "run_financial_model", "params": p, "result": fmt.execute_financial_model(copy.deepcopy(p), ctx), "call_index": 1}
    filled, _ = contract_fill.fill([call], {}, dict(f, shares_outstanding=1e9), saved["price_implied_price"], ticker="AMD")
    assert filled["rev22_control_desk"] is True and filled["plausibility_gate"] is None           # the control is not gated
    assert "rev22_control_desk" in cv.S12_SUMMARY_KEYS


# ---- working capital on the scenario's own revenue path (ruling 12) --------------------------------------------------------------------------

LR_WC = {"nwc_intensity": 0.2, "revenue_path": [100.0, 110.0, 121.0, 133.1, 146.41, 161.051], "oe_path": [11.0, 12.1, 13.31, 14.641, 16.1051]}


def _dcf(growth, wc=LR_WC):
    return fmt.unbundled_dcf(base_cf=10.0, explicit_growth=[growth] * 5, wacc=0.10, terminal_g=0.03, shares_diluted=1.0, fade_years=5,
                             sbc_treatment="deducted_in_cf", terminal_ronic=0.15, long_run=None, long_run_margin=None,
                             working_capital={"intensity": wc["nwc_intensity"], "revenue": wc["revenue_path"], "owner_earnings": wc["oe_path"]})


def test_two_scenarios_differing_only_in_growth_deduct_on_their_own_revenue_paths_by_hand():
    # the consensus: revenue 100 growing 10% a year with owner earnings 10 growing 10%; intensity 20%
    on = _dcf(0.10)          # on the consensus owner earnings: revenue 110, 121, ...: 20% of 10, 11, 12.1, 13.31, 14.641
    assert on["working_capital_deducted"] == pytest.approx([2.0, 2.2, 2.42, 2.662, 2.9282], abs=1e-4)
    fast = _dcf(0.20)        # owner earnings 12, 14.4, ...: revenue_t = consensus_t x 12/11, x 14.4/12.1, ... = 120, 144, 172.8, 207.36, 248.832
    assert fast["working_capital_deducted"] == pytest.approx([4.0, 4.8, 5.76, 6.912, 8.2944], abs=1e-4)
    flat = _dcf(0.0)         # owner earnings 10 each year: revenue 100 each year: nothing tied up
    assert flat["working_capital_deducted"] == pytest.approx([0.0] * 5, abs=1e-12)
    assert sum(fast["working_capital_deducted"]) > sum(on["working_capital_deducted"]) > sum(flat["working_capital_deducted"])
    assert "working_capital_own_path" in fast["stamps"] and "working_capital_deducted" in fast["stamps"]
    # the flows are the owner earnings less those deductions
    assert fast["projected_cfs"][:2] == pytest.approx([12.0 - 4.0, 14.4 - 4.8], abs=1e-4)
    # a growth of -100% leaves no owner earnings to scale revenue by: no deduction, stamped (never a negative revenue)
    gone = _dcf(-1.0)
    assert gone["working_capital_deducted"] is None and "working_capital_own_path_undefined_nonpositive_owner_earnings" in gone["stamps"]


def test_through_the_desk_each_scenario_deducts_on_its_own_path_and_the_facts_schedule_is_not_read():
    p = {**_ALL_REASONS_GIVEN, "cash_flow_life": "perpetual", "cash_flow_life_reason": "x", "sbc_treatment": "deducted_in_cf", "fade_years": 5,
         "terminal_g": 0.03, "terminal_ronic": 0.15, "long_run_margin": 0.10,
         "scenarios": [{"name": n, "prob": pb, "base_cf": 10.0, "explicit_growth": [g] * 5, "wacc": 0.10}
                       for n, pb, g in (("Base", 0.5, 0.10), ("Bull", 0.25, 0.20), ("Bear", 0.25, 0.0))]}
    ctx = {"price": 100.0, "shares_default_b": 1.0, "coe_anchor": 0.10, "owner_earnings_default_b": 10.0, "long_run": dict(LR_WC),
           "working_capital": [9.0] * 5, "long_run_defaults_withheld": True}           # a schedule in the context: never read
    res = fmt.execute_financial_model(p, ctx)
    assert "error" not in res, res.get("error")
    got = {s["name"]: s["dcf"]["working_capital_deducted"] for s in res["scenario_dcfs"]}
    assert got["Base"] == pytest.approx([2.0, 2.2, 2.42, 2.662, 2.9282], abs=1e-4)
    assert got["Bull"] == pytest.approx([4.0, 4.8, 5.76, 6.912, 8.2944], abs=1e-4)
    assert got["Bear"] == pytest.approx([0.0] * 5, abs=1e-9)
    # no consensus revenue path (as before: no schedule either), or no intensity: no deduction
    for lr in ({"nwc_intensity": 0.2}, {"revenue_path": LR_WC["revenue_path"], "oe_path": LR_WC["oe_path"]}):
        res = fmt.execute_financial_model(copy.deepcopy(p), dict(ctx, long_run=lr))
        assert all(s["dcf"]["working_capital_deducted"] is None for s in res["scenario_dcfs"])


def test_the_built_pack_carries_the_revenue_path_unprinted_and_the_iii_block_prints_the_intensity_not_the_schedule():
    import pack_facts
    lr = pack_facts.quantize_long_run({"nwc_intensity": 0.2, "revenue_path": [100e0, 110e0], "oe_path": [11.0], "stub_months": 3.0})
    assert lr["revenue_path"] == [100.0, 110.0] and lr["oe_path"] == [11.0] and "revenue_path" in pack_facts.LONG_RUN_UNPRINTED
    f = dict(pack_facts.empty(), long_run=dict(lr, nwc_years=[2018, 2025, 8]), working_capital=[1.0, 2.0, 3.0, 4.0, 5.0])
    block = pack_facts.render_defaults_block(f, withhold_reference=True, withhold_long_run=True)
    assert "- working_capital_intensity: 20.00% | " in block and "\n- working_capital: " not in block and "1.000000, 2.000000" not in block
    assert "revenue_path" not in block
    block22 = pack_facts.render_defaults_block(f)
    assert "- working_capital: 1.000000, 2.000000, 3.000000, 4.000000, 5.000000 | " in block22


# ---- the pack revision a frozen pack is recorded with (coordinator) --------------------------------------------------------------------------

def test_a_frozen_revision_22_pack_is_stamped_revision_22_and_the_code_constant_beside_it():
    saved, excerpt = _saved("AMD")
    text22 = rebuild_rev22(excerpt, saved)                       # the saved pack as the rev22 arm prints it: "(pack revision 22)"
    assert text22.startswith("# DATA PACK") and "(pack revision 22)" in text22.split("\n", 1)[0]
    assert cv.pack_revision_stamp(text22, frozen=True) == {"pack_revision": 22, "code_pack_revision": cap.PACK_REVISION}
    assert cv.pack_revision_stamp(text22, frozen=False) == {"pack_revision": cap.PACK_REVISION}
    text24 = text22.replace("(pack revision 22)", "(pack revision 24)", 1)
    assert cv.pack_revision_stamp(text24, frozen=True) == {"pack_revision": 24}
    assert cv.pack_revision_stamp("no marker here", frozen=True) == {"pack_revision": None, "code_pack_revision": cap.PACK_REVISION}
    # the verdict row carries both
    v = dp.band_verdict({"ticker": "AMD", "price": 100.0, "runs": [], "scorecard": {}, "median_iv": None, "spread_pct": None,
                         "pack_revision": 22, "code_pack_revision": 24})
    assert v["pack_revision"] == 22 and v["code_pack_revision"] == 24
