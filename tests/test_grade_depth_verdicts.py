"""tests/test_grade_depth_verdicts.py — TRK-06 (P2.1), fixed per the Phase 2 approval review
(reports/PHASE_2_APPROVAL.md) fix list B1-B4 + carriables C1-C3/C5/C6/C10.

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
3. `actionable`/`analyst_valid` are recomputed via depth_gates, never read from a ledger stamp.
4. B1: nomination context joins from factor_signal_log.jsonl (git-read from the DEDICATED
   screener_publish_repo clone), never a run after the verdict, 10-day window, never guessed.
5. B3: dedupe_rows — cross-ledger exact-triple duplicates collapse by precedence; within-ledger
   rederivation chains keep every line, tag every but the last `superseded_by`, and those are
   excluded from stats/cuts/correlations downstream.
6. B4: cuts always render (n_missing/reason never silently dropped).
7. Aggregation: bucket_stats' t-stat/inconclusive flag, cut()'s multi-label mode, tercile_cut.
8. C2/C3: --offline never touches the network; an exit beyond the offline cache's reach is
   pending, not missing. C6: weekend entry, exit==entry, missing benchmark, missing entry.
9. The generated caveats block states dedup, nomination-join and analyst-validity shares.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import grade_depth_verdicts as g  # noqa: E402
import depth_gates  # noqa: E402


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
    {"ticker": "DDD", "date": "2026-01-08", "consensus_dir": "DDD_20260108_1",
     "direction": "undervalued", "size_hint": "full", "spread_pct": 34.5, "n_basis": 2,
     "early_stop": False, "conviction_score": 9.0, "business_quality_moat": 3.5,
     "kelly_fraction_pct": 11.0, "mos_vs_median_pct": 30.0, "mos_vs_base_pct": 25.0,
     "pack_revision": 3, "gate_version": 2, "fiduciary_verdict": "PASS",
     "run_source": "orchestrator"},
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


def _grade(rows=None, cache=None, horizons=None, signal_runs=None, **kw):
    return g.grade_rows(rows if rows is not None else ROWS, cache if cache is not None else PRICES,
                        horizons or [30], signal_runs or [], **kw)


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
    graded, pending, missing = _grade(cache=prices)
    ddd = next(row for row in graded if row["ticker"] == "DDD")
    assert ddd["exit_date"] == "2026-02-04"
    assert pending == 0


def test_guard_4_days_short_is_not_graded():
    prices = {**PRICES, "DDD": {"2026-01-08": 40.00, "2026-02-03": 44.00}}  # 4d short
    graded, pending, missing = _grade(cache=prices)
    assert "DDD" not in {row["ticker"] for row in graded}
    assert pending == 1


# ═══════════════════════════════════════════════════════════════════════════════════════════
# C6 — fixture cases computed by hand: weekend entry, exit==entry, missing benchmark, missing
# entry. Each isolated from the byte-agreement fixture with its own small ROWS/PRICES so it
# cannot perturb EXPECTED above.
# ═══════════════════════════════════════════════════════════════════════════════════════════

def test_c6_weekend_entry_date_rolls_forward_to_monday():
    # 2026-01-10 is a Saturday; entry must resolve to the next trading day, Monday 2026-01-12.
    rows = [{"ticker": "FFF", "date": "2026-01-10", "consensus_dir": "FFF_1",
             "direction": "hold", "pack_revision": 3, "gate_version": 2,
             "run_source": "orchestrator"}]
    prices = {"FFF": {"2026-01-12": 100.00, "2026-02-09": 110.00},
              "IWM": {"2026-01-12": 50.00, "2026-02-09": 52.00},
              "SPY": {"2026-01-12": 400.00, "2026-02-09": 410.00},
              "QQQ": {"2026-01-12": 300.00, "2026-02-09": 312.00}}
    graded, pending, missing = _grade(rows=rows, cache=prices)
    assert len(graded) == 1
    row = graded[0]
    assert row["entry_date"] == "2026-01-12"      # rolled off the weekend
    assert row["exit_date"] == "2026-02-09"
    assert row["return_pct"] == 10.0


def test_c6_exit_resolving_to_entry_date_is_missing_not_fake_zero_return():
    # Only one price point ever recorded for GGG (a delisting-like gap): the 5-day-horizon
    # target's backward window reaches back to the entry date itself. Must be "missing exit",
    # never a fabricated 0% return from entry==exit.
    rows = [{"ticker": "GGG", "date": "2026-01-12", "consensus_dir": "GGG_1",
             "direction": "hold", "pack_revision": 3, "gate_version": 2,
             "run_source": "orchestrator"}]
    prices = {"GGG": {"2026-01-12": 50.00},
              "IWM": {"2026-01-12": 50.00, "2026-01-17": 50.00},
              "SPY": {"2026-01-12": 400.00, "2026-01-17": 400.00},
              "QQQ": {"2026-01-12": 300.00, "2026-01-17": 300.00}}
    graded, pending, missing = _grade(rows=rows, cache=prices, horizons=[5])
    assert graded == []
    assert missing["exit"] == [("GGG", "2026-01-12", 5)]


def test_c6_missing_benchmark_price_excludes_row_never_fabricates():
    rows = [{"ticker": "HHH", "date": "2026-01-13", "consensus_dir": "HHH_1",
             "direction": "hold", "pack_revision": 3, "gate_version": 2,
             "run_source": "orchestrator"}]
    prices = {"HHH": {"2026-01-13": 60.00, "2026-02-12": 66.00},
              "IWM": {"2026-01-13": 50.00, "2026-02-12": 52.00},
              "SPY": {"2026-01-13": 400.00, "2026-02-12": 410.00}}
              # QQQ entirely absent — a benchmark hole.
    graded, pending, missing = _grade(rows=rows, cache=prices)
    assert graded == []
    assert missing["exit"] == [("HHH", "2026-01-13", 30)]


def test_c6_missing_entry_price_series_never_dropped_silently():
    rows = [{"ticker": "III", "date": "2026-01-14", "consensus_dir": "III_1",
             "direction": "hold", "pack_revision": 3, "gate_version": 2,
             "run_source": "orchestrator"}]
    prices = {"IWM": {"2026-01-14": 50.00}, "SPY": {"2026-01-14": 400.00},
              "QQQ": {"2026-01-14": 300.00}}   # III has no series at all
    graded, pending, missing = _grade(rows=rows, cache=prices)
    assert graded == []
    assert missing["entry"] == [("III", "2026-01-14", 30)]


# ═══════════════════════════════════════════════════════════════════════════════════════════
# actionable / analyst_valid recomputed via depth_gates — never trusted from a ledger stamp
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


def test_analyst_valid_false_by_default_first_valid_pack_revision_unset():
    # Every ROWS entry has pack_revision=3 / gate_version in {1,2}; with
    # FIRST_VALID_PACK_REVISION still None (no Phase 4 ruling yet), NOTHING is valid.
    graded, _, _ = _grade()
    assert all(row["analyst_valid"] is False for row in graded)


def test_analyst_valid_true_once_ruling_sets_the_floor(monkeypatch):
    monkeypatch.setattr(depth_gates, "FIRST_VALID_PACK_REVISION", 3)
    graded, _, _ = _grade()
    by_ticker = {row["ticker"]: row for row in graded}
    # AAA/CCC/EEE: pack_revision=3 (>=3), gate_version=2 (>=GATE_VERSION) -> valid.
    assert by_ticker["AAA"]["analyst_valid"] is True
    assert by_ticker["CCC"]["analyst_valid"] is True
    assert by_ticker["EEE"]["analyst_valid"] is True
    # BBB: gate_version=1 < GATE_VERSION -> still invalid even at pack_revision 3.
    assert by_ticker["BBB"]["analyst_valid"] is False


def test_ledger_source_and_consensus_dir_carried():
    rows = [dict(r, _ledger_source="production") for r in ROWS]
    graded, _, _ = _grade(rows=rows)
    aaa = next(row for row in graded if row["ticker"] == "AAA")
    assert aaa["ledger_source"] == "production"
    assert aaa["consensus_dir"] == "AAA_20260105_1"
    assert aaa["also_in"] == []
    assert aaa["superseded_by"] is None


# ═══════════════════════════════════════════════════════════════════════════════════════════
# B3 — dedupe_rows: one verdict counted once
# ═══════════════════════════════════════════════════════════════════════════════════════════

def _tag(rows, src):
    return [dict(r, _ledger_source=src) for r in rows]


def test_dedupe_cross_ledger_precedence_keeps_test_over_archive():
    # Measured real pattern: a name quarantined into `test` still sits, byte-identical apart
    # from the quarantine stamps, in `archive` too.
    base = {"ticker": "CAT", "date": "2026-09-18", "consensus_dir": "CAT_X"}
    rows = _tag([base], "archive") + _tag([dict(base, quarantined_at="2026-09-23")], "test")
    out, dropped = g.dedupe_rows(rows)
    assert dropped == 1
    assert len(out) == 1
    assert out[0]["_ledger_source"] == "test"
    assert out[0]["also_in"] == ["archive"]
    assert out[0]["superseded_by"] is None


def test_dedupe_precedence_full_order_test_over_production_over_ondemand_over_archive():
    base = {"ticker": "X", "date": "2026-01-01", "consensus_dir": "X_1"}
    rows = (_tag([base], "archive") + _tag([base], "ondemand")
            + _tag([base], "production") + _tag([base], "test"))
    out, dropped = g.dedupe_rows(rows)
    assert len(out) == 1
    assert out[0]["_ledger_source"] == "test"
    assert dropped == 3
    assert out[0]["also_in"] == ["archive", "ondemand", "production"]


def test_dedupe_within_ledger_two_line_chain_tags_predecessor_only():
    # Measured real pattern: KFY 2026-08-24 — original (n_basis=2), then one rederivation
    # (n_basis=3, carries `supersedes` + `rederived_at`), same (ticker, date, consensus_dir).
    rows = _tag([
        {"ticker": "KFY", "date": "2026-08-24", "consensus_dir": "KFY_X", "n_basis": 2},
        {"ticker": "KFY", "date": "2026-08-24", "consensus_dir": "KFY_X", "n_basis": 3,
         "rederived_at": "2026-08-24 19:52:53", "supersedes": {"n_basis": 2}},
    ], "archive")
    out, dropped = g.dedupe_rows(rows)
    assert dropped == 0        # nothing collapsed — both lines are real analyst output, kept
    assert len(out) == 2
    original = next(r for r in out if r["n_basis"] == 2)
    successor = next(r for r in out if r["n_basis"] == 3)
    assert successor["superseded_by"] is None
    assert original["superseded_by"] == "2026-08-24 19:52:53"


def test_dedupe_within_ledger_three_line_chain_only_last_is_current():
    # Measured real pattern: ATI 2026-08-24 — a 3-line rederivation chain.
    rows = _tag([
        {"ticker": "ATI", "date": "2026-08-24", "consensus_dir": "ATI_X", "n_basis": 1},
        {"ticker": "ATI", "date": "2026-08-24", "consensus_dir": "ATI_X", "n_basis": 2,
         "rederived_at": "T2"},
        {"ticker": "ATI", "date": "2026-08-24", "consensus_dir": "ATI_X", "n_basis": 3,
         "rederived_at": "T3"},
    ], "archive")
    out, dropped = g.dedupe_rows(rows)
    assert dropped == 0
    assert len(out) == 3
    by_basis = {r["n_basis"]: r for r in out}
    assert by_basis[3]["superseded_by"] is None
    assert by_basis[1]["superseded_by"] == "T2"
    assert by_basis[2]["superseded_by"] == "T3"


def test_dedupe_supersedes_row_with_no_rederived_at_falls_back_to_consensus_dir():
    rows = _tag([
        {"ticker": "Y", "date": "2026-01-01", "consensus_dir": "Y_1", "n_basis": 1},
        {"ticker": "Y", "date": "2026-01-01", "consensus_dir": "Y_1", "n_basis": 2},
    ], "archive")
    out, dropped = g.dedupe_rows(rows)
    predecessor = next(r for r in out if r["n_basis"] == 1)
    assert predecessor["superseded_by"] == "Y_1"


def test_dedupe_singleton_rows_unaffected():
    rows = _tag([{"ticker": "A", "date": "2026-01-01", "consensus_dir": "A_1"}], "production")
    out, dropped = g.dedupe_rows(rows)
    assert dropped == 0
    assert out[0]["also_in"] == []
    assert out[0]["superseded_by"] is None


def test_dedupe_missing_consensus_dir_never_collapsed():
    rows = _tag([{"ticker": "A", "date": "2026-01-01"},
                 {"ticker": "A", "date": "2026-01-01"}], "production")
    out, dropped = g.dedupe_rows(rows)
    assert dropped == 0
    assert len(out) == 2


def test_dedupe_superseded_row_excluded_from_stats_in_grade_rows_output():
    """A superseded row still appears in `graded` (annotated), and a caller computing stats must
    filter it out — proved here by checking the tag survives end-to-end through grade_rows."""
    rows = _tag([
        {"ticker": "KFY", "date": "2026-01-05", "consensus_dir": "KFY_X", "direction": "hold",
         "pack_revision": 3, "gate_version": 2, "run_source": "orchestrator", "n_basis": 2},
        {"ticker": "KFY", "date": "2026-01-05", "consensus_dir": "KFY_X", "direction": "hold",
         "pack_revision": 3, "gate_version": 2, "run_source": "orchestrator", "n_basis": 3,
         "rederived_at": "T2"},
    ], "archive")
    deduped, dropped = g.dedupe_rows(rows)
    prices = {"KFY": {"2026-01-05": 100.00, "2026-02-04": 110.00}, **{
        b: {"2026-01-05": v, "2026-02-04": v * 1.02} for b, v in
        (("IWM", 50.0), ("SPY", 400.0), ("QQQ", 300.0))}}
    graded, _, _ = _grade(rows=deduped, cache=prices)
    assert len(graded) == 2
    by_basis = {row["n_basis"]: row for row in graded}
    assert by_basis[3]["superseded_by"] is None
    assert by_basis[2]["superseded_by"] == "T2"
    valid_for_stats = [row for row in graded if not row.get("superseded_by")]
    assert len(valid_for_stats) == 1
    assert valid_for_stats[0]["n_basis"] == 3


# ═══════════════════════════════════════════════════════════════════════════════════════════
# B1 — nomination context: factor_signal_log.jsonl, 10-day window, never a run after D
# ═══════════════════════════════════════════════════════════════════════════════════════════

def _sig(symbol, **over):
    s = {"symbol": symbol, "fct_band": "research_now", "fct_composite": 90.0, "fct_rank": 5}
    s.update(over)
    return s


SIGNAL_RUNS = [
    {"run_id": "20260104T120000Z", "engine": "dual_door_dynamic_macro_v2_cluster_guarded",
     "signals": [_sig("AAA", fct_rank=3,
                       fct_nominated_doors=["DOOR_1_COMPOUNDER"],
                       fct_z={"quality": 1.0, "momentum": 1.2, "revisions": 0.5,
                              "value": -0.3, "exp_gap": 0.8},
                       cluster="tech_semis", sector="Technology")]},
    {"run_id": "20260120T120000Z", "engine": "dual_door_dynamic_macro_v2_cluster_guarded",
     "signals": [_sig("AAA", fct_rank=50, fct_band="watchlist")]},   # AFTER most verdict dates below
]


def test_nomination_context_within_window_joins_p23_fields():
    ctx = g.nomination_context("AAA", "2026-01-05", SIGNAL_RUNS)
    assert ctx["nomination_run_id"] == "20260104T120000Z"
    assert ctx["nomination_engine"] == "dual_door_dynamic_macro_v2_cluster_guarded"
    assert ctx["fct_band"] == "research_now"
    assert ctx["fct_rank"] == 3
    assert ctx["fct_nominated_doors"] == ["DOOR_1_COMPOUNDER"]
    assert ctx["z_momentum"] == 1.2
    assert ctx["z_value"] == -0.3
    assert ctx["z_exp_gap"] == 0.8
    assert ctx["cluster"] == "tech_semis"
    assert ctx["sector"] == "Technology"
    assert ctx["nomination_reason"] is None


def test_nomination_context_never_uses_a_run_after_the_verdict():
    # Both runs are after 2026-01-02: the 01-04 run is 2 days AFTER, so neither qualifies.
    ctx = g.nomination_context("AAA", "2026-01-02", SIGNAL_RUNS)
    assert ctx["fct_band"] is None
    assert ctx["nomination_reason"] == g.NOM_REASON_NO_RUN


def test_nomination_context_a_verdict_graded_30_days_later_still_joins():
    # The join must key off the VERDICT date, not "today" — grading happens long after.
    ctx = g.nomination_context("AAA", "2026-01-10", SIGNAL_RUNS)   # run 01-04 is 6 days before
    assert ctx["fct_rank"] == 3
    assert ctx["nomination_reason"] is None


def test_nomination_context_10_day_boundary():
    # D - 10 days: qualifies.
    at_boundary = [{"run_id": "20260122T000000Z",
                    "signals": [_sig("A", fct_nominated_doors=[], fct_z={})]}]
    ctx_a = g.nomination_context("A", "2026-02-01", at_boundary)
    assert ctx_a["nomination_reason"] is None

    # D - 11 days: excluded — no qualifying run at all for this symbol.
    beyond_boundary = [{"run_id": "20260121T000000Z", "signals": [_sig("B")]}]
    ctx_b = g.nomination_context("B", "2026-02-01", beyond_boundary)
    assert ctx_b["nomination_reason"] == g.NOM_REASON_NO_RUN


def test_nomination_context_missing_symbol():
    ctx = g.nomination_context("ZZZ", "2026-01-05", SIGNAL_RUNS)
    assert ctx["fct_band"] is None
    assert ctx["nomination_reason"] == g.NOM_REASON_NOT_IN_RUN


def test_nomination_context_pre_p23_row_keeps_old_fields_blanks_new_ones():
    runs = [{"run_id": "20260105T000000Z", "engine": "old_engine",
             "signals": [_sig("AAA", fct_rank=7, fct_composite=88.5)]}]  # no doors/fct_z at all
    ctx = g.nomination_context("AAA", "2026-01-06", runs)
    assert ctx["fct_band"] == "research_now"
    assert ctx["fct_rank"] == 7
    assert ctx["fct_composite"] == 88.5
    assert ctx["fct_nominated_doors"] is None
    assert ctx["z_momentum"] is None
    assert ctx["z_value"] is None
    assert ctx["z_exp_gap"] is None
    assert ctx["nomination_reason"] == g.NOM_REASON_PRE_P23


def test_nomination_context_ties_on_date_pick_latest_by_full_timestamp():
    runs = [{"run_id": "20260105T090000Z", "signals": [_sig("A", fct_rank=1)]},
            {"run_id": "20260105T210000Z", "signals": [_sig("A", fct_rank=2)]}]
    ctx = g.nomination_context("A", "2026-01-05", runs)
    assert ctx["fct_rank"] == 2
    assert ctx["nomination_run_id"] == "20260105T210000Z"


def test_nomination_context_malformed_verdict_date():
    ctx = g.nomination_context("AAA", "not-a-date", SIGNAL_RUNS)
    assert ctx["nomination_reason"] == g.NOM_REASON_NO_RUN


def test_grade_rows_carries_nomination_fields():
    rows = [dict(r) for r in ROWS if r["ticker"] == "AAA"]
    graded, _, _ = _grade(rows=rows, signal_runs=SIGNAL_RUNS)
    aaa = graded[0]
    assert aaa["fct_rank"] == 3
    assert aaa["z_momentum"] == 1.2
    assert aaa["nomination_reason"] is None


def test_grade_rows_signal_log_error_blanks_every_nomination_field():
    rows = [dict(r) for r in ROWS if r["ticker"] == "AAA"]
    graded, _, _ = _grade(rows=rows, signal_runs=SIGNAL_RUNS, signal_log_error="git fetch failed")
    aaa = graded[0]
    assert aaa["fct_rank"] is None
    assert aaa["z_momentum"] is None
    assert aaa["nomination_reason"] == g.NOM_REASON_LOG_UNAVAILABLE


# ---- load_factor_signal_log: git-read from the DEDICATED publish clone, never a write --------

def _git(repo, *args):
    import subprocess
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_signal_log_clone(tmp_path, content_lines):
    origin = tmp_path / "stock-screener.git"
    import subprocess
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "screener-publish-clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@test")
    _git(clone, "config", "user.name", "test")
    (clone / "public" / "data").mkdir(parents=True)
    if content_lines is not None:
        (clone / "public" / "data" / "factor_signal_log.jsonl").write_text(
            "\n".join(json.dumps(r) for r in content_lines) + "\n", encoding="utf-8")
    else:
        (clone / "public" / "data" / ".gitkeep").write_text("", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "init")
    _git(clone, "branch", "-M", "main")
    _git(clone, "push", "-u", "origin", "main")
    return clone


def test_load_factor_signal_log_no_clone_configured(tmp_path, monkeypatch):
    monkeypatch.setitem(g.CONFIG, "screener_publish_repo", str(tmp_path / "does_not_exist"))
    runs, err = g.load_factor_signal_log(offline=True)
    assert runs == []
    assert "not a git clone" in err


def test_load_factor_signal_log_offline_reads_without_fetching(tmp_path, monkeypatch):
    clone = _make_signal_log_clone(tmp_path, [{"run_id": "20260101T000000Z", "engine": "e",
                                               "signals": [_sig("Q")]}])
    monkeypatch.setitem(g.CONFIG, "screener_publish_repo", str(clone))
    called = []
    import subprocess
    real_run = subprocess.run

    def spy(cmd, **kw):
        called.append(cmd)
        return real_run(cmd, **kw)
    monkeypatch.setattr(g.subprocess, "run", spy)

    runs, err = g.load_factor_signal_log(offline=True)
    assert err is None
    assert len(runs) == 1
    assert runs[0]["run_id"] == "20260101T000000Z"
    assert not any("fetch" in c for c in called)   # --offline never fetches


def test_load_factor_signal_log_network_mode_fetches_then_shows(tmp_path, monkeypatch):
    clone = _make_signal_log_clone(tmp_path, [{"run_id": "20260101T000000Z", "engine": "e",
                                               "signals": []}])
    monkeypatch.setitem(g.CONFIG, "screener_publish_repo", str(clone))
    runs, err = g.load_factor_signal_log(offline=False)
    assert err is None
    assert len(runs) == 1


def test_load_factor_signal_log_git_show_failure(tmp_path, monkeypatch):
    clone = _make_signal_log_clone(tmp_path, None)   # no factor_signal_log.jsonl committed
    monkeypatch.setitem(g.CONFIG, "screener_publish_repo", str(clone))
    runs, err = g.load_factor_signal_log(offline=True)
    assert runs == []
    assert "git show" in err


def test_load_factor_signal_log_fetch_failure(tmp_path, monkeypatch):
    clone = _make_signal_log_clone(tmp_path, [{"run_id": "20260101T000000Z", "signals": []}])
    monkeypatch.setitem(g.CONFIG, "screener_publish_repo", str(clone))

    def fake_run(cmd, **kw):
        import subprocess
        if "fetch" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="network unreachable")
        raise AssertionError("git show must not run after a fetch failure")
    monkeypatch.setattr(g.subprocess, "run", fake_run)

    runs, err = g.load_factor_signal_log(offline=False)
    assert runs == []
    assert "git fetch" in err


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


def test_cut_excludes_none_keys_and_counts_missing():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "sector": "Tech"},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1, "sector": None}]
    result = g.cut(rows, lambda r: r["sector"], "sector")
    assert set(result["buckets"]) == {"Tech"}
    assert result["n_missing"] == 1
    assert result["n_total"] == 2


def test_cut_multi_label_counts_row_in_every_bucket():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1,
             "nominated_doors": ["DOOR_2_VALUE_GAP", "GLOBAL_WILDCARD"]},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1,
             "nominated_doors": ["DOOR_2_VALUE_GAP"]}]
    result = g.cut(rows, lambda r: r.get("nominated_doors"), "nominated_doors", multi=True)
    assert result["buckets"]["DOOR_2_VALUE_GAP"]["n_verdicts"] == 2
    assert result["buckets"]["GLOBAL_WILDCARD"]["n_verdicts"] == 1
    assert result["n_missing"] == 0


def test_cut_empty_result_carries_a_reason():
    result = g.cut([], lambda r: r.get("sector"), "sector")
    assert result["buckets"] == {}
    assert result["reason"] == "no graded rows"

    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "sector": None}]
    result2 = g.cut(rows, lambda r: r.get("sector"), "sector")
    assert result2["buckets"] == {}
    assert "1 of 1 missing" in result2["reason"]


def test_tercile_cut_splits_into_thirds():
    rows = [{"ticker": f"T{i}", "return_pct": i, "excess_iwm_pct": i, "conviction_score": i}
            for i in range(1, 10)]      # 1..9
    result = g.tercile_cut(rows, "conviction_score", "conviction tercile")
    assert set(result["buckets"]) <= {"T1_low", "T2_mid", "T3_high"}
    total = sum(b["n_verdicts"] for b in result["buckets"].values())
    assert total == 9
    assert result["n_missing"] == 0


def test_tercile_cut_respects_predicate():
    rows = [{"ticker": f"T{i}", "return_pct": i, "excess_iwm_pct": i, "z_momentum": i,
             "direction": "undervalued" if i % 2 == 0 else "overvalued"}
            for i in range(1, 13)]
    result = g.tercile_cut(rows, "z_momentum", "z_momentum tercile",
                           predicate=lambda r: r["direction"] == "undervalued")
    total = sum(b["n_verdicts"] for b in result["buckets"].values())
    assert total == 6      # only the 6 "undervalued" rows


def test_tercile_cut_excludes_none_field_and_counts_missing():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": None},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 2},
            {"ticker": "C", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 3},
            {"ticker": "D", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 4}]
    result = g.tercile_cut(rows, "conviction_score", "conviction tercile")
    total = sum(b["n_verdicts"] for b in result["buckets"].values())
    assert total == 3      # the None-conviction row (A) is excluded, not guessed into a bucket
    assert result["n_missing"] == 1


def test_tercile_cut_too_few_rows_yields_no_buckets_with_reason():
    rows = [{"ticker": "A", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 2},
            {"ticker": "B", "return_pct": 1, "excess_iwm_pct": 1, "conviction_score": 3}]
    result = g.tercile_cut(rows, "conviction_score", "conviction tercile")
    assert result["buckets"] == {}
    assert "reason" in result


def test_spread_bucket_boundaries():
    assert g.spread_bucket({"spread_pct": 15.0}) == "<=15"
    assert g.spread_bucket({"spread_pct": 15.01}) == "15-30"
    assert g.spread_bucket({"spread_pct": 30.0}) == "15-30"
    assert g.spread_bucket({"spread_pct": 30.01}) == ">30"
    assert g.spread_bucket({"spread_pct": None}) is None


def test_build_cuts_always_returns_every_cut_including_momentum_ablation():
    labels = [c["cut"] for c in g.build_cuts([])]
    assert "z_momentum tercile (momentum ablation, undervalued only)" in labels
    assert len(labels) == 13   # every cut in the work order's list, even on zero rows
    for c in g.build_cuts([]):
        assert c["buckets"] == {}
        assert "reason" in c


# ═══════════════════════════════════════════════════════════════════════════════════════════
# Caveats — dedup, nomination join, analyst validity, never omitted
# ═══════════════════════════════════════════════════════════════════════════════════════════

def test_caveats_window_and_regime_present():
    graded, _, _ = _grade()
    caveats = g.build_caveats(ROWS, graded, 0, None)
    joined = " ".join(caveats)
    assert "2026-01-05" in joined and "2026-01-09" in joined
    assert "Regime at report time" in joined


def test_caveats_report_dedup_counts():
    graded, _, _ = _grade()
    caveats = g.build_caveats(ROWS, graded, 2, None)
    joined = " ".join(caveats)
    assert "Deduping (B3)" in joined
    assert "2 cross-ledger duplicate" in joined


def test_caveats_report_nomination_join_hit_and_reasons():
    rows = [dict(r) for r in ROWS if r["ticker"] == "AAA"]
    graded, _, _ = _grade(rows=rows, signal_runs=SIGNAL_RUNS)
    caveats = g.build_caveats(rows, graded, 0, None)
    joined = " ".join(caveats)
    assert "Nomination join" in joined
    assert "1 of 1" in joined


def test_caveats_report_signal_log_unavailable_reason():
    graded, _, _ = _grade(signal_log_error="git fetch failed: network unreachable")
    caveats = g.build_caveats(ROWS, graded, 0, "git fetch failed: network unreachable")
    joined = " ".join(caveats)
    assert "UNAVAILABLE" in joined
    assert "git fetch failed" in joined


def test_caveats_analyst_validity_zero_is_capitalized_and_never_omitted():
    graded, _, _ = _grade()   # FIRST_VALID_PACK_REVISION is None -> 0 valid
    caveats = g.build_caveats(ROWS, graded, 0, None)
    joined = " ".join(caveats)
    assert "Analyst validity: 0 of 4" in joined
    assert "NO CONCLUSION ABOUT THE ANALYST MAY BE DRAWN" in joined


def test_caveats_analyst_validity_reports_nonzero_k(monkeypatch):
    monkeypatch.setattr(depth_gates, "FIRST_VALID_PACK_REVISION", 3)
    graded, _, _ = _grade()
    caveats = g.build_caveats(ROWS, graded, 0, None)
    joined = " ".join(caveats)
    assert "Analyst validity: 3 of 4" in joined   # AAA/CCC/EEE valid, BBB not (gate_version=1)
    assert "NO CONCLUSION" not in joined


def test_caveats_never_omitted_on_zero_graded_rows():
    caveats = g.build_caveats([], [], 0, None)
    joined = " ".join(caveats)
    assert "Analyst validity: 0 of 0" in joined
    assert "Deduping (B3)" in joined


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

def _isolate_main(monkeypatch, tmp_path, ledger_rows):
    ledger = tmp_path / "depth_ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(r) for r in ledger_rows) + "\n", encoding="utf-8")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    monkeypatch.setattr(g, "LEDGERS", {"production": ledger, "archive": empty,
                                       "ondemand": empty, "test": empty})
    outcomes = tmp_path / "depth_outcomes.json"
    report = tmp_path / "depth_outcomes_report.md"
    monkeypatch.setattr(g, "OUTCOMES_JSON", outcomes)
    monkeypatch.setattr(g, "REPORT_MD", report)
    monkeypatch.setattr(g, "MRI_CURRENT_REGIME", tmp_path / "no_regime.json")
    monkeypatch.setattr(g, "load_factor_signal_log", lambda offline: ([], None))
    return outcomes, report


def test_main_offline_end_to_end(tmp_path, monkeypatch):
    outcomes, report = _isolate_main(monkeypatch, tmp_path, ROWS)
    price_cache = tmp_path / "depth_outcome_prices.json"
    price_cache.write_text(json.dumps(PRICES), encoding="utf-8")
    monkeypatch.setattr(g, "PRICE_CACHE_JSON", price_cache)

    monkeypatch.setattr(sys, "argv", ["grade_depth_verdicts.py", "--offline",
                                      "--ledgers", "production", "--horizons", "30"])
    rc = g.main()
    assert rc == 0

    payload = json.loads(outcomes.read_text(encoding="utf-8"))
    assert payload["graded_verdict_horizons"] == 4       # DDD guarded out
    assert payload["distinct_verdict_horizons"] == 4     # no dupes in this fixture
    assert payload["pending_verdict_horizons"] == 1
    assert payload["ledger_row_counts"] == {"production": 5}
    assert payload["cross_ledger_duplicates_dropped"] == 0
    assert "Analyst validity" in " ".join(payload["caveats"])
    assert payload["gradeable_counts_per_horizon"]["30"]["total"] == 4
    assert payload["gradeable_counts_per_horizon"]["30"]["by_ledger_source"] == {"production": 4}

    report_text = report.read_text(encoding="utf-8")
    assert "Depth Verdict Outcome Report" in report_text
    assert "Analyst validity" in report_text
    assert "30-day horizon" in report_text
    # B4: the momentum ablation cut renders even though it is empty (no signal_runs supplied).
    assert "z_momentum tercile (momentum ablation, undervalued only)" in report_text
    assert "n = 0" in report_text


def test_main_offline_missing_price_cache_exits_nonzero_never_fetches(tmp_path, monkeypatch):
    """C2: --offline must NEVER touch the network. A missing price cache is a hard failure."""
    outcomes, report = _isolate_main(monkeypatch, tmp_path, ROWS)
    monkeypatch.setattr(g, "PRICE_CACHE_JSON", tmp_path / "does_not_exist_prices.json")

    def _boom(*a, **k):
        raise AssertionError("fetch_history must never be called in --offline mode")
    monkeypatch.setattr(g, "fetch_history", _boom)

    monkeypatch.setattr(sys, "argv", ["grade_depth_verdicts.py", "--offline",
                                      "--ledgers", "production"])
    rc = g.main()
    assert rc == 1
    assert not outcomes.exists()


def test_main_offline_dedup_collapses_duplicate_and_tags_supersession(tmp_path, monkeypatch):
    """B3 end-to-end: a cross-ledger exact duplicate collapses to one row, and a within-ledger
    rederivation chain is excluded from the horizon's stats but still present in `graded`."""
    rows = [dict(r) for r in ROWS if r["ticker"] in ("AAA", "CCC")]
    # KFY: a 2-line rederivation chain sharing (ticker, date, consensus_dir), both gradeable.
    rows += [
        {"ticker": "KFY", "date": "2026-01-05", "consensus_dir": "KFY_X", "direction": "hold",
         "pack_revision": 3, "gate_version": 2, "run_source": "orchestrator", "n_basis": 2},
        {"ticker": "KFY", "date": "2026-01-05", "consensus_dir": "KFY_X", "direction": "hold",
         "pack_revision": 3, "gate_version": 2, "run_source": "orchestrator", "n_basis": 3,
         "rederived_at": "T2"},
    ]
    outcomes, report = _isolate_main(monkeypatch, tmp_path, rows)
    price_cache = tmp_path / "depth_outcome_prices.json"
    prices = {**PRICES, "KFY": {"2026-01-05": 100.00, "2026-02-04": 110.00}}
    price_cache.write_text(json.dumps(prices), encoding="utf-8")
    monkeypatch.setattr(g, "PRICE_CACHE_JSON", price_cache)

    monkeypatch.setattr(sys, "argv", ["grade_depth_verdicts.py", "--offline",
                                      "--ledgers", "production", "--horizons", "30"])
    rc = g.main()
    assert rc == 0

    payload = json.loads(outcomes.read_text(encoding="utf-8"))
    # AAA + CCC + KFY(x2 lines, 1 superseded) = 4 graded rows, 3 distinct.
    assert payload["graded_verdict_horizons"] == 4
    assert payload["distinct_verdict_horizons"] == 3
    gc = payload["gradeable_counts_per_horizon"]["30"]
    assert gc["total"] == 3
    assert gc["total_incl_superseded"] == 4
    kfy_rows = [g_ for g_ in payload["graded"] if g_["ticker"] == "KFY"]
    assert len(kfy_rows) == 2
    superseded = [g_ for g_ in kfy_rows if g_["superseded_by"]]
    assert len(superseded) == 1
    assert superseded[0]["n_basis"] == 2
    # The horizon's own aggregate ("all") must not count the superseded row.
    assert payload["per_horizon"]["30"]["all"]["n_verdicts"] == 3


