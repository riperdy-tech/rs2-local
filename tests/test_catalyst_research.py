"""tests/test_catalyst_research.py — tests for discovery run, catalyst brief, slicing, and pack integration."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
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

    monkeypatch.setattr(cr, "run", cr._run_live)
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
    monkeypatch.setattr(cr, "run", cr._run_live)
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
    monkeypatch.setattr(cr, "run", cr._run_live)
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


def _render_with_deadline(brief, seconds=10):
    """render() in a daemon thread, so a regression to an endless loop fails instead of hanging."""
    import threading
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("lines", cr.render(brief)), daemon=True)
    th.start()
    th.join(seconds)
    assert not th.is_alive(), f"render() did not finish within {seconds}s"
    return out["lines"]


def test_render_fits_cap_and_keeps_all_events():
    """Over-long mechanisms are cut to fit BRIEF_CAP and no event is dropped."""
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
    rendered = _render_with_deadline(brief)
    full_text = "\n".join(rendered)
    assert len(full_text) <= cr.BRIEF_CAP

    # Ensure every single event is retained
    for i in range(5):
        assert f"Major industry event {i}" in full_text


def _amd_shaped_brief():
    """Field sizes of the first real brief (AMD, 2026-09-24): the old renderer never returned on it."""
    events = []
    for i, (ev_len, mech_len) in enumerate([(275, 233), (452, 246), (216, 310), (235, 269)]):
        events.append({
            "date": f"2026-0{7 + i // 2}-1{i}",
            "direction": "bear" if i == 3 else "bull",
            "event": (f"EVENT{i} " + "e" * ev_len)[:ev_len],
            "mechanism": (f"MECH{i}-START " + "m" * mech_len)[:mech_len - 8] + f" END{i}ME",
            "estimates_moved": "estimates rose about 18% over 90 days, 33 up and 3 down revisions " + "x" * 40,
            "source_url": f"https://www.example{i}.com/news/article-{i}",
            "verified": True,
        })
    return {
        "asof": "2026-09-24", "pages_read": 4,
        "narrative": "N" * 679, "bear_narrative": "B" * 405, "events": events,
        "open_questions": [f"OQ{i} " + "q" * n for i, n in enumerate([258, 185, 206, 206, 153, 224])],
        "flags": [],
    }


def test_render_amd_shaped_brief_returns_and_cuts_open_questions_before_mechanisms():
    """Regression: the AMD brief hung the old renderer. Now it fits, with every mechanism whole."""
    brief = _amd_shaped_brief()
    full_text = "\n".join(_render_with_deadline(brief))
    assert len(full_text) <= cr.BRIEF_CAP
    for e in brief["events"]:
        assert e["mechanism"] in full_text          # mechanisms untouched
    assert "N" * 679 in full_text and "B" * 405 in full_text   # narrative and bear untouched
    oq_line = next(l for l in full_text.splitlines() if l.startswith("- Open questions:"))
    assert "…" in oq_line                           # the open questions took the cut
    for i in range(6):
        assert f"OQ{i}" in oq_line                  # but each question is still named


def test_render_pathological_brief_fits_and_keeps_every_event():
    """Twelve events with huge fields: the cut reaches every tier and still keeps all events."""
    events = [{"date": f"2026-09-{i + 10}", "direction": "bull", "event": f"EV{i:02d} " + "e" * 2000,
               "mechanism": f"MC{i:02d} " + "m" * 2000, "estimates_moved": "s" * 2000,
               "source_url": f"https://site{i}.com/a", "verified": i % 2 == 0} for i in range(12)]
    brief = {"asof": "2026-09-24", "pages_read": 12, "narrative": "n" * 5000, "bear_narrative": "b" * 5000,
             "events": events, "open_questions": ["q" * 3000] * 5, "flags": ["recent_move_unexplained"]}
    full_text = "\n".join(_render_with_deadline(brief))
    assert len(full_text) <= cr.BRIEF_CAP
    for i in range(12):
        assert f"EV{i:02d}" in full_text and f"MC{i:02d}" in full_text
    assert "(unverified)" in full_text and "- Flags: recent_move_unexplained" in full_text


def test_render_short_brief_is_untouched():
    brief = _amd_shaped_brief()
    brief["open_questions"] = ["Is the Q3 guide conservative?"]
    brief["narrative"], brief["bear_narrative"] = "Short bull.", "Short bear."
    full_text = "\n".join(cr.render(brief))
    assert "…" not in full_text
    assert "- Open questions: Is the Q3 guide conservative?" in full_text
    assert "- Open questions: none" in "\n".join(cr.render(dict(brief, open_questions=[])))


def test_fit_cuts_longest_first_and_respects_budget_and_floor():
    texts = ["a" * 100, "b" * 40, "c" * 10]
    out = cr._fit(texts, 90, 5)
    assert sum(len(t) for t in out) <= 90
    assert out[2] == "c" * 10                        # short text below the cut level untouched
    assert out[0].endswith("…") and len(out[0]) <= 40
    assert cr._fit(texts, 1000, 5) == texts          # already fits: unchanged
    floor_only = cr._fit(texts, 3, 20)               # budget impossible: everything at the floor
    assert [len(t) for t in floor_only] == [20, 20, 10]


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
    """Verify TASK bullet Explain The Recent Move First is replaced exactly.
    # S3 A+B (brief §4.2): the old "Explain The Recent Move First" bullet is now checklist item 1;
    # same doctrine (start from CATALYST BRIEF/RECENT COMPANY NEWS/SECTION 8, accept-or-dispute each
    # development, record in `catalysts`), new sentence."""
    expected_bullet = (
        "1. Explain the recent move first. Start from the CATALYST BRIEF, RECENT COMPANY NEWS and "
        "SECTION 8's estimate trend and revisions. For each development, say whether you accept or "
        "dispute it and why, and how it enters Bull, Base and Bear. Add any development you find "
        "yourself, and fetch the articles you rely on. Record them in `catalysts`."
    )
    assert expected_bullet in cap.TASK


