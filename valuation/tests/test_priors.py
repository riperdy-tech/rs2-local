"""Tests of the population priors (T-priors): the no-look-ahead proof, the quantile and merge rules on synthetic panels, the curves, the curve-position
reference, and the engines running end to end on a real PriorSet.  Synthetic companyfacts only, except the last test (real store, skipped if absent)."""
import gzip
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation import engine_commodity as com, engine_financial as fin, engine_operating as op
from valuation.common import Curve, QuantileDist, build_state
from valuation.pit_data import PitData
from valuation.priors import PopulationPriors, _curve_from_rows, features
from valuation.priors_build import config as C
from valuation.priors_build import stats as S
from valuation.priors_build.make_tables import tables_from_frames
from valuation.priors_build.obs import company_observations
from valuation.tests import synth


# ---- a synthetic population ---------------------------------------------------------------------------------------------------------------------

def make_company(store, cik, rng, family="operating", first=2009, last=2024):
    """One company, annual reports 2009..2024 filed 60 days after the year end: revenue growing at a company-specific rate with noise, an operating margin that
    mean-reverts around a company-specific level."""
    g = rng.uniform(-0.03, 0.15)
    m_lvl = rng.uniform(0.02, 0.25)
    m = m_lvl + rng.uniform(-0.05, 0.05)
    rev = rng.uniform(50, 5000)
    facts = []
    for y in range(first, last + 1):
        rev *= 1 + g + rng.gauss(0, 0.05)
        m = m_lvl + 0.5 * (m - m_lvl) + rng.gauss(0, 0.03)
        fye = f"{y}-12-31"
        filed = (date.fromisoformat(fye) + timedelta(days=60)).isoformat()
        vals = {"Revenues": rev, "GrossProfit": rev * 0.5, "OperatingIncomeLoss": rev * m, "NetIncomeLoss": rev * m * 0.7,
                "NetCashProvidedByUsedInOperatingActivities": rev * m * 0.9, "PaymentsToAcquirePropertyPlantAndEquipment": rev * 0.05,
                "DepreciationDepletionAndAmortization": rev * 0.04,
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": rev * m,
                "IncomeTaxExpenseBenefit": rev * m * 0.3, "Assets": rev * 1.5, "StockholdersEquity": rev * 0.8, "CashAndCashEquivalentsAtCarryingValue": rev * 0.2,
                "LongTermDebtNoncurrent": rev * 0.3, "LongTermDebtCurrent": rev * 0.05, "AssetsCurrent": rev * 0.6, "LiabilitiesCurrent": rev * 0.25,
                "PropertyPlantAndEquipmentNet": rev * 0.5, "Liabilities": rev * 0.7}
        facts += synth.annual_report(fye, filed, vals, accn=f"{cik}-{y}")
    return synth.write_company(store, cik, facts)


def make_population(store, n_operating=260, n_commodity=70, n_financial=70, seed=7):
    rng = random.Random(seed)
    sic = {}
    cik = 1000
    for fam, n, code in (("operating", n_operating, "3571"), ("commodity", n_commodity, "1311"), ("financial", n_financial, "6021")):
        for _ in range(n):
            cik += 1
            sic[make_company(store, cik, rng, fam)] = code
    return sic


def observations(store, sic, vintage):
    pit = PitData(store)
    cut = C.cut_date(vintage)
    rows = []
    for cik in sorted(sic):
        c = pit.company(cik)
        rows += company_observations(c, cut, sic[cik])
        pit.drop_cache()
    return pd.DataFrame(rows).sort_values(["cik", "fye"]).reset_index(drop=True)


def perturb_after(store_in, store_out, cut_iso, factor=3.7):
    """A copy of the store in which every fact filed on or after `cut_iso` has another value, with one extra, later annual report per company and a company
    that first files after the cut: whatever the future holds, it is different."""
    Path(store_out).mkdir(parents=True, exist_ok=True)
    for p in Path(store_in).glob("*.json.gz"):
        doc = json.load(gzip.open(p, "rt", encoding="utf-8"))
        for tags in doc["facts"].values():
            for units in tags.values():
                for rows in units.values():
                    for r in rows:
                        if r[4] >= cut_iso:
                            r[2] = r[2] * factor
        with gzip.open(Path(store_out) / p.name, "wt", encoding="utf-8") as f:
            json.dump(doc, f)
    synth.write_company(store_out, 99999, synth.annual_report("2018-12-31", "2019-03-01", {"Revenues": 10.0, "OperatingIncomeLoss": 1.0}))


