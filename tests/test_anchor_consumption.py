"""Anchor consumption: the vocabulary bridge and the fallback gates.

The bug these tests exist to prevent: MRI publishes snake_case sector ids
("information_technology") while RS2 holds Yahoo/GICS names ("Technology"). Those sets share
no value, so a lookup that passes one straight into the other matches nothing and the anchored
band silently never appears — a dead feature indistinguishable from a data gap. The first test
asserts the bridge over the ACTUAL vocabulary in stocks.csv, not over a convenient sample.
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import rs2_data  # noqa: E402


EXPECTED_BRIDGE = {
    "Basic Materials": "materials",
    "Communication Services": "communication_services",
    "Consumer Cyclical": "consumer_discretionary",
    "Consumer Defensive": "consumer_staples",
    "Energy": "energy",
    "Financial Services": "financials",
    "Healthcare": "health_care",
    "Industrials": "industrials",
    "Real Estate": "real_estate",
    "Technology": "information_technology",
    "Utilities": "utilities",
}


@pytest.fixture()
def anchor_dir(tmp_path, monkeypatch):
    """A configurable anchors directory with a NON-degraded band payload."""
    today = date.today().isoformat()
    payload = {
        "anchor_id": "sector_multiple_bands",
        "asof": today,
        "built_at": f"{today}T00:00:00Z",
        "panel_source": "external_valuation_panel",
        "degraded": False,
        "bands": [
            {
                "sector_id": sector_id,
                "regime_state": {"growth": "strong", "inflation": "high"},
                "ntm_pe": {"p25": 12.0, "median": 15.0, "p75": 18.0},
                "n_obs": 40,
                "conditioning_level": ["growth"],
                "arithmetic_check": {"coe": 0.09, "g": 0.025, "justified_pe": 9.2},
            }
            for sector_id in sorted(set(EXPECTED_BRIDGE.values()))
        ],
    }
    (tmp_path / rs2_data.ANCHOR_FILES["sector_multiple_bands"]).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setitem(rs2_data.CONFIG, "anchors_dir", str(tmp_path))
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    return tmp_path


def test_every_sector_in_stocks_csv_bridges_to_a_real_mri_id():
    """The bridge must be total over the vocabulary RS2 actually holds."""
    path = Path(rs2_data.CONFIG["screener_data_dir"]) / "stocks.csv"
    if not path.exists():
        pytest.skip("stocks.csv not available")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        column = next((c for c in reader.fieldnames if c.lower() == "sector"), None)
        assert column, "stocks.csv has no Sector column"
        observed = {(row.get(column) or "").strip() for row in reader}

    # Nothing in the real vocabulary may fall through the mapping unbridged.
    unknown = {
        value
        for value in observed
        if value and value.lower() != "unknown" and value not in EXPECTED_BRIDGE
    }
    assert unknown == set(), f"unbridged sector values: {sorted(unknown)}"

    for label, expected in EXPECTED_BRIDGE.items():
        assert rs2_data.mri_sector_id(label) == expected


def test_unknown_or_empty_sector_maps_to_none_never_to_a_real_sector():
    """A name with no known sector must not inherit another sector's band."""
    for value in ("", None, "Unknown", "  ", "Not A Sector"):
        assert rs2_data.mri_sector_id(value) is None or rs2_data.mri_sector_id(value).startswith(
            "not_a"
        )


def test_anchor_band_is_found_through_the_bridge(anchor_dir):
    """RS2's own vocabulary must reach the anchored band."""
    for label, sector_id in EXPECTED_BRIDGE.items():
        result = rs2_data.anchor_multiple_bands(label)
        assert result, f"no band resolved for {label!r} -> {sector_id!r}"
        assert result["anchor_ntm_pe"]["median"] == 15.0
        assert result["anchor_ntm_pe_n"] == 40
        assert result["anchor_arithmetic_check"]["justified_pe"] == 9.2


def test_absent_or_degraded_anchor_returns_nothing(anchor_dir, monkeypatch):
    """A missing anchor must fall back to the engine's own constants, not to a default band."""
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    (anchor_dir / rs2_data.ANCHOR_FILES["sector_multiple_bands"]).unlink()
    assert rs2_data.anchor_multiple_bands("Technology") == {}
    assert rs2_data.anchor_terminal_g()[0] is None
    assert rs2_data.anchor_level_cost_of_equity_pct()[0] is None


