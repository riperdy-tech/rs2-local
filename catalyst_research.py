#!/usr/bin/env python3
"""catalyst_research.py — discovery run before valuation (Phase 4 Amendments Section E9).

A separate focused discovery pass by the analyst model with search/fetch tools only
(no financial model desk) to discover what happened in the last 90 days that investors
are reacting to and why it matters.

End-product: a cached CATALYST BRIEF embedded directly into the pack after RECENT COMPANY NEWS.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import rs2_data
import analyst_tools
import capability_test

CACHE_DIR = HERE / "cache" / "catalyst_brief"

PROMPT_TEMPLATE = """You are the news desk of an equity research team. Today is {asof}. Your job is DISCOVERY, not valuation: find out what has happened to {company} ({ticker}) and its industry in the last 90 days that investors are reacting to, and why it matters. Your own knowledge ends before today — everything recent must come from searching and reading.

FACTS FROM OUR DATA
{facts}

DO THIS
1. Explain the price action: why did the stock move the way it did over the last month and the last six months? Search for it (for example "why is {company} stock {up_down}" and the events in the headlines above) and open the articles you rely on. Reuters pages are often blocked to us — look for other coverage of the same story.
2. For each important development: what happened and when, the mechanism (how it changes revenue, earnings, margins or risk for {company} specifically), whether it is bullish or bearish, and whether analysts' estimates moved with it.
3. Say in 2-3 sentences what the current price is betting on, and in 1-2 sentences the strongest bear argument.
Do not value the company. Cite only pages you fetched in this run.

