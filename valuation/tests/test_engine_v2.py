"""Engine v2 (SPEC_engine_v2.md; plan B2): the copied chains are proved against v1, the section-2 centres, the section-3 distributions, refusals and a full run."""
import math

import pytest

from valuation import engine_financial as f1, engine_financial_v2 as f2, engine_operating as o1, engine_operating_v2 as o2, near_term as nt
from valuation.common import QuantileDist, build_state, level_path_weights, terminal_growth_rate
from valuation.muse.tests import fixtures as fx

RESID = {0.01: -0.30, 0.05: -0.18, 0.10: -0.12, 0.25: -0.05, 0.50: 0.01, 0.75: 0.06, 0.90: 0.13, 0.95: 0.19, 0.99: 0.31}


def setup(family="operating", sic="3674"):
    pit = fx.make_pit(sic=sic)
    st = build_state(pit)
    st.update(fx.INDUSTRY_CONTEXT)
    ps = fx.LabeledPlaceholderPriors().for_company(family, st, pit.asof)
    return pit, st, ps, fx.disc_factory(st)


def table(n=500, i=None, resid=RESID, corr=None):
    pool = {"n": n, "q": {str(p): v for p, v in resid.items()}}
    var = lambda: {str(k): {"cells": {}, "pool": pool} for k in nt.KS}
    i = i or {"operating": {"growth": {str(k): {"median": 0.05, "n": n} for k in nt.KS}},
              "financial": {"rote": {str(k): {"median": 0.10, "n": n} for k in nt.KS}}}
    return {"version": nt.ENGINE_VERSION, "vintage": 2024, "cut_date": "2025-01-01", "i": i, "edges": {"size_usd": [5e7, 2.5e8, 1e9, 5e9, 2e10], "growth": [-0.1, 0.0, 0.05, 0.1, 0.2, 0.4]},
            "level_cuts": {"operating": [0.05, 0.1, 0.15, 0.2], "financial": [0.05, 0.08, 0.11, 0.14]},
            "residuals": {"operating": {"growth": var(), "margin": var()}, "financial": {"tbvg": var(), "rote": var()}}, "corr": corr or {}}


# ---- the copies are v1 under v1's own path ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("g1,m5,ronic", [(0.08, 0.18, 0.14), (-0.03, 0.09, 0.07), (0.25, 0.30, 0.22)])
def test_the_v2_operating_chain_reproduces_v1_exactly_when_its_years_1_to_3_are_v1s_path(g1, m5, ronic):
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    p = {"g1": g1, "g_terminal": gT, "margin_target": m5, "ronic": ronic}
    gd, mr = ps.curves["growth_decay"], ps.curves["margin_retention"]
    wm, info = level_path_weights(mr, len(gd))
    assert info["clipped"] is False
    q = dict(p, **{f"nt_lgrowth_{k}": math.log1p(gT + (g1 - gT) * gd.at(k)) for k in nt.KS}, **{f"nt_margin_{k}": st["op_margin"] + (m5 - st["op_margin"]) * wm[k - 1] for k in nt.KS})
    a = o1.operating_chain(st, p, ps.curves, disc, detail=True)
    b = o2.operating_chain_v2(st, q, ps.curves, disc, detail=True)
    for key in ("ev", "equity", "pv_explicit", "pv_terminal", "fcff1", "terminal_value"):
        assert b[key] == pytest.approx(a[key], rel=1e-12, abs=1e-9), key
    for ya, yb in zip(a["years"], b["years"]):
        assert yb["growth"] == pytest.approx(ya["growth"], abs=1e-12) and yb["margin"] == pytest.approx(ya["margin"], abs=1e-12)
    assert a["rules"] == b["rules"]


