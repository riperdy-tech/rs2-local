"""Revision 26 (BRIEF_R26_C_forecast_desk.md): tools/r26_forecast.py - validation, the path, the bridge, valuing through the desk, the alternative paths,
the K = 3 aggregation and the pull ratio. Pure functions; no model, no network."""
import copy
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import financial_model_tool as fmt  # noqa: E402
import r26_forecast as r26  # noqa: E402
from test_rev25_bridge import BASE_CF, _call, _ctx  # noqa: E402

APPROX = dict(rel=1e-12, abs=1e-12)
BAR = {"min": 0.05, "p25": 0.08, "median": 0.12, "p75": 0.15, "max": 0.20, "last": 0.14}


def sc(**over):
    d = {"near_term": {"rev_growth": [0.10, 0.05], "op_margin": [0.10, 0.10], "fact_ids": ["F1"]},
         "normalized": {"year": 5, "rev_growth": 0.03, "baseline": "median", "delta_pts": 4.0, "fact_ids": ["F1"], "reason": "backlog converts"},
         "transition": "linear", "long_run_margin_op": 0.15, "terminal_g": 0.03, "terminal_ronic": 0.15, "fade_years": 4, "prob": 0.5,
         "long_run_fact_ids": ["F1"]}
    d.update(over)
    return d


def forecast(**over):
    f = {"discount_rate": 0.10, "frame": "equity",
         "scenarios": {"Base": sc(), "Bull": sc(prob=0.25, long_run_margin_op=0.16), "Bear": sc(prob=0.25, long_run_margin_op=0.14)}}
    f.update(over)
    return f


DOSSIER = {"facts": [{"fact_id": "F1", "duration_years": 4.7, "usable": True}, {"fact_id": "F2", "duration_years": "ongoing", "usable": True},
                     {"fact_id": "F3", "duration_years": None, "usable": False}]}


def problems(obj, dossier=DOSSIER):
    return {(p["field"], p["problem"]) for p in r26.validate_forecast(obj, dossier)}


# ---- validation ---------------------------------------------------------------------------------------------------------------------------------

def test_a_well_formed_forecast_has_no_problems_and_numbers_are_not_bounded():
    assert r26.validate_forecast(forecast(), DOSSIER) == []
    wild = forecast()
    wild["scenarios"]["Base"]["near_term"]["op_margin"] = [4.0, -3.0]                 # 400% and a loss: structure is fine
    wild["scenarios"]["Base"]["normalized"]["delta_pts"] = 0.0                        # 0.0 is a number
    wild["scenarios"]["Base"]["prob"] = 0.0
    wild["scenarios"]["Bull"]["prob"] = 0.75                                          # 0.0 is a probability; the three still add to one
    assert r26.validate_forecast(wild, DOSSIER) == []


@pytest.mark.parametrize("mut,expect", [
    (lambda s: s["near_term"].__setitem__("rev_growth", [0.1]), "not_a_list_of_2_numbers"),
    (lambda s: s["near_term"].__setitem__("op_margin", [0.1, float("nan")]), "not_finite_numbers"),
    (lambda s: s["near_term"].__setitem__("op_margin", [0.1, True]), "not_finite_numbers"),
    (lambda s: s["normalized"].__setitem__("delta_pts", float("inf")), "not_a_finite_number"),
    (lambda s: s["normalized"].__setitem__("baseline", "mean"), "not_one_of_min|p25|median|p75|max|last"),
    (lambda s: s.__setitem__("transition", "ramp"), "not_one_of_linear|step_at_year|hold_then_linear"),
    (lambda s: s.__setitem__("prob", None), "not_a_finite_number"),
    (lambda s: s.__setitem__("terminal_ronic", "0.15"), "not_a_finite_number"),
    (lambda s: s["normalized"].__setitem__("year", 2), "normalized_year_out_of_range"),
    (lambda s: s["normalized"].__setitem__("year", 6), "normalized_year_out_of_range"),
    (lambda s: s["normalized"].__setitem__("year", 4.5), "not_a_whole_number"),
    (lambda s: s["normalized"].__setitem__("reason", "word " * 61), "more_than_60_words"),
    (lambda s: s["normalized"].__setitem__("fact_ids", ["F9"]), "fact_id_not_in_dossier"),
    (lambda s: s["near_term"].__setitem__("fact_ids", "F1"), "not_a_list_of_fact_ids"),
    (lambda s: s.__setitem__("long_run_fact_ids", ["F7"]), "fact_id_not_in_dossier"),
    (lambda s: s["normalized"].__setitem__("fact_ids", ["F3"]), "fact_id_not_usable"),
    (lambda s: s["near_term"].__setitem__("fact_ids", []), "fact_ids_empty"),
    (lambda s: s.__setitem__("fade_years", -1), "not_a_whole_number_of_years"),
])
def test_each_structure_failure_is_named(mut, expect):
    f = forecast()
    mut(f["scenarios"]["Base"])
    assert any(prob == expect and field.startswith("Base.") for field, prob in problems(f)), problems(f)