def test_stale_anchor_is_rejected(anchor_dir, monkeypatch):
    """An anchor older than anchor_max_age_days must not be consumed."""
    path = anchor_dir / rs2_data.ANCHOR_FILES["sector_multiple_bands"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["asof"] = "2000-01-01"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    assert rs2_data.usable_anchor("sector_multiple_bands") is None
    assert rs2_data.anchor_multiple_bands("Technology") == {}


def test_implied_cost_of_equity_is_consumed_and_its_basis_named(anchor_dir, monkeypatch):
    """A universe-implied level IS consumed — but the basis travels in the source string.

    The level is weaker evidence than an index-implied one, so a caller must be able to see
    which it got without opening the payload.
    """
    today = date.today().isoformat()
    (anchor_dir / rs2_data.ANCHOR_FILES["cost_of_capital"]).write_text(
        json.dumps(
            {
                "asof": today,
                "built_at": f"{today}T00:00:00Z",
                "risk_free": {"nominal_10y": 0.0494},
                "implied_erp": 0.0424,
                "implied_cost_of_equity": 0.0918,
                "erp_basis": "universe",
                "market_implied_coe": None,
                "erp_source": "implied",
                "degraded": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    level, source = rs2_data.anchor_level_cost_of_equity_pct()
    assert level == pytest.approx(9.18)
    assert "universe" in source


def test_a_risk_free_only_level_is_never_published_as_a_cost_of_equity(anchor_dir, monkeypatch):
    """The nominal 10y alone would understate the discount rate by the whole equity premium."""
    today = date.today().isoformat()
    (anchor_dir / rs2_data.ANCHOR_FILES["cost_of_capital"]).write_text(
        json.dumps(
            {
                "asof": today,
                "built_at": f"{today}T00:00:00Z",
                "risk_free": {"nominal_10y": 0.0445},
                "implied_cost_of_equity": None,
                "market_implied_coe": None,
                "erp_source": "unavailable",
                "degraded": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    level, source = rs2_data.anchor_level_cost_of_equity_pct()
    assert level is None
    assert "risk_free_only" in source


def test_degraded_long_run_growth_is_rejected(anchor_dir, monkeypatch):
    today = date.today().isoformat()
    (anchor_dir / rs2_data.ANCHOR_FILES["long_run_growth"]).write_text(
        json.dumps(
            {
                "asof": today,
                "built_at": f"{today}T00:00:00Z",
                "terminal_g_suggestion": 0.0375,
                "degraded": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    value, source = rs2_data.anchor_terminal_g()
    assert value is None
    assert "degraded" in source


def _growth_payload(tmp_path: Path, terminal_g: float) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (tmp_path / rs2_data.ANCHOR_FILES["long_run_growth"]).write_text(
        json.dumps(
            {
                "anchor_id": "long_run_growth",
                "asof": today,
                "built_at": f"{today}T00:00:00Z",
                "nominal_gdp_trend": 0.0445,
                "terminal_g_suggestion": terminal_g,
                "downstream_prior_in_use": 0.025,
                "delta": round(terminal_g - 0.025, 4),
                "degraded": False,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _valued_ticker():
    """A ticker the backbone actually values on the reverse-DCF route."""
    import rs2_data as rd

    sd = Path(rd.CONFIG["screener_data_dir"]) / "financials"
    if not sd.exists():
        return None
    for path in sorted(sd.glob("*.json"))[:80]:
        ticker = path.stem
        try:
            probe = _vb().backbone(ticker)
        except Exception:  # noqa: BLE001
            continue
        if probe.get("ok") and probe.get("method") == "reverse_dcf":
            return ticker
    return None


def _vb():
    import importlib

    sys.path.insert(0, str(HERE))
    return importlib.import_module("valuation_backbone")


def test_anchor_terminal_growth_actually_drives_the_solver(tmp_path, monkeypatch):
    """The claim the repair package rests on: the anchor moves the DCF, and it says so.

    A perpetual-growth change feeds _solve_implied_growth(), so the implied growth and the
    expectations gap must move with it. This asserts the wiring rather than trusting it.
    """
    vb = _vb()
    ticker = _valued_ticker()
    if ticker is None:
        pytest.skip("no reverse-DCF name available in the corpus")

    # Baseline: an EMPTY anchors dir, so the engine falls back to its own constant.
    (tmp_path / "empty").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    monkeypatch.setitem(rs2_data.CONFIG, "anchors_dir", str(tmp_path / "empty"))
    baseline = vb.backbone(ticker)

    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    monkeypatch.setitem(
        rs2_data.CONFIG, "anchors_dir", str(_growth_payload(tmp_path / "g35", 0.035))
    )
    anchored = vb.backbone(ticker)

    assert baseline["terminal_growth"] == pytest.approx(0.025)
    assert anchored["terminal_growth"] == pytest.approx(0.035)
    assert "anchor_long_run_growth" in anchored["terminal_growth_source"]
    assert "engine_constant" in baseline["terminal_growth_source"]
    # The wiring is real: the implied growth and the gap both moved.
    assert anchored["implied_growth"] != baseline["implied_growth"]
    assert anchored["expectations_gap_pts"] != baseline["expectations_gap_pts"]

    # DIRECTION, measured as a controlled comparison rather than inferred from the two arms.
    # The two arms now differ in TWO ways — the anchor changes the terminal rate, and the cache
    # consistency gate then refuses the offset because it was solved under the other rate — so
    # comparing them directly would conflate the two. Holding the discount rate fixed isolates
    # the terminal-growth effect: a richer perpetual rate needs LESS stage-1 growth to justify
    # the same price.
    base_cf, mcap, wacc = 1.0e9, 2.5e10, 0.10
    low = vb._solve_implied_growth(base_cf, mcap, wacc, 0.025)
    high = vb._solve_implied_growth(base_cf, mcap, wacc, 0.035)
    assert high < low


def test_agg_value_defaults_to_the_engine_constant():
    """No anchor → identical to the previous behaviour, byte for byte."""
    vb = _vb()
    names = [{"ni": 1.0e9, "mcap": 2.0e10, "g": 0.06, "table_rate": 0.10}]
    assert vb._agg_value(names, lambda n: 0.10) == vb._agg_value(
        names, lambda n: 0.10, vb.TERMINAL_G
    )


def test_calibration_solver_follows_the_engine_terminal_growth():
    """The offset must be solved on the assumption the engine actually values with.

    The bug this pins: `_agg_value` used the module constant TERMINAL_G while backbone() had
    started taking its rate from the long-run growth anchor. The calibration then answered "what
    rate makes the aggregate match market cap assuming 2.5% perpetuity" while the engine
    answered "assuming 3.5%", so the level it landed was mis-levelled by construction — and its
    own docstring ("the OFFSET that achieves the same aggregate") was false. Measured: the same
    book values ~10% higher at 3.5% than at 2.5%.
    """
    import inspect

    vb = _vb()
    names = [{"ni": 1.0e9, "mcap": 2.0e10, "g": 0.06, "table_rate": 0.10}]
    low = vb._agg_value(names, lambda n: 0.10, 0.025)
    high = vb._agg_value(names, lambda n: 0.10, 0.035)
    assert high > low * 1.05

    source = inspect.getsource(vb.build_coe_calibration)
    assert "_g_term, _g_src = terminal_g()" in source
    assert "_agg_value(names, rate_of_mid(mid), _g_term)" in source


def test_cached_coe_offset_is_refused_when_solved_under_a_different_terminal_g(monkeypatch):
    """A calibration outliving its assumption is the failure this whole change removes.

    `coe_offset_pts()` had no gate at all, deliberately ("level continuity beats freshness").
    Consistency is a different requirement: an offset solved at 2.5% perpetuity and applied while
    the engine runs at 3.5% lands the book at a level nobody chose. It must be refused loudly,
    and the raw sector table used instead.
    """
    vb = _vb()
    cache = {"level_offset_pts": 2.4, "terminal_g": 0.035}

    monkeypatch.setattr(vb.rs2_data, "load_json", lambda path: dict(cache))
    monkeypatch.setattr(vb.rs2_data, "anchor_level_cost_of_equity_pct", lambda: (None, "no_anchor"))
    monkeypatch.setattr(vb, "terminal_g", lambda: (0.035, "matching"))
    assert vb.coe_offset_pts() == pytest.approx(2.4)

    monkeypatch.setattr(vb, "terminal_g", lambda: (0.025, "engine_constant"))
    assert vb.coe_offset_pts() == 0.0, "a calibration solved at a different rate was applied"
    assert "calibration_not_applicable" in vb.coe_level_source()
    assert "cache_solved_at_terminal_g=0.0350" in vb.coe_level_source()


def test_a_cache_predating_the_stamp_is_refused(monkeypatch):
    """An offset with no recorded growth assumption cannot be trusted to match any."""
    vb = _vb()
    monkeypatch.setattr(vb.rs2_data, "load_json", lambda path: {"level_offset_pts": 1.7})
    monkeypatch.setattr(vb.rs2_data, "anchor_level_cost_of_equity_pct", lambda: (None, "no_anchor"))
    monkeypatch.setattr(vb, "terminal_g", lambda: (0.035, "matching"))
    assert vb.coe_offset_pts() == 0.0
    assert "cache_predates_terminal_g_stamp" in vb.coe_level_source()