def test_depth_pipeline_wires_discovery(tmp_path, monkeypatch):
    """depth_pipeline calls catalyst_research.run before consensus and survives failure with flag;
    --no-discovery skips it."""
    import depth_pipeline as dp

    order = []
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path / "research"))
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))
    monkeypatch.setattr(dp.price_now, "quote", lambda t: {"price": 100.0, "asof": "2026-09-24", "source": "yfinance"})
    monkeypatch.setattr(dp, "run_research", lambda t: (order.append("research"), True)[1])
    monkeypatch.setattr(dp, "audit_verdict", lambda t, ledger: None)
    monkeypatch.setattr(dp.ops, "notify_telegram", lambda msg: None)
    monkeypatch.setattr(dp, "LEDGER", tmp_path / "depth_ledger.jsonl")
    monkeypatch.setattr(dp, "TEST_LEDGER", tmp_path / "depth_test_ledger.jsonl")
    monkeypatch.setattr(dp, "OD_LEDGER", tmp_path / "depth_ondemand_ledger.jsonl")

    consensus_dir = tmp_path / "TEST_20260924_120000"
    consensus_dir.mkdir(exist_ok=True)
    doc = {
        "ticker": "TEST",
        "price": 100.0,
        "runs": [{"iv": 120.0, "plausible": True, "truncated": False, "flags": []}],
        "median_iv": 120.0,
        "spread_pct": 5.0,
    }
    monkeypatch.setattr(dp, "run_consensus", lambda *a, **k: (order.append("consensus"), (consensus_dir, doc))[1])

    # Case 1: discovery fails with error -> recorded on verdict as discovery_failed:<reason> and never stops run
    order.clear()
    monkeypatch.setattr(cr, "run", lambda t: (order.append("discovery"), {"ticker": t, "error": "simulated discovery timeout"})[1])
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "TEST"])
    dp.main()

    assert order == ["research", "discovery", "consensus"]
    v_path = consensus_dir / "verdict_depth.json"
    assert v_path.exists()
    v1 = json.loads(v_path.read_text(encoding="utf-8"))
    assert "discovery_failed:simulated discovery timeout" in v1.get("flags", [])

    # Case 2: discovery raises an exception -> recorded on verdict and never stops run
    order.clear()
    def failing_run(t):
        order.append("discovery")
        raise RuntimeError("unexpected network crash")
    monkeypatch.setattr(cr, "run", failing_run)
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "TEST"])
    dp.main()

    assert order == ["research", "discovery", "consensus"]
    v2 = json.loads(v_path.read_text(encoding="utf-8"))
    assert any("discovery_failed:unexpected network crash" in f for f in v2.get("flags", []))

    # Case 3: --no-discovery skips discovery call
    order.clear()
    monkeypatch.setattr(cr, "run", lambda t: order.append("discovery_should_not_run"))
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "TEST", "--no-discovery"])
    dp.main()

    assert order == ["research", "consensus"]
    v3 = json.loads(v_path.read_text(encoding="utf-8"))
    assert not any("discovery_failed" in f for f in v3.get("flags", []))


