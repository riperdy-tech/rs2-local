"""Tests of the T-integrate pieces: the adapter (decision-time refusals, stamps), the Addendum F 4 margin_target rescale, the Addendum G debt rule, the
population context and the discount rate of a company (Addendum B 3 and 5), the holdout lock of the gate-1 run, and one company end to end on synthetic data.
Synthetic data only: no network, no archive, no model."""
import json
from datetime import datetime, timezone

import pytest

from valuation import gate1, pit_adapter
from valuation import pit_data as pdm
from valuation.common import Curve, DataNotPresent, Filed, QuantileDist, build_state
from valuation.priors import MARGIN_RESCALE_CAP, PopulationPriors
from valuation.priors_interface import PlaceholderPriors
from valuation.tests import synth
from valuation.muse.tests import fixtures as fx


# ---- Addendum F 4: the margin_target spread ----------------------------------------------------------------------------------------------------

def _qd():
    return QuantileDist({0.05: -0.10, 0.10: -0.05, 0.25: -0.02, 0.50: 0.0, 0.75: 0.03, 0.90: 0.06, 0.95: 0.09}, "t")


def _rescale(r5, family="operating"):
    inputs, meta = {"margin_target": _qd()}, {}
    curve = Curve([1.0, 0.9, 0.85, 0.8, r5, r5, r5, r5, r5, r5], "margin_retention")
    PopulationPriors._rescale_margin_target(family, inputs, {"margin_retention": curve, "growth_decay": curve}, {}, meta, None)
    return inputs["margin_target"], meta["margin_target_rescale"], curve


def test_rescale_makes_the_engines_year_5_margin_spread_equal_the_measured_one():
    qd, info, curve = _rescale(0.75)
    assert info["factor"] == pytest.approx(4.0) and not info["capped"]
    raw = _qd()
    m0 = 0.15
    r5 = curve.at(5)
    for p in (0.10, 0.25, 0.75, 0.90):
        # the engine's year-5 margin is (1 - r5) m_T + r5 m_0: its deviation from the median path is (1 - r5) times the deviation of m_T
        dev_engine = (1 - r5) * (qd.ppf(p) - qd.ppf(0.5))
        assert dev_engine == pytest.approx(raw.ppf(p) - raw.ppf(0.5))
    assert info["implied_year5_margin_width"] == pytest.approx(raw.ppf(0.9) - raw.ppf(0.1))
    assert qd.ppf(0.5) == raw.ppf(0.5)                                  # the pivot is the median: the centre does not move
    assert info["stamp"].startswith("Addendum F 4")


def test_rescale_is_capped_at_ten_when_the_retention_is_at_or_above_0_9():
    qd, info, _ = _rescale(0.95)
    assert info["factor"] == MARGIN_RESCALE_CAP == 10.0 and info["capped"]
    assert qd.ppf(0.9) - qd.ppf(0.5) == pytest.approx(10 * (_qd().ppf(0.9) - _qd().ppf(0.5)))
    qd9, info9, _ = _rescale(0.9)
    assert info9["factor"] == pytest.approx(10.0) and not info9["capped"]
    qd0, info0, _ = _rescale(0.0)
    assert info0["factor"] == pytest.approx(1.0)


def test_rescale_reports_the_implied_terminal_year_spread():
    _, info, curve = _rescale(0.6)
    rN = curve.at(len(curve))
    assert info["r_terminal"] == rN
    assert info["implied_terminal_year_margin_width"] == pytest.approx((1 - rN) * info["p10_p90_width_of_m_T_after_rescale"])


def test_the_rescale_can_be_switched_off(tmp_path):
    pp = PopulationPriors(tmp_path, rescale_margin_target=False)
    assert pp.rescale_margin_target is False and PopulationPriors(tmp_path).rescale_margin_target is True


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
    ctx = gate1.DateContext.build("2020-06-30", 0.02, [{"industry": "Software", "de_book": 0.1 * i, "kd_effective": 0.06} for i in range(1, 31)])
    rates = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")})
    priors = PlaceholderPriors(True)
    v1 = gate1.value_company(dict(prep, industry="Software"), ctx, priors, rates, shares=50.0, n_draws=300)
    v2 = gate1.value_company(dict(prep, industry="Software"), ctx, priors, rates, shares=50.0, n_draws=300)
    assert v1["status"] == "ok" and any(x.startswith("kd_population_spread") for x in v1["stamps"]) and v1 == v2                                           # deterministic: the seed is per company and date
    assert v1["iv_ps"]["p10"] <= v1["iv_ps"]["p50"] <= v1["iv_ps"]["p90"]
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
    assert len(dates) == 24 and dates[0] == "2017-03-31" and dates[-1] == "2022-12-31" and not holdout.touches_holdout(dates)
    with pytest.raises(holdout.HoldoutRefused):                               # also with a freeze file that does not name this engine
        freeze = tmp_path / "freeze.json"
        freeze.write_text(json.dumps({"engines": {}}), encoding="utf-8")
        gate1_run.main(["--out-dir", str(tmp_path / "out2"), "--dates", "2024-12-31", "--freeze", str(freeze)])
