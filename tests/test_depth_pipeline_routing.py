"""depth_pipeline.py — run_source resolution, ledger routing, and provenance stamping (P1.2).

Exercises `_run_source()` and `stamp_and_route()` directly against synthetic verdicts/argv/env,
never the real research/consensus subprocesses or the real cache/ ledgers.
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# depth_pipeline re-wraps sys.stdout at import (utf-8 console on Windows). Under pytest that
# wraps the capture buffer, and letting the wrapper be garbage-collected would close it — same
# hazard api_llm/publish_cloud_verdicts.py guards with _STDOUT_KEEPALIVE (and orchestrate_depth's
# own test, tests/test_depth_queue.py). Keep it, restore ours.
_ORIG_STDOUT = sys.stdout
import depth_pipeline as dp  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


# ---- _run_source(): --ondemand > RS2_RUN_SOURCE env > --production > manual -------------------

@pytest.mark.parametrize("argv, env, expected", [
    (["depth_pipeline.py", "AAPL", "--ondemand"], {}, "ondemand"),
    (["depth_pipeline.py", "AAPL"], {"RS2_RUN_SOURCE": "orchestrator"}, "orchestrator"),
    (["depth_pipeline.py", "AAPL"], {"RS2_RUN_SOURCE": "cloud"}, "cloud"),
    (["depth_pipeline.py", "AAPL", "--production"], {}, "manual_production"),
    (["depth_pipeline.py", "AAPL"], {}, "manual"),
    # --ondemand wins even with an env marker set (a spawner passing both is unambiguous: the
    # explicit CLI flag is the stronger signal).
    (["depth_pipeline.py", "AAPL", "--ondemand"], {"RS2_RUN_SOURCE": "orchestrator"}, "ondemand"),
    # an env value outside the recognised set is not honoured — falls through to --production
    # or manual, same as if it were unset.
    (["depth_pipeline.py", "AAPL"], {"RS2_RUN_SOURCE": "bogus"}, "manual"),
])
def test_run_source_resolution_order(monkeypatch, argv, env, expected):
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    assert dp._run_source() == expected


# ---- stamp_and_route(): ledger target + every new field present -------------------------------

def _synthetic_verdict():
    return {"ticker": "FLXS", "price": 100.0, "date": "2026-09-23", "direction": "hold"}


@pytest.mark.parametrize("run_source, expected_ledger", [
    ("ondemand", "OD_LEDGER"),
    ("orchestrator", "LEDGER"),
    ("cloud", "LEDGER"),
    ("manual_production", "LEDGER"),
    ("manual", "TEST_LEDGER"),
])
def test_stamp_and_route_targets_the_right_ledger(monkeypatch, tmp_path, run_source, expected_ledger):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    ledger, notice = dp.stamp_and_route(v, "FLXS", run_source)
    assert ledger == getattr(dp, expected_ledger)
    if run_source == "manual":
        assert notice is not None
        assert "NOT the production ledger" in notice
        assert "FLXS" in notice
    else:
        assert notice is None


NEW_FIELDS = ("run_source", "arm", "pack_source", "research_brief_asof",
              "research_brief_age_days", "price_asof", "price_source", "gate_version",
              "pipeline_commit", "screener_data_commit")


def test_stamp_and_route_adds_every_new_field(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    for field in NEW_FIELDS:
        assert field in v, f"missing field: {field}"
    assert v["run_source"] == "orchestrator"
    assert v["arm"] == "local"
    assert v["pack_source"] == "fresh"
    assert v["gate_version"] == dp.GATE_VERSION
    assert v["screener_data_commit"] is None  # not passed — explicit key, never fabricated


# ---- screener_data_commit (P4.-1) --------------------------------------------------------------

def test_stamp_and_route_records_screener_data_commit_when_passed(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator", screener_data_commit="deadbeef")
    assert v["screener_data_commit"] == "deadbeef"


@pytest.mark.parametrize("run_source, expected", [
    ("orchestrator", "spawned"), ("cloud", "spawned"), ("ondemand", "spawned"),
])
def test_screener_data_commit_reads_env_when_spawned(monkeypatch, run_source, expected):
    monkeypatch.setenv("RS2_SCREENER_DATA_COMMIT", "abc1234")
    ok, sha = dp._screener_data_commit(run_source)
    assert ok is True
    assert sha == "abc1234"


@pytest.mark.parametrize("run_source", ["manual", "manual_production"])
def test_screener_data_commit_refreshes_on_standalone_run(monkeypatch, run_source):
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data",
                        lambda: (True, "freshsha"))
    ok, sha = dp._screener_data_commit(run_source)
    assert ok is True
    assert sha == "freshsha"


def test_screener_data_commit_refusal_propagates(monkeypatch):
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data",
                        lambda: (False, "dirty clone"))
    ok, reason = dp._screener_data_commit("manual")
    assert ok is False
    assert reason == "dirty clone"


def test_screener_data_commit_none_for_cloud_without_env(monkeypatch):
    """A cloud-sourced run whose spawner (api_llm/cloud_backstop.py) did not set the env var
    stamps None — never fabricated, and never re-refreshes on cloud's behalf (out of this
    module's contract)."""
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    ok, sha = dp._screener_data_commit("cloud")
    assert ok is True
    assert sha is None