def perturb_before(store_in, store_out, cut_iso, cik, factor=1.5):
    Path(store_out).mkdir(parents=True, exist_ok=True)
    for p in Path(store_in).glob("*.json.gz"):
        doc = json.load(gzip.open(p, "rt", encoding="utf-8"))
        if p.name.startswith(f"{int(cik):010d}"):
            for tags in doc["facts"].values():
                for units in tags.values():
                    for rows in units.values():
                        for r in rows:
                            if "2014-01-01" <= r[4] < cut_iso:
                                r[2] = r[2] * factor
        with gzip.open(Path(store_out) / p.name, "wt", encoding="utf-8") as f:
            json.dump(doc, f)


@pytest.fixture(scope="module")
def pop(tmp_path_factory):
    root = tmp_path_factory.mktemp("pop")
    sic = make_population(root / "store")
    return root, sic


META = {"obs_sha256": "0" * 64, "store_fingerprint_sha256": "1" * 64, "observations": 0}


# ---- the no-look-ahead proof -------------------------------------------------------------------------------------------------------------------

def test_changing_any_fact_filed_after_the_cut_changes_nothing_in_the_observations_or_the_tables(pop, tmp_path):
    root, sic = pop
    cut = C.cut_date(2016)
    perturb_after(root / "store", tmp_path / "later", cut)
    a = observations(root / "store", sic, 2016)
    b = observations(tmp_path / "later", dict(sic, **{"0000099999": "3571"}) if False else sic, 2016)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) > 100
    # an extra company that first files after the cut has no observation at the vintage
    sic2 = dict(sic)
    sic2["0000099999"] = "3571"
    c = observations(tmp_path / "later", sic2, 2016)
    assert len(c) == len(a)
    ta, tb = tables_from_frames(a, None, META, None, 2016), tables_from_frames(c, None, META, None, 2016)
    assert json.dumps(ta, sort_keys=True) == json.dumps(tb, sort_keys=True)


def test_the_proof_is_sensitive_changing_a_fact_filed_before_the_cut_changes_the_observations(pop, tmp_path):
    root, sic = pop
    perturb_before(root / "store", tmp_path / "earlier", C.cut_date(2016), 1001)
    a = observations(root / "store", sic, 2016)
    b = observations(tmp_path / "earlier", sic, 2016)
    assert not a.equals(b)


def test_a_prior_for_t_is_unchanged_by_anything_filed_on_or_after_the_cut(pop, tmp_path):
    root, sic = pop
    cut = C.cut_date(2016)
    perturb_after(root / "store", tmp_path / "later", cut)
    dirs = {}
    for name, store in (("a", root / "store"), ("b", tmp_path / "later")):
        df = observations(store, sic, 2016)
        t = tables_from_frames(df, None, META, None, 2016)
        d = tmp_path / name / "2016"
        d.mkdir(parents=True)
        (d / "tables.json").write_text(json.dumps(t), encoding="utf-8")
        dirs[name] = tmp_path / name
    pit = PitData(root / "store")
    cik = sorted(sic)[3]
    cp = pit.company_pit(cik, "2016-12-31")
    st = build_state(cp)
    pa = PopulationPriors(dirs["a"]).for_company("operating", st, "2017-06-30")
    pb = PopulationPriors(dirs["b"]).for_company("operating", st, "2017-06-30")
    assert pa.source == pb.source and "vintage=2016" in pa.source
    assert set(pa.inputs) == set(pb.inputs) and pa.inputs
    for k in pa.inputs:
        assert pa.inputs[k].q == pb.inputs[k].q
    for k in pa.curves:
        assert pa.curves[k].values == pb.curves[k].values
    assert pa.meta["cells"] == pb.meta["cells"]


def test_a_date_uses_the_vintage_of_the_previous_year_end():
    p = PopulationPriors(Path("."))
    assert p.vintage_for("2017-01-01") == 2016 and p.vintage_for("2016-12-31") == 2015 and p.vintage_for("2026-06-30") == 2025
    assert C.cut_date(2016) == "2017-01-01"        # filings filed strictly before it: nothing on or after any T >= the cut date


def test_no_vintage_is_an_empty_set_the_engine_refuses_on_not_an_exception(tmp_path):
    ps = PopulationPriors(tmp_path).for_company("operating", {"periods": []}, "2017-06-30")
    assert ps.inputs == {} and ps.source == "UNAVAILABLE" and ps.meta["unavailable"]


# ---- quantile and merge rules on synthetic panels ---------------------------------------------------------------------------------------------

def test_quantiles_are_type7_with_n():
    x = list(range(1, 102))
    q = S.qdict(x)
    assert q["n"] == 101 and q["p50"] == 51 and q["p5"] == pytest.approx(6.0) and q["p95"] == pytest.approx(96.0)
    assert S.qdict([float("nan")])["n"] == 0


