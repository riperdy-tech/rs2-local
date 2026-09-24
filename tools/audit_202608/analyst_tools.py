#!/usr/bin/env python3
"""analyst_tools.py — let the depth-tier analyst search DURING its own reasoning.

WHY. The 2026-08-20 audit of three Q5 GOOG valuations found all three had invented a
2027+ capital-expenditure path, and that single unsourced assumption decided the answer:
holding everything else and refusing the assumed collapse moved the three from $317/$321/$273
to $204/$178/$149. They did not reason badly. The data pack contains capex guidance for 2026
ONLY, so they filled a hole. A model that can look things up would have found management's own
forward commentary instead of guessing.

TWO RULES, both enforced here rather than trusted to the prompt:

1. SNAPSHOT EVERYTHING. Every query, every result list and every fetched page is written into
   the run directory. Otherwise two runs differ because the WEB moved, not because of sampling,
   and the seeded-consensus tolerance measurement becomes meaningless. With snapshots a run
   stays auditable after the fact and can be replayed against exactly what it saw.

2. SEARCH FOR THE FUTURE, NEVER FOR THE PAST. Financials come from SEC filings, which we already
   hold. Re-sourcing them from the web is how the research brief ended up asserting a stale
   $462B cloud backlog while the correct $514B sat in the verbatim transcript in the same pack.
   The tool description says so, and `looks_like_refetch` warns when a query smells like it is
   trying to re-derive a number the pack already contains.

Local SearXNG only (config searxng_url) — unmetered, no API key, no per-call cost.
"""
import difflib
import html
import io
import json
import re
import ssl
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
# NOTE: do NOT rewrap sys.stdout at import. This is a library; the importer may already have
# installed its own TextIOWrapper, and wrapping its .buffer a second time closes the first on
# GC -> "ValueError: I/O operation on closed file" on the caller's next print. Killed the first
# tool-enabled run. Console encoding is set under __main__ only.

import rs2_data  # noqa: E402

SEARX = rs2_data.CONFIG.get("searxng_url", "http://localhost:8888")
OLLAMA = "http://127.0.0.1:11434/api/chat"
MAX_TOOL_CALLS = 25          # balanced research budget; deduplication eliminates redundant query loops
UA = {"User-Agent": "Mozilla/5.0 (RS2 analyst research)"}
# SEC EDGAR refuses requests that do not declare a contact (its fair-access policy), so every
# sec.gov fetch with UA failed with HTTP 403 - including the filings the pack tells the analyst to
# check. sec.gov fetches use the declared identity sec_guidance already uses.
try:
    from sec_guidance import UA as SEC_UA  # noqa: E402
except Exception:
    SEC_UA = UA
# Certificate verification with Mozilla's root bundle (certifi) plus the Windows store. The
# Windows store alone missed roots some sites chain to: cnn.com failed with "unable to get local
# issuer certificate" in the E9 discovery runs. Verification stays on.
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    _SSL_CTX.load_default_certs()
except Exception:
    _SSL_CTX = None

# Content farms and aggregator spam. Mirrors deep_research.py's low-trust stripping — a search
# result is only as good as its source, and these restate numbers without filing provenance.
LOW_TRUST = ("pitchgrade.com", "stocksentinel", "zacks.com/stock/chart", "marketbeat.com",
             "simplywall.st", "investing.com/news/stock-market-news", "benzinga.com/insights")

