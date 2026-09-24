"""fetch_page: sec.gov gets the declared SEC identity, EDGAR headers are skipped, entities decoded.

Found 2026-09-24 in the E9 discovery runs: every sec.gov fetch failed with HTTP 403 (EDGAR's
fair-access policy wants a declared contact), GEV's run tried the same filing three times, and
numeric entities (&#160; &#8226;) filled the text the model is shown.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at  # noqa: E402
import sec_guidance  # noqa: E402


class _Resp:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, body="<html><body>ok</body></html>"):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        return _Resp(body)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_sec_gov_fetch_uses_the_declared_sec_identity(monkeypatch):
    seen = _capture(monkeypatch)
    at.fetch_page("https://www.sec.gov/Archives/edgar/data/1/000/0001.txt")
    assert seen["ua"] == sec_guidance.UA["User-Agent"]
    at.fetch_page("https://efts.sec.gov/LATEST/search-index?q=x")
    assert seen["ua"] == sec_guidance.UA["User-Agent"]


def test_other_hosts_keep_the_generic_identity(monkeypatch):
    seen = _capture(monkeypatch)
    at.fetch_page("https://www.example.com/news")
    assert seen["ua"] == at.UA["User-Agent"]
    at.fetch_page("https://notsec.gov.example.com/a")      # look-alike host is not SEC
    assert seen["ua"] == at.UA["User-Agent"]


def test_edgar_submission_header_is_skipped(monkeypatch):
    body = ("<SEC-HEADER>ACCESSION NUMBER: 0001 " + "HEADER " * 2000 + "</SEC-HEADER>"
            "<DOCUMENT><TYPE>8-K<TEXT><html><body>Item 2.02 Results of Operations</body></html>"
            "</TEXT></DOCUMENT>")
    _capture(monkeypatch, body)
    r = at.fetch_page("https://www.sec.gov/Archives/edgar/data/1/000/0001.txt")
    assert r["text"].startswith("8-K")
    assert "Item 2.02 Results of Operations" in r["text"]
    assert "ACCESSION NUMBER" not in r["text"]


def test_numeric_and_named_entities_are_decoded(monkeypatch):
    _capture(monkeypatch, "<p>Orders&#58; $24.2&#160;B &#8226; R&amp;D up</p>")
    r = at.fetch_page("https://www.example.com/pr")
    assert r["text"] == "Orders: $24.2 B • R&D up"
