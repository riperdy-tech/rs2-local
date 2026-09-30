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
import math
import re
import ssl
import statistics
import sys
import time
import urllib.error
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

DESK_BUDGET = "{used} of {cap} desk runs used; {refused} refused calls (the 7th refused call closes the desk)"
DESK_CLOSED_RUNS = ("The desk is now closed: all {cap} desk runs are used, so run_financial_model is no longer "
                    "offered. These are your final desk results; report them. Research tools stay open; write the "
                    "memorandum when your research is done.")
DESK_CLOSED_REJECTED = ("The desk is now closed after {n} rejected calls, so run_financial_model is no longer "
                        "offered. Your last valid desk results stand; report them. Research tools stay open; write "
                        "the memorandum when your research is done.")
# Revision 17, briefs C6 and C6b: the loop guard. A refusal that names a reason one of the last two refusals named,
# with the inputs changed since that refusal, means the model is walking an input across rules (UGI's loop alternated
# two reasons, which a comparison with the refusal just before cannot see); the refusal says so.
DESK_LOOP_GUARD = "Changing inputs has not cleared {rules}. Give the reasons named above with the inputs you have."
DESK_CLOSED_LINE = ("The desk is closed: run_financial_model is no longer offered, and your last desk results stand. "
                    "Write the memorandum when your research is done.")
PART_CHARS = 9000
PDF_REFUSAL = ("this address is a PDF document; fetch_page reads web pages and text only. Search for the same document "
               "as a web page (for a filing, its sec.gov HTML version).")

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
            "Read them before searching; do not repeat a search you have already run. Fetching a page again gives its next unread part."),
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
        "description": (
            "Retrieve the readable text of one URL returned by search_web, when the snippet is not enough. "
            "Prefer primary sources: company IR pages, earnings-call transcripts, regulators, central banks. "
            "A page is served in parts of 9,000 characters; the result says which part you have and how many "
            "there are. Call again with the same url for the next part you have not read, or pass part to choose "
            "one. Pass find to get the passages of the whole page that contain a word or phrase."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "part": {"type": "integer", "description": "Optional. The 9,000-character part to read; 1 is the start of the page."},
                "find": {"type": "string", "description": "Optional. A word or phrase of 3 to 100 characters; returns up to 5 passages of the whole page that contain it, each marked with its part. When given, part is ignored."},
            },
            "required": ["url"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "run_financial_model",
        "description": (
            "Run the Python desk. One call values Base, Bull and Bear together: each scenario's base_cf, "
            "five years of cash-flow growth, fade, discount rate and terminal growth (with an optional "
            "terminal_ronic) give its per-share value. The desk also returns the reverse DCF (the growth today's "
            "price implies, under your structure and under the neutral reference) and quarter-Kelly sizing. "
            "The harness supplies today's price, the pack's share count, the anchors and the base-rate table; "
            "pass only your decisions. An input that departs from its DEFAULT needs its reason argument: the "
            "desk names any that are missing, and a refused call does not use one of your desk runs. The desk "
            "holds Base years 3-5 at next-FY consensus revenue growth unless guidance_deviation_reason is "
            "given, and shows the value on your path beside it. It holds the Base's years 1-2 at the DEFAULTS "
            "cash-flow levels the same way (a Base year 2 more than 5% away). It deducts the DEFAULTS working "
            "capital in years 1-5 (not when base_cf is within 2% of cash_basis_b) and pays for growth from year 6 "
            "at terminal_ronic. It values at the base fiscal year end and rolls the value forward to today. "
            "The firm frame uses the same long run, an approximation: the return on new investment is measured on "
            "tangible invested capital before interest and applied to equity earnings, which is conservative "
            "for a levered company. Base is every scenario not named Bull or Bear. "
            "Blend mode combines named desk legs for display; it is never your answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["dcf", "blend"], "description": "Calculation mode: 'dcf' (default) or 'blend'."},
                "valuation_frame": {
                    "type": "string",
                    "enum": ["equity", "firm"],
                    "description": "'equity' (the default) discounts the pack's after-interest flows at the cost of equity; nonzero net_debt is refused. 'firm' discounts a pre-interest flow at a WACC and needs interest_addback, wacc_reason and net debt (default: the DEFAULTS net debt)."
                },
                "rate_type": {
                    "type": "string",
                    "enum": ["cost_of_equity", "true_wacc", "cost_of_equity_proxy"],
                    "description": "Semantic discount rate type. Must match valuation_frame (equity -> cost_of_equity; firm -> true_wacc)."
                },
                "cash_flow_life": {
                    # one JSON type: a list-valued "type" is untested with the Ollama tool parser on
                    # this box; the desk accepts "perpetual", a digit string or an integer alike
                    "type": "string",
                    "description": "Required. \"perpetual\", or the whole number of years (1-60) until the cash flows end: filed reserves over current production, or the remaining licence, concession or patent term. It applies to every scenario; a finite life values the flows over that life with no end value."
                },
                "cash_flow_life_reason": {
                    "type": "string",
                    "description": "Required. One dated sentence: for a finite life, the filed reserves and production rate or the remaining term; where revenue follows a commodity price, the price deck your flows assume and its source."
                },
                "base_cf_reason": {
                    "type": "string",
                    "description": "Why a Base base_cf more than 2% from the DEFAULTS owner earnings is more representative, with the filing behind it."
                },
                "guidance_deviation_reason": {
                    "type": "string",
                    "description": "Dated evidence for a Base that departs from consensus: a year-2 cash flow more than 5% from the DEFAULTS year-2 level (without it the desk holds years 1-2 at the DEFAULTS levels), a Base value outside 0.75-1.33 of the reference, or Base years 3-5 above next-FY revenue growth (without it the desk holds those years at that growth)."
                },
                "scenario_deviation_reason": {
                    "type": "string",
                    "description": "Why a Bull or Bear year-2 cash flow is more than 15% from the DEFAULTS bull2 or bear2 level."
                },
                "terminal_reason": {
                    "type": "string",
                    "description": "Dated evidence for a Base terminal_g more than 0.5 points from the DEFAULTS terminal-growth default, or for a Base terminal_ronic more than 2 points from the DEFAULTS terminal_ronic."
                },
                "coe_adjustment_reason": {
                    "type": "string",
                    "description": "Why the Base discount rate is more than 1.5 points from the COE ANCHOR."
                },
                "shares_reason": {
                    "type": "string",
                    "description": "The instrument and its vesting condition, when any scenario's shares_diluted differs from the pack's count by more than 1%. Add contingent shares only in the scenarios where they vest."
                },
                "net_debt_reason": {
                    "type": "string",
                    "description": "Firm frame: why net_debt differs from the DEFAULTS net debt."
                },
                "wacc_reason": {
                    "type": "string",
                    "description": "Firm frame, required: the COE ANCHOR, the cost of debt (filed interest over debt), the tax rate and the weights behind the WACC."
                },
                "interest_addback": {
                    "type": "number",
                    "description": "Firm frame, required: the after-tax interest expense in $B that makes the flow pre-interest. base_cf already includes it."
                },
                "bull_below_price_reason": {
                    "type": "string",
                    "description": "When the Bull value is below today's price: the assumption of the market-implied path you reject, with dated evidence; when Bull is also below the lowest analyst target, what every analyst is missing."
                },
                "bear_above_price_reason": {
                    "type": "string",
                    "description": "When the Bear value is above today's price: why even the downside case is worth more than the price, with dated evidence."
                },
                "explicit_growth": {
                    "type": "array",
                    "description": "Annual growth of base_cf - the owner cash flow being valued - for each of years 1-5 (e.g. [0.12, 0.10, 0.08, 0.06, 0.05]). Not revenue growth: revenue growth leaves out margin change. Years 1-2 normally follow consensus EPS growth (DATA 8). Base years 3-5 above next-FY consensus revenue growth are held at it unless guidance_deviation_reason is given.",
                    "items": {"type": "number"}
                },
                "growth_rates": {
                    "type": "array",
                    "description": "Alias for explicit_growth.",
                    "items": {"type": "number"}
                },
                "fade_years": {
                    "type": "integer",
                    "description": "Duration of Stage 2 linear fade in years (integer >= 0). Fades linearly from the last explicit rate to terminal_g; the return on new investment and a cyclical margin move to their long-run values over the same years."
                },
                "terminal_g": {
                    "type": "number",
                    "description": "REQUIRED for DCF. Long-term nominal terminal growth rate as decimal (e.g. 0.025 for 2.5%, 0.035 for 3.5%). The silent default was removed in Phase 4; calls without it are refused."
                },
                "terminal_ronic": {"type": "number", "description": "The return on new investment (a fraction, e.g. 0.12) that pays for growth from year 6 and in the terminal value. Default: the DEFAULTS terminal_ronic. A Base value more than 2 points from it needs terminal_reason."},
                "sbc_treatment": {
                    "type": "string",
                    "enum": ["deducted_in_cf", "add_back_dilution"],
                    "description": "SBC policy declaration. If 'deducted_in_cf', sbc_dilution may NOT also be passed (double deduction refused)."
                },
                "sbc_dilution": {
                    "type": "number",
                    "description": "Share dilution from SBC when sbc_treatment is 'add_back_dilution': a fraction below 1 (0.02 = 2%) or a whole number of new shares. Must NOT be passed if sbc_treatment is 'deducted_in_cf'."
                },
                "base_cf": {"type": "number", "description": "Base owner cash flow / FCF (in $B or per-share, matching units)."},
                "wacc": {"type": "number", "description": "Cost of capital / discount rate as decimal, e.g. 0.085 for 8.5%."},
                "annuity_flow": {"type": "number", "description": "Separate annual services / installed-base recurring annuity cash flow (if unbundled)."},
                "annuity_cap_rate": {"type": "number", "description": "Capitalization rate for annuity flow (e.g. 0.075 for 7.5%)."},
                "net_debt": {"type": "number", "description": "Firm frame only, in $B; default: the DEFAULTS net debt. Must be 0 or omitted in the equity frame."},
                "shares_diluted": {"type": "number", "description": "Optional. The desk uses the DEFAULTS block's shares_default when you leave it out. shares_default is a whole share count, for example 79,364,362; billions are also accepted. Pass it only for a different count, with shares_reason."},
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
                        "Exactly three entries, one each with role Base, Bull and Bear. Each entry: name, prob, "
                        "base_cf ($B), explicit_growth (5 annual growth rates of base_cf, cash flow not revenue), "
                        "fade_years, wacc (the discount rate), terminal_g, and optionally terminal_ronic "
                        "and shares_diluted. The desk computes every value, the reverse DCF and Kelly "
                        "sizing in one call."
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
                            "terminal_ronic": {"type": "number", "description": "Return on new investment for this scenario, as a fraction. Default: the DEFAULTS terminal_ronic."},
                            "shares_diluted": {"type": "number", "description": "Only for a contingent instrument that vests in this scenario, as a whole share count, for example 79,364,362; billions are also accepted. Needs shares_reason."}
                        },
                        "required": ["name", "prob"]
                    }
                }
            },
            "required": ["cash_flow_life", "cash_flow_life_reason", "terminal_g", "fade_years", "sbc_treatment"]
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