REFETCH_SMELL = re.compile(
    r"\b(ttm|trailing twelve)\b|\bnet income\b|\brevenue for (fy|20)\d|\bfree cash flow\b|"
    r"\bshares outstanding\b|\bmarket cap\b", re.I)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for information that is NOT in your data pack. Use this for "
            "FORWARD-LOOKING and CONTEXTUAL facts: management guidance beyond the periods you "
            "were given, capital-expenditure plans for future years, analyst estimates, "
            "competitor spending, industry capacity, regulatory rulings, and current macro "
            "(rates, policy). "
            "DO NOT use it to re-source financial statement figures you already hold — your "
            "pack's revenue, net income, operating cash flow, capex, FCF and share counts come "
            "from SEC filings and are authoritative. Web restatements of those are less "
            "reliable, not more. "
            "If a number you need for an assumption is missing from the pack, SEARCH FOR IT "
            "rather than assuming a value."
            " Your earlier tool results stay in the conversation as compact notes marked [call N]. "
            "Read them before searching; do not repeat a search you have already run or re-fetch a page you have already read."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "a specific search query"},
                "why": {"type": "string",
                        "description": "what assumption this is meant to ground, in one line"},
            },
            "required": ["query"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "fetch_page",
        "description": ("Retrieve the readable text of one URL returned by search_web, when the "
                        "snippet is not enough. Prefer primary sources: company IR pages, "
                        "earnings-call transcripts, regulators, central banks."),
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "run_financial_model",
        "description": (
            "Invoke the Python Financial Modeling Analyst Desk to execute deterministic calculations: "
            "1. Three-Stage DCF: computes exact per-share intrinsic value across Stage 1 (explicit growth), "
            "Stage 2 (linear fade over fade_years to terminal_g), and Stage 3 (dual terminal value: Gordon growth "
            "and exit multiple, both properly discounted to t=0). Enforces valuation frames ('equity' discounts FCFE "
            "at cost_of_equity with nonzero net_debt refused; 'firm' discounts FCFF at true_wacc requiring net_debt "
            "and shares_diluted) and verifies rate pairing via rate_engine. Refuses SBC double-deduction. Reconciles "
            "implied terminal EV/FCF multiple against sector_multiple_band. "
            "2. Reverse DCF: solves market-implied growth under (a) analyst's own structure and (b) neutral reference "
            "structure (coe_anchor, 10-year linear fade to terminal_g_anchor) returning implied 10-year CAGR and base-rate table percentile. "
            "3. Mathematical continuous Kelly sizing: derives exact quarter-Kelly and full Kelly log-wealth position sizes across scenarios. "
            "4. Blend mode: calculates weighted combination of named desk valuation legs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "price": {"type": "number", "description": "Current market price T0 from Section 2."},
                "mode": {"type": "string", "enum": ["dcf", "blend"], "description": "Calculation mode: 'dcf' (default) or 'blend'."},
                "valuation_frame": {
                    "type": "string",
                    "enum": ["equity", "firm"],
                    "description": "Valuation frame: 'equity' (default) discounts FCFE at cost_of_equity; nonzero net_debt is refused. 'firm' discounts FCFF at true_wacc; requires net_debt and shares_diluted."
                },
                "rate_type": {
                    "type": "string",
                    "enum": ["cost_of_equity", "true_wacc", "cost_of_equity_proxy"],
                    "description": "Semantic discount rate type. Must match valuation_frame (equity -> cost_of_equity; firm -> true_wacc)."
                },
                "explicit_growth": {
                    "type": "array",
                    "description": "Annual growth of base_cf - the owner cash flow being valued - for each Stage 1 year (e.g. [0.12, 0.10, 0.08, 0.06, 0.05]). Not revenue growth: revenue growth leaves out margin change. Years 1-2 normally follow consensus EPS growth (SECTION 8).",
                    "items": {"type": "number"}
                },
                "growth_rates": {
                    "type": "array",
                    "description": "Alias for explicit_growth.",
                    "items": {"type": "number"}
                },
                "fade_years": {
                    "type": "integer",
                    "description": "Duration of Stage 2 linear fade in years (integer >= 0). Fades linearly from the last explicit rate to terminal_g."
                },
                "terminal_g": {
                    "type": "number",
                    "description": "REQUIRED for DCF. Long-term nominal terminal growth rate as decimal (e.g. 0.025 for 2.5%, 0.035 for 3.5%). The silent default was removed in Phase 4; calls without it are refused."
                },
                "terminal_exit_multiple": {"type": "number", "description": "Optional exit multiple on final projected cash flow (e.g. 16.0 for 16x)."},
                "sector_multiple_band": {
                    "type": "object",
                    "description": "MRI sector multiple band {low, mid, high, metric} used for reconciliation of implied terminal EV/FCF multiple.",
                    "properties": {
                        "low": {"type": "number"},
                        "mid": {"type": "number"},
                        "high": {"type": "number"},
                        "metric": {"type": "string"}
                    }
                },
                "sbc_treatment": {
                    "type": "string",
                    "enum": ["deducted_in_cf", "add_back_dilution"],
                    "description": "SBC policy declaration. If 'deducted_in_cf', sbc_dilution may NOT also be passed (double deduction refused)."
                },
                "sbc_dilution": {
                    "type": "number",
                    "description": "Share dilution from SBC when sbc_treatment is 'add_back_dilution'. Must NOT be passed if sbc_treatment is 'deducted_in_cf'."
                },
                "base_cf": {"type": "number", "description": "Base owner cash flow / FCF (in $B or per-share, matching units)."},
                "wacc": {"type": "number", "description": "Cost of capital / discount rate as decimal, e.g. 0.085 for 8.5%."},
                "annuity_flow": {"type": "number", "description": "Separate annual services / installed-base recurring annuity cash flow (if unbundled)."},
                "annuity_cap_rate": {"type": "number", "description": "Capitalization rate for annuity flow (e.g. 0.075 for 7.5%)."},
                "net_debt": {"type": "number", "description": "Total net debt in $B. Must be 0 or omitted in equity frame; required in firm frame."},
                "shares_diluted": {"type": "number", "description": "Diluted share count in billions. Required in firm frame."},
                "demonstrated_cagr_5y": {"type": "number", "description": "Historical 5-year revenue CAGR in percent from Section 7."},
                "coe_anchor": {"type": "number", "description": "Cost of equity anchor decimal for neutral reference reverse DCF."},
                "terminal_g_anchor": {"type": "number", "description": "Long-run terminal growth anchor decimal for neutral reference reverse DCF."},
                "base_rate_table": {
                    "type": "object",
                    "description": "Base rate table {p50, p90, share_ge_10, share_ge_20, share_ge_30} for implied CAGR percentile ranking.",
                    "properties": {
                        "p50": {"type": "number"},
                        "p90": {"type": "number"},
                        "share_ge_10": {"type": "number"},
                        "share_ge_20": {"type": "number"},
                        "share_ge_30": {"type": "number"}
                    }
                },
                "legs": {
                    "type": "array",
                    "description": "Named valuation legs for blend mode: [{'name': 'Gordon DCF', 'weight': 0.6, 'iv': 150.0, 'source': 'desk'}, ...]. Weights must sum to 1.0.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "weight": {"type": "number"},
                            "iv": {"type": "number"},
                            "source": {"type": "string"}
                        },
                        "required": ["name", "weight", "iv"]
                    }
                },
                "scenarios": {
                    "type": "array",
                    "description": (
                        "List of scenario dicts. You can provide pre-computed 'iv' or supply scenario DCF parameters "
                        "('base_cf', 'growth_rates', 'wacc', 'terminal_g') and Python will calculate all IVs, expectations gap, "
                        "and Kelly sizing in a single call. Example: "
                        "[{'name': 'Base', 'prob': 0.50, 'base_cf': 4.8, 'growth_rates': [0.29, 0.22, 0.17, 0.15, 0.12], 'wacc': 0.095, 'terminal_g': 0.045}, "
                        "{'name': 'Bull', 'prob': 0.30, 'base_cf': 5.0, 'growth_rates': [0.34, 0.26, 0.21, 0.18, 0.15], 'wacc': 0.090, 'terminal_g': 0.050}, "
                        "{'name': 'Bear', 'prob': 0.20, 'base_cf': 4.5, 'growth_rates': [0.15, 0.13, 0.07, 0.06, 0.05], 'wacc': 0.115, 'terminal_g': 0.025}]"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "prob": {"type": "number"},
                            "iv": {"type": "number", "description": "Optional pre-computed intrinsic value"},
                            "base_cf": {"type": "number", "description": "Base FCF in $B for this scenario"},
                            "growth_rates": {"type": "array", "items": {"type": "number"}, "description": "5 annual growth rates of base_cf (cash flow, not revenue)"},
                            "explicit_growth": {"type": "array", "items": {"type": "number"}, "description": "5 annual growth rates of base_cf (cash flow, not revenue)"},
                            "fade_years": {"type": "integer"},
                            "wacc": {"type": "number", "description": "Discount rate as decimal"},
                            "terminal_g": {"type": "number", "description": "REQUIRED. Terminal growth as decimal"},
                            "terminal_exit_multiple": {"type": "number"}
                        },
                        "required": ["name", "prob"]
                    }
                }
            },
            "required": ["price"]
        }
    }
}]


def research_tools():
    """Return the TOOLS entries for search_web and fetch_page only."""
    return [t for t in TOOLS if t.get("function", {}).get("name") in ("search_web", "fetch_page")]


def _normalize_tokens(q):
    """Normalize query into sorted keywords to detect redundant/rephrased searches."""
    tokens = set(re.findall(r"\b[a-z0-9]{3,}\b", (q or "").lower()))
    tokens.discard("the")
    tokens.discard("and")
    tokens.discard("for")
    return tokens


