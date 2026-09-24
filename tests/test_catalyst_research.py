"""tests/test_catalyst_research.py — tests for discovery run, catalyst brief, slicing, and pack integration."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import pytest

import catalyst_research as cr
import capability_test as cap


def test_discovery_context_slices_and_fallbacks(monkeypatch):
    sample_pack = """# DATA PACK - TEST
## SECTION 1 - OVERVIEW
Some overview

## SECTION 2.5 - PRICE ACTION (facts, not a valuation input)   [Arithmetic]
- 12-1 month return: +50.0%
- 1-month return: +12.0%
These are facts about price and are not a valuation input.

## RECENT COMPANY NEWS   [SearXNG news search]
- The stock moved +12.0% in 1 month and +50.0% in 6 months (SECTION 2.5).
- 2026-09-20 | reuters.com | Major partnership announced | https://reuters.com/news/1 | Partnership details

## SECTION 3 - TRAILING TWELVE MONTHS
- Revenue: $10.0B

## SECTION 8 - CONSENSUS & MULTIPLES   [Aggregator]
- Trailing P/E: 25.0
- CONSENSUS ESTIMATES   [yfinance, fetched 2026-09-24]
| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | growth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current FY | $10.0B | $9.5B | $10.5B | 20 | +15% | $2.00 | $1.80 | $2.20 | +20% |
| next FY | $12.0B | $11.0B | $13.0B | 22 | +20% | $2.50 | $2.20 | $2.80 | +25% |
- Next-FY EPS estimate trend: now $2.50 | 30 days ago $2.40 | 60 days ago $2.30 | 90 days ago $2.20  (+13.6% in 90 days)
- Estimate revisions, last 30 days (next FY): 15 up / 2 down  (last 7 days: 3 up / 0 down)
- Analyst price targets: low 50 / mean 70 / high 90

## GUIDANCE & CONSENSUS   [company's own earnings release]
COMPANY'S OWN WORDS — latest earnings release (SEC 8-K Item 2.02, filed 2026-08-01).
Management expects revenue growth of 15-20% for the full year.
Additional commentary here.

## SECTION 12 - WHAT WE DO NOT HOLD
Declared gaps.
"""
    monkeypatch.setattr(cap, "build_pack", lambda ticker, include_research=False: cap.PackText(sample_pack))
    monkeypatch.setattr(cap, "LAST_PACK_MOMENTUM_STATE", {"mom_1m": 0.12, "mom_6m": 0.50})
    monkeypatch.setattr(cr.rs2_data, "resolve_name", lambda t: "Test Company Inc.")
    monkeypatch.setattr(cr.rs2_data, "sector_lookup", lambda t: ("Technology", "Semiconductors"))

    ctx = cr.discovery_context("TEST")
    assert ctx["ticker"] == "TEST"
    assert ctx["company"] == "Test Company Inc."
    assert ctx["sector"] == "Technology"
    assert ctx["industry"] == "Semiconductors"
    assert ctx["mom_1m"] == 0.12
    assert ctx["mom_6m"] == 0.50
    assert "## SECTION 2.5 - PRICE ACTION" in ctx["section_2_5"]
    assert "## RECENT COMPANY NEWS" in ctx["recent_news"]
    assert "- CONSENSUS ESTIMATES" in ctx["consensus_estimates"]
    assert "- Estimate revisions, last 30 days" in ctx["consensus_estimates"]
    assert "- Analyst price targets" not in ctx["consensus_estimates"]
    assert "## GUIDANCE & CONSENSUS" in ctx["guidance"]
    assert len(ctx["guidance"].splitlines()) == 3
    assert "Additional commentary here" not in ctx["guidance"]

    # Fallback when blocks are absent
    monkeypatch.setattr(cap, "build_pack", lambda ticker, include_research=False: cap.PackText("# Empty pack\n"))
    ctx_fallback = cr.discovery_context("TEST")
    assert "not available" in ctx_fallback["section_2_5"]
    assert "not available" in ctx_fallback["recent_news"]
    assert "not available" in ctx_fallback["consensus_estimates"]
    assert "not available" in ctx_fallback["guidance"]


def test_parse_catalyst_brief_blocks(monkeypatch, tmp_path):
    """Parses ```json:catalysts block and plain ```json block, or records error."""
    # 1. json:catalysts block
    report_catalysts = """Here is my research:
```json:catalysts
{
  "asof": "2026-09-24",
  "narrative": "Growth accelerating",
  "bear_narrative": "Margin pressure",
  "events": [
    {"date": "2026-09-20", "event": "New product", "mechanism": "Raises rev", "direction": "bull", "estimates_moved": "up 5%", "source_url": "https://example.com/p1"}
  ],
  "open_questions": ["Will margins hold?"]
}
```
"""
    # 2. plain json block
    report_plain = """Here is my research:
```json
{
  "asof": "2026-09-24",
  "narrative": "Turnaround underway",
  "bear_narrative": "High debt",
  "events": [],
  "open_questions": []
}
```
"""
    # 3. invalid / missing block
    report_missing = "I could not find structured data."

    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.05, "facts": "facts"
    })

    # Test 1
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools",
                        lambda *a, **k: (report_catalysts, "", {"tool_calls": 2}))
    b1 = cr.run("T1", force=True)
    assert b1["error"] is None
    assert b1["narrative"] == "Growth accelerating"
    assert len(b1["events"]) == 1

    # Test 2
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools",
                        lambda *a, **k: (report_plain, "", {"tool_calls": 1}))
    b2 = cr.run("T2", force=True)
    assert b2["error"] is None
    assert b2["narrative"] == "Turnaround underway"

    # Test 3
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools",
                        lambda *a, **k: (report_missing, "", {"tool_calls": 0}))
    b3 = cr.run("T3", force=True)
    assert b3["error"] == "no parseable brief"


def test_url_verification(monkeypatch, tmp_path):
    """URL verification: normalized match, cache hit counts, failed fetch does not."""
    report = """
```json:catalysts
{
  "asof": "2026-09-24",
  "narrative": "AI boom",
  "bear_narrative": "Capex cycle",
  "events": [
    {"date": "2026-09-20", "event": "Chip launch", "mechanism": "Revenue up", "direction": "bull", "estimates_moved": "up", "source_url": "HTTPS://WWW.REUTERS.COM/tech/chips/"},
    {"date": "2026-09-18", "event": "Supplier deal", "mechanism": "Capacity secured", "direction": "bull", "estimates_moved": "none", "source_url": "https://bloomberg.com/news/123"},
    {"date": "2026-09-15", "event": "Failed fetch event", "mechanism": "Unknown", "direction": "bear", "estimates_moved": "none", "source_url": "https://example.com/failed"},
    {"date": "2026-09-10", "event": "Unread article", "mechanism": "None", "direction": "bear", "estimates_moved": "none", "source_url": "https://unfetched.com/news"}
  ],
  "open_questions": []
}
```
"""
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.02, "facts": "facts"
    })

    def fake_chat(*args, **kwargs):
        out_dir = kwargs.get("out_dir")
        out_dir.mkdir(parents=True, exist_ok=True)
        # Snapshot containing 3 fetch_page calls:
        # 1. reuters.com: trailing slash, uppercase
        # 2. bloomberg.com: cache hit
        # 3. example.com/failed: failed fetch (chars=0, error set)
        snap = {
            "tool_calls": 3,
            "calls": [
                {"tool": "fetch_page", "url": "https://www.reuters.com/tech/chips", "chars": 1500, "text": "Content", "cached": False},
                {"tool": "fetch_page", "url": "https://bloomberg.com/news/123/", "chars": 2000, "text": "Content cached", "cached": True},
                {"tool": "fetch_page", "url": "https://example.com/failed", "chars": 0, "text": "", "error": "fetch failed: 404"},
            ]
        }
        (out_dir / "_research_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
        return report, "", {"tool_calls": 3}

    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", fake_chat)

    b = cr.run("TEST_URL", force=True)
    assert b["pages_read"] == 2  # reuters and bloomberg only
    evs = b["events"]
    assert evs[0]["verified"] is True   # reuters matched despite HTTPS://WWW and trailing slash
    assert evs[1]["verified"] is True   # bloomberg matched cache hit
    assert evs[2]["verified"] is False  # failed fetch does not verify
    assert evs[3]["verified"] is False  # unfetched page does not verify
    assert "unverified_events:2" in b["flags"]


def test_flags_at_edges(monkeypatch, tmp_path):
    """Flags at edges:
    - 2 events -> too_few_events; 3 events -> not
    - mom_1m 0.10 with newest event 46 days old -> recent_move_unexplained; 44 days -> not
    """
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    today = datetime(2026, 9, 24).date()

    # Edge 1: 2 events vs 3 events
    def make_report(events):
        return f"""
