"""Tests of the T-integrate pieces: the adapter (decision-time refusals, stamps), the Addendum H1 margin level, the Addendum G debt rule, the
population context and the discount rate of a company (Addendum B 3 and 5), the holdout lock of the gate-1 run, and one company end to end on synthetic data.
Synthetic data only: no network, no archive, no model."""
import json
from datetime import datetime, timezone

import pytest

from valuation import gate1, pit_adapter
from valuation import pit_data as pdm
from valuation.common import Curve, DataNotPresent, Filed, QuantileDist, build_state, level_path_weights
from valuation.priors import PopulationPriors
from valuation.priors_interface import PlaceholderPriors
from valuation.tests import synth
from valuation.muse.tests import fixtures as fx


# ---- Addendum H1: the margin level five years on --------------------------------------------------------------------------------------------------

def test_level_path_weights_follow_the_measured_curve_and_hold_after_year_5():
    curve = Curve([0.9, 0.8, 0.7, 0.6, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5], "margin_retention")
    w, info = level_path_weights(curve, 10)
    assert info == {"shape": "curve", "clipped": False, "v_ref": 0.5}
    assert w[:5] == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0]) and w[5:] == [1.0] * 5
    # the median level five years on, m0 + (m5 - m0) w_t, IS the median path m_t = med + r_t (m0 - med) of the curve, where m5 = med + r_5 (m0 - med)
    m0, med = 0.20, 0.10
    m5 = med + curve.at(5) * (m0 - med)
    for t in range(1, 6):
        assert m0 + (m5 - m0) * w[t - 1] == pytest.approx(med + curve.at(t) * (m0 - med))


def test_level_path_weights_clip_a_non_monotone_curve_and_go_linear_when_nothing_closed_by_year_5():
    w, info = level_path_weights(Curve([0.9, 0.3, 0.8, 0.7, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6]), 10)
    assert info["clipped"] and all(0.0 <= x <= 1.0 for x in w) and w[1] == 1.0       # v_2 < v_5: the raw fraction exceeds 1
    w2, info2 = level_path_weights(Curve([1.0] * 10), 10)
    assert info2["shape"] == "linear" and w2[:5] == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0]) and w2[5:] == [1.0] * 5


def test_the_margin_level_is_drawn_directly_without_a_rescale():
    from valuation.priors import PopulationPriors
    assert not hasattr(PopulationPriors, "_rescale_margin_target")


# ---- Addendum G: debt never tagged ------------------------------------------------------------------------------------------------------------

def test_debt_components_never_tagged_count_as_zero_and_are_stamped():
    pit = fx.make_pit(asof="2026-06-30", drop=("debt_lt_noncurrent", "debt_current"))
    st = build_state(pit)
    assert st["debt"] == 0.0 and "debt" not in " ".join(st["missing"])
    assert any("never tagged" in s and "debt_lt_noncurrent" in s for s in st["read_as_none"])
    assert set(st["debt_components_never_tagged"]) == {"debt_lt_noncurrent", "debt_current", "short_term_borrowings_separate"}


def test_a_debt_line_tagged_in_an_earlier_year_is_not_never_tagged():
    pit = fx.make_pit(asof="2026-06-30", drop=("debt_lt_noncurrent", "debt_current"))
    first = pit.periods()[0]
    pit.series.setdefault("debt_current", {})[first] = Filed(5.0, first, "2017-03-01", "ACC-old", "10-K", "x")
    st = build_state(pit)
    assert st["debt"] is None and any("debt" in m for m in st["missing"])          # the inconsistency stays a refusal, never a zero


def test_a_company_that_files_debt_is_unchanged():
    st = build_state(fx.make_pit(asof="2026-06-30"))
    assert st["debt"] == pytest.approx(320.0) and "debt_components_never_tagged" in st and st["debt_components_never_tagged"] == ["short_term_borrowings_separate"]


# ---- Addendum H3: the industry median return of a date -------------------------------------------------------------------------------------------------

