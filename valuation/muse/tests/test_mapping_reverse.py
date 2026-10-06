"""Mapping (percentile + width -> distribution on the prior), the engines fed through MusePriors, and the reverse valuation (PLACEHOLDER priors and rates: test-only)."""
import pytest

from valuation.common import Curve, InputError, QuantileDist, build_state, exp_curve
from valuation.muse import mapping as mp
from valuation.muse import reverse as rv
from valuation.muse.mapping import Position, MusePriors, muse_distribution, percentile_of, position_curve, run_engine
from valuation.muse.reverse import point_value_per_share, reverse_valuation
from valuation.muse.schema import WIDTH_FACTORS
from valuation.muse.tests import fixtures as fx


def setup(family="operating", sic="3674"):
    pit = fx.make_pit(sic=sic)
    st = build_state(pit)
    ps = fx.LabeledPlaceholderPriors().for_company(family, st, pit.asof)
    return pit, st, ps, fx.disc_factory(st)


# ---- level inputs --------------------------------------------------------------------------------------------------------------------------

def test_p50_normal_is_the_prior_itself():
    _, _, ps, _ = setup()
    d = muse_distribution(ps.inputs["g1"], 50, "normal")
    for p, v in ps.inputs["g1"].q:
        assert d.ppf(p) == pytest.approx(v)


def test_the_median_moves_to_the_chosen_percentiles_value_and_width_scales_the_interquartile_range():
    _, _, ps, _ = setup()
    prior = ps.inputs["g1"]
    iqr = prior.ppf(0.75) - prior.ppf(0.25)
    for width, k in WIDTH_FACTORS.items():
        d = muse_distribution(prior, 75, width)
        assert d.ppf(0.5) == pytest.approx(prior.ppf(0.75))
        assert d.ppf(0.75) - d.ppf(0.25) == pytest.approx(k * iqr)
    assert WIDTH_FACTORS == {"narrow": 0.5, "normal": 1.0, "wide": 1.5}


def test_bad_width_or_percentile_is_an_input_error():
    _, _, ps, _ = setup()
    with pytest.raises(InputError):
        muse_distribution(ps.inputs["g1"], 50, "huge")
    with pytest.raises(InputError):
        muse_distribution(ps.inputs["g1"], 100, "normal")


def test_percentile_of_inverts_the_quantile_function():
    d = QuantileDist({0.10: -0.05, 0.25: 0.0, 0.50: 0.04, 0.75: 0.09, 0.90: 0.14})
    for u in (0.03, 0.2, 0.5, 0.77, 0.96):
        assert percentile_of(d, d.ppf(u)) == pytest.approx(u, abs=1e-6)
    assert percentile_of(d, 99.0) > 0.999999 - 1e-9


# ---- curve inputs ---------------------------------------------------------------------------------------------------------------------------

def test_position_curve_hits_q_at_year_5_keeps_order_and_range():
    base = exp_curve(10, 3.0, "m")
    for q in (0.05, 0.3, 0.8, 0.95):
        c, stamp = position_curve(base, q)
        assert stamp is None and c.at(5) == pytest.approx(q)
        assert all(0.0 <= v <= 1.0 for v in c.values)
        assert all(a >= b for a, b in zip(c.values, c.values[1:]))                    # a decaying curve stays decaying
    assert position_curve(base, base.at(5))[0] is base
    assert position_curve(base, 1.0)[0].values == [1.0] * 10
    assert position_curve(base, 0.0)[0].values == [0.0] * 10
    assert position_curve(base, 1.7)[0].values == [1.0] * 10                           # clamped


def test_a_curve_that_cannot_be_positioned_is_left_as_measured_and_says_so():
    flat = Curve([1.0] * 10, "flat")
    c, stamp = position_curve(flat, 0.5)
    assert c is flat and "not positionable" in stamp


# ---- the engines fed through MusePriors -------------------------------------------------------------------------------------------------------

def p50(res):
    return res["distribution"]["equity"]["p50"]


def test_an_all_p50_normal_placement_reproduces_the_prior_alone():
    pit, st, ps, disc = setup()
    base = run_engine("operating", pit, MusePriors(ps, "operating", st, {}), disc, n_draws=300, seed=7)
    pos = {n: Position(50.0, "normal") for n in ("g1", "margin_target", "ronic", "g_terminal")}
    placed = run_engine("operating", pit, MusePriors(ps, "operating", st, pos), disc, n_draws=300, seed=7)
    assert p50(placed) == pytest.approx(p50(base), rel=1e-9)
    assert placed["placeholder"] is True