@pytest.mark.parametrize("g1,rT", [(0.06, 0.12), (0.01, 0.07), (0.15, 0.18)])
def test_the_v2_financial_chain_reproduces_v1_exactly_when_its_years_1_to_3_are_v1s_path(g1, rT):
    pit, st, ps, disc = setup("financial", "6021")
    gT = terminal_growth_rate(disc.rf)
    p = {"g1": g1, "g_terminal": gT, "rote_target": rT}
    gd, rho, phi = ps.curves["growth_decay"], ps.curves["rote_retention"], ps.curves["excess_fade"]
    R0, ind = st["rote_latest"], st["industry_rote"]["value"]
    q = dict(p, **{f"nt_ltbvg_{k}": math.log1p(gT + (g1 - gT) * gd.at(k)) for k in nt.KS},
             **{f"nt_rote_{k}": ind + ((rT + (R0 - rT) * rho.at(k)) - ind) * phi.at(k) for k in nt.KS})
    a = f1.financial_chain(st, p, ps.curves, disc, detail=True)
    b = f2.financial_chain_v2(st, q, ps.curves, disc, detail=True)
    for key in ("ev", "equity", "pv_explicit_excess", "pv_terminal_excess"):
        assert b[key] == pytest.approx(a[key], rel=1e-12, abs=1e-9), key
    for ya, yb in zip(a["years"], b["years"]):
        assert yb["rote_after_fade"] == pytest.approx(ya["rote_after_fade"], abs=1e-12) and yb["growth"] == pytest.approx(ya["growth"], abs=1e-12)


# ---- section 2: the centres --------------------------------------------------------------------------------------------------------------------------

def test_the_operating_centres_follow_section_2_with_the_studys_formulas():
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    ps.meta = {"features": {"med8": 0.12, "dev": st["op_margin"] - 0.12}}
    c, d = nt.centres("operating", st, ps, gT, table())
    gd, mr = ps.curves["growth_decay"], ps.curves["margin_retention"]
    ii1 = gT + (ps.inputs["g1"].ppf(0.5) - gT) * gd.at(1)
    assert c["growth"][1] == pytest.approx(0.05 + 0.5 * (ii1 - 0.05)) and c["growth"][2] == 0.05 and c["growth"][3] == 0.05
    wm, _ = level_path_weights(mr, len(gd))
    m5c = 0.12 + mr.at(5) * (st["op_margin"] - 0.12)
    assert all(c["margin"][k] == pytest.approx(st["op_margin"] + (m5c - st["op_margin"]) * wm[k - 1]) for k in nt.KS)
    assert d["growth"][1]["w"] == 0.5 and d["margin"][2]["w"] == 1.0 and d["margin"][2]["i"] is None


def test_the_financial_centres_blend_rote_at_075_and_keep_the_codes_tangible_book_growth():
    pit, st, ps, disc = setup("financial", "6021")
    gT = terminal_growth_rate(disc.rf)
    c, _d = nt.centres("financial", st, ps, gT, table())
    R0, ind = st["rote_latest"], st["industry_rote"]["value"]
    rho, phi = ps.curves["rote_retention"], ps.curves["excess_fade"]
    for k in nt.KS:
        ii = ind + ((R0 + (R0 - R0) * rho.at(k)) - ind) * phi.at(k)              # no rote_med8: the centre is R0
        assert c["rote"][k] == pytest.approx(0.10 + 0.75 * (ii - 0.10))
        assert c["tbvg"][k] == pytest.approx(gT + (ps.inputs["g1"].ppf(0.5) - gT) * ps.curves["growth_decay"].at(k))


def test_a_population_median_under_50_or_a_missing_residual_table_is_a_named_refusal_never_a_fill_in():
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    short = table(i={"operating": {"growth": {"1": {"median": 0.05, "n": 49}, "2": {"median": 0.05, "n": 500}, "3": {"median": 0.05, "n": 500}}}})
    with pytest.raises(nt.NearTermRefusal) as e:
        nt.centres("operating", st, ps, gT, short)
    assert "growth year 1" in str(e.value) and "n=49" in str(e.value)
    with pytest.raises(nt.NearTermRefusal):
        nt.near_term_inputs("operating", st, ps, gT, table(n=10), {})
    r = o2.run(pit, fx.LabeledPlaceholderPriors(), disc, short, n_draws=50, state=st)
    assert r["status"] == "refused" and any("population median" in x for x in r["reasons"])


# ---- section 3: the distributions -----------------------------------------------------------------------------------------------------------------