def test_step_and_hold_need_a_transition_year_inside_three_to_n():
    for tr in ("step_at_year", "hold_then_linear"):
        f = forecast()
        f["scenarios"]["Base"]["transition"] = tr
        assert ("Base.transition_year", "required_whole_number_for_" + tr) in problems(f)
        f["scenarios"]["Base"]["transition_year"] = 2
        assert ("Base.transition_year", "year_outside_3_to_normalized_year") in problems(f)
        f["scenarios"]["Base"]["transition_year"] = 6
        assert ("Base.transition_year", "year_outside_3_to_normalized_year") in problems(f)
        f["scenarios"]["Base"]["transition_year"] = 4
        assert r26.validate_forecast(f, DOSSIER) == []


def test_top_level_fields_and_missing_scenarios_are_named():
    f = forecast(frame="firm", discount_rate=float("nan"))
    del f["scenarios"]["Bear"]
    p = problems(f)
    assert ("frame", "not_one_of_equity") in p and ("discount_rate", "not_a_finite_number") in p and ("Bear", "missing_or_not_an_object") in p
    assert r26.validate_forecast("x") == [{"field": "forecast", "problem": "not_an_object"}]
    assert r26.validate_forecast(forecast()) == []                                     # no dossier supplied: fact IDs are not checked


# ---- the path: every transition, exact numbers ---------------------------------------------------------------------------------------------

def test_normalized_margin_is_the_bars_value_plus_delta_points_and_zero_delta_is_the_baseline():
    n = sc()["normalized"]
    assert r26.normalized_margin(n, BAR)["value"] == pytest.approx(0.16, **APPROX)           # median 0.12 + 4.0 pts
    n0 = dict(n, delta_pts=0.0, baseline="last")
    assert r26.normalized_margin(n0, BAR)["value"] == 0.14 and r26.normalized_margin(n0, BAR)["delta"] == 0.0
    assert r26.normalized_margin(dict(n, baseline="p75", delta_pts=-2.5), BAR)["value"] == pytest.approx(0.125, **APPROX)
    assert r26.normalized_margin(n, {"median": None})["status"] == "baseline_not_in_bar"


def _margins(transition, k=None, N=5, n_years=5):
    s = sc(transition=transition)
    s["normalized"] = dict(s["normalized"], year=N)
    if k:
        s["transition_year"] = k
    p = r26.build_path(s, BAR, 100.0, years=n_years)
    return [y["op_margin"] for y in p["years"]], [y["rev_growth"] for y in p["years"]], p


def test_linear():
    m, g, p = _margins("linear")
    assert m == pytest.approx([0.10, 0.10, 0.12, 0.14, 0.16], **APPROX)
    assert g == pytest.approx([0.10, 0.05, 0.05 - 0.02 / 3, 0.05 - 0.04 / 3, 0.03], **APPROX)
    assert p["status"] == "ok" and p["stamps"] == []


def test_step_at_year():
    m, g, _ = _margins("step_at_year", k=4)
    assert m == pytest.approx([0.10, 0.10, 0.10, 0.16, 0.16], **APPROX)
    assert g == pytest.approx([0.10, 0.05, 0.05, 0.03, 0.03], **APPROX)                    # growth steps with the margin


def test_hold_then_linear():
    m, g, _ = _margins("hold_then_linear", k=3)
    assert m == pytest.approx([0.10, 0.10, 0.10, 0.13, 0.16], **APPROX)
    assert g == pytest.approx([0.10, 0.05, 0.05, 0.04, 0.03], **APPROX)


