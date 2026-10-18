"""Brief D2a (BRIEF_D2a_desk_port.md; PLAN_terminal_reinvestment.md sections 3, 3a, 5 O2c / O3 / O5 / O7 / O8): the D2 formula in the desk.

1. Legacy: with `d2` absent the desk is today's; s = 0, w = 0, delta = 0 supplied through `d2` in the legacy-equivalent form reproduce today's value
   to the cent and to 1e-6 relative.
2. Synthetic parity: the desk, fed the `d2` members computed from each simulated firm's statements, equals `reference_d2.py` (read in place under
   STOCKS_ROOT/stocks-workspace/scratch/rev23/terminal_d2; skipped when absent) in value and in every annual flow, to 1e-9. C and C2 are run twice,
   on the default path (the reference fails them against the truth, +7.37% and +4.53%: reported as failures, never as passes) and on their cited path.
3. The O2c states of H: missing, cited, uncited, malformed, H > F.
4. No hidden charge: supplying or removing the O8 diagnostics' inputs changes no value and no flow.
5. The identity Flow_0 = X_0 - (1 - delta)(capex_0 - D&A_org,0 + dNWC_0) - (P_0 - ROU_0) + tau A_0.
6. No sustaining charge s in the production code.
"""
import copy
import math
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import consensus_reference as cr  # noqa: E402
import financial_model_tool as fmt  # noqa: E402  (defaults STOCKS_ROOT when unset)

TOL = 1e-9


def _terminal_d2_dir():
    root = os.environ.get("STOCKS_ROOT")
    if not root:
        return None
    p = Path(root) / "stocks-workspace" / "scratch" / "rev23" / "terminal_d2"
    return p if (p / "reference_d2.py").is_file() and (p / "synthetic.py").is_file() else None


_D2DIR = _terminal_d2_dir()
needs_reference = pytest.mark.skipif(_D2DIR is None, reason="scratch/rev23/terminal_d2 (reference_d2.py, synthetic.py) not under STOCKS_ROOT")


@pytest.fixture(scope="module")
def harness():
    sys.path.insert(0, str(_D2DIR))
    import reference_d2 as ref
    import synthetic as S
    yield ref, S
    sys.path.remove(str(_D2DIR))


_SIM = {}


def _sim(S, name):
    if name not in _SIM:
        _SIM[name] = S.simulate(S.FIRMS[name])
    return _SIM[name]


# ---- the feed: the `d2` members and the call, computed from a simulated firm's statements --------------------------------------------------------

