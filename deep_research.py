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
import re
import sys
import time
import urllib.parse
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
    env = KEYED_TOOLS.get(tool)
    if env:
        o[f"search.engine.web.{tool}.api_key"] = quota.key(env)
    return o


# Keyed providers, and the secret each one reads. All three are first-class LDR engines taking
# an `api_key` init arg, so adding one is config, not integration.
KEYED_TOOLS = {"serper": "SERPER_API_KEY", "brave": "BRAVE_API_KEY", "tavily": "TAVILY_API_KEY"}


def searches_per_topic():
    """How many upstream search calls one topic costs — iterations x questions/iteration."""
    return max(1, int(CONFIG["research_iterations"]) * int(CONFIG["research_questions_per_iter"]))


def tool_chain():
    """Ordered list of search backends to try for a topic, best-effort first.

    SearXNG leads because it is UNMETERED and the paid quotas cannot carry this workload: at
    16 searches/ticker (2 iterations x 2 questions x 4 topics), the 256-ticker universe costs
    ~4,100 searches per sweep, and with research_cache_days=7 that is ~17,500/month. The
    combined paid allowance (serper 2400 + brave 950 + tavily 900 = 4,250) is about ONE sweep.
    Spending it as the primary would exhaust it in days and then break research entirely.

    So the paid keys are the FALLBACK that removes data breaks: when SearXNG's engines are
    blocked -- which happens routinely, yep and duckduckgo were both down tonight -- the topic
    retries on a keyed provider instead of returning zero sources and voiding the brief.

    ORDER: RESETTING quotas before ONE-TIME grants. Tavily and Brave refill monthly, so unspent
    allowance is simply lost; Serper's 2500 is a one-time signup grant that never comes back
    (they sell prepaid credits, not subscriptions). Sorting by "most remaining" -- the obvious
    thing -- would spend the irreplaceable bucket first while use-it-or-lose-it allowance
    expired unused. Within each class, deepest bucket first.
    """
    est = searches_per_topic()
    monthly, one_time = [], []
    for tool, env in KEYED_TOOLS.items():
        if not quota.key(env) or quota.remaining(tool) <= est:
            continue
        (one_time if tool in quota.TOTAL_CAPS else monthly).append((quota.remaining(tool), tool))
    return (["searxng"]
            + [t for _, t in sorted(monthly, reverse=True)]
            + [t for _, t in sorted(one_time, reverse=True)])


def pick_tool():
    """First usable backend — kept for callers that want a single name (preflight)."""
    return tool_chain()[0]


def preflight(tool):
    """Fail FAST if the chosen search engine is unreachable.

    Without this, a dead SearXNG does not error — LDR simply finds nothing and the model answers
    from its own recall, producing a clean-looking, correctly-sized, entirely UNCITED brief that
    passes every error check. That is worse than a crash: it is confident, unsupported research
    that reads as real (POWL, 2026-08-05, while Docker was down). SearXNG is a docker container
    on this box and has now died twice unattended, so it must be verified, not assumed.

    The probe must look like REAL RESEARCH. The original was `q=test` accepting >=1 result, and
    it passed for weeks while the instance was effectively dead: every default engine was
    CAPTCHA'd or rate-limited, real multi-word queries returned nothing, and 2,676 subqueries
    produced a 100% zero-source rate -- but a one-word probe still scraped together a single
    result and green-lit the run. A realistic query with a real threshold is the difference
    between "the container answers" and "the engine can actually research".

    It also inspects unresponsive_engines: results can look adequate while the engines doing the
    work are being blocked one by one, which is the leading edge of the failure, not the
    aftermath. Only engines that are supposed to be SERVING count -- a permanently blocked one
    (duckduckgo here) would otherwise fire on every single probe until it was ignored."""
    if tool != "searxng":
        return
    probe = "realty income dividend 2026"          # multi-word, the shape LDR actually issues
    min_results = int(CONFIG.get("searxng_min_probe_results", 5))
    serving = tuple(CONFIG.get("searxng_serving_engines", ["bing", "yep"]))
    url = (CONFIG["searxng_url"].rstrip("/") + "/search?"
           + urllib.parse.urlencode({"q": probe, "format": "json"}))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        n = len(body.get("results") or [])
        unresp = {name: msg for name, msg in (body.get("unresponsive_engines") or [])}
        blocked = [e for e in serving if e in unresp]
        if n < min_results:
            raise ResearchInfraError(
                f"SearXNG at {CONFIG['searxng_url']} returned {n} results (<{min_results}) for "
                f"a realistic query — engine up but not searching. Blocked engines: "
                f"{unresp or 'none reported'}")
        # Blocked engines matter only when they cost us RESULTS. Failing on any single blocked
        # engine was a self-inflicted outage: yep gets rate-limited routinely, bing keeps
        # serving 9-10 results, and research would have been fine — but the preflight aborted
        # anyway, so 44 consecutive tickers exited 3 in ~9s each without a single search being
        # attempted. Only refuse when EVERYTHING that serves is down; otherwise warn and run.
        if blocked and len(blocked) >= len(serving):
            detail = "; ".join(f"{e}: {unresp[e][:40]}" for e in blocked)
            raise ResearchInfraError(
                f"every SearXNG serving engine is blocked ({detail}) — refusing to research; "
                f"briefs would be thin or uncited")
        if blocked:
            print(f"[deep_research] preflight WARNING: "
                  f"{'; '.join(f'{e}: {unresp[e][:40]}' for e in blocked)} — "
                  f"{n} results still available, continuing", flush=True)
        print(f"[deep_research] preflight ok: searxng {n} results", flush=True)
    except ResearchInfraError:
        raise
    except Exception as e:
        raise ResearchInfraError(
            f"SearXNG unreachable at {CONFIG['searxng_url']} ({str(e)[:120]}) — refusing to "
            f"research: an uncited brief built from model recall would look valid. "
            f"Start Docker Desktop (the searxng container auto-restarts).")


