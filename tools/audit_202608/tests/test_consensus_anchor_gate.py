"""tools/audit_202608/tests/test_consensus_anchor_gate.py

Unit tests for coding brief S2c (gate consensus anchor):
1. Facts: from_text on 5 estimate lines; build_pack with GEV fixture across 5 statuses; parity on each.
2. Gate: assess() behavior for each status, absent status at gv=6 vs gv=5, street_fence validation.
3. ASTH L2 fixture: assess() returns False with exactly consensus_data_unavailable and no_street_fence.
4. Harness: ::PACK DATA:: line on non-ok status and consensus.json consensus_data_status stamp.
5. Battery: build_frozen_pack raises SystemExit on enrich_missing and stale, succeeds on ok.
"""
from datetime import datetime as _real_datetime
import json
from pathlib import Path
import socket
import sys
import urllib.request

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
REPO = AUDIT_DIR.parent
for p in (str(AUDIT_DIR), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import capability_test as cap
import consensus_valuation as cv
import depth_gates
import pack_facts
import rs2_data
import tools.dispersion_battery as db
from capability_test import PackText

FIXED_LOCAL = _real_datetime(2026, 9, 27, 12, 0, 0)


class FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FIXED_LOCAL.astimezone(tz)
        return FIXED_LOCAL


@pytest.fixture
def frozen_env(monkeypatch):
    """Freeze clock and stub external services for deterministic build_pack."""
    class BlockedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")

        def connect(self, *args, **kwargs):
            raise RuntimeError("Socket access blocked in test")

    monkeypatch.setattr(socket, "socket", BlockedSocket)
    monkeypatch.setattr(
        cap.company_news, "fetch",
        lambda company, t: {"date": "2026-09-27", "rows": [], "unresponsive_engines": [], "errors": ["stubbed"]}
    )
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)

    for mod in (cap, rs2_data):
        monkeypatch.setattr(mod, "datetime", FrozenDatetime, raising=False)


def _fake_asof_price_lookup(monkeypatch, price=180.0, asof_str="2026-03-31", series=None):
    series = series if series is not None else {asof_str: price}

    def _fake(t, asof_date, lookback_days=400):
        return {"price": price, "asof": asof_str, "series": series}
    monkeypatch.setattr(cap, "_asof_price_lookup", _fake)


def _fake_mri_asof(monkeypatch, degraded=True):
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


# =============================================================================================
# 1. Facts tests: from_text and build_pack
# =============================================================================================

def test_from_text_consensus_data_status_lines():
    cases = [
        ("- CONSENSUS ESTIMATES: not available \u2014 stale (> 45 days)", "stale"),
        ("- CONSENSUS ESTIMATES: not available - stale (> 45 days)", "stale"),
        ("- CONSENSUS ESTIMATES: not available \u2014 enrich record missing", "enrich_missing"),
        ("- CONSENSUS ESTIMATES: not available - enrich record missing", "enrich_missing"),
        ("- CONSENSUS ESTIMATES: not available \u2014 yfinance estimates unavailable", "estimates_unavailable"),
        ("- CONSENSUS ESTIMATES: not available - yfinance estimates unavailable", "estimates_unavailable"),
        ("- CONSENSUS ESTIMATES   [yfinance, fetched 2026-09-27]", "ok"),
        ("## SECTION 8 - CONSENSUS & MULTIPLES   [not available (point-in-time)]", "point_in_time"),
    ]
    for line, expected_status in cases:
        text = f"# DATA PACK - TST\n\n## SECTION 8\n{line}\n"
        facts = pack_facts.from_text(text)
        assert facts["consensus_data_status"] == expected_status, f"Failed for line: {line}"


def test_build_pack_facts_enrich_missing(screener_data_stub, frozen_env):
    enrich_file = cap.HERE / "enrich" / "GEV.json"
    if enrich_file.exists():
        enrich_file.unlink()

    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["consensus_data_status"] == "enrich_missing"
    ft = pack_facts.from_text(str(pack))
    assert ft["consensus_data_status"] == "enrich_missing"
    assert pack_facts.parity(pack.facts, ft) == []


def test_build_pack_facts_ok(screener_data_stub, frozen_env):
    enrich_dir = cap.HERE / "enrich"
    enrich_dir.mkdir(parents=True, exist_ok=True)
    enrich_data = {
        "_fetched_at": "2026-09-25T12:00:00",
        "estimates": {
            "revenue": {"2026": 30000000000.0},
            "earnings": {"2026": 2000000000.0},
        },
        "analyst_target_low": 150.0,
        "analyst_target_high": 250.0,
    }
    (enrich_dir / "GEV.json").write_text(json.dumps(enrich_data), encoding="utf-8")

    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["consensus_data_status"] == "ok"
    ft = pack_facts.from_text(str(pack))
    assert ft["consensus_data_status"] == "ok"
    assert pack_facts.parity(pack.facts, ft) == []