def feed(ref, S, name, state_h=0, override=True, extra=None):
    """The unbundled_dcf kwargs for a simulated (non-insurer) firm, as the pack would supply them: the true bridge path, the pooled five-year totals,
    the filed PP&E, the amortization schedule, the true capex path as a cited override (mode 1) and, with state_h > 0, as the cited state path."""
    spec = S.FIRMS[name]
    o = _sim(S, name)
    r, tax = spec["r"], spec["tax"]
    F = spec.get("F", S.F)
    dp = spec.get("debt", "none")
    delta, kd = (dp[1], dp[2]) if dp != "none" else (0.0, 0.0)
    e_end = 5 + state_h
    R = [o["R"][t] for t in range(0, e_end + 1)]
    X = [o["x"][t] for t in range(0, e_end + 1)]
    yrs = range(-4, 1)
    da_org = lambda t: o["da"][t] - o["rou_dep"][t]
    bridge = {"revenue": R[:6], "margin": [X[t] / R[t] for t in range(1, 6)], "kappa": 1.0, "wc_intensity": o["nwc"][0] / o["R"][0],
              "m0": X[0] / R[0]}
    d2 = {"delta": delta, "kd": kd, "tau": tax,
          "pooled": {"revenue": sum(o["R"][t] for t in yrs), "capex": sum(o["capex"][t] for t in yrs), "da_org": sum(da_org(t) for t in yrs),
                     "lease_principal": sum(o["lease_principal"][t] for t in yrs), "rou_dep": sum(o["rou_dep"][t] for t in yrs), "years": 5},
          "ppe": {"gross_prior": o["gross_ppe"][-1], "gross": o["gross_ppe"][0], "net": o["ppe"][0], "da_org_0": da_org(0)},
          "amortization": {"schedule": [o["amort"][t] for t in range(1, 6)], "thereafter": sum(o["amort"].get(t, 0.0) for t in range(6, S.T + 2))},
          "year0": {"capex": o["capex"][0], "da_org": da_org(0), "dnwc": o["nwc"][0] - o["nwc"][-1], "lease_principal": o["lease_principal"][0],
                    "rou_dep": o["rou_dep"][0], "amortization": o["amort"][0], "invested_capital": o["ic"][0]}}
    if override:
        d2["capex_override"] = {"mode": 1, "values": [o["capex"][t] / o["R"][t] for t in range(1, 6)], "citation": "synthetic: the firm's own plan"}
    if state_h:
        d2["state_path"] = {"H": state_h, "years": [
            {"year": t, "capex_over_revenue": o["capex"][t] / o["R"][t], "revenue": o["R"][t], "margin": X[t] / R[t], "units": "capex_over_revenue",
             "citation": "synthetic: the firm's own plan", "filed": "2025-01-01"} for t in range(6, e_end + 1)]}
        d2["valuation_date"] = "2026-01-01"
    if extra:
        d2.update(extra)
    SS = S.SS
    g_T = (o["x"][SS + 25] / o["x"][SS]) ** (1 / 25) - 1
    roc_T = sum(ref.roc(o, t, tax) for t in range(SS + 1, SS + 26)) / 25
    kw = dict(base_cf=1.0, discount_rate=r, terminal_g=g_T, fade_years=F, terminal_ronic=roc_T,
              long_run={"r_tc": ref.roc(o, 0, tax), "stub_months": 0}, long_run_margin=o["x"][SS] / o["R"][SS], shares_diluted=1.0,
              net_debt=0.0, sbc_treatment="deducted_in_cf", bridge=bridge, d2=d2)
    return kw


def feed_financial(ref, S, name):
    spec = S.FIRMS[name]
    o = S.insurer(spec)
    SS, r = S.SS, spec["r"]
    R = [o["R"][t] for t in range(0, 6)]
    X = [o["x"][t] for t in range(0, 6)]
    g_T = (o["x"][SS + 25] / o["x"][SS]) ** (1 / 25) - 1
    return dict(base_cf=1.0, discount_rate=r, terminal_g=g_T, fade_years=10, terminal_ronic=spec["roe"],
                long_run={"r_tc": spec["roe"], "stub_months": 0}, long_run_margin=o["x"][SS] / o["R"][SS], shares_diluted=1.0, net_debt=0.0,
                sbc_treatment="deducted_in_cf",
                bridge={"revenue": R, "margin": [X[t] / R[t] for t in range(1, 6)], "kappa": 1.0, "m0": X[0] / R[0]},
                d2={"family": "financial"})


def _rel(a, b):
    return abs(a - b) / max(abs(b), 1e-300)


def _flow_diff(desk_flows, ref_flows):
    assert len(desk_flows) == len(ref_flows), (len(desk_flows), len(ref_flows))
    return max(abs(a - b) for a, b in zip(desk_flows, ref_flows))


def _reference(ref, name, state_h):
    """(value, flows 1..N) of the reference on the registered path."""
    if state_h:
        v = ref.d2_value_state(name, state_h, "vintages")
        return v["value"], v["flows"]
    v = ref.d2_value(name, "true", "vintages")
    return v["value"], list(v["flows_1_5"]) + list(v["fade_flows"])


# name, state H (0 = the default path: the year-5 gap fades over F), label, registered to pass against the truth
PATHS = [("A_compounder", 0, "default", True), ("B_newbuild", 25, "levels to year 30", True), ("B2_newbuild", 0, "default", True),
         ("C_depleter", 0, "default", False), ("C_depleter", 15, "cited path to year 20", True),
         ("C2_depleter_levered", 0, "default", False), ("C2_depleter_levered", 15, "cited path to year 20", True),
         ("C3_impaired", 0, "default", True), ("D_acquirer", 0, "default", True), ("E_holiday", 9, "levels to year 14", True),
         ("G_utility", 0, "default", True), ("H_reit", 0, "default", True), ("I_lessee", 0, "default", True)]


