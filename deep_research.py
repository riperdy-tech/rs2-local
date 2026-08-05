#!/usr/bin/env python3
"""
deep_research.py — analyst-grade per-ticker web research (replaces snippet-only research_agent).

Runs LearningCircuit's Local Deep Research (LDR) headless: for each RS2-aligned topic it
generates sub-questions, searches, READS FULL PAGES (snippets_only=False), reflects on gaps,
re-queries, and synthesizes a CITED summary. Engine = Tavily (primary, quota-guarded) ->
SearXNG (local, unlimited fallback). Runs on a CLEAN model (config research_model), never
rs2-analyst (whose baked RS2 prompt would derail LDR).

MUST run with the research-venv python (has local_deep_research). Output: research/{T}.md
(source-cited, deep), cached for research_cache_days.

CLI:  <research-venv-python> deep_research.py NVDA "NVIDIA Corporation"
"""
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import ops    # local (stdlib): telegram + infra-error signatures
import quota  # local (stdlib)

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# RS2-aligned research topics (LDR expands each into sub-questions + iterates)
TOPICS = [
    ("Competitive Position & Moat",
     "{subj} competitive position, market share, moat durability and threats from rivals in {yr}"),
    ("Catalysts & Guidance",
     "{subj} latest earnings results, management guidance, growth catalysts and outlook for {yr}"),
    ("Bear Case / Short Thesis / Regulatory",
     "{subj} bear case, key risks, short-seller or activist concerns, and regulatory/legal exposure {yr}"),
    ("Industry Demand & End-Markets",
     "{subj} end-market demand trends, industry growth drivers and headwinds {yr}"),
]


class ResearchInfraError(RuntimeError):
    """LLM/search infrastructure failed (ollama 500, CUDA OOM, engine unreachable).
    Distinct from 'the web had nothing to say', which is a legitimate thin result."""


def ldr_overrides(tool):
    o = {
        "llm.provider": "ollama",
        "llm.model": CONFIG["research_model"],
        "llm.ollama.url": CONFIG["ollama_endpoint"].replace("/api/chat", ""),
        "llm.ollama.enable_thinking": False,            # faster across LDR's many calls
        # Pin LDR's ollama context to the research model's cap. Research = search +
        # summarize pages; it does NOT need rs2-analyst's 24k. 8192 = 100% GPU / 0 spill
        # on this 12GB-RAM / 24GB-VRAM box, while still fitting a full page per call.
        # Pinned defensively so a future LDR default (cloud path is 128k) can't re-inflate it.
        "llm.local_context_window_size": int(CONFIG.get("research_ctx", 8192)),
        "llm.context_window_unrestricted": False,
        "search.tool": tool,
        "search.snippets_only": False,                  # READ full pages, not snippets
        "search.iterations": int(CONFIG["research_iterations"]),
        "search.questions_per_iteration": int(CONFIG["research_questions_per_iter"]),
        "search.max_results": int(CONFIG["research_max_results"]),
        "search.engine.web.searxng.default_params.instance_url": CONFIG["searxng_url"],
    }
    if tool == "tavily":
        o["search.engine.web.tavily.api_key"] = quota.key("TAVILY_API_KEY")
    return o


def pick_tool():
    """Tavily if a whole query's worth of calls fits under the cap, else SearXNG."""
    est = int(CONFIG["tavily_calls_per_query_est"])
    if quota.key("TAVILY_API_KEY") and quota.remaining("tavily") > est:
        return "tavily"
    return "searxng"


def preflight(tool):
    """Fail FAST if the chosen search engine is unreachable.

    Without this, a dead SearXNG does not error — LDR simply finds nothing and the model answers
    from its own recall, producing a clean-looking, correctly-sized, entirely UNCITED brief that
    passes every error check. That is worse than a crash: it is confident, unsupported research
    that reads as real (POWL, 2026-08-05, while Docker was down). SearXNG is a docker container
    on this box and has now died twice unattended, so it must be verified, not assumed."""
    if tool != "searxng":
        return
    url = CONFIG["searxng_url"].rstrip("/") + "/search?q=test&format=json"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        n = len(body.get("results") or [])
        if n == 0:
            raise ResearchInfraError(f"SearXNG at {CONFIG['searxng_url']} returned 0 results for a "
                                     f"probe query — engine up but not searching")
        print(f"[deep_research] preflight ok: searxng {n} results", flush=True)
    except ResearchInfraError:
        raise
    except Exception as e:
        raise ResearchInfraError(
            f"SearXNG unreachable at {CONFIG['searxng_url']} ({str(e)[:120]}) — refusing to "
            f"research: an uncited brief built from model recall would look valid. "
            f"Start Docker Desktop (the searxng container auto-restarts).")


def run_topic(query):
    from local_deep_research.api import quick_summary
    tool = pick_tool()
    res = quick_summary(query, settings_override=ldr_overrides(tool))
    if tool == "tavily":
        quota.bump("tavily", int(CONFIG["tavily_calls_per_query_est"]))
    return tool, res


