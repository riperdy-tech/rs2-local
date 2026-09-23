"""tests/test_publish_cloud_verdicts.py — P1-fix B1 (Phase 1 approval review, §6).

publish_cloud_verdicts.py used to stamp today's `dp.GATE_VERSION` on every cloud verdict it
published, whether or not that verdict was ever judged against the v2 gates. The review measured
that simulating `depth_gates.assess()` with that stamp made 99 of 104 2026-08-26 flash cloud runs
read as `actionable: true` — verdicts with pack revision 3, no `fiduciary_verdict`, no live price,
some with spreads up to 205%, none of which the v2 gates ever saw.

The fix carries the verdict's own `gate_version` through untouched (present only if a future
cloud run is ever actually gated); these pre-P1.3 runs have none, so `depth_gates.assess()`
correctly reads them as `pre_v3.1_gates` -> not actionable. This test reproduces that shape end
to end: a synthetic 2026-08-26 flash run with no `gate_version` field, published through the real
`main()`, must land in the ledger and overlay as `actionable: false`.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "api_llm"))

import depth_gates                          # noqa: E402
import orchestrate_depth as od               # noqa: E402
import publish_cloud_verdicts as pcv         # noqa: E402


def _stub_audit(monkeypatch):
    """Real dp.audit_verdict shells out to depth_sanity.py and appends to the real
    cache/depth_audit.log — never allowed to run for real in a test (repo-root conftest.py
    fails any test that changes a cache/ mtime). Records the (ticker, ledger) calls instead."""
    calls = []
    monkeypatch.setattr(pcv.dp, "audit_verdict", lambda t, ledger: calls.append((t, ledger)))
    return calls


def _make_run(tmp_path, ticker="ABBV", direction="undervalued", spread_pct=5.0):
    """A synthetic cloud run dir shaped exactly like a real 2026-08-26 flash run
    (api_llm/deep_api/ABBV_20260826_012953/verdict_depth.json): pack_source fresh, pack_revision
    3, no gate_version, no fiduciary_verdict, no live price."""
    d = tmp_path / f"{ticker}_20260826_012953"
    d.mkdir()
    verdict = {
        "ticker": ticker, "price": 100.0, "date": "2026-08-26", "model": "deepseek-v4-flash",
        "samples_run": 3, "n_basis": 3, "iv_band_low": 90.0, "iv_band_high": 110.0,
        "median_iv": 130.0, "spread_pct": spread_pct, "flags": [], "pack_revision": 3,
        "scheme": "band_direction_v1", "direction": direction, "size_hint": "full",
        "mos_vs_median_pct": 30.0, "consensus_dir": d.name, "arm": "cloud_api",
        "pack_source": "fresh", "research_brief_age_days": 6.1, "searxng_up": True,
    }
    (d / "verdict_depth.json").write_text(json.dumps(verdict), encoding="utf-8")
    doc = {"ticker": ticker, "model": "deepseek-v4-flash", "pack_source": "fresh",
           "research_brief_age_days": 6.1, "pack_revision": 3, "runs": [],
           "spread_pct": spread_pct}
    (d / "consensus.json").write_text(json.dumps(doc), encoding="utf-8")
    return d, doc, verdict


def test_2026_08_26_cloud_verdict_is_not_actionable(tmp_path, monkeypatch):
    d, doc, verdict = _make_run(tmp_path)
    assert "gate_version" not in verdict  # the source run never had one — confirms the shape

    monkeypatch.setattr(pcv, "cloud_runs", lambda: {"ABBV": (d, doc, verdict)})
    monkeypatch.setattr(od, "live_book", lambda: {"ABBV"})
    monkeypatch.setattr(od, "LEDGER", tmp_path / "depth_ledger.jsonl")
    monkeypatch.setattr(od, "OVERLAY", tmp_path / "depth_overlay.json")
    monkeypatch.setattr(od, "PENDING_REPORTS", tmp_path / "cloud_pending_reports")
    monkeypatch.setattr(sys, "argv", ["publish_cloud_verdicts.py"])
    _stub_audit(monkeypatch)

    pcv.main()

    rows = [json.loads(ln) for ln in od.LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1
    rec = rows[0]
    assert rec["run_source"] == "cloud"
    assert rec.get("gate_version") is None  # carried through, never stamped with today's

    actionable, reasons = depth_gates.assess(rec)
    assert actionable is False
    assert reasons == ["pre_v3.1_gates"]

    ov = json.loads(od.OVERLAY.read_text(encoding="utf-8"))
    assert ov["actionable_count"] == 0
    assert ov["tickers"]["ABBV"]["actionable"] is False
    assert ov["tickers"]["ABBV"]["actionable_reasons"] == ["pre_v3.1_gates"]


def test_publish_audits_every_appended_row(tmp_path, monkeypatch):
    """B5 (Phase 1 approval review, folded from P1.8): 'every ledger append path calls
    audit_verdict' was false for this path. Each published cloud verdict must now be audited
    against the SAME ledger file its row was appended to, with the same function the PC append
    path (depth_pipeline.main()) uses."""
    d1, doc1, v1 = _make_run(tmp_path, ticker="ABBV")
    d2, doc2, v2 = _make_run(tmp_path, ticker="MU")

    monkeypatch.setattr(pcv, "cloud_runs", lambda: {"ABBV": (d1, doc1, v1), "MU": (d2, doc2, v2)})
    monkeypatch.setattr(od, "live_book", lambda: {"ABBV", "MU"})
    ledger_path = tmp_path / "depth_ledger.jsonl"
    monkeypatch.setattr(od, "LEDGER", ledger_path)
    monkeypatch.setattr(od, "OVERLAY", tmp_path / "depth_overlay.json")
    monkeypatch.setattr(od, "PENDING_REPORTS", tmp_path / "cloud_pending_reports")
    monkeypatch.setattr(sys, "argv", ["publish_cloud_verdicts.py"])
    calls = _stub_audit(monkeypatch)

    pcv.main()

    assert sorted(calls) == [("ABBV", ledger_path), ("MU", ledger_path)]
