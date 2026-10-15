"""Revision 24 step 2a (brief BRIEF_R24_S2a_desk_fixes.md; PHASE_4_AMENDMENTS.md "Revision 24 step 1", the coordinator's rulings 1-6): the
analyst's long-run margin through the desk call, the annotations that reach the records, the remaining reference leaks, and the reveal off.
The arithmetic fixes (D2, D3, D4) and the margin rule's stamps are tested in test_rev24_desk_arithmetic.py, whose eight strict xfails they turned
into passes."""
import copy
import json
import math
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN  # noqa: E402

INF = math.inf
R, GT, FADE = 0.10, 0.03, 4
# a company with a reference on a revenue path: e5 = oe5 = $100B and m5 10%, so the facts' year-5 revenue is $1,000B; the record's return is
# unlimited at both ends, so every long-run flow is the year's earnings and the margin path can be read off the flows
FACTS_LR = {"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF}


def _ctx(**over):
    ctx = {"price": 1000.0, "shares_default_b": 1.0, "coe_anchor": R, "terminal_g_default": GT, "terminal_g_anchor": GT,
           "owner_earnings_default_b": 100.0, "terminal_ronic": INF, "long_run": dict(FACTS_LR), "years35_cap": None}
    ctx.update(over)
    return ctx


def _sc(name, prob, g, **extra):
    d = {"name": name, "prob": prob, "base_cf": 100.0 / 1.05 ** 5, "explicit_growth": [g] * 5, "wacc": R, "terminal_g": GT,
         "fade_years": FADE}
    d.update(extra)
    return d


def _call(**over):
    p = dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="a perpetual franchise, 10-K 2025", fade_years=FADE,
             terminal_g=GT, sbc_treatment="deducted_in_cf", long_run_margin=0.08,
             scenarios=[_sc("Base", 0.5, 0.05), _sc("Bull", 0.25, 0.09, long_run_margin=0.12), _sc("Bear", 0.25, -0.02, long_run_margin=0.05)])
    p.update(over)
    return p


def _margin_path(dcf):
    """The earnings margin of years 5..5+F as the desk valued them: with an unlimited return each long-run flow is that year's earnings; the
    scenario's year-5 revenue (the desk's echo) grows with the earnings' growth through the fade; year 5's margin is E5 over that revenue."""
    lr = dcf["long_run"]
    rev = lr["year5_revenue"]
    path = [lr["year5_earnings"] / rev]
    for g, flow in zip(dcf["growth_rates_applied"][5:], dcf["projected_cfs"][5:]):
        rev *= 1 + g
        path.append(flow / rev)
    return path


# ---- 1. the analyst's long-run margin through the desk call ---------------------------------------------------------------------

def test_the_margin_path_reaches_the_long_run_margin_at_the_end_of_the_fade_in_base_bull_and_bear():
    """Ruling 1: margin_ratio = long_run_margin / (the scenario's year-5 earnings / its year-5 revenue), applied proportionally over the fade.
    Base takes the top-level 8%, Bull and Bear their own 12% and 5%. Each scenario's year-5 margin is the facts' 10% (its revenue scales with its
    owner earnings, as its earnings do), the path is linear in the fade years, and it ends at the scenario's long_run_margin; the terminal value is
    that margin on the year-N revenue, grown one year at terminal growth, over r - g."""
    res = fmt.execute_financial_model(_call(), _ctx())
    assert "error" not in res, res.get("error")
    for item, m in zip(res["scenario_dcfs"], (0.08, 0.12, 0.05)):
        dcf = item["dcf"]
        path = _margin_path(dcf)
        assert path[0] == pytest.approx(0.10, abs=1e-5)
        assert path == pytest.approx([0.10 + (m - 0.10) * k / FADE for k in range(FADE + 1)], abs=1e-5), item["name"]
        assert dcf["long_run"]["margin_ratio"] == pytest.approx(m / 0.10, abs=1e-4) and dcf["long_run"]["long_run_margin"] == m
        rev_n = dcf["long_run"]["year5_revenue"] * math.prod(1 + g for g in dcf["growth_rates_applied"][5:])
        assert dcf["terminal_value_nominal"] == pytest.approx(m * rev_n * (1 + GT) / (R - GT), rel=1e-5)
        assert "long_run_margin_not_applied_no_revenue" not in dcf["stamps"]


