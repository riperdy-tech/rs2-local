"""tests/test_thesis_monitor.py — P4.5/DEP-13 thesis_monitor.py.

Covers the pure rule-evaluation core (evaluate_ticker: synthetic rules vs synthetic data ->
breached / intact / unknown, momentum flip met, momentum break -> avoid), the current-data
snapshot builders against small hand-written fixtures, and run()'s actionable-only filtering,
atomic write and --dry-run behaviour — isolated from the real cache/ and screener data throughout.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import thesis_monitor as tm  # noqa: E402
import depth_gates  # noqa: E402


# ================================================================================================
# evaluate_ticker() — pure, no I/O
# ================================================================================================

def _rule(metric="gross_margin_pct", comparator="<", threshold=30.0, window="next quarter",
          source="fundamentals_quarterly.json"):
    return {"metric": metric, "comparator": comparator, "threshold": threshold,
            "window": window, "source": source}


def test_breached_when_a_checkable_rule_fires():
    v = {"invalidation_rules": [_rule(threshold=30.0)]}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={"gross_margin_pct": 22.0}, mom={})
    assert status == "breached"
    assert checks[0]["breached"] is True
    assert checks[0]["current_value"] == 22.0


def test_intact_when_evaluated_rules_all_hold():
    v = {"invalidation_rules": [_rule(threshold=30.0)]}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={"gross_margin_pct": 45.0}, mom={})
    assert status == "intact"
    assert checks[0]["breached"] is False


def test_unknown_when_no_invalidation_rules():
    v = {"invalidation_rules": None}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={}, mom={})
    assert status == "unknown"
    assert checks == []


def test_unknown_when_current_value_missing():
    v = {"invalidation_rules": [_rule(metric="net_income")]}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={"net_income": None}, mom={})
    assert status == "unknown"
    assert checks[0]["breached"] is None
    assert checks[0]["current_value"] is None


def test_uncheckable_metric_is_excluded_from_checks_entirely():
    v = {"invalidation_rules": [_rule(metric="not_in_the_vocabulary", threshold=1)]}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={}, mom={})
    assert checks == []
    assert status == "unknown"


def test_one_breached_and_one_intact_rule_is_breached_overall():
    v = {"invalidation_rules": [_rule(metric="gross_margin_pct", threshold=30.0),
                                _rule(metric="net_income", comparator="<", threshold=0)]}
    status, checks, _, _ = tm.evaluate_ticker(
        v, fin={"gross_margin_pct": 45.0, "net_income": -100.0}, mom={})
    # net_income -100 < 0 -> breached; gross_margin_pct 45 < 30 -> False (intact)
    assert status == "breached"
    results = {c["metric"]: c["breached"] for c in checks}
    assert results["gross_margin_pct"] is False
    assert results["net_income"] is True


def test_zero_is_a_real_value_not_an_absence():
    # non-negotiable 4: filing_8k_count == 0 must evaluate normally, never read as "unknown".
    v = {"invalidation_rules": [_rule(metric="filing_8k_count", comparator=">", threshold=0)]}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={"filing_8k_count": 0}, mom={})
    assert checks[0]["breached"] is False   # 0 > 0 is False, evaluated, not unknown
    assert status == "intact"


def test_malformed_rule_missing_keys_is_dropped_not_checkable():
    v = {"invalidation_rules": [{"metric": "gross_margin_pct"}]}   # no comparator/threshold
    status, checks, _, _ = tm.evaluate_ticker(v, fin={"gross_margin_pct": 10.0}, mom={})
    assert checks == []
    assert status == "unknown"


def test_invalidation_rules_not_a_list_is_unknown_not_a_crash():
    v = {"invalidation_rules": "not a list"}
    status, checks, _, _ = tm.evaluate_ticker(v, fin={}, mom={})
    assert status == "unknown"
    assert checks == []


# ---- momentum flip / break ---------------------------------------------------------------------

def test_momentum_flip_met_flips_entry_timing_to_buy_now():
    v = {"entry_timing": "wait_for_momentum",
         "momentum_flip_condition": {"metric": "mom_12_1", "comparator": ">", "threshold": 0.10,
                                     "window_days": 30}}
    _, _, entry_timing_now, flip_met = tm.evaluate_ticker(v, fin={}, mom={"mom_12_1": 0.15})
    assert flip_met is True
    assert entry_timing_now == "buy_now"


def test_momentum_flip_not_met_keeps_wait_for_momentum():
    v = {"entry_timing": "wait_for_momentum",
         "momentum_flip_condition": {"metric": "mom_12_1", "comparator": ">", "threshold": 0.10,
                                     "window_days": 30}}
    _, _, entry_timing_now, flip_met = tm.evaluate_ticker(v, fin={}, mom={"mom_12_1": 0.02})
    assert flip_met is False
    assert entry_timing_now == "wait_for_momentum"


def test_momentum_flip_condition_ignored_when_entry_timing_is_not_wait_for_momentum():
    v = {"entry_timing": "buy_now",
         "momentum_flip_condition": {"metric": "mom_12_1", "comparator": ">", "threshold": -1,
                                     "window_days": 30}}
    _, _, entry_timing_now, flip_met = tm.evaluate_ticker(v, fin={}, mom={"mom_12_1": 0.5})
    assert flip_met is False
    assert entry_timing_now == "buy_now"


def test_momentum_break_rule_flips_buy_now_to_avoid():
    v = {"entry_timing": "buy_now",
         "momentum_break_rule": {"metric": "mom_6m", "comparator": "<", "threshold": -0.10,
                                 "window_days": 30}}
    _, _, entry_timing_now, _ = tm.evaluate_ticker(v, fin={}, mom={"mom_6m": -0.20})
    assert entry_timing_now == "avoid"


def test_momentum_break_rule_not_fired_keeps_buy_now():
    v = {"entry_timing": "buy_now",
         "momentum_break_rule": {"metric": "mom_6m", "comparator": "<", "threshold": -0.10,
                                 "window_days": 30}}
    _, _, entry_timing_now, _ = tm.evaluate_ticker(v, fin={}, mom={"mom_6m": 0.05})
    assert entry_timing_now == "buy_now"


def test_entry_timing_now_copies_through_unchanged_when_no_rules_present():
    v = {"entry_timing": "avoid"}
    _, _, entry_timing_now, flip_met = tm.evaluate_ticker(v, fin={}, mom={})
    assert entry_timing_now == "avoid"
    assert flip_met is False


# ================================================================================================
# _financial_snapshot() / _momentum_snapshot() — small hand-written fixtures
# ================================================================================================

@pytest.fixture
def sd(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(tm, "SD", d)
    return d


def _write(sd, name, doc):
    (sd / name).write_text(json.dumps(doc), encoding="utf-8")


def test_financial_snapshot_computes_revenue_yoy_and_gross_margin_from_quarterly(sd):
    quarters = [{"end": f"202{4+i//4}-{(i%4)*3+1:02d}-01", "revenue": 100.0 + i,
                 "gross_profit": 40.0 + i} for i in range(6)]
    _write(sd, "fundamentals_quarterly.json", {"tickers": {"AAA": {"quarters": quarters}}})
    _write(sd, "fundamentals_ttm.json", {"tickers": {}})
    _write(sd, "fundamentals_battery.json", {"tickers": {}})
    fin = tm._financial_snapshot("AAA", cik=None, since_date="2026-01-01")
    # newest (index 5): revenue 105, gross_profit 45; 4-quarters-back (index 1): revenue 101
    assert fin["revenue_yoy_pct"] == round((105.0 / 101.0 - 1) * 100, 2)
    assert fin["gross_margin_pct"] == round(45.0 / 105.0 * 100, 2)


def test_financial_snapshot_reads_ttm_and_battery_fields(sd):
    _write(sd, "fundamentals_quarterly.json", {"tickers": {}})
    _write(sd, "fundamentals_ttm.json", {"tickers": {"AAA": {
        "fields": {"net_income": 500.0, "ocf": 700.0, "fcf": 300.0}}}})
    _write(sd, "fundamentals_battery.json", {"tickers": {"AAA": {
        "op_margin_latest": 0.2129, "net_issuance_1y": -0.0206}}})
    fin = tm._financial_snapshot("AAA", cik=None, since_date="2026-01-01")
    assert fin["net_income"] == 500.0
    assert fin["ocf"] == 700.0
    assert fin["fcf"] == 300.0
    assert fin["operating_margin_pct"] == 21.29    # battery fraction * 100
    assert fin["net_issuance_1y"] == -0.0206        # native fraction, no _pct suffix


def test_financial_snapshot_missing_sources_are_none_not_zero(sd):
    _write(sd, "fundamentals_quarterly.json", {"tickers": {}})
    _write(sd, "fundamentals_ttm.json", {"tickers": {}})
    _write(sd, "fundamentals_battery.json", {"tickers": {}})
    fin = tm._financial_snapshot("AAA", cik=None, since_date="2026-01-01")
    for k in tm.FINANCIAL_METRICS:
        assert fin[k] is None


def test_financial_snapshot_filing_8k_count_reuses_depth_triggers(sd, monkeypatch):
    _write(sd, "fundamentals_quarterly.json", {"tickers": {}})
    _write(sd, "fundamentals_ttm.json", {"tickers": {}})
    _write(sd, "fundamentals_battery.json", {"tickers": {}})
    calls = []

    def fake_filings_since(cik, since):
        calls.append((cik, since))
        return [("8-K", "2026-09-01"), ("8-K", "2026-09-10"), ("10-Q", "2026-09-15")]
    monkeypatch.setattr(tm.depth_triggers, "_filings_since", fake_filings_since)
    fin = tm._financial_snapshot("AAA", cik="0000123", since_date="2026-08-01")
    assert fin["filing_8k_count"] == 2
    assert calls == [("0000123", "2026-08-01")]


def test_financial_snapshot_filing_8k_count_is_zero_not_none_when_cik_present_and_no_filings(sd, monkeypatch):
    _write(sd, "fundamentals_quarterly.json", {"tickers": {}})
    _write(sd, "fundamentals_ttm.json", {"tickers": {}})
    _write(sd, "fundamentals_battery.json", {"tickers": {}})
    monkeypatch.setattr(tm.depth_triggers, "_filings_since", lambda cik, since: [])
    fin = tm._financial_snapshot("AAA", cik="0000123", since_date="2026-08-01")
    assert fin["filing_8k_count"] == 0


def test_financial_snapshot_filing_8k_count_none_without_cik(sd):
    _write(sd, "fundamentals_quarterly.json", {"tickers": {}})
    _write(sd, "fundamentals_ttm.json", {"tickers": {}})
    _write(sd, "fundamentals_battery.json", {"tickers": {}})
    fin = tm._financial_snapshot("AAA", cik=None, since_date="2026-08-01")
    assert fin["filing_8k_count"] is None


def test_momentum_snapshot_reads_factor_scores(sd):
    _write(sd, "factor_scores.json", {"tickers": {"AAA": {
        "fct_momentum_state": {"mom_12_1": 0.25, "mom_6m": 0.10, "mom_1m": 0.02,
                               "high_52w_proxy": -0.05, "mom_z_sector": 1.2},
        "fct_z": {"momentum": 1.1}}}})
    mom = tm._momentum_snapshot("AAA")
    assert mom["mom_12_1"] == 0.25
    assert mom["high_52w_distance"] == -0.05
    assert mom["mom_z_sector"] == 1.2
    for k in ("above_below_200d_mean", "rs_vs_cluster_etf_3m", "rs_vs_iwm_3m",
              "realised_vol_60d", "mom_break"):
        assert mom[k] is None


def test_momentum_snapshot_absent_ticker_is_all_none(sd):
    _write(sd, "factor_scores.json", {"tickers": {}})
    mom = tm._momentum_snapshot("AAA")
    for k in tm.MOMENTUM_METRICS:
        assert mom[k] is None


# ================================================================================================
# run() — actionable-only filtering, atomic write, --dry-run
# ================================================================================================

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "THESIS_CACHE", tmp_path / "depth_thesis.json")
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(tm, "SD", d)
    for name in ("fundamentals_quarterly.json", "fundamentals_ttm.json",
                "fundamentals_battery.json", "factor_scores.json"):
        _write(d, name, {"tickers": {}})
    # Full isolation from the real screener-publish clone's cik_map.json (read-only, harmless,
    # but pinning it to None keeps this suite deterministic regardless of disk state).
    monkeypatch.setattr(tm.depth_triggers, "_cik", lambda t: None)
    return tmp_path


def _clean_verdict(ticker, **over):
    v = {"ticker": ticker, "direction": "hold", "gate_version": depth_gates.GATE_VERSION,
         "n_basis": 2, "fiduciary_verdict": "PASS", "kelly_fraction_pct": 0.0, "spread_pct": 5.0,
         "run_source": "orchestrator", "date": "2026-09-01",
         "producer_class": {"status": "ok", "depleting": False, "sector": "Technology",
                            "industry": "Software", "source": "test"},
         "invalidation_rules": [_rule(metric="net_income", comparator="<", threshold=0)]}
    v.update(over)
    return v


def test_run_evaluates_only_actionable_rows(isolated, monkeypatch):
    actionable = _clean_verdict("AAA")
    non_actionable = _clean_verdict("BBB", n_basis=1)   # single_sample -> not actionable
    monkeypatch.setattr(tm.depth_triggers, "newest_verdicts",
                        lambda: {"AAA": actionable, "BBB": non_actionable})
    summary = tm.run()
    assert summary["evaluated"] == 1
    assert "AAA" in summary["doc"]["tickers"]
    assert "BBB" not in summary["doc"]["tickers"]


def test_run_writes_the_cache_file(isolated, monkeypatch):
    monkeypatch.setattr(tm.depth_triggers, "newest_verdicts",
                        lambda: {"AAA": _clean_verdict("AAA")})
    tm.run()
    assert tm.THESIS_CACHE.exists()
    doc = json.loads(tm.THESIS_CACHE.read_text(encoding="utf-8"))
    assert "AAA" in doc["tickers"]
    assert doc["tickers"]["AAA"]["thesis_status"] in ("intact", "breached", "unknown")
    assert "evaluated_at" in doc["tickers"]["AAA"]


def test_run_dry_run_does_not_write(isolated, monkeypatch):
    monkeypatch.setattr(tm.depth_triggers, "newest_verdicts",
                        lambda: {"AAA": _clean_verdict("AAA")})
    summary = tm.run(dry_run=True)
    assert not tm.THESIS_CACHE.exists()
    assert summary["evaluated"] == 1


def test_run_empty_ledger_writes_empty_doc(isolated, monkeypatch):
    monkeypatch.setattr(tm.depth_triggers, "newest_verdicts", lambda: {})
    summary = tm.run()
    assert summary["evaluated"] == 0
    doc = json.loads(tm.THESIS_CACHE.read_text(encoding="utf-8"))
    assert doc["tickers"] == {}
    assert "asof" in doc


# ---- seeded breach / seeded flip — the exact end-to-end fixtures the phase report cites --------

def test_seeded_breach_end_to_end(isolated, monkeypatch):
    d = isolated / "data"
    _write(d, "fundamentals_quarterly.json", {"tickers": {"BREACH": {"quarters": [
        {"end": "2026-06-01", "revenue": 100.0, "gross_profit": 20.0}]}}})
    v = _clean_verdict("BREACH", invalidation_rules=[
        _rule(metric="gross_margin_pct", comparator="<", threshold=30.0)])
    monkeypatch.setattr(tm.depth_triggers, "newest_verdicts", lambda: {"BREACH": v})
    summary = tm.run()
    row = summary["doc"]["tickers"]["BREACH"]
    assert row["thesis_status"] == "breached"          # 20% gross margin < 30% threshold
    assert summary["breached"] == 1


def test_seeded_flip_end_to_end(isolated, monkeypatch):
    d = isolated / "data"
    _write(d, "factor_scores.json", {"tickers": {"FLIP": {
        "fct_momentum_state": {"mom_12_1": 0.20}}}})
    v = _clean_verdict("FLIP", entry_timing="wait_for_momentum", invalidation_rules=[],
                       momentum_flip_condition={"metric": "mom_12_1", "comparator": ">",
                                                "threshold": 0.10, "window_days": 30})
    monkeypatch.setattr(tm.depth_triggers, "newest_verdicts", lambda: {"FLIP": v})
    summary = tm.run()
    row = summary["doc"]["tickers"]["FLIP"]
    assert row["momentum_flip_met"] is True
    assert row["entry_timing_now"] == "buy_now"


# ---- P4 E5b: momentum exit for momentum-basis positions --------------------------------------

def test_momentum_exit_fired_on_negative_6m():
    v = {"position_basis": "momentum", "entry_timing": "buy_now"}
    res = tm.evaluate_ticker(v, fin={}, mom={"mom_6m": -0.01, "high_52w_distance": 0.0})
    assert res.momentum_exit is True
    assert "mom_6m" in (res.momentum_exit_reason or "")
    assert res.entry_timing_now == "avoid"
    # Backward compatible 4-tuple unpacking
    status, checks, timing_now, flip_met = res
    assert timing_now == "avoid"


def test_momentum_exit_fired_on_high_52w_below_threshold():
    v = {"position_basis": "momentum", "entry_timing": "buy_now"}
    res = tm.evaluate_ticker(v, fin={}, mom={"mom_6m": 0.10, "high_52w_distance": -0.26})
    assert res.momentum_exit is True
    assert "high_52w_distance" in (res.momentum_exit_reason or "")
    assert res.entry_timing_now == "avoid"


def test_momentum_exit_not_fired_when_within_thresholds():
    v = {"position_basis": "momentum", "entry_timing": "buy_now"}
    res = tm.evaluate_ticker(v, fin={}, mom={"mom_6m": 0.01, "high_52w_distance": -0.24})
    assert res.momentum_exit is False
    assert res.momentum_exit_reason is None
    assert res.entry_timing_now == "buy_now"


def test_non_momentum_verdict_never_gets_momentum_exit_true():
    v = {"position_basis": "value", "entry_timing": "buy_now"}
    res = tm.evaluate_ticker(v, fin={}, mom={"mom_6m": -0.10, "high_52w_distance": -0.30})
    assert res.momentum_exit is False
    assert res.momentum_exit_reason is None
    assert res.entry_timing_now == "buy_now"


def test_build_ticker_record_always_writes_momentum_exit():
    v_val = {"position_basis": "value", "entry_timing": "buy_now"}
    rec_val = tm.build_ticker_record(v_val, fin={}, mom={"mom_6m": -0.01})
    assert rec_val["momentum_exit"] is False
    assert "momentum_exit_reason" not in rec_val

    v_mom = {"position_basis": "momentum", "entry_timing": "buy_now"}
    rec_mom = tm.build_ticker_record(v_mom, fin={}, mom={"mom_6m": -0.01})
    assert rec_mom["momentum_exit"] is True
    assert "momentum_exit_reason" in rec_mom