_TITLE_STOP = set("the and for its has have had are was were with from that this into over after than "
                  "amid will would could may might not but new says said stock stocks shares news why "
                  "how what today report reports inc corp com".split())


def _host(u):
    h = (urllib.parse.urlparse(u or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _title_tokens(t):
    """Content words of a headline, lightly stemmed so "signs"/"signed" and "deals"/"deal" match."""
    words = {w for w in re.findall(r"[a-z0-9]+", (t or "").lower().replace("'s", ""))
             if len(w) >= 3 and w not in _TITLE_STOP and not w.isdigit()}
    return {re.sub(r"(ing|ed|es|s)$", "", w) if len(w) > 4 else w for w in words}


def related_to_query(query, result):
    q = _title_tokens(query)
    if not q:
        return None          # a query with no content word cannot be judged
    return bool(q & _title_tokens(" ".join([result.get("title") or "", result.get("snippet") or "",
                                            result.get("url") or ""])))


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

    audit_results = []
    served = []
    set_aside_items = []
    has_content = bool(_title_tokens(query))

    for res in (data.get("results") or []):
        u = res.get("url") or ""
        item = {
            "title": (res.get("title") or "")[:180],
            "url": u,
            "snippet": re.sub(r"\s+", " ", res.get("content") or "")[:420],
        }
        is_low_trust = any(bad in u for bad in LOW_TRUST)
        if is_low_trust:
            audit_entry = {
                "title": item["title"],
                "url": item["url"],
                "snippet": item["snippet"],
                "engines": res.get("engines"),
                "publishedDate": res.get("publishedDate"),
                "low_trust": True,
                "related": None,
                "served": False,
            }
            audit_results.append(audit_entry)
            continue

        if not has_content:
            rel = None
            is_served = len(served) < n
            if is_served:
                served.append(item)
        else:
            rel = related_to_query(query, item)
            if rel:
                is_served = len(served) < n
                if is_served:
                    served.append(item)
            else:
                is_served = False
                set_aside_items.append(item)

        audit_entry = {
            "title": item["title"],
            "url": item["url"],
            "snippet": item["snippet"],
            "engines": res.get("engines"),
            "publishedDate": res.get("publishedDate"),
            "low_trust": False,
            "related": rel,
            "served": is_served,
        }
        audit_results.append(audit_entry)

    rec = {
        "query": query,
        "why": why,
        "n_results": len(served),
        "results": served,
    }
    if set_aside_items:
        distinct_hosts = []
        for it in set_aside_items:
            h = _host(it.get("url"))
            if h and h not in distinct_hosts:
                distinct_hosts.append(h)
        sa = {
            "count": len(set_aside_items),
            "hosts": distinct_hosts[:8],
        }
        m = len(distinct_hosts) - 8
        if m > 0:
            sa["more_hosts"] = m
        sa["reason"] = "no word in common with your query"
        rec["set_aside"] = sa

    rec["refetch_warning"] = looks_like_refetch(query)
    rec["cache_hit"] = False
    rec["_audit_results"] = audit_results
    rec["_audit_unresponsive_engines"] = data.get("unresponsive_engines")

    if query_cache is not None:
        query_cache[query] = served
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
def _publisher(h):
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov"):
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else h


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


STRONG_PAYWALL_MARKERS = ("active subscription", "subscribe now", "subscription(s)", "log in to read",
                          "sign in to read", "subscribers only", "this content is for subscribers")


def _looks_paywalled(text):
    """A short page with paywall wording, or any page whose opening is a subscription wall (a
    long page can still be one: The Hindu's copy of the Muse story, 2026-09-25)."""
    t = (text or "")
    low = t.lower()
    return ((len(t) < 2500 and any(m in low for m in PAYWALL_MARKERS))
            or any(m in low[:2000] for m in STRONG_PAYWALL_MARKERS))


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


def part_note(k, n, chars, cap=PART_CHARS):
    a = (k - 1) * cap + 1
    b = k * cap
    N = chars
    if k < n:
        return f"part {k} of {n}: characters {a:,}-{b:,} of {N:,}. Call fetch_page again with this url for the next part, or pass part or find."
    if k == n and n > 1:
        return f"part {n} of {n}: characters {a:,}-{N:,} of {N:,}, the end of the page."
    return ""


def page_part(rec, k, cap=PART_CHARS):
    """Serve part k (1-indexed) of a page."""
    url = rec.get("url") or ""
    chars = rec.get("chars")
    if chars is None:
        chars = len(rec.get("full_text") or rec.get("text") or "")
    n = max(1, math.ceil(chars / cap))
    if not (1 <= k <= n):
        return {"url": url, "error": f"this page has {n} parts; part {k} does not exist."}
    if k > 1 and "full_text" not in rec:
        return {"url": url, "error": "only part 1 of this page is stored; the rest is not available."}
    full_text = rec.get("full_text") if "full_text" in rec else rec.get("text", "")
    chunk = full_text[(k - 1) * cap : k * cap]
    out = {
        "url": url,
        "part": k,
        "parts": n,
    }
    if n > 1:
        out["part_note"] = part_note(k, n, chars, cap)
    out["chars"] = chars
    out["text"] = chunk
    return out


def find_in_page(rec, phrase, cap=PART_CHARS, window=400, max_passages=5):
    url = rec.get("url") or ""
    phrase = (phrase or "").strip()
    if len(phrase) < 3 or len(phrase) > 100:
        return {"url": url, "error": "find needs 3 to 100 characters."}

    has_full = "full_text" in rec and rec["full_text"] is not None
    text = rec["full_text"] if has_full else (rec.get("text") or "")
    chars = rec.get("chars")
    if chars is None:
        chars = len(text)
    searched_note = None if has_full else "part 1 only (the rest is not stored)"

    needle = phrase.lower()
    haystack = text.lower()
    matches = []
    idx = 0
    while True:
        pos = haystack.find(needle, idx)
        if pos == -1:
            break
        matches.append((pos, pos + len(needle)))
        idx = pos + len(needle)

    m = len(matches)
    if m == 0:
        out = {
            "url": url,
            "find": phrase,
            "matches": 0,
            "note": f'No passage of this page ({chars:,} characters) contains "{phrase}".',
        }
        if searched_note:
            out["searched"] = searched_note
        return out

    passages = []
    for start, end in matches:
        span_start = max(0, start - window)
        span_end = min(len(text), end + window)
        if passages and start <= passages[-1]["span_end"]:
            passages[-1]["span_end"] = max(passages[-1]["span_end"], span_end)
        else:
            if len(passages) >= max_passages:
                continue
            passages.append({
                "span_start": span_start,
                "span_end": span_end,
                "first_match_start": start,
            })

    formatted_passages = [
        f"[part {p['first_match_start'] // cap + 1}] {text[p['span_start']:p['span_end']]}"
        for p in passages
    ]
    joined = "\n\n".join(formatted_passages)

    out = {
        "url": url,
        "find": phrase,
        "matches": m,
        "chars": chars,
        "text": joined,
    }
    if searched_note:
        out["searched"] = searched_note
    return out


def _parse_part(raw_part):
    """Parse part argument. Returns (part_int, None) on success, or (None, error_str) on invalid."""
    if raw_part is None:
        return None, None
    if isinstance(raw_part, bool):
        return None, "part must be a whole number from 1."
    if isinstance(raw_part, int):
        if raw_part >= 1:
            return raw_part, None
        return None, "part must be a whole number from 1."
    if isinstance(raw_part, float):
        if raw_part.is_integer() and int(raw_part) >= 1:
            return int(raw_part), None
        return None, "part must be a whole number from 1."
    if isinstance(raw_part, str):
        s = raw_part.strip()
        if s.isdigit() and int(s) >= 1:
            return int(s), None
        return None, "part must be a whole number from 1."
    return None, "part must be a whole number from 1."


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
    # E16: '…' means the address was shortened or masked where the model saw it (UGI (b) s1 retried
    # a masked signed link five times against an "'ascii' codec" error); other non-ASCII characters
    # are percent-encoded so the request can be made at all.
    if any(ord(ch) > 127 for ch in url):
        if "…" in url:
            if snap is not None:
                snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"), "url": url,
                             "chars": 0, "text": "", "cached": False, "refused": "shortened or masked URL"})
            return {"url": url, "error": "refused: this address contains '…', so it was shortened or masked "
                                         "where you saw it and cannot be fetched. Use a full address copied "
                                         "exactly from a search result."}
        url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    if url_cache is not None and url in url_cache:
        # A cache HIT still means the model was served this page, so it belongs in the audit trail.
        # Returning here without appending under-recorded GEV sample 1 by 6 of its 28 tool calls —
        # the repeats were re-fetches of the same SEC and GEV URLs, and the module's rule is that
        # EVERY fetched page is written into the run directory.
        rec = url_cache[url]
        chars = rec.get("chars")
        if chars is None:
            chars = len(rec.get("full_text") or rec.get("text") or "")
        n = max(1, math.ceil(chars / cap))
        ret = {
            "url": rec.get("url") or url,
            "part": 1,
            "parts": n,
        }
        if n > 1:
            ret["part_note"] = part_note(1, n, chars, cap)
        ret["chars"] = chars
        ret["text"] = (rec.get("full_text") or rec.get("text") or "")[:cap]
        ret["cache_hit"] = True
        if snap is not None:
            snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"),
                         "cached": True, **ret})
        return ret
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    is_sec = host == "sec.gov" or host.endswith(".sec.gov")
    try:
        req = urllib.request.Request(url, headers=SEC_UA if is_sec else UA)
        with urllib.request.urlopen(req, timeout=40, context=_SSL_CTX) as r:
            data = r.read(1_500_000)
            headers = getattr(r, "headers", None)
            ctype = (headers.get("Content-Type") or "") if headers else ""
            if "application/pdf" in ctype.lower() or (isinstance(data, bytes) and data[:5] == b"%PDF-") or (isinstance(data, str) and data[:5] == "%PDF-"):
                if snap is not None:
                    snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"), "url": url,
                                 "chars": 0, "text": "", "cached": False,
                                 "error": PDF_REFUSAL})
                return {"url": url, "error": PDF_REFUSAL}
            raw = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
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
    rec = {"url": url, "chars": len(txt), "text": txt[:cap], "full_text": txt}
    if url_cache is not None:
        url_cache[url] = rec
    n = max(1, math.ceil(len(txt) / cap))
    ret = {
        "url": url,
        "part": 1,
        "parts": n,
    }
    if n > 1:
        ret["part_note"] = part_note(1, n, len(txt), cap)
    ret["chars"] = len(txt)
    ret["text"] = txt[:cap]
    ret["cache_hit"] = False
    if snap is not None:
        snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"),
                     "cached": False, **ret})
    return ret