def is_near_duplicate(q1, q2, threshold=0.75):
    """Jaccard similarity check on query keyword sets."""
    s1, s2 = _normalize_tokens(q1), _normalize_tokens(q2)
    if not s1 or not s2:
        return False
    inter = len(s1.intersection(s2))
    union = len(s1.union(s2))
    return (inter / union) >= threshold if union > 0 else False


def looks_like_refetch(query):
    return bool(REFETCH_SMELL.search(query or ""))


def search_web(query, why="", snap=None, n=6, query_cache=None):
    """SearXNG JSON search -> compact result list. Deduplicates against prior queries."""
    if not query or not query.strip():
        rec = {"query": query, "why": why, "error": "empty query", "results": []}
        if snap is not None:
            snap.append({"tool": "search_web", "ts": time.strftime("%H:%M:%S"), **rec})
        return rec
    if query_cache is not None:
        for prev_q, prev_res in query_cache.items():
            if is_near_duplicate(query, prev_q):
                rec = {"query": query, "why": why, "n_results": len(prev_res), "results": prev_res,
                       "refetch_warning": looks_like_refetch(query),
                       "deduplicated_from": prev_q, "cache_hit": True}
                if snap is not None:
                    snap.append({"tool": "search_web", "ts": time.strftime("%H:%M:%S"),
                                 "dedup": True, **rec})
                return rec

    url = f"{SEARX}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        rec = {"query": query, "why": why, "error": f"search failed: {str(e)[:120]}", "results": []}
        if snap is not None:
            snap.append({"tool": "search_web", "ts": time.strftime("%H:%M:%S"), **rec})
        return rec
    out = []
    for res in (data.get("results") or []):
        u = res.get("url") or ""
        if any(bad in u for bad in LOW_TRUST):
            continue
        out.append({"title": (res.get("title") or "")[:180],
                    "url": u,
                    "snippet": re.sub(r"\s+", " ", res.get("content") or "")[:420]})
        if len(out) >= n:
            break
    rec = {"query": query, "why": why, "n_results": len(out), "results": out,
           "refetch_warning": looks_like_refetch(query), "cache_hit": False}
    if query_cache is not None:
        query_cache[query] = out
    if snap is not None:
        snap.append({"tool": "search_web", "ts": time.strftime("%H:%M:%S"), **rec})
    return rec


