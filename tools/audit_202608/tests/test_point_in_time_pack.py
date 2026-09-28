"""Phase 4 E4.3 (time-travel trial) — point-in-time (`asof`) pack mode.

Proves, per input class, that no row dated after `asof` reaches the pack: fundamentals (annual
and quarterly cutoffs, the fiscal-year-end derivation), the macro/regime/shock accessors (via
fakes — no real duckdb file is touched here, matching the machine-independence discipline
`conftest.py`'s `screener_data_stub` fixture already enforces), and the price/momentum fetch (via
a monkeypatched `_asof_price_lookup`, so these tests hit no network and no Ollama).

Uses the same GEV fixture slice every other `build_pack` test uses
(`fundamentals_history.json`: FY2022-2025; `fundamentals_quarterly.json`: quarters through
2026-06-30; `fundamentals_ttm.json.fy_leg_end`: "2025-12-31", i.e. a calendar fiscal year end).
"""
import sys
import re
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import capability_test as cap
import rs2_data


def _split_sec(text, tag):
    parts = re.split(rf"(?:##\s*)?DATA\s+{re.escape(tag)}(?=\s|$)", text)
    return parts


def _fake_asof_price_lookup(monkeypatch, price=180.0, asof_str="2026-03-31", series=None):
    """Stub `cap._asof_price_lookup` so no test touches the network or yfinance."""
    series = series if series is not None else {asof_str: price}

    def _fake(t, asof_date, lookback_days=400):
        return {"price": price, "asof": asof_str, "series": series}
    monkeypatch.setattr(cap, "_asof_price_lookup", _fake)


def _fake_mri_asof(monkeypatch, degraded=True):
    """Stub every rs2_data.asof_* MRI accessor with deterministic, network/duckdb-free fakes."""
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": 0.043, "real_10y": 0.02,
                                         "breakeven_10y": 0.023},
        "risk_free_source": {"nominal_10y": "fake", "real_10y": "fake", "breakeven_10y": "fake"},
        "implied_erp": None, "implied_cost_of_equity": None, "sector_loadings": {},
        "erp_source": "unavailable", "degraded": degraded,
        "degradation_reasons": ["no_anchor_run_stored_at_or_before(fake)"],
        "anchor_run_asof": None,
    })
    monkeypatch.setattr(rs2_data, "asof_terminal_g", lambda asof: (None, "fake_no_anchor_run"))
    monkeypatch.setattr(rs2_data, "asof_secondary_macro_series", lambda asof: {
        "t10y2y": (0.25, str(asof)), "baa10y": (1.4, str(asof)), "hy_oas": (3.0, str(asof)),
    })
    monkeypatch.setattr(rs2_data, "asof_regime_vector", lambda asof, max_age_days=None: {
        "date": str(asof), "probabilities": {"goldilocks": 0.29, "reflation": 0.22,
                                             "stagflation": 0.18, "recession": 0.17,
                                             "tightening": 0.13},
        "headline": "goldilocks", "headline_probability": 0.29, "margin": 0.07,
    })
    monkeypatch.setattr(rs2_data, "asof_shock_register", lambda asof: {
        "asof": str(asof), "shocks": [{"shock_id": "oil_shock", "severity": 2, "direction": "up",
                                       "onset_date": "2026-03-05", "state": "active"}],
        "elevated_volatility_ahead": False,
    })
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp", lambda asof: (None, "fake_unavailable"))
    monkeypatch.setattr(rs2_data, "asof_inflation_trend", lambda asof: {"cpi_yoy": 0.033,
                                                                        "pce_yoy": 0.035})


# ── header / mode plumbing ──────────────────────────────────────────────────────────────────

def test_asof_none_is_byte_identical_to_omitting_the_argument(screener_data_stub, monkeypatch):
    """The default (asof=None) must be untouched, live-pack behaviour."""
    _fake_mri_asof(monkeypatch)
    a = cap.build_pack("GEV")
    b = cap.build_pack("GEV", asof=None)
    assert str(a) == str(b)