def test_dispersion_battery_wires_discovery(tmp_path, monkeypatch, capsys):
    """tools/dispersion_battery calls run before building pack, skips on --dry-run / --no-discovery."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import dispersion_battery as db

    order = []
    monkeypatch.setattr(cr, "run", lambda name: order.append(("discovery", name)))
    monkeypatch.setattr(db, "build_frozen_pack", lambda name, path: (order.append(("pack", name)), ("pack content", False))[1])
    monkeypatch.setattr(db, "_existing_complete_run", lambda *a, **k: {"samples_run": 1})

    class MockArgs:
        def __init__(self, arm="A", samples=1, dry_run=False, no_discovery=False):
            self.arm = arm
            self.samples = samples
            self.dry_run = dry_run
            self.no_discovery = no_discovery
            self.temperature = None
            self.model = None
            self.ctx = 81920
            self.failfast_street = False

    # 1. Normal run: calls discovery before pack
    order.clear()
    db.run_name("GEV", MockArgs(dry_run=False, no_discovery=False), tmp_path)
    assert order == [("discovery", "GEV"), ("pack", "GEV")]

    # 2. --dry-run: skips discovery run and prints "would run discovery for <name>"
    order.clear()
    capsys.readouterr()
    res_dry = db.run_name("GEV", MockArgs(dry_run=True, no_discovery=False), tmp_path)
    assert order == [("pack", "GEV")]
    out = capsys.readouterr().out
    assert "would run discovery for GEV" in out
    assert res_dry.get("dry_run") is True

    # 3. --no-discovery: skips discovery run and does not print "would run discovery for"
    order.clear()
    capsys.readouterr()
    db.run_name("GEV", MockArgs(dry_run=False, no_discovery=True), tmp_path)
    assert order == [("pack", "GEV")]
    out = capsys.readouterr().out
    assert "would run discovery for" not in out



def test_get_cached_brief_uses_a_fresh_brief_from_just_before_midnight(monkeypatch, tmp_path):
    """The pack is built in another process after the discovery run. A brief written at 23:59
    must still be found at 00:01, but a stale one from yesterday must not be."""
    import os
    import time as _time
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    prev = tmp_path / f"ABC_{yesterday}.json"
    prev.write_text(json.dumps({"asof": yesterday, "narrative": "late run"}), encoding="utf-8")
    assert cr.get_cached_brief("abc")["narrative"] == "late run"          # written just now

    old = _time.time() - 7 * 3600
    os.utime(prev, (old, old))
    assert cr.get_cached_brief("ABC") is None                             # 7 hours old: stale

    (tmp_path / f"ABC_{today}.json").write_text(json.dumps({"asof": today, "narrative": "today"}),
                                                encoding="utf-8")
    assert cr.get_cached_brief("ABC")["narrative"] == "today"             # today's always wins
    assert cr.get_cached_brief("ABC", asof=yesterday)["narrative"] == "late run"   # explicit date
    assert cr.get_cached_brief("ABC", asof="2020-01-01") is None


def test_run_saves_final_text_and_final_turn(monkeypatch, tmp_path):
    """The model's final text is kept next to the snapshot, and the brief says how the final turn
    ended - MU's lost run (2026-09-24) left nothing to diagnose it from."""
    report = 'Findings.\n```json:catalysts\n{"asof": "2026-09-24", "narrative": "n", "bear_narrative": "b", "events": []}\n```'
    monkeypatch.setattr(cr, "run", cr._run_live)
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.01, "facts": "facts"})
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (
        report, "the thinking", {"tool_calls": 3, "done_reason": "stop",
                                 "turns": [{"turn": 1}, {"turn": 2, "length_recovery": True}]}))
    b = cr.run("T9", force=True)
    run_dir = tmp_path / "T9_2026-09-24_run"
    assert (run_dir / "_report.md").read_text(encoding="utf-8") == report
    assert (run_dir / "_thinking.md").read_text(encoding="utf-8") == "the thinking"
    assert b["final_turn"] == {"done_reason": "stop", "length_recovery": True, "json_repaired": False}