def _same_article(url, known_urls):
    """A URL from this run's search results with the same host and the same article slug (last
    path segment, at least 12 characters), or None. The model copies URLs from memory and
    garbles them: 7 of 86 fetches in the E9 discovery runs were 404s, all on URLs no search
    returned, such as fool.com/investing/2026-09-14/<slug> for the returned
    fool.com/investing/2026/09/14/<slug>."""
    def parts(u):
        p = urllib.parse.urlparse(u or "")
        host = (p.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        segs = [s for s in p.path.split("/") if s]
        return host, (segs[-1] if segs else "")
    host, slug = parts(url)
    if len(slug) < 12:
        return None
    for k in known_urls or ():
        if k and k.rstrip("/") != url.rstrip("/") and parts(k) == (host, slug):
            return k
    return None


# --- Blocked or paywalled page -> the same story from a free, legitimate copy -----------------
# A third of the E9 discovery fetches were refused (HTTP 401/403: Barron's, Seeking Alpha,
# Forbes, ...), and AMD's run lost the Muse story that way. News is rarely exclusive to one
# paywalled page: it is syndicated under licence (Yahoo Finance, MSN, AOL, Nasdaq, Morningstar,
# AP) or reported by other outlets. On a refusal the harness searches the headline and opens such
# a copy. It never circumvents a paywall: no crawler impersonation, no archive or mirror sites.
# A near-verbatim copy on a host that is neither a licensed syndicator nor the same publisher is
# skipped, because that is usually a scraped mirror of the paywalled piece.
SYNDICATION_HOSTS = ("finance.yahoo.com", "yahoo.com", "msn.com", "aol.com", "nasdaq.com",
                     "morningstar.com", "apnews.com")
NOT_ARTICLES = ("youtube.com", "facebook.com", "linkedin.com", "twitter.com", "x.com",
                "instagram.com", "tiktok.com", "reddit.com", "wikipedia.org", "archive.ph",
                "archive.today", "archive.is", "12ft.io", "removepaywall")
PAYWALL_MARKERS = ("subscribe to continue", "subscribe to read", "subscribers only", "for subscribers",
                   "already a subscriber", "to continue reading", "sign in to continue",
                   "log in to continue", "create a free account to", "premium article")
_TITLE_STOP = set("the and for its has have had are was were with from that this into over after than "
                  "amid will would could may might not but new says said stock stocks shares news why "
                  "how what today report reports inc corp com".split())


def _host(u):
    h = (urllib.parse.urlparse(u or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _publisher(h):
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov"):
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else h


def _title_tokens(t):
    """Content words of a headline, lightly stemmed so "signs"/"signed" and "deals"/"deal" match."""
    words = {w for w in re.findall(r"[a-z0-9]+", (t or "").lower().replace("'s", ""))
             if len(w) >= 3 and w not in _TITLE_STOP and not w.isdigit()}
    return {re.sub(r"(ing|ed|es|s)$", "", w) if len(w) > 4 else w for w in words}


def _norm_title(t):
    t = re.sub(r"\s*(\.\.\.|…)\s*$", "", (t or "").lower())
    return re.sub(r"\s+[-|]\s+[^-|]+$", "", t).strip()      # drop a trailing ' - Site Name'


def _slug_query(url):
    """Search words from a URL's article slug, for a URL no search returned."""
    segs = [s for s in urllib.parse.urlparse(url or "").path.split("/") if s]
    if not segs:
        return None
    slug = re.sub(r"\.(html?|php|aspx?)$", "", max(segs, key=len))
    words = [w for w in re.split(r"[-_]+", slug)
             if w and not w.isdigit() and not (len(w) >= 6 and re.search(r"\d", w) and re.search(r"[a-z]", w))]
    return " ".join(words[:12]) if len(words) >= 3 else None


def _looks_paywalled(text):
    t = (text or "")
    return len(t) < 2500 and any(m in t.lower() for m in PAYWALL_MARKERS)


def _searx(query, n=10):
    url = f"{SEARX}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return [{"url": x.get("url") or "", "title": x.get("title") or ""} for x in (data.get("results") or [])][:n]


def _alternate_copy(url, title, cap, url_cache, snap):
    q = (title or "").strip() or _slug_query(url)
    if not q:
        return None
    try:
        results = _searx(q)
    except Exception:
        return None
    host, want = _host(url), _title_tokens(q)
    cands = []
    for r in results:
        u, t = r["url"], r["title"]
        h = _host(u)
        if not u or h == host or any(bad in u for bad in LOW_TRUST) \
                or any(h == d or h.endswith("." + d) or d in u for d in NOT_ARTICLES):
            continue
        common = want & _title_tokens(t)
        overlap = len(common) / max(1, min(len(want), len(_title_tokens(t))))
        # Same story: 3+ shared headline words, or 2 covering half the original headline. Two
        # shared words alone are often just the company name (a DXC headline matched a generic
        # DXC price-target page).
        if overlap < 0.3 or not (len(common) >= 3 or (len(common) == 2 and len(want) <= 4)):
            continue
        syndicated = any(h == s or h.endswith("." + s) for s in SYNDICATION_HOSTS)
        verbatim = difflib.SequenceMatcher(None, _norm_title(q), _norm_title(t)).ratio() >= 0.9
        if verbatim and not syndicated and _publisher(h) != _publisher(host):
            continue                                     # near-verbatim copy on an unknown host
        cands.append((overlap, u, t))
    for _, u, t in sorted(cands, key=lambda c: -c[0])[:3]:
        res = fetch_page(u, snap, cap=cap, url_cache=url_cache, _fallback=False)
        if not res.get("error") and (res.get("chars") or 0) >= 2000 and not _looks_paywalled(res.get("text")):
            return {**res, "alternate_for": url, "alternate_query": q,
                    "note": (f"{url} is not readable to us (blocked or paywalled). This is the same story "
                             f"from {_host(u)}: \"{t[:120]}\".")}
    return None


def fetch_page(url, snap=None, cap=9000, url_cache=None, known_urls=None, _fallback=True):
    if any(bad in url for bad in LOW_TRUST):
        if _fallback:
            copy = _alternate_copy(url, (known_urls or {}).get(url) if isinstance(known_urls, dict) else None,
                                   cap, url_cache, snap)
            if copy:
                return copy
        if snap is not None:
            snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"), "url": url,
                         "chars": 0, "text": "", "cached": False,
                         "refused": "low-trust source"})
        return {"url": url, "error": "low-trust source refused"}
    if url_cache is not None and url in url_cache:
        # A cache HIT still means the model was served this page, so it belongs in the audit trail.
        # Returning here without appending under-recorded GEV sample 1 by 6 of its 28 tool calls —
        # the repeats were re-fetches of the same SEC and GEV URLs, and the module's rule is that
        # EVERY fetched page is written into the run directory.
        rec = url_cache[url]
        if snap is not None:
            snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"), "url": url,
                         "chars": rec.get("chars"), "text": rec.get("text", ""), "cached": True})
        # A copy, not the stored `rec` itself — `cache_hit` marks the RETURN value for this call
        # (P4.0b hit/miss accounting) and must never leak into what is persisted in url_cache.
        return {**rec, "cache_hit": True}
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    is_sec = host == "sec.gov" or host.endswith(".sec.gov")
    try:
        req = urllib.request.Request(url, headers=SEC_UA if is_sec else UA)
        with urllib.request.urlopen(req, timeout=40, context=_SSL_CTX) as r:
            raw = r.read(1_500_000).decode("utf-8", "replace")
    except Exception as e:
        code = getattr(e, "code", None)
        alt = _same_article(url, known_urls) if code == 404 else None
        if alt:
            res = fetch_page(alt, snap, cap=cap, url_cache=url_cache, _fallback=False)
            if not res.get("error"):
                return {**res, "corrected_from": url,
                        "note": f"{url} does not exist (HTTP 404); this is the same article at the "
                                f"address your search returned. Copy URLs exactly from search results."}
        if _fallback and code in (401, 402, 403, 404, 451):
            copy = _alternate_copy(url, (known_urls or {}).get(url) if isinstance(known_urls, dict) else None,
                                   cap, url_cache, snap)
            if copy:
                return copy
        # A FAILED fetch is still a tool result the model was served, and the run directory is
        # meant to explain the model's behaviour after the fact. Without this the audit trail
        # shows the model going quiet with no record of why.
        if snap is not None:
            snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"), "url": url,
                         "chars": 0, "text": "", "cached": False,
                         "error": f"fetch failed: {str(e)[:120]}"})
        return {"url": url, "error": f"fetch failed: {str(e)[:120]}"}
    if is_sec and "<DOCUMENT>" in raw:
        # A full EDGAR submission (.txt) opens with an SGML filing header that would fill most
        # of the `cap` characters the model is shown. Start at the first document instead.
        raw = raw[raw.index("<DOCUMENT>"):]
    txt = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    # Decode every entity. The old named-only strip left numeric ones (&#160; &#8226; &#58;) in
    # the text - EDGAR filings are full of them - and dropped real characters such as "&".
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if _fallback and _looks_paywalled(txt):
        copy = _alternate_copy(url, (known_urls or {}).get(url) if isinstance(known_urls, dict) else None,
                               cap, url_cache, snap)
        if copy:
            return {**copy, "paywalled_teaser": txt[:600]}
    rec = {"url": url, "chars": len(txt), "text": txt[:cap]}
    if url_cache is not None:
        url_cache[url] = rec
    if snap is not None:
        snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"),
                     "url": url, "chars": len(txt), "text": txt[:cap], "cached": False})
    return {**rec, "cache_hit": False}


def dispatch_tool(name, args, snap=None, query_cache=None, url_cache=None, known_urls=None):
    """Unified dispatcher for all analyst tools."""
    if name == "search_web":
        return search_web(args.get("query", ""), args.get("why", ""), snap, query_cache=query_cache)
    elif name == "fetch_page":
        return fetch_page(args.get("url", ""), snap, url_cache=url_cache, known_urls=known_urls)
    elif name == "run_financial_model":
        import financial_model_tool as fmt
        res = fmt.execute_financial_model(args)
        md = fmt.format_model_results_markdown(res)
        res["markdown_report"] = md
        if snap is not None:
            snap.append({
                "tool": "run_financial_model",
                "ts": time.strftime("%H:%M:%S"),
                "params": args,
                "result": res,
            })
        return res
    else:
        return {"error": f"unknown tool {name}"}