def test_years_after_n_hold_normalized_and_a_later_n_ends_the_path_mid_transition():
    m, _, p = _margins("linear", N=3, n_years=5)
    assert m == pytest.approx([0.10, 0.10, 0.16, 0.16, 0.16], **APPROX)
    m, _, p = _margins("linear", N=7, n_years=5)
    assert m == pytest.approx([0.10, 0.10, 0.10 + 0.06 / 5, 0.10 + 0.12 / 5, 0.10 + 0.18 / 5], **APPROX) and p["stamps"] == ["normalized_year_beyond_path"]


def test_revenue_compounds_from_rev0_and_a_zero_margin_is_kept():
    s = sc()
    s["near_term"]["op_margin"] = [0.0, 0.0]
    p = r26.build_path(s, BAR, 100.0)
    assert p["years"][0]["op_margin"] == 0.0 and p["years"][1]["op_margin"] == 0.0
    assert p["years"][0]["revenue"] == pytest.approx(110.0, **APPROX) and p["years"][1]["revenue"] == pytest.approx(115.5, **APPROX)
    assert p["years"][2]["revenue"] == pytest.approx(115.5 * (1 + 0.05 - 0.02 / 3), **APPROX)


# ---- the bridge: a hand-computed MSGE-like case -----------------------------------------------------------------------------------------------

def flat_path(op, rev=100.0, n=5):
    return {"years": [{"year": t, "op_margin": op, "revenue": rev} for t in range(1, n + 1)]}


FACTS = {"family": "operating", "operating_income_0": 10.0, "x_0": 6.0, "tax_rate": 0.25}          # K_0 = 10 - 6 / 0.75 = 2.0 (revenue 100 at the base year)


def test_bridge_is_exact_at_the_base_year_by_construction():
    # the identity: X_0 = (OI_0 - K_0)(1 - tau), to 1e-12, with the base-year revenue and the filed margin OI_0 / R_0
    for oi0, x0, tau, r0 in ((10.0, 6.0, 0.25, 100.0), (0.45, 0.0623, 0.35, 1.06), (-3.0, 1.2, 0.0, 7.0), (50.0, 12.5, 0.18, 47.8), (2.0, -1.0, 0.3, 5.0)):
        f = {"family": "operating", "operating_income_0": oi0, "x_0": x0, "tax_rate": tau}
        b = r26.bridge_to_x({"years": [{"year": 0, "op_margin": oi0 / r0, "revenue": r0}]}, f)
        assert b["status"] == "ok" and b["rows"][0]["x_margin"] * r0 == pytest.approx(x0, rel=0, abs=1e-12)
        assert r26.invert_bridge(x0 / r0, 0, f, revenue=r0)["op_margin"] == pytest.approx(oi0 / r0, rel=0, abs=1e-12)


def test_bridge_hand_computed_and_stamped_calibrated():
    # K_0 = 10 - 6 / 0.75 = 2: at R = 100, op = 0.10 -> X = (0.10 - 0.02) x 0.75 = 0.06 = X_0 / R_0
    b = r26.bridge_to_x(flat_path(0.10), FACTS)
    assert b["status"] == "ok" and [r["x_margin"] for r in b["rows"]] == pytest.approx([0.06] * 5, **APPROX)
    r = b["rows"][0]
    assert (r["k_0"], r["k_0_pct"], r["tax_rate"]) == (2.0, 0.02, 0.25)
    assert b["stamps"] == ["bridge_calibrated_to_base_year"]
    assert any(a.startswith("bridge_calibrated_to_base_year") for a in b["assumptions"]) and "tax_rate_measured" in b["assumptions"]
    assert any("amortization" in a and "held" in a for a in b["assumptions"])                       # the held amortization is listed as an assumption


def test_bridge_holds_k_0_in_dollars_so_it_shrinks_as_a_share_of_growing_revenue():
    p = {"years": [{"year": 1, "op_margin": 0.10, "revenue": 100.0}, {"year": 2, "op_margin": 0.10, "revenue": 200.0}]}
    b = r26.bridge_to_x(p, FACTS)
    assert b["rows"][1]["x_margin"] == pytest.approx((0.10 - 0.01) * 0.75, **APPROX)


