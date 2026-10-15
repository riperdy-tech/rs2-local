"""Unit tests for Phase 4 E5b Momentum Basis.

Covers:
- Eligibility checks at edges
- None inputs -> unknown -> ineligible
- revenue_ttm_yoy from 8 quarters, annual fallback, None
- system_exit triggers
- Section 12 JSON contract & consensus parse
- depth_pipeline band_verdict position_basis and sizing
"""
import pytest
import momentum_basis as mb

pytestmark = pytest.mark.usefixtures("crux_valid_everywhere")      # revision 19: these tests are about their own rule, not the crux
import depth_pipeline as dp
import capability_test as cap
from tools.audit_202608.consensus_valuation import extract_scorecard, select_medoid_scorecard

VALID_INVALIDATION_RULES = [
    {"metric": "mom_12_1", "comparator": "<", "threshold": -20.0,
     "window": "next reported quarter", "source": "momentum_state.json"},
    {"metric": "revenue_yoy_pct", "comparator": "<", "threshold": 0.0,
     "window": "next reported quarter", "source": "fundamentals_quarterly.json"},
]


# ---- ITEM C: Eligibility check tests -----------------------------------------------------------

def _clean_state():
    return {
        "mom_z_universe": 0.8,
        "mom_6m": 0.10,
        "high_52w_distance": -0.05,
        "regime_shift_down": False,
    }