# A terminal turn is only a DELIVERABLE if it is actually a memorandum. Anything from
# `<tool_call>` to `</tool_call>`, or a dangling opening tag to end-of-text, is tool-call
# envelope markup rather than prose — strip it and judge what remains.
_TOOL_CALL_BLOCK = re.compile(r"<tool_call>.*?(?:</tool_call>|\Z)", re.S | re.I)
# Matches depth_sanity.STUB_CHARS: a 12-section institutional memorandum cannot be shorter than
# this. Sample 1 of the GEV consensus run (2026-09-20) published 1,861 chars of pure envelope.
REPORT_MIN_CHARS = 5000


def report_is_deliverable(text):
    """Issue 1 (GEV 2026-09-20 sample 1): is this terminal turn a memorandum, or a stub?

    WHY THIS EXISTS. chat_with_tools used `not final_report.strip()` as its completeness test,
    so ANY non-empty terminal content counted as the report. With --tools, sample 1 spent 29
    minutes over 30 tool calls and then emitted the tool-call envelope as plain content — Ollama
    did not parse it into `tool_calls`, so `tcs` was empty and the non-empty envelope was accepted
    as the deliverable. The forced report-delivery turn below never fired, and the sample was
    published as a report and then discarded for containing no value.

    The envelope is stripped rather than merely detected, so a genuine memorandum that happens to
    end with one stray late tool call is still accepted. Returns True only if what remains is a
    memorandum of plausible length.
    """
    body = _TOOL_CALL_BLOCK.sub("", text or "").strip()
    return len(body) >= REPORT_MIN_CHARS


def turn_metrics(resp):
    """Per-turn cost record from one Ollama /api/chat response.

    Added 2026-09-20. The loop previously accumulated ONLY whole-sample totals (`gen_tokens`,
    `eval_duration_total`), so a run directory could not answer "which turn cost 15 minutes".
    Measured on GEV: a single turn took 952s (≈39K tokens at the observed 41 tok/s), and 36% of
    the sample sat before the first tool call and after the last — all of it invisible in the
    totals, because the totals are dominated by whichever turn happened to be longest.

    Kept as a pure function so the mapping is testable without a live model.
    """
    return {
        "prompt_tokens": resp.get("prompt_eval_count"),
        "prompt_eval_s": round((resp.get("prompt_eval_duration") or 0) / 1e9, 2),
        "gen_tokens": resp.get("eval_count"),
        "gen_s": round((resp.get("eval_duration") or 0) / 1e9, 2),
        "load_s": round((resp.get("load_duration") or 0) / 1e9, 2),
        "done_reason": resp.get("done_reason"),
        "n_tool_calls": len((resp.get("message") or {}).get("tool_calls") or []),
    }


def compact_tool_note(name, args, result, call_index) -> str:
    """Format a compact note for an earlier tool result to preserve context without bloat."""
    # Check for budget/quota messages first — kept verbatim
    if isinstance(result, dict):
        status = result.get("status")
        msg = str(result.get("message") or "")
        err = str(result.get("error") or "")
        if status == "search_quota_met" or "search_quota_met" in msg or "search_quota_met" in err:
            return json.dumps(result)
        if "budget exhausted" in msg.lower() or "budget exhausted" in err.lower():
            return json.dumps(result)
    elif isinstance(result, str):
        if "search_quota_met" in result or "budget exhausted" in result.lower():
            return result

    if name == "search_web":
        q = (args or {}).get("query", "") if isinstance(args, dict) else ""
        prefix = f'[call {call_index}] search: "{q}" -> '
        if isinstance(result, dict) and result.get("error"):
            return f"{prefix}{result['error']}"

        is_dedup = bool(isinstance(result, dict) and (
            result.get("deduplicated_from") or result.get("cache_hit") or result.get("dedup")
        ))
        res_list = (result.get("results") or []) if isinstance(result, dict) else []
        res_lines = []
        for r in res_list[:4]:
            t = (r.get("title") or "").strip()
            u = (r.get("url") or "").strip()
            s = (r.get("snippet") or "").strip()[:220]
            res_lines.append(f"{t} | {u} | {s}")

        if res_lines:
            note = f"{prefix}\n" + "\n".join(res_lines)
        else:
            note = prefix.rstrip()
        if is_dedup:
            note += " (repeat of an earlier search)"
        return note

    elif name == "fetch_page":
        u = (args or {}).get("url", "") if isinstance(args, dict) else ""
        prefix = f"[call {call_index}] page: {u} -> "
        if isinstance(result, dict) and (result.get("error") or result.get("refused")):
            err = result.get("error") or result.get("refused")
            return f"{prefix}{err}"
        txt = (result.get("text", "") if isinstance(result, dict) else str(result or ""))[:1500]
        return f"{prefix}{txt}"

    elif name == "run_financial_model":
        if isinstance(result, dict) and result.get("error"):
            compact = {"error": result["error"]}
        elif isinstance(result, dict):
            compact = {}
            if "mode" in result:
                compact["mode"] = result["mode"]
            elif isinstance(args, dict) and "mode" in args:
                compact["mode"] = args["mode"]
            else:
                compact["mode"] = "blend" if "blend" in result else "dcf"

            # Per-share values
            if "scenario_dcfs" in result and isinstance(result["scenario_dcfs"], list):
                scs = {}
                for sc in result["scenario_dcfs"]:
                    if isinstance(sc, dict):
                        sc_name = sc.get("name", "Scenario")
                        dcf = sc.get("dcf") or {}
                        iv = dcf.get("per_share_iv")
                        if iv is not None:
                            scs[sc_name] = iv
                if scs:
                    compact["scenarios"] = scs
            elif "scenarios" in result and isinstance(result["scenarios"], list):
                scs = {}
                for sc in result["scenarios"]:
                    if isinstance(sc, dict) and sc.get("iv") is not None:
                        scs[sc.get("name", "Scenario")] = sc.get("iv")
                if scs:
                    compact["scenarios"] = scs

            if "dcf_model" in result and isinstance(result["dcf_model"], dict):
                dcf = result["dcf_model"]
                if dcf.get("per_share_iv") is not None:
                    compact["per_share_iv"] = dcf.get("per_share_iv")

            b = result.get("blend") if isinstance(result.get("blend"), dict) else (result if result.get("mode") == "blend" else None)
            if b and isinstance(b, dict):
                b_iv = b.get("blended_per_share_iv") if b.get("blended_per_share_iv") is not None else b.get("per_share_iv")
                if b_iv is not None:
                    compact["blend_iv"] = b_iv

            if "reverse_dcf" in result and isinstance(result["reverse_dcf"], dict):
                rd = result["reverse_dcf"]
                rev_dict = {}
                if rd.get("implied_stage1_growth_pct") is not None:
                    rev_dict["implied_stage1_growth_pct"] = rd.get("implied_stage1_growth_pct")
                neutral = rd.get("neutral_reference_structure")
                if isinstance(neutral, dict) and neutral.get("implied_10y_cagr_pct") is not None:
                    rev_dict["neutral_10y_cagr_pct"] = neutral.get("implied_10y_cagr_pct")
                if rev_dict:
                    compact["reverse_dcf"] = rev_dict

            if "kelly_sizing" in result and isinstance(result["kelly_sizing"], dict):
                k = result["kelly_sizing"]
                k_dict = {}
                if k.get("quarter_kelly_pct") is not None:
                    k_dict["quarter_kelly_pct"] = k.get("quarter_kelly_pct")
                if k.get("recommendation") is not None:
                    k_dict["recommendation"] = k.get("recommendation")
                if k_dict:
                    compact["kelly"] = k_dict
        else:
            compact = {"raw": str(result)[:200]}

        json_str = json.dumps(compact, separators=(',', ':'))
        if len(json_str) > 1200:
            json_str = json_str[:1200]
        return f"[call {call_index}] model: {json_str}"

    return str(result)[:500]