def test_loads_lenient_repairs_what_the_model_breaks():
    """DXC 2026-09-24: one unescaped quote ("Expecting ',' delimiter" at char 4240) lost the brief."""
    assert cr._loads_lenient('{"a": 1}') == ({"a": 1}, False)
    obj, rep = cr._loads_lenient('{"event": "DXC\'s "AI-first" plan fell flat", "n": 1}')
    assert rep and obj == {"event": 'DXC\'s "AI-first" plan fell flat', "n": 1}
    obj, rep = cr._loads_lenient('{"events": [{"a": 1} {"b": 2}], "x": "y" "z": 3}')
    assert rep and obj == {"events": [{"a": 1}, {"b": 2}], "x": "y", "z": 3}
    obj, rep = cr._loads_lenient('{"events": [1, 2,], "q": ["a",],}')
    assert rep and obj == {"events": [1, 2], "q": ["a"]}
    obj, rep = cr._loads_lenient('{"a": "line1\nline2"}')
    assert rep and obj == {"a": "line1\nline2"}
    with pytest.raises(json.JSONDecodeError):
        cr._loads_lenient("not json at all")
    with pytest.raises(json.JSONDecodeError):               # bounded: gives up, never spins
        cr._loads_lenient('{"a": "' + '" x ' * 200 + '"')


def test_run_repairs_an_unescaped_quote_in_the_brief(monkeypatch, tmp_path):
    report = ('```json:catalysts\n{"asof": "2026-09-24", "narrative": "The "AI-first" pivot", '
              '"bear_narrative": "b", "events": [{"date": "2026-09-01", "event": "Guide cut", '
              '"mechanism": "m", "direction": "bear", "estimates_moved": "down", "source_url": ""}]}\n```')
    monkeypatch.setattr(cr, "run", cr._run_live)
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.01, "facts": "facts"})
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (report, "", {"tool_calls": 1}))
    b = cr.run("T8", force=True)
    assert b["error"] is None and b["narrative"] == 'The "AI-first" pivot' and len(b["events"]) == 1
    assert b["final_turn"]["json_repaired"] is True


def test_a_corrected_fetch_verifies_the_address_the_model_cites(monkeypatch, tmp_path):
    """fetch_page may open the search's address for a garbled one; an event citing either counts."""
    good = "https://www.fool.com/investing/2026/09/14/why-did-ge-vernova-stock-fall-today/"
    bad = "https://www.fool.com/investing/2026-09-14/why-did-ge-vernova-stock-fall-today/"
    ev = [{"date": "2026-09-14", "event": f"E{i}", "mechanism": "m", "direction": "bear",
           "estimates_moved": "none", "source_url": bad} for i in range(3)]
    block = json.dumps({"asof": "2026-09-24", "narrative": "n", "bear_narrative": "b", "events": ev})
    report = "```json:catalysts" + chr(10) + block + chr(10) + "```"

    def fake_chat(*a, **k):
        out_dir = k.get("out_dir"); out_dir.mkdir(parents=True, exist_ok=True)
        snap = {"calls": [{"tool": "fetch_page", "url": good, "corrected_from": bad, "chars": 50,
                           "text": "GE Vernova fell"}]}
        (out_dir / "_research_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
        return report, "", {"tool_calls": 1}

    monkeypatch.setattr(cr, "run", cr._run_live)
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.01, "facts": "facts"})
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", fake_chat)
    b = cr.run("T7", force=True)
    assert all(e["verified"] for e in b["events"]) and "unverified_events:3" not in b["flags"]