def test_eligibility_every_check_at_edge():
    # Base clean state passes everything
    res = mb.eligibility(_clean_state(), revenue_yoy=0.10, base_iv=100.0, price=100.0)
    assert res["eligible"] is True
    assert res["first_failure"] is None

    # Check 1: mom_z_universe >= 0.5 (0.5 passes, 0.4999 fails)
    st = _clean_state()
    st["mom_z_universe"] = 0.5
    assert mb.eligibility(st, 0.10, 100.0, 100.0)["eligible"] is True
    st["mom_z_universe"] = 0.4999
    r = mb.eligibility(st, 0.10, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "mom_z_universe"

    # Check 2: mom_6m > 0 (0.0 fails, 0.0001 passes)
    st = _clean_state()
    st["mom_6m"] = 0.0001
    assert mb.eligibility(st, 0.10, 100.0, 100.0)["eligible"] is True
    st["mom_6m"] = 0.0
    r = mb.eligibility(st, 0.10, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "mom_6m"

    # Check 3: high_52w_distance >= -0.15 (-0.15 passes, -0.1501 fails)
    st = _clean_state()
    st["high_52w_distance"] = -0.15
    assert mb.eligibility(st, 0.10, 100.0, 100.0)["eligible"] is True
    st["high_52w_distance"] = -0.1501
    r = mb.eligibility(st, 0.10, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "high_52w_distance"

    # Check 4: regime_shift_down is not True (None passes, False passes, True fails)
    st = _clean_state()
    st["regime_shift_down"] = None
    assert mb.eligibility(st, 0.10, 100.0, 100.0)["eligible"] is True
    st["regime_shift_down"] = False
    assert mb.eligibility(st, 0.10, 100.0, 100.0)["eligible"] is True
    st["regime_shift_down"] = True
    r = mb.eligibility(st, 0.10, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "regime_shift_down"

    # Check 5: revenue_ttm_yoy > 0 (0.0 fails, 0.0001 passes)
    st = _clean_state()
    assert mb.eligibility(st, 0.0001, 100.0, 100.0)["eligible"] is True
    r = mb.eligibility(st, 0.0, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "revenue_ttm_yoy"

    # Check 6: base_iv / price >= 0.5 (0.5 passes, 0.4999 fails)
    st = _clean_state()
    assert mb.eligibility(st, 0.10, 50.0, 100.0)["eligible"] is True
    r = mb.eligibility(st, 0.10, 49.99, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "base_iv_to_price"


def test_eligibility_none_inputs_unknown():
    st = _clean_state()

    # None revenue_yoy -> unknown -> ineligible
    r = mb.eligibility(st, None, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "revenue_ttm_yoy"
    c = next(x for x in r["checks"] if x["check"] == "revenue_ttm_yoy")
    assert c["result"] == "unknown"

    # None base_iv -> unknown -> ineligible
    r = mb.eligibility(st, 0.10, None, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "base_iv_to_price"
    c = next(x for x in r["checks"] if x["check"] == "base_iv_to_price")
    assert c["result"] == "unknown"

    # None price -> unknown -> ineligible
    r = mb.eligibility(st, 0.10, 100.0, None)
    assert r["eligible"] is False
    assert r["first_failure"] == "base_iv_to_price"

    # momentum_state None -> every price check unknown -> first failure mom_z_universe
    r = mb.eligibility(None, 0.10, 100.0, 100.0)
    assert r["eligible"] is False
    assert r["first_failure"] == "mom_z_universe"
    for c in r["checks"][:4]:
        assert c["result"] == "unknown"


def test_system_exit():
    # mom_6m < 0 triggers exit
    fired, reason = mb.system_exit({"mom_6m": -0.01, "high_52w_distance": -0.05})
    assert fired is True
    assert "mom_6m" in reason

    # high_52w_distance < -0.25 triggers exit
    fired, reason = mb.system_exit({"mom_6m": 0.05, "high_52w_distance": -0.26})
    assert fired is True
    assert "high_52w_distance" in reason

    # -0.24 and mom_6m 0.01 -> no exit
    fired, reason = mb.system_exit({"mom_6m": 0.01, "high_52w_distance": -0.24})
    assert fired is False
    assert reason is None

    # None values never trigger
    fired, reason = mb.system_exit({"mom_6m": None, "high_52w_distance": None})
    assert fired is False
    assert reason is None

    fired, reason = mb.system_exit(None)
    assert fired is False


def test_revenue_ttm_yoy_sources(monkeypatch):
    # 1. 8 quarters with revenue -> computes from quarters
    fake_fq = {
        "tickers": {
            "TEST1": {
                "quarters": [
                    {"revenue": 100}, {"revenue": 100}, {"revenue": 100}, {"revenue": 100},  # prior 4 = 400
                    {"revenue": 120}, {"revenue": 120}, {"revenue": 120}, {"revenue": 120},  # newest 4 = 480
                ]
            }
        }
    }
    monkeypatch.setattr(mb.rs2_data, "load_json", lambda p: fake_fq if "quarterly" in str(p) else {})
    val = mb.revenue_ttm_yoy("TEST1")
    assert val == pytest.approx(480 / 400 - 1.0)  # 0.20

    # 2. Fallback to annual fundamentals_history when quarters < 8
    fake_fq_short = {"tickers": {"TEST2": {"quarters": [{"revenue": 100}] * 5}}}
    fake_fh = {
        "tickers": {
            "TEST2": {
                "2023": {"revenue": 1000},
                "2024": {"revenue": 1250},
            }
        }
    }
    def mock_load(p):
        if "quarterly" in str(p):
            return fake_fq_short
        if "history" in str(p):
            return fake_fh
        return {}
    monkeypatch.setattr(mb.rs2_data, "load_json", mock_load)
    val = mb.revenue_ttm_yoy("TEST2")
    assert val == pytest.approx(1250 / 1000 - 1.0)  # 0.25

    # 3. None when both unavailable
    monkeypatch.setattr(mb.rs2_data, "load_json", lambda p: {})
    assert mb.revenue_ttm_yoy("TEST3") is None


# ---- ITEM A & B: Contract and Parser Tests ----------------------------------------------------

def test_contract_section_12_includes_momentum_basis():
    assert '"position_basis":' in cap.TASK
    assert '"momentum_evidence":' in cap.TASK
    assert cap.PACK_REVISION == 24


def test_extract_scorecard_and_medoid_summary():
    report = """
```json:underwriting
{
  "base_iv": 110.0,
  "bull_iv": 150.0,
  "bear_iv": 80.0,
  "position_basis": " MOMENTUM ",
  "momentum_evidence": "  Backlog grew 35% YoY in Q2  ",
  "momentum_view": " CONFIRMING ",
  "entry_timing": " BUY_NOW ",
  "invalidation_rules": [
    {"metric": "mom_12_1", "comparator": "<", "threshold": -20.0, "window": "Q", "source": "momentum_state.json"}
  ]
}
```
"""
    card = extract_scorecard(report, price=100.0)
    assert card["position_basis"] == "momentum"
    assert card["momentum_evidence"] == "Backlog grew 35% YoY in Q2"
    assert card["momentum_view"] == "confirming"
    assert card["entry_timing"] == "buy_now"

    # Medoid summary carries position_basis and momentum_evidence
    runs = [{"sample": 1, "iv": 110.0, "plausible": True, "truncated": False, "scorecard": card}]
    medoid, summary = select_medoid_scorecard(runs, price=100.0)
    assert summary["position_basis"] == "momentum"
    assert summary["momentum_evidence"] == "Backlog grew 35% YoY in Q2"


# ---- ITEM D: depth_pipeline band_verdict tests ------------------------------------------------

def _pipeline_doc(price, base_iv, direction_spread, scorecard_extra=None, momentum_state=None, doc_extra=None):
    sc = {
        "base_iv": base_iv,
        "median_iv": base_iv,
        "invalidation_rules": VALID_INVALIDATION_RULES,
        "median_conviction_score": 12.0,
    }
    if scorecard_extra:
        sc.update(scorecard_extra)

    doc = {
        "ticker": "TEST",
        "price": price,
        "samples_run": 2,
        "converged": True,
        "spread_pct": 2.0,
        "median_iv": base_iv,
        "early_stop": True,
        "runs": [
            {"sample": 1, "iv": base_iv, "plausible": True, "truncated": False, "scorecard": sc},
            {"sample": 2, "iv": base_iv, "plausible": True, "truncated": False, "scorecard": sc},
        ],
        "scorecard": sc,
        "momentum_state": momentum_state or _clean_state(),
    }
    if doc_extra:
        doc.update(doc_extra)
    return doc


def test_pipeline_momentum_basis_on_hold_and_overvalued(monkeypatch):
    monkeypatch.setattr(mb, "revenue_ttm_yoy", lambda t: 0.20)
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("full", None))

    # Hold (price inside band or above med_iv within 10% MoS):
    # price 100, base_iv 95 -> direction "hold"
    sc_mom = {
        "position_basis": "momentum",
        "momentum_view": "confirming",
        "entry_timing": "buy_now",
        "momentum_evidence": "Guidance raised 20%",
        "momentum_break_rule": {"metric": "mom_6m", "comparator": "<", "threshold": 0.0},
    }
    doc_hold = _pipeline_doc(price=100.0, base_iv=95.0, direction_spread=2.0, scorecard_extra=sc_mom)
    v_hold = dp.band_verdict(doc_hold)
    assert v_hold["direction"] == "hold"
    assert v_hold["position_basis"] == "momentum"
    assert v_hold["size_hint"] == "half"
    assert v_hold["size_components"]["basis"]["bucket"] == "half"
    assert v_hold["size_components"]["basis"]["position_basis"] == "momentum"
    assert v_hold["size_components"]["mos"]["replaced_by_basis"] is True

    # Overvalued (price 100, base_iv 80 -> direction "overvalued"):
    doc_ov = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc_mom)
    v_ov = dp.band_verdict(doc_ov)
    assert v_ov["direction"] == "overvalued"
    assert v_ov["position_basis"] == "momentum"
    assert v_ov["size_hint"] == "quarter"
    assert v_hold["size_components"]["basis"]["bucket"] == "half"
    assert v_ov["size_components"]["basis"]["bucket"] == "quarter"


def test_pipeline_momentum_basis_structural_requirements_missing(monkeypatch):
    monkeypatch.setattr(mb, "revenue_ttm_yoy", lambda t: 0.20)
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("full", None))

    base_sc = {
        "position_basis": "momentum",
        "momentum_view": "confirming",
        "entry_timing": "buy_now",
        "momentum_evidence": "Guidance raised",
        "momentum_break_rule": {"metric": "mom_6m", "comparator": "<", "threshold": 0.0},
    }

    # 1. direction not in {hold, overvalued}: price 100, base_iv 130 -> direction "undervalued"
    doc_uv = _pipeline_doc(price=100.0, base_iv=130.0, direction_spread=2.0, scorecard_extra=base_sc)
    v = dp.band_verdict(doc_uv)
    assert v["position_basis"] == "none"
    assert "position_basis_mismatch:direction" in v["flags"]

    # 2. momentum_view 'contradicting' is EXPECTED for a momentum position on an overvalued call
    #    (the uptrend contradicts the valuation call by definition) and must not block the basis.
    sc2 = dict(base_sc, momentum_view="contradicting")
    doc2 = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc2)
    v2 = dp.band_verdict(doc2)
    assert "position_basis_mismatch:momentum_view" not in v2.get("flags", [])

    # 3. entry_timing not buy_now
    sc3 = dict(base_sc, entry_timing="wait_for_momentum")
    doc3 = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc3)
    v3 = dp.band_verdict(doc3)
    assert v3["position_basis"] == "none"
    assert "position_basis_mismatch:entry_timing" in v3["flags"]

    # 4. momentum_evidence empty
    sc4 = dict(base_sc, momentum_evidence="   ")
    doc4 = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc4)
    v4 = dp.band_verdict(doc4)
    assert v4["position_basis"] == "none"
    assert "position_basis_mismatch:momentum_evidence" in v4["flags"]

    # 5. momentum_break_rule missing or not dict with metric
    sc5 = dict(base_sc, momentum_break_rule=None)
    doc5 = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc5)
    v5 = dp.band_verdict(doc5)
    assert v5["position_basis"] == "none"
    assert "position_basis_mismatch:momentum_break_rule" in v5["flags"]


def test_pipeline_momentum_basis_ineligible(monkeypatch):
    monkeypatch.setattr(mb, "revenue_ttm_yoy", lambda t: 0.20)
    sc = {
        "position_basis": "momentum",
        "momentum_view": "confirming",
        "entry_timing": "buy_now",
        "momentum_evidence": "Guidance raised",
        "momentum_break_rule": {"metric": "mom_6m", "comparator": "<", "threshold": 0.0},
    }
    # mom_z_universe is 0.2 (< 0.5)
    st = _clean_state()
    st["mom_z_universe"] = 0.2
    doc = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc, momentum_state=st)
    v = dp.band_verdict(doc)
    assert v["position_basis"] == "none"
    assert "momentum_basis_ineligible:mom_z_universe" in v["flags"]

    # momentum_state is None -> ineligible:mom_z_universe
    doc_none_ms = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc, momentum_state=None)
    doc_none_ms["momentum_state"] = None
    v_none = dp.band_verdict(doc_none_ms)
    assert v_none["position_basis"] == "none"
    assert "momentum_basis_ineligible:mom_z_universe" in v_none["flags"]


