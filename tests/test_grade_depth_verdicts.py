"""tests/test_grade_depth_verdicts.py — TRK-06 (P2.1).

1. BYTE-AGREEMENT FIXTURE: a 5-row fixture whose expected price-derived fields (return_pct,
   entry_date, exit_date, excess_iwm/spy/qqq_pct) were computed once by hand AND once by running
   the actual stock-screener grader (`origin/main:scripts/grade_rs2_verdicts.py`) against this
   exact fixture — both agree, and are hardcoded here (EXPECTED below) as the source of truth.
   `grade_depth_verdicts.grade_rows` must reproduce them exactly for every row the 3-day
   horizon-shortfall guard does not touch (AAA, BBB, CCC, EEE); DDD is the guard's own case (2).
2. THE GUARD: DDD's price cache runs dry 5 calendar days short of its 30-day target. The
   unguarded screener grader graded it anyway (return_pct=10.0, excess_iwm_pct=8.0 — verified by
   hand-running the screener grader against this fixture). This module must NOT grade it — it
   must count as pending instead.
3. `actionable` is recomputed via depth_gates.assess, never read from a ledger stamp.
4. Nomination-context joins (dual-door profiles, factor-signal log) respect the 10-day window
   and never guess.
5. Aggregation: bucket_stats' t-stat/inconclusive flag, cut()'s multi-label mode, tercile_cut.
6. The generated caveats block states the pre-current-gates share prominently.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import grade_depth_verdicts as g  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Fixture — see module docstring. Round numbers throughout so hand verification is trivial.
# ═══════════════════════════════════════════════════════════════════════════════════════════

ROWS = [
    {"ticker": "AAA", "date": "2026-01-05", "consensus_dir": "AAA_20260105_1",
     "direction": "undervalued", "size_hint": "half", "spread_pct": 10.0, "n_basis": 2,
     "early_stop": False, "conviction_score": 8.0, "business_quality_moat": 3.0,
     "kelly_fraction_pct": 5.0, "mos_vs_median_pct": 12.0, "mos_vs_base_pct": 9.0,
     "pack_revision": 3, "gate_version": 2, "fiduciary_verdict": "PASS",
     "run_source": "orchestrator"},
    {"ticker": "BBB", "date": "2026-01-06", "consensus_dir": "BBB_20260106_1",
     "direction": "overvalued", "size_hint": "quarter", "spread_pct": 40.0, "n_basis": 3,
     "early_stop": False, "conviction_score": 4.0, "business_quality_moat": 2.0,
     "kelly_fraction_pct": 0.0, "mos_vs_median_pct": -20.0, "mos_vs_base_pct": -18.0,
     "pack_revision": 3, "gate_version": 1, "fiduciary_verdict": "PASS",
     "run_source": "manual"},
    {"ticker": "CCC", "date": "2026-01-07", "consensus_dir": "CCC_20260107_1",
     "direction": "hold", "size_hint": "starter", "spread_pct": 5.0, "n_basis": 1,
     "early_stop": True, "conviction_score": 5.0, "business_quality_moat": 4.0,
     "kelly_fraction_pct": 1.0, "mos_vs_median_pct": 0.0, "mos_vs_base_pct": 0.0,
     "pack_revision": 3, "gate_version": 2, "fiduciary_verdict": "PASS",
     "run_source": "orchestrator"},
    # DDD: cache runs dry at 2026-02-02, 5 calendar days short of the 30d target (2026-02-07).
    # Also carries `supersedes` -> must be tagged superseded_prior_version, graded normally.
    {"ticker": "DDD", "date": "2026-01-08", "consensus_dir": "DDD_20260108_1",
     "direction": "undervalued", "size_hint": "full", "spread_pct": 34.5, "n_basis": 2,
     "early_stop": False, "conviction_score": 9.0, "business_quality_moat": 3.5,
     "kelly_fraction_pct": 11.0, "mos_vs_median_pct": 30.0, "mos_vs_base_pct": 25.0,
     "pack_revision": 3, "gate_version": 2, "fiduciary_verdict": "PASS",
     "run_source": "orchestrator", "supersedes": {"n_basis": 1}},
    {"ticker": "EEE", "date": "2026-01-09", "consensus_dir": "EEE_20260109_1",
     "direction": "undervalued", "size_hint": "half", "spread_pct": 33.0, "n_basis": 2,
     "early_stop": False, "conviction_score": 6.0, "business_quality_moat": 2.5,
     "kelly_fraction_pct": 3.0, "mos_vs_median_pct": 15.0, "mos_vs_base_pct": 11.0,
     "pack_revision": 3, "gate_version": 2, "fiduciary_verdict": "PASS",
     "run_source": "orchestrator"},
]

PRICES = {
    "AAA": {"2026-01-05": 100.00, "2026-02-04": 110.00},
    "BBB": {"2026-01-06": 50.00, "2026-02-05": 45.00},
    "CCC": {"2026-01-07": 20.00, "2026-02-06": 22.00},
    "DDD": {"2026-01-08": 40.00, "2026-02-02": 44.00},
    "EEE": {"2026-01-09": 80.00, "2026-02-08": 76.00},
    "IWM": {"2026-01-05": 50.00, "2026-02-04": 52.00,
            "2026-01-06": 50.00, "2026-02-05": 51.00,
            "2026-01-07": 50.00, "2026-02-06": 50.50,
            "2026-01-08": 50.00, "2026-02-02": 51.00, "2026-02-07": 51.20,
            "2026-01-09": 50.00, "2026-02-08": 49.00},
    "SPY": {"2026-01-05": 400.00, "2026-02-04": 408.00,
            "2026-01-06": 400.00, "2026-02-05": 404.00,
            "2026-01-07": 400.00, "2026-02-06": 402.00,
            "2026-01-08": 400.00, "2026-02-02": 406.00, "2026-02-07": 407.00,
            "2026-01-09": 400.00, "2026-02-08": 396.00},
    "QQQ": {"2026-01-05": 300.00, "2026-02-04": 315.00,
            "2026-01-06": 300.00, "2026-02-05": 306.00,
            "2026-01-07": 300.00, "2026-02-06": 303.00,
            "2026-01-08": 300.00, "2026-02-02": 309.00, "2026-02-07": 310.00,
            "2026-01-09": 300.00, "2026-02-08": 291.00},
}

# Computed once by hand AND once by running scripts/grade_rs2_verdicts.py (origin/main) against
# this exact ROWS/PRICES fixture with horizons=[30] — both agree. DDD is deliberately absent: the
# unguarded screener grader graded it (return_pct=10.0, entry_date=2026-01-08,
# exit_date=2026-02-02, excess_iwm_pct=8.0, excess_spy_pct=8.5, excess_qqq_pct=7.0) but this
# module's guard must not.
EXPECTED = {
    "AAA": {"return_pct": 10.0, "entry_date": "2026-01-05", "exit_date": "2026-02-04",
            "excess_iwm_pct": 6.0, "excess_spy_pct": 8.0, "excess_qqq_pct": 5.0},
    "BBB": {"return_pct": -10.0, "entry_date": "2026-01-06", "exit_date": "2026-02-05",
            "excess_iwm_pct": -12.0, "excess_spy_pct": -11.0, "excess_qqq_pct": -12.0},
    "CCC": {"return_pct": 10.0, "entry_date": "2026-01-07", "exit_date": "2026-02-06",
            "excess_iwm_pct": 9.0, "excess_spy_pct": 9.5, "excess_qqq_pct": 9.0},
    "EEE": {"return_pct": -5.0, "entry_date": "2026-01-09", "exit_date": "2026-02-08",
            "excess_iwm_pct": -3.0, "excess_spy_pct": -4.0, "excess_qqq_pct": -2.0},
}


def _grade():
    return g.grade_rows(ROWS, PRICES, [30], None, None, [])


def test_byte_agreement_with_screener_grader():
    graded, pending, missing = _grade()
    by_ticker = {row["ticker"]: row for row in graded}
    assert set(by_ticker) == {"AAA", "BBB", "CCC", "EEE"}     # DDD excluded by the guard
    for ticker, expected in EXPECTED.items():
        row = by_ticker[ticker]
        for field, val in expected.items():
            assert row[field] == val, f"{ticker}.{field}: {row[field]!r} != {val!r}"
    assert missing == {"entry": [], "exit": []}


def test_horizon_shortfall_guard_excludes_ddd_as_pending():
    """DDD's 30d exit resolves 5 calendar days short of target (> EXIT_TARGET_TOLERANCE_DAYS=3):
    must be pending, not graded on the truncated window the unguarded screener grader accepted."""
    graded, pending, missing = _grade()
    assert "DDD" not in {row["ticker"] for row in graded}
    assert pending == 1


def test_guard_boundary_exactly_3_days_short_is_graded():
    prices = {**PRICES, "DDD": {"2026-01-08": 40.00, "2026-02-04": 44.00}}  # exactly 3d short
    graded, pending, missing = g.grade_rows(ROWS, prices, [30], None, None, [])
    ddd = next(row for row in graded if row["ticker"] == "DDD")
    assert ddd["exit_date"] == "2026-02-04"
    assert pending == 0


def test_guard_4_days_short_is_not_graded():
    prices = {**PRICES, "DDD": {"2026-01-08": 40.00, "2026-02-03": 44.00}}  # 4d short
    graded, pending, missing = g.grade_rows(ROWS, prices, [30], None, None, [])
    assert "DDD" not in {row["ticker"] for row in graded}
    assert pending == 1


# ═══════════════════════════════════════════════════════════════════════════════════════════
# actionable recomputed via depth_gates.assess — never trusted from a ledger stamp
# ═══════════════════════════════════════════════════════════════════════════════════════════

def test_actionable_recomputed_per_row():
    graded, _, _ = _grade()
    by_ticker = {row["ticker"]: row for row in graded}
    aaa = by_ticker["AAA"]
    assert aaa["actionable"] is True
    assert aaa["actionable_reasons"] == []

    bbb = by_ticker["BBB"]      # gate_version=1 (<2) AND run_source=manual
    assert bbb["actionable"] is False
    assert bbb["actionable_reasons"] == ["pre_v3.1_gates", "non_production_row"]

    ccc = by_ticker["CCC"]      # n_basis == 1
    assert ccc["actionable"] is False
    assert ccc["actionable_reasons"] == ["single_sample"]

    eee = by_ticker["EEE"]      # undervalued, spread_pct=33 > 25
    assert eee["actionable"] is False
    assert eee["actionable_reasons"] == ["high_dispersion"]


def test_superseded_prior_version_tagged_not_dropped():
    graded, _, _ = _grade()
    by_ticker = {row["ticker"]: row for row in graded}
    assert by_ticker["AAA"]["superseded_prior_version"] is False
    # DDD carries `supersedes` but is excluded from `graded` by the guard in this fixture —
    # prove the tag itself on a row that IS graded, using the boundary-case price series.
    prices = {**PRICES, "DDD": {"2026-01-08": 40.00, "2026-02-04": 44.00}}
    graded2, _, _ = g.grade_rows(ROWS, prices, [30], None, None, [])
    ddd = next(row for row in graded2 if row["ticker"] == "DDD")
    assert ddd["superseded_prior_version"] is True


def test_ledger_source_and_consensus_dir_carried():
    rows = [dict(r, _ledger_source="production") for r in ROWS]
    graded, _, _ = g.grade_rows(rows, PRICES, [30], None, None, [])
    aaa = next(row for row in graded if row["ticker"] == "AAA")
    assert aaa["ledger_source"] == "production"
    assert aaa["consensus_dir"] == "AAA_20260105_1"


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Nomination context — 10-day window, never guessed
# ═══════════════════════════════════════════════════════════════════════════════════════════

PROFILES = {"AAA": {"sector": "Technology", "cluster": "tech_semis",
                    "nominated_doors": ["DOOR_1_COMPOUNDER"],
                    "z_momentum": 1.2, "z_value": -0.3, "z_exp_gap": 0.8}}


def test_dual_door_context_within_window():
    ctx = g.dual_door_context("AAA", "2026-01-10", PROFILES, "2026-01-05T00:00:00Z")
    assert ctx["sector"] == "Technology"
    assert ctx["z_momentum"] == 1.2
    assert ctx["nominated_doors"] == ["DOOR_1_COMPOUNDER"]


def test_dual_door_context_outside_window_is_none():
    ctx = g.dual_door_context("AAA", "2026-01-20", PROFILES, "2026-01-05T00:00:00Z")
    assert ctx == {"sector": None, "cluster": None, "nominated_doors": None,
                   "z_momentum": None, "z_value": None, "z_exp_gap": None}


def test_dual_door_context_missing_ticker_is_none():
    ctx = g.dual_door_context("ZZZ", "2026-01-06", PROFILES, "2026-01-05T00:00:00Z")
    assert ctx["sector"] is None


def test_dual_door_context_missing_file_is_none():
    ctx = g.dual_door_context("AAA", "2026-01-06", None, None)
    assert ctx["sector"] is None


SIGNAL_RUNS = [
    {"snapshot_date": "2026-01-04", "signals": [{"symbol": "AAA", "fct_band": "research_now",
                                                  "fct_rank": 3}]},
    {"snapshot_date": "2026-01-20", "signals": [{"symbol": "AAA", "fct_band": "watchlist",
                                                  "fct_rank": 50}]},
]


def test_factor_signal_context_picks_nearest_run_within_window():
    ctx = g.factor_signal_context("AAA", "2026-01-05", SIGNAL_RUNS)
    assert ctx == {"fct_band": "research_now", "fct_rank": 3}   # 01-04 is 1 day away, not 01-20


def test_factor_signal_context_outside_window_is_none():
    ctx = g.factor_signal_context("AAA", "2026-02-01", SIGNAL_RUNS)   # neither run within 10d
    assert ctx == {"fct_band": None, "fct_rank": None}


def test_factor_signal_context_ticker_not_in_run_is_none():
    ctx = g.factor_signal_context("ZZZ", "2026-01-05", SIGNAL_RUNS)
    assert ctx == {"fct_band": None, "fct_rank": None}


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════════════════════════════════

def _fake_graded(n, ticker_prefix="T", excess=1.0):
    return [{"ticker": f"{ticker_prefix}{i}", "return_pct": excess, "excess_iwm_pct": excess}
            for i in range(n)]


def test_bucket_stats_inconclusive_below_min_n():
    s = g.bucket_stats(_fake_graded(5))
    assert s["n_verdicts"] == 5
    assert s["inconclusive"] is True


def test_bucket_stats_conclusive_at_min_n():
    s = g.bucket_stats(_fake_graded(10))
    assert s["inconclusive"] is False


def test_bucket_stats_t_stat_none_for_single_row():
    s = g.bucket_stats(_fake_graded(1))
    assert s["t_stat_excess_iwm_ignoring_overlap"] is None


def test_bucket_stats_t_stat_computed():
    members = [{"ticker": "A", "return_pct": v, "excess_iwm_pct": v} for v in
               (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0)]
    s = g.bucket_stats(members)
    import statistics
    mean = statistics.mean(v for v in range(1, 11))
    sd = statistics.stdev(range(1, 11))
    expected_t = round(mean / (sd / (10 ** 0.5)), 3)
    assert s["t_stat_excess_iwm_ignoring_overlap"] == expected_t


def test_cut_excludes_none_keys():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "sector": "Tech"},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1, "sector": None}]
    result = g.cut(rows, lambda r: r["sector"], "sector")
    assert set(result["buckets"]) == {"Tech"}


def test_cut_multi_label_counts_row_in_every_bucket():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1,
             "nominated_doors": ["DOOR_2_VALUE_GAP", "GLOBAL_WILDCARD"]},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1,
             "nominated_doors": ["DOOR_2_VALUE_GAP"]}]
    result = g.cut(rows, lambda r: r.get("nominated_doors"), "nominated_doors", multi=True)
    assert result["buckets"]["DOOR_2_VALUE_GAP"]["n_verdicts"] == 2
    assert result["buckets"]["GLOBAL_WILDCARD"]["n_verdicts"] == 1


def test_tercile_cut_splits_into_thirds():
    rows = [{"ticker": f"T{i}", "return_pct": i, "excess_iwm_pct": i, "conviction_score": i}
            for i in range(1, 10)]      # 1..9
    result = g.tercile_cut(rows, "conviction_score", "conviction tercile")
    assert set(result["buckets"]) <= {"T1_low", "T2_mid", "T3_high"}
    total = sum(b["n_verdicts"] for b in result["buckets"].values())
    assert total == 9


def test_tercile_cut_respects_predicate():
    rows = [{"ticker": f"T{i}", "return_pct": i, "excess_iwm_pct": i, "z_momentum": i,
             "direction": "undervalued" if i % 2 == 0 else "overvalued"}
            for i in range(1, 13)]
    result = g.tercile_cut(rows, "z_momentum", "z_momentum tercile",
                           predicate=lambda r: r["direction"] == "undervalued")
    total = sum(b["n_verdicts"] for b in result["buckets"].values())
    assert total == 6      # only the 6 "undervalued" rows


def test_tercile_cut_excludes_none_field():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": None},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 2},
            {"ticker": "C", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 3},
            {"ticker": "D", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 4}]
    result = g.tercile_cut(rows, "conviction_score", "conviction tercile")
    total = sum(b["n_verdicts"] for b in result["buckets"].values())
    assert total == 3      # the None-conviction row (A) is excluded, not guessed into a bucket


def test_tercile_cut_too_few_rows_yields_no_buckets():
    """Fewer than 3 usable rows cannot be split into thirds — no bucket is fabricated."""
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 2},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 3}]
    result = g.tercile_cut(rows, "conviction_score", "conviction tercile")
    assert result["buckets"] == {}


def test_spread_bucket_boundaries():
    assert g.spread_bucket({"spread_pct": 15.0}) == "<=15"
    assert g.spread_bucket({"spread_pct": 15.01}) == "15-30"
    assert g.spread_bucket({"spread_pct": 30.0}) == "15-30"
    assert g.spread_bucket({"spread_pct": 30.01}) == ">30"
    assert g.spread_bucket({"spread_pct": None}) is None


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Caveats — the pre-current-gates share must be stated prominently
# ═══════════════════════════════════════════════════════════════════════════════════════════

def test_caveats_report_pre_gates_share():
    # Of the 4 graded rows (AAA/BBB/CCC/EEE), only BBB carries gate_version=1 (< GATE_VERSION):
    # the other three are non-actionable for OTHER reasons (single_sample, high_dispersion) but
    # are NOT pre-gates — the caveat must report exactly that share, not overclaim.
    graded, _, _ = _grade()
    caveats = g.build_caveats(ROWS, graded)
    joined = " ".join(caveats)
    assert "PRE-CURRENT-GATES" in joined
    assert "1 of 4" in joined
    assert "NO CONCLUSION ABOUT THE CURRENT ANALYST" in joined


def test_caveats_report_all_pre_gates_when_every_row_is():
    rows = [dict(r) for r in ROWS]
    for r in rows:
        r.pop("gate_version", None)     # every row now pre-v3.1-gates, like today's real ledgers
    graded, _, _ = g.grade_rows(rows, PRICES, [30], None, None, [])
    caveats = g.build_caveats(rows, graded)
    joined = " ".join(caveats)
    assert "ALL of them" in joined


def test_caveats_window_and_regime_present():
    graded, _, _ = _grade()
    caveats = g.build_caveats(ROWS, graded)
    joined = " ".join(caveats)
    assert "2026-01-05" in joined and "2026-01-09" in joined
    assert "Regime at report time" in joined


def test_caveats_report_nomination_context_coverage():
    graded, _, _ = _grade()      # none of these rows have a dual-door profile passed in -> 0/4
    caveats = g.build_caveats(ROWS, graded)
    joined = " ".join(caveats)
    assert "Nomination context" in joined
    assert "joined for 0 of 4" in joined


def test_regime_string_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MRI_CURRENT_REGIME", tmp_path / "nope.json")
    assert "unavailable" in g.regime_string()


def test_regime_string_reads_season_headline(tmp_path, monkeypatch):
    p = tmp_path / "current_regime.json"
    p.write_text(json.dumps({"season_headline": "goldilocks", "date": "2026-09-01"}),
                encoding="utf-8")
    monkeypatch.setattr(g, "MRI_CURRENT_REGIME", p)
    assert g.regime_string() == "goldilocks (as of 2026-09-01)"


# ═══════════════════════════════════════════════════════════════════════════════════════════
# End-to-end main() — offline, fully redirected away from cache/ and reports/
# ═══════════════════════════════════════════════════════════════════════════════════════════

def test_main_offline_end_to_end(tmp_path, monkeypatch):
    ledger = tmp_path / "depth_ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n", encoding="utf-8")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    monkeypatch.setattr(g, "LEDGERS", {"production": ledger, "archive": empty,
                                       "ondemand": empty, "test": empty})
    price_cache = tmp_path / "depth_outcome_prices.json"
    price_cache.write_text(json.dumps(PRICES), encoding="utf-8")
    monkeypatch.setattr(g, "PRICE_CACHE_JSON", price_cache)
    outcomes = tmp_path / "depth_outcomes.json"
    report = tmp_path / "depth_outcomes_report.md"
    monkeypatch.setattr(g, "OUTCOMES_JSON", outcomes)
    monkeypatch.setattr(g, "REPORT_MD", report)
    monkeypatch.setattr(g, "DUAL_DOOR_JSON", tmp_path / "no_dual_door.json")
    monkeypatch.setattr(g, "FACTOR_SIGNAL_LOG", tmp_path / "no_signal_log.jsonl")
    monkeypatch.setattr(g, "MRI_CURRENT_REGIME", tmp_path / "no_regime.json")

    monkeypatch.setattr(sys, "argv", ["grade_depth_verdicts.py", "--offline",
                                      "--ledgers", "production", "--horizons", "30"])
    rc = g.main()
    assert rc == 0

    payload = json.loads(outcomes.read_text(encoding="utf-8"))
    assert payload["graded_verdict_horizons"] == 4       # DDD guarded out
    assert payload["pending_verdict_horizons"] == 1
    assert payload["ledger_row_counts"] == {"production": 5}
    assert "PRE-CURRENT-GATES" in " ".join(payload["caveats"])
    assert payload["gradeable_counts_per_horizon"]["30"]["total"] == 4
    assert payload["gradeable_counts_per_horizon"]["30"]["by_ledger_source"] == {"production": 4}

    report_text = report.read_text(encoding="utf-8")
    assert "Depth Verdict Outcome Report" in report_text
    assert "PRE-CURRENT-GATES" in report_text
    assert "30-day horizon" in report_text
