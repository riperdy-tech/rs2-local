"""Tests of the round-4 level decomposition (Addendum J1): the variant list is one component at a time, a variant through `gate1.value_company` changes only what it says,
and the summary table's arithmetic.  Synthetic data only."""
import json

import pytest

from rebuild_harness import gate1_decompose as gd
from rebuild_harness import gate1_decompose_summary as ds
from valuation import gate1, pit_adapter
from valuation import pit_data as pdm
from valuation import variants as V
from valuation.priors_interface import PlaceholderPriors
from valuation.tests.test_gate1 import FakeStore, _sic, _store


def test_every_variant_swaps_exactly_one_component_and_the_erp_swap_leaves_the_engine_neutral():
    keys = [k for k, *_ in gd.VARIANTS]
    assert len(keys) == len(set(keys)) == 9
    default = V.Variant()
    for key, label, variant, swap_erp, fams in gd.VARIANTS:
        changed = [f for f in ("terminal_g", "terminal_ronic", "growth_decay", "margin", "reinvestment", "width") if getattr(variant, f) != getattr(default, f)]
        if swap_erp:
            assert changed == [] and variant.neutral and key == "a_erp_closure"
        else:
            assert len(changed) == 1, (key, changed)
        assert set(fams) <= {"operating", "commodity", "financial"} and label
    fam = {k: f for k, _l, _v, _s, f in gd.VARIANTS}
    assert fam["h_no_normalization"] == ("commodity",) and "financial" not in fam["f_zero_reinvestment"]


def _setup(tmp_path):
    pit = pdm.PitData(_store(tmp_path, base_rev=1000.0, growth=0.05), sic_source=_sic(tmp_path))
    prep = gate1.prepare(pit_adapter.adapt(pit, 1, "2020-06-30"))
    ctx = gate1.DateContext.build("2020-06-30", 0.02, [{"industry": "Software", "family": "operating", "de_book": 0.1 * i, "kd_effective": 0.06, "roic3": 0.01 * i} for i in range(1, 31)])
    return dict(prep, industry="Software"), ctx, gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")}), PlaceholderPriors(True)


def test_value_company_with_a_neutral_variant_is_the_registered_value_and_a_swap_changes_it(tmp_path):
    prep, ctx, rates, priors = _setup(tmp_path)
    base = gate1.value_company(prep, ctx, priors, rates, shares=50.0, n_draws=200)
    assert gate1.value_company(prep, ctx, priors, rates, shares=50.0, n_draws=200, variant=V.Variant()) == base
    assert gate1.value_company(prep, ctx, priors, rates, shares=50.0, n_draws=200, variant=None) == base
    flat = gate1.value_company(prep, ctx, priors, rates, shares=50.0, n_draws=200, variant=V.Variant(terminal_g="flat"))
    assert base["terminal_growth"]["base"] == 0.02 and flat["terminal_growth"]["base"] == 0.0375 and flat["iv_ps"]["p50"] != base["iv_ps"]["p50"]
    half = gate1.value_company(prep, ctx, priors, rates, shares=50.0, n_draws=200, variant=V.Variant(width=0.5))
    assert half["iv_point_p50_inputs_ps"] == pytest.approx(base["iv_point_p50_inputs_ps"])        # the point values do not move
    assert half["iv_ps"]["p90"] - half["iv_ps"]["p10"] < base["iv_ps"]["p90"] - base["iv_ps"]["p10"]


def _decomp():
    """Two dates; a base and two variants over four names of two families; one variant loses a name."""
    def day(d, closure):
        uni = {"1": {"family": "operating"}, "2": {"family": "operating"}, "3": {"family": "operating"}, "4": {"family": "financial"}}
        # [IV/price, share of valid draws floored, valid draws, draws, share invalid]
        base = {"1": [0.2, 0.5, 100, 100, 0.0], "2": [1.0, 0.0, 100, 100, 0.0], "3": [3.0, 0.0, 100, 100, 0.0], "4": [1.5, 0.0, 100, 100, 0.0]}
        v1 = {"1": [0.6, 0.25, 100, 100, 0.0], "2": [1.2, 0.0, 100, 100, 0.0], "3": None, "4": [1.7, 0.0, 100, 100, 0.0]}
        v2 = {"1": [-0.1, 1.0, 50, 100, 0.5], "2": [2.0, 0.0, 100, 100, 0.0]}              # a family-restricted variant: names 3 and 4 are not in it
        return {"date": d, "erp": {"damodaran_monthly": 0.05, "damodaran_annual": 0.05, "round3b_common_closure": closure, "monthly_row": d[:8] + "01"},
                "n_universe": 4, "universe": uni, "variants": {"base": base, "v1": v1, "v2": v2}, "labels": {"v1": "variant one", "v2": "variant two"}, "reference_check": None}
    return {"2020-03-31": day("2020-03-31", 0.03), "2022-03-31": day("2022-03-31", None)}


def test_the_summary_by_family_with_deltas_lost_names_and_pooled_floored_draws():
    S = ds.summarize(_decomp())
    b = S["base"]["operating"]
    assert b["n"] == 6 and b["median_vp"] == pytest.approx(1.0) and b["share_outside_0_4_2_5"] == pytest.approx(4 / 6) and b["share_nonpositive_iv"] == 0.0
    assert b["share_draws_floored_at_zero"] == pytest.approx((0.5 * 100 * 2) / 600)               # pooled over the valid draws of the names
    v1 = S["v1"]["operating"]
    assert v1["n"] == 4 and v1["n_lost"] == 2 and v1["n_in_universe"] == 6
    assert v1["median_vp"] == pytest.approx(0.9) and v1["baseline_median_vp_same_names"] == pytest.approx(0.6)       # base on the same four names: 0.2, 1.0, 0.2, 1.0
    assert v1["delta_median_vp"] == pytest.approx(0.3) and v1["median_paired_difference_vp"] == pytest.approx(0.3)
    v2 = S["v2"]["operating"]
    assert v2["n"] == 4 and v2["share_nonpositive_iv"] == pytest.approx(0.5) and v2["share_names_over_5pct_invalid_draws"] == pytest.approx(0.5)
    assert v2["share_draws_floored_at_zero"] == pytest.approx((1.0 * 50 * 2) / 300)
    assert S["v2"]["financial"]["n"] == 0                                                          # not in the variant
    allf = S["v1"]["all"]
    assert allf["n"] == 6 and allf["n_lost"] == 2
    assert ds.summarize(_decomp(), ["2020-03-31"])["base"]["operating"]["n"] == 3


def test_the_rendered_table_names_the_erp_series_and_says_diagnostic_provisional():
    txt = ds.render(_decomp())
    assert "DIAGNOSTIC ONLY" in txt and "PROVISIONAL" in txt and "2020-03-31" in txt and "3.0%" in txt and "variant one" in txt and "return dates only" in txt


def test_the_decomposition_refuses_more_than_eight_workers_and_a_holdout_date(tmp_path):
    with pytest.raises(SystemExit):
        gd.main(["--out-dir", str(tmp_path / "o"), "--priors-dir", str(tmp_path), "--closure-dir", str(tmp_path), "--workers", "9"])
    from rebuild_harness import holdout
    with pytest.raises(holdout.HoldoutRefused):
        gd.main(["--out-dir", str(tmp_path / "o2"), "--priors-dir", str(tmp_path), "--closure-dir", str(tmp_path), "--dates", "2023-03-31"])
    assert not (tmp_path / "o2").exists()
