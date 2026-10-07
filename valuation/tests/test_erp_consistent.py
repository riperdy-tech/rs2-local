"""Tests of the engine-consistent equity risk premium (Addenda L1, M option B): the reproduced index model, the differential, the engine growth, the cap weighting, the monthly row, the Rates default
and one company's growth path against the engine's own year-1 growth.  Synthetic numbers except the one reproduction check on Damodaran's file (skipped where the approved files are absent)."""
import hashlib
import json
from datetime import date, datetime

import pytest

from valuation import discount_rate as dr
from valuation import erp_consistent as ec
from valuation import gate1, pit_adapter
from valuation import pit_data as pdm
from valuation.common import Curve, DataNotPresent, InputError
from valuation.priors_interface import PlaceholderPriors
from valuation.tests.test_gate1 import FakeStore, _sic, _store


# ---- the reproduced index model ---------------------------------------------------------------------------------------------------------------------

def _index_level(r, cf0, g, rf, n=5):
    """The S that the model makes of a required return r (the inverse of the solve)."""
    return ec.model_value(r, 0.0, cf0, g, rf, n)


def test_the_solve_inverts_the_model():
    for r, g, rf in ((0.08, 0.05, 0.02), (0.065, 0.10, 0.015), (0.05, 0.02, 0.04), (0.12, 0.0, 0.03)):
        S = _index_level(r, 100.0, g, rf)
        assert ec.required_return(S, 100.0, g, rf) == pytest.approx(r, abs=1e-10)


def test_the_value_falls_with_the_required_return_and_the_model_is_the_five_year_plus_perpetuity_form():
    cf, g, rf, r = 100.0, 0.05, 0.02, 0.08
    by_hand = sum(cf * (1 + g) ** t / (1 + r) ** t for t in range(1, 6)) + cf * (1 + g) ** 5 * (1 + rf) / (r - rf) / (1 + r) ** 5
    assert ec.model_value(r, 0.0, cf, g, rf) == pytest.approx(by_hand)
    assert ec.model_value(0.07, 0.0, cf, g, rf) > ec.model_value(0.09, 0.0, cf, g, rf)


def test_inputs_that_define_no_root_are_a_refusal_naming_them_not_a_guess():
    with pytest.raises(DataNotPresent, match="positive"):
        ec.required_return(1000.0, -5.0, 0.05, 0.02)
    with pytest.raises(DataNotPresent, match="needs g"):
        ec.required_return(1000.0, 50.0, None, 0.02)
    with pytest.raises(DataNotPresent, match="no root"):
        ec.required_return(1e-6, 50.0, 0.05, 0.02)             # an index level no required return can be as low as
    with pytest.raises(DataNotPresent, match="no root"):
        ec.required_return(1e12, 50.0, 0.05, 0.02)


# ---- the differential -------------------------------------------------------------------------------------------------------------------------------

def _row(erp=0.045, g=0.09, S=4000.0, cf=120.0, rf=0.015, d=date(2021, 6, 1)):
    return {"date": d, "erp": erp, "index": S, "tbond": rf, "cf_t12": cf, "growth": g, "file": "implprem_ERPbymonth.xlsx", "file_sha256": "abc"}


def test_delta_is_zero_when_the_engine_growth_equals_damodarans_and_the_premium_is_then_his():
    c = ec.consistent_erp("2021-06-30", _row(), 0.09)
    assert c.delta == pytest.approx(0.0, abs=1e-12) and c.erp == pytest.approx(0.045)


def test_a_lower_engine_growth_lowers_the_required_return_and_the_premium_by_the_solved_difference():
    row = _row()
    c = ec.consistent_erp("2021-06-30", row, 0.03)
    r_d = ec.required_return(row["index"], row["cf_t12"], row["growth"], row["tbond"])
    r_e = ec.required_return(row["index"], row["cf_t12"], 0.03, row["tbond"])
    assert c.delta == pytest.approx(r_e - r_d) and c.delta < 0
    assert c.erp == pytest.approx(row["erp"] + (r_e - r_d))                      # published ERP + delta, exactly
    assert c.required_return_damodaran_growth == pytest.approx(r_d) and c.required_return_engine_growth == pytest.approx(r_e)
    assert ec.consistent_erp("2021-06-30", row, 0.12).delta > 0                    # a higher growth raises it
    assert "5-year growth 9.00% -> engine 3.00%" in c.label() and c.meta()["source"] == "engine_consistent" and c.meta()["file_sha256"] == "abc"


