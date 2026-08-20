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
import io
import json
import re
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
OLLAMA = "http://localhost:11434/api/chat"
MAX_TOOL_CALLS = 12          # a hard ceiling; a runaway loop is worse than a missing fact
UA = {"User-Agent": "Mozilla/5.0 (RS2 analyst research)"}

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
            "rather than assuming a value."),
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
}]


def looks_like_refetch(query):
    return bool(REFETCH_SMELL.search(query or ""))


def search_web(query, why="", snap=None, n=6):
    """SearXNG JSON search -> compact result list. Snapshots the raw response."""
    url = f"{SEARX}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"query": query, "error": f"search failed: {str(e)[:120]}", "results": []}
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
           "refetch_warning": looks_like_refetch(query)}
    if snap is not None:
        snap.append({"tool": "search_web", "ts": time.strftime("%H:%M:%S"), **rec})
    return rec


def fetch_page(url, snap=None, cap=9000):
    if any(bad in url for bad in LOW_TRUST):
        return {"url": url, "error": "low-trust source refused"}
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read(1_500_000).decode("utf-8", "replace")
    except Exception as e:
        return {"url": url, "error": f"fetch failed: {str(e)[:120]}"}
    txt = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = re.sub(r"&[a-z]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    rec = {"url": url, "chars": len(txt), "text": txt[:cap]}
    if snap is not None:
        snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"),
                     "url": url, "chars": len(txt), "text": txt[:cap]})
    return rec


def chat_with_tools(model, content, out_dir, think="high", ctx=65536, num_predict=49152,
                    seed=None, timeout=14400, verbose=True):
    """Ollama chat with the search tools available. Returns (report, thinking, meta).

    Snapshots every tool call to out_dir/_research_snapshot.json so the run stays reproducible
    and auditable against exactly what the model saw.
    """
    msgs = [{"role": "user", "content": content}]
    snap, calls = [], 0
    opts = {"num_ctx": ctx, "num_predict": num_predict}
    if seed is not None:
        opts["seed"] = seed
    t0 = time.time()
    final_report, final_think, done_reason = "", "", None
    gen_tokens = 0

    while True:
        body = {"model": model, "stream": False, "think": think, "messages": msgs,
                "tools": TOOLS, "options": opts}
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
        msg = resp.get("message") or {}
        done_reason = resp.get("done_reason")
        gen_tokens += resp.get("eval_count") or 0
        if msg.get("thinking"):
            final_think += msg["thinking"]
        tcs = msg.get("tool_calls") or []
        if not tcs:
            final_report = msg.get("content") or ""
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": tcs})
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
            if calls > MAX_TOOL_CALLS:
                result = {"error": f"tool-call budget exhausted ({MAX_TOOL_CALLS}); "
                                   f"conclude with what you have and say what is unresolved"}
            elif name == "search_web":
                result = search_web(args.get("query", ""), args.get("why", ""), snap)
            elif name == "fetch_page":
                result = fetch_page(args.get("url", ""), snap)
            else:
                result = {"error": f"unknown tool {name}"}
            if verbose:
                q = args.get("query") or args.get("url") or ""
                print(f"    [tool {calls}] {name}: {str(q)[:88]}", flush=True)
            msgs.append({"role": "tool", "content": json.dumps(result)[:12000]})
        if calls > MAX_TOOL_CALLS:
            # BUDGET REACHED -> force the answer, never just break. Breaking here returned an
            # EMPTY report (sample 3 of the first tool run: 59,074 chars of thinking, 0 chars of
            # report) because the loop exited mid-conversation with nothing asked for. Re-issue
            # WITHOUT tools so the model has no choice but to conclude on what it has.
            msgs.append({"role": "user", "content":
                         "Research budget is exhausted. Write the complete report NOW from what "
                         "you have. Mark anything you could not establish as [Unconfirmed] and "
                         "carry that uncertainty into your scenarios. Do not search again."})
            body = {"model": model, "stream": False, "think": think, "messages": msgs,
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
            break

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "_research_snapshot.json").write_text(
        json.dumps({"model": model, "seed": seed, "tool_calls": calls,
                    "elapsed_s": round(time.time() - t0), "calls": snap}, indent=2),
        encoding="utf-8")
    return final_report, final_think, {"tool_calls": calls, "done_reason": done_reason,
                                       "generated_tokens": gen_tokens,
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