def test_a_fade_of_zero_reaches_the_long_run_margin_in_the_terminal_year():
    res = fmt.execute_financial_model(_call(fade_years=0, scenarios=[dict(s, fade_years=0) for s in _call()["scenarios"]]), _ctx())
    assert "error" not in res, res.get("error")
    for item, m in zip(res["scenario_dcfs"], (0.08, 0.12, 0.05)):
        dcf = item["dcf"]
        rev5 = dcf["long_run"]["year5_revenue"]
        assert dcf["projected_cfs"][5:] == [] and dcf["terminal_value_nominal"] == pytest.approx(m * rev5 * (1 + GT) / (R - GT), rel=1e-5)


def test_a_missing_long_run_margin_is_refused_by_name_and_uses_no_desk_run():
    p = _call()
    del p["long_run_margin"]
    for sc in p["scenarios"]:
        sc.pop("long_run_margin", None)
    res = fmt.execute_financial_model(p, _ctx())
    assert res["validation_error"] is True and res["error"].startswith("Not accepted as a desk run; it does not use one of your desk runs.")
    assert res["missing"] == ["long_run_margin (the earnings margin your long run reaches at the end of the fade, a decimal such as 0.12: your "
                              "judgment, with no default)"]
    # named per scenario when only some lack it
    p = _call()
    del p["long_run_margin"]
    res = fmt.execute_financial_model(p, _ctx())
    assert res["validation_error"] is True and res["missing"][0].startswith("long_run_margin for Base (the earnings margin")
    # a value that is not a number is refused too, whatever its scenario
    bad = _call(long_run_margin="12%")
    assert fmt.execute_financial_model(bad, _ctx())["missing"] == ["long_run_margin for Base (a number, for example 0.12)"]
    # a top-level single run needs it as well
    single = {k: v for k, v in _call().items() if k not in ("scenarios", "long_run_margin")}
    single.update(base_cf=90.0, explicit_growth=[0.05] * 5, wacc=R)
    assert fmt.execute_financial_model(single, _ctx())["missing"][0].startswith("long_run_margin (the earnings margin")
    assert "error" not in fmt.execute_financial_model(dict(single, long_run_margin=0.08), _ctx())


def test_a_finite_cash_flow_life_does_not_need_it():
    p = _call(cash_flow_life=20, fade_years=0)
    del p["long_run_margin"]
    for sc in p["scenarios"]:
        sc.pop("long_run_margin", None)
        sc["fade_years"] = 0
    res = fmt.execute_financial_model(p, _ctx())
    assert "long_run_margin" not in str(res.get("error") or "")


def test_without_a_year5_revenue_the_margin_is_held_and_stamped():
    """No reference (no consensus) or a reference without a revenue path: the facts give no year-5 revenue, so the desk cannot turn an earnings
    margin into a ratio; it holds the margin and says so (an open question for the coordinator: 17 of the 34 saved baseline packs)."""
    for lr in ({"x_over_oe": 0.9, "r_tc": INF}, {"e5": 100.0, "oe5": 100.0, "m5": None, "r_tc": INF}):
        call = _call()
        res = fmt.execute_financial_model(copy.deepcopy(call), _ctx(long_run=lr))
        assert "error" not in res, res.get("error")
        for item, sc in zip(res["scenario_dcfs"], call["scenarios"]):
            dcf = item["dcf"]
            assert "long_run_margin_not_applied_no_revenue" in dcf["stamps"] and dcf["long_run"]["margin_ratio"] is None
            held = fmt.unbundled_dcf(base_cf=sc["base_cf"], explicit_growth=sc["explicit_growth"], wacc=R, terminal_g=GT, shares_diluted=1.0,
                                     fade_years=FADE, sbc_treatment="deducted_in_cf", terminal_ronic=INF, long_run=lr)
            assert dcf["per_share_iv_raw"] == pytest.approx(held["per_share_iv_raw"], rel=1e-12)