def fresh(path, days):
    try:
        age = (time.time() - path.stat().st_mtime) / 86400
        return age <= days
    except Exception:
        return False


def build(ticker, name):
    t = ticker.upper()
    out_dir = Path(CONFIG["out_research_dir"]); out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{t}.md"
    if fresh(path, int(CONFIG["research_cache_days"])):
        # A cached brief is only reusable if it is actually research. Briefs written before
        # the infra-error guard existed are error text on disk with a fresh mtime, so trusting
        # mtime alone would re-serve the poison for research_cache_days AND make the ticker
        # fail sanity on every retry — a name stuck failing with no way to self-heal.
        cached_sig = ops.infra_error(path.read_text(encoding="utf-8", errors="replace"))
        if cached_sig:
            print(f"[deep_research] {t}: cached brief is infra-error text ({cached_sig}) — "
                  f"ignoring cache and re-researching", flush=True)
        else:
            print(f"[deep_research] {t}: cached ({path}), skip", flush=True)
            return path

    subj = f"{name} ({t})" if name else t
    yr = datetime.now().year
    L = [f"# DEEP RESEARCH BRIEF — {name + ' ' if name else ''}({t})",
         f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | iterative deep research "
         f"(full-page reads + citations). Cite only the listed sources.", ""]
    preflight(pick_tool())   # dead engine -> abort now, before writing anything

    failures = []            # infra failures — any one of these voids the whole brief
    for title, qt in TOPICS:
        q = qt.format(subj=subj, yr=yr)
        t0 = time.time()
        try:
            tool, res = run_topic(q)
        except Exception as e:
            failures.append((title, f"exception: {str(e)[:200]}"))
            print(f"[deep_research] {t} '{title}' ERROR {str(e)[:120]}", flush=True)
            continue
        summ = (res.get("summary") or "").strip()
        # LDR returns ollama/llama-server failures as 200-with-error-prose, so the
        # failure has to be caught on CONTENT. This is the bug that let whole days of
        # briefs ship as four sections of 'cudaMalloc failed: out of memory' dressed
        # up as research (7/28, 7/29, 8/3, 8/4).
        sig = ops.infra_error(summ)
        if sig:
            failures.append((title, f"{sig}: {summ[:200]}"))
            print(f"[deep_research] {t} '{title}' ::INFRA FAIL:: {sig} — {summ[:120]}", flush=True)
            continue
        L.append(f"## {title}  _(engine: {tool}, {time.time()-t0:.0f}s)_")
        L.append(summ if summ else "_(no summary returned)_")
        # citation->URL mapping lives in formatted_findings; sources/all_links_of_system as backup
        urls = []
        for s in (res.get("sources") or []):
            u = s.get("url") if isinstance(s, dict) else (s if isinstance(s, str) else None)
            if u and u not in urls:
                urls.append(u)
        ff = (res.get("formatted_findings") or "").strip()
        if urls:
            L.append("\n**Sources:**")
            L += [f"- {u}" for u in urls[:15]]
        elif ff:
            # extract URLs from the formatted findings block
            import re as _re
            found = []
            for u in _re.findall(r"https?://[^\s\)\]]+", ff):
                u = u.rstrip(".,)")
                if u not in found:
                    found.append(u)
            if found:
                L.append("\n**Sources:**")
                L += [f"- {u}" for u in found[:15]]
            urls = found
        L.append("")
        print(f"[deep_research] {t} '{title}' done via {tool} in {time.time()-t0:.0f}s "
              f"({len(summ)} chars, {len(urls)} sources)", flush=True)

    if failures:
        # Do NOT write the file. A written brief is cached research_cache_days (7) and is
        # read back as genuine research, so persisting an infra failure poisons every
        # downstream verdict for a week and never self-heals. Writing nothing leaves the
        # name due, so the retry re-runs it for real.
        detail = "; ".join(f"{ti}: {er[:120]}" for ti, er in failures)
        print(f"[deep_research] {t} ::ABORT:: {len(failures)}/{len(TOPICS)} topics hit infra "
              f"errors — brief NOT written (no poisoned cache). {detail}", flush=True)
        ops.notify_telegram(
            f"[RS2 ops] research_infra_fail — {t}: {len(failures)}/{len(TOPICS)} topics failed. "
            f"Brief not written; ticker will retry. {detail[:600]}")
        raise ResearchInfraError(detail)

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"[deep_research] {t} -> {path} (Tavily remaining: {quota.remaining('tavily')})", flush=True)
    return path


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: deep_research.py <TICKER> [Company Name]", file=sys.stderr)
        sys.exit(1)
    try:
        build(sys.argv[1].upper(), " ".join(sys.argv[2:]).strip())
    except ResearchInfraError as e:
        # exit 3 = infra failure, brief deliberately not written. run_rs2.run_research
        # treats this as fatal for the ticker so nothing is analysed on an empty brief.
        print(f"[deep_research] infra failure: {str(e)[:300]}", file=sys.stderr)
        sys.exit(3)