def _compact_history(msgs, meta, budget_chars=36000):
    """Tool messages BEFORE the last assistant tool-call turn become their compact note.
    Latest round stays full. If total chars of all compact notes exceed budget_chars,
    shrink oldest search/page notes first to header-only until under budget. Model notes never shrunk.
    """
    last_asst_idx = -1
    for idx in range(len(msgs) - 1, -1, -1):
        if msgs[idx].get("role") == "assistant" and msgs[idx].get("tool_calls"):
            last_asst_idx = idx
            break

    compact_notes = {}
    for idx, m in enumerate(msgs):
        if m.get("role") == "tool" and last_asst_idx != -1 and idx < last_asst_idx:
            m_info = meta[idx] if meta and idx < len(meta) else None
            if isinstance(m_info, dict):
                name = m_info.get("name", "")
                args = m_info.get("args") or {}
                result = m_info.get("result")
                call_idx = m_info.get("call_index", idx)
            elif isinstance(m_info, (list, tuple)) and len(m_info) == 4:
                name, args, result, call_idx = m_info
            else:
                name, args, result, call_idx = "", {}, m.get("content", ""), idx
            compact_notes[idx] = compact_tool_note(name, args, result, call_idx)

    total_chars = sum(len(note) for note in compact_notes.values())
    if total_chars > budget_chars:
        # Shrink the OLDEST search/page notes first to header-only until under budget
        for idx in sorted(compact_notes.keys()):
            if total_chars <= budget_chars:
                break
            m_info = meta[idx] if meta and idx < len(meta) else None
            if isinstance(m_info, dict):
                name = m_info.get("name", "")
                args = m_info.get("args") or {}
                call_idx = m_info.get("call_index", idx)
            elif isinstance(m_info, (list, tuple)) and len(m_info) == 4:
                name, args, _, call_idx = m_info
            else:
                name, args, call_idx = "", {}, idx

            if name == "search_web":
                q = (args or {}).get("query", "")
                header_only = f'[call {call_idx}] search: "{q}" (results shown earlier)'
                diff = len(compact_notes[idx]) - len(header_only)
                if diff > 0:
                    compact_notes[idx] = header_only
                    total_chars -= diff
            elif name == "fetch_page":
                u = (args or {}).get("url", "")
                header_only = f'[call {call_idx}] page: {u} (read earlier)'
                diff = len(compact_notes[idx]) - len(header_only)
                if diff > 0:
                    compact_notes[idx] = header_only
                    total_chars -= diff

    active_msgs = []
    for idx, m in enumerate(msgs):
        if idx in compact_notes:
            new_m = dict(m)
            new_m["content"] = compact_notes[idx]
            active_msgs.append(new_m)
        else:
            active_msgs.append(m)
    return active_msgs


def extract_desk_run_value(args, result) -> float | None:
    """Extract one base per-share value from a run_financial_model call result.
    - single DCF -> its per_share_iv
    - batch scenarios -> scenario whose name contains "base" (case-insensitive), else median of scenarios' per_share_iv
    - blend mode and reverse-DCF-only calls are NOT valuations -> skipped (None)
    - errors skipped (None)
    """
    if not isinstance(result, dict) or result.get("error"):
        return None
    if isinstance(args, dict) and args.get("mode") == "blend":
        return None
    if result.get("mode") == "blend":
        return None

    # Batch scenarios
    scs = result.get("scenario_dcfs")
    if scs and isinstance(scs, list):
        base_iv = None
        all_ivs = []
        for item in scs:
            if isinstance(item, dict):
                name = str(item.get("name") or "")
                d = item.get("dcf") or {}
                iv = d.get("per_share_iv")
                if iv is not None:
                    try:
                        iv_f = float(iv)
                        all_ivs.append(iv_f)
                        if "base" in name.lower() and base_iv is None:
                            base_iv = iv_f
                    except (ValueError, TypeError):
                        pass
        if base_iv is not None:
            return base_iv
        if all_ivs:
            return float(statistics.median(all_ivs))

    raw_scs = result.get("scenarios")
    if raw_scs and isinstance(raw_scs, list):
        base_iv = None
        all_ivs = []
        for item in raw_scs:
            if isinstance(item, dict):
                name = str(item.get("name") or "")
                iv = item.get("iv")
                if iv is not None:
                    try:
                        iv_f = float(iv)
                        all_ivs.append(iv_f)
                        if "base" in name.lower() and base_iv is None:
                            base_iv = iv_f
                    except (ValueError, TypeError):
                        pass
        if base_iv is not None:
            return base_iv
        if all_ivs:
            return float(statistics.median(all_ivs))

    # Single DCF
    dcf = result.get("dcf_model")
    if isinstance(dcf, dict):
        iv = dcf.get("per_share_iv")
        if iv is not None:
            try:
                return float(iv)
            except (ValueError, TypeError):
                pass

    return None


def _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap):
    """Persist snapshot immediately so tool calls are recorded before execution."""
    try:
        p = Path(out_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "_research_snapshot.json").write_text(
            json.dumps({"model": model, "seed": seed, "tool_calls": calls,
                        "stub_rejected": stub_rejected,
                        "turns": turns,
                        "elapsed_s": round(time.time() - t0), "calls": snap}, indent=2),
            encoding="utf-8")
    except Exception:
        pass


