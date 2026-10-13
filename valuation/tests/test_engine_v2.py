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
    return {"vintage": 2024, "i": i, "edges": {"size_usd": [5e7, 2.5e8, 1e9, 5e9, 2e10], "growth": [-0.1, 0.0, 0.05, 0.1, 0.2, 0.4]},
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
    q = dict(p, **{f"nt_growth_{k}": gT + (g1 - gT) * gd.at(k) for k in nt.KS}, **{f"nt_margin_{k}": st["op_margin"] + (m5 - st["op_margin"]) * wm[k - 1] for k in nt.KS})
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
    q = dict(p, **{f"nt_tbvg_{k}": gT + (g1 - gT) * gd.at(k) for k in nt.KS},
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
    assert d["nt_growth_1"].ppf(0.5) == pytest.approx(c["growth"][1] + 0.02 + RESID[0.5])     # the median bias is kept
    assert d["nt_margin_2"].ppf(0.9) == pytest.approx(c["margin"][2] + RESID[0.9])
    fy = info["forecast_years"]["growth"][1]
    assert fy["forecast_p50_rule"] == pytest.approx(c["growth"][1]) and fy["median_bias"] == RESID[0.5] and fy["deviation"] == 0.02
    assert info["deviations"] == {"growth_1": 0.02} and info["cells"]["nt_growth_1"] == "pool" and len(info["fallbacks"]) == 6


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
    bad = {("nt_growth_1", "nt_growth_2"): 0.99, ("nt_growth_2", "nt_growth_3"): 0.99, ("nt_growth_1", "nt_growth_3"): -0.99, ("g1", "margin_target"): 0.3}
    out = nt.checked_corr(["g1", "margin_target", "nt_growth_1", "nt_growth_2", "nt_growth_3"], bad, info)
    assert out == {("g1", "margin_target"): 0.3} and "independence" in info["fallbacks"][0]


def test_full_runs_value_both_families_and_report_years_1_to_3():
    for family, sic, mod, var in (("operating", "3674", o2, "growth"), ("financial", "6021", f2, "rote")):
        pit, st, ps, disc = setup(family, sic)
        r = mod.run(pit, fx.LabeledPlaceholderPriors(), disc, table(corr={family: {"nt_" + var + "_1|nt_" + var + "_2": 0.5}}), n_draws=300, seed=3, state=st)
        assert r["status"] == "ok" and r["engine_version"] == "v2.0" and r["distribution"]["equity"]["p50"] > 0
        assert set(r["forecast_years"][var]) == {1, 2, 3} and "p50" in r["forecast_year1"][var if family == "operating" else "rote"]
        assert r["near_term"]["copula"]["measured"] == ["nt_" + var + "_1|nt_" + var + "_2"]
