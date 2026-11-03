"""SPEC_m3q §2: qwen_c/value/coe.py, the code-owned cost of equity, with the anchor accessors stubbed."""
from datetime import datetime, timezone

import pytest

from qwen_c.value import coe, desk

T = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def anchors(monkeypatch):
    def set_(rf=0.05, ga=0.0375, load=(1.25, 1.375), erp=(0.0417, "2026-10-04", None), rf_src="(x,2026-10-29)"):
        monkeypatch.setattr(coe.rs2_data, "anchor_risk_free_rate", lambda: (rf, rf_src))
        monkeypatch.setattr(coe.rs2_data, "anchor_terminal_g", lambda: (ga, "anchor_long_run_growth(2026-10-29)"))
        monkeypatch.setattr(coe.rs2_data, "coe_loading", lambda s: load)
        monkeypatch.setattr(coe.rs2_data, "reference_closure", lambda p=None: erp)
    return set_


def test_formula_and_provenance(anchors):
    anchors()
    r, prov = coe.cost_of_equity("Technology", T, closure="x")
    assert r == pytest.approx(max(0.05, 0.0375) + 1.25 * 0.0417)
    assert prov["closure_asof"] == "2026-10-04" and prov["stamps"] == ["coe_leg_undated:loading"]


def test_growth_anchor_above_rf_is_the_floor(anchors):
    anchors(rf=0.03, ga=0.0375)
    assert coe.cost_of_equity("X", T, closure="x")[0] == pytest.approx(0.0375 + 1.25 * 0.0417)


def test_missing_leg_is_refused_never_substituted(anchors):
    anchors(erp=(None, None, "no_reference_closure_artifact"))
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("X", T, closure="x")
    assert e.value.code == "coe_unavailable" and "no_reference_closure_artifact" in str(e.value)


def test_anchor_after_T_refused_unless_allowed_and_then_stamped(anchors):
    anchors(rf_src="(x,2026-11-02)")
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("X", T, closure="x")
    assert e.value.code == "coe_anchor_after_T"
    assert "anchor_after_T" in coe.cost_of_equity("X", T, closure="x", allow_after_T=True)[1]["stamps"]


def test_closure_path_is_the_main_checkouts_cache():
    p = coe.closure_path()
    assert p.name == "reference_closure.json" and p.parent.name == "cache"


# ---- the archival mode (J2 v0.2 section 7 item 1): OFF unless RS2_ARCHIVAL_COE_DIR names a pinned, hashed directory ----------------

import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import date, timedelta  # noqa: E402

T_ARCH = datetime(2025, 12, 31, 21, 0, tzinfo=timezone.utc)
_REAL_CLOSURE = coe.rs2_data.reference_closure          # read at collection, before the root conftest's autouse stub replaces it


@pytest.fixture
def real_closure(monkeypatch):
    """The accessor under test is the real reference_closure (the root conftest stubs it for every other test)."""
    monkeypatch.setattr(coe.rs2_data, "reference_closure", _REAL_CLOSURE)


def _payloads(asof="2026-09-23", degraded=False):
    coc = {"asof": asof, "erp_basis": "index", "risk_free": {"nominal_10y": 0.042}, "sector_loadings": {"information_technology": 1.2}}
    lrg = {"asof": asof, "terminal_g_suggestion": 0.038, "degraded": degraded}
    clo = {"asof": asof, "erp": 0.045, "flag": None, "gap": 0.0, "revision": coe.rs2_data.REFERENCE_CLOSURE_REVISION, "members": 400,
           "coverage_share": 0.8, "aggregate": {"constituents_without_marker": 0}}
    return {"cost_of_capital_anchor.json": coc, "long_run_growth_anchor.json": lrg, "reference_closure.json": clo}