def chat_with_tools(model, content, out_dir, think="high", ctx=65536, num_predict=49152,
                    seed=None, timeout=14400, verbose=True, draft_num_predict=None,
                    temperature=None, query_cache=None, url_cache=None,
                    tools=None, max_search_calls=25, max_model_calls=5):
    """Ollama chat with the search tools available. Returns (report, thinking, meta).

    Snapshots every tool call to out_dir/_research_snapshot.json so the run stays reproducible
    and auditable against exactly what the model saw.

    `query_cache`/`url_cache` (P4.0b): when given, these are the CALLER's dicts — e.g. a frozen
    evidence store shared by every sample of a dispersion-battery run — and are mutated in place,
    so the caller can persist them after this call returns. Omitted (the default), fresh empty
    dicts are used exactly as before this option existed: no behaviour change for every existing
    caller. `meta["evidence_hits"]`/`["evidence_misses"]` count how many search_web/fetch_page
    calls this turn resolved from THAT dict (hit) versus actually went to the network for (miss) —
    it is meaningful whether or not an external cache was supplied, since even the fresh per-call
    dict dedupes within a single sample's own tool calls.
    """
    msgs = [{"role": "user", "content": content}]
    meta_msgs = [None]
    snap, calls, turns = [], 0, []
    q_cache = query_cache if query_cache is not None else {}
    u_cache = url_cache if url_cache is not None else {}
    evidence_hits, evidence_misses = 0, 0
    opts = {
        "num_ctx": ctx,
        "num_predict": num_predict,
        "repeat_penalty": 1.05,
        "presence_penalty": 0.05
    }
    if seed is not None:
        opts["seed"] = seed
    if draft_num_predict is not None:
        opts["draft_num_predict"] = draft_num_predict
    if temperature is not None:
        opts["temperature"] = temperature
    t0 = time.time()
    final_report, final_think, done_reason = "", "", None
    stub_rejected = False
    gen_tokens = 0
    eval_duration_total = 0

    search_calls = 0
    model_calls = 0
    desk_validation_errors = 0
    eff_tools = TOOLS if tools is None else tools

    sample_search_queries = []
    sample_fetched_urls = set()
    research_calls = 0
    repeat_calls = 0
    desk_runs = []
    seen_result_urls = {}   # url -> title for every result search_web returned this run (fetch_page fallbacks)

    def _recover_cut_off_brief():
        """Discovery mode only (no desk). If the final turn hit num_predict before the
        json:catalysts block, ask once for the block alone with thinking off. MU 2026-09-24:
        the final turn spent all 16,384 tokens thinking and the whole run was lost as "no
        parseable brief". Valuation runs keep their own truncation path (continue_report)."""
        nonlocal final_report, final_think, done_reason, gen_tokens, eval_duration_total
        if max_model_calls > 0 or done_reason != "length" or "```json" in (final_report or ""):
            return
        if verbose:
            print("    [harness] final turn cut off at the length limit before the brief - asking "
                  "for the json:catalysts block alone", flush=True)
        msgs.append({"role": "assistant", "content": final_report or ""})
        meta_msgs.append(None)
        msgs.append({"role": "user", "content": (
            "Your answer was cut off by the length limit before the ```json:catalysts block. Do not "
            "deliberate further. Write ONLY the ```json:catalysts block now, exactly as specified in "
            "the first message, from the research above.")})
        meta_msgs.append(None)
        body = {"model": model, "stream": False, "think": False,
                "messages": _compact_history(msgs, meta_msgs),
                "options": dict(opts, num_predict=8192)}
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
        fm = resp.get("message") or {}
        final_report = ((final_report or "") + "\n\n" + (fm.get("content") or "")).strip()
        final_think += fm.get("thinking") or ""
        done_reason = resp.get("done_reason")
        gen_tokens += resp.get("eval_count") or 0
        eval_duration_total += resp.get("eval_duration") or 0
        turns.append({"turn": len(turns) + 1, **turn_metrics(resp), "length_recovery": True})

    while True:
        active_msgs = _compact_history(msgs, meta_msgs)

        # If search budget is exhausted, only expose financial modeling tool
        active_tools = eff_tools
        if search_calls >= max_search_calls:
            active_tools = [t for t in eff_tools if t["function"]["name"] == "run_financial_model"]
        if model_calls >= max_model_calls or desk_validation_errors > 6:
            active_tools = [t for t in active_tools if t["function"]["name"] != "run_financial_model"]

        body = {"model": model, "stream": False, "think": think, "messages": active_msgs,
                "options": opts}
        if active_tools and (search_calls < max_search_calls or (model_calls < max_model_calls and desk_validation_errors <= 6)):
            body["tools"] = active_tools

        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
        msg = resp.get("message") or {}
        done_reason = resp.get("done_reason")
        gen_tokens += resp.get("eval_count") or 0
        eval_duration_total += resp.get("eval_duration") or 0
        turns.append({"turn": len(turns) + 1, **turn_metrics(resp)})
        if msg.get("thinking"):
            final_think += msg["thinking"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            final_report = msg.get("content") or ""
            is_stub = not report_is_deliverable(final_report) if max_model_calls > 0 else not bool(_TOOL_CALL_BLOCK.sub("", final_report or "").strip())
            if is_stub:
                # BOTH live failure shapes land here, and the old test (`not content.strip()`)
                # only caught the first:
                #   ANET s2 / BFH s3 — reasoned to a stop and emitted NOTHING.
                #   GEV s1 2026-09-20 — emitted the tool-call envelope as plain content because
                #     Ollama did not parse it, so `tcs` was empty while `content` was not. The
                #     non-empty stub sailed through as the deliverable 29 minutes in.
                # Force report delivery turn without tools.
                stub_rejected = bool((final_report or "").strip())
                if verbose and stub_rejected:
                    print(f"    [harness] terminal turn was a {len(final_report)}-char stub, not a "
                          f"report — forcing the deliverable turn instead of accepting it",
                          flush=True)
                retry_prompt = (
                    "You have completed your research and reasoning. Write the complete "
                    "institutional memorandum and Section 12 machine contract NOW. Do not search again."
                    if max_model_calls > 0 else
                    "You have completed your research and reasoning. Provide your findings NOW, ending with the ```json:catalysts block exactly as specified. Do not search again."
                )
                msgs.append({"role": "user", "content": retry_prompt})
                meta_msgs.append(None)
                active_msgs_retry = _compact_history(msgs, meta_msgs)
                opts_retry = dict(opts)
                opts_retry["num_predict"] = 32768 if max_model_calls > 0 else opts.get("num_predict", 16384)
                body = {"model": model, "stream": False, "think": "low" if max_model_calls > 0 else think,
                        "messages": active_msgs_retry, "options": opts_retry}
                req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    resp = json.loads(r.read().decode())
                fm = resp.get("message") or {}
                final_report = fm.get("content") or ""
                final_think += fm.get("thinking") or ""
                done_reason = resp.get("done_reason")
                gen_tokens += resp.get("eval_count") or 0
                eval_duration_total += resp.get("eval_duration") or 0
                turns.append({"turn": len(turns) + 1, **turn_metrics(resp),
                              "forced_report": True})
            _recover_cut_off_brief()
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": tcs})
        meta_msgs.append(None)
        for tc in tcs:
            calls += 1
            fn = (tc.get("function") or {})
            name = fn.get("name")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            # P1.7: Append every dispatched call BEFORE it executes and persist immediately to disk
            call_rec = {
                "tool": name,
                "call_index": calls,
                "ts": time.strftime("%H:%M:%S"),
                "params": args,
            }
            snap.append(call_rec)
            _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)

            result = None
            try:
                if name in ("search_web", "fetch_page"):
                    research_calls += 1
                    if name == "search_web":
                        q = (args or {}).get("query", "")
                        if any(is_near_duplicate(q, prev_q, threshold=0.50) for prev_q in sample_search_queries):
                            repeat_calls += 1
                        sample_search_queries.append(q)
                    elif name == "fetch_page":
                        u = (args or {}).get("url", "")
                        if u in sample_fetched_urls:
                            repeat_calls += 1
                        sample_fetched_urls.add(u)

                    search_calls += 1
                    if search_calls > max_search_calls:
                        msg_text = (
                            f"Web search budget completed ({max_search_calls} calls). "
                            "Do not search again. Formulate your scenario drivers and invoke "
                            "run_financial_model to compute intrinsic values and Kelly sizing, "
                            "then proceed to write your memorandum."
                            if max_model_calls > 0 else
                            f"Web search budget completed ({max_search_calls} calls). "
                            "Do not search again. Conclude your research and provide your findings now, ending with the ```json:catalysts block exactly as specified."
                        )
                        result = {
                            "status": "search_quota_met",
                            "message": msg_text,
                        }
                    else:
                        result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache,
                                               known_urls=seen_result_urls)
                        if name == "search_web" and isinstance(result, dict):
                            for r in (result.get("results") or []):
                                if isinstance(r, dict) and r.get("url"):
                                    seen_result_urls.setdefault(r["url"], r.get("title") or "")
                elif name == "run_financial_model":
                    if model_calls >= max_model_calls or desk_validation_errors > 6:
                        result = {"error": f"financial model call budget exhausted ({max_model_calls}); "
                                           f"use computed results and finalize memorandum"}
                    else:
                        result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache)
                        if isinstance(result, dict) and result.get("validation_error") is True:
                            desk_validation_errors += 1
                            if desk_validation_errors > 6:
                                result = {"error": f"financial model call budget exhausted ({max_model_calls}); "
                                                   f"use computed results and finalize memorandum"}
                        else:
                            model_calls += 1
                else:
                    result = {"error": f"unknown tool {name}"}
            except Exception as e:
                call_rec["error"] = f"dispatch error: {type(e).__name__}: {str(e)[:120]}"
                _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)
                raise
            else:
                if name in ("search_web", "fetch_page") and isinstance(result, dict) \
                        and "cache_hit" in result:
                    if result["cache_hit"]:
                        evidence_hits += 1
                    else:
                        evidence_misses += 1
                if name == "run_financial_model":
                    dv = extract_desk_run_value(args, result)
                    if dv is not None:
                        desk_runs.append(dv)
                    if isinstance(result, dict) and "result" in result:
                        call_rec.update(result)
                    elif isinstance(result, dict):
                        call_rec.update(result)
                    elif result is not None:
                        call_rec["result"] = result
                elif isinstance(result, dict):
                    call_rec.update(result)
                elif result is not None:
                    call_rec["result"] = result
                _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)

            if verbose:
                q = args.get("query") or args.get("url") or (f"price={args.get('price')}" if name == 'run_financial_model' else "")
                print(f"    [tool {calls}] {name}: {str(q)[:88]}", flush=True)
            msgs.append({"role": "tool", "content": json.dumps(result)[:12000]})
            meta_msgs.append({"name": name, "args": args, "result": result, "call_index": calls})

        if search_calls >= max_search_calls and (model_calls >= max_model_calls or desk_validation_errors > 6):
            # ALL BUDGETS REACHED -> force the answer, never just break.
            exhausted_prompt = (
                "Tool budgets are exhausted. Write the complete institutional memorandum "
                "and Section 12 machine contract NOW from what you have. Do not search again."
                if max_model_calls > 0 else
                "Tool budgets are exhausted. Conclude your research and provide your findings NOW from what you have, ending with the ```json:catalysts block exactly as specified. Do not search again."
            )
            msgs.append({"role": "user", "content": exhausted_prompt})
            meta_msgs.append(None)
            active_msgs_exhausted = _compact_history(msgs, meta_msgs)
            body = {"model": model, "stream": False, "think": think, "messages": active_msgs_exhausted,
                    "options": opts}
            req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode())
            fm = resp.get("message") or {}
            final_report = fm.get("content") or ""
            final_think += fm.get("thinking") or ""
            done_reason = resp.get("done_reason")
            gen_tokens += resp.get("eval_count") or 0
            eval_duration_total += resp.get("eval_duration") or 0
            turns.append({"turn": len(turns) + 1, **turn_metrics(resp),
                          "budget_exhausted": True})
            _recover_cut_off_brief()
            break

    _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)
    eval_rate = round(gen_tokens / (eval_duration_total / 1e9), 2) if eval_duration_total > 0 else 0
    return final_report, final_think, {"tool_calls": calls, "done_reason": done_reason,
                                       "stub_rejected": stub_rejected,
                                       "turns": turns,
                                       "generated_tokens": gen_tokens,
                                       "eval_duration_s": round(eval_duration_total / 1e9, 2),
                                       "eval_rate": eval_rate,
                                       "evidence_hits": evidence_hits,
                                       "evidence_misses": evidence_misses,
                                       "research_calls": research_calls,
                                       "repeat_calls": repeat_calls,
                                       "desk_runs": desk_runs,
                                       "desk_validation_errors": desk_validation_errors,
                                       "elapsed_s": round(time.time() - t0)}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    q = " ".join(sys.argv[1:]) or "Alphabet 2027 capital expenditure guidance"
    r = search_web(q, "smoke test")
    print(f"query: {r['query']} | results: {r['n_results']} | refetch_warning={r.get('refetch_warning')}")
    for x in r["results"][:4]:
        print(f"  - {x['title'][:80]}\n    {x['url'][:100]}\n    {x['snippet'][:150]}")