def test_asof_mode_prints_the_point_in_time_header(screener_data_stub, monkeypatch):
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    assert "POINT-IN-TIME BRIEFING" in pack
    assert "as of 2026-03-31" in pack
    assert "you must not use knowledge of events after this date" in pack
    assert "point_in_time" in pack.flags


def test_asof_mode_forces_research_off_regardless_of_include_research(screener_data_stub, monkeypatch):
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31", include_research=True)
    assert "SECTION 11 - DEEP RESEARCH BRIEF" not in pack and "DATA 11 - DEEP RESEARCH BRIEF" not in pack
    assert "not available (point-in-time trial)" in pack


def test_asof_accepts_a_date_object_and_a_string_identically(screener_data_stub, monkeypatch):
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    p1 = cap.build_pack("GEV", asof="2026-03-31")
    p2 = cap.build_pack("GEV", asof=date(2026, 3, 31))
    assert str(p1) == str(p2)


# ── fundamentals cutoffs ────────────────────────────────────────────────────────────────────

def test_quarterly_rows_after_the_cutoff_are_excluded(screener_data_stub, monkeypatch):
    """asof 2026-03-31, 45-day lag -> cutoff 2026-02-14. GEV's fixture carries quarters through
    2026-06-30; only quarters ending on/before 2026-02-14 may appear (through 2025-12-31)."""
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    assert "2025-12-31" in pack        # last allowed quarter
    sec4_text = _split_sec(_split_sec(pack, "4")[1], "5")[0]
    assert "2026-03-31" not in sec4_text
    assert "2026-06-30" not in sec4_text


def test_fiscal_years_after_the_cutoff_are_excluded(screener_data_stub, monkeypatch):
    """asof 2025-06-30, 45-day lag -> cutoff 2025-05-16 -> last allowed FY 2024 (GEV's fixture
    carries FY2022-2025; FY2025 must not appear)."""
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch, asof_str="2025-06-30")
    pack = cap.build_pack("GEV", asof="2025-06-30")
    sec5 = _split_sec(pack, "5 -")[1].split("GROWTH BASE RATES")[0]
    assert "| 2022 |" in sec5 or "2022" in sec5
    assert "| 2024 |" in sec5 or "2024" in sec5
    assert "| 2025 |" not in sec5


def test_all_fiscal_years_allowed_when_cutoff_postdates_them_all(screener_data_stub, monkeypatch):
    """asof 2026-03-31 -> cutoff 2026-02-14, which is after GEV's FY2025 fiscal year end
    (2025-12-31) — every fixture year (2022-2025) is knowable and none is excluded."""
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    live_pack = cap.build_pack("GEV")
    asof_pack = cap.build_pack("GEV", asof="2026-03-31")
    live_years = {int(y) for y in cap.rs2_data.load_json(
        cap.SD / "fundamentals_history.json")["tickers"]["GEV"]}
    for y in live_years:
        assert f"| {y} |" in asof_pack


def test_ttm_recomputed_from_trailing_four_allowed_quarters(screener_data_stub, monkeypatch):
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec3 = _split_sec(_split_sec(pack, "3")[1], "4")[0]
    assert "recomputed from the 4 trailing allowed quarters" in sec3
    # S3 C (brief §5.6): one typed line (Revenue | net income | ...), lower-cased labels.
    assert "operating cash flow not available (point-in-time)" in sec3
    assert "capital expenditure not available (point-in-time)" in sec3
    assert "free cash flow not available (point-in-time)" in sec3
    # Revenue IS recomputable (sum of the last 4 allowed quarters' `revenue` field) — must not
    # be blanket-omitted the way ocf/capex/fcf are.
    assert "Revenue not available" not in sec3


def test_ttm_omitted_when_fewer_than_four_quarters_are_allowed(screener_data_stub, monkeypatch):
    """asof far enough back that fewer than 4 of GEV's fixture quarters qualify."""
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch, asof_str="2024-07-01")
    pack = cap.build_pack("GEV", asof="2024-07-01")
    sec3 = _split_sec(_split_sec(pack, "3")[1], "4")[0]
    assert "not available (point-in-time)" in sec3
    assert "fewer than 4 quarters" in sec3