def test_the_date_context_holds_the_industry_median_roic_and_rote_of_the_dates_population():
    rows = ([{"industry": "A", "family": "operating", "roic3": 0.01 * i, "rote3": None} for i in range(1, 26)]                 # 25 in industry A: median 0.13
            + [{"industry": "B", "family": "commodity", "roic3": 0.5, "rote3": None} for _ in range(5)]                    # 5 in B: too thin
            + [{"industry": "C", "family": "financial", "roic3": None, "rote3": 0.02 * i} for i in range(1, 23)]          # 22 financials: median 0.23
            + [{"industry": "A", "family": "operating", "roic3": None, "rote3": None}])                                    # not measurable: not in the median
    ctx = gate1.DateContext.build("2020-06-30", 0.02, rows)
    a = ctx.industry_return("A", "operating")
    assert a == {"value": pytest.approx(0.13), "n": 25, "basis": "industry"}
    b = ctx.industry_return("B", "commodity")                                                                              # too thin: the pooled operating + commodity median, stamped
    assert b["basis"].startswith("pooled") and b["n"] == 30 and b["value"] == pytest.approx(0.155)
    assert ctx.industry_return(None, "operating")["basis"].startswith("pooled")
    c = ctx.industry_return("C", "financial")
    assert c["basis"] == "industry" and c["n"] == 22 and c["value"] == pytest.approx(0.23)                                 # financials never mix with the operating pool
    assert gate1.DateContext.build("2020-06-30", 0.02, []).industry_return("A", "operating") is None


# ---- the adapter -------------------------------------------------------------------------------------------------------------------------------

def _store(tmp_path, cik=1, **kw):
    synth.simple_company(tmp_path / "store", cik, 6, extra={"PropertyPlantAndEquipmentNet": 300.0, "Liabilities": 500.0}, **kw)
    return tmp_path / "store"


def _sic(tmp_path, cik=1, sic="3571", industry="Computers/Peripherals"):
    p = tmp_path / "sic.json"
    p.write_text(json.dumps({"meta": {}, "map": {str(cik).zfill(10): {"sic": sic, "industry": industry}}}), encoding="utf-8")
    return pit_adapter.CurrentSicFile(p)


def test_the_adapter_applies_the_decision_time_and_stamps_the_current_dated_sic(tmp_path):
    pit = pdm.PitData(_store(tmp_path), sic_source=_sic(tmp_path))
    last_filed = "2020-02-29"                                   # FY2019 filed 60 days after 2019-12-31
    r0 = pit_adapter.adapt(pit, 1, "2020-02-01")
    assert r0.ok and r0.company.periods()[-1] == "2018-12-31"
    on_day = pit_adapter.adapt(pit, 1, last_filed)              # a filing on the date with no timestamp is AMBIGUOUS and unused
    assert on_day.ok and on_day.company.periods()[-1] == "2018-12-31"
    nxt = pit_adapter.adapt(pit, 1, "2020-03-01")
    assert nxt.ok and nxt.company.periods()[-1] == "2019-12-31"
    assert "sic_current_dated" in nxt.stamps and "industry_current_dated" in nxt.stamps and nxt.industry == "Computers/Peripherals"
    assert nxt.company.sic.point_in_time is False and nxt.provenance["cells"] > 0
    none = pit_adapter.adapt(pit, 1, "2015-06-30")
    assert not none.ok and none.refusals == ["no_annual_report_at_decision_time"]
    assert not pit_adapter.adapt(pit, 99, "2020-06-30").ok


def test_the_acceptance_timestamp_decides_a_filing_on_the_date(tmp_path):
    store = _store(tmp_path)
    et_after = datetime(2020, 2, 29, 22, 0, tzinfo=timezone.utc)       # 17:00 EST: after the decision time
    et_before = datetime(2020, 2, 29, 20, 0, tzinfo=timezone.utc)      # 15:00 EST
    for t, expect in ((et_after, "2018-12-31"), (et_before, "2019-12-31")):
        pit = pdm.PitData(store, sic_source=_sic(tmp_path), acceptance_source=lambda cik, t=t: {"1-2019": t})
        assert pit_adapter.adapt(pit, 1, "2020-02-29").company.periods()[-1] == expect


