"""Tests for P4 T4 (D4/D8/E3): the research brief template and its header-based guard.

deep_research.py's TOPICS drive an external search model (LDR), so these tests check the
QUERY TEXT the template sends (the only part this repo controls) plus the deterministic parts
build() writes itself (the header line, the "claims not facts" wording) — never a live search.
research_brief_guard.py's header preference is tested directly against brief_text strings.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))

import deep_research
from tools.audit_202608.research_brief_guard import check_research_brief, _header_company_match


def _topic(title):
    for t, q in deep_research.TOPICS:
        if t == title:
            return q
    raise AssertionError(f"no topic named {title!r} in deep_research.TOPICS")


# ---------------------------------------------------------------------------------------------
# Template text (D4 / D8 / E3)
# ---------------------------------------------------------------------------------------------

def test_what_changed_topic_covers_12_months_30_day_sourcing_and_ai_exposure():
    q = _topic("What Changed in the Last 12 Months")
    assert "last 12 months" in q
    assert "company AND its industry" in q
    assert "3 sources dated within the last 30 days" in q
    assert "growth driver" in q
    assert "AI" in q and "AI revenue share" in q and "customer concentration" in q


def test_catalysts_topic_requests_a_fenced_guidance_block():
    q = _topic("Catalysts & Guidance")
    assert "```guidance" in q
    assert "metric | period | value | source | date" in q
    # only dated, sourced figures — an empty block is explicitly allowed rather than fabricated
    assert "empty ```guidance``` block" in q


def test_every_topic_is_still_formattable_with_subj_and_yr():
    """The two new/edited entries must not break the {subj}/{yr} substitution every topic uses."""
    for _title, q in deep_research.TOPICS:
        q.format(subj="Example Corp (EX)", yr=2026)  # raises KeyError/IndexError on a bad brace


# ---------------------------------------------------------------------------------------------
# build() — deterministic header line and claims wording (no network: run_topic is mocked)
# ---------------------------------------------------------------------------------------------

def test_build_writes_fixed_header_and_claims_wording(monkeypatch, tmp_path):
    monkeypatch.setitem(deep_research.CONFIG, "out_research_dir", str(tmp_path))
    monkeypatch.setattr(deep_research, "fresh", lambda *a, **k: False)
    monkeypatch.setattr(deep_research, "preflight", lambda *a, **k: None)
    monkeypatch.setattr(deep_research.rs2_data, "sector_lookup",
                        lambda t: ("Technology", "Consumer Electronics"))
    monkeypatch.setattr(deep_research, "flag_consistency", lambda *a, **k: None)

    def fake_run_topic(query):
        return ("mock_engine", {}, ["https://www.sec.gov/edgar/example-filing"])

    monkeypatch.setattr(deep_research, "run_topic", fake_run_topic)

    path = deep_research.build("AAPL", "Apple Inc.", force=True)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines[0] == "Company: Apple Inc. | Ticker: AAPL | Industry: Consumer Electronics"
    assert "not a verified fact" in text
    assert "check it against the filings in the pack" in text
    # every topic actually ran (including the new one) and contributed a section
    assert "## What Changed in the Last 12 Months" in text
    assert "## Catalysts & Guidance" in text


def test_build_header_falls_back_to_unknown_without_name_or_industry(monkeypatch, tmp_path):
    monkeypatch.setitem(deep_research.CONFIG, "out_research_dir", str(tmp_path))
    monkeypatch.setattr(deep_research, "fresh", lambda *a, **k: False)
    monkeypatch.setattr(deep_research, "preflight", lambda *a, **k: None)
    monkeypatch.setattr(deep_research.rs2_data, "sector_lookup", lambda t: (None, None))
    monkeypatch.setattr(deep_research, "flag_consistency", lambda *a, **k: None)
    monkeypatch.setattr(deep_research, "run_topic",
                        lambda q: ("mock_engine", {}, ["https://www.sec.gov/edgar/x"]))

    path = deep_research.build("ZZZZ", "", force=True)
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "Company: Unknown | Ticker: ZZZZ | Industry: Unknown"


# ---------------------------------------------------------------------------------------------
# research_brief_guard.py — header preference (D8)
# ---------------------------------------------------------------------------------------------

def test_header_exact_match_is_sufficient_with_no_industry_word_anywhere():
    """The header alone must clear the guard even when the body never mentions the industry —
    the scenario body-text matching alone could not previously handle without an industry word."""
    brief = (
        "Company: GE Vernova Inc. | Ticker: GEV | Industry: Specialty Industrial Machinery\n"
        "# DEEP RESEARCH BRIEF — GE Vernova Inc. (GEV)\n\n"
        "## Competitive Position\nGas turbine orders and grid equipment backlog drive growth.\n")
    ok, reason = check_research_brief(
        "GEV", brief_text=brief, company_name="GE Vernova Inc.",
        sector="Utilities", industry="Something Unrelated To The Body Text")
    assert ok is True
    assert reason is None


def test_header_wrong_ticker_falls_through_to_body_checks():
    """A header naming a DIFFERENT ticker must not short-circuit the guard — it must fall
    through to the existing name/industry checks (and fail, since the body is also wrong)."""
    brief = (
        "Company: Microsoft Corporation | Ticker: MSFT | Industry: Software\n"
        "Azure and Windows drive strong revenue for Microsoft.\n")
    ok, reason = check_research_brief(
        "AAPL", brief_text=brief, company_name="Apple Inc.",
        sector="Technology", industry="Consumer Electronics")
    assert ok is False


def test_header_name_mismatch_is_not_trusted_on_ticker_alone():
    """Right ticker, wrong legal name in the header (e.g. a stale/copied header) must not be
    accepted via the header — the name must also match exactly. With no name or industry word
    anywhere else in the body, the brief must be refused."""
    brief = (
        "Company: Some Other Company Inc. | Ticker: AAPL | Industry: Widget Manufacturing\n"
        "This paragraph names neither the real company nor its real industry in any way.\n")
    ok, reason = check_research_brief(
        "AAPL", brief_text=brief, company_name="Apple Inc.",
        sector="Technology", industry="Consumer Electronics")
    assert ok is False


def test_header_match_helper_only_looks_near_the_top():
    """A header-shaped line deep in the body (past the lookback window) must not count as the
    real header — otherwise a brief could smuggle a false company match anywhere in its text.
    Tested directly against the helper (rather than the full guard) because the guard's separate
    whole-document name scan would independently find "Apple Inc." wherever it appears and mask
    what this test is checking."""
    padding = "x" * 1000
    brief_header_near_top = "Company: Apple Inc. | Ticker: AAPL | Industry: Consumer Electronics\n"
    brief_header_buried = f"# some other line\n{padding}\n{brief_header_near_top}"

    assert _header_company_match(brief_header_near_top, "AAPL", "Apple Inc.") is True
    assert _header_company_match(brief_header_buried, "AAPL", "Apple Inc.") is False
