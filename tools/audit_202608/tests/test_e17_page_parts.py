"""E17 B2, B3, F page parts, find, and PDF refusal tests."""
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at


class _FakeResp(io.BytesIO):
    def __init__(self, data, ctype="text/html"):
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
        super().__init__(data)
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_page_36526_chars_returns_part_1_of_5(monkeypatch):
    raw_text = "X" * 36526
    html = f"<html><body><p>{raw_text}</p></body></html>"
    monkeypatch.setattr(at.urllib.request, "urlopen", lambda req, *a, **k: _FakeResp(html))

    url_cache = {}
    snap = []
    res = at.fetch_page("https://example.com/long-page", snap=snap, url_cache=url_cache)

    assert res["url"] == "https://example.com/long-page"
    assert res["part"] == 1
    assert res["parts"] == 5
    assert res["chars"] == 36526
    assert len(res["text"]) == 9000
    assert res["text"] == raw_text[:9000]
    expected_note = (
        "part 1 of 5: characters 1-9,000 of 36,526. Call fetch_page again with this url for the next part, "
        "or pass part or find."
    )
    assert res["part_note"] == expected_note
    assert "full_text" not in res
    assert "full_text" in url_cache["https://example.com/long-page"]
    assert url_cache["https://example.com/long-page"]["full_text"] == raw_text


def test_page_part_spans_and_error():
    raw_text = "0123456789" * 3652 + "ABCD"  # 36524 chars
    raw_text = raw_text[:36526]
    # Make exactly 36,526
    raw_text = raw_text.ljust(36526, "Z")
    rec = {"url": "https://example.com/page", "chars": len(raw_text), "full_text": raw_text}

    p2 = at.page_part(rec, 2)
    assert p2["part"] == 2
    assert p2["parts"] == 5
    assert p2["chars"] == 36526
    assert p2["text"] == raw_text[9000:18000]
    assert p2["part_note"] == "part 2 of 5: characters 9,001-18,000 of 36,526. Call fetch_page again with this url for the next part, or pass part or find."

    p5 = at.page_part(rec, 5)
    assert p5["part"] == 5
    assert p5["parts"] == 5
    assert p5["chars"] == 36526
    assert p5["text"] == raw_text[36000:36526]
    assert p5["part_note"] == "part 5 of 5: characters 36,001-36,526 of 36,526, the end of the page."

    p6 = at.page_part(rec, 6)
    assert p6["error"] == "this page has 5 parts; part 6 does not exist."