def test_the_reproduction_error_cancels_in_the_differential():
    """The reproduced model's level may be off the published premium; delta does not depend on that level: it is a function of (S, CF0, rf, g's) only, so the same delta is added to any published value."""
    row = _row()
    a = ec.consistent_erp("2021-06-30", dict(row, erp=0.040), 0.03)
    b = ec.consistent_erp("2021-06-30", dict(row, erp=0.055), 0.03)
    assert a.delta == b.delta and b.erp - a.erp == pytest.approx(0.015)


def test_a_result_outside_a_plausible_premium_is_a_refusal_never_clipped():
    with pytest.raises(DataNotPresent, match="not a plausible"):
        ec.consistent_erp("2021-06-30", _row(erp=0.005), 0.0)                      # his premium is small and the engine growth much lower: the sum is not positive
    with pytest.raises(DataNotPresent, match="no engine growth"):
        ec.consistent_erp("2021-06-30", _row(), float("nan"))


# ---- the engine's growth path and its cap weighting --------------------------------------------------------------------------------------------------

def test_the_growth_path_is_the_engines_chain_for_years_1_to_5():
    curve = Curve([1.0, 0.8, 0.6, 0.4, 0.2, 0.1, 0.0, 0.0, 0.0, 0.0], "growth_decay")
    path = ec.growth_path(0.12, 0.02, curve)
    assert path == pytest.approx([0.02 + 0.10 * d for d in (1.0, 0.8, 0.6, 0.4, 0.2)])
    assert ec.mean_growth(path) == pytest.approx(0.02 + 0.10 * 0.6)


def test_a_short_curve_continues_at_the_engines_perpetuity_rate_and_a_negative_rate_continues():
    short = Curve([1.0, 0.5, 0.0], "growth_decay")
    p = ec.growth_path(0.10, 0.03, short)
    assert p == pytest.approx([0.10, 0.065, 0.03, 0.03, 0.03])                       # after year 3: g_T
    neg = ec.growth_path(-0.05, 0.03, Curve([1.0, 1.0, 1.0], "growth_decay"))
    assert neg == pytest.approx([-0.05] * 5)                                           # a negative last explicit rate continues (terminal_growth_after)
    with pytest.raises(InputError):
        ec.mean_growth([])


def test_cap_weighting_is_the_market_cap_weighted_mean_and_drops_what_has_no_cap_or_growth():
    out = ec.cap_weighted([(300.0, 0.10), (100.0, 0.02), (None, 0.5), (50.0, None), (0.0, 0.9), (-5.0, 0.9), (float("nan"), 0.1)])
    assert out["n"] == 2 and out["total_cap"] == 400.0 and out["value"] == pytest.approx((300 * 0.10 + 100 * 0.02) / 400)
    with pytest.raises(DataNotPresent):
        ec.cap_weighted([(None, 0.1)])
    big = ec.cap_weighted([(1e12, 0.01), (1e9, 0.30)])
    assert big["value"] < 0.011                                                         # a cap-weighted mean, not a median or a plain mean


# ---- Damodaran's monthly row ---------------------------------------------------------------------------------------------------------------------------

HDR = ["Start of month", "S&P 500", "T.Bond Rate", "$ Riskfree Rate", "Ten-year average CF", "CF (Trailing 12 month)", "Normalized CF", "Expected growth rate",
       "ERP (T12 m with sustainable payout)", "ERP (T12m)", "Notes"]


