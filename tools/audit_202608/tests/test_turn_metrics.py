"""Per-turn cost instrumentation, and the snapshot gap that hides repeated fetches.

Two defects this pins down:

1. A sample's wall time could not be attributed to turns. The loop accumulates only whole-sample
   totals (`gen_tokens`, `eval_duration_total`), so "which turn cost 15 minutes" was unanswerable
   from the run directory. Measured on GEV: one turn took 952s, and 36% of the sample sat before
   the first tool call and after the last — invisible in every total.

2. `fetch_page`'s url_cache hit returns WITHOUT snapshotting (analyst_tools.py:224-225). GEV sample 1
   made 28 tool calls but only 22 reached `_research_snapshot.json`; the 6 missing are repeat
   fetches of the same URL. The module's stated rule is "SNAPSHOT EVERYTHING ... every fetched
   page is written into the run directory", so the audit trail is silently incomplete — and the
   missing turns are also invisible to any timing analysis built on those timestamps.
"""
import json

import pytest

from tools.audit_202608.analyst_tools import chat_with_tools, fetch_page, turn_metrics


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _payload(**over):
    base = {
        "message": {"content": "x" * 6000},
        "done_reason": "stop",
        "prompt_eval_count": 13096,
        "prompt_eval_duration": 11_290_000_000,
        "eval_count": 500,
        "eval_duration": 8_000_000_000,
        "load_duration": 15_900_000_000,
    }
    base.update(over)
    return base


# --- 1. turn_metrics: a pure mapping from an Ollama response to a per-turn cost record ---------

def test_turn_metrics_maps_ollama_response():
    t = turn_metrics(_payload())
    assert t["prompt_tokens"] == 13096
    assert t["prompt_eval_s"] == pytest.approx(11.29, abs=0.01)
    assert t["gen_tokens"] == 500
    assert t["gen_s"] == pytest.approx(8.0, abs=0.01)
    assert t["load_s"] == pytest.approx(15.9, abs=0.01)
    assert t["done_reason"] == "stop"
    assert t["n_tool_calls"] == 0


def test_turn_metrics_counts_tool_calls_and_tolerates_missing_fields():
    t = turn_metrics({"message": {"content": "", "tool_calls": [{}, {}, {}]}})
    assert t["n_tool_calls"] == 3
    assert t["prompt_tokens"] is None
    assert t["prompt_eval_s"] == 0.0
    assert t["done_reason"] is None


# --- 2. the loop records one entry per turn, in the snapshot and in meta ----------------------

def test_chat_with_tools_records_a_turn_per_round_trip(monkeypatch, tmp_path):
    import tools.audit_202608.analyst_tools as at

    # two turns, then a deliverable report, so the loop runs three times
    turns = [
        _payload(message={"content": "", "tool_calls": [
            {"function": {"name": "search_web", "arguments": {"query": "q"}}}]}),
        _payload(message={"content": "", "tool_calls": [
            {"function": {"name": "search_web", "arguments": {"query": "q"}}}]}),
        _payload(message={"content": "y" * 6000}),
    ]
    seen = []

    class _Boom(Exception):
        pass

    def fake_urlopen(req, timeout=None):
        seen.append(1)
        return _FakeResponse(turns[min(len(seen) - 1, len(turns) - 1)])

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "search_web", lambda *a, **k: {"results": []})

    _rep, _think, meta = at.chat_with_tools("m", "pack", tmp_path, verbose=False)

    assert len(meta["turns"]) == len(seen) == 3
    assert [t["turn"] for t in meta["turns"]] == [1, 2, 3]
    # the tool-call turn must be distinguishable from the final report turn
    assert meta["turns"][0]["n_tool_calls"] == 1
    assert meta["turns"][-1]["n_tool_calls"] == 0
    snapshot = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))
    assert len(snapshot["turns"]) == 3


# --- 3. a cache-hit fetch must still reach the snapshot ---------------------------------------

def test_cached_fetch_page_is_still_snapshotted():
    snap = []
    url = "https://www.sec.gov/Archives/edgar/data/1996810/example.htm"
    cache = {url: {"url": url, "text": "already fetched earlier in this sample"}}

    fetch_page(url, snap, url_cache=cache)

    assert len(snap) == 1, "a URL-cache hit still counts as a fetched page the model saw"
    assert snap[0]["tool"] == "fetch_page"
    assert snap[0]["cached"] is True
    assert snap[0]["url"] == url


def test_uncached_fetch_page_records_cached_false(monkeypatch):
    import tools.audit_202608.analyst_tools as at

    class _PageResp:
        # read() must accept the byte cap fetch_page passes; an earlier fake took no argument,
        # raised TypeError, and was swallowed by the error path — which is how the missing
        # failure-path snapshot below was found.
        def read(self, n=None):
            return b"<html><body>" + b"z" * 300 + b"</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(at.urllib.request, "urlopen", lambda *a, **k: _PageResp())
    snap = []
    fetch_page("https://example.test/fresh", snap, url_cache={})
    assert len(snap) == 1
    assert snap[0]["cached"] is False


def test_failed_fetch_is_snapshotted(monkeypatch):
    """A fetch that raises is still a tool result the model received."""
    import tools.audit_202608.analyst_tools as at

    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(at.urllib.request, "urlopen", boom)
    snap = []
    out = fetch_page("https://example.test/slow", snap, url_cache={})
    assert "error" in out
    assert len(snap) == 1
    assert "error" in snap[0]
    assert snap[0]["cached"] is False