@needs_reference
@pytest.mark.parametrize("name,h,label,registered", PATHS, ids=[f"{n}-{lab}" for n, _, lab, _ in PATHS])
def test_synthetic_parity_value_and_every_annual_flow(harness, name, h, label, registered):
    ref, S = harness
    res = fmt.unbundled_dcf(**feed(ref, S, name, state_h=h))
    assert "error" not in res, res
    rv, rflows = _reference(ref, name, h)
    assert _rel(res["per_share_iv_raw"], rv) < TOL, (name, res["per_share_iv_raw"], rv)
    assert _flow_diff(res["d2_flows"], rflows) < TOL
    assert res["d2"]["H"] == h


@needs_reference
def test_insurer_financial_route_parity(harness):
    ref, S = harness
    res = fmt.unbundled_dcf(**feed_financial(ref, S, "F_insurer"))
    assert "error" not in res, res
    rv = ref.financial_value("F_insurer")
    assert _rel(res["per_share_iv_raw"], rv["value"]) < TOL
    assert _flow_diff(res["d2_flows"][:5], rv["flows_1_5"]) < TOL
    assert res["d2"]["route"] == "financial"


@needs_reference
def test_registered_criteria_against_the_truth_and_c_c2_default_fail(harness):
    """The registered +/-3% bar on the registered paths. C and C2 on the default path FAIL it (+7.37%, +4.53%) and that is asserted, so a future
    change that quietly moved them cannot go unnoticed; their cited-path passes are never counted as default passes."""
    ref, S = harness
    out = {}
    for name, h, label, registered in PATHS:
        o_spec = S.FIRMS[name]
        truth = S.true_value(_sim(S, name), o_spec["r"])
        res = fmt.unbundled_dcf(**feed(ref, S, name, state_h=h))
        out[(name, label)] = res["per_share_iv_raw"] / truth - 1
        assert (abs(out[(name, label)]) <= 0.03) == registered, (name, label, out[(name, label)])
    assert out[("C_depleter", "default")] == pytest.approx(0.0737, abs=5e-4)
    assert out[("C2_depleter_levered", "default")] == pytest.approx(0.0453, abs=5e-4)
    assert out[("C_depleter", "cited path to year 20")] == pytest.approx(0.0230, abs=5e-4)
    assert out[("C2_depleter_levered", "cited path to year 20")] == pytest.approx(0.0159, abs=5e-4)


@needs_reference
def test_insurer_within_registered_bar(harness):
    ref, S = harness
    res = fmt.unbundled_dcf(**feed_financial(ref, S, "F_insurer"))
    truth = S.true_value(S.insurer(S.FIRMS["F_insurer"]), S.FIRMS["F_insurer"]["r"])
    assert abs(res["per_share_iv_raw"] / truth - 1) <= 0.03


# ---- 1. legacy ---------------------------------------------------------------------------------------------------------------------------------

def _legacy_bridge_call():
    R = [1.0, 1.06, 1.12, 1.18, 1.23, 1.28]
    mg = [0.20, 0.205, 0.21, 0.21, 0.21]
    return R, mg


def test_d2_absent_is_the_legacy_call_and_the_signature_default_is_none():
    import inspect
    assert inspect.signature(fmt.unbundled_dcf).parameters["d2"].default is None
    R, mg = _legacy_bridge_call()
    kw = dict(base_cf=0.17, explicit_growth=[0.05] * 5, discount_rate=0.09, terminal_g=0.03, fade_years=10, terminal_ronic=0.12,
              long_run={"r_tc": 0.15, "stub_months": 0}, long_run_margin=0.19, shares_diluted=1.0, net_debt=0.0, sbc_treatment="deducted_in_cf",
              bridge={"revenue": R, "margin": mg, "kappa": 0.8, "wc_intensity": 0.1, "m0": 0.2})
    a = fmt.unbundled_dcf(**kw)
    b = fmt.unbundled_dcf(**kw, d2=None)
    assert a == b and "d2" not in a