def _rows():
    return [HDR,
            [datetime(2008, 9, 1), 1252, 0.0372, None, None, None, None, None, None, 0.0422, None],               # before the column
            [datetime(2021, 4, 1), 3973, 0.0175, None, 99, 118.65, 100, 0.0876, 0.0422, 0.0414, None],
            [datetime(2021, 5, 1), 4182, 0.0163, None, 99, 118.65, 100, 0.0897, 0.0407, 0.0399, None],
            [datetime(2021, 6, 1), 4204, 0.0158, None, 99, 118.65, 100, 0.0969, 0.0420, 0.0410, None],
            [datetime(2021, 7, 1), 4298, 0.0147, None, 99, None, 100, 0.0979, 0.0431, 0.0396, None],                # no cash flow in the row
            [datetime(2021, 8, 1), 4395, 0.0123, None, 99, 116.17, 100, 0.0977, None, 0.0391, None],               # no published ERP: not a row of the series
            ["not a date", 1, 1, None, None, None, None, None, 0.04, None, None]]


def _store_with_rows(tmp_path, rows):
    f = tmp_path / dr.ERP_MONTHLY_FILE
    f.write_bytes(b"synthetic monthly file")
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"files": {dr.ERP_MONTHLY_FILE: {"sha256": hashlib.sha256(f.read_bytes()).hexdigest()}}}), encoding="utf-8")
    return dr.DamodaranStore(tmp_path, reader=lambda path, sheet=None: rows)


def test_the_model_row_is_the_row_the_erp_provider_uses_with_the_inputs_of_that_row(tmp_path):
    st = _store_with_rows(tmp_path, _rows())
    row = st.monthly_model_row("2021-06-30")
    erp, label, meta = st.erp_provider()("2021-06-30")
    assert row["date"] == date(2021, 6, 1) and row["erp"] == erp == 0.0420 and meta["row_date"] == "2021-06-01"
    assert (row["index"], row["tbond"], row["cf_t12"], row["growth"]) == (4204.0, 0.0158, 118.65, 0.0969) and row["file_sha256"] == meta["file_sha256"]
    assert st.monthly_model_row("2021-05-31")["date"] == date(2021, 5, 1)                              # on or before the date: the 2021-06-01 row is not used for 05-31


def test_a_row_without_a_model_input_is_a_refusal_not_an_earlier_row(tmp_path):
    st = _store_with_rows(tmp_path, _rows())
    with pytest.raises(DataNotPresent, match="cf_t12"):
        st.monthly_model_row("2021-07-31")
    with pytest.raises(DataNotPresent, match="stale"):
        st.monthly_model_row("2021-09-30")                              # newest row with a published ERP is 2021-07-01: 91 days
    with pytest.raises(DataNotPresent, match="no monthly ERP row"):
        st.monthly_model_row("2008-12-31")


def test_the_parser_refuses_an_implausible_published_premium_and_a_sheet_without_the_columns():
    bad = [HDR, [datetime(2021, 6, 1), 4204, 0.0158, None, 99, 118.65, 100, 0.0969, 0.9, 0.0410, None]]
    with pytest.raises(DataNotPresent, match="plausible"):
        dr.parse_erp_model_rows(bad)
    with pytest.raises(DataNotPresent, match="no column"):
        dr.parse_erp_model_rows([["Start of month", "S&P 500"], [datetime(2021, 6, 1), 1]])


# ---- Rates: the default premium ---------------------------------------------------------------------------------------------------------------------------

def _consistent(asof="2020-06-30", erp=0.031):
    return ec.ConsistentErp(asof=asof, row_date="2020-06-01", damodaran_erp=0.04, delta=erp - 0.04, erp=erp, engine_growth=0.02, damodaran_growth=0.05,
                            required_return_damodaran_growth=0.05, required_return_engine_growth=0.04, index_level=3000.0, cf_t12=130.0, rf_row=0.01, file="f.xlsx", file_sha256="z")