def test_the_distribution_is_the_centre_plus_the_residuals_kept_uncentred_and_a_deviation_shifts_and_is_stamped():
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    c, _ = nt.centres("operating", st, ps, gT, table())
    d, corr, info = nt.near_term_inputs("operating", st, ps, gT, table(), {}, deviations={"growth": {1: 0.02}})
    assert d["nt_lgrowth_1"].ppf(0.5) == pytest.approx(math.log1p(c["growth"][1] + 0.02) + RESID[0.5])     # log growth (AL.1); the median bias is kept
    assert d["nt_margin_2"].ppf(0.9) == pytest.approx(c["margin"][2] + RESID[0.9])
    fy = info["forecast_years"]["growth"][1]
    assert fy["forecast_p50_rule"] == pytest.approx(c["growth"][1]) and fy["median_bias_log"] == RESID[0.5] and fy["deviation"] == 0.02
    assert fy["p50"] == pytest.approx(math.expm1(math.log1p(c["growth"][1] + 0.02) + RESID[0.5]))          # reported back as a growth rate
    assert info["deviations"] == {"growth_1": 0.02} and info["cells"]["nt_lgrowth_1"] == "pool" and len(info["fallbacks"]) == 6


def test_the_companys_own_cell_is_used_when_it_has_50_and_the_pool_otherwise():
    t = table()
    t["residuals"]["operating"]["margin"]["1"]["cells"]["l2"] = {"n": 80, "q": {str(p): v * 2 for p, v in RESID.items()}}
    t["residuals"]["operating"]["margin"]["2"]["cells"]["l2"] = {"n": 30, "q": {str(p): v * 2 for p, v in RESID.items()}}
    q1, used1 = nt.residual_quantiles("operating", "margin", 1, "l2", t)
    q2, used2 = nt.residual_quantiles("operating", "margin", 2, "l2", t)
    assert used1 == "l2" and q1[0.9] == RESID[0.9] * 2 and used2 == "pool"
    assert nt.cell_key("margin", "operating", {"m": 0.12}, t) == "l2" and nt.cell_key("growth", "operating", {"rev": 2e9, "usd": True, "g3": 0.07}, t) == "s3_g3"
    assert nt.cell_key("growth", "operating", {"rev": 2e9, "usd": False, "g3": 0.07}, t) is None          # non-USD size: no cell, the pool


def test_a_copula_that_is_not_positive_definite_drops_only_the_near_term_pairs_and_says_so():
    info = {}
    bad = {("nt_lgrowth_1", "nt_lgrowth_2"): 0.99, ("nt_lgrowth_2", "nt_lgrowth_3"): 0.99, ("nt_lgrowth_1", "nt_lgrowth_3"): -0.99, ("g1", "margin_target"): 0.3}
    out = nt.checked_corr(["g1", "margin_target", "nt_lgrowth_1", "nt_lgrowth_2", "nt_lgrowth_3"], bad, info)
    assert out == {("g1", "margin_target"): 0.3} and "independence" in info["fallbacks"][0]


def test_full_runs_value_both_families_and_report_years_1_to_3():
    for family, sic, mod, var in (("operating", "3674", o2, "growth"), ("financial", "6021", f2, "rote")):
        pit, st, ps, disc = setup(family, sic)
        r = mod.run(pit, fx.LabeledPlaceholderPriors(), disc, table(corr={family: {nt.name(var, 1) + "|" + nt.name(var, 2): 0.5}}), n_draws=300, seed=3, state=st)
        assert r["status"] == "ok" and r["engine_version"] == "v2.0.3" and r["engine_interim"].startswith("interim:") and r["near_term_table_version"] == "v2.0" and r["distribution"]["equity"]["p50"] > 0
        assert set(r["forecast_years"][var]) == {1, 2, 3} and "p50" in r["forecast_year1"][var if family == "operating" else "rote"]
        assert r["near_term"]["copula"]["measured"] == [nt.name(var, 1) + "|" + nt.name(var, 2)]


# ---- Addendum AL.1: the outside review's tests ---------------------------------------------------------------------------------------------------