End with exactly one block:
```json:catalysts
{{"asof": "YYYY-MM-DD", "narrative": "<what the price is betting on>", "bear_narrative": "<strongest bear argument>", "events": [{{"date": "YYYY-MM-DD", "event": "<what happened>", "mechanism": "<how it changes revenue/earnings/margins/risk>", "direction": "bull|bear", "estimates_moved": "<how estimates moved, or 'no visible change'>", "source_url": "<a URL you fetched in this run>"}}], "open_questions": ["<...>"]}}
```"""


def normalize_url(url: str) -> str:
    """Normalize URL: scheme/host lowercase, trailing slash stripped."""
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(url.strip())
        scheme = p.scheme.lower()
        netloc = p.netloc.lower()
        path = p.path.rstrip("/")
        return urllib.parse.urlunparse((scheme, netloc, path, p.params, p.query, p.fragment))
    except Exception:
        return str(url).strip().rstrip("/")


def extract_domain(url: str) -> str:
    """Extract domain from URL, stripping leading www."""
    try:
        p = urllib.parse.urlparse(url or "")
        d = p.netloc.lower()
        if d.startswith("www."):
            d = d[4:]
        return d or "unknown"
    except Exception:
        return "unknown"


def _slice_section(pack_text: str, start_prefix: str, end_prefix: str = "## ") -> str | None:
    lines = pack_text.splitlines()
    start_idx = next((i for i, l in enumerate(lines) if l.startswith(start_prefix)), None)
    if start_idx is None:
        return None
    end_idx = next((i for i in range(start_idx + 1, len(lines)) if lines[i].startswith(end_prefix)), len(lines))
    chunk = lines[start_idx:end_idx]
    while chunk and not chunk[-1].strip():
        chunk.pop()
    return "\n".join(chunk) if chunk else None


def _slice_consensus_estimates(pack_text: str) -> str | None:
    lines = pack_text.splitlines()
    start_idx = next((i for i, l in enumerate(lines) if l.startswith("- CONSENSUS ESTIMATES")), None)
    if start_idx is None:
        return None
    if ": not available" in lines[start_idx]:
        return lines[start_idx].strip()
    res = [lines[start_idx]]
    for i in range(start_idx + 1, len(lines)):
        l = lines[i]
        if l.startswith("|") or l.startswith("- Next-FY EPS estimate trend:") or l.startswith("- Estimate revisions, last 30 days"):
            res.append(l)
        elif not l.strip():
            if any(r.startswith("- Estimate revisions") for r in res):
                break
        else:
            break
    while res and not res[-1].strip():
        res.pop()
    return "\n".join(res) if res else None


def _slice_guidance(pack_text: str) -> str | None:
    lines = pack_text.splitlines()
    start_idx = next((i for i, l in enumerate(lines) if l.startswith("## GUIDANCE & CONSENSUS")), None)
    if start_idx is None:
        return None
    chunk = lines[start_idx : min(start_idx + 3, len(lines))]
    return "\n".join(chunk)


def discovery_context(ticker: str) -> dict:
    """Build live pack with research off and slice out discovery facts."""
    t = str(ticker).upper()
    pack_text = str(capability_test.build_pack(t, include_research=False))

    sec25 = _slice_section(pack_text, "## SECTION 2.5") or "## SECTION 2.5 - PRICE ACTION\nnot available"
    news = _slice_section(pack_text, "## RECENT COMPANY NEWS") or "## RECENT COMPANY NEWS\nnot available"
    est = _slice_consensus_estimates(pack_text) or "- CONSENSUS ESTIMATES: not available"
    guidance = _slice_guidance(pack_text) or "## GUIDANCE & CONSENSUS\nnot available"

    company = rs2_data.resolve_name(t) or t
    sector, industry = rs2_data.sector_lookup(t)
    mom_state = getattr(capability_test, "LAST_PACK_MOMENTUM_STATE", {}) or {}
    mom_1m = mom_state.get("mom_1m")
    mom_6m = mom_state.get("mom_6m")
    asof = datetime.now().strftime("%Y-%m-%d")

    facts = f"{sec25}\n\n{news}\n\n{est}\n\n{guidance}".strip()

    return {
        "ticker": t,
        "company": company,
        "sector": sector,
        "industry": industry,
        "mom_1m": mom_1m,
        "mom_6m": mom_6m,
        "asof": asof,
        "section_2_5": sec25,
        "recent_news": news,
        "consensus_estimates": est,
        "guidance": guidance,
        "facts": facts,
    }


def get_cached_brief(ticker: str, asof: str = None) -> dict | None:
    """Load cached brief for ticker and date without running model."""
    t = str(ticker).upper()
    date_str = asof or datetime.now().strftime("%Y-%m-%d")
    cache_file = CACHE_DIR / f"{t}_{date_str}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def run(ticker: str, force: bool = False) -> dict:
    """Execute or load cached discovery run. Never raises."""
    t = str(ticker).upper()
    asof = datetime.now().strftime("%Y-%m-%d")
    cache_file = CACHE_DIR / f"{t}_{asof}.json"

    if not force and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    t0 = time.time()
    try:
        ctx = discovery_context(t)
    except Exception as e:
        res = {
            "ticker": t,
            "asof": asof,
            "model": rs2_data.CONFIG.get("depth_model", "rs2-analyst-deep-mtp5"),
            "narrative": None,
            "bear_narrative": None,
            "events": [],
            "open_questions": [],
            "flags": ["too_few_events"],
            "pages_read": 0,
            "search_calls": 0,
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"discovery context failed: {str(e)[:120]}",
        }
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
        except Exception:
            pass
        return res

    up_down = "up" if (ctx.get("mom_1m") is not None and ctx["mom_1m"] >= 0) else "down"
    prompt = PROMPT_TEMPLATE.format(
        asof=ctx["asof"],
        company=ctx["company"],
        ticker=ctx["ticker"],
        facts=ctx["facts"],
        up_down=up_down,
    )

    run_dir = CACHE_DIR / f"{t}_{ctx['asof']}_run"
    model = rs2_data.CONFIG.get("depth_model", "rs2-analyst-deep-mtp5")

    try:
        report, thinking, meta = analyst_tools.chat_with_tools(
            model=model,
            content=prompt,
            out_dir=run_dir,
            think="high",
            ctx=81920,
            num_predict=16384,
            tools=analyst_tools.research_tools(),
            max_search_calls=14,
            max_model_calls=0,
            timeout=1800,
        )
    except Exception as e:
        res = {
            "ticker": t,
            "asof": ctx["asof"],
            "model": model,
            "narrative": None,
            "bear_narrative": None,
            "events": [],
            "open_questions": [],
            "flags": ["too_few_events"],
            "pages_read": 0,
            "search_calls": 0,
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"model run failed: {str(e)[:120]}",
        }
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
        except Exception:
            pass
        return res

    # Read fetched URLs from run snapshot
    snap_path = run_dir / "_research_snapshot.json"
    fetched_urls = set()
    search_calls = 0
    if snap_path.exists():
        try:
            snap_data = json.loads(snap_path.read_text(encoding="utf-8"))
            for call in (snap_data.get("calls") or []):
                tool = call.get("tool")
                if tool == "search_web":
                    search_calls += 1
                elif tool == "fetch_page":
                    chars = call.get("chars") or 0
                    text = call.get("text") or ""
                    err = call.get("error") or call.get("refused")
                    u = call.get("url") or (call.get("params") or {}).get("url") or ""
                    if chars > 0 and text and not err and u:
                        fetched_urls.add(normalize_url(u))
        except Exception:
            pass

    # Parse catalysts block
    m = re.search(r"```json:catalysts\s*\n(.*?)```", report, re.DOTALL)
    if not m:
        m = re.search(r"```json\s*\n(.*?)```", report, re.DOTALL)

    parsed = None
    parse_error = None
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
        except Exception as e:
            parse_error = f"no parseable brief: {str(e)[:100]}"
    else:
        parse_error = "no parseable brief"

    narrative = None
    bear_narrative = None
    events = []
    open_questions = []

    if isinstance(parsed, dict):
        narrative = parsed.get("narrative")
        bear_narrative = parsed.get("bear_narrative")
        events = parsed.get("events") if isinstance(parsed.get("events"), list) else []
        open_questions = parsed.get("open_questions") if isinstance(parsed.get("open_questions"), list) else []

    # Validate each event's source_url
    unverified_count = 0
    for e in events:
        if isinstance(e, dict):
            src = e.get("source_url") or ""
            is_v = bool(src and normalize_url(src) in fetched_urls)
            e["verified"] = is_v
            if not is_v:
                unverified_count += 1

    flags = []
    if len(events) < 3:
        flags.append("too_few_events")

    mom_1m = ctx.get("mom_1m")
    if mom_1m is not None and abs(mom_1m) >= 0.10:
        has_recent = False
        try:
            asof_d = datetime.strptime(str(ctx["asof"])[:10], "%Y-%m-%d").date()
        except Exception:
            asof_d = datetime.now().date()
        for e in events:
            if isinstance(e, dict) and e.get("date"):
                try:
                    ed = datetime.strptime(str(e["date"])[:10], "%Y-%m-%d").date()
                    days = (asof_d - ed).days
                    if 0 <= days <= 45:
                        has_recent = True
                        break
                except Exception:
                    pass
        if not has_recent:
            flags.append("recent_move_unexplained")

    if unverified_count > 0:
        flags.append(f"unverified_events:{unverified_count}")

    res = {
        "ticker": t,
        "asof": ctx["asof"],
        "model": model,
        "narrative": narrative,
        "bear_narrative": bear_narrative,
        "events": events,
        "open_questions": open_questions,
        "flags": flags,
        "pages_read": len(fetched_urls),
        "search_calls": search_calls or meta.get("tool_calls", 0),
        "elapsed_s": round(time.time() - t0, 1),
        "error": parse_error,
    }

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
    except Exception:
        pass

    return res


_run_live = run


# Rendered brief cap. E9 first said 3,000 characters, set before any real brief existed. The first
# real one (AMD, 2026-09-24) rendered 5,400 characters, 4,300 of them outside the mechanisms, so
# 3,000 could only be met by cutting the mechanisms to nothing - and the mechanism is the reason the
# brief exists (AMD's Muse -> EPYC CPU link sits in one). 5,000 characters is about 1,300 tokens
# in a ~30k-character pack and a 49k-token window.
BRIEF_CAP = 5000

# What gets cut when a brief is over the cap, least useful to the valuation first. Each tier
# shortens the longest texts in its group, never below the group's floor. The last tier is a
# safety net for pathological briefs (many events, very long fields).
_CUT_ORDER = (
    (("open_questions",), 60),
    (("narrative", "bear_narrative"), 250),
    (("event", "estimates_moved"), 80),
    (("mechanism",), 150),
    (("open_questions", "narrative", "bear_narrative", "event", "estimates_moved", "mechanism"), 20),
)


def _fit(texts: list[str], budget: int, floor: int) -> list[str]:
    """Shorten the longest texts first so the total fits `budget`, none below `floor` characters.

    The cut level is found by bisection over a bounded range, so this always terminates. (The
    trim loop it replaces re-appended "..." to what it cut, stopped shrinking at ~18 characters
    and spun forever on AMD's brief.) Returns the texts unchanged when they already fit; when
    even `floor` does not fit, every text is cut to `floor`.
    """
    if not texts or sum(len(t) for t in texts) <= budget:
        return list(texts)
    lo, hi = floor, max(len(t) for t in texts)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sum(min(len(t), mid) for t in texts) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return [t if len(t) <= lo else t[:max(lo - 1, 0)].rstrip() + "…" for t in texts]


def render(brief: dict | None) -> list[str]:
    """Render the catalyst brief as pack lines, at most BRIEF_CAP characters, every event kept.

    Over the cap, text is cut in _CUT_ORDER: open questions first, mechanisms last.
    """
    if not brief or brief.get("error"):
        reason = brief.get("error") if brief and brief.get("error") else "not available"
        return [f"## CATALYST BRIEF   [not available — {reason}]"]

    asof = str(brief.get("asof") or "unknown")[:10]
    pages_read = brief.get("pages_read", 0)
    flags = brief.get("flags") or []

    hdr = f"## CATALYST BRIEF   [discovery run by the analyst model on {asof}; {pages_read} pages read; claims from third-party sources, not verified facts — events marked (unverified) cite no page the run read]"
    flags_line = f"- Flags: {', '.join(str(f) for f in flags)}" if flags else None

    # Fixed-width parts of each event line are bounded here so only the cuttable texts can grow.
    skel = []
    texts = {"narrative": [str(brief.get("narrative") or "")],
             "bear_narrative": [str(brief.get("bear_narrative") or "")],
             "event": [], "mechanism": [], "estimates_moved": [],
             "open_questions": [str(q) for q in (brief.get("open_questions") or [])]}
    for e in brief.get("events") or []:
        if not isinstance(e, dict):
            continue
        skel.append({"date": str(e.get("date") or "undated")[:10],
                     "direction": str(e.get("direction") or "unknown")[:8],
                     "domain": extract_domain(e.get("source_url") or "")[:40],
                     "unverified": "" if e.get("verified") else " (unverified)"})
        texts["event"].append(str(e.get("event") or ""))
        texts["mechanism"].append(str(e.get("mechanism") or ""))
        texts["estimates_moved"].append(str(e.get("estimates_moved") or "no visible change"))

    def _assemble(tx):
        lines = [hdr,
                 f"- What the price is betting on: {tx['narrative'][0]}",
                 f"- Strongest bear argument: {tx['bear_narrative'][0]}"]
        for i, s in enumerate(skel):
            lines.append(f"- {s['date']} | {s['direction']} | {tx['event'][i]} — {tx['mechanism'][i]} "
                         f"(estimates: {tx['estimates_moved'][i]}) [{s['domain']}]{s['unverified']}")
        lines.append(f"- Open questions: {'; '.join(tx['open_questions']) or 'none'}")
        if flags_line:
            lines.append(flags_line)
        return lines

    lines = _assemble(texts)
    for keys, floor in _CUT_ORDER:
        excess = len("\n".join(lines)) - BRIEF_CAP
        if excess <= 0:
            break
        group = [t for k in keys for t in texts[k]]
        fitted = _fit(group, sum(len(t) for t in group) - excess, floor)
        for k in keys:
            n = len(texts[k])
            texts[k], fitted = fitted[:n], fitted[n:]
        lines = _assemble(texts)
    return lines


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Catalyst research discovery run")
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument("--force", action="store_true", help="Force new run, ignoring cache")
    args = parser.parse_args()

    t = args.ticker.upper()
    brief = run(t, force=args.force)
    rendered = render(brief)
    print("\n".join(rendered))
    cache_path = CACHE_DIR / f"{t}_{brief.get('asof', datetime.now().strftime('%Y-%m-%d'))}.json"
    print(f"\nCache: {cache_path}")