def test_higher_growth_placement_raises_value_and_width_widens_the_distribution():
    pit, st, ps, disc = setup()
    lo = run_engine("operating", pit, MusePriors(ps, "operating", st, {"g1": Position(20.0, "normal")}), disc, n_draws=400, seed=3)
    hi = run_engine("operating", pit, MusePriors(ps, "operating", st, {"g1": Position(80.0, "normal")}), disc, n_draws=400, seed=3)
    assert p50(hi) > p50(lo)
    nar = run_engine("operating", pit, MusePriors(ps, "operating", st, {"g1": Position(50.0, "narrow")}), disc, n_draws=400, seed=3)
    wid = run_engine("operating", pit, MusePriors(ps, "operating", st, {"g1": Position(50.0, "wide")}), disc, n_draws=400, seed=3)
    spread = lambda r: r["distribution"]["equity"]["p90"] - r["distribution"]["equity"]["p10"]   # noqa: E731
    assert spread(wid) > spread(nar)


def test_curve_inputs_move_the_value_and_stamp_that_their_width_is_not_propagated():
    pit, st, ps, disc = setup()
    slow = MusePriors(ps, "operating", st, {"growth_persistence": Position(90.0, "wide")})
    fast = MusePriors(ps, "operating", st, {"growth_persistence": Position(10.0, "wide")})
    # the sign of the effect is not asserted: growth is nearly value-neutral when the return on new capital fades to the cost of capital
    assert p50(run_engine("operating", pit, slow, disc, n_draws=300, seed=5)) != pytest.approx(p50(run_engine("operating", pit, fast, disc, n_draws=300, seed=5)), rel=1e-6)
    assert mp.CURVE_WIDTH_STAMP in slow.stamps()
    assert slow.for_company("operating", st, pit.asof).curves["growth_decay"].at(5) == pytest.approx(ps.refs["curve_position"]("growth_persistence").ppf(0.9))


def test_the_family_must_match():
    _, st, ps, _ = setup()
    with pytest.raises(InputError):
        MusePriors(ps, "operating", st, {}).for_company("financial", st, None)


def test_commodity_margin_retention_is_positioned_through_the_normalization_reference():
    pit, st, ps, disc = setup("commodity", "1311")
    res = run_engine("commodity", pit, MusePriors(ps, "commodity", st, {"margin_retention": Position(90.0, "normal")}), disc, n_draws=200, seed=2)
    assert res["status"] == "ok" and "positioned" in res["normalization"]["curve_source"]
    base = run_engine("commodity", pit, MusePriors(ps, "commodity", st, {}), disc, n_draws=200, seed=2)
    assert p50(res) != p50(base)


def test_financial_rote_retention_is_positioned():
    pit, st, ps, disc = setup("financial", "6021")
    a = run_engine("financial", pit, MusePriors(ps, "financial", st, {"rote_retention": Position(90.0, "normal")}), disc, n_draws=200, seed=2)
    b = run_engine("financial", pit, MusePriors(ps, "financial", st, {"rote_retention": Position(10.0, "normal")}), disc, n_draws=200, seed=2)
    assert a["status"] == "ok" and p50(a) != p50(b)


def test_unanchored_is_the_priors_p50_with_width_wide_stamped():
    u = mp.unanchored("checks failed twice", "P2")
    assert (u.percentile, u.width, u.status) == (50.0, "wide", "unanchored") and "unanchored: checks failed twice" in u.stamps[0]


# ---- the reverse valuation ----------------------------------------------------------------------------------------------------------------------

def value_with(family, st, ps, disc, pct_by_name, level_u=None):
    point, q = rv.pass1_point(ps, family, st, {n: Position(p, "normal") for n, p in pct_by_name.items()})
    for n, u in (level_u or {}).items():
        point[n] = ps.inputs[n].ppf(u)
    curves, _nc, _s = mp.positioned_curves(ps, family, st, q)
    return point_value_per_share(family, st, point, curves, disc, st["shares_outstanding"])