def desk_loop_guard(result, call_key, window):
    """Revision 17, briefs C6 and C6b. `result` is a desk refusal, `call_key` the call's inputs as sent and `window`
    the (reason set, call_key) of the last two tracked refusals, or None. Returns (result, the window with this
    refusal added): when one of this refusal's reasons was named by a refusal in the window and the inputs differ
    from the latest such refusal's, the error gains DESK_LOOP_GUARD, naming the reasons of the whole window (sorted,
    joined with ", " and a final " and "). A refusal with no reasons (a missing input, the order rule) is not
    tracked and clears the window; so does an accepted call, in the analyst loop."""
    reasons = frozenset(n.get("reason") for n in (result.get("needs_reasons") or []) if isinstance(n, dict))
    if not reasons:
        return result, None
    window = tuple(window or ())
    sharing = [h for h in window if h[0] & reasons]
    if sharing and sharing[-1][1] != call_key:
        named = sorted(set().union(*(h[0] for h in window)))
        rules = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
        result = dict(result, error=f"{result['error']} {DESK_LOOP_GUARD.format(rules=rules)}")
    return result, (window + ((reasons, call_key),))[-2:]


def dispatch_tool(name, args, snap=None, query_cache=None, url_cache=None, known_urls=None, desk_context=None):
    """Unified dispatcher for all analyst tools."""
    if name == "search_web":
        return search_web(args.get("query", ""), args.get("why", ""), snap, query_cache=query_cache)
    elif name == "fetch_page":
        return fetch_page(args.get("url", ""), snap, url_cache=url_cache, known_urls=known_urls)
    elif name == "run_financial_model":
        import financial_model_tool as fmt
        res = fmt.execute_financial_model(args, context=desk_context)
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