def test_merge_rule_smallest_group_joins_its_smaller_adjacent_neighbour():
    assert S.merge_1d([100, 100, 100]) == [(0, 0), (1, 1), (2, 2)]
    assert S.merge_1d([10, 60, 5, 100]) == [(0, 2), (3, 3)]       # 5 joins 60 (the smaller neighbour) = 65; then 10 joins 65 = 75
    assert S.merge_1d([49, 49]) == [(0, 1)]
    assert S.merge_1d([5, 5, 5, 5, 5], 50) == [(0, 4)]
    assert S.merge_1d([30, 30, 100]) == [(0, 1), (2, 2)]
    assert S.merge_1d([100, 3, 100]) == [(0, 1), (2, 2)]           # tie between the neighbours: the lower index


def test_grid_cells_merge_thin_cells_flag_them_and_keep_every_observation():
    rng = np.random.default_rng(1)
    rows = np.concatenate([np.zeros(200, int), np.ones(10, int), np.full(200, 2)])
    cols = rng.integers(0, 3, size=len(rows))
    vals = rng.normal(size=len(rows))
    cells = S.grid_cells(rows, cols, vals, 3, 3, 50)
    assert sum(c["n"] for c in cells) == len(rows)
    assert all(c["n"] >= 50 for c in cells)
    assert any(c["merged_rows"] for c in cells)               # the thin middle row (10 obs) was merged into a neighbour
    assert S.find_cell(cells, 1, 1) is not None


def test_nnls_small_matches_the_unconstrained_solution_when_it_is_non_negative_and_zeroes_the_rest():
    rng = np.random.default_rng(2)
    X = rng.uniform(size=(500, 4))
    y = X @ np.array([0.5, 0.0, 0.3, 0.2]) + rng.normal(scale=0.01, size=500)
    w = S.nnls_small(X, y)
    assert np.allclose(w, [0.5, 0, 0.3, 0.2], atol=0.03)
    y2 = X @ np.array([0.5, -2.0, 0.3, 0.2])
    assert S.nnls_small(X, y2)[1] == 0.0


def test_the_copula_correlation_reproduces_a_spearman_rank_correlation():
    assert S.gaussian_copula_r(0.0) == 0.0
    assert S.gaussian_copula_r(1.0) == pytest.approx(1.0)
    rng = np.random.default_rng(3)
    z = rng.multivariate_normal([0, 0], [[1, 0.6], [0.6, 1]], size=20000)
    rs, _ = S.spearman(z[:, 0], z[:, 1])
    assert S.gaussian_copula_r(rs) == pytest.approx(0.6, abs=0.03)


# ---- curves ---------------------------------------------------------------------------------------------------------------------------------------

def test_a2_retention_recovers_a_designed_geometric_reversion_and_it_is_monotone():
    rng = np.random.default_rng(4)
    n = 400
    med = rng.uniform(0.05, 0.2, n)
    dev = rng.choice([-1, 1], n) * rng.uniform(0.02, 0.1, n)
    levels = {k: med + dev * 0.6 ** k for k in S.RATIO_KS}
    t = S.retention_table(dev, med, levels, np.ones(n, bool))
    meds = [r["median"] for r in t["ks"]]
    assert meds == pytest.approx([0.6 ** k for k in S.RATIO_KS])
    assert all(b < a for a, b in zip(meds, meds[1:]))
    assert t["ks"][4]["q"]["p50"] == pytest.approx(0.6 ** 5)         # the fraction-still-open distribution at year 5 is kept


def test_a_non_monotone_measured_curve_is_reported_not_forced():
    rows = [{"k": k, "n": 100, "median": v} for k, v in enumerate([0.9, 0.5, 0.7, 0.4], 1)]
    flags = []
    cv = _curve_from_rows(rows, "median", "n", "margin_retention", "src", flags)
    assert cv.values[:4] == [0.9, 0.5, 0.7, 0.4]                      # not sorted or smoothed
    assert any("not monotone" in f for f in flags)
    rows2 = [{"k": 1, "n": 100, "median": 1.4}, {"k": 2, "n": 100, "median": -0.2}]
    flags = []
    cv = _curve_from_rows(rows2, "median", "n", "x", "src", flags)
    assert cv.values[:2] == [1.0, 0.0] and any("clipped" in f for f in flags)
    assert len(cv) == 10 and any("held" in f for f in flags)


def test_the_curve_stops_where_fewer_than_50_observations_stand_behind_it():
    rows = [{"k": 1, "n": 100, "median": 0.9}, {"k": 2, "n": 60, "median": 0.8}, {"k": 3, "n": 49, "median": 0.1}]
    cv = _curve_from_rows(rows, "median", "n", "c", "s", [])
    assert cv.values[:3] == [0.9, 0.8, 0.8]                             # k = 3 (n = 49) is not used; the last measured value is held


