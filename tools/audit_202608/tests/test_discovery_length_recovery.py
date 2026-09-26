"""chat_with_tools, discovery mode: a final turn cut off by num_predict before the
json:catalysts block gets one recovery turn (thinking off) that asks for the block alone.

MU 2026-09-24: the final turn spent all 16,384 tokens thinking; the run was lost as "no
parseable brief". Valuation runs (max_model_calls > 0) must be untouched: they keep their own
truncation path in consensus_valuation.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at  # noqa: E402

BLOCK = '```json:catalysts\n{"asof": "2026-09-24", "narrative": "n", "events": []}\n```'


def _fake_ollama(monkeypatch, responses):
    """Serve queued /api/chat responses; record each request body."""
    bodies = []
    queue = list(responses)

    class _R:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self, n=-1):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return _R(queue.pop(0))

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    return bodies


def _resp(content, done="stop", thinking=""):
    return {"message": {"content": content, "thinking": thinking}, "done_reason": done,
            "eval_count": 10, "eval_duration": 1_000_000_000}


def test_cut_off_final_turn_gets_one_block_only_recovery(monkeypatch, tmp_path):
    # MU's shape: the final turn thinks to the limit and writes nothing; the forced retry of that
    # empty stub is cut off the same way; only then does the recovery ask for the block alone.
    bodies = _fake_ollama(monkeypatch, [_resp("", done="length", thinking="t" * 50),
                                        _resp("", done="length", thinking="t" * 50), _resp(BLOCK)])
    report, thinking, meta = at.chat_with_tools(
        "m", "prompt", tmp_path, tools=at.research_tools(), max_search_calls=0, max_model_calls=0,
        num_predict=32768, verbose=False)
    assert "```json:catalysts" in report
    assert len(bodies) == 3                     # final turn, forced retry of the empty stub, recovery
    rec = bodies[-1]
    assert rec["think"] is False and rec["options"]["num_predict"] == 8192
    assert "cut off by the length limit" in rec["messages"][-1]["content"]
    assert meta["turns"][-1].get("length_recovery") is True


def test_cut_off_partial_text_is_kept_and_block_appended(monkeypatch, tmp_path):
    bodies = _fake_ollama(monkeypatch, [_resp("Findings so far: memory prices up", done="length"),
                                        _resp(BLOCK)])
    report, _, meta = at.chat_with_tools(
        "m", "prompt", tmp_path, tools=at.research_tools(), max_search_calls=0, max_model_calls=0,
        verbose=False)
    assert report.startswith("Findings so far") and report.endswith("```")
    assert len(bodies) == 2 and bodies[-1]["think"] is False


def test_complete_final_turn_is_not_touched(monkeypatch, tmp_path):
    bodies = _fake_ollama(monkeypatch, [_resp("Findings.\n" + BLOCK, done="length")])
    report, _, meta = at.chat_with_tools(
        "m", "prompt", tmp_path, tools=at.research_tools(), max_search_calls=0, max_model_calls=0,
        verbose=False)
    assert len(bodies) == 1 and not any(t.get("length_recovery") for t in meta["turns"])


def test_valuation_mode_never_gets_the_discovery_recovery(monkeypatch, tmp_path):
    # valuation keeps its own path: the desk-only recovery turn, then the forced report
    bodies = _fake_ollama(monkeypatch, [_resp("partial memo", done="length"),
                                        _resp("still partial", done="length"),
                                        _resp("forced memo")])
    at.chat_with_tools("m", "prompt", tmp_path, max_search_calls=0, max_model_calls=5, verbose=False)
    assert all(b.get("think") is not False for b in bodies)
    assert all("json:catalysts" not in b["messages"][-1]["content"] for b in bodies)


def test_search_result_urls_reach_later_fetches(monkeypatch, tmp_path):
    """chat_with_tools hands every URL search_web returned to fetch_page (its 404 fix needs them)."""
    good = "https://www.fool.com/investing/2026/09/14/why-did-ge-vernova-stock-fall-today/"
    _fake_ollama(monkeypatch, [
        {"message": {"content": "", "tool_calls": [{"function": {"name": "search_web", "arguments": {"query": "q"}}}]},
         "done_reason": "stop"},
        {"message": {"content": "", "tool_calls": [{"function": {"name": "fetch_page", "arguments": {"url": good}}}]},
         "done_reason": "stop"},
        _resp("done\n" + BLOCK)])
    seen = {}

    def fake_dispatch(name, args, snap=None, query_cache=None, url_cache=None, known_urls=None):
        if name == "search_web":
            return {"query": "q", "results": [{"title": "t", "url": good, "snippet": "s"}]}
        seen["known"] = list(known_urls or [])
        return {"url": args["url"], "chars": 4, "text": "text"}

    monkeypatch.setattr(at, "dispatch_tool", fake_dispatch)
    at.chat_with_tools("m", "prompt", tmp_path, tools=at.research_tools(), max_search_calls=5,
                       max_model_calls=0, verbose=False)
    assert seen["known"] == [good]
