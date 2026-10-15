"""The pack's reading of an enrich ERROR record (tests/test_enrich_error_status.py holds the rest): the vendor fetch failed, which
the pack says in those words - it is never "no coverage" - and the verdict is gated as consensus data unavailable."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_throughcycle_reference import _synthetic_pack  # noqa: E402


def _err(code=401):
    return {"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "_status": "error",
            "_error": {"http_status": code, "where": "info"}}


def test_the_pack_says_the_fetch_failed_and_gates_the_verdict_as_consensus_unavailable(screener_data_stub, monkeypatch):
    import pack_facts
    import depth_gates
    rec = _err(401)
    pack = _synthetic_pack(monkeypatch, enrich_override=rec)
    text = str(pack)
    assert pack.facts["consensus_data_status"] == "fetch_error"
    line = next(l for l in text.splitlines() if l.startswith("- CONSENSUS ESTIMATES:"))
    assert line == "- CONSENSUS ESTIMATES: not available — the vendor fetch failed (HTTP 401 at info, 2026-09-26); a failed fetch, not a lack of coverage"
    # restated for pack revision 24 (R24.2): the line is not printed; the facts keep it
    assert "- CONSENSUS-IMPLIED VALUE: not available" not in text
    assert pack.facts["reference_line"] == "- CONSENSUS-IMPLIED VALUE: not available — consensus fetch failed"
    assert "CONSENSUS-IMPLIED VALUE (reference" not in text
    assert pack_facts.from_text(text)["consensus_data_status"] == "fetch_error"
    ok, reasons = depth_gates.assess({"consensus_data_status": "fetch_error", "gate_version": 6})
    assert "consensus_data_unavailable" in reasons