def test_price_asof_basis_copied_when_present(monkeypatch, tmp_path):
    """C9 follow-on (Phase 1 approval review): stamp_and_route must carry quote['asof_basis']
    onto the verdict as price_asof_basis when price_now set one (the fast_info-unverified
    fallback marker)."""
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    quote = {"price": 104.16, "asof": "2026-09-22", "source": "yfinance_fast_info",
             "asof_basis": "fast_info_unverified"}
    dp.stamp_and_route(v, "FLXS", "orchestrator", quote=quote)
    assert v["price_asof_basis"] == "fast_info_unverified"


def test_price_asof_basis_absent_means_absent(monkeypatch, tmp_path):
    """A verified daily close carries no basis note at all — must never be invented."""
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    quote = {"price": 102.5, "asof": "2026-09-22", "source": "yfinance"}
    assert "asof_basis" not in quote  # confirms the fixture shape
    dp.stamp_and_route(v, "FLXS", "orchestrator", quote=quote)
    assert v["price_asof_basis"] is None


def test_price_asof_and_source_are_none_not_fabricated(monkeypatch, tmp_path):
    """P1.5 is not implemented yet — these must be explicit None with a reason, never a value."""
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    assert v["price_asof"] is None
    assert v["price_source"] is None
    assert v.get("price_asof_reason")  # a stated reason accompanies the absence


