"""fetch_page: a blocked or paywalled page is replaced by the same story from a legitimate free
copy - a licensed syndication host or another outlet's own reporting - found by searching the
headline. Never a scraped near-verbatim mirror, never an archive/bypass site, never recursive.

E9 discovery runs, 2026-09-24: 28 of 86 fetches were refused (401/403); AMD's run lost the Meta
Muse story because Barron's and Seeking Alpha refused it, while Yahoo Finance and Fox Business
carried the same story free.
"""
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at  # noqa: E402

BARRONS = "https://www.barrons.com/articles/intel-stock-price-arm-meta-muse-2a81cacf"
TITLE = "Meta's Muse AI Agent Triggers Intel, Chip Stock Rally. AMD Hits $1 Trillion"
LONG = "<p>" + "Meta's Muse agent lifted chip stocks; AMD crossed $1 trillion as CPU demand for agents grew. " * 30 + "</p>"


class _Resp:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _web(monkeypatch, pages, results):
    """pages: url -> body or HTTP status int. results: what the headline search returns."""
    asked, searches = [], []

    def fake_urlopen(req, timeout=None, context=None):
        asked.append(req.full_url)
        v = pages.get(req.full_url, 404)
        if isinstance(v, int):
            raise urllib.error.HTTPError(req.full_url, v, "blocked", {}, None)
        return _Resp(v)

    def fake_searx(q, n=10):
        searches.append(q)
        return results

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "_searx", fake_searx)
    return asked, searches


def test_blocked_page_opens_a_licensed_syndicated_copy(monkeypatch):
    yahoo = "https://finance.yahoo.com/news/meta-muse-ai-agent-triggers-chip-rally-amd-1t.html"
    asked, searches = _web(monkeypatch, {BARRONS: 401, yahoo: LONG}, [
        {"url": BARRONS, "title": TITLE},                                   # same host: skipped
        {"url": "https://www.youtube.com/watch?v=abc", "title": TITLE},    # not an article
        {"url": yahoo, "title": TITLE},                                     # licensed syndication
    ])
    r = at.fetch_page(BARRONS, known_urls={BARRONS: TITLE})
    assert searches == [TITLE]
    assert r["url"] == yahoo and r["alternate_for"] == BARRONS and "same story" in r["note"]
    assert "youtube" not in " ".join(asked)


def test_mirror_is_skipped_and_independent_coverage_is_used(monkeypatch):
    mirror = "https://www.live-feeds.com/news/meta-muse-ai-agent-triggers-intel"
    fox = "https://www.foxbusiness.com/markets/meta-muse-agent-chip-rally-amd-trillion"
    asked, _ = _web(monkeypatch, {BARRONS: 403, mirror: LONG, fox: LONG}, [
        {"url": mirror, "title": TITLE},                                    # verbatim copy, unknown host
        {"url": fox, "title": "Meta's Muse agent sparks chip rally as AMD tops $1 trillion"},
    ])
    r = at.fetch_page(BARRONS, known_urls={BARRONS: TITLE})
    assert r["url"] == fox and mirror not in asked


def test_unrelated_results_leave_the_original_error(monkeypatch):
    _web(monkeypatch, {BARRONS: 403}, [
        {"url": "https://medlabbuddy.com/band-neutrophils", "title": "Band Neutrophils: Identification"},
        {"url": "https://www.kbb.com/sell", "title": "How to Sell a Car: 10 Steps"},
    ])
    r = at.fetch_page(BARRONS, known_urls={BARRONS: TITLE})
    assert "403" in r["error"] and "alternate_for" not in r


def test_paywall_teaser_triggers_the_fallback(monkeypatch):
    teaser = "<p>Meta's Muse rally. Subscribe to continue reading this article.</p>"
    yahoo = "https://finance.yahoo.com/news/meta-muse-rally.html"
    _web(monkeypatch, {BARRONS: teaser, yahoo: LONG}, [{"url": yahoo, "title": TITLE}])
    r = at.fetch_page(BARRONS, known_urls={BARRONS: TITLE})
    assert r["alternate_for"] == BARRONS and "Subscribe" in r["paywalled_teaser"]


def test_a_blocked_alternate_never_starts_another_search(monkeypatch):
    other = "https://www.foxbusiness.com/markets/meta-muse-chip-stock-rally-amd"
    asked, searches = _web(monkeypatch, {BARRONS: 403, other: 403}, [{"url": other, "title": TITLE}])
    r = at.fetch_page(BARRONS, known_urls={BARRONS: TITLE})
    assert len(searches) == 1 and "error" in r


def test_a_url_no_search_returned_is_searched_by_its_slug(monkeypatch):
    assert at._slug_query(BARRONS) == "intel stock price arm meta muse"
    assert at._slug_query("https://x.com/a/b") is None
    yahoo = "https://finance.yahoo.com/news/intel-arm-meta-muse-rally.html"
    _, searches = _web(monkeypatch, {BARRONS: 401, yahoo: LONG},
                       [{"url": yahoo, "title": "Intel, Arm stock price jump on Meta Muse agent"}])
    r = at.fetch_page(BARRONS)
    assert searches == ["intel stock price arm meta muse"] and r["url"] == yahoo


def test_sharing_only_the_company_name_is_not_the_same_story(monkeypatch):
    sa = "https://seekingalpha.com/article/4851234-dxc-technologys-ai-ambitions-may-struggle-to-offset-shrinking"
    _web(monkeypatch, {sa: 403, "https://www.pricetargets.com/NYSE/DXC/": LONG},
         [{"url": "https://www.pricetargets.com/NYSE/DXC/", "title": "DXC Technology Price Target"}])
    r = at.fetch_page(sa, known_urls={sa: "DXC Technology's AI Ambitions May Struggle To Offset Shrinking Revenue"})
    assert "error" in r and "alternate_for" not in r


def test_a_low_trust_page_is_replaced_by_a_legitimate_copy(monkeypatch):
    inv = "https://www.investing.com/news/stock-market-news/comfort-systems-usa-stock-soars-to-alltime-high"
    fool = "https://www.fool.com/investing/2026/09/10/comfort-systems-stock-all-time-high-data-center/"
    _web(monkeypatch, {fool: LONG}, [{"url": fool, "title": "Comfort Systems USA stock soars to an all-time high on data center backlog"}])
    r = at.fetch_page(inv, known_urls={inv: "Comfort Systems USA stock soars to all-time high of $394.82"})
    assert r["url"] == fool and r["alternate_for"] == inv