# ---- the curve-position reference: the median equals the curve at year 5 ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_vintage(pop, tmp_path_factory):
    root, sic = pop
    df = observations(root / "store", sic, 2024)
    t = tables_from_frames(df, None, META, None, 2024)
    d = tmp_path_factory.mktemp("vint")
    (d / "2024").mkdir()
    (d / "2024" / "tables.json").write_text(json.dumps(t), encoding="utf-8")
    return d, root, sic


def _state_for(root, sic, cik, asof="2025-06-30", industry_roic=0.10, industry_rote=0.10):
    pit = PitData(root / "store")
    cp = pit.company_pit(cik, asof)
    st = build_state(cp)
    st["industry_roic"] = {"value": industry_roic, "n": 50, "basis": "industry"}        # Addendum H3: what gate1.value_company attaches from the date's population
    st["industry_rote"] = {"value": industry_rote, "n": 50, "basis": "industry"}
    return cp, st


@pytest.mark.parametrize("family,names", [("operating", {"growth_persistence": "growth_decay", "margin_retention": "margin_retention"}),
                                          ("commodity", {"growth_persistence": "growth_decay"}),
                                          ("financial", {"growth_persistence": "growth_decay", "rote_retention": "rote_retention"})])
def test_curve_position_median_equals_the_measured_curve_at_year_5(synthetic_vintage, family, names):
    d, root, sic = synthetic_vintage
    code = {"operating": "3571", "commodity": "1311", "financial": "6021"}[family]
    cik = next(c for c, s in sorted(sic.items()) if s == code)
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company(family, st, "2025-06-30")
    pos = ps.refs["curve_position"]
    for name, curve in names.items():
        qd = pos(name, st)
        assert isinstance(qd, QuantileDist) and qd is not None
        assert qd.ppf(0.5) == pytest.approx(ps.curves[curve].at(5), abs=1e-12)
        lv = [p for p, _ in qd.q]
        assert lv[0] == 0.05 and lv[-1] == 0.95 and all(0.0 <= v <= 1.0 for _, v in qd.q)
    assert pos("ronic_not_a_curve", st) is None


def test_commodity_margin_retention_position_matches_the_normalization_curve_of_the_score(synthetic_vintage):
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "1311")
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company("commodity", st, "2025-06-30")
    score = st["cyclicality"]["score"]
    curve = ps.refs["normalization_curve"](score, 10)
    qd = ps.refs["curve_position"]("margin_retention", st)
    assert qd.ppf(0.5) == pytest.approx(curve.at(5), abs=1e-12)


def test_the_priorset_carries_the_baseline_the_correlations_and_stamps_every_fallback(synthetic_vintage):
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    assert ps.placeholder is False and "vintage=2024" in ps.source and "obs_sha256=" in ps.source
    mb = ps.meta["mechanical_baseline"]
    assert mb["g1"] is not None and mb["margin_held"] is not None and "trailing 3-year CAGR" in mb["g1_basis"]
    assert isinstance(ps.meta["fallbacks"], list) and isinstance(ps.meta["unavailable"], list)
    assert set(ps.inputs) <= {"g1", "g_terminal", "margin_target", "ronic"}


def _group_of(T_section, cell):
    """The residual group (as built into the vintage) the prior's meta says it used: its residual cell and its level band."""
    grp = [g for g in T_section["residual_k5_by_level"][cell["residual_cell"]]["groups"] if g["band"] == cell["level_band"]["band"]]
    assert len(grp) == 1
    return grp[0]


def test_margin_target_is_the_year_5_level_with_the_spread_measured_in_the_companys_own_current_level_band(synthetic_vintage):
    """Addendum H1 + I1: the quantiles are centre + r_5 x deviation + the residual quantiles of the company's CURRENT margin band (measured, not scaled); the median path is the curve's."""
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    cell = ps.meta["cells"]["margin_target"]
    qd = ps.inputs["margin_target"]
    T = json.loads((d / "2024" / "tables.json").read_text(encoding="utf-8"))
    assert T["priors_version"] == "3" and "residual_k5_by_level" in T["margin_retention"] and "residual_k5_by_level" in T["roic_level"]
    res = _group_of(T["margin_retention"], cell)
    lo, hi = res["lower"], res["upper"]
    assert (lo is None or st["op_margin"] >= lo) and (hi is None or st["op_margin"] < hi) and cell["level_band"]["level"] == pytest.approx(st["op_margin"])
    assert cell["r5"] == pytest.approx(ps.curves["margin_retention"].at(5))
    assert cell["level5_median"] == pytest.approx(cell["centre_8y_median"] + cell["r5"] * (cell["dev"] or 0.0))
    assert qd.ppf(0.9) - qd.ppf(0.1) == pytest.approx(res["p90"] - res["p10"])          # the measured width of the band, as measured
    assert qd.ppf(0.5) == pytest.approx(cell["level5_median"] + res["p50"])
    assert res["n"] >= C.MIN_N and cell["n"] == res["n"]


