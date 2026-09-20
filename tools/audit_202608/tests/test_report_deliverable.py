"""Issue 1 (GEV 2026-09-20 sample 1): the harness accepted an unparsed tool call as a "report".

Root cause under test: chat_with_tools decided completeness with `not content.strip()`, so any
non-empty terminal content counted as the deliverable. Sample 1 spent 29 minutes on 30 tool calls
and then emitted only the raw `<tool_call>` XML envelope below — Ollama did not parse it into
`tool_calls`, so `tcs` was empty, `content` was non-empty, and the forced report-delivery turn
never fired. The sample was published as `report_chars: 1861` and then discarded.

These tests pin the predicate that decides whether a terminal turn is a deliverable memorandum.
"""
import json

from tools.audit_202608.analyst_tools import report_is_deliverable

# Verbatim shape of ab_reports/consensus/GEV_20260920_135750/sample1.md (1,861 chars).
UNPARSED_TOOL_CALL = """<tool_call>
<function=run_financial_model>
<parameter=price>
951.04
</parameter>
<parameter=scenarios>
[{"base_cf": 8, "name": "Base", "prob": 0.5, "wacc": 0.095}]
</parameter>
<parameter=terminal_g>
0.025
</parameter>
</function>
</tool_call>"""

MEMORANDUM = (
    "SECTION 0. EXECUTIVE VERDICT\n"
    + "\n".join(f"  {n}. Operating driver line {n} with [Actual] provenance." for n in range(400))
    + "\nSECTION 12. MACHINE CONTRACT\n```json:underwriting\n{\"base_iv\": 1037.88}\n```\n"
)


def test_unparsed_tool_call_is_not_a_deliverable_report():
    assert report_is_deliverable(UNPARSED_TOOL_CALL) is False


def test_full_memorandum_is_deliverable():
    assert report_is_deliverable(MEMORANDUM) is True


def test_empty_and_whitespace_are_not_deliverable():
    assert report_is_deliverable("") is False
    assert report_is_deliverable("   \n\t ") is False


def test_short_stub_is_not_a_deliverable_report():
    # A 12-section memorandum cannot be this short; depth_sanity already calls <5000ch a stub.
    assert report_is_deliverable("I recommend holding GEV.") is False


def test_memorandum_with_trailing_stray_tool_call_still_deliverable():
    """A real memo must not be discarded because the model appended a late tool call."""
    assert report_is_deliverable(MEMORANDUM + "\n\n" + UNPARSED_TOOL_CALL) is True


# --- the recovery path itself -----------------------------------------------------------------
# A unit test on the predicate is not enough: the defect was that chat_with_tools never CALLED
# it on this path. These drive the real loop with a stubbed HTTP layer, so the turn after the
# stub is observed rather than assumed.

class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_urlopen(monkeypatch, analyst_tools, turns):
    """Serve `turns` in order and count how many HTTP calls the loop made."""
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(json.loads(req.data.decode()))
        payload = turns[min(len(seen) - 1, len(turns) - 1)]
        return _FakeResponse(payload)

    monkeypatch.setattr(analyst_tools.urllib.request, "urlopen", fake_urlopen)
    return seen


def _msg(payload):
    return {"message": payload, "done_reason": "stop", "eval_count": 10}


def test_stub_terminal_turn_triggers_the_report_delivery_turn(monkeypatch, tmp_path):
    """GEV sample 1 replay: the model ends on an unparsed envelope; the harness must NOT accept
    it, must ask for the memorandum, and must return the memorandum."""
    import tools.audit_202608.analyst_tools as at

    seen = _stub_urlopen(monkeypatch, at, [
        _msg({"content": UNPARSED_TOOL_CALL}),   # the failure that cost the sample
        _msg({"content": MEMORANDUM}),           # the forced memorandum turn
    ])
    report, _think, meta = at.chat_with_tools(
        "test-model", "prompt", tmp_path, verbose=False)

    assert len(seen) == 2, "the stub turn must be followed by exactly one forced turn"
    assert report == MEMORANDUM
    assert meta["stub_rejected"] is True
    # The forced turn must be tool-free, or the model can just call another tool.
    assert "tools" not in seen[1]


def test_deliverable_report_needs_no_forced_turn(monkeypatch, tmp_path):
    import tools.audit_202608.analyst_tools as at

    seen = _stub_urlopen(monkeypatch, at, [_msg({"content": MEMORANDUM})])
    report, _think, meta = at.chat_with_tools(
        "test-model", "prompt", tmp_path, verbose=False)

    assert len(seen) == 1
    assert report == MEMORANDUM
    assert meta["stub_rejected"] is False