def test_legacy_equivalent_d2_reproduces_todays_value_to_the_cent_and_1e6():
    """s = 0 (no s exists), w = 0 and delta = 0: the capex path is set so the levels flow equals today's owner earnings less working capital
    (c_t = m_t (1 - kappa)), and kappa is set so the year-5 wedge is exactly 0; no D&A, leases or amortization."""
    R, mg = _legacy_bridge_call()
    g_t, f, ronic0, ronic_t, rate, m_long = 0.03, 10, 0.15, 0.12, 0.09, 0.19
    g5 = R[5] / R[4] - 1.0
    g6 = g5 + (g_t - g5) / f
    wc = 0.1
    kappa = 1.0 - g6 / ronic0 + wc * (R[5] - R[4]) / (R[5] * mg[4])      # I_5 = (1 - kappa) X_5 + wc_5 equals I*_5 = g_6 X_5 / RONIC_0
    common = dict(discount_rate=rate, terminal_g=g_t, fade_years=f, terminal_ronic=ronic_t, long_run={"r_tc": ronic0, "stub_months": 0},
                  long_run_margin=m_long, shares_diluted=1.0, net_debt=0.0, sbc_treatment="deducted_in_cf")
    bridge = {"revenue": R, "margin": mg, "kappa": kappa, "wc_intensity": wc, "m0": 0.2}
    oe0 = kappa * R[0] * 0.2
    growth = [kappa * R[t + 1] * mg[t] / (kappa * R[t] * (mg[t - 1] if t else 0.2)) - 1.0 for t in range(5)]
    legacy = fmt.unbundled_dcf(base_cf=oe0, explicit_growth=growth, bridge=bridge, **common)
    assert "error" not in legacy, legacy
    d2 = {"delta": 0.0, "tau": 0.0, "pooled": {"revenue": 1.0, "capex": 0.0, "da_org": 0.0, "years": 5},
          "capex_override": {"mode": 1, "values": [mg[t] * (1.0 - kappa) for t in range(5)], "citation": "legacy-equivalent test"}}
    new = fmt.unbundled_dcf(base_cf=oe0, bridge=bridge, d2=d2, **common)
    assert "error" not in new, new
    assert abs(new["d2"]["wedge_rate_5"]) < 1e-12
    assert round(new["per_share_iv_raw"], 2) == round(legacy["per_share_iv_raw"], 2)
    assert new["per_share_iv"] == legacy["per_share_iv"]
    assert _rel(new["per_share_iv_raw"], legacy["per_share_iv_raw"]) < 1e-6
    assert _flow_diff(new["d2_flows"], legacy["projected_cfs"]) < 1e-3          # the legacy list is rounded to 4 places
    assert new["d2"]["da_rule"] == "pooled" and "da_vintages_no_gross_ppe" in new["stamps"]


# ---- 3. the O2c states of H --------------------------------------------------------------------------------------------------------------------

def _state_call(harness, h=3, mutate=None, fade=None):
    ref, S = harness
    kw = feed(ref, S, "E_holiday", state_h=h)
    if mutate:
        mutate(kw["d2"])
    if fade is not None:
        kw["fade_years"] = fade
    return kw


@needs_reference
def test_state_missing_is_the_default_gap_over_fade_and_valued(harness):
    ref, S = harness
    kw = feed(ref, S, "E_holiday", state_h=0)
    res = fmt.unbundled_dcf(**kw)
    assert res["d2"]["investment_state"] == "missing" and res["d2"]["H"] == 0 and res["d2"]["wedge_applied"] is True
    assert res["long_run"]["years"] == 5 + kw["fade_years"]


@needs_reference
def test_state_cited_extends_the_levels_leg_and_drops_the_gap(harness):
    res = fmt.unbundled_dcf(**_state_call(harness, 3))
    assert res["d2"]["investment_state"] == "cited" and res["d2"]["H"] == 3 and res["d2"]["wedge_applied"] is False
    assert "investment_state_duration_uncited" not in res["stamps"]


