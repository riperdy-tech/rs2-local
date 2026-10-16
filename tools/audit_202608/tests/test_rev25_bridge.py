"""Revision 25, Stage 0.3: the bridge desk contract (SPEC_rev25_normalization_bridge.md sections 3 to 8; BRIEF_R25_0_3_desk_contract.md).

1. The switch: desk_schema 25.1 on the arms r25_b and r25_c only; the arms' TASK_REV25, PACK_REVISION 25 for those packs only.
2. The arithmetic (section 4): the long run is unchanged for equal inputs (1e-9), and an independent recompute that imports nothing from rs2 reproduces
   the bridge desk's values on fixed synthetic declarations.
3. The checks C1 to C5 (section 5): a pass, a fail and a not-computable case each; no write path to any input.
4. The desk contract: refusals by name, inheritance, the non-applicable cases, the reason requests, the verdict-row fields and the derived S12 figures.
5. Arm A unchanged: the 22 saved pilot desk calls replayed through execute_financial_model give every Base's per_share_iv_raw exactly (fixtures read in
   place from stocks-workspace/scratch/rev23/pilot_r24, never copied; skipped when absent). The MU worked case (section 7) reads the same fixtures.
"""
import copy
import glob
import json
import math
import os
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bridge_checks as bc  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import contract_fill as cf  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN  # noqa: E402
from test_rev24_s2b_pack import built  # noqa: E402,F401  (the fixture: a built GEV pack)

INF = math.inf
# the pilot runs and the 0.4 synthetic set, read in place under STOCKS_ROOT (never an absolute path; financial_model_tool sets its default)
_SCRATCH = Path(os.environ.get("STOCKS_ROOT") or ".") / "stocks-workspace" / "scratch" / "rev23"
PILOT = _SCRATCH / "pilot_r24" / "runs"
SYNTH = _SCRATCH / "r25_synth"


# ---- the switch ----------------------------------------------------------------------------------------------------------------------------

def test_the_new_arms_are_pilot_arms_and_set_no_p50():
    assert {"r25_b", "r25_c"} <= set(cap.PILOT_ARMS) and cap.R25_ARMS == ("r25_b", "r25_c")
    for arm in cap.R25_ARMS:
        assert cap.pack_flags(arm) == (arm, False)
        with pytest.raises(ValueError):
            cap.pack_flags(arm, ranges_show_p50=True)


def test_desk_schema_is_a_fact_of_its_owner_and_absent_for_every_existing_arm():
    assert "desk_schema" in pack_facts.KEYS and "desk_schema" in pack_facts.SIDECAR_ONLY
    assert pack_facts.empty()["desk_schema"] is None
    assert pack_facts.parity({"desk_schema": "25.1"}, {"desk_schema": None}) == []         # no text prints it, so parity leaves it out


def test_a_built_r25_pack_carries_desk_schema_revision_25_and_its_task(built):
    for arm in cap.R25_ARMS:
        pk = built(pilot_arm=arm)
        assert str(pk).split("\n", 1)[0] == "# DATA PACK - GEV   (pack revision 25)"
        assert pk.facts["desk_schema"] == "25.1" and pk.facts["pilot_arm"] == arm and pk.facts["ranges_show_p50"] is False
        assert cap.task_for(pk.facts) is cap.TASK_REV25
        assert cv.build_desk_context(pk.facts, 100.0, "GEV", "GEV")["desk_schema"] == "25.1"
        assert pack_facts.parity(pk.facts, pack_facts.from_text(str(pk))) == []
    for arm in (None, "iii_p50", "iii_no_p50", "rev22"):
        pk = built(pilot_arm=arm) if arm else built()
        assert pk.facts["desk_schema"] is None
        assert str(pk).split("\n", 1)[0] == f"# DATA PACK - GEV   (pack revision {22 if arm == 'rev22' else 24})"
        assert cap.task_for(pk.facts) is (cap.TASK_REV22 if arm == "rev22" else cap.TASK)
        assert cv.build_desk_context(pk.facts, 100.0, "GEV", "GEV")["desk_schema"] is None


def test_the_r25_task_describes_the_declarations_and_derives_the_two_figures():
    t = cap.TASK_REV25
    assert cap.PACK_REVISION == 24                                   # the module's revision is unchanged: arms iii and rev22 stay as they are
    for word in ("revenue_growth", "earnings_margin", "normalized_margin", "normalization_horizon", "normalized_revenue_base", "structural_growth",
                 "flags", "X basis", "context only", "bridge_C1_reason"):
        assert word in t
    assert "do not type them" in t
    contract = t[t.index("```json:underwriting"):]
    assert '"near_term_earnings"' not in contract and '"normalized_earnings"' not in contract and '"normalization_reason"' in contract
    assert "near_term_earnings" not in cap.FORM_FIELDS_25 and "normalized_earnings" not in cap.FORM_FIELDS_25
    assert t.count(cap.TWO_PASS_TASK_PARAGRAPH) == 1 and "reconciliation_reasons" in contract      # Stage 0.6: the TASK says there are two passes
    assert '"near_term_earnings"' in cap.TASK and "revenue_growth" not in cap.TASK        # the revision-24 TASK is untouched


# ---- fixtures: synthetic facts, a bridge call ------------------------------------------------------------------------------------------------

R_, GT_, F_ = 0.10, 0.03, 4
LR = {"rev_L": 100.0, "x_L": 0.30, "nwc_intensity": 0.10, "m_tc": 0.25, "om_tc": 0.20, "om_L": 0.27, "om_trend": 0.26, "m5": 0.32, "g_rev": 0.05}
BASE_CF = 24.0                                                      # kappa = 24 / (100 x 0.30) = 0.8