def test_residual_by_level_measures_a_spread_that_grows_with_the_level():
    """Addendum I1 on a heteroskedastic panel: resid = level x noise.  The five bands' widths rise with the level, the ranges tile the line, every group has n >= 50."""
    rng = np.random.default_rng(11)
    lv = rng.uniform(0.01, 0.30, 2000)
    t = S.residual_by_level(lv, rng.normal(0, 1, 2000) * lv * 0.5)
    g = t["groups"]
    assert t["n"] == 2000 and [x["band"] for x in g] == [[i, i] for i in range(5)] and sum(x["n"] for x in g) == 2000 and all(x["n"] >= S.MIN_N for x in g)
    w = [x["p90"] - x["p10"] for x in g]
    assert all(b > a for a, b in zip(w, w[1:])) and w[-1] > 3 * w[0]                  # the spread is measured by level, not scaled by hand
    assert g[0]["lower"] is None and g[-1]["upper"] is None and all(a["upper"] == b["lower"] for a, b in zip(g, g[1:]))
    # a value on a cut goes to the upper band (the repo's bucket convention)
    from valuation.priors import _level_group
    cut = g[1]["upper"]
    assert _level_group(t, cut)[0]["band"] == [2, 2] and _level_group(t, cut - 1e-12)[0]["band"] == [1, 1]
    assert _level_group(t, -5.0)[0]["band"] == [0, 0] and _level_group(t, 5.0)[0]["band"] == [4, 4]       # open ends
    assert _level_group(t, None)[0] is None and _level_group(None, 0.1)[0] is None


def test_residual_by_level_merges_thin_bands_by_the_stated_rule_and_a_cell_under_50_stays_thin():
    rng = np.random.default_rng(5)
    t = S.residual_by_level(rng.uniform(0, 1, 120), rng.normal(0, 1, 120))               # 24 per quintile: merged by merge_1d until every group has >= 50
    assert all(x["n"] >= S.MIN_N for x in t["groups"]) and sum(x["n"] for x in t["groups"]) == 120
    assert len(t["groups"]) == len(S.merge_1d([24] * 5, S.MIN_N))
    assert all(x["merged"] for x in t["groups"] if x["band"][1] > x["band"][0])
    thin = S.residual_by_level(rng.uniform(0, 1, 40), rng.normal(0, 1, 40))             # under 50 in all: one thin group, which the lookup refuses (Addendum I5)
    assert len(thin["groups"]) == 1 and thin["groups"][0]["thin"] and thin["n"] == 40
    from valuation.priors import _level_group
    assert _level_group(thin, 0.5) == (None, 40)
    assert S.residual_by_level(np.array([]), np.array([]))["groups"] == []


def _tables_copy(d, tmp_path, mutate):
    T = json.loads((d / "2024" / "tables.json").read_text(encoding="utf-8"))
    mutate(T)
    out = tmp_path / "v"
    (out / "2024").mkdir(parents=True)
    (out / "2024" / "tables.json").write_text(json.dumps(T), encoding="utf-8")
    return out


def test_two_companies_in_different_level_bands_get_different_spreads(synthetic_vintage, tmp_path):
    """Addendum I1: the residual quantiles come from the group the company's own current margin falls in: split the cell at the company's margin and the two sides differ."""
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    base = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    cell = base.meta["cells"]["margin_target"]
    m = st["op_margin"]

    def split(low_width, high_width, cut):
        def mutate(T):
            key = cell["residual_cell"]
            tab = T["margin_retention"]["residual_k5_by_level"][key]
            tab["groups"] = [{"band": [0, 1], "lower": None, "upper": cut, "n": 100, "p5": -low_width, "p10": -low_width / 2, "p25": -low_width / 4, "p50": 0.0, "p75": low_width / 4,
                              "p90": low_width / 2, "p95": low_width, "merged": True, "thin": False},
                             {"band": [2, 4], "lower": cut, "upper": None, "n": 100, "p5": -high_width, "p10": -high_width / 2, "p25": -high_width / 4, "p50": 0.0,
                              "p75": high_width / 4, "p90": high_width / 2, "p95": high_width, "merged": True, "thin": False}]
            tab["n"] = 200
        return mutate
    lo_side = PopulationPriors(_tables_copy(d, tmp_path / "a", split(0.02, 0.40, m + 1.0))).for_company("operating", st, "2025-06-30")      # the margin is below the cut
    hi_side = PopulationPriors(_tables_copy(d, tmp_path / "b", split(0.02, 0.40, m - 1.0))).for_company("operating", st, "2025-06-30")      # the margin is above the cut
    w = lambda ps: ps.inputs["margin_target"].ppf(0.9) - ps.inputs["margin_target"].ppf(0.1)         # noqa: E731
    assert w(lo_side) == pytest.approx(0.02 / 2 * 2) and w(hi_side) == pytest.approx(0.40 / 2 * 2)
    assert lo_side.meta["cells"]["margin_target"]["level_band"]["band"] == [0, 1] and hi_side.meta["cells"]["margin_target"]["level_band"]["band"] == [2, 4]