def test_tax_operating_income_and_x_0_unavailable_are_stated_and_nothing_is_valued_or_defaulted():
    for tau in (None, "n/a", float("nan"), 1.0):
        b = r26.bridge_to_x(flat_path(0.10), dict(FACTS, tax_rate=tau))
        assert b["status"] == "bridge_unavailable_tax" and b["rows"] == [] and "bridge_unavailable_tax" in b["stamps"]
    nf = {k: v for k, v in FACTS.items() if k != "tax_rate"}
    assert r26.bridge_to_x(flat_path(0.10), nf)["status"] == "bridge_unavailable_tax"
    assert r26.bridge_to_x(flat_path(0.10), dict(FACTS, operating_income_0=None))["status"] == "bridge_unavailable_operating_income"
    assert r26.bridge_to_x(flat_path(0.10), dict(FACTS, x_0=None))["status"] == "bridge_unavailable_x_0"
    assert r26.invert_bridge(0.06, 1, dict(FACTS, x_0=None), revenue=100.0)["status"] == "bridge_unavailable_x_0"


def test_zero_tax_zero_operating_income_and_zero_x_0_are_values():
    b = r26.bridge_to_x(flat_path(0.10), {"family": "operating", "operating_income_0": 0.0, "x_0": 0.0, "tax_rate": 0.0})
    assert b["status"] == "ok" and b["rows"][0]["x_margin"] == 0.10 and b["rows"][0]["k_0"] == 0.0


def test_the_financial_family_is_an_identity():
    f = {"family": "financial"}                                              # no tax, no interest: none is needed
    b = r26.bridge_to_x(flat_path(0.1234), f)
    assert b["status"] == "ok" and [r["x_margin"] for r in b["rows"]] == [0.1234] * 5 and b["assumptions"][0].startswith("financial_family_identity")
    assert r26.invert_bridge(0.1234, 3, f)["op_margin"] == 0.1234
    assert r26.bridge_margin(0.07, 5, 100.0, f)["x_margin"] == 0.07


@pytest.mark.parametrize("facts", [FACTS, dict(FACTS, operating_income_0=-1.5, x_0=2.0),
                                   dict(FACTS, tax_rate=0.0, x_0=13.0)])
def test_invert_bridge_round_trips_bridge_to_x(facts):
    p = {"years": [{"year": t, "op_margin": m, "revenue": r} for t, m, r in
                   ((1, 0.10, 100.0), (2, -0.02, 120.0), (3, 0.0, 90.0), (4, 0.31, 150.0), (5, 0.18, 210.0))]}
    b = r26.bridge_to_x(p, facts)
    for row, y in zip(b["rows"], p["years"]):
        inv = r26.invert_bridge(row["x_margin"], y["year"], facts, revenue=y["revenue"])
        assert inv["status"] == "ok" and inv["op_margin"] == pytest.approx(y["op_margin"], abs=1e-12)
    assert r26.invert_bridge(0.06, 1, FACTS, revenue=100.0)["op_margin"] == pytest.approx(0.10, **APPROX)
    assert r26.invert_bridge(0.06, 1, dict(FACTS, revenue_by_year={1: 100.0}))["op_margin"] == pytest.approx(0.10, **APPROX)
    assert r26.invert_bridge(0.06, 1, FACTS)["status"] == "bridge_unavailable_revenue"
    assert r26.invert_bridge(0.06, 1, dict(FACTS, tax_rate=None), revenue=100.0)["status"] == "bridge_unavailable_tax"


# ---- valuing through the existing desk ------------------------------------------------------------------------------------------------------------

DFACTS = {"family": "operating", "operating_income_0": 10.0, "x_0": 6.75, "tax_rate": 0.25}          # K_0 = 10 - 6.75 / 0.75 = 1.0
DBAR = {"min": 0.30, "p25": 0.34, "median": 0.38, "p75": 0.40, "max": 0.44, "last": 0.40}