def test_al1_1_rote_semantics_the_centre_the_residual_target_and_the_residual_income_input_are_one_variable_with_rote_med8():
    pit, st, ps, disc = setup("financial", "6021")
    gT = terminal_growth_rate(disc.rf)
    ps.meta = {"features": {"rote_med8": 0.09}}                                   # the production case: an 8-year median exists
    R0, ind = st["rote_latest"], st["industry_rote"]["value"]
    rho, phi = ps.curves["rote_retention"], ps.curves["excess_fade"]
    ii1 = ind + ((0.09 + (R0 - 0.09) * rho.at(1)) - ind) * phi.at(1)               # pass_priors.forecasts rote_curve_1 with centre = rote_med8
    c, _ = nt.centres("financial", st, ps, gT, table())
    assert c["rote"][1] == pytest.approx(0.10 + 0.75 * (ii1 - 0.10))
    # the residual-income input of year 1 IS the drawn nt_rote_1: excess return = (nt_rote_1 - coe) x tangible book
    q = {"g_terminal": gT, "rote_target": 0.12, **{f"nt_ltbvg_{k}": math.log1p(0.04) for k in nt.KS}, **{f"nt_rote_{k}": 0.13 for k in nt.KS}}
    y1 = f2.financial_chain_v2(st, q, ps.curves, disc, detail=True)["years"][0]
    assert y1["rote_after_fade"] == 0.13 and y1["excess_return"] == pytest.approx((0.13 - disc.coe) * st["tbv"])
    # and the outcome a residual is measured against is realised ROTE: net income / average tangible book, build_state's definition
    from valuation.priors_build.obs import rote_by_period
    assert rote_by_period.__doc__.lstrip().startswith("Return on tangible equity of a year: net income over the average")


def test_al1_2_no_sampled_growth_can_reach_minus_100_percent_and_the_chain_refuses_one_that_does():
    extreme = {p: v for p, v in zip(nt.RESID_LEVELS, (-6.0, -4.0, -3.0, -1.5, 0.0, 0.3, 0.6, 0.8, 1.2))}   # log-space misses far beyond history
    for family, sic, mod in (("operating", "3674", o2), ("financial", "6021", f2)):
        pit, st, ps, disc = setup(family, sic)
        r = mod.run(pit, fx.LabeledPlaceholderPriors(), disc, table(resid=extreme), n_draws=2000, seed=5, state=st)
        assert r["status"] == "ok" and not any("100%" in k for k in r["distribution"]["invalid_reasons"])    # log space: none reached -100%
        gvar = "growth" if family == "operating" else "tbvg"
        assert all(r["forecast_years"][gvar][k]["p10"] > -1.0 for k in nt.KS)
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    bad = {"g_terminal": gT, "margin_target": 0.15, "ronic": 0.12, "nt_lgrowth_1": -50.0, "nt_lgrowth_2": 0.0, "nt_lgrowth_3": 0.0,
           **{f"nt_margin_{k}": 0.15 for k in nt.KS}}
    from valuation.common import DrawInvalid
    with pytest.raises(DrawInvalid):                                              # expm1(-50) rounds to -1.0: refused, never a negative revenue
        o2.operating_chain_v2(st, bad, ps.curves, disc)