# ── same-day-snapshot sources: omitted, not leaked ──────────────────────────────────────────

def test_same_day_snapshot_sections_are_omitted_with_a_reason(screener_data_stub, monkeypatch):
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    for header in ("7 - FILING-DERIVED QUALITY MEASURES",
                   "8 - CONSENSUS & MULTIPLES",
                   "8.5 - PEER CONTEXT",
                   "9 - POSITIONING",
                   "10 - EARNINGS CALL EXCERPT"):
        assert f"DATA {header}" in pack
    assert "not available (point-in-time)" in pack
    assert "POINT-IN-TIME OMISSIONS" in pack


def test_vendor_scalars_omitted_in_section_2(screener_data_stub, monkeypatch):
    """Total cash/debt/SBC/beta (SECTION 2) are same-day vendor scalars with no history — must
    read `not available`, never today's `financials/GEV.json` value."""
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec2 = _split_sec(_split_sec(pack, "2 - MARKET")[1], "2.5")[0]
    assert "Total cash (vendor): not available (point-in-time)" in sec2
    assert "Total debt (vendor): not available (point-in-time)" in sec2
    assert "Stock-based compensation (vendor): not available (point-in-time)" in sec2
    assert "Beta: not available (point-in-time)" in sec2


# ── price / SCR-10 momentum ─────────────────────────────────────────────────────────────────

def test_price_comes_from_the_asof_lookup_not_the_vendor_snapshot(screener_data_stub, monkeypatch):
    _fake_asof_price_lookup(monkeypatch, price=123.45, asof_str="2026-03-30")
    _fake_mri_asof(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    assert "Price: $123.45" in pack
    assert "2026-03-30" in pack


def test_scr10_momentum_recomputed_from_series_not_factor_scores(screener_data_stub, monkeypatch):
    """factor_scores.json is absent from the fixture entirely; a live-mode pack would print NULL
    momentum facts from it. In asof mode the facts come from the fetched price series instead."""
    series = {
        "2025-03-31": 100.0, "2025-09-30": 120.0, "2026-02-28": 150.0,
        "2026-03-02": 160.0, "2026-03-31": 180.0,
    }
    _fake_asof_price_lookup(monkeypatch, price=180.0, asof_str="2026-03-31", series=series)
    _fake_mri_asof(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec25 = _split_sec(_split_sec(pack, "2.5")[1], "3")[0]
    assert "recomputed from historical closes" in sec25
    assert "Distance from 52-week high" in sec25
    assert "not available (point-in-time)" not in sec25.split("Distance from 52-week high")[1].split("\n")[0]


def test_price_omitted_when_no_historical_close_is_found(screener_data_stub, monkeypatch):
    monkeypatch.setattr(cap, "_asof_price_lookup", lambda t, asof_date, lookback_days=400: None)
    _fake_mri_asof(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    assert "Price: not available (point-in-time)" in pack
    assert "no historical close found" in pack


# ── macro / regime / shocks — via fakes, no real duckdb touched ────────────────────────────

def test_macro_state_of_the_world_uses_asof_accessors(screener_data_stub, monkeypatch):
    _fake_mri_asof(monkeypatch)
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    assert "point-in-time" in _split_sec(_split_sec(pack, "1.5")[1], "2")[0]
    assert "goldilocks" in pack
    assert "ACTIVE SHOCK: `oil_shock`" in pack
    # ERP/CoE unavailable per the fake -> COE ANCHOR line must degrade honestly, not invent one.
    assert "COE ANCHOR for this name: not available (point-in-time)" in pack


def test_macro_state_prints_not_available_when_mri_gives_nothing(screener_data_stub, monkeypatch):
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": None, "real_10y": None,
                                         "breakeven_10y": None},
        "risk_free_source": {"nominal_10y": None, "real_10y": None, "breakeven_10y": None},
        "implied_erp": None, "implied_cost_of_equity": None, "sector_loadings": {},
        "erp_source": "unavailable", "degraded": True,
        "degradation_reasons": ["fake_none"], "anchor_run_asof": None,
    })
    monkeypatch.setattr(rs2_data, "asof_terminal_g", lambda asof: (None, "fake_none"))
    monkeypatch.setattr(rs2_data, "asof_secondary_macro_series",
                        lambda asof: {"t10y2y": None, "baa10y": None, "hy_oas": None})
    monkeypatch.setattr(rs2_data, "asof_regime_vector", lambda asof, max_age_days=None: None)
    monkeypatch.setattr(rs2_data, "asof_shock_register", lambda asof: None)
    monkeypatch.setattr(rs2_data, "asof_inflation_trend", lambda asof: {"cpi_yoy": None, "pce_yoy": None})
    _fake_asof_price_lookup(monkeypatch)
    pack = cap.build_pack("GEV", asof="2026-03-31")
    assert pack.macro_degraded is True
    sec16 = _split_sec(_split_sec(pack, "1.6")[1], "2")[0]
    assert "not available (point-in-time)" in sec16
    assert "MRI regime probability vector: not available (point-in-time)" in sec16
    assert "Active shocks (S4 register): not available (point-in-time)" in sec16