def test_the_adapter_refuses_an_input_the_rule_calls_invalid_or_ambiguous(tmp_path):
    pit = pdm.PitData(_store(tmp_path), sic_source=_sic(tmp_path))
    c = pit.company("1")
    obj = pit.company_pit("1", "2020-03-02")
    assert pit_adapter._eligibility_hits(c, "2020-03-02", obj) == {}
    # a value whose accession the rule rejects at an earlier date: filed on the date itself (AMBIGUOUS) and after it (PIT_INVALID)
    obj.series["revenue"]["2019-12-31"] = Filed(1.0, "2019-12-31", "2020-03-02", "x-1", "10-K", "Revenues")
    obj.series["net_income"]["2019-12-31"] = Filed(1.0, "2019-12-31", "2020-04-01", "x-2", "10-K", "NetIncomeLoss")
    hits = pit_adapter._eligibility_hits(c, "2020-03-02", obj)
    assert set(hits) == {"AMBIGUOUS", "PIT_INVALID"} and hits["AMBIGUOUS"][0][1] == "x-1"


def test_a_filer_with_no_dollar_facts_is_refused(tmp_path):
    synth.simple_company(tmp_path / "store", 2, 4)                       # a normal filer for the control
    facts = synth.annual_report("2018-12-31", "2019-03-01", {"Revenues": 100.0, "Assets": 50.0}, unit="EUR")
    synth.write_company(tmp_path / "store", 3, facts)
    pit = pdm.PitData(tmp_path / "store")
    r = pit_adapter.adapt(pit, 3, "2019-06-30")
    assert not r.ok and r.refusals == ["reporting_currency_not_usd"]


# ---- the population context and the discount rate ------------------------------------------------------------------------------------------------

class FakeStore:
    """Stand-in for DamodaranStore: one betas file dated 2019-01-05, one implied ERP."""
    ROWS = [["Industry Name", "Number of firms", "D/E Ratio", "Effective Tax rate", "Unlevered beta corrected for cash"],
            ["Software", "10", "0.20", "10%", "1.20"], ["Steel", "10", "0.60", "10%", "0.90"]]

    def beta_snapshots(self):
        return [{"file": "fake_betas.xls", "date": pdm.to_date("2019-01-05"), "_rows": self.ROWS}]

    def beta_provider(self):
        return lambda asof, industry: (1.2 if industry == "Software" else 0.9, "fake beta", {"file_sha256": "x"})

    def levered_beta_provider(self):
        return lambda asof, industry: (1.5 if industry == "Software" else 1.1, "fake levered beta", {"file_sha256": "x"})

    def erp_provider(self):
        return lambda asof: (0.05, "fake erp", {"file_sha256": "y"})


def _rates(rf=0.02):
    return gate1.Rates(FakeStore(), {"2019-12-31": (rf, "fake rf")})


def test_the_context_uses_the_industry_cross_section_when_it_has_enough_names_else_the_pooled_one():
    rows = [{"industry": "Software", "de_book": 0.1 * i, "kd_effective": 0.05 + 0.001 * i} for i in range(1, 31)]
    rows += [{"industry": "Steel", "de_book": 1.0, "kd_effective": 0.08} for _ in range(3)]
    ctx = gate1.DateContext.build("2019-12-31", 0.02, rows)
    thr, n, how = ctx.de_threshold("Software")
    assert how == "industry" and n == 30 and thr == pytest.approx(0.1 * (1 + 0.95 * 29))
    thr2, n2, how2 = ctx.de_threshold("Steel")                           # three names: pooled
    assert how2 == "pooled" and n2 == 33
    sp, nsp, how_sp = ctx.kd_spread("Software")
    assert how_sp == "industry" and sp == pytest.approx(sorted(r["kd_effective"] - 0.02 for r in rows[:30])[14] / 2 + sorted(r["kd_effective"] - 0.02 for r in rows[:30])[15] / 2)
    assert ctx.kd_spread("Nothing")[2] == "pooled"


def _state(de_book, kd, equity=100.0, tax=0.2):
    return {"de_book": de_book, "kd_effective": kd, "equity": equity, "tax_rate": tax}