def test_build_pack_facts_stale(screener_data_stub, frozen_env):
    enrich_dir = cap.HERE / "enrich"
    enrich_dir.mkdir(parents=True, exist_ok=True)
    # 48 days before 2026-09-27
    enrich_data = {
        "_fetched_at": "2026-08-10T12:00:00",
        "estimates": {
            "revenue": {"2026": 30000000000.0},
            "earnings": {"2026": 2000000000.0},
        },
        "analyst_target_low": 150.0,
        "analyst_target_high": 250.0,
    }
    (enrich_dir / "GEV.json").write_text(json.dumps(enrich_data), encoding="utf-8")

    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["consensus_data_status"] == "stale"
    ft = pack_facts.from_text(str(pack))
    assert ft["consensus_data_status"] == "stale"
    assert pack_facts.parity(pack.facts, ft) == []


def test_build_pack_facts_estimates_unavailable(screener_data_stub, frozen_env):
    enrich_dir = cap.HERE / "enrich"
    enrich_dir.mkdir(parents=True, exist_ok=True)
    # Fresh enrich record, but estimates is None / empty dict
    enrich_data = {
        "_fetched_at": "2026-09-25T12:00:00",
        "estimates": None,
        "analyst_target_low": 150.0,
        "analyst_target_high": 250.0,
    }
    (enrich_dir / "GEV.json").write_text(json.dumps(enrich_data), encoding="utf-8")

    pack = cap.build_pack("GEV", include_research=False)
    assert pack.facts["consensus_data_status"] == "estimates_unavailable"
    ft = pack_facts.from_text(str(pack))
    assert ft["consensus_data_status"] == "estimates_unavailable"
    assert pack_facts.parity(pack.facts, ft) == []


def test_build_pack_facts_point_in_time(screener_data_stub, frozen_env, monkeypatch):
    _fake_asof_price_lookup(monkeypatch, price=180.0, asof_str="2026-03-31")
    _fake_mri_asof(monkeypatch)

    pack = cap.build_pack("GEV", asof="2026-03-31", include_research=False)
    assert pack.facts["consensus_data_status"] == "point_in_time"
    ft = pack_facts.from_text(str(pack))
    assert ft["consensus_data_status"] == "point_in_time"
    assert pack_facts.parity(pack.facts, ft) == []


# =============================================================================================
# 2. Gate tests: assess() statuses, missing status, fence validation
# =============================================================================================

@pytest.fixture
def base_verdict():
    return {
        "run_source": "orchestrator",
        "gate_version": depth_gates.GATE_VERSION,
        "n_basis": 2,
        "fiduciary_verdict": "PASS",
        "kelly_fraction_pct": 5.0,
        "spread_pct": 10.0,
        "instability": {"unstable": False},
        "pack_revision": 14,
        "street_fence": {"low": 100.0, "high": 150.0},
        "median_iv": 120.0,
        "mos_vs_base_pct": 20.0,
        "direction": "undervalued",
        "flags": [],
        "producer_class": {"status": "ok", "depleting": False},
        "consensus_data_status": "ok",
    }


def test_gate_consensus_data_statuses(base_verdict):
    # 'ok' passes
    passed, reasons = depth_gates.assess(base_verdict)
    assert "consensus_data_unavailable" not in reasons
    assert passed is True

    # 'stale', 'enrich_missing', 'point_in_time' fail with consensus_data_unavailable, and so does
    # 'estimates_unavailable' (reviewer ruling at the S2c review, 2026-09-28: the brief had left it
    # open; it also marks an enrich record written before estimates were fetched, and a failed fetch)
    for st in ("stale", "enrich_missing", "point_in_time", "estimates_unavailable"):
        v = dict(base_verdict, consensus_data_status=st)
        passed, reasons = depth_gates.assess(v)
        assert "consensus_data_unavailable" in reasons, f"Status {st} should have consensus_data_unavailable"
        assert passed is False