def _ctx(**over):
    ctx = {"price": 50.0, "shares_default_b": 1.0, "coe_anchor": R_, "owner_earnings_default_b": BASE_CF, "terminal_g_anchor": GT_,
           "long_run": dict(LR), "long_run_defaults_withheld": True, "desk_schema": "25.1"}
    ctx.update(over)
    return ctx


def _sc(name, prob, **extra):
    d = {"name": name, "prob": prob, "base_cf": BASE_CF, "revenue_growth": [0.10, 0.08, 0.06, 0.05, 0.04],
         "earnings_margin": [0.30, 0.31, 0.32, 0.32, 0.32], "wacc": R_, "terminal_g": GT_, "fade_years": F_, "long_run_margin": 0.30,
         "terminal_ronic": 0.15}
    d.update(extra)
    return d


NORM = dict(normalized_margin=0.30, normalization_horizon=0, structural_growth=0.06, flags=[])


def _call(scs=None, **over):
    p = dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="a perpetual franchise, 10-K 2025", fade_years=F_,
             terminal_g=GT_, sbc_treatment="deducted_in_cf", terminal_ronic=0.15, valuation_frame="equity",
             scenarios=scs or [_sc("Base", 0.5, **NORM), _sc("Bull", 0.25, earnings_margin=[0.31, 0.31, 0.31, 0.31, 0.31], long_run_margin=0.31),
                               _sc("Bear", 0.25, revenue_growth=[0.06] * 5, earnings_margin=[0.29, 0.29, 0.29, 0.29, 0.29],
                                   long_run_margin=0.29)])
    p.update(over)
    return p


def _run(call=None, ctx=None):
    return fmt.execute_financial_model(copy.deepcopy(call or _call()), ctx or _ctx())


def _dcf(res, role):
    return next(i["dcf"] for i in res["scenario_dcfs"] if i["name"].lower().startswith(role))


# ---- the arithmetic: section 8's two tests -----------------------------------------------------------------------------------------------------

def _independent(sc, lr, r, shares, ronic_t, gt, F):
    """The bridge desk's value from the spec alone: imports nothing from rs2."""
    R0, x0 = lr["rev_L"], lr["x_L"]
    kappa = sc["base_cf"] / (R0 * x0)
    R = [R0]
    for g in sc["revenue_growth"]:
        R.append(R[-1] * (1 + g))
    m = sc["earnings_margin"]
    oe = [kappa * R[t] * m[t - 1] for t in range(1, 6)]
    wc = [lr["nwc_intensity"] * (R[t] - R[t - 1]) for t in range(1, 6)]
    pv = sum((oe[t - 1] - wc[t - 1]) / (1 + r) ** t for t in range(1, 6))
    e5, g5, ratio = R[5] * m[4], R[5] / R[4] - 1, sc["long_run_margin"] / m[4]
    cum = 1.0
    for t in range(6, 6 + F):
        g = g5 + (gt - g5) * (t - 5) / F
        gn = gt if t + 1 > 5 + F else g5 + (gt - g5) * (t + 1 - 5) / F
        cum *= 1 + g
        e = e5 * cum * (1 + (ratio - 1) * (t - 5) / F)
        pv += e * (1 - gn / ronic_t) / (1 + r) ** t
    n = 5 + F
    e_term = e5 * cum * ratio * (1 + gt)
    pv += e_term * (1 - gt / ronic_t) / (r - gt) / (1 + r) ** n
    return pv / shares


SYNTHETIC = [
    dict(base=_sc("Base", 0.5, **NORM)),
    dict(base=_sc("Base", 0.5, revenue_growth=[0.30, 0.12, 0.05, 0.02, 0.0], earnings_margin=[0.35, 0.30, 0.25, 0.22, 0.20], long_run_margin=0.18,
                  normalized_margin=0.18, normalization_horizon=6, structural_growth=0.03, flags=["cyclical"], cycle_position="peak",
                  cycle_evidence="inventory days 112 vs 70 (10-Q)")),
    dict(base=_sc("Base", 0.5, revenue_growth=[-0.10, -0.05, 0.0, 0.01, 0.02], earnings_margin=[0.25, 0.26, 0.28, 0.30, 0.31], long_run_margin=0.31,
                  normalized_margin=0.31, normalization_horizon=5, structural_growth=0.0, flags=["turnaround"])),
]


@pytest.mark.parametrize("case", range(len(SYNTHETIC)))
def test_an_independent_recompute_reproduces_the_bridge_desk(case):
    base = SYNTHETIC[case]["base"]
    bull = dict(base, name="Bull", prob=0.25)
    bear = dict(base, name="Bear", prob=0.25)
    res = _run(_call([base, bull, bear], bridge_C1_reason="r", bridge_C1b_reason="r", bridge_C2_reason="r", bridge_C3_reason="r",
                     bridge_C4_reason="r", bridge_C5_reason="r"))
    assert "error" not in res, res.get("error")
    d = _dcf(res, "base")
    want = _independent(base, LR, R_, 1.0, 0.15, GT_, F_)
    assert d["per_share_iv_raw"] == pytest.approx(want, rel=1e-9)
    assert d["bridge"]["applied"] and d["bridge"]["kappa"] == pytest.approx(0.8, rel=1e-12)
    assert "desk_schema_25_1" in d["stamps"] and "working_capital_bridge_revenue" in d["stamps"]