# Domains that are never equity research. A brief about a company should not be grounded in
# dictionary entries or social posts — EW (Edwards Lifesciences) came back citing
# merriam-webster, dictionary.cambridge, youtube and ew.com (Entertainment Weekly), and it was
# FULLY CITED, so the citation guard passed it happily.
# DICTIONARY sources are never equity research, and their presence is a near-perfect signal that
# the search matched the TICKER AS AN ENGLISH WORD rather than the company. Measured across 597
# topics on disk: only 4 (0.7%) cite any dictionary at all, and every one is exactly that failure
# — COST ("cost"), CDNS ("cadence"), CGNX. EW's wrong-company brief was 40% dictionary.
DICT_DOMAINS = ("merriam-webster.", "dictionary.cambridge.", "dictionary.com", "thesaurus.",
                "wiktionary.", "urbandictionary.", "britannica.", "wikihow.",
                "collinsdictionary.", "vocabulary.com")
DICT_SHARE_REJECT = 0.15   # 0.7% base rate; 15% catches all four known cases with room to spare

# SOCIAL sources are a DIFFERENT distribution and must not share a threshold: median 0%, p95 11%,
# max 38%, and the top cases (OKLO, PLTR bear-case) are retail sentiment on speculative names,
# which is legitimate research. Only reject when they dominate outright.
SOCIAL_DOMAINS = ("youtube.", "facebook.", "instagram.", "tiktok.", "pinterest.", "quora.",
                  "zhihu.", "indeed.", "glassdoor.")
SOCIAL_SHARE_REJECT = 0.5


# LOW-TRUST sources: topically correct, so no relevance check catches them, but they are
# synthetic or laundered content rather than research. Measured across 8,835 citations: 12.5%
# came from these, against 34.4% from reputable finance sources.
#   support.trustwave.com — a SECURITY VENDOR's support portal serving templated stock-earnings
#     articles under /expert-time/ (ARGX, AVGO, GOOGL...). A hijacked or abused subdomain running
#     SEO spam; it appeared in 100 briefs.
#   the rest are AI-generated finance content farms.
# Not blocked outright: a single such citation alongside real sources is noise, not poison. They
# are rejected only when they DOMINATE a topic, which means the real sources never surfaced.
LOW_TRUST_DOMAINS = ("support.trustwave.com", "pitchgrade.com", "ainvest.com", "koalagains.com",
                     "geminibrief.com", "artificall.com", "stocksentinel.ai",
                     "pestel-analysis.com")
LOW_TRUST_SHARE_REJECT = 0.4


