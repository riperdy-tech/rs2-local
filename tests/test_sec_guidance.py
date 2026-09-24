"""tests/test_sec_guidance.py — tests for sec_guidance.py and SEC earnings release integration."""
import io
import json
import urllib.error
from datetime import date
from pathlib import Path
import pytest

import sec_guidance
import depth_triggers
import capability_test as cap


class DummyResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_depth_triggers_submissions_alias():
    """depth_triggers._submissions is still importable and is the same function."""
    assert depth_triggers._submissions is sec_guidance._submissions
    assert depth_triggers.UA is sec_guidance.UA
    assert depth_triggers.SUB_CACHE == sec_guidance.SUB_CACHE


def test_selection_picks_newest_8k_with_202_and_ignores_without_and_after_asof(monkeypatch):
    """Selection picks the newest 8-K with 2.02 and ignores 8-Ks without 2.02 and filings after asof."""
    fake_subs = {
        "filings": {
            "recent": {
                "form": ["8-K", "8-K", "10-Q", "8-K", "8-K"],
                "filingDate": ["2026-08-20", "2026-08-10", "2026-08-05", "2026-08-01", "2026-07-01"],
                "items": ["5.02", "2.02,9.01", "", "2.02", "1.01"],
                "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003", "0001-26-000004", "0001-26-000005"],
            }
        }
    }
    monkeypatch.setattr(sec_guidance, "_submissions", lambda cik: fake_subs)

    # Mock fetch of the accession text
    fetched_urls = []
    sample_sgml = (
        "<DOCUMENT>\n<TYPE>8-K\n<TEXT>8-K</TEXT>\n</DOCUMENT>\n"
        "<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>Lead exhibit text. AMD expects Q3 revenue of $13B.</TEXT>\n</DOCUMENT>"
    )

    def fake_urlopen(req, timeout=60):
        fetched_urls.append(req.full_url)
        return DummyResponse(sample_sgml.encode("utf-8"))

    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", fake_urlopen)

    # 1. Without asof: should skip 2026-08-20 (items 5.02, no 2.02) and pick 2026-08-10 (accession 0001-26-000002)
    res = sec_guidance.latest_earnings_release("0000001234", asof=None)
    assert res is not None
    assert res["accession"] == "0001-26-000002"
    assert res["filing_date"] == "2026-08-10"
    assert "0001-26-000002.txt" in fetched_urls[-1]

    # 2. With asof="2026-08-05": should ignore 2026-08-20 and 2026-08-10, and pick 2026-08-01 (accession 0001-26-000004)
    res_asof = sec_guidance.latest_earnings_release("0000001234", asof="2026-08-05")
    assert res_asof is not None
    assert res_asof["accession"] == "0001-26-000004"
    assert res_asof["filing_date"] == "2026-08-01"

    # 3. With asof="2026-06-30": no 8-K with 2.02 on or before this date
    res_none = sec_guidance.latest_earnings_release("0000001234", asof="2026-06-30")
    assert res_none is None
    assert sec_guidance.latest_earnings_release.last_reason == "no 8-K Item 2.02 on or before 2026-06-30"


def test_asof_mode_never_selects_filing_dated_after_asof(monkeypatch):
    """asof mode never selects a filing dated after asof."""
    fake_subs = {
        "filings": {
            "recent": {
                "form": ["8-K", "8-K"],
                "filingDate": ["2026-04-15", "2026-03-15"],
                "items": ["2.02", "2.02"],
                "accessionNumber": ["acc-future", "acc-past"],
            }
        }
    }
    monkeypatch.setattr(sec_guidance, "_submissions", lambda cik: fake_subs)
    sample_sgml = "<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>Content</TEXT>\n</DOCUMENT>"
    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", lambda req, timeout=60: DummyResponse(sample_sgml.encode("utf-8")))

    res = sec_guidance.latest_earnings_release("0000001234", asof="2026-03-31")
    assert res is not None
    assert res["accession"] == "acc-past"
    assert res["filing_date"] == "2026-03-15"
    assert res["filing_date"] <= "2026-03-31"


def test_exhibit_preference_ex99_1_over_ex99(monkeypatch):
    """EX-99.1 preferred over EX-99, EX-99.01 preferred over EX-99."""
    fake_subs = {
        "filings": {
            "recent": {
                "form": ["8-K"],
                "filingDate": ["2026-08-01"],
                "items": ["2.02"],
                "accessionNumber": ["acc-exhibit"],
            }
        }
    }
    monkeypatch.setattr(sec_guidance, "_submissions", lambda cik: fake_subs)

    # 1. Both EX-99 and EX-99.1 present: EX-99.1 must be chosen even if EX-99 appears first
    sgml_1 = (
        "<DOCUMENT>\n<TYPE>EX-99\n<TEXT>Old exhibit</TEXT>\n</DOCUMENT>\n"
        "<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>Preferred 99.1 exhibit</TEXT>\n</DOCUMENT>\n"
    )
    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", lambda req, timeout=60: DummyResponse(sgml_1.encode("utf-8")))
    res1 = sec_guidance.latest_earnings_release("0000001234", asof=None)
    assert res1 is not None
    assert "Preferred 99.1 exhibit" in res1["text"]

    # 2. Both EX-99 and EX-99.01 present, no EX-99.1: EX-99.01 must be chosen
    fake_subs["filings"]["recent"]["accessionNumber"] = ["acc-exhibit-01"]
    sgml_2 = (
        "<DOCUMENT>\n<TYPE>EX-99\n<TEXT>Old exhibit</TEXT>\n</DOCUMENT>\n"
        "<DOCUMENT>\n<TYPE>EX-99.01\n<TEXT>Preferred 99.01 exhibit</TEXT>\n</DOCUMENT>\n"
    )
    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", lambda req, timeout=60: DummyResponse(sgml_2.encode("utf-8")))
    res2 = sec_guidance.latest_earnings_release("0000001234", asof=None)
    assert res2 is not None
    assert "Preferred 99.01 exhibit" in res2["text"]

    # 3. Only EX-99 present: falls back to EX-99
    fake_subs["filings"]["recent"]["accessionNumber"] = ["acc-exhibit-99"]
    sgml_3 = "<DOCUMENT>\n<TYPE>EX-99\n<TEXT>Fallback 99 exhibit</TEXT>\n</DOCUMENT>\n"
    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", lambda req, timeout=60: DummyResponse(sgml_3.encode("utf-8")))
    res3 = sec_guidance.latest_earnings_release("0000001234", asof=None)
    assert res3 is not None
    assert "Fallback 99 exhibit" in res3["text"]