# ── point-in-time helper functions, unit level ──────────────────────────────────────────────

def test_last_allowed_fiscal_year_uses_the_companys_own_fiscal_calendar():
    """A January fiscal-year-end company (e.g. NVDA) must not be pinned to a Dec-31 assumption:
    its already-filed January-ending FY must qualify once the cutoff clears it."""
    cutoff = date(2026, 2, 14)   # asof 2026-03-31 minus the 45-day lag
    # Calendar (Dec 31) FYE: FY2026 would end 2026-12-31, far after cutoff -> FY2025 is the
    # last allowed year.
    assert cap._last_allowed_fiscal_year(cutoff, 12, 31) == 2025
    # January FYE (NVDA-style, ends 2026-01-25): that FY-label-2026 year has ALREADY ended and,
    # by the 45-day lag, is presumed filed -> FY2026 itself is allowed.
    assert cap._last_allowed_fiscal_year(cutoff, 1, 25) == 2026


def test_fy_end_date_for_clamps_invalid_days():
    assert cap._fy_end_date_for(2025, 2, 29) == date(2025, 2, 28)   # not a leap year
    assert cap._fy_end_date_for(2024, 2, 29) == date(2024, 2, 29)   # leap year: unclamped


def test_parse_asof_accepts_string_and_date():
    assert cap._parse_asof("2026-03-31") == date(2026, 3, 31)
    assert cap._parse_asof(date(2026, 3, 31)) == date(2026, 3, 31)


def test_series_close_on_or_before_matches_grade_depth_verdicts_semantics():
    series = {"2026-03-25": 100.0, "2026-03-27": 102.0}
    d, c = cap._series_close_on_or_before(series, "2026-03-31", window=10)
    assert (d, c) == ("2026-03-27", 102.0)
    d2, c2 = cap._series_close_on_or_before(series, "2026-03-31", window=1)
    assert (d2, c2) == (None, None)   # nothing within a 1-day window of 2026-03-31


# ── point-in-time CoE anchor reconstruction (Phase 4 E4.3) ──────────────────────────

def test_damodaran_annual_erp_picks_correct_year_by_asof():
    """ERP(asof) picks Dec-31 of the prior year when asof >= 30 days into the new year;
    picks two years back when within the first 30 days."""
    # 2026-03-31: >= 30 days into 2026 -> 2025-12-31 value (0.0423)
    erp, label = rs2_data.asof_damodaran_erp("2026-03-31")
    assert erp == pytest.approx(0.0423, abs=1e-5)
    assert label == "Damodaran implied ERP, year-end 2025 (published ~Jan 2026)"

    # 2026-01-15: within first 30 days of 2026 -> 2024-12-31 value (0.0433)
    erp2, label2 = rs2_data.asof_damodaran_erp("2026-01-15")
    assert erp2 == pytest.approx(0.0433, abs=1e-5)
    assert label2 == "Damodaran implied ERP, year-end 2024 (published ~Jan 2025)"

    # 2026-01-30: exactly 30 days into 2026 -> cutoff 2025-12-31 -> 2025-12-31 value (0.0423)
    erp3, label3 = rs2_data.asof_damodaran_erp("2026-01-30")
    assert erp3 == pytest.approx(0.0423, abs=1e-5)
    assert label3 == "Damodaran implied ERP, year-end 2025 (published ~Jan 2026)"