def test_gate_absent_consensus_data_status(base_verdict):
    # Absent status at gate_version = 6 fails with consensus_data_unavailable
    v6 = dict(base_verdict, gate_version=6)
    v6.pop("consensus_data_status", None)
    passed, reasons = depth_gates.assess(v6)
    assert "consensus_data_unavailable" in reasons
    assert passed is False

    # Absent status at gate_version = 5 gets pre_v3.1_gates, but NOT consensus_data_unavailable
    v5 = dict(base_verdict, gate_version=5)
    v5.pop("consensus_data_status", None)
    passed, reasons = depth_gates.assess(v5)
    assert "consensus_data_unavailable" not in reasons
    assert "pre_v3.1_gates" in reasons
    assert passed is False


def test_gate_street_fence_validation(base_verdict):
    # Valid fence passes
    passed, reasons = depth_gates.assess(base_verdict)
    assert "no_street_fence" not in reasons

    # No fence (None or missing)
    v_none = dict(base_verdict, street_fence=None)
    passed, reasons = depth_gates.assess(v_none)
    assert "no_street_fence" in reasons
    assert passed is False

    # Missing 'low'
    v_no_low = dict(base_verdict, street_fence={"high": 150.0})
    passed, reasons = depth_gates.assess(v_no_low)
    assert "no_street_fence" in reasons
    assert passed is False

    # Non-numeric 'high'
    v_str_high = dict(base_verdict, street_fence={"low": 100.0, "high": "invalid"})
    passed, reasons = depth_gates.assess(v_str_high)
    assert "no_street_fence" in reasons
    assert passed is False

    # Boolean value (should not count as numeric)
    v_bool = dict(base_verdict, street_fence={"low": True, "high": 150.0})
    passed, reasons = depth_gates.assess(v_bool)
    assert "no_street_fence" in reasons
    assert passed is False


# =============================================================================================
# 3. ASTH L2 Fixture
# =============================================================================================

def test_l2_asth_fixture():
    fixture_path = TESTS_DIR / "fixture_data" / "gate" / "ASTH_20260928_060305_verdict.json"
    assert fixture_path.exists(), f"Missing fixture: {fixture_path}"
    v = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert v["run_source"] == "orchestrator"
    assert v["gate_version"] == 6
    assert v["consensus_data_status"] == "enrich_missing"
    assert v.get("street_fence") is None

    passed, reasons = depth_gates.assess(v)
    assert passed is False
    # the recorded row was written under gate 6; from gate 7 on (revision 19) it is also older than the gate that judges it
    assert set(reasons) == {"consensus_data_unavailable", "no_street_fence", "pre_v3.1_gates"}


# =============================================================================================
# 4. Harness test: cv.main() with --pack-file
# =============================================================================================

class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_SAMPLE_MEMO = """## SECTION 12 - MACHINE-READABLE FIDUCIARY CONTRACT (Charter v3.1)
```json
{
  "contract_version": "3.1",
  "direction": "undervalued",
  "fiduciary_verdict": "PASS",
  "scenario_weights": {"base": 0.6, "bull": 0.2, "bear": 0.2},
  "terminal_method": "dual_blend",
  "cash_flow_life": "perpetual",
  "cash_flow_life_reason": "ongoing business",
  "capital_intensity": "moderate",
  "base_cf_basis": "owner_earnings_default",
  "base_cf_reason": "default owner earnings",
  "shares_used": 266333600.0,
  "shares_reason": "default shares",
  "intrinsic_value_distribution": {"base": 120.0, "bull": 160.0, "bear": 90.0},
  "blended_iv": 122.0,
  "margin_of_safety_pct": 22.0,
  "terminal_growth_rate": 0.0375,
  "terminal_reason": "anchored to macro",
  "discount_rate": 0.0898,
  "coe_adjustment_reason": "anchored to MRI",
  "valuation_frame": "equity",
  "reverse_dcf": {
    "market_implied_growth": 0.05,
    "growth_hurdle_rate": 0.06,
    "historical_median_growth": 0.08,
    "historical_p90_growth": 0.16,
    "implied_growth_verdict": "plausible",
    "valuation_tension_commentary": "reasonable"
  },
  "momentum_view": "neutral",
  "momentum_flip_condition": "none",
  "entry_timing": "buy_now",
  "invalidation_rules": ["drop in backlog"],
  "variant_perception": "market underappreciates service margins",
  "fiduciary_declarations": {
    "no_undisclosed_adjustments": true,
    "parameters_within_mandates": true,
    "installed_base_modeled_honestly": true
  }
}
```
"""

_DUMMY_PACK = """# DATA PACK - GEV

## SECTION 8 - CONSENSUS & MULTIPLES
- CONSENSUS ESTIMATES: not available — enrich record missing
"""