@needs_reference
def test_state_uncited_is_used_and_stamped(harness):
    def drop(d2):
        del d2["state_path"]["years"][1]["citation"]
    cited = fmt.unbundled_dcf(**_state_call(harness, 3))
    res = fmt.unbundled_dcf(**_state_call(harness, 3, drop))
    assert res["d2"]["investment_state"] == "uncited" and "investment_state_duration_uncited" in res["stamps"]
    assert res["per_share_iv_raw"] == cited["per_share_iv_raw"] and res["d2_flows"] == cited["d2_flows"]       # annotate, never gate


@needs_reference
@pytest.mark.parametrize("why,mutate", [
    ("H not equal to the years supplied", lambda d: d["state_path"].update(H=4)),
    ("a year out of order", lambda d: d["state_path"]["years"][1].update(year=9)),
    ("wrong units", lambda d: d["state_path"]["years"][0].update(units="dollars")),
    ("a non-numeric margin", lambda d: d["state_path"]["years"][2].update(margin="high")),
    ("a non-positive revenue", lambda d: d["state_path"]["years"][2].update(revenue=0.0)),
    ("filed after the valuation date", lambda d: d["state_path"]["years"][0].update(filed="2026-06-01")),
    ("H negative", lambda d: d["state_path"].update(H=-1)),
    ("not an object", lambda d: d.update(state_path=[1, 2, 3])),
])
def test_state_malformed_is_refused_by_name_never_shortened(harness, why, mutate):
    res = fmt.unbundled_dcf(**_state_call(harness, 3, mutate))
    assert res.get("validation_error") and res["d2_refusal"] == "investment_state_path_malformed", (why, res)
    assert "per_share_iv_raw" not in res


@needs_reference
def test_state_declared_without_a_path_is_refused_by_name(harness):
    res = fmt.unbundled_dcf(**_state_call(harness, 3, lambda d: d.update(state_path={"H": 3})))
    assert res.get("validation_error") and res["d2_refusal"] == "investment_state_path_missing"


@needs_reference
def test_state_longer_than_fade_extends_the_horizon_no_truncation(harness):
    res = fmt.unbundled_dcf(**_state_call(harness, 9, fade=4))                 # H = 9 > F = 4
    assert res["long_run"]["years"] == 5 + 9 and len(res["d2_flows"]) == 14
    assert "investment_state_longer_than_fade" in res["stamps"]
    res2 = fmt.unbundled_dcf(**_state_call(harness, 3, fade=10))              # H < F: N = 5 + F
    assert res2["long_run"]["years"] == 15 and "investment_state_longer_than_fade" not in res2["stamps"]


@needs_reference
def test_override_uncited_and_modes(harness):
    ref, S = harness
    kw = feed(ref, S, "B2_newbuild")
    cited = fmt.unbundled_dcf(**kw)
    kw2 = copy.deepcopy(kw)
    del kw2["d2"]["capex_override"]["citation"]
    un = fmt.unbundled_dcf(**kw2)
    assert "capex_override_uncited" in un["stamps"] and "capex_override_uncited" not in cited["stamps"]
    assert un["per_share_iv_raw"] == cited["per_share_iv_raw"] and un["d2"]["capex_override_uncited"] is True
    kw3 = copy.deepcopy(kw)
    kw3["d2"]["capex_override"] = {"mode": 2, "year5": 0.2, "citation": "x"}
    m2 = fmt.unbundled_dcf(**kw3)
    c_base = m2["d2"]["pooled"]["capex_ratio"]
    assert m2["d2"]["capex_mode"] == 2
    kw4 = copy.deepcopy(kw)
    del kw4["d2"]["capex_override"]
    m3 = fmt.unbundled_dcf(**kw4)
    assert m3["d2"]["capex_mode"] == 3 and c_base > 0
    kw5 = copy.deepcopy(kw)
    kw5["d2"]["capex_override"] = {"mode": 1, "values": [0.1, 0.1]}
    assert fmt.unbundled_dcf(**kw5)["d2_refusal"] == "capex_override_malformed"