def desk_forecast():
    def one(prob, lr, m):
        return sc(prob=prob, long_run_margin_op=lr, near_term={"rev_growth": [0.10, 0.08], "op_margin": [m, m], "fact_ids": ["F1"]},
                  normalized={"year": 5, "rev_growth": 0.04, "baseline": "last", "delta_pts": 0.0, "fact_ids": ["F1"], "reason": "r"},
                  fade_years=4)
    return {"discount_rate": 0.10, "frame": "equity", "scenarios": {"Base": one(0.5, 0.40, 0.40), "Bull": one(0.25, 0.42, 0.42), "Bear": one(0.25, 0.37, 0.37)}}


def desk_inputs():
    params = {k: v for k, v in _call().items() if k != "scenarios"}
    return dict(base_cf=BASE_CF, desk_params=params, desk_context=_ctx(desk_schema=None))


def test_value_forecast_feeds_the_x_path_and_revenue_to_the_existing_desk():
    f = desk_forecast()
    res = r26.value_forecast(f, DBAR, 100.0, DFACTS, **desk_inputs())
    assert res["status"] == "ok" and res["stamps"] == [] and set(res["values"]) == {"Base", "Bull", "Bear"}
    # an independent recompute of the Base's lists, fed to the desk directly
    s = f["scenarios"]["Base"]
    g = [0.10, 0.08] + [0.08 + (0.04 - 0.08) * (t - 2) / 3 for t in (3, 4, 5)]
    R = [100.0]
    for gi in g:
        R.append(R[-1] * (1 + gi))
    x = lambda op, r: (op - 1.0 / r) * 0.75
    margins = [x(0.40, R[t]) for t in range(1, 6)]
    entries = [dict(name=n, prob=f["scenarios"][n]["prob"], base_cf=BASE_CF, revenue_growth=g if n == "Base" else res["scenarios"][n]["desk_entry"]["revenue_growth"],
                    earnings_margin=margins if n == "Base" else res["scenarios"][n]["desk_entry"]["earnings_margin"], wacc=0.10, terminal_g=0.03,
                    fade_years=4, long_run_margin=(x(f["scenarios"][n]["long_run_margin_op"], R[5]) if n == "Base" else res["scenarios"][n]["desk_entry"]["long_run_margin"]),
                    terminal_ronic=0.15) for n in ("Base", "Bull", "Bear")]
    e = res["scenarios"]["Base"]["desk_entry"]
    assert e["earnings_margin"] == pytest.approx(margins, **APPROX) and e["revenue_growth"] == pytest.approx(g, **APPROX)
    assert e["long_run_margin"] == pytest.approx(x(0.40, R[5]), **APPROX)               # bridged at the final year's revenue
    params = dict(desk_inputs()["desk_params"], scenarios=entries)
    direct = fmt.execute_financial_model(params, dict(desk_inputs()["desk_context"], desk_schema="25.2"))
    assert res["base_value"] == direct["scenario_dcfs"][0]["dcf"]["per_share_iv_raw"] == res["values"]["Base"]
    assert res["desk"]["scenario_dcfs"][0]["dcf"]["bridge"]["applied"] is True


def test_value_forecast_does_not_value_a_sample_whose_bridge_is_unavailable():
    res = r26.value_forecast(desk_forecast(), DBAR, 100.0, dict(DFACTS, tax_rate=None), **desk_inputs())
    assert res["status"] == "bridge_unavailable_tax" and res["values"] is None and res["desk"] is None
    f = desk_forecast()
    f["scenarios"]["Base"]["normalized"]["baseline"] = "p10"
    assert r26.value_forecast(f, DBAR, 100.0, DFACTS, **desk_inputs())["status"] == "baseline_not_in_bar"


def test_value_forecast_leaves_the_desks_existing_results_alone():
    inputs = desk_inputs()
    before = fmt.execute_financial_model(copy.deepcopy(_call()), _ctx())
    r26.value_forecast(desk_forecast(), DBAR, 100.0, DFACTS, **inputs)
    assert fmt.execute_financial_model(copy.deepcopy(_call()), _ctx()) == before
    assert "desk_schema" not in inputs["desk_context"] or inputs["desk_context"]["desk_schema"] is None       # the caller's context is not mutated


# ---- the alternative paths --------------------------------------------------------------------------------------------------------------------------