def test_asof_coe_anchor_reconstruction_in_pack(screener_data_stub, monkeypatch):
    """When Rf, ERP, and sector loading are available, the pack stamps the COE ANCHOR
    and the +-150bp COE MANDATE with the required structural labels."""
    _fake_asof_price_lookup(monkeypatch)
    # Provide working fakes: Rf 4.30%, Damodaran ERP 4.23%, loading 0.868 (Industrials for GEV)
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": 0.043, "real_10y": 0.02,
                                         "breakeven_10y": 0.023},
        "risk_free_source": {"nominal_10y": "asof_raw_observations(DGS10,2026-03-31)",
                             "real_10y": "fake", "breakeven_10y": "fake"},
        "implied_erp": None, "implied_cost_of_equity": None, "sector_loadings": {},
        "erp_source": "unavailable", "degraded": True,
        "degradation_reasons": ["no_anchor_run_stored_at_or_before(fake)"],
        "anchor_run_asof": None,
    })
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp",
                        lambda asof: (0.0423, "Damodaran implied ERP, year-end 2025 (published ~Jan 2026)"))
    monkeypatch.setattr(rs2_data, "anchor_sector_loading",
                        lambda sector: (0.868, "mri_anchor:sector_loadings:industrials"))
    monkeypatch.setattr(rs2_data, "anchor_terminal_g",
                        lambda: (0.0375, "anchor_long_run_growth(2026-09-23)"))
    monkeypatch.setattr(rs2_data, "asof_secondary_macro_series",
                        lambda asof: {"t10y2y": (0.25, str(asof)), "baa10y": (1.4, str(asof)), "hy_oas": (3.0, str(asof))})
    monkeypatch.setattr(rs2_data, "asof_regime_vector", lambda asof, max_age_days=None: {
        "date": str(asof), "probabilities": {"goldilocks": 0.29, "reflation": 0.22,
                                             "stagflation": 0.18, "recession": 0.17, "tightening": 0.13},
        "headline": "goldilocks", "headline_probability": 0.29, "margin": 0.07,
    })
    monkeypatch.setattr(rs2_data, "asof_shock_register", lambda asof: {
        "asof": str(asof), "shocks": [], "elevated_volatility_ahead": False,
    })
    monkeypatch.setattr(rs2_data, "asof_inflation_trend", lambda asof: {"cpi_yoy": 0.033, "pce_yoy": 0.035})

    pack = cap.build_pack("GEV", asof="2026-03-31")
    sec15 = _split_sec(_split_sec(pack, "1.5")[1], "1.6")[0]

    # COE ANCHOR: rf 4.30% + adj loading 0.912 (Blume: 0.67 * 0.868 + 0.33) * ERP 4.23% = 8.16%
    # S3 C (brief §5.6): the result is stated before "=", and the anchor line is now combined with
    # the long-run growth anchor clause on one line via " | ".
    assert ("COE ANCHOR for this name: 8.16% = rf 4.30% + adjusted loading 0.912× (Blume: 0.67 × "
            "raw 0.868 + 0.33) × implied ERP 4.23%") in sec15

    # Structural parameter labels must be present
    assert "sector loading from the current anchor (structural parameter; small look-ahead risk, accepted for this trial)" in sec15
    assert "Damodaran implied ERP, year-end 2025 (published ~Jan 2026)" in sec15
    assert "from the current anchor (structural parameter; small look-ahead risk, accepted for this trial)" in sec15

    # S3 C (brief §5.3): the COE MANDATE line is gone — that rule now lives in the DEFAULTS block
    # (§5.2), which names the same +-150bp tolerance against coe_anchor.
    assert "**COE MANDATE:**" not in sec15