def test_the_long_run_is_unchanged_for_equal_inputs_to_1e_9(monkeypatch):
    """The bridge path calls consensus_reference.long_run_value with (e5 = R5 m5, g5 = R5/R4 - 1, margin_ratio = long_run_margin / m5, the same RONIC,
    fade and terminal); a revision-24 call that arrives at the same five inputs gets the same call, and the same years-6-on value."""
    calls = []
    real = cr.long_run_value

    def spy(*a, **k):
        out = real(*a, **k)
        calls.append((a, k, out))
        return out
    monkeypatch.setattr(cr, "long_run_value", spy)
    base = _sc("Base", 0.5, **NORM)
    br = _run(_call([base, dict(base, name="Bull", prob=0.25), dict(base, name="Bear", prob=0.25)]))
    assert "error" not in br, br.get("error")
    args_bridge = calls[0][0]
    R = [100.0]
    for g in base["revenue_growth"]:
        R.append(R[-1] * (1 + g))
    m5 = base["earnings_margin"][4]
    assert args_bridge[0] == pytest.approx(R[5] * m5, rel=1e-12) and args_bridge[1] == pytest.approx(R[5] / R[4] - 1, rel=1e-12)
    assert args_bridge[6] == pytest.approx(base["long_run_margin"] / m5, rel=1e-12) and args_bridge[7] == F_
    ret_bridge = calls[0][2]
    # revision 24 on the same five inputs: the facts' e5 = oe5 = 1 make the scenario's e5 its own year-5 owner earnings, which we set to R5 m5;
    # its year-5 growth is g5 (year 4 = year 5 / (1 + g5)); the facts' m5 is the declared year-5 margin, so the margin ratio matches
    oe5 = R[5] * m5
    oe4 = oe5 / (R[5] / R[4])
    lr24 = {"e5": 1.0, "oe5": 1.0, "m5": m5, "rev_L": 100.0, "x_L": 0.30, "nwc_intensity": 0.10}
    sc24 = {"name": "Base", "prob": 0.5, "base_cf": BASE_CF, "explicit_growth": [oe4 / BASE_CF - 1, 0.0, 0.0, 0.0, R[5] / R[4] - 1], "wacc": R_,
            "terminal_g": GT_, "fade_years": F_, "long_run_margin": base["long_run_margin"], "terminal_ronic": 0.15}
    calls.clear()
    r24 = fmt.execute_financial_model(copy.deepcopy(_call([sc24, dict(sc24, name="Bull", prob=0.25), dict(sc24, name="Bear", prob=0.25)])),
                                      _ctx(desk_schema=None, long_run=lr24))
    assert "error" not in r24, r24.get("error")
    for a, b in zip(args_bridge, calls[0][0]):
        assert a == pytest.approx(b, rel=1e-9)
    assert ret_bridge["value_raw"] == pytest.approx(calls[0][2]["value_raw"], rel=1e-9, abs=1e-9)
    assert ret_bridge["tv_pv"] == pytest.approx(calls[0][2]["tv_pv"], rel=1e-9, abs=1e-9)


# ---- the checks: a pass, a fail and a not-computable case each ----------------------------------------------------------------------------------

PATH = [0.30, 0.31, 0.32, 0.33, 0.34] + [0.34 - 0.01 * i for i in range(1, 6)]            # m_1..m_10 ending at 0.29


def test_the_tolerances_are_one_dict_and_marked_frozen():
    assert set(bc.BRIDGE_TOLERANCES) == {"tau_m_y1_5", "tau_m_y6_10", "tau_m_y11_plus", "tau_R_T5", "tau_R_TH", "tau_b", "tau_g"}
    assert bc.BRIDGE_TOLERANCES["tau_m_y1_5"] == 0.03 and bc.BRIDGE_TOLERANCES["tau_R_T5"] == 0.10 and bc.BRIDGE_TOLERANCES["tau_b"] == 0.01
    src = (HERE.parent / "bridge_checks.py").read_text(encoding="utf-8")
    block = src[src.index("BRIDGE_TOLERANCES: Dict"):src.index("KNOWN_FLAGS")]
    assert "UNCALIBRATED" not in block and "FROZEN 2026-10-16" in src                        # Stage 0.4 step 5 replaced the placeholders
    assert fmt.__dict__.get("BRIDGE_TOLERANCES") is None                                       # nothing reads a tolerance from anywhere else


def _shape(r):
    assert set(r) >= {"id", "status", "declared", "derived", "horizon", "tolerance"} and r["status"] in ("pass", "fail", "not_computable")
    return r["status"]