def test_alt_op_margins_with_a_4_7_year_fact_hand_computed():
    path = [0.10, 0.10, 0.12, 0.14, 0.16]
    alt = r26.alt_op_margins(path, 4.7, 4, 0.08)
    s = 0.14 + 0.7 * 0.02                                                      # the path's level at year 4.7 = 0.154
    assert alt[:4] == path[:4] and alt[4] == pytest.approx(s + (0.08 - s) * 0.3 / 4, **APPROX) == pytest.approx(0.14845, abs=1e-12)
    assert r26.alt_op_margins(path, 4.7, 0, 0.08)[4] == 0.08                   # no fade: a step at the expiry
    six = r26.alt_op_margins(path + [0.16], 4.7, 4, 0.08, years=6)
    assert six[5] == pytest.approx(s + (0.08 - s) * 1.3 / 4, **APPROX)
    assert r26.alt_op_margins(path, 0.0, 2, 0.08)[:2] == pytest.approx([0.10 + (0.08 - 0.10) * 0.5, 0.08], **APPROX)   # expires at once: fades from year 1's level


def test_alt_paths_value_the_expiry_and_never_substitute():
    f = desk_forecast()
    f["scenarios"]["Base"]["normalized"]["baseline"] = "median"                # 0.38, below the path's 0.40 level
    f["scenarios"]["Base"]["normalized"]["delta_pts"] = 2.0                    # normalized 0.40
    inputs = desk_inputs()
    base = r26.value_forecast(f, DBAR, 100.0, DFACTS, **inputs)
    alts = r26.alt_paths(f, DOSSIER, DBAR, 100.0, DFACTS, **inputs)
    assert len(alts) == 1 and alts[0]["fact_id"] == "F1" and alts[0]["duration_years"] == 4.7 and alts[0]["label"] == "alt_path_after_evidence_expiry"
    a = alts[0]
    assert a["status"] == "ok" and a["long_run_margin_op"] == 0.38
    assert a["op_margins"][:4] == pytest.approx([0.40] * 4, **APPROX) and a["op_margins"][4] == pytest.approx(0.40 + (0.38 - 0.40) * 0.3 / 4, **APPROX)
    assert len(a["x_margins"]) == 5 and a["value"] < base["base_value"]          # the evidence expiring lowers the value
    assert r26.value_forecast(f, DBAR, 100.0, DFACTS, **inputs)["base_value"] == base["base_value"]      # the forecast's own value is untouched
    assert "stamps" in a and "evidence_outlasts_explicit_years" not in a["stamps"]


def test_alt_paths_skip_ongoing_null_unknown_and_negative_durations_and_cover_long_run_facts():
    f = desk_forecast()
    f["scenarios"]["Base"]["normalized"]["fact_ids"] = ["F2", "F3", "F1"]
    f["scenarios"]["Base"]["long_run_fact_ids"] = ["F4", "F1", "F9"]
    d = {"facts": DOSSIER["facts"] + [{"fact_id": "F4", "duration_years": 7.5}, {"fact_id": "F5", "duration_years": -1}]}
    alts = r26.alt_paths(f, d, DBAR, 100.0, DFACTS, **desk_inputs())
    assert [a["fact_id"] for a in alts] == ["F1", "F4"]                          # F2 ongoing, F3 null, F9 unknown; F1 once
    assert alts[1]["duration_years"] == 7.5 and "evidence_outlasts_explicit_years" in alts[1]["stamps"] and alts[1]["status"] == "ok"
    f["scenarios"]["Base"]["long_run_fact_ids"] = ["F5"]
    assert [a["fact_id"] for a in r26.alt_paths(f, d, DBAR, 100.0, DFACTS, **desk_inputs())] == ["F1"]


def test_an_alternative_path_that_cannot_be_bridged_says_so():
    alts = r26.alt_paths(desk_forecast(), DOSSIER, DBAR, 100.0, dict(DFACTS, tax_rate=None), **desk_inputs())
    assert alts[0]["status"] == "bridge_unavailable_tax" and alts[0]["value"] is None


# ---- aggregation and the direction split ------------------------------------------------------------------------------------------------------------