def test_asof_coe_anchor_uses_adjusted_loading(screener_data_stub, monkeypatch):
    """asof_coe_anchor directly returns the Blume-adjusted loading and anchor calculation."""
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": 0.043},
    })
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp",
                        lambda asof: (0.0423, "Damodaran ERP"))
    monkeypatch.setattr(rs2_data, "anchor_sector_loading",
                        lambda sector: (0.868, "mri_anchor:sector_loadings:industrials"))

    res = rs2_data.asof_coe_anchor("GEV", "2026-03-31")
    # 4.30 + (0.67 * 0.868 + 0.33) * 4.23 = 8.16% (NOT 7.97%)
    assert res["coe_anchor_asof"] == 8.16
    assert res["sector_loading"] == 0.912
    assert res["raw_sector_loading"] == 0.868



def test_asof_coe_anchor_missing_pieces_degrades_and_omits_mandate(screener_data_stub, monkeypatch):
    """If Rf, ERP, or sector loading is missing, COE ANCHOR prints 'not available (point-in-time)'
    and the COE MANDATE is omitted."""
    _fake_asof_price_lookup(monkeypatch)
    _fake_mri_asof(monkeypatch)

    # 1. Missing Rf:
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": None, "real_10y": 0.02, "breakeven_10y": 0.023},
        "risk_free_source": {"nominal_10y": None, "real_10y": "fake", "breakeven_10y": "fake"},
        "implied_erp": None, "implied_cost_of_equity": None, "sector_loadings": {},
        "erp_source": "unavailable", "degraded": True, "degradation_reasons": [], "anchor_run_asof": None,
    })
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp",
                        lambda asof: (0.0423, "Damodaran implied ERP, year-end 2025 (published ~Jan 2026)"))
    monkeypatch.setattr(rs2_data, "anchor_sector_loading", lambda sector: (0.868, "src"))

    pack_no_rf = cap.build_pack("GEV", asof="2026-03-31")
    sec15_no_rf = _split_sec(_split_sec(pack_no_rf, "1.5")[1], "1.6")[0]
    assert "- COE ANCHOR for this name: not available (point-in-time)" in sec15_no_rf
    assert "COE MANDATE" not in sec15_no_rf

    # 2. Missing ERP:
    monkeypatch.setattr(rs2_data, "asof_cost_of_capital", lambda asof: {
        "asof": str(asof), "risk_free": {"nominal_10y": 0.043, "real_10y": 0.02, "breakeven_10y": 0.023},
        "risk_free_source": {"nominal_10y": "src", "real_10y": "fake", "breakeven_10y": "fake"},
        "implied_erp": None, "implied_cost_of_equity": None, "sector_loadings": {},
        "erp_source": "unavailable", "degraded": True, "degradation_reasons": [], "anchor_run_asof": None,
    })
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp", lambda asof: (None, "unavailable"))

    pack_no_erp = cap.build_pack("GEV", asof="2026-03-31")
    sec15_no_erp = _split_sec(_split_sec(pack_no_erp, "1.5")[1], "1.6")[0]
    assert "- COE ANCHOR for this name: not available (point-in-time)" in sec15_no_erp
    assert "COE MANDATE" not in sec15_no_erp

    # 3. Missing sector loading:
    monkeypatch.setattr(rs2_data, "asof_damodaran_erp",
                        lambda asof: (0.0423, "Damodaran implied ERP, year-end 2025 (published ~Jan 2026)"))
    monkeypatch.setattr(rs2_data, "anchor_sector_loading", lambda sector: (None, "unmapped"))

    pack_no_load = cap.build_pack("GEV", asof="2026-03-31")
    sec15_no_load = _split_sec(_split_sec(pack_no_load, "1.5")[1], "1.6")[0]
    assert "- COE ANCHOR for this name: not available (point-in-time)" in sec15_no_load
    assert "COE MANDATE" not in sec15_no_load