CASES = [
    # (name, call, expected status)
    ("C1 pass", lambda: bc.check_c1(PATH, 0.29, 10), "pass"),
    ("C1 pass inside tolerance from the horizon", lambda: bc.check_c1(PATH, 0.315, 3), "pass"),
    ("C1 fail", lambda: bc.check_c1(PATH, 0.222, 10), "fail"),
    ("C1 not computable", lambda: bc.check_c1(PATH, None, 10), "not_computable"),
    ("C1b pass", lambda: bc.check_c1b(0.30, 0.31, 5), "pass"),
    ("C1b fail", lambda: bc.check_c1b(0.35, 0.222, 5), "fail"),
    ("C1b not computable", lambda: bc.check_c1b(None, 0.222, 5), "not_computable"),
    ("C2 peak pass", lambda: bc.check_c2("peak", 0.30, 0.638), "pass"),
    ("C2 peak fail", lambda: bc.check_c2("peak", 0.70, 0.638), "fail"),
    ("C2 trough pass", lambda: bc.check_c2("trough", 0.30, 0.20), "pass"),
    ("C2 trough fail", lambda: bc.check_c2("trough", 0.10, 0.20), "fail"),
    ("C2 mid pass", lambda: bc.check_c2("mid", 0.21, 0.20), "pass"),
    ("C2 mid fail", lambda: bc.check_c2("mid", 0.30, 0.20), "fail"),
    ("C2 not computable (no position)", lambda: bc.check_c2(None, 0.30, 0.20), "not_computable"),
    ("C3 pass", lambda: bc.check_c3([100, 106, 112, 119, 126, 133.8], None, 0.06, 0), "pass"),
    ("C3 fail", lambda: bc.check_c3([100, 106, 112, 119, 126, 133.8], None, 0.15, 0), "fail"),
    ("C3 cyclical revenue not rejoined by H", lambda: bc.check_c3([100, 90, 85, 84, 86, 107], 80.0, 0.06, 4), "fail"),
    ("C3 cyclical revenue rejoined by H", lambda: bc.check_c3([100, 90, 95, 98, 101, 107], 80.0, 0.06, 4), "pass"),
    ("C3 not computable", lambda: bc.check_c3([100, 106], None, 0.06, 0), "not_computable"),
    ("C4 pass", lambda: bc.check_c4(["cyclical"], 0.03, 0.05, 0.2, 0.3, 4, "DRAM price index"), "pass"),
    ("C4 fail: cyclical without evidence", lambda: bc.check_c4(["cyclical"], 0.03, 0.05, 0.2, 0.3, 4, None), "fail"),
    ("C4 fail: structural_decline with growth", lambda: bc.check_c4(["structural_decline"], 0.02, 0.05, 0.2, 0.3, 0, None), "fail"),
    ("C4 fail: no flag with a horizon", lambda: bc.check_c4([], 0.03, 0.05, 0.2, 0.3, 3, None), "fail"),
    ("C4 fail: turnaround without a higher margin", lambda: bc.check_c4(["turnaround"], 0.03, 0.05, 0.2, 0.3, 3, None), "fail"),
    ("C4 fail: structural_growth not above the trend", lambda: bc.check_c4(["structural_growth"], 0.03, 0.05, 0.3, 0.3, 0, None), "fail"),
    ("C4 not computable (no trend in the facts)", lambda: bc.check_c4(["structural_growth"], 0.09, None, 0.3, 0.3, 0, None), "not_computable"),
    ("C4 not computable (flags unreadable)", lambda: bc.check_c4("cyclical", 0.03, 0.05, 0.2, 0.3, 4, "x"), "not_computable"),
    ("C5 pass", lambda: bc.check_c5({"normalized_margin": 0.222}, {"om_tc": 0.244}, {"m_tc": 0.222}), "pass"),
    ("C5 fail: the operating median declared as an X margin", lambda: bc.check_c5({"normalized_margin": 0.244}, {"om_tc": 0.244},
                                                                                {"m_tc": 0.222, "x_L": 0.638}), "fail"),
    ("C5 not computable", lambda: bc.check_c5({"normalized_margin": 0.244}, {}, {"m_tc": 0.222}), "not_computable"),
]


@pytest.mark.parametrize("name,call,want", CASES, ids=[c[0] for c in CASES])
def test_each_check_has_its_pass_fail_and_not_computable_cases(name, call, want):
    assert _shape(call()) == want


def test_c3_with_cyclical_revenue_checks_the_horizon_too_and_only_year_5_when_h_is_0():
    # R_N0 = 80 and g_S = 6%: the normal level is 101.0 at T = 4 and 107.06 at T = 5
    r = bc.check_c3([100, 90, 85, 84, 86, 107], 80.0, 0.06, 4)
    assert r["status"] == "fail" and r["horizon"] == 4 and r["declared"] == pytest.approx(80 * 1.06 ** 4)       # T = 5 alone would have passed
    assert bc.check_c3([100, 90, 85, 84, 86, 107], 80.0, 0.06, 0)["status"] == "pass"                           # H = 0: only T = 5
    assert bc.check_c3([100, 90, 85, 84, 86, 107], 80.0, 0.06, 0)["horizon"] == 5
    assert bc.check_c3([100, 90, 85, 84, 86, 107], None, 0.06, 4)["horizon"] == 5                              # R_N0 = R_0: no second point


def test_the_margin_path_is_declared_then_a_straight_line_to_the_long_run_margin():
    p = bc.margin_path([0.3, 0.3, 0.3, 0.3, 0.4], 0.2, 5)
    assert p[:5] == [0.3, 0.3, 0.3, 0.3, 0.4] and p[-1] == pytest.approx(0.2) and p[5] == pytest.approx(0.4 - 0.04)
    assert bc.margin_path([0.3] * 5, 0.2, 0) == [0.3] * 5


class _Frozen(list):
    def _no(self, *a, **k):
        raise AssertionError("a check wrote to its input")
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = sort = reverse = clear = __iadd__ = _no