def test_loads_lenient_brackets_and_cut_off_blocks():
    """GEV 2026-09-24 closed its open_questions list with a wrong bracket: `"}]` for `"]}`."""
    obj, rep = cr._loads_lenient('{"a": 1, "open_questions": ["x", "y?"}]' + chr(10) + '}')
    assert rep and obj == {"a": 1, "open_questions": ["x", "y?"]}
    obj, rep = cr._loads_lenient('{"events": [{"a": 1}')                      # cut off
    assert rep and obj == {"events": [{"a": 1}]}
    obj, rep = cr._loads_lenient('{"narrative": "abc')                           # cut off in a string
    assert rep and obj == {"narrative": "abc"}
    obj, rep = cr._loads_lenient('{"q": ["a" }')                                 # list left open
    assert rep and obj == {"q": ["a"]}


def _run_with_block(monkeypatch, tmp_path, block, llm_fix):
    report = "```json:catalysts" + chr(10) + block + chr(10) + "```"
    monkeypatch.setattr(cr, "run", cr._run_live)
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.01, "facts": "facts"})
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools", lambda *a, **k: (report, "", {"tool_calls": 1}))
    monkeypatch.setattr(cr, "_llm_fix_json", llm_fix)
    return cr.run("T6", force=True)


def test_run_asks_the_model_to_fix_json_the_repairs_cannot(monkeypatch, tmp_path):
    broken = '{narrative: "n", "events": [{"event": "Guidance raised", "date": "2026-09-01"}]}'
    good = '{"narrative": "n", "events": [{"event": "Guidance raised", "date": "2026-09-01"}]}'
    b = _run_with_block(monkeypatch, tmp_path, broken, lambda model, block, err: good)
    assert b["error"] is None and b["events"][0]["event"] == "Guidance raised"
    assert b["final_turn"]["json_llm_fixed"] is True


def test_a_json_fix_that_invents_an_event_is_refused(monkeypatch, tmp_path):
    broken = '{narrative: "n", "events": [{"event": "Guidance raised", "date": "2026-09-01"}]}'
    invented = '{"narrative": "n", "events": [{"event": "Takeover bid at a 40% premium", "date": "2026-09-02"}]}'
    b = _run_with_block(monkeypatch, tmp_path, broken, lambda model, block, err: invented)
    assert b["error"].startswith("no parseable brief") and b["events"] == []


def test_news_step_passes_failure_name_on(monkeypatch, tmp_path):
    report = "no json block in this response at all"
    monkeypatch.setattr(cr, "run", cr._run_live)
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.01, "facts": "facts"})
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools",
                        lambda *a, **k: (report, "", {"tool_calls": 0, "failure": "brief_not_delivered"}))
    b = cr.run("T9", force=True)
    assert b["error"] == "brief_not_delivered"


def test_news_step_passes_failure_name_on_json_syntax_error(monkeypatch, tmp_path):
    report = "```json:catalysts\n{unparseable json\n```"
    monkeypatch.setattr(cr, "run", cr._run_live)
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cr, "discovery_context", lambda t: {
        "ticker": t, "company": t, "asof": "2026-09-24", "mom_1m": 0.01, "facts": "facts"})
    monkeypatch.setattr(cr.analyst_tools, "chat_with_tools",
                        lambda *a, **k: (report, "", {"tool_calls": 0, "failure": "brief_not_delivered"}))
    b = cr.run("T10", force=True)
    assert b["error"] == "brief_not_delivered"