# Operator ruling 2026-09-27: reduced thinking is not a result. The retry fires on done_reason == "length",
# which at the 98,304 window is usually the 65,536-token output cap, not the window. If a turn runs out of
# room deliberating before any tool call and with no desk result, give one full-thinking retry with normal
# options and tools rather than a desk-only low-effort turn.
WINDOW_RETRY_PROMPT = (
    "Your previous turn ran out of room deliberating before any tool call, and that reasoning is "
    "lost. Do not compute values in your reasoning: run_financial_model does the arithmetic. Call it "
    "now with Base, Bull and Bear as the TASK sets them. This first call is a starting point, not "
    "your answer: research what the TASK asks, then re-run the desk, listing each change in 'Model "
    "revisions' with the evidence that moved it.")
# Revision 17, brief C8: the desk continuation. A terminal turn (no tool call) while no desk run has covered Base, Bull
# and Bear and the desk is still open gets one more turn, on the desk alone, instead of a memorandum that cannot
# publish anything. Not the desk-only recovery removed on 2026-09-27: that one ran at reduced thinking on the printed
# defaults; this one runs at the configured think level and asks for the scenarios the analysis argues for.
DESK_CONTINUATION = (
    "{lead} no desk-backed value: {cause}. Code takes every published value from your last complete desk run of "
    "Bear, Base and Bull; without one, nothing is published. Call run_financial_model now with the Bear, Base and "
    "Bull your analysis argues for; only run_financial_model is open now, and you have {left} of {cap} desk runs "
    "left. When the desk has returned a complete run, write the complete memorandum, SECTION 0 to SECTION 12, with "
    "SECTION 0, SECTION 4 and SECTION 12 taken from that run.")
DESK_CONTINUATION_LEAD = {"memorandum": "Your memorandum has",
                          "no_memorandum": "Your turn ended without the memorandum, and there is"}
DESK_CONTINUATION_CAUSE = {"no_desk_call": "you have made no run_financial_model call",
                           "no_complete_run": "none of your run_financial_model calls returned a complete run of "
                                              "Bear, Base and Bull"}
DESK_ONLY_OPEN = "Only run_financial_model is open now."


def desk_run_is_complete(calls):
    """Revision 17, brief C8: a complete desk run is exactly contract_fill's rule, with its own functions. Over the
    session's run_financial_model calls (snapshot records: the tool, its params and the result's keys), the union of
    `entries(call)` roles over the calls where `completed(call)` holds covers base, bull and bear."""
    import contract_fill        # not at module level: contract_fill -> fiduciary_gate -> capability_test -> analyst_tools
    roles = set()
    for c in calls:
        if isinstance(c, dict) and c.get("tool") == "run_financial_model" and contract_fill.completed(c):
            roles |= {e["role"] for e in contract_fill.entries(c)}
    return {"base", "bull", "bear"} <= roles


def desk_continuation_cause(calls, model_calls, desk_validation_errors, max_model_calls):
    """Revision 17, brief C8. None when the desk continuation must not fire on the state of the desk: discovery mode
    (max_model_calls 0), the desk closed (all runs used, or more than 6 refusals), or a complete desk run in `calls`.
    Otherwise "no_desk_call" (the session made no run_financial_model call) or "no_complete_run" (it made some, and
    none covered Base, Bull and Bear)."""
    if max_model_calls <= 0 or model_calls >= max_model_calls or desk_validation_errors > 6:
        return None
    if desk_run_is_complete(calls):
        return None
    made = any(isinstance(c, dict) and c.get("tool") == "run_financial_model" for c in calls)
    return "no_complete_run" if made else "no_desk_call"


# UGI s3 and LAMR s1 wrote essays of up to 30,523 characters into sector_multiple_band.metric. The
# arguments stayed in every later prompt, and the desk echoed them into every scenario, which
# pushed Bear past the 12,000-character cut of the tool message in 3 of 85 desk calls.
ARG_MAX_CHARS = 300
TOOL_MESSAGE_MAX_CHARS = 12000
# Narrow report-room rule: older page notes shrink to headers, oldest first, only when the next
# prompt would leave less than this many tokens of the window. Search and desk notes stay: they
# are the evidence the report cites. The largest full-thinking report turn in batch (b) generated
# 39,031 tokens (FSM s2); forced reports now run at full thinking too.
# 42,000 + the 2,048-token edge margin of F2, so the report keeps the same guaranteed room
REPORT_ROOM_TOKENS = 44048


def truncate_long_strings(obj, limit=ARG_MAX_CHARS, path=""):
    """(copy of obj, [{field, original_length}]) with every string longer than `limit` cut to it.
    Applied to desk arguments before dispatch; numbers are untouched."""
    cuts = []
    if isinstance(obj, str):
        if len(obj) > limit:
            cuts.append({"field": path or "(value)", "original_length": len(obj)})
            return obj[:limit], cuts
        return obj, cuts
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k], c = truncate_long_strings(v, limit, f"{path}.{k}" if path else str(k))
            cuts += c
        return out, cuts
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj):
            nv, c = truncate_long_strings(v, limit, f"{path}[{i}]")
            out.append(nv)
            cuts += c
        return out, cuts
    return obj, cuts


def _shorten_strings(obj, limit=ARG_MAX_CHARS):
    if isinstance(obj, str):
        return obj if len(obj) <= limit else f"{obj[:limit]} [{len(obj) - limit} characters omitted]"
    if isinstance(obj, dict):
        return {k: _shorten_strings(v, limit) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shorten_strings(v, limit) for v in obj]
    return obj