def _ctx():
    rows = [{"industry": "Software", "de_book": 0.05 * i, "kd_effective": 0.05} for i in range(1, 41)]      # P95 about 1.9
    return gate1.DateContext.build("2019-12-31", 0.02, rows)


def test_book_de_is_used_unless_equity_is_not_positive_or_de_exceeds_the_industry_p95():
    ctx, rates = _ctx(), _rates()
    d, stamps = gate1.make_discount(_state(0.5, 0.06), "2019-12-31", "operating", "Software", ctx, rates)
    assert d.de_basis == "book" and d.de_ratio == 0.5 and stamps == []
    assert d.beta_levered == pytest.approx(1.2 * (1 + 0.8 * 0.5)) and d.coe == pytest.approx(0.02 + d.beta_levered * 0.05)
    d, stamps = gate1.make_discount(_state(5.0, 0.06), "2019-12-31", "operating", "Software", ctx, rates)         # above the 95th percentile
    assert d.de_basis == "industry_damodaran" and d.de_ratio == pytest.approx(0.20) and "de_industry" in stamps[0]
    d, stamps = gate1.make_discount(_state(None, 0.06, equity=-3.0), "2019-12-31", "operating", "Software", ctx, rates)   # parent equity not positive
    assert d.de_basis == "industry_damodaran" and "equity not positive" in stamps[0]


def test_a_company_with_debt_and_no_interest_line_takes_riskfree_plus_the_population_spread():
    ctx, rates = _ctx(), _rates()
    d, stamps = gate1.make_discount(_state(0.5, None), "2019-12-31", "operating", "Software", ctx, rates)
    assert d.kd_pretax == pytest.approx(0.02 + 0.03) and any(s.startswith("kd_population_spread") for s in stamps)
    d0, s0 = gate1.make_discount(_state(0.0, None), "2019-12-31", "operating", "Software", ctx, rates)            # no debt: no cost of debt needed
    assert d0.wacc == d0.coe and s0 == []


def test_missing_industry_or_industry_not_in_the_file_is_a_refusal_not_a_default():
    ctx, rates = _ctx(), _rates()
    with pytest.raises(DataNotPresent, match="industry_unmapped"):
        gate1.make_discount(_state(0.5, 0.06), "2019-12-31", "operating", None, ctx, rates)
    with pytest.raises(DataNotPresent):
        gate1.make_discount(_state(0.5, 0.06), "2019-12-31", "operating", "Not an industry", ctx, rates)
    with pytest.raises(DataNotPresent, match="negative"):
        gate1.make_discount(_state(-0.1, 0.06), "2019-12-31", "operating", "Software", ctx, rates)


def test_the_financial_family_takes_the_industrys_levered_beta_as_is_with_no_hamada_step():
    """Addendum I3: coe = rf + the industry's LEVERED beta x ERP; the company's own D/E (and the tax rate) do not move it; an operating company still relevers."""
    ctx, rates = _ctx(), _rates()
    a, sa = gate1.make_discount(_state(0.3, 0.06), "2019-12-31", "financial", "Software", ctx, rates)
    b, sb = gate1.make_discount(_state(2.0, 0.06, tax=0.3), "2019-12-31", "financial", "Software", ctx, rates)
    assert a.beta_levered == b.beta_levered == 1.5 and a.beta_unlevered is None
    assert a.coe == b.coe == pytest.approx(0.02 + 1.5 * 0.05)
    assert any(s.startswith("coe_levered_industry_beta") for s in sa) and any("LEVERED" in w for w in a.warnings)
    o, _ = gate1.make_discount(_state(0.3, 0.06), "2019-12-31", "operating", "Software", ctx, rates)
    assert o.beta_unlevered == 1.2 and o.beta_levered == pytest.approx(1.2 * (1 + 0.8 * 0.3))