def test_chat_sequence_parts_find_and_notes(monkeypatch, tmp_path):
    # Construct a 5-part page (> 36,000 chars) with "attrition" in it
    page_text = "hello " * 1000 + "attrition " + "x" * 31516  # exactly 36,526 chars -> 5 parts
    network_calls = []

    turn_plan = [
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq"})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq"})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq", "part": 1})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq", "find": "attrition"})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq"})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq"})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq"})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": "https://example.com/test-seq"})}],
        [],  # report
    ]

    turn_idx = [0]

    def fake_urlopen(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "11434" in url:
            idx = turn_idx[0]
            turn_idx[0] += 1
            tcs = [{"function": tc} for tc in turn_plan[idx]] if idx < len(turn_plan) else []
            content = "Institutional Report " * 500 if not tcs else ""
            return _FakeResp({"message": {"role": "assistant", "content": content, "tool_calls": tcs},
                              "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 10})
        network_calls.append(url)
        return _FakeResp(f"<html><body><p>{page_text}</p></body></html>")

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, verbose=False)

    assert len(network_calls) == 1
    assert meta["repeat_calls"] == 2
    assert meta["research_calls"] == 8

    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    assert len(snap) == 8

    # call 1: part 1 of 5
    assert snap[0]["part"] == 1
    assert snap[0]["parts"] == 5

    # call 2: part 2 of 5
    assert snap[1]["part"] == 2
    assert snap[1]["parts"] == 5

    # call 3: part 1 again with served_again
    assert snap[2]["part"] == 1
    assert "you first read this part at call 1;" in snap[2]["served_again"]

    # call 4: find passages
    assert snap[3]["find"] == "attrition"
    assert snap[3]["matches"] == 1
    assert "[part 1]" in snap[3]["text"]

    # call 5: part 3 of 5
    assert snap[4]["part"] == 3
    assert snap[4]["parts"] == 5

    # call 6: part 4 of 5
    assert snap[5]["part"] == 4
    assert snap[5]["parts"] == 5

    # call 7: part 5 of 5
    assert snap[6]["part"] == 5
    assert snap[6]["parts"] == 5

    # call 8: all-served note with request 8
    expected_all_served = "All 5 parts of this page were served to you (calls 1, 2, 5, 6, 7); this is request 8 for it. Pass part to read one again, or find to search the whole page."
    assert snap[7]["note"] == expected_all_served
    assert "chars" not in snap[7]
    assert "text" not in snap[7]


def test_find_limits_and_passages():
    rec = {"url": "https://example.com/p", "full_text": "Sample text for searching", "chars": 25}

    # 2 characters
    res_short = at.find_in_page(rec, "ab")
    assert res_short["error"] == "find needs 3 to 100 characters."

    # 101 characters
    res_long = at.find_in_page(rec, "x" * 101)
    assert res_long["error"] == "find needs 3 to 100 characters."

    # no match
    res_none = at.find_in_page(rec, "nonexistentphrase")
    assert res_none["matches"] == 0
    assert res_none["find"] == "nonexistentphrase"
    assert res_none["note"] == 'No passage of this page (25 characters) contains "nonexistentphrase".'

    # 7 matches: 2 close together (merged), 5 spread out across parts
    base = ["x"] * 40000
    for pos in (1000, 1400, 9500, 18500, 27500, 36100, 36300):
        for i, ch in enumerate("TARGET"):
            base[pos + i] = ch
    full = "".join(base)
    rec7 = {"url": "https://example.com/multi", "full_text": full, "chars": len(full)}
    res7 = at.find_in_page(rec7, "TARGET")
    assert res7["matches"] == 7
    passages = res7["text"].split("\n\n")
    assert len(passages) == 5  # max_passages = 5
    # First passage merges matches at 1000 and 1400, prefixed with [part 1]
    assert passages[0].startswith("[part 1] ")
    assert passages[1].startswith("[part 2] ")
    assert passages[2].startswith("[part 3] ")
    assert passages[3].startswith("[part 4] ")
    assert passages[4].startswith("[part 5] ")


def test_e16_masked_refusal_and_failure_note(monkeypatch, tmp_path):
    masked_url = "https://example.com/proxy/test\u2026file"

    def fake_dispatch(name, args, **kw):
        return {"url": args.get("url"), "error": "fetch failed: HTTP 403"}

    turn_plan = [
        [{"name": "fetch_page", "arguments": json.dumps({"url": masked_url})}],
        [{"name": "fetch_page", "arguments": json.dumps({"url": masked_url})}],
        [],
    ]
    turn_idx = [0]

    def fake_urlopen(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "11434" in url
        idx = turn_idx[0]
        turn_idx[0] += 1
        tcs = [{"function": tc} for tc in turn_plan[idx]] if idx < len(turn_plan) else []
        content = "Institutional Report " * 500 if not tcs else ""
        return _FakeResp({"message": {"role": "assistant", "content": content, "tool_calls": tcs},
                          "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 10})

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, verbose=False)
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    assert len(snap) == 2
    # call 1: masked refusal
    assert "refused: this address contains '\u2026'" in snap[0]["error"]
    # call 2: E16 failure note
    assert "already fetched in this sample:" in snap[1]["note"]
    assert "it failed (refused: this address contains '\u2026'" in snap[1]["note"]
    assert meta["repeat_calls"] == 1


def test_pdf_refusal_content_type_and_magic_bytes(monkeypatch):
    monkeypatch.setattr(at.urllib.request, "urlopen",
                        lambda req, *a, **k: _FakeResp(b"Binary PDF payload", ctype="application/pdf"))
    res_ctype = at.fetch_page("https://example.com/annual_report.pdf")
    assert res_ctype["error"] == at.PDF_REFUSAL
    assert "text" not in res_ctype

    monkeypatch.setattr(at.urllib.request, "urlopen",
                        lambda req, *a, **k: _FakeResp(b"%PDF-1.7 binary content", ctype="application/octet-stream"))
    res_magic = at.fetch_page("https://example.com/filing_doc")
    assert res_magic["error"] == at.PDF_REFUSAL
    assert "text" not in res_magic


# --- Review fixes (reviewer, 2026-09-27): each test failed on the build as delivered -------------------

def _run_turns(monkeypatch, tmp_path, turns, pages, url_cache=None, searx_results=None):
    """Drive chat_with_tools with scripted tool calls; pages maps url -> text or an HTTP error code."""
    import urllib.error
    turn = {"n": 0}
    network = []

    def fake_urlopen(req, *a, **k):
        url = req.full_url
        if "11434" in url:
            i = turn["n"]
            turn["n"] += 1
            plan = turns[i] if i < len(turns) else []
            tcs = [{"function": {"name": n, "arguments": args}} for n, args in plan]
            return _FakeResp({"message": {"role": "assistant", "content": "" if tcs else "R" * 6000,
                                          "tool_calls": tcs},
                              "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 10})
        network.append(url)
        if url.startswith(at.SEARX):
            return _FakeResp({"results": searx_results or []})
        v = pages[url]
        if isinstance(v, int):
            raise urllib.error.HTTPError(url, v, "blocked", {}, None)
        return _FakeResp(f"<html><body><p>{v}</p></body></html>")

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    rep, think, meta = at.chat_with_tools("fake-model", "prompt", tmp_path, verbose=False, url_cache=url_cache)
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    return snap, meta, network


def test_single_part_note_cites_the_call_that_served_the_page(monkeypatch, tmp_path):
    """The first access is a find, so part 1 is first served at call 2, not call 1."""
    u = "https://example.com/single-part-article"
    snap, meta, network = _run_turns(monkeypatch, tmp_path,
                                     [[("fetch_page", {"url": u, "find": "alpha"})],
                                      [("fetch_page", {"url": u})],
                                      [("fetch_page", {"url": u})]],
                                     {u: "alpha beta gamma " * 50})
    assert snap[0]["find"] == "alpha" and snap[1]["part"] == 1
    assert snap[2]["note"].startswith("This page is a single part, served to you at call 2; this is request 3 for it.")
    assert len(network) == 1


def test_parts_that_are_not_stored_are_never_reported_as_served(monkeypatch, tmp_path):
    """An evidence-store record written before E17 holds part 1 only: later parts are an error each time, and no
    note may claim they were served."""
    v = "https://example.com/old-store-page"
    cache = {v: {"url": v, "chars": 20000, "text": "y" * 9000}}
    snap, meta, network = _run_turns(monkeypatch, tmp_path, [[("fetch_page", {"url": v})]] * 4, {}, url_cache=cache)
    assert snap[0]["part"] == 1 and snap[0]["parts"] == 3
    for c in snap[1:]:
        assert c["error"] == "only part 1 of this page is stored; the rest is not available."
        assert "note" not in c
    assert network == []


def test_a_second_address_reaching_a_read_page_keeps_its_cache_accounting(monkeypatch, tmp_path):
    """The second address is refused and its free copy is the page already read: it serves part 2, and the
    dispatch's cache hit still reaches the P4.0b hit/miss counts."""
    s = "https://www.fool.com/earnings/call-transcripts/2026/08/13/some-company-q3-2026-earnings-call-transcript/"
    b = "https://www.investing.com/news/transcripts/earnings-call-transcript-some-company-q3-2026-misses"
    snap, meta, network = _run_turns(
        monkeypatch, tmp_path, [[("fetch_page", {"url": s})], [("fetch_page", {"url": b})]],
        {s: "z" * 20000, b: 403},
        searx_results=[{"url": s, "title": "Some Company (SC) Q3 2026 Earnings Call Transcript | The Motley Fool"}])
    assert snap[1]["part"] == 2 and snap[1]["same_page_as"] == "call 1" and snap[1]["alternate_for"] == b
    assert snap[1]["cache_hit"] is True
    assert meta["evidence_misses"] == 1 and meta["evidence_hits"] == 1