def test_no_check_writes_to_any_input():
    kw = dict(margins_1_5=_Frozen([0.3, 0.3, 0.3, 0.3, 0.3]), long_run_margin=0.2, fade_years=5, m_N=0.25, H=3, m_0=0.3,
              revenue=_Frozen([100, 105, 110, 115, 120, 125]), R_N0=None, g_S=0.05, flags=_Frozen(["cyclical"]), g_rev=0.04, cycle_position="peak",
              cycle_evidence="x", operating_facts=types.MappingProxyType({"om_tc": 0.25}), x_facts=types.MappingProxyType({"m_tc": 0.2}))
    snapshot = copy.deepcopy({k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, types.MappingProxyType) else v) for k, v in kw.items()})
    out = bc.run_checks(**kw)
    assert [c["id"] for c in out] == list(bc.CHECK_IDS)
    for k, v in kw.items():
        now = list(v) if isinstance(v, list) else dict(v) if isinstance(v, types.MappingProxyType) else v
        assert now == snapshot[k], k
    src = (HERE.parent / "bridge_checks.py").read_text(encoding="utf-8")
    assert "open(" not in src and "write" not in src.replace("writes", "") and "import os" not in src


# ---- the desk contract ----------------------------------------------------------------------------------------------------------------------

def test_the_bridge_desk_returns_the_derived_table_n0_and_the_checks():
    res = _run()
    assert "error" not in res, res.get("error")
    b = _dcf(res, "base")["bridge"]
    assert b["revenue"][0] == 100.0 and b["margin"][0] == pytest.approx(0.30) and b["owner_earnings"][0] == pytest.approx(BASE_CF)
    assert b["owner_earnings"][1] == pytest.approx(0.8 * 110.0 * 0.30)
    assert b["working_capital"][0] == pytest.approx(0.10 * 10.0)
    assert len(b["margin_path"]) == 5 + F_ and b["n0"] == pytest.approx(0.30 * 100.0)
    assert [c["id"] for c in b["checks"]] == list(bc.CHECK_IDS)
    md = fmt.format_model_results_markdown(res)
    assert "derived path (years 0-5" in md and "| Check | Status |" in md and "Normalized earnings: N_0 = 30.0000" in md
    assert _dcf(res, "base")["explicit_growth"] and "reverse_dcf" in res


def test_bull_and_bear_inherit_the_bases_normalization_unless_they_give_their_own():
    res = _run(_call([_sc("Base", 0.5, **NORM), _sc("Bull", 0.25, normalized_margin=0.31), _sc("Bear", 0.25)]))
    assert "error" not in res, res.get("error")
    bull, bear = _dcf(res, "bull")["bridge"]["declared"], _dcf(res, "bear")["bridge"]["declared"]
    assert bear["normalized_margin"] == 0.30 and set(bear["inherited"]) >= {"normalized_margin", "normalization_horizon", "structural_growth", "flags"}
    assert bull["normalized_margin"] == 0.31 and "normalized_margin" not in bull["inherited"] and bull["structural_growth"] == 0.06


def test_a_missing_declaration_is_refused_by_name():
    for field in ("revenue_growth", "earnings_margin"):
        scs = [_sc("Base", 0.5, **NORM), _sc("Bull", 0.25), _sc("Bear", 0.25)]
        del scs[0][field]
        res = _run(_call(scs))
        assert res["validation_error"] is True and any(m.startswith(f"{field} for Base") for m in res["missing"]), res
    for field in ("normalized_margin", "normalization_horizon", "structural_growth", "flags"):
        base = dict(_sc("Base", 0.5, **NORM))
        del base[field]
        res = _run(_call([base, _sc("Bull", 0.25), _sc("Bear", 0.25)]))
        names = [m.split(" ", 1)[0] for m in res["missing"]]
        assert names.count(field) == 1, (field, res["missing"])          # named once: Bull and Bear inherit the Base's gap and do not repeat it
    res = _run(_call([dict(_sc("Base", 0.5, **NORM), normalization_horizon=3.5), _sc("Bull", 0.25), _sc("Bear", 0.25)]))
    assert any(m.startswith("normalization_horizon for Base") for m in res["missing"])
    res = _run(_call([dict(_sc("Base", 0.5, **NORM), normalization_horizon=10), _sc("Bull", 0.25), _sc("Bear", 0.25)]))
    assert any(m.startswith("normalization_horizon for Base") for m in res["missing"])           # beyond 5 + fade_years (9)


def test_growth_rates_and_explicit_growth_are_refused_under_25_1_naming_the_new_fields():
    for key in ("explicit_growth", "growth_rates"):
        scs = [dict(_sc("Base", 0.5, **NORM), **{key: [0.1] * 5}), _sc("Bull", 0.25), _sc("Bear", 0.25)]
        res = _run(_call(scs))
        assert res["validation_error"] is True
        msg = " ".join(res["missing"])
        assert f"{key} in Base" in msg and "revenue_growth and earnings_margin" in msg
    res = _run(_call(explicit_growth=[0.1] * 5))
    assert "explicit_growth at the top level" in " ".join(res["missing"])


def test_a_scenario_where_the_bridge_does_not_apply_keeps_revision_24s_path_and_says_so():
    cases = {"x_L_missing": _ctx(long_run={k: v for k, v in LR.items() if k != "x_L"}),
             "revenue_not_positive": _ctx(long_run=dict(LR, rev_L=0.0)), "earnings_not_positive": _ctx(long_run=dict(LR, x_L=-0.1))}
    for why, ctx in cases.items():
        scs = [dict({k: v for k, v in _sc(n, p).items() if k not in ("revenue_growth", "earnings_margin")}, explicit_growth=[0.08] * 5)
               for n, p in (("Base", 0.5), ("Bull", 0.25), ("Bear", 0.25))]
        res = _run(_call(scs), ctx)
        assert "error" not in res, (why, res.get("error"))
        d = _dcf(res, "base")
        assert f"bridge_not_applied:{why}" in d["stamps"] and d["bridge"] == {"applied": False, "reason": why}
        assert f"bridge_not_applied:{why}" in res["desk_stamps"]
    # the firm frame: not applied, revision 24's path (which needs net_debt and interest_addback in its own way; the stamp is what is tested here)
    plan = fmt._bridge_not_applied_reason(LR, "firm", "perpetual"), fmt._bridge_not_applied_reason(LR, "equity", 10)
    assert plan == ("firm_frame", "finite_life") and fmt._bridge_not_applied_reason(LR, "equity", "perpetual") is None
    # revision 24's path under 25.1 still needs explicit_growth where the bridge does not apply
    res = _run(_call([_sc("Base", 0.5, **NORM), _sc("Bull", 0.25), _sc("Bear", 0.25)]), cases["x_L_missing"])
    assert any("explicit_growth" in m for m in res["missing"])