def test_the_financial_engine_does_not_need_a_cost_of_debt():
    ctx = gate1.DateContext.build("2019-12-31", 0.02, [])
    d, stamps = gate1.make_discount(_state(0.5, None), "2019-12-31", "financial", "Software", ctx, _rates())
    assert d.kd_pretax == 0.02 and any("not_used_by_the_financial_engine" in s for s in stamps)
    with pytest.raises(DataNotPresent):
        gate1.make_discount(_state(0.5, None), "2019-12-31", "operating", "Software", ctx, _rates())


# ---- one company end to end (synthetic; PLACEHOLDER priors, so nothing here is a valuation) ----------------------------------------------------------

def test_a_company_is_valued_per_share_and_every_record_field_is_present(tmp_path):
    pit = pdm.PitData(_store(tmp_path, base_rev=1000.0, growth=0.05), sic_source=_sic(tmp_path))
    ad = pit_adapter.adapt(pit, 1, "2020-06-30")
    prep = gate1.prepare(ad)
    assert prep["status"] == "prepared" and prep["family"] == "operating" and prep["blob"]
    ctx = gate1.DateContext.build("2020-06-30", 0.02, [{"industry": "Software", "family": "operating", "de_book": 0.1 * i, "kd_effective": 0.06, "roic3": 0.01 * i}
                                                       for i in range(1, 31)])
    rates = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")})
    priors = PlaceholderPriors(True)
    v1 = gate1.value_company(dict(prep, industry="Software"), ctx, priors, rates, shares=50.0, n_draws=300)
    v2 = gate1.value_company(dict(prep, industry="Software"), ctx, priors, rates, shares=50.0, n_draws=300)
    assert v1["status"] == "ok" and any(x.startswith("kd_population_spread") for x in v1["stamps"]) and v1 == v2                                           # deterministic: the seed is per company and date
    assert v1["iv_ps"]["p10"] <= v1["iv_ps"]["p50"] <= v1["iv_ps"]["p90"]
    assert any(x.startswith("industry_median_return: industry, n=30") for x in v1["stamps"])               # Addendum H3: the date's industry median ROIC
    assert v1["terminal_growth"]["base"] == 0.02                                                              # Addendum H2: min(rf 2%, 3.75%)
    v100 = gate1.value_company(dict(prep, industry="Software"), ctx, priors, rates, shares=100.0, n_draws=300)
    assert v100["iv_ps"]["p50"] == pytest.approx(v1["iv_ps"]["p50"] / 2)               # per share: equity / shares
    assert v1["discount"]["de_basis"] == "book" and v1["discount_sources"]["beta_file_sha256"] == "x"
    assert gate1.seed_for("0000000001", "2020-06-30") != gate1.seed_for("0000000002", "2020-06-30")
    nov = gate1.value_company(dict(prep, industry=None), ctx, priors, rates, shares=50.0, n_draws=50)
    assert nov["status"] == "refused" and nov["reasons"][0].startswith("discount_rate: industry_unmapped")


def test_family_not_built_and_refusals_are_named_not_dropped(tmp_path):
    pit = pdm.PitData(_store(tmp_path), sic_source=_sic(tmp_path, sic="6798"))
    prep = gate1.prepare(pit_adapter.adapt(pit, 1, "2020-06-30"))
    assert prep["status"] == "family_not_built" and "reit" in prep["reasons"][0]
    assert gate1.prepare(pit_adapter.adapt(pit, 1, "2010-01-01"))["status"] == "refused"


# ---- the holdout lock of the gate-1 run ---------------------------------------------------------------------------------------------------------

def test_the_gate1_run_refuses_a_holdout_date_before_opening_any_data(tmp_path):
    from rebuild_harness import gate1_run, holdout
    with pytest.raises(holdout.HoldoutRefused):
        gate1_run.main(["--out-dir", str(tmp_path / "out"), "--dates", "2022-12-31", "2023-03-31", "--store", str(tmp_path / "nope"),
                        "--id-map", str(tmp_path / "nope.json")])
    assert not (tmp_path / "out").exists()                                   # nothing was created: the lock answers first
    dates = gate1_run.dev_dates()
    assert len(dates) == 16 and dates[0] == "2019-03-31" and dates[-1] == "2022-12-31" and not holdout.touches_holdout(dates)         # Addendum H6
    assert [d for d in dates if d <= "2021-12-31"] == dates[:12] and dates[12:] == ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]
    with pytest.raises(holdout.HoldoutRefused):                               # also with a freeze file that does not name this engine
        freeze = tmp_path / "freeze.json"
        freeze.write_text(json.dumps({"engines": {}}), encoding="utf-8")
        gate1_run.main(["--out-dir", str(tmp_path / "out2"), "--dates", "2024-12-31", "--freeze", str(freeze)])