def test_a_margin_or_roic_residual_cell_under_50_is_merged_up_then_the_input_is_refused_named(synthetic_vintage, tmp_path):
    """Addendum I1 (the merge rule) and I5: the residual cell of the company's band is merged up (sign-pooled, then fully pooled) and, when every cell is under 50, the input
    is refused naming the n."""
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    base = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    key = base.meta["cells"]["margin_target"]["residual_cell"]

    def thin_own(T):                                  # the company's own cell: under 50
        T["margin_retention"]["residual_k5_by_level"][key]["n"] = 25
    ps = PopulationPriors(_tables_copy(d, tmp_path / "a", thin_own)).for_company("operating", st, "2025-06-30")
    assert "margin_target" in ps.inputs or any("margin_target:" in u for u in ps.meta["unavailable"])
    if "margin_target" in ps.inputs:                  # merged up to the next pooled cell, stamped
        assert any("merged up to" in f for f in ps.meta["fallbacks"])

    def thin_all(T):
        for v in T["margin_retention"]["residual_k5_by_level"].values():
            v["n"] = 25
        for v in T["roic_level"]["residual_k5_by_level"].values():
            v["n"] = 25
    ps = PopulationPriors(_tables_copy(d, tmp_path / "b", thin_all)).for_company("operating", st, "2025-06-30")
    assert "margin_target" not in ps.inputs and any("margin_target: no residual cell with n >= 50" in u and "n=25" in u for u in ps.meta["unavailable"])
    assert "ronic" not in ps.inputs and any("ronic: no ROIC residual cell with n >= 50" in u and "n=25" in u for u in ps.meta["unavailable"])
    r = op.run(cp, PopulationPriors(_tables_copy(d, tmp_path / "c", thin_all)), _disc(), n_draws=20, state=st)
    assert r["status"] == "refused" and any("priors do not supply" in x and "margin_target" in x for x in r["reasons"])


def test_a_rote_residual_or_g1_cell_under_50_refuses_the_input_named(synthetic_vintage, tmp_path):
    """Addendum I5 for the other inputs: the ROTE residual (the coordinator's example, n = 25) and a growth cell under 50 after the merges."""
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    cikf = next(c for c, s in sorted(sic.items()) if s == "6021")
    cpf, stf = _state_for(root, sic, cikf)

    def thin_rote(T):                                 # the ROTE residual of the 2020 vintage in the coordinator's example: n = 25
        for v in T["rote_retention"]["residual_k5"].values():
            v["n"] = 25
    psf = PopulationPriors(_tables_copy(d, tmp_path / "d", thin_rote)).for_company("financial", stf, "2025-06-30")
    assert "rote_target" not in psf.inputs and any("rote_target: no residual cell with n >= 50" in u and "n=25" in u for u in psf.meta["unavailable"])
    assert fin.run(cpf, PopulationPriors(_tables_copy(d, tmp_path / "e", thin_rote)), _disc(), n_draws=20, state=stf)["status"] == "refused"

    def thin_g1(T):                                   # a size x growth cell under 50 (a whole table that thin): refused, named (the operating family has no fallback)
        for basis in T["g1"]["operating"].values():
            for c in basis.get("cells", []) + basis.get("size_pooled_cells", []):
                c["n"] = 30
    psg = PopulationPriors(_tables_copy(d, tmp_path / "f", thin_g1)).for_company("operating", st, "2025-06-30")
    assert "g1" not in psg.inputs and any(u.startswith("g1:") and "n=30" in u for u in psg.meta["unavailable"])

    def merge_rote(T):                                # the signed cell under 50 merges to the sign-pooled cell when that has 50 or more: stamped
        T["rote_retention"]["residual_k5"]["pos"]["n"] = 20
        T["rote_retention"]["residual_k5"]["neg"]["n"] = 20
    psm = PopulationPriors(_tables_copy(d, tmp_path / "g", merge_rote)).for_company("financial", stf, "2025-06-30")
    assert "rote_target" in psm.inputs and psm.meta["cells"]["rote_target"]["residual_cell"] == "all" and any("rote_target: residual cell" in f for f in psm.meta["fallbacks"])


def _disc():
    from valuation.discount_rate import DiscountRate
    return DiscountRate(asof="2025-06-30", rf=0.04, erp=0.05, beta_unlevered=1.0, de_ratio=0.0, de_basis="book", tax=0.25, beta_levered=1.0, coe=0.10,
                        kd_pretax=None, wacc=0.09, placeholder=True)