def _pin(d, payloads, tamper=None, drop=None):
    d.mkdir(parents=True, exist_ok=True)
    files = {}
    for f, p in payloads.items():
        b = json.dumps(p).encode()
        (d / f).write_bytes(b)
        files[f] = {"sha256": hashlib.sha256(b).hexdigest()}
    if tamper:
        (d / tamper).write_bytes((d / tamper).read_bytes() + b" ")
    if drop:
        files.pop(drop)
    (d / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return hashlib.sha256((d / "manifest.json").read_bytes()).hexdigest()


@pytest.fixture
def live_forbidden(monkeypatch, real_closure):
    """The live accessors must not be read in the archival mode."""
    def boom(*a, **k):
        raise AssertionError("a live anchor accessor was read in the archival mode")
    for name in ("anchor_risk_free_rate", "anchor_terminal_g", "coe_loading"):
        monkeypatch.setattr(coe.rs2_data, name, boom)


def test_without_the_variable_the_live_path_runs_unchanged(anchors, monkeypatch):
    monkeypatch.delenv(coe.ARCHIVAL_ENV, raising=False)
    anchors()
    r, prov = coe.cost_of_equity("Technology", T, closure="x")
    assert coe.archival_dir() is None and "archival" not in prov and coe.ARCHIVAL_STAMP not in prov["stamps"]
    assert prov["stamps"] == ["coe_leg_undated:loading"] and prov["version"] == "m3q.coe.v1"
    monkeypatch.setenv(coe.ARCHIVAL_ENV, "   ")                            # set but empty: still the live path
    assert coe.cost_of_equity("Technology", T, closure="x") == (r, prov)
    anchors(rf_src="(x,2026-11-02)")                                      # and the live after-T rule still refuses
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("X", T, closure="x")
    assert e.value.code == "coe_anchor_after_T"


def test_the_archival_mode_reads_the_pinned_copies_skips_after_T_and_age_and_stamps(tmp_path, monkeypatch, live_forbidden):
    msha = _pin(tmp_path / "pin", _payloads(asof="2026-09-23"))           # after T 2025-12-31 and more than 45 days before today
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "pin"))
    r, prov = coe.cost_of_equity("Technology", T_ARCH)
    assert r == pytest.approx(max(0.042, 0.038) + (0.67 * 1.2 + 0.33) * 0.045)
    assert coe.ARCHIVAL_STAMP in prov["stamps"] and "anchor_after_T" not in prov["stamps"]
    a = prov["archival"]
    assert a["manifest_sha256"] == msha and a["version"] == coe.ARCHIVAL_VERSION and set(a["files"]) == set(coe.ARCHIVAL_FILES)
    assert sorted(a["legs_after_T"]) == ["closure_erp", "g_anchor", "rf"] and prov["closure_asof"] == "2026-09-23"


def test_a_mismatched_sha256_refuses(tmp_path, monkeypatch, live_forbidden):
    for f in coe.ARCHIVAL_FILES:
        d = tmp_path / f.split(".")[0]
        _pin(d, _payloads(), tamper=f)
        monkeypatch.setenv(coe.ARCHIVAL_ENV, str(d))
        with pytest.raises(desk.DeskRefusal) as e:
            coe.cost_of_equity("Technology", T_ARCH)
        assert e.value.code == "coe_archival_sha256_mismatch" and f in str(e.value)


def test_an_incomplete_or_absent_pin_refuses(tmp_path, monkeypatch, live_forbidden):
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "nowhere"))
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("Technology", T_ARCH)
    assert e.value.code == "coe_archival_unreadable"
    _pin(tmp_path / "partial", _payloads(), drop="reference_closure.json")
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "partial"))
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("Technology", T_ARCH)
    assert e.value.code == "coe_archival_unreadable" and "reference_closure.json" in str(e.value)


def test_the_archival_mode_keeps_every_rule_but_the_age_and_after_T(tmp_path, monkeypatch, live_forbidden):
    _pin(tmp_path / "deg", _payloads(degraded=True))
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "deg"))
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("Technology", T_ARCH)
    assert e.value.code == "coe_unavailable" and "g_anchor" in str(e.value)
    p = _payloads()
    p["reference_closure.json"]["flag"] = "upper_bound"
    _pin(tmp_path / "flag", p)
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "flag"))
    with pytest.raises(desk.DeskRefusal) as e:
        coe.cost_of_equity("Technology", T_ARCH)
    assert e.value.code == "coe_unavailable" and "bound_flag" in str(e.value)


def test_archival_legs_equal_the_live_accessors_on_the_same_fresh_payloads(tmp_path, monkeypatch, real_closure):
    p = _payloads(asof=date.today().isoformat())
    _pin(tmp_path / "pin", p)
    monkeypatch.setattr(coe.rs2_data, "load_anchors", lambda force=False: {"cost_of_capital": p["cost_of_capital_anchor.json"],
                                                                            "long_run_growth": p["long_run_growth_anchor.json"]})
    T_now = datetime.now(timezone.utc) + timedelta(days=2)               # after the local date the payloads carry, in any zone
    monkeypatch.delenv(coe.ARCHIVAL_ENV, raising=False)
    r_live, live = coe.cost_of_equity("Technology", T_now, closure=tmp_path / "pin" / "reference_closure.json")
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "pin"))
    r_arch, arch = coe.cost_of_equity("Technology", T_now)
    assert r_arch == r_live
    assert {k: v for k, v in arch.items() if k not in ("archival", "stamps")} == {k: v for k, v in live.items() if k != "stamps"}
    assert arch["stamps"] == live["stamps"] + [coe.ARCHIVAL_STAMP]