def test_guidance_excerpt_rules():
    """Excerpt keeps an outlook sentence with a digit, drops a keyword sentence with no digit,
    drops the safe-harbor sentence, respects the cap and document order."""
    text = (
        "Headline Earnings Summary for Company X. Total revenue reached $100M. "
        + "A" * 300 + ". "
        "For third quarter of 2026, guidance expects revenue to be approximately $13 billion. "
        "The company has great outlook and momentum across all divisions. "
        "Safe harbor: forward-looking statements regarding our 2026 outlook are subject to risks and uncertainties. "
        "Backlog as of June 30, 2026 was $14.06 billion. "
        "Backlog as of June 30, 2026 was $14.06 billion. "  # duplicate
        "Total orders reached $5B in the quarter."
    )
    excerpt = sec_guidance.guidance_excerpt(text, cap=3000)
    lines = excerpt.splitlines()

    # All lines prefixed with '- '
    assert all(line.startswith("- ") for line in lines)

    # First line contains lead 400 chars
    assert "Headline Earnings Summary" in lines[0]

    # Keeps outlook sentence with a digit
    assert any("guidance expects revenue to be approximately $13 billion" in l for l in lines)

    # Drops keyword sentence with no digit
    assert not any("great outlook and momentum across all divisions" in l for l in lines)

    # Drops safe-harbor sentence
    assert not any("forward-looking statements" in l.lower() for l in lines)
    assert not any("safe harbor" in l.lower() for l in lines)

    # Keeps backlog with digit
    assert any("$14.06 billion" in l for l in lines)

    # Deduplicated: backlog sentence appears only once
    backlog_lines = [l for l in lines if "$14.06 billion" in l]
    assert len(backlog_lines) == 1

    # Document order: guidance expects sentence appears before backlog sentence, before orders sentence
    idx_guidance = next(i for i, l in enumerate(lines) if "guidance expects" in l)
    idx_backlog = next(i for i, l in enumerate(lines) if "Backlog" in l)
    idx_orders = next(i for i, l in enumerate(lines) if "Total orders" in l)
    assert idx_guidance < idx_backlog < idx_orders

    # Respects cap
    short_cap = len(lines[0]) + 1 + len(lines[1]) + 5
    short_excerpt = sec_guidance.guidance_excerpt(text, cap=short_cap)
    assert len(short_excerpt) <= short_cap
    assert "Total orders" not in short_excerpt


def test_stale_label_at_121_days_and_not_at_120(monkeypatch):
    """STALE label at 121 days and not at 120."""
    monkeypatch.setattr(cap, "cik", lambda t: "0000001234")
    # Base filing date: 2026-01-01
    fake_rel = {
        "accession": "0001-26-000001",
        "filing_date": "2026-01-01",
        "url": "https://www.sec.gov/Archives/edgar/data/1234/000126000001/0001-26-000001.txt",
        "text": "Lead exhibit text. Guidance expects $10B in 2026.",
    }
    monkeypatch.setattr(sec_guidance, "latest_earnings_release", lambda cik, asof=None: fake_rel)

    # 120 days after 2026-01-01 is 2026-05-01 (Jan 31 + Feb 28 + Mar 31 + Apr 30 = 120 days)
    pack_120 = cap.build_pack("TEST", asof="2026-05-01")
    assert "STALE" not in pack_120
    assert "COMPANY'S OWN WORDS — latest earnings release (SEC 8-K Item 2.02, filed 2026-01-01" in pack_120

    # 121 days after 2026-01-01 is 2026-05-02
    pack_121 = cap.build_pack("TEST", asof="2026-05-02")
    assert "STALE (121 days) — COMPANY'S OWN WORDS — latest earnings release (SEC 8-K Item 2.02, filed 2026-01-01" in pack_121


def test_fetch_failure_yields_sec_fetch_failed_and_build_pack_succeeds(monkeypatch):
    """Fetch failure -> 'not available — SEC fetch failed' and build_pack still succeeds."""
    monkeypatch.setattr(cap, "cik", lambda t: "0000001234")

    def boom_fetch(req, timeout=60):
        raise urllib.error.URLError("SEC network timeout")

    monkeypatch.setattr(sec_guidance.urllib.request, "urlopen", boom_fetch)

    # Calling latest_earnings_release directly returns None and records reason
    res = sec_guidance.latest_earnings_release("0000001234")
    assert res is None
    assert sec_guidance.latest_earnings_release.last_reason == "SEC fetch failed"

    # build_pack succeeds and contains graceful degraded message
    pack = cap.build_pack("TEST")
    assert "COMPANY'S OWN WORDS: not available — SEC fetch failed" in pack