# ---- 4. no hidden charge -----------------------------------------------------------------------------------------------------------------------

@needs_reference
@pytest.mark.parametrize("name,h", [("C_depleter", 0), ("H_reit", 0), ("E_holiday", 9)])
def test_o8_diagnostic_inputs_change_no_value_and_no_flow(harness, name, h):
    ref, S = harness
    bare = fmt.unbundled_dcf(**feed(ref, S, name, state_h=h))
    kw = feed(ref, S, name, state_h=h, extra={"reserves": {"costs_incurred": 5.0, "reserve_additions": 2.0, "dda": 3.0, "production": 2.0},
                                              "reit": {"recurring_capex": 0.5, "da": 0.9}})
    full = fmt.unbundled_dcf(**kw)
    for k in ("per_share_iv_raw", "d2_flows", "projected_cfs", "terminal_value_pv", "dcf_pv", "enterprise_value"):
        assert bare[k] == full[k], k
    assert bare["d2"]["fd_vs_dda_gap"] == "unavailable" and bare["d2"]["reit_recurring_capex_vs_da"] == "unavailable"
    assert full["d2"]["fd_vs_dda_gap"]["gap"] == pytest.approx((5.0 / 2.0) / (3.0 / 2.0) - 1.0)
    assert full["d2"]["reit_recurring_capex_vs_da"]["ratio"] == pytest.approx(0.5 / 0.9)
    # a partly supplied input is unavailable, never "no gap"
    kw2 = feed(ref, S, name, state_h=h, extra={"reserves": {"costs_incurred": 5.0}})
    assert fmt.unbundled_dcf(**kw2)["d2"]["fd_vs_dda_gap"] == "unavailable"


@needs_reference
def test_diagnostics_never_change_the_value_or_flows_with_year0_removed(harness):
    ref, S = harness
    kw = feed(ref, S, "G_utility")
    full = fmt.unbundled_dcf(**kw)
    del kw["d2"]["year0"]
    bare = fmt.unbundled_dcf(**kw)
    assert bare["per_share_iv_raw"] == full["per_share_iv_raw"] and bare["d2_flows"] == full["d2_flows"]
    assert bare["d2"]["explicit_years_implied_return"] == "unavailable" and bare["d2"]["roic_n1_roll_forward"]["status"] == "unavailable"


# ---- 5. the identity ---------------------------------------------------------------------------------------------------------------------------

@needs_reference
@pytest.mark.parametrize("name", ["A_compounder", "B_newbuild", "B2_newbuild", "C_depleter", "C3_impaired", "D_acquirer", "E_holiday", "G_utility", "H_reit", "I_lessee"])
def test_flow_0_identity(harness, name):
    """Flow_0 = X_0 - (1 - delta)(capex_0 - D&A_org,0 + dNWC_0) - (P_0 - ROU_0) + tau A_0, to 1e-9, equals the simulated FCFE of year 0."""
    ref, S = harness
    o = _sim(S, name)
    res = fmt.unbundled_dcf(**feed(ref, S, name))
    assert abs(res["d2"]["flow_0"] - o["fcfe"][0]) < TOL, (name, res["d2"]["flow_0"], o["fcfe"][0])


def test_d2_flow_is_the_identity_term_by_term():
    f = cr.d2_flow(x=10.0, capex=4.0, da_org=3.0, dnwc=0.5, p=1.0, rou=0.7, a=0.2, delta=0.3, tau=0.25)
    assert f == pytest.approx(10.0 - 0.7 * (4.0 - 3.0 + 0.5) - (1.0 - 0.7) + 0.25 * 0.2, abs=1e-12)


# ---- 6. the rest of the specification ----------------------------------------------------------------------------------------------------------