def _ollama_payload():
    return {"message": {"content": _SAMPLE_MEMO}, "done_reason": "stop",
            "eval_count": 500, "prompt_eval_count": 100}


def test_harness_pack_data_line_and_stamp(monkeypatch, tmp_path, screener_data_stub, capsys):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_ollama_payload()))

    frozen_dir = tmp_path / "frozen_enrich_missing"
    frozen_dir.mkdir(parents=True)
    pack_file = frozen_dir / "_pack.md"
    pack_file.write_text(_DUMMY_PACK, encoding="utf-8")

    sidecar_facts = pack_facts.from_text(_DUMMY_PACK)
    sidecar_facts["source"] = "build"
    sidecar_facts["consensus_data_status"] = "enrich_missing"
    pack_facts.write_sidecar(frozen_dir, sidecar_facts)

    out_dir = tmp_path / "out_missing"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--pack-file", str(pack_file), "--out-dir", str(out_dir)
    ])
    cv.main()

    captured = capsys.readouterr()
    assert "::PACK DATA:: enrich_missing" in captured.out

    run_dirs = list(out_dir.glob("GEV_*"))
    assert len(run_dirs) == 1
    d = run_dirs[0]
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert doc["consensus_data_status"] == "enrich_missing"


def test_harness_pack_data_ok_does_not_print(monkeypatch, tmp_path, screener_data_stub, capsys):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_ollama_payload()))

    pack_text_ok = """# DATA PACK - GEV

## SECTION 8 - CONSENSUS & MULTIPLES
- CONSENSUS ESTIMATES   [yfinance, fetched 2026-09-27]
"""
    frozen_dir = tmp_path / "frozen_ok"
    frozen_dir.mkdir(parents=True)
    pack_file = frozen_dir / "_pack.md"
    pack_file.write_text(pack_text_ok, encoding="utf-8")

    sidecar_facts = pack_facts.from_text(pack_text_ok)
    sidecar_facts["source"] = "build"
    sidecar_facts["consensus_data_status"] = "ok"
    pack_facts.write_sidecar(frozen_dir, sidecar_facts)

    out_dir = tmp_path / "out_ok"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--pack-file", str(pack_file), "--out-dir", str(out_dir)
    ])
    cv.main()

    captured = capsys.readouterr()
    assert "::PACK DATA::" not in captured.out

    run_dirs = list(out_dir.glob("GEV_*"))
    assert len(run_dirs) == 1
    d = run_dirs[0]
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))
    assert doc["consensus_data_status"] == "ok"


# =============================================================================================
# 5. Battery test: build_frozen_pack refusals
# =============================================================================================

def test_battery_build_frozen_pack_refuses_missing_and_stale(monkeypatch, tmp_path):
    target_pack = tmp_path / "battery_pack" / "XYZ" / "_pack.md"

    # 1. Refuses enrich_missing
    mock_facts_missing = pack_facts.empty()
    mock_facts_missing["consensus_data_status"] = "enrich_missing"
    pack_missing = PackText("fake pack content", facts=mock_facts_missing)
    monkeypatch.setattr(cap, "build_pack", lambda name: pack_missing)

    with pytest.raises(SystemExit) as exc:
        db.build_frozen_pack("XYZ", target_pack)
    assert "XYZ: cannot build frozen pack with consensus_data_status='enrich_missing'" in str(exc.value)
    assert not target_pack.exists()

    # 2. Refuses stale
    mock_facts_stale = pack_facts.empty()
    mock_facts_stale["consensus_data_status"] = "stale"
    pack_stale = PackText("fake pack content", facts=mock_facts_stale)
    monkeypatch.setattr(cap, "build_pack", lambda name: pack_stale)

    with pytest.raises(SystemExit) as exc:
        db.build_frozen_pack("XYZ", target_pack)
    assert "XYZ: cannot build frozen pack with consensus_data_status='stale'" in str(exc.value)
    assert not target_pack.exists()

    # 3. Accepts ok
    mock_facts_ok = pack_facts.empty()
    mock_facts_ok["consensus_data_status"] = "ok"
    pack_ok = PackText("fake pack content", facts=mock_facts_ok)
    monkeypatch.setattr(cap, "build_pack", lambda name: pack_ok)

    pack_content, reused = db.build_frozen_pack("XYZ", target_pack)
    assert target_pack.exists()
    assert reused is False
    assert (target_pack.parent / pack_facts.SIDECAR).exists()
    sidecar_data = json.loads((target_pack.parent / pack_facts.SIDECAR).read_text(encoding="utf-8"))
    assert sidecar_data["consensus_data_status"] == "ok"