def test_al1_3_a_table_of_another_version_vintage_cut_hash_or_with_bad_quantiles_is_a_named_refusal(tmp_path):
    import hashlib
    import json as _json
    good = table()
    nt.validate_table(good, "2025-06-30")
    for mutate, needle in ((lambda t: t.update(version="v1.9"), "engine version"), (lambda t: t.update(cut_date="2025-06-30"), "is not the cut"),
                           (lambda t: t["residuals"]["operating"]["growth"]["1"]["pool"]["q"].pop("0.99"), "incomplete"),
                           (lambda t: t["residuals"]["operating"]["margin"]["2"]["pool"]["q"].update({"0.75": -9.0}), "decrease")):
        t = _json.loads(_json.dumps(good))
        mutate(t)
        with pytest.raises(nt.NearTermRefusal) as e:
            nt.validate_table(t, "2025-06-30")
        assert needle in str(e.value)
    with pytest.raises(nt.NearTermRefusal) as e:
        nt.validate_table(good, "2024-12-31")                                     # the cut (2025-01-01) is after the valuation date
    assert "point in time" in str(e.value)
    d = tmp_path / "2024"
    d.mkdir()
    (d / "near_term.json").write_text(_json.dumps(good), encoding="utf-8")
    (d / "near_term.sha256").write_text(hashlib.sha256((d / "near_term.json").read_bytes()).hexdigest(), encoding="utf-8")
    assert nt.load_table(tmp_path, 2024, "2025-06-30")["_sha256"]
    (d / "near_term.sha256").write_text("0" * 64, encoding="utf-8")
    with pytest.raises(nt.NearTermRefusal, match="sha256"):
        nt.load_table(tmp_path, 2024)
    pit, st, ps, disc = setup()
    r = o2.run(pit, fx.LabeledPlaceholderPriors(), disc, dict(good, cut_date="2030-01-01", vintage=2029), n_draws=50, state=st)
    assert r["status"] == "refused" and any("point in time" in x for x in r["reasons"])


def test_al1_4_a_non_monotone_margin_retention_curve_keeps_the_v1_identity_with_its_clipped_weights():
    from valuation.common import Curve
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    mr = Curve([0.95, 0.70, 0.80, 0.40, 0.30, 0.25, 0.20, 0.20, 0.20, 0.20], "margin_retention", "non-monotone test")
    curves = dict(ps.curves, margin_retention=mr)
    wm, info = level_path_weights(mr, len(curves["growth_decay"]))
    assert info["clipped"] is False and wm[1] > wm[2]                              # non-monotone path: year 2 moves further than year 3
    discriminating = Curve([0.88, 0.04, 0.82, 0.96, 0.57, 0.17, 0.87, 0.97, 0.7, 0.51], "margin_retention", "old formula off v1")   # brute force, AL.1 4
    for curve in (mr, discriminating, Curve([0.5, 0.2, 0.6, 0.1, 0.3, 0.25, 0.2, 0.2, 0.2, 0.2], "margin_retention", "clipped")):
        cv = dict(ps.curves, margin_retention=curve)
        w, inf = level_path_weights(curve, 10)
        p = {"g1": 0.07, "g_terminal": gT, "margin_target": 0.2, "ronic": 0.13}
        q = dict(p, **{f"nt_lgrowth_{k}": math.log1p(gT + (0.07 - gT) * cv["growth_decay"].at(k)) for k in nt.KS},
                 **{f"nt_margin_{k}": st["op_margin"] + (0.2 - st["op_margin"]) * w[k - 1] for k in nt.KS})
        a, b = o1.operating_chain(st, p, cv, disc, detail=True), o2.operating_chain_v2(st, q, cv, disc, detail=True)
        assert b["equity"] == pytest.approx(a["equity"], rel=1e-12)
        assert all(yb["margin"] == pytest.approx(ya["margin"], abs=1e-12) for ya, yb in zip(a["years"], b["years"]))
    assert inf["clipped"] is True                                                 # the second curve exercises v1's clipping


def test_al1_5_after_a_positive_definite_fallback_the_report_lists_the_pairs_actually_used():
    pit, st, ps, disc = setup()
    bad = {"operating": {"nt_lgrowth_1|nt_lgrowth_2": 0.99, "nt_lgrowth_2|nt_lgrowth_3": 0.99, "nt_lgrowth_1|nt_lgrowth_3": -0.99, "nt_margin_1|nt_margin_2": 0.5}}
    r = o2.run(pit, fx.LabeledPlaceholderPriors(), disc, table(corr=bad), n_draws=100, seed=1, state=st)
    cop = r["near_term"]["copula"]
    assert r["status"] == "ok" and cop["measured"] == [] and set(cop["dropped_not_positive_definite"]) == set(bad["operating"])
    assert set(bad["operating"]) <= set(cop["independent"]) and any("independence" in f for f in r["near_term"]["fallbacks"])