@needs_reference
def test_e0_not_positive_is_refused_and_a_negative_flow_year_is_valued(harness):
    ref, S = harness
    kw = feed(ref, S, "B_newbuild")                       # firm B's doubling programme: a heavy-capex build-out
    bad = copy.deepcopy(kw)
    bad["bridge"]["m0"] = -0.1
    assert fmt.unbundled_dcf(**bad)["d2_refusal"] == "d2_e0_not_positive"
    nom0 = copy.deepcopy(kw)
    del nom0["bridge"]["m0"]
    assert fmt.unbundled_dcf(**nom0)["d2_refusal"] == "d2_e0_missing"
    res = fmt.unbundled_dcf(**kw)
    assert "error" not in res and min(res["d2_flows"][:5]) < 0 and res["per_share_iv_raw"] > 0     # the build-out years run negative and are valued


def test_d2_refusals_by_name():
    R, mg = _legacy_bridge_call()
    base = dict(base_cf=1.0, discount_rate=0.09, terminal_g=0.03, fade_years=10, terminal_ronic=0.12, long_run={"r_tc": 0.15, "stub_months": 0},
                long_run_margin=0.19, shares_diluted=1.0, net_debt=0.0, sbc_treatment="deducted_in_cf")
    br = {"revenue": R, "margin": mg, "kappa": 1.0, "m0": 0.2}
    d2 = {"delta": 0.0, "tau": 0.2, "pooled": {"revenue": 5.0, "capex": 0.5, "da_org": 0.4}}
    assert fmt.unbundled_dcf(**base, d2=d2)["d2_refusal"] == "d2_requires_bridge"
    assert fmt.unbundled_dcf(**base, bridge=br, d2="x")["d2_refusal"] == "d2_malformed"
    assert fmt.unbundled_dcf(**base, bridge=br, d2=dict(d2, delta=1.0))["d2_refusal"] == "d2_input_invalid"
    assert fmt.unbundled_dcf(**base, bridge=br, d2=dict(d2, delta=0.3))["d2_refusal"] == "d2_input_invalid"            # kd needed
    assert fmt.unbundled_dcf(**base, bridge=br, d2=dict(d2, pooled={"revenue": 0.0, "capex": 0.5, "da_org": 0.4}))["d2_refusal"] == "rev_5yr_nonpositive"
    assert fmt.unbundled_dcf(**base, bridge=br, d2=dict(d2, family="bank"))["d2_refusal"] == "d2_malformed"
    ok = fmt.unbundled_dcf(**base, bridge=br, d2=d2)
    assert "error" not in ok and "partial_history_n_years" not in ok["stamps"]
    part = fmt.unbundled_dcf(**base, bridge=br, d2=dict(d2, pooled=dict(d2["pooled"], years=3)))
    assert "partial_history_n_years" in part["stamps"] and part["d2"]["pooled"]["partial_history_n_years"] == 3
    assert fmt.unbundled_dcf(**base, bridge=br, finite_life_years=10, d2=d2)["validation_error"]


def test_result_carries_every_key_of_the_legacy_bridge_result():
    R, mg = _legacy_bridge_call()
    common = dict(discount_rate=0.09, terminal_g=0.03, fade_years=10, terminal_ronic=0.12, long_run={"r_tc": 0.15, "stub_months": 0},
                  long_run_margin=0.19, shares_diluted=1.0, net_debt=0.0, sbc_treatment="deducted_in_cf")
    br = {"revenue": R, "margin": mg, "kappa": 0.8, "wc_intensity": 0.1, "m0": 0.2}
    legacy = fmt.unbundled_dcf(base_cf=0.16, explicit_growth=[0.05] * 5, bridge=br, **common)
    new = fmt.unbundled_dcf(base_cf=0.16, bridge=br, d2={"delta": 0.0, "tau": 0.2, "pooled": {"revenue": 5.0, "capex": 0.5, "da_org": 0.4}}, **common)
    assert set(legacy) - set(new) == set(), set(legacy) - set(new)
    assert set(legacy["long_run"]) == set(new["long_run"]) and set(legacy["implied"]) == set(new["implied"])


def test_amortization_schedule_and_thereafter_run_off():
    assert cr.d2_amortization([4, 4, 4, 4, 4], 6.0, 9) == [4, 4, 4, 4, 4, 4, 2.0, 0.0, 0.0]
    assert cr.d2_amortization([0, 0, 0, 0, 0], 5.0, 7) == [0, 0, 0, 0, 0, 0.0, 0.0]            # a zero year-5 rate runs nothing off