def test_a_changed_long_run_margin_is_a_changed_input_for_the_crux_follow_up_and_stage_b():
    a = _call()
    assert fmt.followup_input_changes(_call(long_run_margin=0.09), a) == ["long_run_margin"]
    b = _call()
    b["scenarios"][1]["long_run_margin"] = 0.11
    assert fmt.followup_input_changes(b, a) == ["Bull.long_run_margin"]


def test_the_price_implied_block_and_the_reverse_dcf_value_the_base_with_its_long_run_margin():
    """The solver rebuilds the Base with the Base's long_run_margin (its identity check holds), and the reverse DCF's own structure values the
    Base's growth with it: at the Base's own constant growth the own-structure value is the Base's."""
    flat = _call(scenarios=[_sc("Base", 0.5, 0.05), _sc("Bull", 0.25, 0.09), _sc("Bear", 0.25, -0.02)])
    res = fmt.execute_financial_model(flat, _ctx(price=900.0))
    assert "error" not in res, res.get("error")
    pi = res["price_implied"]
    assert "error" not in pi and pi["growth_years_3_5"]["own"] == pytest.approx(0.05, abs=1e-12)
    base = res["scenario_dcfs"][0]["dcf"]
    own = fmt.reverse_dcf_expectations_gap(current_price=base["per_share_iv_raw"], shares_diluted=1.0, base_cf=_sc("Base", 0.5, 0.05)["base_cf"],
                                           wacc=R, terminal_g=GT, fade_years=FADE, terminal_ronic=INF, long_run=dict(FACTS_LR),
                                           long_run_margin=0.08, x0=0.05)
    assert own["own_structure"]["reachable"] and own["own_structure"]["implied_stage1_growth_pct"] == pytest.approx(5.0, abs=0.01)
    # without the long_run_margin the own structure values another long run (the margin held at 10%), so the same price implies other growth
    held = fmt.reverse_dcf_expectations_gap(current_price=base["per_share_iv_raw"], shares_diluted=1.0, base_cf=_sc("Base", 0.5, 0.05)["base_cf"],
                                            wacc=R, terminal_g=GT, fade_years=FADE, terminal_ronic=INF, long_run=dict(FACTS_LR), x0=0.05)
    assert held["own_structure"]["implied_stage1_growth_pct"] < 5.0 - 0.5
    # and the desk's own reverse DCF (at today's price, 900) is the one with the Base's long_run_margin
    direct = fmt.reverse_dcf_expectations_gap(current_price=900.0, shares_diluted=1.0, base_cf=_sc("Base", 0.5, 0.05)["base_cf"], wacc=R,
                                              terminal_g=GT, fade_years=FADE, terminal_ronic=INF, long_run=dict(FACTS_LR), long_run_margin=0.08,
                                              x0=0.05)
    assert res["reverse_dcf"]["own_structure"]["implied_stage1_growth_pct"] == direct["own_structure"]["implied_stage1_growth_pct"]


# ---- 2. ruling 5: a terminal_ronic below r is stamped in the desk output and the sample record ----------------------------------

def test_a_terminal_ronic_below_r_is_valued_as_r_and_stamped_in_the_desk_output_and_the_sample_record(tmp_path):
    from test_terminal_and_frame import PACK, _dcf, _snapshot
    d = _dcf(0.0898, terminal_ronic=0.05)
    at_r = _dcf(0.0898, terminal_ronic=0.0898)
    assert "terminal_ronic_floored_at_r" in d["stamps"] and "terminal_ronic_floored_at_r" not in at_r["stamps"]
    assert d["per_share_iv"] == at_r["per_share_iv"] and d["terminal_ronic"] == 0.05
    _, st = cv.scenario_checks(_snapshot(tmp_path, d), {"base_iv": d["per_share_iv"]}, None, PACK, 1643.39,
                               facts=dict(pack_facts.empty(), terminal_ronic=0.10))
    assert "terminal_ronic_floored_at_r" in st["desk_stamps"]


# ---- 3. ruling 5: the margin rule's benchmark stamps are logged, never printed ------------------------------------------------------

