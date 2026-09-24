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

    def fake_urlopen(req, timeout=None, context=None):
        seen["ua"] = req.get_header("User-agent")
        seen["context"] = context
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


def test_fetch_verifies_certificates_with_certifi_and_the_windows_store(monkeypatch):
    seen = _capture(monkeypatch)
    at.fetch_page("https://www.example.com/news")
    ctx = seen["context"]
    assert ctx is at._SSL_CTX and ctx is not None
    assert ctx.verify_mode == at.ssl.CERT_REQUIRED and ctx.check_hostname


def test_a_garbled_url_404_opens_the_same_article_the_search_returned(monkeypatch):
    """fool.com/investing/2026-09-14/<slug> (model's copy) vs .../2026/09/14/<slug>/ (search)."""
    import urllib.error
    good = "https://www.fool.com/investing/2026/09/14/why-did-ge-vernova-stock-fall-today/"
    bad = "https://www.fool.com/investing/2026-09-14/why-did-ge-vernova-stock-fall-today/"
    asked = []

    def fake_urlopen(req, timeout=None, context=None):
        asked.append(req.full_url)
        if req.full_url == bad:
            raise urllib.error.HTTPError(bad, 404, "Not Found", {}, None)
        return _Resp("<p>GE Vernova fell 8.6% on AI slowdown fears</p>")

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    r = at.fetch_page(bad, known_urls=["https://other.com/x", good])
    assert asked == [bad, good]
    assert r["url"] == good and r["corrected_from"] == bad and "8.6%" in r["text"]
    assert "does not exist" in r["note"]


def test_a_404_with_no_matching_search_result_stays_an_error(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    r = at.fetch_page("https://www.cnbc.com/2026-09-21/amd-stock-1-trillion-value.html",
                      known_urls=["https://www.cnbc.com/2026/09/21/amd-hits-1-trillion.html"])
    assert "404" in r["error"] and "corrected_from" not in r
    # a short slug never matches (too generic to be the same article)
    assert at._same_article("https://a.com/x/news", ["https://a.com/y/news"]) is None
    # another host never matches
    assert at._same_article("https://a.com/2026-09-01/long-article-slug-here",
                            ["https://b.com/2026/09/01/long-article-slug-here"]) is None
