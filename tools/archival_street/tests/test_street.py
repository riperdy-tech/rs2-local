"""tools/archival_street (S1): the pool's frame, CIK and draw stages, the S0 row, the pinned set's checks and premium, and prepare at T with
a pinned external-premium set, on synthetic data (no network, no store, no ticker of any real company)."""
import hashlib
import os

import pytest

import pin_coe as PC
import pool_k2
import pool_street as S
from qwen_c.tests import test_value_checks as C
from qwen_c.value import coe

T_DATE = "2026-06-15"


# ---- the frame and CIK stages, the draw ---------------------------------------------------------------------------------------------

def test_frame_keeps_three_or_more_analysts_with_a_target_and_zero_is_a_value():
    snap = {"ZA": {"analyst_count": 3, "target_mean_delta_pct": 0.0}, "ZB": {"analyst_count": 2, "target_mean_delta_pct": 5.0},
            "ZC": {"analyst_count": 7, "target_mean_delta_pct": None}, "ZD": {"analyst_count": True, "target_mean_delta_pct": 1.0},
            "ZE": {"analyst_count": 3.0, "target_mean_delta_pct": 1.0}, "ZF": {"analyst_count": 9, "target_mean_delta_pct": float("nan")},
            "ZG": {"analyst_count": 4, "target_mean_delta_pct": -12.5}, "ZH": "not a record"}
    kept, left = S.frame_stage(snap)
    assert [t for t, _ in kept] == ["ZA", "ZG"]
    assert {r["ticker"]: r["reason"] for r in left} == {"ZB": "few_analysts", "ZC": "no_target", "ZD": "few_analysts",
                                                        "ZE": "few_analysts", "ZF": "no_target", "ZH": "few_analysts"}
    assert all(r["stage"] == "frame" for r in left)


def test_cik_one_company_per_cik_first_sorted_ticker_and_dot_as_dash():
    tmap = {"ZQ-B": ("0000000002", "Two"), "ZQ-A": ("0000000002", "Two"), "ZP": ("0000000001", "One")}
    kept = [("ZQ.B", {"analyst_count": 3}), ("ZP", {"analyst_count": 4}), ("ZQ-A", {"analyst_count": 5}), ("ZX", {"analyst_count": 6})]
    comps, left = S.cik_stage(kept, tmap)
    assert [(c["ticker"], c["cik"]) for c in comps] == [("ZP", "0000000001"), ("ZQ-A", "0000000002")]
    assert comps[1]["other_tickers"] == ["ZQ.B"] and comps[1]["street"] == {"analyst_count": 5}
    assert {r["ticker"]: r["reason"] for r in left} == {"ZQ.B": "duplicate_company", "ZX": "no_cik"}


def test_draw_order_is_the_sha256_of_the_key_and_cik():
    comps = [{"ticker": f"Z{i}", "cik": str(i).zfill(10)} for i in range(1, 30)]
    got = [c["cik"] for c in S.draw_order(comps)]
    want = sorted((c["cik"] for c in comps), key=lambda k: hashlib.sha256(("S1:2026-06-15:" + k).encode()).hexdigest())
    assert got == want and S.DRAW_KEY == "S1:2026-06-15:" and got != sorted(got)


def test_s0_row_has_k2s_fields_only_from_the_frame_row():
    from qwen_c import packet
    row = {"sector": "Technology", "industry": "Software", "country": "United States", "price": 99.0, "marketCap": 1.0, "score": 5}
    s0 = S.s0_row("ZA", "Zed Co", row, 12.345678, 4.2e9)
    assert s0 == {"symbol": "ZA", "name": "Zed Co", "sector": "Technology", "industry": "Software", "country": "United States",
                  "price": 12.3457, "marketCap": 4200000000, "Last_Updated": "2026-06-15"}
    assert set(s0) <= {k for k, _ in packet.S0_FIELDS}


def test_k2_shares_rule_takes_the_session_and_keeps_k2s_default():
    rows = [{"val": 100, "end": "2025-07-31", "filed": "2025-08-05", "accn": "a1"},
            {"val": 60, "end": "2026-04-30", "filed": "2026-05-06", "accn": "a2"}, {"val": 40, "end": "2026-04-30", "filed": "2026-05-06", "accn": "a2"},
            {"val": 999, "end": "2026-07-31", "filed": "2026-08-04", "accn": "a3"}]
    cf = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": rows}}}}}
    assert pool_k2.shares_at_T(cf) == (100, "2025-07-31", "2025-08-05")                        # K2's session 2025-10-01
    assert pool_k2.shares_at_T(cf, session=T_DATE) == (100, "2026-04-30", "2026-05-06")        # two classes of one filing, summed
    assert pool_k2.shares_at_T(cf, session="2025-08-01") is None


# ---- pin_coe: the anchors' checks, the workbook row, the manifest coe.py reads ----------------------------------------------------

def _bundle(asof="2026-06-01", degraded=False, dates=None):
    prov = {"input_dates": dates or {"DGS10": "2026-05-29"}, "degradation_reasons": ["stale"] if degraded else []}
    return {"asof": asof, "scoring_mode": "point_in_time", "degraded": degraded,
            "cost_of_capital": {"asof": asof, "degraded": degraded, "erp_basis": "universe", "risk_free": {"nominal_10y": 0.0445},
                                "sector_loadings": {"information_technology": 1.35}, "provenance": prov},
            "long_run_growth": {"asof": asof, "degraded": degraded, "terminal_g_suggestion": 0.0375,
                                "provenance": {"input_dates": {"GDPPOT": "2026-04-01"}, "degradation_reasons": []}}}