def _domain_share(urls, pats):
    """Fraction of sources whose domain matches any pattern. Never raises."""
    if not urls:
        return 0.0
    n = 0
    for u in urls:
        try:
            d = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
        except Exception:
            continue
        if any(p in d for p in pats):
            n += 1
    return n / len(urls)


def source_verdict(urls):
    """(reject_reason or None, dict_share, social_share, low_trust_share) for one topic."""
    ds = _domain_share(urls, DICT_DOMAINS)
    ss = _domain_share(urls, SOCIAL_DOMAINS)
    ls = _domain_share(urls, LOW_TRUST_DOMAINS)
    if ds >= DICT_SHARE_REJECT:
        return (f"{ds*100:.0f}% DICTIONARY sources — the ticker matched an English word, "
                f"not the company"), ds, ss, ls
    if ss >= SOCIAL_SHARE_REJECT:
        return f"{ss*100:.0f}% social-media sources — not research", ds, ss, ls
    return None, ds, ss, ls


def drop_low_trust(urls):
    """Remove synthetic / laundered sources, keeping the rest. Returns (kept, dropped).

    These are topically CORRECT, so no relevance check fires — but they are AI content farms and
    one hijacked subdomain, and they account for 12.5% of all citations on disk. Rejecting the
    topic outright would have been far worse than the disease: 74 of ~600 topics exceed 40%, and
    ONE failed topic voids the whole brief, so ~60 tickers would fail forever while the farms
    resurfaced on every retry. Strip them instead. If real sources remain the brief is fine; if
    NOTHING remains, the existing zero-source guard voids it, which is the correct outcome.
    """
    kept, dropped = [], []
    for u in urls:
        try:
            d = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
        except Exception:
            kept.append(u); continue
        (dropped if any(p in d for p in LOW_TRUST_DOMAINS) else kept).append(u)
    return kept, dropped


def extract_urls(res):
    """Source URLs from an LDR result: `sources` first, then the citation block."""
    urls = []
    for s in (res.get("sources") or []):
        u = s.get("url") if isinstance(s, dict) else (s if isinstance(s, str) else None)
        if u and u not in urls:
            urls.append(u)
    if not urls:
        ff = (res.get("formatted_findings") or "").strip()
        for u in re.findall(r"https?://[^\s\)\]]+", ff):
            u = u.rstrip(".,)")
            if u not in urls:
                urls.append(u)
    return urls