def test_a_pack_without_desk_schema_ignores_the_bridge_fields_entirely():
    scs = [dict({k: v for k, v in _sc(n, p, **NORM).items() if k not in ("revenue_growth", "earnings_margin")}, explicit_growth=[0.08] * 5)
           for n, p in (("Base", 0.5), ("Bull", 0.25), ("Bear", 0.25))]
    res = _run(_call(scs), _ctx(desk_schema=None))
    assert "error" not in res, res.get("error")
    assert all("bridge" not in i["dcf"] for i in res["scenario_dcfs"])


def test_a_failed_check_draws_a_named_reason_and_with_it_the_value_computes_and_the_check_stays_fail():
    base = _sc("Base", 0.5, **dict(NORM, normalized_margin=0.15))           # the margin path ends at 0.30: C1 and C1b disagree with 0.15
    call = _call([base, _sc("Bull", 0.25, normalized_margin=0.30), _sc("Bear", 0.25, normalized_margin=0.30)])
    res = _run(call)
    assert res["validation_error"] is True
    names = {n["reason"] for n in res["needs_reasons"]}
    assert {"bridge_C1_reason", "bridge_C1b_reason"} <= names and all(n.startswith("bridge_C") for n in names - {"scenario_deviation_reason"})
    call2 = dict(call, bridge_C1_reason="the 8-year median is the right level, 10-K 2025", bridge_C1b_reason="a second step down, 10-K 2025")
    res2 = _run(call2)
    assert "error" not in res2, res2.get("error")
    checks = {c["id"]: c for c in _dcf(res2, "base")["bridge"]["checks"]}
    assert checks["C1"]["status"] == "fail" and checks["C1"]["reason_given"] is True       # never re-labelled
    assert checks["C1b"]["status"] == "fail" and checks["C1b"]["reason_given"] is True
    assert "reason_given" not in checks["C2"]
    # the declared inputs are untouched: the value is the one the independent recompute gives
    assert _dcf(res2, "base")["per_share_iv_raw"] == pytest.approx(_independent(call["scenarios"][0], LR, R_, 1.0, 0.15, GT_, F_), rel=1e-9)


def test_the_price_implied_block_values_the_base_through_the_bridge():
    res = _run()
    pi = res["price_implied"]
    assert "error" not in pi and pi["growth_years_3_5"]["not_available"].startswith("not applicable under desk schema 25.1")
    assert pi["year2_level"]["not_available"].startswith("not applicable under desk schema 25.1")
    assert pi["long_run_margin"]["own"] == pytest.approx(0.30)


# ---- the contract: the verdict-row fields and the derived S12 figures ----------------------------------------------------------------------------

def _snapshot_call(res, params):
    return {"tool": "run_financial_model", "call_index": 1, "params": params, "scenario_dcfs": res["scenario_dcfs"],
            "kelly_sizing": res.get("kelly_sizing"), "price": res["price"], "price_implied": res.get("price_implied")}


def test_the_fill_derives_the_two_s12_figures_from_the_base_bridge_and_stamps_a_typed_difference():
    call = _call()
    res = _run(call)
    assert "error" not in res
    facts = {"desk_schema": "25.1", "coe_anchor": R_, "shares_outstanding": 1.0, "long_run_defaults_withheld": True}
    snap = [_snapshot_call(res, call)]
    filled, prov = cf.fill(snap, {}, facts, 50.0)
    b = _dcf(res, "base")["bridge"]
    assert filled["desk_schema"] == "25.1" and filled["bridge"]["n0"] == b["n0"] and filled["normalized_earnings"] == pytest.approx(30.0)
    assert filled["near_term_earnings"] == pytest.approx(b["earnings"][1])         # the audit: a number, E_1 (E_2 is in the bridge table)
    assert set(filled["bridge_checks"]) == {"base", "bull", "bear"} and prov["stamps"] == []
    filled2, prov2 = cf.fill(snap, {"normalized_earnings": 80.0, "near_term_earnings": 50.0}, facts, 50.0)
    assert filled2["normalized_earnings"] == pytest.approx(30.0) and prov2["stamps"] == ["s12_figure_derived_under_25_1"]     # the typed 80 is ignored
    filled3, prov3 = cf.fill(snap, {"normalized_earnings": 30.0, "near_term_earnings": filled["near_term_earnings"]}, facts, 50.0)
    assert prov3["stamps"] == []


def test_a_fill_without_desk_schema_is_what_it_was():
    call = _call()
    res = fmt.execute_financial_model(copy.deepcopy(call), _ctx())
    filled, prov = cf.fill([_snapshot_call(res, call)], {}, {"coe_anchor": R_, "shares_outstanding": 1.0}, 50.0)
    for k in cf.REVISION_25:
        assert k not in filled and k not in prov["unfilled"]
    assert "stamps" not in prov