def test_al1_4b_the_one_case_v2_cannot_reproduce_v1_reached_target_by_year_3_then_back_is_stamped():
    from valuation.common import Curve
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    curve = Curve([0.6, 0.4, 0.2, 0.5, 0.3, 0.25, 0.2, 0.2, 0.2, 0.2], "margin_retention", "past target at year 3")
    cv = dict(ps.curves, margin_retention=curve)
    w, _ = level_path_weights(curve, 10)
    assert w[2] == 1.0 and w[3] < 1.0
    q = {"g_terminal": gT, "margin_target": 0.2, "ronic": 0.13, **{f"nt_lgrowth_{k}": 0.05 for k in nt.KS}, **{f"nt_margin_{k}": 0.2 for k in nt.KS}}
    r = o2.operating_chain_v2(st, q, cv, disc, detail=True)
    assert o2.RULE_HELD_AFTER_TARGET in r["rules"] and r["years"][3]["margin"] == 0.2


# ---- Addendum AL.27: v2.0.1, no amplification after year 3 ---------------------------------------------------------------------------------------------

from valuation.common import Curve                                                    # noqa: E402

RISING = [1.0, 0.30, 0.02, 0.25, 0.45, 0.30, 0.20, 0.15, 0.10, 0.10]                  # the shape of priors_v3/2021 operating band 2 (AL.25): d_5 / d_3 = 22


def _op_point(curves, g3_log, m3=0.12):
    pit, st, ps, disc = setup()
    gT = terminal_growth_rate(disc.rf)
    q = {"g_terminal": gT, "margin_target": 0.15, "ronic": 0.12, "nt_lgrowth_1": 0.05, "nt_lgrowth_2": 0.04, "nt_lgrowth_3": g3_log,
         "nt_margin_1": 0.12, "nt_margin_2": 0.12, "nt_margin_3": m3}
    return o2.operating_chain_v2(st, q, dict(ps.curves, **curves), disc, detail=True), gT


def test_al27_a_rising_growth_decay_curve_never_amplifies_a_year_3_deviation_and_is_stamped():
    gd = Curve(RISING, "growth_decay")
    for g3 in (-0.30, -0.10, 0.25, 0.60):
        r, gT = _op_point({"growth_decay": gd}, math.log1p(g3))
        later = [y["growth"] for y in r["years"][3:]]
        assert all(abs(g - gT) <= abs(g3 - gT) + 1e-12 for g in later)                 # v2.0 gave gT + (g3 - gT) * 22.5 in year 5
        assert o2.RULE_DECAY_ENVELOPE in r["rules"]
    r, gT = _op_point({"growth_decay": gd}, math.log1p(-0.50))
    assert r["equity"] >= 0.0                                                           # v2.0: year-5 growth -0.5 x 22.5 < -100%, an invalid draw


def test_al27_a_non_increasing_curve_is_unchanged_by_the_envelope_so_v2_0_paths_and_v1_identity_stand():
    pit, st, ps, disc = setup()
    gd = ps.curves["growth_decay"]
    assert not nt.rises(gd) and nt.envelope(gd).values == gd.values
    r, _ = _op_point({}, math.log1p(0.08))
    assert o2.RULE_DECAY_ENVELOPE not in r["rules"]


def test_al27_the_financial_continuation_never_amplifies_tbv_growth_or_the_rote_deviation():
    pit, st, ps, disc = setup("financial", "6021")
    gT = terminal_growth_rate(disc.rf)
    ind = st["industry_rote"]["value"]
    curves = dict(ps.curves, growth_decay=Curve(RISING, "growth_decay"), rote_retention=Curve([1.0, 0.6, 0.05, 0.4, 0.6, 0.5, 0.4, 0.3, 0.3, 0.3], "rote_retention"),
                  excess_fade=Curve([1.0, 0.7, 0.1, 0.5, 0.6, 0.5, 0.4, 0.4, 0.4, 0.4], "excess_fade"))
    for g3, r3 in ((-0.2, ind + 0.08), (0.3, ind - 0.06)):
        q = {"g_terminal": gT, "rote_target": ind, "nt_ltbvg_1": 0.05, "nt_ltbvg_2": 0.05, "nt_ltbvg_3": math.log1p(g3), "nt_rote_1": ind, "nt_rote_2": ind, "nt_rote_3": r3}
        r = f2.financial_chain_v2(st, q, curves, disc, detail=True)
        for y in r["years"][3:]:
            assert abs(y["growth"] - gT) <= abs(g3 - gT) + 1e-12
            assert abs(y["rote_after_fade"] - ind) <= abs(r3 - ind) + 1e-12             # rote_target = I here, so the deviation from I can only shrink
        assert f2.RULE_ENVELOPE in r["rules"]