```json:catalysts
{{
  "asof": "2026-09-24",
  "narrative": "Narrative",
  "bear_narrative": "Bear narrative",
  "events": {json.dumps(events)},
  "open_questions": []
}}
```
"""
    # 2 events
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.05, "facts": "facts"
    })
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (make_report([
        {"date": "2026-09-20", "event": "E1", "mechanism": "M1", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": "2026-09-19", "event": "E2", "mechanism": "M2", "direction": "bull", "estimates_moved": "none", "source_url": ""},
    ]), "", {}))
    b_2ev = cr.run("T_2EV", force=True)
    assert "too_few_events" in b_2ev["flags"]

    # 3 events
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (make_report([
        {"date": "2026-09-20", "event": "E1", "mechanism": "M1", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": "2026-09-19", "event": "E2", "mechanism": "M2", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": "2026-09-18", "event": "E3", "mechanism": "M3", "direction": "bull", "estimates_moved": "none", "source_url": ""},
    ]), "", {}))
    b_3ev = cr.run("T_3EV", force=True)
    assert "too_few_events" not in b_3ev["flags"]

    # Edge 2: mom_1m = 0.10 with newest event 46 days old vs 44 days old
    date_46 = (today - timedelta(days=46)).strftime("%Y-%m-%d")
    date_44 = (today - timedelta(days=44)).strftime("%Y-%m-%d")

    # 46 days old -> recent_move_unexplained
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.10, "facts": "facts"
    })
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (make_report([
        {"date": date_46, "event": "E1", "mechanism": "M1", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": date_46, "event": "E2", "mechanism": "M2", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": date_46, "event": "E3", "mechanism": "M3", "direction": "bull", "estimates_moved": "none", "source_url": ""},
    ]), "", {}))
    b_46d = cr.run("T_46D", force=True)
    assert "recent_move_unexplained" in b_46d["flags"]

    # 44 days old -> NOT recent_move_unexplained
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (make_report([
        {"date": date_44, "event": "E1", "mechanism": "M1", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": date_46, "event": "E2", "mechanism": "M2", "direction": "bull", "estimates_moved": "none", "source_url": ""},
        {"date": date_46, "event": "E3", "mechanism": "M3", "direction": "bull", "estimates_moved": "none", "source_url": ""},
    ]), "", {}))
    b_44d = cr.run("T_44D", force=True)
    assert "recent_move_unexplained" not in b_44d["flags"]


def test_render_under_3000_chars_and_keeps_all_events():
    """Render must stay <= 3,000 chars by truncating mechanism text first, and never drop events."""
    events = []
    for i in range(5):
        events.append({
            "date": f"2026-09-{10+i}",
            "direction": "bull" if i % 2 == 0 else "bear",
            "event": f"Major industry event {i}",
            "mechanism": "Very detailed mechanism explanation that takes up a lot of space " * 20,
            "estimates_moved": f"revisions up by {i*5}%",
            "source_url": f"https://news.reuters.com/article/{i}",
            "verified": True,
        })
    brief = {
        "asof": "2026-09-24",
        "pages_read": 5,
        "narrative": "A long narrative about market expectations " * 5,
        "bear_narrative": "A long bear narrative about cyclical risks " * 5,
        "events": events,
        "open_questions": ["Question 1", "Question 2"],
        "flags": ["flag_a", "flag_b"],
    }
    rendered = cr.render(brief)
    full_text = "\n".join(rendered)
    assert len(full_text) <= 3000

    # Ensure every single event is retained
    for i in range(5):
        assert f"Major industry event {i}" in full_text


def test_render_error():
    assert cr.render(None) == ["## CATALYST BRIEF   [not available — not available]"]
    assert cr.render({"error": "network failure"}) == ["## CATALYST BRIEF   [not available — network failure]"]


def test_pack_placement_and_build_pack_never_calls_run(monkeypatch, tmp_path):
    """CATALYST BRIEF placed right after RECENT COMPANY NEWS; build_pack never calls run()."""
    # 1. Live mode without cache
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path / "nonexistent")

    def run_should_never_be_called(*args, **kwargs):
        raise AssertionError("build_pack must NEVER call catalyst_research.run()")

    monkeypatch.setattr(cr, "run", run_should_never_be_called)

    pack_live_nocache = str(cap.build_pack("TEST", include_research=False))
    assert "## CATALYST BRIEF   [not available — no discovery run today]" in pack_live_nocache

    # Verify placement directly after RECENT COMPANY NEWS
    lines = pack_live_nocache.splitlines()
    news_idx = next(i for i, l in enumerate(lines) if "## RECENT COMPANY NEWS" in l)
    brief_idx = next(i for i, l in enumerate(lines) if "## CATALYST BRIEF" in l)
    sec3_idx = next(i for i, l in enumerate(lines) if "## SECTION 3" in l)
    assert news_idx < brief_idx < sec3_idx

    # 2. Point-in-time mode
    pack_pit = str(cap.build_pack("TEST", asof="2026-03-31"))
    assert "## CATALYST BRIEF   [not available (point-in-time) — the discovery run searches today's web]" in pack_pit
    lines_pit = pack_pit.splitlines()
    news_pit_idx = next(i for i, l in enumerate(lines_pit) if "## RECENT COMPANY NEWS" in l)
    brief_pit_idx = next(i for i, l in enumerate(lines_pit) if "## CATALYST BRIEF" in l)
    sec3_pit_idx = next(i for i, l in enumerate(lines_pit) if "## SECTION 3" in l)
    assert news_pit_idx < brief_pit_idx < sec3_pit_idx

    # 3. Live mode with cached brief
    cached_dir = tmp_path / "cache_brief"
    cached_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_file = cached_dir / f"TEST_{today}.json"
    sample_brief = {
        "ticker": "TEST",
        "asof": today,
        "pages_read": 3,
        "narrative": "Price betting on AI acceleration",
        "bear_narrative": "Valuation stretches margins",
        "events": [
            {"date": today, "event": "Chip breakthrough", "mechanism": "Boosts EPS", "direction": "bull",
             "estimates_moved": "+10%", "source_url": "https://reuters.com/chip", "verified": True}
        ],
        "open_questions": ["Will execution sustain?"],
        "flags": ["too_few_events"],
    }
    cache_file.write_text(json.dumps(sample_brief), encoding="utf-8")
    monkeypatch.setattr(cr, "CACHE_DIR", cached_dir)

    pack_cached = str(cap.build_pack("TEST", include_research=False))
    assert "- What the price is betting on: Price betting on AI acceleration" in pack_cached
    assert "Chip breakthrough — Boosts EPS" in pack_cached


def test_task_bullet_text_replaced():
    """Verify TASK bullet Explain The Recent Move First is replaced exactly."""
    expected_bullet = (
        "  * Explain The Recent Move First: start from the CATALYST BRIEF, RECENT COMPANY NEWS and "
        "SECTION 8's estimate trend and revisions. For each development say whether you accept or "
        "dispute it and why, and how it enters your Bull, Base and Bear numbers; add any development "
        "you find yourself and fetch the articles you rely on. Record them in `catalysts`."
    )
    assert expected_bullet in cap.TASK