def test_the_benchmark_stamps_reach_the_facts_stamps_full_and_never_the_pack(screener_data_stub, monkeypatch):
    """The committed GEV slice builds no reference (its base-rate table is missing), so the pack is built with the LITE-like reference of the
    audit (test_rev24_desk_arithmetic.lite_like: an implied OM_5 of 346% and a long-run margin clamped to 0, both stamped by the margin rule) in
    place of the one the slice cannot build."""
    from test_consensus_reference import AMD_EST
    from test_rev24_desk_arithmetic import lite_like
    orig_load = rs2_data.load_json
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00", "estimates": AMD_EST}
    monkeypatch.setattr(rs2_data, "load_json", lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p) else orig_load(p))
    lite, _ = lite_like()
    assert set(cr.BENCHMARK_STAMPS) <= set(lite["stamps"])
    monkeypatch.setattr(cr, "build", lambda *a, **k: copy.deepcopy(lite))
    built = cap.build_pack("GEV")
    lr = built.facts["long_run"]
    assert built.facts["reference_status"] != "not_available" and lr.get("m_long") == 0.0, "the reference did not reach the facts"
    assert set(cr.BENCHMARK_STAMPS) <= set(lr.get("stamps_full") or [])
    assert not set(cr.BENCHMARK_STAMPS) & set(lr.get("stamps") or [])
    for s in cr.BENCHMARK_STAMPS:
        assert s not in str(built)
    assert pack_facts.parity(built.facts, pack_facts.from_text(str(built))) == []


# ---- 4. the remaining reference leaks (R24.2's report) --------------------------------------------------------------------------

def _rebuilt(t):
    from test_rev24_stage_a_pack import _saved, rebuild_rev24
    saved, excerpt = _saved(t)
    text, facts = rebuild_rev24(excerpt, saved)
    return saved, text, facts


CIV_NAMES = ("CONSENSUS-IMPLIED", "consensus-implied", "consensus_implied_value", "CIV", "consensus path", "reference_status")


@pytest.mark.parametrize("t", ("AMD", "KSS", "HRTG"))
def test_no_civ_name_or_value_in_the_rebuilt_pack_text_and_the_facts_parity_holds(t):
    """The three saved packs rebuilt at revision 24 from their facts (DATA 8 and DEFAULTS): no name of the reference, no CONSENSUS-IMPLIED VALUE
    or TTM-window value (in any print form), and the facts the text carries equal the computed ones (parity, the withheld keys aside)."""
    saved, text, facts = _rebuilt(t)
    for name in CIV_NAMES:
        assert name not in text, (t, name)
    civ = saved["consensus_implied_value"]
    for form in (f"{civ:,.2f}", f"{civ:.2f}"):
        assert form not in text, (t, form)
    assert "ttm_value=" not in text and "is worth $" not in text
    assert "- reference_base_b: " in text and "| the fiscal-year owner-earnings base\n" in text
    assert pack_facts.parity(facts, pack_facts.from_text(text)) == []


def test_the_ttm_window_value_is_printed_neither_in_the_window_check_nor_in_defaults_and_its_year2_level_stays():
    win = {"gap": 0.30, "quarters": 2, "expected_ttm": 1e9, "flag": True, "ttm_value": 52.0, "ttm_levels": (1e9, 1.2e9)}
    line = cr.window_line(win, {"value": 40.0}, 1.3e9, "2026-06-30", cap._bn, reference_shown=False)
    assert "52.00" not in line and "40.00" not in line and "consensus path" not in line
    assert "on the TTM window the year-2 cash-flow level is 1.200" in line
    f = dict(pack_facts.empty(), base_window={"gap": 0.30, "ttm_value": 52.0, "ttm_year2": 1.2}, reference_withheld=True)
    block = pack_facts.render_defaults_block(f, withhold_reference=True)
    assert "- base_window: gap=+30%, ttm_year2=1.200 |" in block and "52.00" not in block
    shown = pack_facts.render_defaults_block(dict(f, reference_withheld=None))
    assert "- base_window: gap=+30%, ttm_value=52.00, ttm_year2=1.200 |" in shown          # an older revision prints it as before
    parsed = pack_facts.from_text("# DATA PACK - X   (pack revision 24)\n\n" + block + "\n")
    assert parsed["base_window"] == {"gap": 0.30, "ttm_value": None, "ttm_year2": 1.2}
    assert "base_window" not in pack_facts.parity(f, parsed)