def test_research_brief_asof_absent_when_no_brief_on_disk(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    assert v["research_brief_asof"] is None
    assert v["research_brief_age_days"] is None


def test_research_brief_asof_present_when_brief_exists(monkeypatch, tmp_path):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    (tmp_path / "FLXS.md").write_text("brief", encoding="utf-8")
    v = _synthetic_verdict()
    dp.stamp_and_route(v, "FLXS", "orchestrator")
    assert v["research_brief_asof"] is not None
    assert v["research_brief_age_days"] is not None
    assert v["research_brief_age_days"] >= 0


# ---- GATE_VERSION is a real, importable single owner (P1.2; moves to depth_gates.py in P1.3) --

def test_gate_version_is_two():
    assert dp.GATE_VERSION == 2


# ---- end-to-end main(): the manual-invocation gate never demonstrated for real (B7, Phase 1 --
# ---- approval review, "gate 4 evidence") ------------------------------------------------------

def test_main_manual_invocation_only_grows_test_ledger(tmp_path, monkeypatch):
    """`python depth_pipeline.py FLXS` (no --ondemand, no --production, no RS2_RUN_SOURCE) —
    invoked exactly the way a manual run is invoked — must write ONLY to TEST_LEDGER, never to
    LEDGER or OD_LEDGER. Runs depth_pipeline.main() for real, end to end, but every subprocess-
    or GPU-touching seam (price_now.quote, run_research, run_consensus, band_verdict,
    audit_verdict) is stubbed, and LEDGER/TEST_LEDGER/OD_LEDGER — and the verdict file main()
    writes — are all redirected under tmp_path. Never runs the real research/consensus pipeline."""
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "FLXS"])
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path / "research"))
    # P4.-1: this manual (standalone) run would otherwise refresh the real screener_publish_repo.
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))

    ledger = tmp_path / "depth_ledger.jsonl"
    test_ledger = tmp_path / "depth_test_ledger.jsonl"
    od_ledger = tmp_path / "depth_ondemand_ledger.jsonl"
    monkeypatch.setattr(dp, "LEDGER", ledger)
    monkeypatch.setattr(dp, "TEST_LEDGER", test_ledger)
    monkeypatch.setattr(dp, "OD_LEDGER", od_ledger)

    quote = {"price": 100.0, "asof": "2026-09-23", "source": "yfinance"}
    monkeypatch.setattr(dp.price_now, "quote", lambda t: quote)
    monkeypatch.setattr(dp, "run_research", lambda t: None)

    consensus_dir = tmp_path / "FLXS_20260923_120000"
    consensus_dir.mkdir()
    doc = {"ticker": "FLXS", "price": 100.0}  # matches quote["price"] — C7's assert requires it
    monkeypatch.setattr(dp, "run_consensus",
                        lambda t, samples=None, price_quote=None: (consensus_dir, doc))
    monkeypatch.setattr(dp, "band_verdict", lambda doc: {
        "ticker": "FLXS", "price": 100.0, "date": "2026-09-23", "direction": "hold"})

    audited = []
    monkeypatch.setattr(dp, "audit_verdict", lambda t, ledger: audited.append((t, ledger)))
    notified = []
    monkeypatch.setattr(dp.ops, "notify_telegram", lambda msg: notified.append(msg))

    dp.main()

    # only TEST_LEDGER grows
    assert not ledger.exists() or ledger.read_text(encoding="utf-8") == ""
    assert not od_ledger.exists() or od_ledger.read_text(encoding="utf-8") == ""
    test_rows = [ln for ln in test_ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(test_rows) == 1
    row = json.loads(test_rows[0])
    assert row["ticker"] == "FLXS"
    assert row["run_source"] == "manual"
    assert row["screener_data_commit"] == "deadbeef"

    # audited against the SAME ledger the row actually landed in
    assert audited == [("FLXS", test_ledger)]
    # the loud manual-run warning fired
    assert len(notified) == 1
    assert "NOT the production ledger" in notified[0] and "FLXS" in notified[0]
    # the verdict file main() writes landed under tmp_path, not cache/
    assert (consensus_dir / "verdict_depth.json").exists()


# ---- C7 (Phase 1 approval review): depth_pipeline asserts the consensus subprocess actually ---
# ---- priced against OUR live quote, not a silently-abandoned --price ---------------------------

def test_main_exits_9_on_screener_refresh_refusal(monkeypatch, capsys):
    """A standalone (manual) invocation that cannot refresh the screener-publish clone must
    refuse before doing anything else — never price_now, never research, never consensus."""
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "FLXS"])
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data",
                        lambda: (False, "dirty clone"))
    called = []
    monkeypatch.setattr(dp.price_now, "quote", lambda t: called.append("quote"))

    with pytest.raises(SystemExit) as exc:
        dp.main()
    assert exc.value.code == 9
    assert called == []
    assert "screener data refresh refused: dirty clone" in capsys.readouterr().out


def test_main_asserts_consensus_price_matches_quote(tmp_path, monkeypatch):
    """If the consensus subprocess ever returns a price that does not match the live quote
    depth_pipeline passed it, main() must fail loudly (assert), never stamp and ledger a
    verdict priced against a number nobody chose."""
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "FLXS"])
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path / "research"))
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))
    monkeypatch.setattr(dp, "LEDGER", tmp_path / "depth_ledger.jsonl")
    monkeypatch.setattr(dp, "TEST_LEDGER", tmp_path / "depth_test_ledger.jsonl")
    monkeypatch.setattr(dp, "OD_LEDGER", tmp_path / "depth_ondemand_ledger.jsonl")

    monkeypatch.setattr(dp.price_now, "quote", lambda t: {"price": 100.0, "asof": "2026-09-23",
                                                           "source": "yfinance"})
    monkeypatch.setattr(dp, "run_research", lambda t: None)

    consensus_dir = tmp_path / "FLXS_20260923_120000"
    consensus_dir.mkdir()
    # MISMATCH: doc carries a different price than the quote depth_pipeline passed in.
    doc = {"ticker": "FLXS", "price": 999.0}
    monkeypatch.setattr(dp, "run_consensus",
                        lambda t, samples=None, price_quote=None: (consensus_dir, doc))

    with pytest.raises(AssertionError):
        dp.main()