def test_roic_level_table_measures_the_excess_retention_and_the_level_residual():
    """Addendum H3 on a hand-built panel: roic_{t+k} = ref + 0.6^k (roic3 - ref) + noise, the same-year median as the reference."""
    rng = np.random.default_rng(3)
    n = 400
    year = np.repeat([2018, 2019, 2020, 2021], n // 4)
    roic3 = rng.normal(0.10, 0.08, n)
    ref = pd.Series(roic3).groupby(year).transform("median").to_numpy()
    d = pd.DataFrame({"family": "operating", "year": year, "roic3": roic3})
    for k in S.RATIO_KS:
        d[f"roic_{k}"] = ref + 0.6 ** k * (roic3 - ref) + (rng.normal(0, 0.03, n) if k == 5 else 0.0)
    t = S.roic_level_tables(d)
    assert t["n_obs"] == n and set(t["bands"]) == {"pos", "neg", "all"}
    meds = [r["median"] for r in t["bands"]["all"]["ks"]]
    assert meds[:4] == pytest.approx([0.6 ** k for k in (1, 2, 3, 4)], abs=1e-9) and meds[4] == pytest.approx(0.6 ** 5, abs=0.05)
    res = t["residual_k5"]["all"]
    assert abs(res["p50"]) < 0.01 and 0.04 < res["p90"] - res["p10"] < 0.10         # about 2 x 1.28 x 0.03 = 0.077: the noise of the level five years on
    assert t["bands"]["pos"]["sign"] == 1 and t["bands"]["neg"]["sign"] == -1
    d2 = d.copy()
    d2["roic3"] = np.nan
    assert S.roic_level_tables(d2)["n_obs"] == 0


def test_ronic_is_the_roic_level_five_years_on_the_own_level_fading_to_the_industry_median_with_the_measured_spread(synthetic_vintage):
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    T = json.loads((d / "2024" / "tables.json").read_text(encoding="utf-8"))
    for ind in (0.02, 0.30):
        cp, st = _state_for(root, sic, cik, industry_roic=ind)
        ps = PopulationPriors(d).for_company("operating", st, "2025-06-30")
        assert "ronic" in ps.inputs and "ronic_fade" in ps.curves, ps.meta["unavailable"]
        cell = ps.meta["cells"]["ronic"]
        L0 = st["roic3"]
        assert cell["L0_trailing_3y_roic"] == pytest.approx(L0) and cell["industry_median_roic"] == ind
        assert cell["level5_median"] == pytest.approx(ind + ps.curves["ronic_fade"].at(5) * (L0 - ind))
        res = _group_of(T["roic_level"], cell)
        qd = ps.inputs["ronic"]
        assert qd.ppf(0.9) - qd.ppf(0.1) == pytest.approx(res["p90"] - res["p10"]) and qd.ppf(0.5) == pytest.approx(cell["level5_median"] + res["p50"])
    # without the date's industry median (or the own trailing ROIC) the prior names what it lacks, and the engine refuses before it
    cp, st = _state_for(root, sic, cik)
    del st["industry_roic"]
    ps = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    assert "ronic" not in ps.inputs and any("industry median ROIC" in u for u in ps.meta["unavailable"])
    st["industry_roic"] = {"value": 0.1, "n": 5, "basis": "industry"}
    st["roic3"] = None
    assert any("trailing 3-year ROIC" in u for u in PopulationPriors(d).for_company("operating", st, "2025-06-30").meta["unavailable"])


def test_terminal_growth_is_not_a_prior(synthetic_vintage):
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    assert "g_terminal" not in ps.inputs and not any("g_terminal" in u for u in ps.meta["unavailable"])


def test_the_financial_priorset_reports_the_plateau_the_terminal_excess_retention_is_read_from(synthetic_vintage):
    """Addendum I4: the plateau of the excess-retention curve and the k it was measured at (the longest k with n >= 50) are named in the PriorSet's meta."""
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "6021")
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company("financial", st, "2025-06-30")
    cell = ps.meta["cells"]["excess_fade"]
    assert cell["plateau"] == pytest.approx(ps.curves["excess_fade"].values[-1]) and 1 <= cell["plateau_k"] <= 7 and cell["plateau_n"] >= C.MIN_N
    T = json.loads((d / "2024" / "tables.json").read_text(encoding="utf-8"))
    rows = T["excess_fade_financial"]["ks"]
    assert cell["plateau_k"] == max(r["k"] for r in rows if r["k"] <= cell["plateau_k"] and r["n"] >= C.MIN_N) and cell["plateau_n"] == rows[cell["plateau_k"] - 1]["n"]