def test_the_default_premium_is_the_engine_consistent_one_and_is_never_replaced_silently_by_damodarans():
    rates = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")})
    assert rates.erp_basis == "engine_consistent"
    with pytest.raises(DataNotPresent, match="no engine-consistent ERP"):
        rates.erp("2020-06-30")
    rates.set_consistent_erp("2020-06-30", _consistent())
    v, label, meta = rates.erp("2020-06-30")
    assert v == 0.031 and label.startswith(ec.CONSISTENT_LABEL) and meta["source"] == "engine_consistent" and meta["file_sha256"] == "z"
    assert rates.erp_damodaran("2020-06-30")[0] == 0.05                       # his own stays available as the sensitivity
    with pytest.raises(DataNotPresent):
        rates.erp("2020-07-31")                                               # another date has none


def test_the_damodaran_basis_is_his_and_an_unknown_basis_is_refused():
    r = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")}, erp_basis="damodaran")
    assert r.erp("2020-06-30")[0] == 0.05
    with pytest.raises(InputError):
        gate1.Rates(FakeStore(), {}, erp_basis="closure")


def test_the_run_wrappers_shift_and_swap_the_premium_over_the_default():
    from rebuild_harness import gate1_run as g
    rates = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")})
    rates.set_consistent_erp("2020-06-30", _consistent())
    assert g.ShiftedErp(rates, 0.01).erp("2020-06-30")[0] == pytest.approx(0.041)
    assert g.DamodaranErp(rates).erp("2020-06-30")[0] == 0.05 and g.DamodaranErp(rates).rf("2020-06-30")[0] == 0.02
    assert g.ERP_BASIS == "engine_consistent" and g.frozen_config()["erp_basis"] == "engine_consistent" and g.frozen_config()["erp_model_years"] == 5
    assert any(p.name == "erp_consistent.py" for p in g.GATE1_FILES)               # the premium is part of the frozen engine's identity


# ---- one company's growth path against the engine ------------------------------------------------------------------------------------------------------

def test_the_growth_path_of_a_prepared_company_is_the_engines_own_year_1_growth_and_does_not_depend_on_the_premium(tmp_path):
    pit = pdm.PitData(_store(tmp_path, base_rev=1000.0, growth=0.05), sic_source=_sic(tmp_path))
    prep = dict(gate1.prepare(pit_adapter.adapt(pit, 1, "2020-06-30")), industry="Software")
    ctx = gate1.DateContext.build("2020-06-30", 0.02, [{"industry": "Software", "family": "operating", "de_book": 0.1 * i, "kd_effective": 0.06, "roic3": 0.01 * i} for i in range(1, 31)])
    priors = PlaceholderPriors(True)
    g = gate1.engine_growth_p50(prep, ctx, priors, 0.02)
    assert g["status"] == "ok" and len(g["path"]) == 5 and g["mean"] == pytest.approx(sum(g["path"]) / 5) and g["g_term"] == 0.02
    for erp in (0.03, 0.06):                                                 # the engine's year-1 growth at the median inputs is the path's first year, whatever the premium
        rates = gate1.Rates(FakeStore(), {"2020-06-30": (0.02, "fake rf")}, erp_basis="damodaran")
        rates._erp = lambda asof, e=erp: (e, "t", {"file_sha256": "y"})
        v = gate1.value_company(prep, ctx, priors, rates, shares=50.0, n_draws=100)
        assert v["status"] == "ok" and v["forecast"]["year1_growth_point"] == pytest.approx(g["path"][0])
    assert g == gate1.engine_growth_p50(prep, ctx, priors, 0.02)              # deterministic
    un = gate1.engine_growth_p50(prep, ctx, type("P", (), {"for_company": lambda self, f, s, a: type("S", (), {"source": "UNAVAILABLE", "inputs": {}, "curves": {}})()})(), 0.02)
    assert un == {"status": "unavailable", "reason": "priors_unavailable"}


# ---- the reproduction on Damodaran's own file (the check of round 5) ---------------------------------------------------------------------------------------