def test_aggregate_picks_the_median_sample_and_the_spread():
    a = r26.aggregate([100.0, 80.0, 120.0])
    assert (a["median_index"], a["median"], a["min"], a["max"], a["n"], a["dropped"]) == (0, 100.0, 80.0, 120.0, 3, [])
    assert a["spread"] == pytest.approx(0.4, **APPROX)
    b = r26.aggregate([{"base_value": 50.0}, {"base_value": 70.0}, {"base_value": 60.0}])
    assert b["median_index"] == 2 and b["median"] == 60.0 and b["spread"] == pytest.approx(20 / 60, **APPROX)
    assert r26.aggregate([5.0, 5.0, 5.0])["spread"] == 0.0 and r26.aggregate([5.0, 5.0, 5.0])["median_index"] == 1     # 0.0 spread is a value; equal values are ordered by index, so the middle one is index 1


def test_aggregate_with_dropped_samples_and_odd_cases():
    a = r26.aggregate([None, 90.0, 110.0])
    assert a["dropped"] == [0] and a["n"] == 2 and a["median_index"] == 1 and a["median"] == 90.0          # lower of the two middle values
    assert r26.aggregate([None, None, None])["median_index"] is None and r26.aggregate([])["spread"] is None
    z = r26.aggregate([-5.0, 0.0, 5.0])
    assert z["median"] == 0.0 and z["spread"] is None and "spread_median_not_positive" in z["stamps"]
    assert r26.aggregate([float("nan"), 10.0, 12.0])["dropped"] == [0]


def test_direction_split_uses_the_verdict_bands_rule():
    band = (100.0, 0.10)
    assert r26.sample_directions([120.0, 80.0, 105.0, 111.0, 89.0, None], 100.0, 0.10) == ["undervalued", "overvalued", "hold", "undervalued", "overvalued", None]
    assert r26.direction_split([120.0, 80.0, 100.0], band) is True                      # one says undervalued, another overvalued
    assert r26.direction_split([120.0, 115.0, 100.0], band) is False                    # undervalued + hold
    assert r26.direction_split([80.0, 85.0, 70.0], band) is False                       # unanimous
    assert r26.direction_split([108.0, 92.0, 100.0], band) is False                     # inside the band on both sides: hold
    assert r26.direction_split([110.0, 90.0], band) is True                              # exactly at the margin of safety counts, as in the verdict
    assert r26.direction_split([{"base_value": 130.0}, {"base_value": 70.0}, None], {"price": 100.0, "min_mos": 0.10}) is True
    assert r26.direction_split([130.0, None, None], band) is False
    assert r26.direction_split([130.0, 70.0], (100.0, 0.5)) is False                    # a wider band holds both


def test_direction_split_default_margin_is_the_verdicts_own_constant():
    import depth_gates
    assert r26.sample_directions([100.0 * (1 + depth_gates.MIN_MOS_FOR_DIRECTION)], 100.0) == ["undervalued"]
    assert r26.direction_split([120.0, 80.0], (100.0,)) is True


# ---- the pull ratio -------------------------------------------------------------------------------------------------------------------------------------

def test_pull_ratio_edge_cases():
    assert r26.pull_ratio(0.10, 0.12, 0.14) == pytest.approx(0.5, **APPROX)
    assert r26.pull_ratio(0.10, 0.14, 0.14) == pytest.approx(1.0, **APPROX)
    assert r26.pull_ratio(0.10, 0.18, 0.14) == pytest.approx(2.0, **APPROX)              # past the consensus
    assert r26.pull_ratio(0.10, 0.08, 0.14) == pytest.approx(0.5, **APPROX)              # away from it: the formula is absolute
    assert r26.pull_ratio(0.10, 0.10, 0.14) == 0.0                                        # not moved: 0.0 is a value
    assert r26.pull_ratio(0.0, 0.01, 0.02) == pytest.approx(0.5, **APPROX)               # a pre-reveal margin of 0.0 is a margin
    assert r26.pull_ratio(0.10, 0.12, 0.0) == pytest.approx(0.2, **APPROX)                  # a consensus margin of 0.0 is a margin
    assert r26.pull_ratio(0.10, 0.12, None) is None                                       # consensus unavailable
    assert r26.pull_ratio(0.10, 0.12, 0.10) is None                                       # consensus equals m_pre
    assert r26.pull_ratio(0.10, None, 0.14) is None and r26.pull_ratio(None, 0.12, 0.14) is None
    assert r26.pull_ratio(0.10, 0.12, float("nan")) is None
    assert r26.pull_ratio(0.0, 0.0, 0.0) is None