def test_the_operating_priorset_reports_the_plateau_the_terminal_ronic_kappa_is_read_from(synthetic_vintage):
    """Addendum J3: the plateau of the ROIC-excess retention curve and the k it was measured at (the longest k with n >= 50) are named in the PriorSet's meta, and the engine's
    kappa is the curve's last value."""
    d, root, sic = synthetic_vintage
    cik = next(c for c, s in sorted(sic.items()) if s == "3571")
    cp, st = _state_for(root, sic, cik)
    ps = PopulationPriors(d).for_company("operating", st, "2025-06-30")
    cell = ps.meta["cells"]["ronic_fade"]
    assert cell["plateau"] == pytest.approx(ps.curves["ronic_fade"].values[-1]) and cell["plateau_n"] >= C.MIN_N and 1 <= cell["plateau_k"] <= 7
    T = json.loads((d / "2024" / "tables.json").read_text(encoding="utf-8"))
    rows = T["roic_level"]["bands"][cell["band"]]["ks"]
    assert cell["plateau_k"] == max(r["k"] for r in rows if r["k"] <= cell["plateau_k"] and r["n"] >= C.MIN_N) and cell["plateau_n"] == rows[cell["plateau_k"] - 1]["n"]


def test_the_engines_run_end_to_end_on_a_synthetic_priorset(synthetic_vintage):
    from valuation.discount_rate import DiscountRate
    d, root, sic = synthetic_vintage
    pp = PopulationPriors(d)
    disc = DiscountRate(asof="2025-06-30", rf=0.04, erp=0.05, beta_unlevered=1.0, de_ratio=0.0, de_basis="book", tax=0.25, beta_levered=1.0, coe=0.10,
                        kd_pretax=None, wacc=0.09, placeholder=True)
    for fam, code, eng in (("operating", "3571", op), ("commodity", "1311", com), ("financial", "6021", fin)):
        cik = next(c for c, s in sorted(sic.items()) if s == code)
        cp, st = _state_for(root, sic, cik)
        r = eng.run(cp, pp, disc, n_draws=100, state=st)
        assert r["status"] in ("ok", "refused")
        assert not any("priors do not supply" in x for x in r.get("reasons", [])), r.get("reasons")
        assert not any("industry median" in x for x in r.get("reasons", []))


# ---- the real population (skipped when the store or the built vintage is absent) -----------------------------------------------------------------

REAL = C.DATA_DIR / "2021" / "tables.json"


def _real_vintage_is_v2():
    try:
        return REAL.exists() and "roic_level" in json.loads(REAL.read_text(encoding="utf-8"))
    except OSError:
        return False


@pytest.mark.skipif(not (C.STORE_DIR.exists() and _real_vintage_is_v2()), reason="real store or a priors-v2 vintage (with the roic_level table) absent")
def test_engines_run_on_real_priors_for_a_few_names_no_value_is_asserted():
    from valuation.classification import classification
    from valuation.discount_rate import DiscountRate
    from valuation.pit_data import SicRecord
    sic_map = json.loads((C.INPUTS_DIR / "sic_by_cik.json").read_text(encoding="utf-8"))["map"]
    pit = PitData(C.STORE_DIR, sic_source=lambda cik: (lambda s: SicRecord(s["sic"], "", "damodaran 2026-01 (current-dated)", False) if s else None)(sic_map.get(cik)))
    pp = PopulationPriors()
    disc = DiscountRate(asof="2022-06-30", rf=0.04, erp=0.05, beta_unlevered=1.0, de_ratio=0.0, de_basis="book", tax=0.25, beta_levered=1.0, coe=0.10,
                        kd_pretax=None, wacc=0.09, placeholder=True)
    ran = {"operating": 0, "commodity": 0, "financial": 0}
    for cik in ("0000320193", "0000789019", "0000034088", "0000019617", "0000070858", "0000072971", "0000831259", "0000093410"):
        cp = pit.company_pit(cik, "2022-06-30")
        if cp is None:
            continue
        fam = classification(cik, "2022-06-30", cp)["family"]
        if fam not in ran:
            continue
        st = build_state(cp)
        st["industry_roic"] = {"value": 0.10, "n": 50, "basis": "industry"}          # Addendum H3: a stand-in for the date's population (plumbing check, no value asserted)
        st["industry_rote"] = {"value": 0.10, "n": 50, "basis": "industry"}
        r = {"operating": op, "commodity": com, "financial": fin}[fam].run(cp, pp, disc, n_draws=200, state=st)
        assert r["status"] in ("ok", "refused")
        assert not any("priors do not supply" in x for x in r.get("reasons", [])), (cik, r.get("reasons"))
        if r["status"] == "ok":
            assert r["placeholder"] is True                  # the discount rate here is a placeholder: the result is a plumbing check, not a value
            ran[fam] += 1
    assert sum(ran.values()) >= 2