def test_the_verdict_row_fields_have_their_owners():
    import depth_pipeline
    src = Path(depth_pipeline.__file__).read_text(encoding="utf-8")
    for k in ("bridge", "bridge_checks", "desk_schema"):
        assert f'"{k}"' in src and k in cv.S12_SUMMARY_KEYS and k in cf.FILLED_25 and k not in cf.FILLED


# ---- arm A unchanged, and the MU worked case, on the saved pilot runs ---------------------------------------------------------------------------

def _pilot_runs():
    return sorted(glob.glob(str(PILOT / "*" / "*" / "*" / "sample1_research" / "_research_snapshot.json")))


def _last_desk_call(snap):
    calls = json.loads(Path(snap).read_text(encoding="utf-8"))["calls"]
    return [x for x in calls if x.get("tool") == "run_financial_model" and x.get("scenario_dcfs")][-1]


def _base_name(dcfs):
    return next(s for s in dcfs if "bull" not in s["name"].lower() and "bear" not in s["name"].lower())


@pytest.mark.skipif(not _pilot_runs(), reason="the pilot_r24 fixtures are read in place and are absent")
def test_arm_a_is_unchanged_on_the_22_saved_pilot_desk_calls():
    snaps = _pilot_runs()
    assert len(snaps) == 22
    for snap in snaps:
        rd = Path(snap).parent.parent
        facts = json.loads((rd / "_pack_facts.json").read_text(encoding="utf-8"))
        c = _last_desk_call(snap)
        ctx = cv.build_desk_context(facts, float(c["price"]), facts.get("ticker") or "X", "Co", run_date="2026-10-16")
        res = fmt.execute_financial_model(c["params"], ctx)
        got = _base_name(res["scenario_dcfs"])["dcf"]["per_share_iv_raw"]
        assert got == _base_name(c["scenario_dcfs"])["dcf"]["per_share_iv_raw"], snap          # exactly equal
        assert "bridge" not in _base_name(res["scenario_dcfs"])["dcf"]


def _mu():
    snaps = [s for s in _pilot_runs() if os.sep + "MU" + os.sep in s and "iii_p50_s2401" in s]
    if not snaps:
        pytest.skip("the MU pilot fixture is absent")
    rd = Path(snaps[0]).parent.parent
    facts = dict(json.loads((rd / "_pack_facts.json").read_text(encoding="utf-8")), desk_schema="25.1")
    c = _last_desk_call(snaps[0])
    return facts, c, cv.build_desk_context(facts, float(c["price"]), "MU", "Micron", run_date="2026-10-16")


def _mu_call(c, m_N, H=10, **reasons):
    p = {k: v for k, v in c["params"].items() if k not in ("scenarios", "crux")}
    scs = []
    for name, prob, mg, lrm in (("Base", 0.5, [0.60, 0.55, 0.50, 0.45, 0.40], 0.35), ("Bull", 0.3, [0.62, 0.58, 0.52, 0.45, 0.40], 0.35),
                                ("Bear", 0.2, [0.50, 0.45, 0.42, 0.40, 0.38], 0.35)):
        s = {"name": name, "prob": prob, "base_cf": 62.397, "revenue_growth": [0.30, 0.15, 0.08, 0.05, 0.03], "earnings_margin": mg,
             "long_run_margin": lrm, "fade_years": 5, "wacc": 0.1041, "terminal_g": 0.025, "terminal_ronic": 0.15}
        if name == "Base":
            s.update(normalized_margin=m_N, normalization_horizon=H, structural_growth=0.117, flags=["cyclical"])
        scs.append(s)
    p.update(scenarios=scs, fade_years=5, cycle_position="peak", cycle_evidence="DRAM contract price index peaked 2026Q3",
             scenario_deviation_reason="dated", bull_below_price_reason="dated", bear_above_price_reason="dated", **reasons)
    return p


def test_mu_worked_case_with_the_normalized_margin_at_the_end_of_the_fade_passes_and_n0_is_46_6():
    facts, c, ctx = _mu()
    res = fmt.execute_financial_model(_mu_call(c, 0.35), ctx)
    assert "error" not in res, res.get("error")
    b = _dcf(res, "base")["bridge"]
    st = {k["id"]: k["status"] for k in b["checks"]}
    assert st["C1"] == "pass" and st["C2"] == "pass" and st["C1b"] == "pass"
    assert round(b["n0"], 1) == 46.6 and b["n0"] == pytest.approx(0.35 * 133.188)


def test_mu_with_the_x_basis_median_fails_c1_and_draws_bridge_c1_reason():
    facts, c, ctx = _mu()
    res = fmt.execute_financial_model(_mu_call(c, 0.222), ctx)
    assert res["validation_error"] is True and "bridge_C1_reason" in {n["reason"] for n in res["needs_reasons"]}
    res = fmt.execute_financial_model(_mu_call(c, 0.222, bridge_C1_reason="the 8-year X-basis median", bridge_C1b_reason="the same"), ctx)
    assert "error" not in res, res.get("error")
    c1 = next(k for k in _dcf(res, "base")["bridge"]["checks"] if k["id"] == "C1")
    assert c1["status"] == "fail" and c1["reason_given"] is True
    assert _dcf(res, "base")["bridge"]["n0"] == pytest.approx(0.222 * 133.188)            # 29.6