def test_main_offline_c3_exit_beyond_cache_is_pending_not_missing(tmp_path, monkeypatch):
    """C3: in --offline mode a horizon whose exit date is beyond the cache's last date is
    pending, never counted as missing/'delisted?'."""
    rows = [{"ticker": "JJJ", "date": "2026-01-05", "consensus_dir": "JJJ_1",
             "direction": "hold", "pack_revision": 3, "gate_version": 2,
             "run_source": "orchestrator"}]
    outcomes, report = _isolate_main(monkeypatch, tmp_path, rows)
    # The offline cache for JJJ (and the benchmarks) stops at 2026-01-20 — well short of the
    # 30-day target (2026-02-04). No data exists anywhere near the target: the cache genuinely
    # has not caught up yet (this is what a stale offline snapshot looks like), not a delisting.
    prices = {"JJJ": {"2026-01-05": 100.00, "2026-01-20": 101.00},
              "IWM": {"2026-01-05": 50.00, "2026-01-20": 50.50},
              "SPY": {"2026-01-05": 400.00, "2026-01-20": 402.00},
              "QQQ": {"2026-01-05": 300.00, "2026-01-20": 301.00}}
    price_cache = tmp_path / "depth_outcome_prices.json"
    price_cache.write_text(json.dumps(prices), encoding="utf-8")
    monkeypatch.setattr(g, "PRICE_CACHE_JSON", price_cache)

    monkeypatch.setattr(sys, "argv", ["grade_depth_verdicts.py", "--offline",
                                      "--ledgers", "production", "--horizons", "30"])
    rc = g.main()
    assert rc == 0
    payload = json.loads(outcomes.read_text(encoding="utf-8"))
    assert payload["graded_verdict_horizons"] == 0
    assert payload["pending_verdict_horizons"] == 1
    assert payload["missing"]["exit"] == 0