# ---- Addendum AL.28 (fork 1's outside-review additions): the attenuation invariant and years 1-3 identity -----------------------------------------------

import json as _json                                                                  # noqa: E402
from pathlib import Path as _Path                                                     # noqa: E402

CURVES_CASES = {
    "monotone": [1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1],
    "rising": RISING,
    "zero_d3": [1.0, 0.5, 0.0, 0.3, 0.4, 0.3, 0.2, 0.1, 0.1, 0.1],
    "near_zero_d3": [1.0, 0.5, 1e-9, 0.3, 0.4, 0.3, 0.2, 0.1, 0.1, 0.1],
    "dip_before_3": [1.0, 0.1, 0.4, 0.3, 0.5, 0.3, 0.2, 0.1, 0.1, 0.1],
}


def _lambdas(path, dev3, centre):
    return [((x - centre) / dev3) for x in path] if abs(dev3) > 1e-15 else [0.0 for _ in path]


@pytest.mark.parametrize("case", sorted(CURVES_CASES))
@pytest.mark.parametrize("g3", [-0.35, -0.05, 0.12, 0.70])
def test_al28_operating_attenuation_invariant_1_ge_lambda4_ge_lambda5_ge_0(case, g3):
    r, gT = _op_point({"growth_decay": Curve(CURVES_CASES[case], "growth_decay")}, math.log1p(g3))
    lam = _lambdas([y["growth"] for y in r["years"][3:]], g3 - gT, gT)
    assert all(1.0 + 1e-12 >= a >= b - 1e-12 for a, b in zip([1.0] + lam, lam)) and all(x >= -1e-12 for x in lam), (case, lam)
    if case == "monotone":                                                              # v2.0.1 == v2.0 on a non-increasing curve
        c = CURVES_CASES[case]
        assert all(y["growth"] == pytest.approx(gT + (g3 - gT) * c[min(t, len(c)) - 1] / c[2], abs=1e-15) for t, y in enumerate(r["years"][3:], start=4))
        assert o2.RULE_DECAY_ENVELOPE not in r["rules"]


@pytest.mark.parametrize("case", sorted(CURVES_CASES))
@pytest.mark.parametrize("dev", [-0.07, 0.09])
def test_al28_financial_attenuation_invariant_for_tbv_growth_and_the_rote_deviation(case, dev):
    pit, st, ps, disc = setup("financial", "6021")
    gT = terminal_growth_rate(disc.rf)
    ind = st["industry_rote"]["value"]
    c = Curve(CURVES_CASES[case], "c")
    curves = dict(ps.curves, growth_decay=c, rote_retention=c, excess_fade=c)
    g3, r3 = gT + dev, ind + dev
    q = {"g_terminal": gT, "rote_target": ind, "nt_ltbvg_1": 0.05, "nt_ltbvg_2": 0.05, "nt_ltbvg_3": math.log1p(g3), "nt_rote_1": ind, "nt_rote_2": ind, "nt_rote_3": r3}
    r = f2.financial_chain_v2(st, q, curves, disc, detail=True)
    for lam in (_lambdas([y["growth"] for y in r["years"][3:]], g3 - gT, gT), _lambdas([y["rote_after_fade"] for y in r["years"][3:]], r3 - ind, ind)):
        assert all(1.0 + 1e-12 >= a >= b - 1e-12 for a, b in zip([1.0] + lam, lam)) and all(x >= -1e-12 for x in lam), (case, lam)


