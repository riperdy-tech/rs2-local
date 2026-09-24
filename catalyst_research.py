#!/usr/bin/env python3
"""catalyst_research.py — discovery run before valuation (Phase 4 Amendments Section E9).

A separate focused discovery pass by the analyst model with search/fetch tools only
(no financial model desk) to discover what happened in the last 90 days that investors
are reacting to and why it matters.

End-product: a cached CATALYST BRIEF embedded directly into the pack after RECENT COMPANY NEWS.
"""
import argparse
from datetime import datetime, timedelta, timezone
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


def _open_containers(s: str, end: int) -> list:
    """The JSON objects/arrays still open at s[:end], outermost first (strings are skipped)."""
    stack, in_str, esc = [], False, False
    for c in s[:end]:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            stack.append(c)
        elif c in "}]" and stack:
            stack.pop()
    return stack


def _llm_fix_json(model: str, block: str, err: str) -> str:
    """Last resort for a brief the deterministic repairs cannot parse: the model re-emits the same
    content as valid JSON, thinking off. It sees only the broken block and the parser's error."""
    body = {"model": model, "stream": False, "think": False,
            "options": {"num_ctx": 32768, "num_predict": 12288, "temperature": 0},
            "messages": [{"role": "user", "content": (
                "The JSON below does not parse (" + err + "). Return the same content as valid JSON: "
                "fix only the syntax (brackets, commas, quotes inside strings - escape them), change no "
                "wording, add or drop nothing. Output only the JSON.\n\n" + block)}]}
    req = analyst_tools.urllib.request.Request(analyst_tools.OLLAMA, data=json.dumps(body).encode(),
                                               headers={"Content-Type": "application/json"})
    with analyst_tools.urllib.request.urlopen(req, timeout=900) as r:
        out = (json.loads(r.read().decode()).get("message") or {}).get("content") or ""
    m = re.search(r"```(?:json[^\n]*)?\s*\n(.*?)```", out, re.DOTALL)
    return (m.group(1) if m else out).strip()


def _loads_lenient(text: str):
    """json.loads, then bounded repairs for the ways the model breaks its own JSON.

    DXC 2026-09-24 lost its whole brief to "Expecting ',' delimiter" at character 4240, the
    usual sign of an unescaped double quote inside a string; GEV's closed a list with the
    wrong bracket. The repairs cover control characters inside strings, trailing commas, a
    stray or wrong closing bracket, a block cut off mid-way, a missing comma between two
    values, and an unescaped quote (escape the last quote before the error, then retry).
    Returns (obj, repaired). Raises the original error when at most 40 repairs do not give
    valid JSON.
    """
    try:
        return json.loads(text), False
    except json.JSONDecodeError as e:
        first = e
    s = re.sub(r",\s*([}\]])", r"\1", text)
    for _ in range(40):
        try:
            return json.loads(s, strict=False), True
        except json.JSONDecodeError as e:
            pos = e.pos
            stack = _open_containers(s, pos)
            ch = s[pos] if pos < len(s) else ""
            if ch in "}]" and stack:
                want = "]" if stack[-1] == "[" else "}"
                if ch != want:
                    # GEV 2026-09-24 closed its list with `"}]` for `"]}`: a stray closer is dropped,
                    # a container left open is closed.
                    s = s[:pos] + s[pos + 1:] if s[pos + 1:].lstrip()[:1] == want else s[:pos] + want + s[pos:]
                    continue
            if e.msg.startswith("Unterminated string") and not s[pos:].rstrip().endswith('"'):
                s = s.rstrip() + '"'                  # cut off inside a string
                continue
            if stack and not s[pos:].strip():
                # Cut off mid-block: close whatever is still open.
                s = s.rstrip() + "".join("]" if c == "[" else "}" for c in reversed(stack))
                continue
            if not e.msg.startswith(("Expecting ',' delimiter", "Expecting ':' delimiter")):
                break
            j = pos - 1
            while j >= 0 and s[j].isspace():
                j -= 1
            if (e.msg.startswith("Expecting ','") and j >= 0 and s[j] in '}]"'
                    and pos < len(s) and s[pos] in '{["'):
                s = s[:j + 1] + "," + s[j + 1:]        # two values with no comma between
                continue
            q = s.rfind('"', 0, pos)
            while q > 0 and s[q - 1] == "\\":
                q = s.rfind('"', 0, q - 1)
            if q <= 0:
                break
            s = s[:q] + "\\" + s[q:]                   # a quote that ended a string too early
    raise first


def get_cached_brief(ticker: str, asof: str = None) -> dict | None:
    """Load the cached brief for ticker and date without running the model.

    With no `asof`: today's brief, else yesterday's if it was written in the last 6 hours. The
    pack is built in a separate process after the discovery run, so without the fallback a run
    whose discovery ends just before midnight would build its pack without the brief.
    """
    t = str(ticker).upper()
    if asof:
        candidates = [CACHE_DIR / f"{t}_{asof}.json"]
    else:
        now = datetime.now()
        candidates = [CACHE_DIR / f"{t}_{now.strftime('%Y-%m-%d')}.json"]
        prev = CACHE_DIR / f"{t}_{(now - timedelta(days=1)).strftime('%Y-%m-%d')}.json"
        try:
            if time.time() - prev.stat().st_mtime < 6 * 3600:
                candidates.append(prev)
        except OSError:
            pass
    for cache_file in candidates:
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
            # The final turn thinks before it writes: 10,184 (AMD) and 12,952 (GEV) tokens on
            # 2026-09-24, and MU used all of the old 16,384 without writing the brief. A ~17k
            # prompt plus 32,768 still fits the 81,920 window.
            num_predict=32768,
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

    # Keep the model's final text: without it a "no parseable brief" cannot be diagnosed.
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "_report.md").write_text(report or "", encoding="utf-8")
        (run_dir / "_thinking.md").write_text(thinking or "", encoding="utf-8")
    except Exception:
        pass
    turns = meta.get("turns") or []
    final_turn = {"done_reason": meta.get("done_reason"),
                  "length_recovery": any(tu.get("length_recovery") for tu in turns),
                  "json_repaired": False}

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
                        for asked in (call.get("corrected_from"), call.get("alternate_for")):
                            if asked:   # the model may cite the address it asked for
                                fetched_urls.add(normalize_url(asked))
        except Exception:
            pass

    # Parse catalysts block
    m = re.search(r"```json:catalysts\s*\n(.*?)```", report, re.DOTALL)
    if not m:
        m = re.search(r"```json\s*\n(.*?)```", report, re.DOTALL)

    parsed = None
    parse_error = None
    if m:
        block = m.group(1).strip()
        try:
            parsed, final_turn["json_repaired"] = _loads_lenient(block)
        except Exception as e:
            parse_error = f"no parseable brief: {str(e)[:100]}"
            try:
                fixed, _ = _loads_lenient(_llm_fix_json(model, block, str(e)[:200]))
                # Accept only a syntax fix: every event the fix returns must be in the original text.
                evs = fixed.get("events") if isinstance(fixed, dict) else None
                if isinstance(evs, list) and all(
                        isinstance(ev, dict) and str(ev.get("event") or "")[:30] in block for ev in evs):
                    parsed, parse_error = fixed, None
                    final_turn["json_llm_fixed"] = True
            except Exception:
                pass
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
        "final_turn": final_turn,
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
# next to a 55-65k-character pack in the analyst's 81,920-token window.
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