def test_equity_return_conversion():
    assert cr.equity_ronic(0.12, 0.0, 0.05, 0.25) == 0.12
    assert cr.equity_ronic(0.12, 0.4, 0.05, 0.25) == pytest.approx(0.12 + 0.4 / 0.6 * (0.12 - 0.05 * 0.75))
    assert math.isinf(cr.equity_ronic(math.inf, 0.4, 0.05, 0.25))


def test_fallback_to_pooled_d2_a_stamped_and_amortization_not_filed():
    R, mg = _legacy_bridge_call()
    base = dict(base_cf=1.0, discount_rate=0.09, terminal_g=0.03, fade_years=10, terminal_ronic=0.12, long_run={"r_tc": 0.15, "stub_months": 0},
                long_run_margin=0.19, shares_diluted=1.0, net_debt=0.0, sbc_treatment="deducted_in_cf")
    br = {"revenue": R, "margin": mg, "kappa": 1.0, "m0": 0.2}
    d2 = {"delta": 0.0, "tau": 0.2, "pooled": {"revenue": 5.0, "capex": 0.5, "da_org": 0.4}, "amortization": {"a0": 0.01}}
    res = fmt.unbundled_dcf(**base, bridge=br, d2=d2)
    assert "amortization_schedule_not_filed" in res["stamps"] and "da_vintages_no_gross_ppe" in res["stamps"]


def test_no_sustaining_charge_in_the_production_code():
    """O8: s is not a parameter, a default, a name, a dict key or a term anywhere in the D2 production functions (read from their syntax trees, so
    the comments and docstrings that name the ruling do not count)."""
    import ast
    d2_funcs = {"equity_ronic", "d2_flow", "d2_amortization", "d2_da_org_path", "d2_value", "d2_value_financial",
                "_d2_state_path", "_d2_prepare", "_d2_diagnostics", "_d2_dcf", "_d2_refuse"}
    seen = set()
    for mod in (cr, fmt):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in d2_funcs]:
            seen.add(fn.name)
            for node in ast.walk(fn):
                names = []
                if isinstance(node, ast.Name):
                    names.append(node.id)
                elif isinstance(node, ast.arg):
                    names.append(node.arg)
                elif isinstance(node, ast.keyword) and node.arg:
                    names.append(node.arg)
                elif isinstance(node, ast.Attribute):
                    names.append(node.attr)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 40:
                    names.append(node.value)             # dict keys and member names; messages are longer
                for nm in names:
                    assert nm != "s" and "sustain" not in nm.lower() and not re.fullmatch(r"s_\w+", nm), (fn.name, nm)
    assert seen == d2_funcs, d2_funcs - seen


@needs_reference
def test_diagnostics_present_and_sane(harness):
    ref, S = harness
    res = fmt.unbundled_dcf(**feed(ref, S, "G_utility"))
    d = res["d2"]
    for k in ("rho_5_bridge", "wedge_rate_5", "explicit_years_implied_return", "roic_n1_roll_forward", "seam_ratio", "steady_state_capex_over_da",
              "fd_vs_dda_gap", "reit_recurring_capex_vs_da", "pooled", "da_rule"):
        assert k in d, k
    assert d["roic_n1_roll_forward"]["status"] == "computed" and d["steady_state_capex_over_da"]["status"] == "computed"
    assert d["seam_ratio"] == pytest.approx(res["d2_flows"][5] / res["d2_flows"][4])
    # a build-out with a net release: negative explicit net reinvestment is named, never n/a
    kw = feed(ref, S, "E_holiday")
    kw["d2"]["year0"]["capex"] = 0.0
    kw["d2"]["capex_override"]["values"] = [0.0] * 5
    kw["d2"]["pooled"]["capex"] = 0.0
    out = fmt.unbundled_dcf(**kw)
    assert out["d2"]["explicit_years_implied_return"] == "negative_net_reinvestment_explicit" and "negative_net_reinvestment_explicit" in out["stamps"]