def run_topic(query):
    """Run one topic, falling through the tool chain until a backend returns SOURCES.

    This is the no-data-breaks path. A single blocked engine used to void an entire brief:
    every topic that came back uncited was discarded (correctly — uncited prose is not
    research), so one bad SearXNG moment cost the whole ticker and it retried from scratch
    later. Now a topic that yields nothing on SearXNG is retried on a keyed provider, and the
    brief completes with real citations from whichever backend actually answered. Each topic
    records which one, so a brief assembled from mixed sources is auditable.

    Returns (tool, res, urls) — the last attempt if every backend failed.
    """
    from local_deep_research.api import quick_summary
    chain = tool_chain()
    last = (chain[0], {}, [])
    for i, tool in enumerate(chain):
        try:
            res = quick_summary(query, settings_override=ldr_overrides(tool))
        except Exception as e:
            if i + 1 >= len(chain):
                raise
            print(f"[deep_research]   {tool} raised {str(e)[:80]} — trying {chain[i+1]}", flush=True)
            continue
        if tool in KEYED_TOOLS:
            quota.bump(tool, searches_per_topic())     # charge the meter for what we spent
        urls = extract_urls(res)
        sig = ops.infra_error((res.get("summary") or "").strip())
        if urls and not sig:
            if i:
                print(f"[deep_research]   recovered on {tool} ({len(urls)} sources)", flush=True)
            return tool, res, urls
        if i + 1 < len(chain):
            print(f"[deep_research]   {tool} gave {sig or 'zero sources'} — "
                  f"falling back to {chain[i+1]}", flush=True)
        last = (tool, res, urls)
    return last


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
        cached_txt = path.read_text(encoding="utf-8", errors="replace")
        cached_sig = ops.infra_error(cached_txt)
        # A fabricated brief passes infra_error (it is fluent prose, not error text) and is
        # typically LARGER than a healthy one — median 25KB vs 16KB — so neither the error
        # signature nor the byte count rejects it. Only the citation test does. Without this
        # arm the cache re-serves the hallucination for research_cache_days while
        # run_rs2.sanity_check fails the ticker on every retry: 3 retries x ~10min burned,
        # no progress, no self-heal.
        uncited = not re.search(r"^- https?://", cached_txt, re.M)
        if cached_sig or uncited:
            why = f"infra-error text ({cached_sig})" if cached_sig else \
                  f"ZERO source citations ({len(cached_txt)}B of uncited prose)"
            print(f"[deep_research] {t}: cached brief is {why} — "
                  f"ignoring cache and re-researching", flush=True)
        else:
            print(f"[deep_research] {t}: cached ({path}), skip", flush=True)
            return path

    # A BARE TICKER is an ambiguous search subject and the queries below embed it directly:
    # "EW competitive position, market share, moat durability" returned Entertainment Weekly,
    # and "DOCU ..." returned dictionary definitions of "document". Both briefs were fully
    # CITED, so the citation guard passed them. When no name resolves, at least anchor the
    # query to the equity with "stock" and say so loudly.
    if name:
        subj = f"{name} ({t})"
    else:
        subj = f"{t} stock"
        print(f"[deep_research] {t}: WARNING no company name — searching as {subj!r}; "
              f"a bare ticker can match the wrong entity", flush=True)
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
            tool, res, urls = run_topic(q)
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
        # Resolve sources BEFORE committing any prose. LDR happily returns a fluent,
        # [1][2]-annotated summary when the search leg found nothing usable — that text is
        # pure model recall, and the old order (append summ, THEN look for urls) wrote it
        # to disk regardless. That is how POWL shipped 11 straight bundles asserting a
        # debt/equity of 4.2, a plant fire and a $500M lawsuit for a net-cash company.
        # citation->URL mapping lives in formatted_findings; sources/all_links_of_system as backup
        # urls came back from run_topic, which already tried every backend in the chain.

        # ZERO-SOURCE GUARD: uncited prose is not research. Treat it exactly like an infra
        # failure so the brief is never written and the ticker retries for real, instead of
        # caching a hallucination for research_cache_days and failing sanity on every retry.
        urls, dropped = drop_low_trust(urls)
        if dropped:
            print(f"[deep_research] {t} '{title}' dropped {len(dropped)} low-trust source(s) "
                  f"({', '.join(sorted({urllib.parse.urlparse(u).netloc.replace('www.','') for u in dropped}))[:70]})",
                  flush=True)

        if not urls:
            failures.append((title, f"zero sources — {len(summ)}B of uncited prose "
                                    f"(model recall, not research): {summ[:160]}"))
            print(f"[deep_research] {t} '{title}' ::NO SOURCES:: {len(summ)}B of uncited "
                  f"prose discarded — {summ[:120]}", flush=True)
            continue

        # RELEVANCE GUARD. Citations prove the model searched; they do NOT prove it searched for
        # the right company. EW returned dictionary entries, YouTube and Entertainment Weekly and
        # passed every existing check because each of those is a real URL. Reject a topic grounded
        # mostly in domains that cannot be equity research, and treat it exactly like zero
        # sources — void the brief rather than cache confident nonsense.
        reason, dshare, sshare, lshare = source_verdict(urls)
        if reason:
            doms = ", ".join(sorted({urllib.parse.urlparse(u).netloc.replace("www.", "")
                                     for u in urls})[:6])
            failures.append((title, f"irrelevant sources — {reason} ({doms})"))
            print(f"[deep_research] {t} '{title}' ::IRRELEVANT SOURCES:: {reason} "
                  f"({doms}) — discarded", flush=True)
            continue
        if dshare or sshare or lshare:
            print(f"[deep_research] {t} '{title}' note: sources {dshare*100:.0f}% dictionary, "
                  f"{sshare*100:.0f}% social, {lshare*100:.0f}% low-trust", flush=True)

        L.append(f"## {title}  _(engine: {tool}, {time.time()-t0:.0f}s)_")
        L.append(summ if summ else "_(no summary returned)_")
        L.append("\n**Sources:**")
        L += [f"- {u}" for u in urls[:15]]
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