def test_the_percentile_that_reproduces_the_price_is_found_for_a_level_input():
    _, st, ps, disc = setup()
    pos = {n: Position(50.0, "normal") for n in ("g1", "g_terminal", "margin_target", "ronic", "growth_persistence", "margin_retention")}
    price = value_with("operating", st, ps, disc, {n: 50 for n in pos}, {"g1": 0.70})
    r = reverse_valuation(ps, "operating", st, pos, disc, price, st["shares_outstanding"])
    g1 = r["inputs"]["g1"]
    assert g1["status"] == "ok" and g1["required_percentile"] == pytest.approx(70.0, abs=0.01) and g1["extraordinary"] is False
    assert g1["required_value"] == pytest.approx(ps.inputs["g1"].ppf(0.70), rel=1e-6)


def test_other_inputs_are_held_at_their_pass1_medians():
    _, st, ps, disc = setup()
    pos = {n: Position(50.0, "normal") for n in ("g1", "g_terminal", "margin_target", "ronic")}
    pos["margin_target"] = Position(80.0, "normal")
    price = value_with("operating", st, ps, disc, {"g1": 50, "g_terminal": 50, "margin_target": 80, "ronic": 50}, {"g1": 0.30})
    r = reverse_valuation(ps, "operating", st, pos, disc, price, st["shares_outstanding"])
    assert r["inputs"]["g1"]["required_percentile"] == pytest.approx(30.0, abs=0.01)
    assert r["iv_at_pass1_medians"] == pytest.approx(value_with("operating", st, ps, disc, {"g1": 50, "g_terminal": 50, "margin_target": 80, "ronic": 50}))


def test_a_curve_input_is_reversed_too():
    _, st, ps, disc = setup()
    pos = {n: Position(50.0, "normal") for n in ("g1", "growth_persistence")}
    cd = ps.refs["curve_position"]("growth_persistence")
    point, q = rv.pass1_point(ps, "operating", st, pos)
    q = dict(q, growth_persistence=cd.ppf(0.65))
    curves, _n, _s = mp.positioned_curves(ps, "operating", st, q)
    price = point_value_per_share("operating", st, point, curves, disc, st["shares_outstanding"])
    r = reverse_valuation(ps, "operating", st, pos, disc, price, st["shares_outstanding"])
    assert r["inputs"]["growth_persistence"]["required_percentile"] == pytest.approx(65.0, abs=0.01)


@pytest.mark.parametrize("u,flag", [(0.04, True), (0.06, False), (0.5, False), (0.94, False), (0.97, True)])
def test_outside_p5_p95_is_an_extraordinary_assumption(u, flag):
    _, st, ps, disc = setup()
    pos = {"g1": Position(50.0, "normal")}
    price = value_with("operating", st, ps, disc, {"g1": 50}, {"g1": u})
    r = reverse_valuation(ps, "operating", st, pos, disc, price, st["shares_outstanding"])["inputs"]["g1"]
    assert r["status"] == "ok" and r["extraordinary"] is flag


def test_a_price_nobody_in_p1_p99_reaches_is_not_reachable_and_extraordinary():
    _, st, ps, disc = setup()
    pos = {"g1": Position(50.0, "normal")}
    for price, word in ((1e9, "above"), (1e-6, "below")):
        r = reverse_valuation(ps, "operating", st, pos, disc, price, st["shares_outstanding"])
        g1 = r["inputs"]["g1"]
        assert g1["status"] == "not_reachable" and g1["extraordinary"] is True and g1["required_percentile"] is None
        assert word in g1["direction"] and 1.0 <= g1["nearest_percentile"] <= 99.0
    assert reverse_valuation(ps, "operating", st, pos, disc, 1e9, st["shares_outstanding"])["extraordinary_inputs"] == ["g1"]


def test_no_price_or_no_shares_is_a_refusal():
    _, st, ps, disc = setup()
    assert reverse_valuation(ps, "operating", st, {"g1": Position(50.0, "normal")}, disc, 10.0, None)["status"] == "refused"
    assert reverse_valuation(ps, "operating", st, {"g1": Position(50.0, "normal")}, disc, 0.0, 100.0)["status"] == "refused"


def test_the_financial_family_is_reversed_on_its_own_inputs():
    _, st, ps, disc = setup("financial", "6021")
    pos = {n: Position(50.0, "normal") for n in ("g1", "rote_target", "g_terminal")}
    price = value_with("financial", st, ps, disc, {n: 50 for n in pos}, {"rote_target": 0.6})
    r = reverse_valuation(ps, "financial", st, pos, disc, price, st["shares_outstanding"])
    assert r["inputs"]["rote_target"]["required_percentile"] == pytest.approx(60.0, abs=0.01)