def test_the_task_and_the_desk_schema_name_no_reference_value_and_the_unit_note_says_the_price():
    assert "CONSENSUS-IMPLIED" not in cap.TASK
    assert "rolls the value forward to today at your discount rate.\n" in cap.TASK
    desk = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")
    assert "CONSENSUS-IMPLIED" not in json.dumps(desk)
    p = _call(scenarios=[dict(s, shares_diluted=1000.0e9) for s in _call()["scenarios"]])
    del p["shares_reason"]                                   # a refusal (R1) carries the note; a share count 1000x the default is its cause
    res = fmt.execute_financial_model(p, _ctx(consensus_implied_value=750.0, reference_status="used", reference_withheld=True))
    assert re.search(r"the Base value is [\d.]+x the price, too far", res["error"]) and "x the reference" not in res["error"]


def test_pack_revision_24_and_the_step_2a_history_line():
    assert cap.PACK_REVISION == 24
    src = Path(cap.__file__).read_text(encoding="utf-8")
    assert "the R10 gate is off. Step 2a: desk long_run_margin (analyst), D2–D4 fixed, reveal off." in src


# ---- 5. the reveal off (ruling 1 of cross-check 18) ------------------------------------------------------------------------------

def test_the_reveal_flag_is_off_by_default_in_the_repository_config():
    cfg = json.loads((Path(rs2_data.__file__).resolve().parent / "config.json").read_text(encoding="utf-8-sig"))
    assert cfg.get("reference_reveal") is not True
    assert rs2_data.CONFIG.get("reference_reveal") is not True and at.reference_reveal_enabled() is False


@pytest.mark.parametrize("value", [None, False, "true", 1])
def test_only_a_literal_true_turns_it_on(monkeypatch, value):
    if value is None:
        monkeypatch.delitem(rs2_data.CONFIG, "reference_reveal", raising=False)
    else:
        monkeypatch.setitem(rs2_data.CONFIG, "reference_reveal", value)
    assert at.reference_reveal_enabled() is False
    monkeypatch.setitem(rs2_data.CONFIG, "reference_reveal", True)
    assert at.reference_reveal_enabled() is True


def test_the_default_pipeline_never_sends_the_reveal_and_the_desk_refuses_reference_revision(monkeypatch, tmp_path):
    """A withheld-reference pack whose reference is in force (the case stage B fired for): with the repository's config the session ends at the
    memorandum, REFERENCE_REVEAL is never sent, and the record says stage B did not fire. The desk context the session gives the desk never carries
    reference_revision_inputs, so a call with reference_revision is refused."""
    from test_desk_continuation import MEMO, PRICE, _desk, _serve
    from test_rev24_stage_b import A_ANSWER, REVEAL, _run, entry
    assert at.reference_reveal_enabled() is False
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn_text(MEMO)])          # a third request (the reveal turn) would fail the loop
    rep, _, meta = _run(tmp_path, reveal=REVEAL)
    assert rep == MEMO and len(bodies) == 2
    assert all(not m["content"].startswith("For comparison only:") for b in bodies for m in b["messages"] if m["role"] == "user")
    assert all("reference_revision" not in t["function"]["parameters"]["properties"] for b in bodies for t in b["tools"]
               if t["function"]["name"] == "run_financial_model")
    assert meta["reference_revision"]["fired"] is False and meta["base_iv_final"] == meta["base_iv_stage_a"]
    assert not (tmp_path / "_reference_reveal.md").exists()
    from test_desk_checks import _ctx as desk_ctx
    p = dict(copy.deepcopy(A_ANSWER), reference_revision=[entry("Base.wacc", 0.08, 0.0825)])
    res = fmt.execute_financial_model(p, context=desk_ctx(price=PRICE, reference_withheld=True))
    assert res["validation_error"] is True and res["reference_revision_refused"] == "not_stage_b"


def _turn_text(content):
    from test_desk_continuation import _turn
    return _turn(content)