# ---- Addendum H5: a name with more than 5% invalid draws is refused ----------------------------------------------------------------------------------

def test_invalid_draw_refusal_threshold_and_named_reasons():
    ok = {"n_draws": 2000, "n_invalid": 100, "invalid_reasons": {"x": 100}}               # exactly 5%: not over
    assert gate1.invalid_draw_refusal(ok) is None
    over = {"n_draws": 2000, "n_invalid": 101, "invalid_reasons": {"return on new capital not positive": 90, "terminal growth is not below the discount rate": 11}}
    r = gate1.invalid_draw_refusal(over)
    assert r.startswith("invalid_draws_over_5%: 5.1% of 2000 draws") and "return on new capital not positive x90" in r and r.index("x90") < r.index("x11")
    assert gate1.invalid_draw_refusal({"n_draws": 0, "n_invalid": 0}) is None


class _WideRonicPriors(PlaceholderPriors):
    """Placeholder priors whose ROIC level five years on is negative for a fifth of the draws: those draws cannot price the growth they carry."""

    def __init__(self, lo):
        super().__init__(True)
        self.lo = lo

    def for_company(self, family, state, asof):
        ps = super().for_company(family, state, asof)
        ps.inputs["ronic"] = QuantileDist({0.10: self.lo, 0.50: 0.12, 0.90: 0.20}, "test")
        return ps


def test_a_name_with_too_many_invalid_draws_is_refused_with_the_reason_and_the_counts_are_kept(tmp_path):
    pit = pdm.PitData(_store(tmp_path, base_rev=1000.0, growth=0.05), sic_source=_sic(tmp_path))
    prep = gate1.prepare(pit_adapter.adapt(pit, 1, "2020-06-30"))
    rows = [{"industry": "Software", "family": "operating", "de_book": 0.1 * i, "kd_effective": 0.06, "roic3": 0.01 * i} for i in range(1, 31)]
    ctx = gate1.DateContext.build("2020-06-30", 0.02, rows)
    rates = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")})
    bad = gate1.value_company(dict(prep, industry="Software"), ctx, _WideRonicPriors(-0.6), rates, shares=50.0, n_draws=400)
    assert bad["status"] == "refused" and bad["reasons"][0].startswith("invalid_draws_over_5%") and "return on new capital not positive" in bad["reasons"][0]
    assert bad["n_draws"] == 400 and sum(bad["invalid_reasons"].values()) == 400 - bad["n_valid"] and bad["n_valid"] < 400 * 0.95
    fine = gate1.value_company(dict(prep, industry="Software"), ctx, _WideRonicPriors(0.04), rates, shares=50.0, n_draws=400)
    assert fine["status"] == "ok" and fine["n_valid"] >= 0.95 * 400 and sum(fine["invalid_reasons"].values()) == 400 - fine["n_valid"]       # the tail below P10 is a few draws: inside the 5%



def test_no_price_outcome_is_formed_past_the_end_of_2022():
    from datetime import date
    from rebuild_harness import gate1_run as g
    assert g.months_after("2021-12-31", 12) == date(2022, 12, 1) <= g.OUTCOMES_END and g.months_after("2022-03-31", 12) > g.OUTCOMES_END
    assert [h for h in g.HORIZONS if g.months_after("2022-06-30", h) <= g.OUTCOMES_END] == [3, 6]
    assert [h for h in g.HORIZONS if g.months_after("2019-03-31", h) <= g.OUTCOMES_END] == [3, 6, 12, 24, 36]
    assert [h for h in g.HORIZONS if g.months_after("2021-12-31", h) <= g.OUTCOMES_END] == [3, 6, 12]