def test_pipeline_value_basis_and_undervalued_sizing_unchanged(monkeypatch):
    monkeypatch.setattr(dp, "risk_bucket", lambda: ("full", None))

    # Declared value on overvalued -> none + mismatch:value_requires_undervalued
    sc_val = {"position_basis": "value"}
    doc_ov = _pipeline_doc(price=100.0, base_iv=80.0, direction_spread=2.0, scorecard_extra=sc_val)
    v_ov = dp.band_verdict(doc_ov)
    assert v_ov["position_basis"] == "none"
    assert "position_basis_mismatch:value_requires_undervalued" in v_ov["flags"]

    # Declared value on undervalued -> value, sizing unchanged
    # base_iv 130 vs price 100 -> MoS 30% ("full"), dispersion 2% ("full"), conviction 12 ("full") -> "full"
    doc_uv = _pipeline_doc(price=100.0, base_iv=130.0, direction_spread=2.0, scorecard_extra=sc_val)
    v_uv = dp.band_verdict(doc_uv)
    assert v_uv["direction"] == "undervalued"
    assert v_uv["position_basis"] == "value"
    assert v_uv["size_hint"] == "full"
    assert "basis" not in v_uv["size_components"]
    assert "replaced_by_basis" not in v_uv["size_components"]["mos"]


def test_momentum_eligibility_carries_the_price_facts_date(monkeypatch):
    # revision 10 (APH (b)): the price facts were a week older than T0 and z passed by 3.5 bp
    monkeypatch.setattr(mb, "revenue_ttm_yoy", lambda t: 0.20)
    sc = {"position_basis": "momentum", "momentum_view": "confirming", "entry_timing": "buy_now",
          "momentum_evidence": "Guidance raised",
          "momentum_break_rule": {"metric": "mom_6m", "comparator": "<", "threshold": 0.0}}
    state = dict(_clean_state(), price_asof="2026-09-17")
    v = dp.band_verdict(_pipeline_doc(price=100.0, base_iv=100.0, direction_spread=2.0, scorecard_extra=sc,
                                      momentum_state=state))
    assert v["momentum_eligibility"]["momentum_asof"] == "2026-09-17"