def _shorten_tool_calls(tool_calls, limit=ARG_MAX_CHARS):
    """A copy of an assistant turn's tool_calls with long string arguments shortened for the
    prompt; the stored history keeps what the model wrote."""
    out = []
    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            out.append(tc)
            continue
        fn = dict(tc.get("function") or {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                fn["arguments"] = json.dumps(_shorten_strings(json.loads(args), limit))
            except Exception:
                fn["arguments"] = _shorten_strings(args, limit)
        elif isinstance(args, (dict, list)):
            fn["arguments"] = _shorten_strings(args, limit)
        out.append(dict(tc, function=fn))
    return out


def _desk_summary(args, result):
    """The numbers a desk call exists to produce, per scenario, then reverse DCF and Kelly."""
    out = {}
    if isinstance(result, dict):
        if "desk_budget" in result:
            out["desk_budget"] = result["desk_budget"]
        if "desk_closed" in result:
            out["desk_closed"] = result["desk_closed"]
    sc_args = [x for x in ((args or {}).get("scenarios") or []) if isinstance(x, dict)]
    # S3 3.7: this read "probability", which no scenario carries (the field is "prob"), so the
    # summary never showed one before.
    probs = {x.get("name"): x.get("prob") for x in sc_args}
    rows = []
    items = result.get("scenario_dcfs") if isinstance(result.get("scenario_dcfs"), list) else None
    if items is None and isinstance(result.get("dcf_model"), dict):
        items = [{"name": "Base", "dcf": result["dcf_model"]}]
    for sc in items or []:
        if not isinstance(sc, dict):
            continue
        d = sc.get("dcf") or {}
        row = {"name": sc.get("name"), "probability": probs.get(sc.get("name")),
               "per_share_iv": d.get("per_share_iv"),
               "terminal_method": d.get("terminal_method")}
        rows.append({k: v for k, v in row.items() if v is not None})
    if rows:
        out["scenarios"] = rows
    rd = result.get("reverse_dcf")
    if isinstance(rd, dict):
        neutral = rd.get("neutral_reference_structure") or {}
        out["reverse_dcf"] = {k: v for k, v in {
            "implied_growth_next_5y_pct": rd.get("implied_growth_next_5y_pct"),
            "neutral_10y_cagr_pct": neutral.get("implied_10y_cagr_pct") if isinstance(neutral, dict) else None,
            "expectations_gap_pts": rd.get("expectations_gap_pts")}.items() if v is not None}
    k = result.get("kelly_sizing")
    if isinstance(k, dict):
        out["kelly"] = {kk: k.get(kk) for kk in ("expected_iv", "expected_return_pct",
                                                 "quarter_kelly_pct", "recommendation")
                        if k.get(kk) is not None}
    if "years35_cap" in result:
        out["years35_cap"] = result["years35_cap"]
    if "years12_held" in result:
        out["years12_held"] = result["years12_held"]
    return out


def tool_message(name, args, result, limit=TOOL_MESSAGE_MAX_CHARS):
    """(content, cut) for one tool result. A desk result leads with its summary, then the markdown
    report, then the details, so the cut can only ever drop details. `cut` is
    {chars, cut_at} when the cut fired, else None."""
    res = result
    if isinstance(result, dict):
        res = {k: v for k, v in result.items() if not k.startswith("_audit")}
    if (name == "run_financial_model" and isinstance(res, dict)
            and not res.get("error") and not res.get("validation_error")):
        ordered = {"summary": _desk_summary(args, res)}
        if "markdown_report" in res:
            ordered["markdown_report"] = res["markdown_report"]
        ordered["details"] = {k: v for k, v in res.items() if k != "markdown_report"}
        full = json.dumps(ordered)
    else:
        full = json.dumps(res)
    if len(full) > limit:
        return full[:limit], {"chars": len(full), "cut_at": limit}
    return full, None


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
        sa = result.get("set_aside") if isinstance(result, dict) else None
        sa_str = f" ({sa['count']} unrelated results set aside)" if isinstance(sa, dict) and "count" in sa else ""
        prefix = f'[call {call_index}] search: "{q}"{sa_str} -> '
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
        if isinstance(result, dict):
            if "note" in result and "text" not in result:
                note = str(result["note"])[:300]
                return f"[call {call_index}] page: {u} -> {note}"
            if "find" in result:
                phrase = result.get("find", "")
                m = result.get("matches", 0)
                txt = (result.get("text") or "")[:1500]
                return f'[call {call_index}] page: {u} find "{phrase}": {m} matches -> {txt}'
            k = result.get("part")
            n = result.get("parts")
            if n is not None and n > 1 and k is not None:
                txt = (result.get("text") or "")[:1500]
                return f"[call {call_index}] page: {u} (part {k} of {n}) -> {txt}"
        txt = (result.get("text", "") if isinstance(result, dict) else str(result or ""))[:1500]
        return f"{prefix}{txt}"

    elif name == "run_financial_model":
        if isinstance(result, dict) and result.get("error"):
            compact = {"error": result["error"]}
            if "desk_budget" in result:
                compact["desk_budget"] = result["desk_budget"]
            if "desk_closed" in result:
                compact["desk_closed"] = True
        elif isinstance(result, dict):
            compact = {}
            if "desk_budget" in result:
                compact["desk_budget"] = result["desk_budget"]
            if "desk_closed" in result:
                compact["desk_closed"] = True
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

            yc = result.get("years35_cap")
            if isinstance(yc, dict) and "dcfs" in yc and isinstance(yc["dcfs"], list):
                capped_map = {
                    d.get("name", "Base"): [d.get("requested_per_share_iv"), d.get("applied_per_share_iv")]
                    for d in yc["dcfs"] if isinstance(d, dict)
                }
                if capped_map:
                    compact["years35_capped"] = capped_map
        else:
            compact = {"raw": str(result)[:200]}

        json_str = json.dumps(compact, separators=(',', ':'))
        if len(json_str) > 1200:
            json_str = json_str[:1200]
        return f"[call {call_index}] model: {json_str}"

    return str(result)[:500]


def _compact_history(msgs, meta, budget_chars=36000, shrink_page_chars=0, stats=None):
    """Tool messages BEFORE the last assistant tool-call turn become their compact note.
    Latest round stays full. If total chars of all compact notes exceed budget_chars,
    shrink oldest search/page notes first to header-only until under budget. Model notes never shrunk.

    `shrink_page_chars` (Phase 4 report-room rule): additionally shrink PAGE notes only, oldest
    first, to header-only until that many characters are saved; `stats["page_notes_to_headers"]`
    counts them. Every assistant turn's tool-call arguments reach the prompt with long strings
    shortened (the stored history keeps what the model wrote).
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

    shrunk_pages = 0
    if shrink_page_chars > 0:
        saved = 0
        for idx in sorted(compact_notes.keys()):
            if saved >= shrink_page_chars:
                break
            m_info = meta[idx] if meta and idx < len(meta) else None
            if isinstance(m_info, dict):
                name, args, call_idx = m_info.get("name", ""), m_info.get("args") or {}, m_info.get("call_index", idx)
            elif isinstance(m_info, (list, tuple)) and len(m_info) == 4:
                name, args, _, call_idx = m_info
            else:
                continue
            if name != "fetch_page":
                continue
            header_only = f'[call {call_idx}] page: {(args or {}).get("url", "")} (read earlier)'
            diff = len(compact_notes[idx]) - len(header_only)
            if diff > 0:
                compact_notes[idx] = header_only
                saved += diff
                shrunk_pages += 1
    if stats is not None:
        stats["page_notes_to_headers"] = shrunk_pages

    active_msgs = []
    for idx, m in enumerate(msgs):
        if idx in compact_notes:
            new_m = dict(m)
            new_m["content"] = compact_notes[idx]
            active_msgs.append(new_m)
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            active_msgs.append(dict(m, tool_calls=_shorten_tool_calls(m["tool_calls"])))
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
                    tools=None, max_search_calls=25, max_model_calls=5, num_batch=None,
                    desk_context=None):
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
        **({"num_batch": num_batch} if num_batch else {}),
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
    desk_refusal_window = None          # (reasons, inputs) of the last two refused desk calls, cleared by an accepted call (C6b)
    eff_tools = TOOLS if tools is None else tools

    sample_search_queries = []
    page_alias = {}
    page_reads = {}
    sample_fetch_failures = {}
    research_calls = 0
    repeat_calls = 0
    desk_runs = []
    seen_result_urls = {}   # url -> title for every result search_web returned this run (fetch_page fallbacks)
    failure = None
    window_retry_used = False
    window_retry_pending = False
    desk_continuation = None            # C8: the record returned in meta; None until the continuation fires
    desk_continuation_pending = False   # the next turn's record carries "continuation_for_desk"
    desk_only = False                   # C8: only run_financial_model is open for the rest of the session
    desk_calls_at_c8 = 0
    server_errors = 0
    chars_per_token = [None]   # measured on the previous request, for the report-room rule

    def _turn_options(base_opts, msgs_sent):
        cpt = chars_per_token[0] if chars_per_token[0] is not None else 3.0
        est = int(len(json.dumps(msgs_sent)) / cpt)
        np_req = base_opts.get("num_predict", num_predict)
        eff_np = max(1024, min(np_req, ctx - est - 2048))
        return dict(base_opts, num_predict=eff_np), est, eff_np

    def _history():
        """(active messages, page notes shortened). The report-room rule: when the next prompt
        would leave less than REPORT_ROOM_TOKENS of the window, older page notes shrink to headers,
        oldest first."""
        am = _compact_history(msgs, meta_msgs)
        cpt = chars_per_token[0]
        if cpt:
            over = len(json.dumps(am)) / cpt - (ctx - REPORT_ROOM_TOKENS)
            if over > 0:
                st_ = {}
                am = _compact_history(msgs, meta_msgs, shrink_page_chars=int(over * cpt) + 1, stats=st_)
                return am, st_.get("page_notes_to_headers", 0)
        return am, 0

    def _post(body):
        nonlocal server_errors
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                server_errors += 1
                return {"message": {}, "done_reason": "server_error", "http_status": e.code}
            raise
        if resp.get("prompt_eval_count"):
            chars_per_token[0] = len(json.dumps(body["messages"])) / resp["prompt_eval_count"]
        return resp

    def _force_report():
        """The forced memorandum turn: no tools, same think level."""
        nonlocal final_report, final_think, done_reason, gen_tokens, eval_duration_total, failure
        retry_prompt = (
            "You have completed your research and reasoning. Write the complete "
            "institutional memorandum and Section 12 machine contract NOW. Do not search again."
            if max_model_calls > 0 else
            "You have completed your research and reasoning. Provide your findings NOW, ending with the ```json:catalysts block exactly as specified. Do not search again."
        )
        msgs.append({"role": "user", "content": retry_prompt})
        meta_msgs.append(None)
        active_msgs_retry, shrunk = _history()
        base_opts_retry = opts if max_model_calls > 0 else dict(opts, num_predict=opts.get("num_predict", 16384))
        req_opts, est, eff_np = _turn_options(base_opts_retry, active_msgs_retry)
        body = {"model": model, "stream": False, "think": think,
                "messages": active_msgs_retry, "options": req_opts}
        resp = _post(body)
        fm = resp.get("message") or {}
        final_report = fm.get("content") or ""
        final_think += fm.get("thinking") or ""
        done_reason = resp.get("done_reason")
        gen_tokens += resp.get("eval_count") or 0
        eval_duration_total += resp.get("eval_duration") or 0
        if resp.get("done_reason") == "server_error":
            if failure is None:
                failure = "server_error"
            final_report = ""
        elif max_model_calls > 0 and not report_is_deliverable(final_report):
            if failure is None:
                failure = "report_not_delivered"
        turn_rec = {"turn": len(turns) + 1, **turn_metrics(resp), "think": body["think"],
                    "forced_report": True,
                    "est_prompt_tokens": est, "num_predict": eff_np,
                    **({"page_notes_to_headers": shrunk} if shrunk else {})}
        if resp.get("done_reason") == "server_error":
            turn_rec["server_error"] = True
            turn_rec["http_status"] = resp.get("http_status")
        turns.append(turn_rec)
        if server_errors >= 2:
            if failure is None:
                failure = "server_error"
            final_report = ""

    def _recover_cut_off_brief():
        """Discovery mode only (no desk). If the final turn hit num_predict before the
        json:catalysts block, ask once for the block alone at configured think level. Valuation
        runs keep their own truncation path (continue_report)."""
        nonlocal final_report, final_think, done_reason, gen_tokens, eval_duration_total, failure
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
        msgs_recovery = _compact_history(msgs, meta_msgs)
        req_opts, est, eff_np = _turn_options(opts, msgs_recovery)
        body = {"model": model, "stream": False, "think": think,
                "messages": msgs_recovery,
                "options": req_opts}
        resp = _post(body)
        fm = resp.get("message") or {}
        final_report = ((final_report or "") + "\n\n" + (fm.get("content") or "")).strip()
        final_think += fm.get("thinking") or ""
        done_reason = resp.get("done_reason")
        gen_tokens += resp.get("eval_count") or 0
        eval_duration_total += resp.get("eval_duration") or 0
        if "```json" not in (final_report or ""):
            failure = "brief_not_delivered"
        turn_rec = {"turn": len(turns) + 1, **turn_metrics(resp), "think": body["think"],
                    "length_recovery": True,
                    "est_prompt_tokens": est, "num_predict": eff_np}
        if resp.get("done_reason") == "server_error":
            turn_rec["server_error"] = True
            turn_rec["http_status"] = resp.get("http_status")
        turns.append(turn_rec)
        if server_errors >= 2:
            if failure is None:
                failure = "server_error"
            final_report = ""

    while True:
        active_msgs, shrunk = _history()
        req_opts, est, eff_np = _turn_options(opts, active_msgs)

        # If search budget is exhausted, only expose financial modeling tool
        active_tools = eff_tools
        if search_calls >= max_search_calls or desk_only:
            active_tools = [t for t in eff_tools if t["function"]["name"] == "run_financial_model"]
        if model_calls >= max_model_calls or desk_validation_errors > 6:
            active_tools = [t for t in active_tools if t["function"]["name"] != "run_financial_model"]

        body = {"model": model, "stream": False, "think": think, "messages": active_msgs,
                "options": req_opts}
        if active_tools and (search_calls < max_search_calls or (model_calls < max_model_calls and desk_validation_errors <= 6)):
            body["tools"] = active_tools

        resp = _post(body)
        msg = resp.get("message") or {}
        done_reason = resp.get("done_reason")
        gen_tokens += resp.get("eval_count") or 0
        eval_duration_total += resp.get("eval_duration") or 0
        turn_rec = {"turn": len(turns) + 1, **turn_metrics(resp), "think": body["think"],
                    "est_prompt_tokens": est, "num_predict": eff_np,
                    **({"page_notes_to_headers": shrunk} if shrunk else {})}
        if window_retry_pending:
            turn_rec["window_retry"] = True
            window_retry_pending = False
        if desk_continuation_pending:
            turn_rec["continuation_for_desk"] = True
            desk_continuation_pending = False
        if resp.get("done_reason") == "server_error":
            turn_rec["server_error"] = True
            turn_rec["http_status"] = resp.get("http_status")
        turns.append(turn_rec)

        if server_errors >= 2:
            if failure is None:
                failure = "server_error"
            final_report = ""
            break

        if msg.get("thinking"):
            final_think += msg["thinking"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            final_report = msg.get("content") or ""
            is_stub = not report_is_deliverable(final_report) if max_model_calls > 0 else not bool(_TOOL_CALL_BLOCK.sub("", final_report or "").strip())
            # Phase 4 window fix: a tool turn that ran out of room (length) with no tool call, no report and
            # no desk result yet gets one full-thinking retry.
            if (is_stub and not window_retry_used and done_reason in ("length", "server_error")
                    and body.get("tools") and max_model_calls > 0 and model_calls == 0
                    and desk_validation_errors <= 6):
                if verbose:
                    print("    [harness] turn ran out of room (length) with no tool call and no desk "
                          "result - one full-thinking retry", flush=True)
                msgs.append({"role": "user", "content": WINDOW_RETRY_PROMPT})
                meta_msgs.append(None)
                window_retry_used = True
                window_retry_pending = True
                continue
            if is_stub and window_retry_used and done_reason in ("length", "server_error") and model_calls == 0:
                failure = "window_exhausted_twice"
                final_report = ""
                break
            # Revision 17, brief C8: no complete desk run and the desk still open. Whether this turn delivered a
            # memorandum does not matter: a memorandum with no desk run cannot publish a value. Once per call.
            c8_cause = (desk_continuation_cause(snap, model_calls, desk_validation_errors, max_model_calls)
                        if (desk_continuation is None and failure is None and server_errors < 2
                            and done_reason != "server_error"
                            and any(t["function"]["name"] == "run_financial_model" for t in eff_tools))
                        else None)
            if c8_cause is not None:
                delivered = not is_stub
                if verbose:
                    print(f"    [harness] terminal turn with no complete desk run and the desk open "
                          f"({c8_cause}) - continuing on the desk alone", flush=True)
                msgs.append({"role": "assistant", "content": msg.get("content") or ""})
                meta_msgs.append(None)
                msgs.append({"role": "user", "content": DESK_CONTINUATION.format(
                    lead=DESK_CONTINUATION_LEAD["memorandum" if delivered else "no_memorandum"],
                    cause=DESK_CONTINUATION_CAUSE[c8_cause],
                    left=max_model_calls - model_calls, cap=max_model_calls)})
                meta_msgs.append(None)
                desk_only = True
                desk_continuation_pending = True
                desk_calls_at_c8 = sum(1 for c in snap if c.get("tool") == "run_financial_model")
                desk_continuation = {"reason": c8_cause, "after": "memorandum" if delivered else "no_memorandum",
                                     "turn": len(turns), "desk_calls_after": 0, "complete_after": False,
                                     "base_over_reference": None}
                continue
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
                _force_report()
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
            arg_cuts = []
            if name == "run_financial_model":
                args, arg_cuts = truncate_long_strings(args)

            # P1.7: Append every dispatched call BEFORE it executes and persist immediately to disk
            call_rec = {
                "tool": name,
                "call_index": calls,
                "ts": time.strftime("%H:%M:%S"),
                "params": args,
            }
            if arg_cuts:
                call_rec["arg_truncated"] = arg_cuts
            snap.append(call_rec)
            _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)

            result = None
            try:
                desk_was_closed = (model_calls >= max_model_calls or desk_validation_errors > 6) if max_model_calls > 0 else False
                if desk_only and name != "run_financial_model":
                    result = {"error": DESK_ONLY_OPEN}      # C8: counts against no budget
                elif name in ("search_web", "fetch_page"):
                    research_calls += 1
                    if name == "search_web":
                        q = (args or {}).get("query", "")
                        if any(is_near_duplicate(q, prev_q, threshold=0.50) for prev_q in sample_search_queries):
                            repeat_calls += 1
                        sample_search_queries.append(q)

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
                    elif name == "search_web":
                        result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache,
                                               known_urls=seen_result_urls)
                        if isinstance(result, dict):
                            for r in (result.get("results") or []):
                                if isinstance(r, dict) and r.get("url"):
                                    seen_result_urls.setdefault(r["url"], r.get("title") or "")
                    elif name == "fetch_page":
                        u = (args or {}).get("url") or ""
                        raw_part = (args or {}).get("part")
                        find = (args or {}).get("find")
                        if find is not None and not isinstance(find, str):
                            find = str(find)

                        # Step 1: u failed earlier in this sample
                        if u in sample_fetch_failures:
                            repeat_calls += 1
                            result = {
                                "url": u,
                                "note": f"already fetched in this sample: {sample_fetch_failures[u]}. Fetching "
                                        f"it again returns exactly the same, so it adds nothing. Use "
                                        f"what you have, or search for a different source."
                            }
                        else:
                            # Validate part if find is not given
                            part = None
                            part_err = None
                            if find is None and raw_part is not None:
                                part, part_err = _parse_part(raw_part)

                            if part_err is not None:
                                result = {"url": u, "error": part_err}
                            elif u not in page_alias:
                                # Step 2: u is new
                                result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache,
                                                       known_urls=seen_result_urls)
                                if isinstance(result, dict) and (result.get("error") or result.get("refused")):
                                    err_msg = str(result.get("error") or result.get("refused"))
                                    sample_fetch_failures[u] = f"it failed ({err_msg[:160]})"
                                elif isinstance(result, dict):
                                    # the dispatch reached the network or the cache even when another part, a
                                    # find or a note is served below: keep its hit/miss for the P4.0b accounting
                                    dispatch_cache_hit = result.get("cache_hit")
                                    src = result.get("url") or u
                                    page_alias[u] = src
                                    if src not in page_reads:
                                        p_count = result.get("parts")
                                        if p_count is None:
                                            p_count = 1
                                        page_reads[src] = {
                                            "parts": p_count,
                                            "served": {},
                                            "requests": 0,
                                            "finds": {},
                                            "first_call": calls,
                                        }
                                    page_reads[src]["requests"] += 1
                                    r_num = page_reads[src]["requests"]
                                    rec = u_cache.get(src)
                                    if rec is None:
                                        rec = {"url": src, "chars": result.get("chars", len(result.get("text") or "")),
                                               "text": result.get("text") or ""}
                                        u_cache[src] = rec

                                    if find is not None:
                                        result = find_in_page(rec, find)
                                        phrase_key = find.strip().lower()
                                        page_reads[src]["finds"][phrase_key] = calls
                                        # Mark no part served
                                    elif part is not None and part != 1:
                                        part_res = page_part(rec, part)
                                        if not part_res.get("error"):
                                            page_reads[src]["served"][part] = calls
                                        result = part_res
                                    elif bool(page_reads[src]["served"]):
                                        # src already has parts served
                                        n_parts = page_reads[src]["parts"]
                                        unread = [p for p in range(1, n_parts + 1) if p not in page_reads[src]["served"]]
                                        if unread:
                                            next_part = unread[0]
                                            part_res = page_part(rec, next_part)
                                            if not part_res.get("error"):
                                                page_reads[src]["served"][next_part] = calls
                                            part_res["same_page_as"] = f"call {page_reads[src]['first_call']}"
                                            for k in ("alternate_for", "alternate_query", "corrected_from", "note"):
                                                if k in result:
                                                    part_res[k] = result[k]
                                            result = part_res
                                        else:
                                            repeat_calls += 1
                                            if n_parts == 1:
                                                i_call = page_reads[src]["served"][1]
                                                result = {"url": src, "note": f"This page is a single part, served to you at call {i_call}; this is request {r_num} for it. Pass part=1 to read it again, or find to search it."}
                                            else:
                                                served_list = [str(page_reads[src]["served"][p]) for p in range(1, n_parts + 1) if p in page_reads[src]["served"]]
                                                result = {"url": src, "note": f"All {n_parts} parts of this page were served to you (calls {', '.join(served_list)}); this is request {r_num} for it. Pass part to read one again, or find to search the whole page."}
                                    else:
                                        # dispatch result is part 1
                                        page_reads[src]["served"][1] = calls
                                    if dispatch_cache_hit is not None and "cache_hit" not in result:
                                        result["cache_hit"] = dispatch_cache_hit
                            else:
                                # Step 3: u was read before
                                src = page_alias[u]
                                page_reads[src]["requests"] += 1
                                r_num = page_reads[src]["requests"]
                                rec = u_cache[src]      # step 2 always leaves a record for src
                                n_parts = page_reads[src]["parts"]

                                if find is not None:
                                    phrase_key = find.strip().lower()
                                    if phrase_key in page_reads[src]["finds"]:
                                        repeat_calls += 1
                                    else:
                                        page_reads[src]["finds"][phrase_key] = calls
                                    result = find_in_page(rec, find)
                                elif part is not None:
                                    part_res = page_part(rec, part)
                                    if not part_res.get("error"):
                                        if part in page_reads[src]["served"]:
                                            first_i = page_reads[src]["served"][part]
                                            part_res["served_again"] = f"you first read this part at call {first_i}; older page text in your notes is shortened to 1,500 characters."
                                            repeat_calls += 1
                                        else:
                                            page_reads[src]["served"][part] = calls
                                    result = part_res
                                else:
                                    unread = [p for p in range(1, n_parts + 1) if p not in page_reads[src]["served"]]
                                    if unread:
                                        lowest = unread[0]
                                        part_res = page_part(rec, lowest)
                                        if not part_res.get("error"):
                                            page_reads[src]["served"][lowest] = calls
                                        result = part_res
                                    else:
                                        repeat_calls += 1
                                        if n_parts == 1:
                                            i_call = page_reads[src]["served"][1]
                                            result = {"url": src, "note": f"This page is a single part, served to you at call {i_call}; this is request {r_num} for it. Pass part=1 to read it again, or find to search it."}
                                        else:
                                            served_list = [str(page_reads[src]["served"][p]) for p in range(1, n_parts + 1) if p in page_reads[src]["served"]]
                                            result = {"url": src, "note": f"All {n_parts} parts of this page were served to you (calls {', '.join(served_list)}); this is request {r_num} for it. Pass part to read one again, or find to search the whole page."}

                elif name == "run_financial_model":
                    if model_calls >= max_model_calls or desk_validation_errors > 6:
                        result = {"error": f"financial model call budget exhausted ({max_model_calls}); "
                                           f"use computed results and finalize memorandum"}
                    else:
                        # the cap goes only where it is set, so a dispatcher without desk_context fails loudly
                        desk_kw = {"desk_context": desk_context} if desk_context is not None else {}
                        call_key = json.dumps(args, sort_keys=True, default=str)      # the inputs as sent (the desk annotates args)
                        result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache, **desk_kw)
                        if isinstance(result, dict) and result.get("validation_error") is True:
                            desk_validation_errors += 1
                            result, desk_refusal_window = desk_loop_guard(result, call_key, desk_refusal_window)
                            if desk_validation_errors > 6:
                                result = {"error": f"financial model call budget exhausted ({max_model_calls}); "
                                                   f"use computed results and finalize memorandum"}
                        else:
                            model_calls += 1
                            desk_refusal_window = None

                    if max_model_calls > 0 and isinstance(result, dict):
                        result = dict(result)
                        result["desk_budget"] = DESK_BUDGET.format(used=model_calls, cap=max_model_calls,
                                                                    refused=desk_validation_errors)
                        if not desk_was_closed and (model_calls >= max_model_calls or desk_validation_errors > 6):
                            if model_calls >= max_model_calls:
                                result["desk_closed"] = DESK_CLOSED_RUNS.format(cap=max_model_calls)
                            else:
                                result["desk_closed"] = DESK_CLOSED_REJECTED.format(n=desk_validation_errors)
                else:
                    result = {"error": f"unknown tool {name}"}

                if max_model_calls > 0 and desk_was_closed and isinstance(result, dict):
                    result = {"desk": DESK_CLOSED_LINE, **result}
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
                    if "desk" in result:
                        desk_first = [("desk", result["desk"])] + [(k, v) for k, v in call_rec.items() if k != "desk"]
                        call_rec.clear()
                        call_rec.update(desk_first)
                elif result is not None:
                    call_rec["result"] = result
                _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)
                if (name == "run_financial_model" and desk_continuation is not None
                        and not desk_continuation["complete_after"] and desk_run_is_complete(snap)):
                    # the first complete run after C8: its Base against the pack's consensus-implied value, an
                    # annotation of the copy risk the removed desk-only recovery had, never a gate
                    import contract_fill
                    desk_continuation["complete_after"] = True
                    base_iv = next((e["dcf"]["per_share_iv"] for c in reversed(snap)
                                    if c.get("tool") == "run_financial_model" and contract_fill.completed(c)
                                    for e in contract_fill.entries(c) if e["role"] == "base"), None)
                    ref_iv = (desk_context or {}).get("consensus_implied_value")
                    if isinstance(base_iv, (int, float)) and isinstance(ref_iv, (int, float)) and ref_iv > 0:
                        desk_continuation["base_over_reference"] = base_iv / ref_iv

            if verbose:
                q = args.get("query") or args.get("url") or (f"price={args.get('price')}" if name == 'run_financial_model' else "")
                print(f"    [tool {calls}] {name}: {str(q)[:88]}", flush=True)
            content, cut = tool_message(name, args, result)
            if cut:
                call_rec["tool_result_truncated"] = cut
                _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)
            msgs.append({"role": "tool", "content": content})
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
            active_msgs_exhausted, shrunk = _history()
            req_opts, est, eff_np = _turn_options(opts, active_msgs_exhausted)
            body = {"model": model, "stream": False, "think": think, "messages": active_msgs_exhausted,
                    "options": req_opts}
            resp = _post(body)
            fm = resp.get("message") or {}
            final_report = fm.get("content") or ""
            final_think += fm.get("thinking") or ""
            done_reason = resp.get("done_reason")
            gen_tokens += resp.get("eval_count") or 0
            eval_duration_total += resp.get("eval_duration") or 0
            turn_rec = {"turn": len(turns) + 1, **turn_metrics(resp), "think": body["think"],
                        "budget_exhausted": True,
                        "est_prompt_tokens": est, "num_predict": eff_np,
                        **({"page_notes_to_headers": shrunk} if shrunk else {})}
            if resp.get("done_reason") == "server_error":
                turn_rec["server_error"] = True
                turn_rec["http_status"] = resp.get("http_status")
            turns.append(turn_rec)
            if server_errors >= 2:
                if failure is None:
                    failure = "server_error"
                final_report = ""
                break
            if resp.get("done_reason") == "server_error":
                if failure is None:
                    failure = "server_error"
                final_report = ""
                break
            _recover_cut_off_brief()
            if max_model_calls > 0 and not report_is_deliverable(final_report) and failure is None:
                failure = "report_not_delivered"
            break

    _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)
    if desk_continuation is not None:
        desk_continuation["desk_calls_after"] = (
            sum(1 for c in snap if c.get("tool") == "run_financial_model") - desk_calls_at_c8)
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
                                       # ctx minus the prompt of the turn that delivered the report
                                       "report_turn_headroom_tokens": (
                                           ctx - turns[-1]["prompt_tokens"]
                                           if turns and isinstance(turns[-1].get("prompt_tokens"), int)
                                           else None),
                                       "elapsed_s": round(time.time() - t0),
                                       "think_configured": think,
                                       "failure": failure,
                                       "window_retry_used": window_retry_used,
                                       "continuation_for_desk": desk_continuation}


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