def test_the_reproduced_model_matches_his_plain_t12_premium_where_his_file_is_present():
    try:
        st = dr.DamodaranStore()
        rows = st._reader(st.root / dr.ERP_MONTHLY_FILE, dr.ERP_MONTHLY_SHEET)
    except DataNotPresent:
        pytest.skip("the approved Damodaran files are not on this machine")
    hdr = next(r for r in rows if r and dr._norm(r[0]) == "start of month")
    cols = {dr._norm(c): i for i, c in enumerate(hdr)}
    errs = []
    for r in rows:
        if not r or not isinstance(r[0], datetime) or r[0].year < 2016:
            continue
        S, rf, cf, g, plain = (dr._num(r[cols[k]]) for k in ("s&p 500", "t.bond rate", "cf (trailing 12 month)", "expected growth rate", "erp (t12m)"))
        if None in (S, rf, cf, g, plain):
            continue
        errs.append((ec.required_return(S, cf, g, rf) - rf - plain) * 1e4)
    assert len(errs) > 100
    ae = sorted(abs(e) for e in errs)
    signed = sorted(errs)
    assert abs(signed[len(signed) // 2]) < 1.0                                 # round 5's check: the median signed error against his plain trailing-12-month premium is -0.3 bp
    assert sum(1 for e in ae if e <= 5.0) / len(ae) > 0.5                      # ... 53% of the months within 5 bp (his index level is rounded to an integer in the row)
    assert ae[-1] < 200.0                                                      # the worst month (a slip in his March 2026 row) is the check's own 177 bp


# ---- the run's date step -----------------------------------------------------------------------------------------------------------------------------

class _ModelStore(FakeStore):
    def monthly_model_row(self, asof):
        return _row(d=date(2020, 6, 1))


def test_the_date_step_weights_the_gate_universe_by_market_cap_and_sets_the_premium_on_the_rates(tmp_path):
    from rebuild_harness import gate1_run as g
    store = _store(tmp_path, cik=1, base_rev=1000.0, growth=0.05)
    _store(tmp_path, cik=2, base_rev=1000.0, growth=0.20)
    sic = _sic(tmp_path)
    pit = pdm.PitData(store, sic_source=sic)
    ctx = gate1.DateContext.build("2020-06-30", 0.02, [{"industry": "Software", "family": "operating", "de_book": 0.1 * i, "kd_effective": 0.06, "roic3": 0.01 * i} for i in range(1, 31)])
    priors = PlaceholderPriors(True)
    preps, recs = {}, []
    for cik, mcap, status in (("0000000001", 900e6, "prepared"), ("0000000002", 300e6, "prepared"), ("0000000003", 100e6, "prepared"), ("0000000004", 5e9, "refused"), ("0000000005", None, "prepared")):
        recs.append({"cik": cik, "status": status, "market_cap": mcap, "family": "operating"})
    for cik in ("0000000001", "0000000002"):
        preps[cik] = dict(gate1.prepare(pit_adapter.adapt(pit, int(cik), "2020-06-30")), industry="Software")
    preps["0000000003"] = preps["0000000001"]              # below the floor: never read
    rates = gate1.Rates(_ModelStore(), {"2020-06-30": (0.02, "fake rf")})
    ce, uni = g.l1_date("2020-06-30", recs, preps, ctx, priors, rates, 0.02)
    gs = {c: gate1.engine_growth_p50(preps[c], ctx, priors, 0.02)["mean"] for c in ("0000000001", "0000000002")}
    assert gs["0000000001"] != gs["0000000002"]
    assert uni["n"] == 2 and uni["total_cap"] == 1200e6                                                    # the below-floor, the refused and the capless names are not in the universe
    assert ce.engine_growth == pytest.approx((900e6 * gs["0000000001"] + 300e6 * gs["0000000002"]) / 1200e6)
    assert rates.consistent("2020-06-30") is ce and rates.erp("2020-06-30")[0] == ce.erp and ce.erp == pytest.approx(0.045 + ce.delta)
    assert recs[0]["engine_growth_p50_mean_y1_5"] == pytest.approx(gs["0000000001"]) and "engine_growth_p50_mean_y1_5" not in recs[2]
    assert uni["by_family"]["operating"]["n"] == 2 and uni["rule"].startswith("prepared")
