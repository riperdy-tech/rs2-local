"""Phase 4 E16 (UGI (b) sample 1, 2026-09-25): a masked or shortened URL is refused with a reason the
model can act on, other non-ASCII URLs are encoded, and a page fetched again in the same sample
returns a note instead of the same text."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at

MASKED = ("http://routify-file-proxy-sg.oss-ap-southeast-1.aliyuncs.com/proxy_temp_file/production/2026-09-25/"
          "x?Expires=1816079676&OSSAccessKeyId=LTAI5t\u2026QVZr&Signature=%2F%2B\u2026w%3D")


def test_a_masked_url_is_refused_with_a_reason_and_never_requested(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no request may be made")
    monkeypatch.setattr(at.urllib.request, "urlopen", boom)
    snap = []
    res = at.fetch_page(MASKED, snap)
    assert res["error"].startswith("refused: this address contains") and "search result" in res["error"]
    assert snap[0]["refused"] == "shortened or masked URL"


def test_other_non_ascii_characters_are_percent_encoded(monkeypatch):
    seen = {}

    class _R:
        def read(self, n=None):
            return b"<html><body><p>" + b"A real paragraph of text about the company. " * 20 + b"</p></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, *a, **k):
        seen["url"] = req.full_url
        return _R()
    monkeypatch.setattr(at.urllib.request, "urlopen", fake)
    at.fetch_page("https://example.com/caf\u00e9-news?q=\u00e9t\u00e9", [], _fallback=False)
    assert seen["url"] == "https://example.com/caf%C3%A9-news?q=%C3%A9t%C3%A9"


def _run(monkeypatch, tmp_path, calls, dispatch):
    class _FakeResp:
        def __init__(self, tcs):
            self._body = json.dumps({"message": {"role": "assistant", "content": "x", "tool_calls": tcs},
                                     "done_reason": "stop"}).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    turn = {"n": 0}

    def fake_urlopen(req, *a, **k):
        turn["n"] += 1
        return _FakeResp([{"function": c} for c in calls] if turn["n"] == 1 else [])
    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", dispatch)
    return at.chat_with_tools("fake-model", "prompt", tmp_path, verbose=False)


def test_a_page_fetched_again_gets_a_note_not_the_same_text(monkeypatch, tmp_path):
    fetched = []

    def dispatch(name, args, snap=None, query_cache=None, url_cache=None, known_urls=None):
        fetched.append(args.get("url"))
        if args.get("url") == "https://bad.example/x":
            return {"url": args["url"], "error": "fetch failed: HTTP 403"}
        return {"url": args.get("url"), "text": "T" * 9000}

    calls = [{"name": "fetch_page", "arguments": json.dumps({"url": u})}
             for u in ("https://fool.com/t", "https://fool.com/t", "https://bad.example/x",
                       "https://bad.example/x", "https://fool.com/t")]
    _, _, meta = _run(monkeypatch, tmp_path, calls, dispatch)
    assert fetched == ["https://fool.com/t", "https://bad.example/x"]          # each page requested once
    assert meta["repeat_calls"] == 3 and meta["research_calls"] == 5          # repeats still counted
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    notes = [c.get("note") for c in snap if c.get("note")]
    assert len(notes) == 3
    assert "you read its first 9,000 characters" in notes[0]
    assert "it failed (fetch failed: HTTP 403)" in notes[1]