def test_check_anchors_refuses_degraded_after_T_or_missing_legs():
    assert PC.check_anchors(_bundle(), T_DATE) == []
    assert any("degraded" in p for p in PC.check_anchors(_bundle(degraded=True), T_DATE))
    assert any("asof 2026-06-16" in p for p in PC.check_anchors(_bundle(asof="2026-06-16"), T_DATE))
    assert PC.check_anchors(_bundle(dates={"DGS10": "2026-06-16"}), T_DATE) == [
        "cost_of_capital: input DGS10 dated 2026-06-16, after T 2026-06-15"]
    b = _bundle()
    b["cost_of_capital"]["risk_free"] = {}
    b["cost_of_capital"]["sector_loadings"] = {}
    b["long_run_growth"]["terminal_g_suggestion"] = None
    assert len(PC.check_anchors(b, T_DATE)) == 3


def test_erp_at_one_row_a_finite_number_within_the_bounds():
    rows = [{"Start of month": "2026-05-01", "ERP (T12m)": 0.0436}, {"Start of month": "2026-06-01", "ERP (T12m)": 0.0431},
            {"Start of month": "2026-07-01", "ERP (T12m)": "6,36%"}]
    assert PC.erp_at(rows, "2026-06-01") == 0.0431
    for month, rows_, msg in (("2026-08-01", rows, "0 rows"), ("2026-07-01", rows, "not a number"),
                              ("2026-06-01", rows + [{"Start of month": "2026-06-01", "ERP (T12m)": 0.05}], "2 rows"),
                              ("2026-06-01", [{"Start of month": "2026-06-01", "ERP (T12m)": 0.31}], "outside"),
                              ("2026-06-01", [{"Start of month": "2026-06-01", "ERP (T12m)": float("nan")}], "not a number"),
                              ("2026-06-01", [{"Start of month": "2026-06-01", "ERP (T12m)": True}], "not a number")):
        with pytest.raises(PC.Stop, match=msg):
            PC.erp_at(rows_, month)


def _pinned_dir(d):
    """A set written as pin_coe.main writes it, from its own functions."""
    b = _bundle()
    blobs = {f: PC.dump(b[k]) for k, f in PC.ANCHORS}
    blobs["external_premium.json"] = PC.dump(PC.premium_doc(0.0431, "2026-06-01", "ERPbymonth.xlsx", "cd" * 32))
    m = PC.manifest(blobs, b, "2026-06-01", "abc", "ERPbymonth.xlsx", "cd" * 32, "2026-06-01", T_DATE)
    d.mkdir()
    for f, x in blobs.items():
        (d / f).write_bytes(x)
    (d / "manifest.json").write_bytes(PC.dump(m))
    return m


def test_the_pinned_set_is_what_coe_reads(tmp_path, monkeypatch):
    m = _pinned_dir(tmp_path / "pin")
    assert m["premium"] == "external" and set(m["files"]) == set(coe.EXTERNAL_FILES)
    monkeypatch.setenv(coe.ARCHIVAL_ENV, str(tmp_path / "pin"))
    r, prov = coe.cost_of_equity("Technology", S.T)
    assert r == pytest.approx(0.0445 + (0.67 * 1.35 + 0.33) * 0.0431)
    assert prov["stamps"][-2:] == [coe.ARCHIVAL_STAMP, coe.EXTERNAL_STAMP] and prov["archival"]["legs_after_T"] == []
    assert prov["external_premium"]["source_sha256"] == "cd" * 32 and prov["closure_asof"] == "2026-06-01"


# ---- prepare at T with the pinned set --------------------------------------------------------------------------------------------

def test_prepare_succeeds_with_the_pinned_external_set_and_restores_the_environment(tmp_path, monkeypatch):
    _pinned_dir(tmp_path / "pin")
    monkeypatch.delenv(coe.ARCHIVAL_ENV, raising=False)
    monkeypatch.setattr(S.run.facts, "build", lambda *a, **k: C.facts())
    status, why, c = S.prepare_at_T("0000000001", "Technology", 4e9, "operating", None, tmp_path / "pin")
    assert (status, why) == ("ok", None) and c["premium"] == 0.0431 and c["rf"] == 0.0445
    assert c["r"] == pytest.approx(0.0445 + (0.67 * 1.35 + 0.33) * 0.0431)
    assert coe.ARCHIVAL_ENV not in os.environ


def test_prepare_refusals_leave_with_their_code(tmp_path, monkeypatch):
    _pinned_dir(tmp_path / "pin")
    monkeypatch.setattr(S.run.facts, "build", lambda *a, **k: C.facts())
    status, why, _ = S.prepare_at_T("0000000001", "Technology", 4e9, "fund", None, tmp_path / "pin")
    assert status == "refused" and why.startswith("family_not_routed")
    status, why, _ = S.prepare_at_T("0000000001", "No Such Sector", 4e9, "operating", None, tmp_path / "pin")
    assert status == "refused" and why.startswith("coe_unavailable") and "loading" in why
    (tmp_path / "pin" / "external_premium.json").write_bytes(b"{}")                   # tampered: the manifest no longer matches
    status, why, _ = S.prepare_at_T("0000000001", "Technology", 4e9, "operating", None, tmp_path / "pin")
    assert status == "refused" and why.startswith("coe_archival_sha256_mismatch")