# ---- the Stage 0.3 audit (coordinator) -----------------------------------------------------------------------------------------------------------
def test_c5_reads_only_the_two_normalization_margins():
    ops, xs = {"om_tc": 0.20, "om_L": 0.47, "om_trend": 0.24}, {"m_tc": 0.15, "x_L": 0.40, "m5": 0.38}
    # a year-1 margin on an operating figure is not a basis claim
    res = bc.run_checks(margins_1_5=[0.47, 0.30, 0.15, 0.15, 0.15], long_run_margin=0.15, fade_years=5, m_N=0.15, H=3, m_0=0.40,
                        revenue=[10, 9, 8, 7.5, 7.8, 8.1], R_N0=6.5, g_S=0.04, flags=["cyclical"], g_rev=0.06, cycle_position="peak",
                        cycle_evidence="x", operating_facts=ops, x_facts=xs)
    assert {r["id"]: r["status"] for r in res}["C5"] == "pass"
    hit = bc.check_c5({"normalized_margin": 0.24}, ops, xs)
    assert hit["status"] == "fail" and hit["derived"][0]["operating_fact"] == "om_trend"


def test_a_deviation_equal_to_the_tolerance_passes():
    tol = bc.BRIDGE_TOLERANCES["tau_m_y1_5"]
    assert bc.check_c1([0.10 + tol] * 5, 0.10, 1)["status"] == "pass"
    assert bc.check_c1([0.10 + tol + 1e-6] * 5, 0.10, 1)["status"] == "fail"


def test_the_bridge_checks_agree_with_the_coordinators_reference_on_the_synthetic_set():
    """0.4 step 3's 150 cases (scratch/rev23/r25_synth, frozen, sha256 714421ca...) at both ends of the admissible range: every status equals the
    coordinator's independent ref_checks. Read in place; skipped when absent."""
    cases_file = SYNTH / "synth_cases.json"
    if not cases_file.exists():
        pytest.skip("the synthetic set is absent")
    sys.path.insert(0, str(SYNTH))
    try:
        from ref_checks import check_all
    finally:
        sys.path.remove(str(SYNTH))
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    saved = dict(bc.BRIDGE_TOLERANCES)
    try:
        for t in ({"m15": 0.005, "m610": 0.005, "R": 0.02, "b": 0.0025}, {"m15": 0.06, "m610": 0.06, "R": 0.20, "b": 0.02}):
            bc.BRIDGE_TOLERANCES.update(tau_m_y1_5=t["m15"], tau_m_y6_10=t["m610"], tau_m_y11_plus=t["m610"], tau_R_T5=t["R"], tau_R_TH=t["R"],
                                        tau_b=t["b"])
            for c in cases:
                f, d = c["facts"], c["decl"]
                R = [f["rev_L"]]
                for g in d["revenue_growth"]:
                    R.append(R[-1] * (1 + g))
                got = {r["id"]: r["status"] for r in bc.run_checks(
                    margins_1_5=d["earnings_margin"], long_run_margin=d["long_run_margin"], fade_years=d["fade_years"], m_N=d["normalized_margin"],
                    H=d["normalization_horizon"], m_0=f["x_L"], revenue=R, R_N0=d["normalized_revenue_base"], g_S=d["structural_growth"],
                    flags=d["flags"], g_rev=f["g_rev"], cycle_position=d["cycle_position"], cycle_evidence=d["cycle_evidence"],
                    operating_facts={k: f[k] for k in ("om_tc", "om_L", "om_trend")}, x_facts={k: f[k] for k in ("m_tc", "x_L", "m5")})}
                want = {k: {"question": "fail", "not_applicable": "not_computable"}.get(v, v) for k, v in check_all(c, t).items()}
                assert got == want, c["id"]
    finally:
        bc.BRIDGE_TOLERANCES.clear()
        bc.BRIDGE_TOLERANCES.update(saved)


def test_the_25_1_tools_offer_the_bridge_fields_and_keep_explicit_growth_only_for_the_unbridged():
    import analyst_tools as at
    desk = [t for t in at.tools_for({"desk_schema": "25.1", "long_run_defaults_withheld": True})
            if t["function"]["name"] == "run_financial_model"][0]["function"]["parameters"]["properties"]
    item = desk["scenarios"]["items"]["properties"]
    assert {"revenue_growth", "earnings_margin", "normalized_margin", "normalization_horizon", "structural_growth", "flags"} <= set(item)
    assert "growth_rates" not in item and "growth_rates" not in desk
    assert item["explicit_growth"]["description"].startswith("Only for a scenario the normalization bridge does not apply to")
    assert "bridge_C1_reason" in desk and "cycle_position" in desk
    assert at.tools_for({"long_run_defaults_withheld": True}) == at.tools_for({"long_run_defaults_withheld": True, "desk_schema": None})
    assert at.tools_for({}) == at.TOOLS


def test_the_25_1_task_says_a_late_horizon_needs_the_fade_to_end_at_it():
    assert "fade_years equal to normalization_horizon minus 5" in cap.TASK_REV25
    assert "normalization_horizon" not in cap.TASK


def test_the_tolerances_are_the_frozen_stage_0_4_values():
    """Registered 2026-10-16 (PHASE_4_AMENDMENTS, Stage 0.4 step 5). A change here is a new registration, never an edit."""
    assert bc.BRIDGE_TOLERANCES == {"tau_m_y1_5": 0.03, "tau_m_y6_10": 0.03, "tau_m_y11_plus": 0.03, "tau_R_T5": 0.10, "tau_R_TH": 0.10, "tau_b": 0.01,
                                   "tau_g": 0.02}