def test_al28_years_1_to_3_are_identical_to_v2_0_at_the_same_seed_and_inputs():
    """The golden file was written by v2.0's own code (22f22b0, scratch worktree wt-legacy) on these fixtures: forecasts and the years-1..3 rows at the median point."""
    gold = _json.loads((_Path(__file__).parent / "data_v20_years_1_3.json").read_text(encoding="utf-8"))
    for family, sic, mod in (("operating", "3674", o2), ("financial", "6021", f2)):
        pit, st, ps, disc = setup(family, sic)
        r = mod.run(pit, fx.LabeledPlaceholderPriors(), disc, table(), n_draws=200, seed=7, state=st)
        got = _json.loads(_json.dumps({"forecast_years": r["forecast_years"], "years_1_3": r["at_median_inputs"]["years"][:3]}, sort_keys=True, default=str))
        assert got["forecast_years"] == gold[family]["forecast_years"] and got["years_1_3"] == gold[family]["years_1_3"]
        assert gold[family]["engine_version"] == "v2.0" and r["engine_version"] == "v2.0.3"


# ---- Addendum AL.30: v2.0.2, the INTERIM clip of the growth tails --------------------------------------------------------------------------------------

def test_al30_ak51_growth_draws_are_clipped_at_p95_only_and_the_lower_tail_and_levels_are_untouched():
    for family, sic, gvar, lvar in (("operating", "3674", "growth", "margin"), ("financial", "6021", "tbvg", "rote")):
        pit, st, ps, disc = setup(family, sic)
        dists, _corr, info = nt.near_term_inputs(family, st, ps, terminal_growth_rate(disc.rf), table(), {"rev": 2e9, "usd": True, "g3": 0.07, "g_latest": 0.07,
                                                                                                          "tg3": 0.05, "tg_latest": 0.05, "m": 0.15, "rote": 0.12})
        assert info["interim"] == nt.INTERIM
        for k in nt.KS:
            g, lv = dists[nt.name(gvar, k)], dists[nt.name(lvar, k)]
            assert g.ppf(0.999) == pytest.approx(g.ppf(0.95))                                                          # no draw above P95
            assert g.ppf(0.01) - g.ppf(0.05) == pytest.approx(RESID[0.01] - RESID[0.05])                               # AK.51: P1 kept (distress)
            assert g.ppf(0.05) - g.ppf(0.10) == pytest.approx(RESID[0.05] - RESID[0.10])                               # P5..P95 as measured
            assert lv.ppf(0.01) - lv.ppf(0.5) == pytest.approx(RESID[0.01] - RESID[0.50])                              # levels keep their P1 / P99


def test_ak51_item7_rote_attenuation_holds_when_the_long_run_rote_differs_from_the_industry():
    """lambda_t = d ROTE'_t / d ROTE'_3 (the response to the year-3 deviation, other inputs fixed): in [0, 1] and non-increasing, for rT != I."""
    pit, st, ps, disc = setup("financial", "6021")
    gT = terminal_growth_rate(disc.rf)
    ind = st["industry_rote"]["value"]
    for case in sorted(CURVES_CASES):
        c = Curve(CURVES_CASES[case], "c")
        curves = dict(ps.curves, growth_decay=c, rote_retention=c, excess_fade=c)
        for rT in (ind + 0.05, ind - 0.04):
            def path(r3):
                q = {"g_terminal": gT, "rote_target": rT, "nt_ltbvg_1": 0.05, "nt_ltbvg_2": 0.05, "nt_ltbvg_3": 0.05, "nt_rote_1": ind, "nt_rote_2": ind, "nt_rote_3": r3}
                return [y["rote_after_fade"] for y in f2.financial_chain_v2(st, q, curves, disc, detail=True)["years"][3:]]
            a, b = path(ind + 0.02), path(ind + 0.10)
            lam = [(y1 - y0) / 0.08 for y0, y1 in zip(a, b)]
            assert all(1.0 + 1e-9 >= x >= y - 1e-9 for x, y in zip([1.0] + lam, lam)) and all(x >= -1e-9 for x in lam), (case, rT, lam)
