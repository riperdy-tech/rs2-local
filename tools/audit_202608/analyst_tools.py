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
OLLAMA = "http://127.0.0.1:11434/api/chat"
MAX_TOOL_CALLS = 25          # balanced research budget; deduplication eliminates redundant query loops
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
}, {
    "type": "function",
    "function": {
        "name": "run_financial_model",
        "description": (
            "Invoke the Python Financial Modeling Analyst Desk to execute deterministic calculations: "
            "1. Unbundled DCF: computes exact per-share intrinsic value with optional separate capitalization "
            "of installed-base recurring annuity streams. "
            "2. Reverse DCF expectations gap: computes what 5-year growth the market is pricing in at T0 vs demonstrated 5y CAGR. "
            "3. Mathematical continuous Kelly sizing: derives exact quarter-Kelly and full Kelly log-wealth position sizes across your scenario distribution (Base/Bull/Bear). "
            "Call this whenever you have scenario assumptions and need exact arithmetic rather than estimating in prose."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "price": {"type": "number", "description": "Current market price T0 from Section 2."},
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
                            "growth_rates": {"type": "array", "items": {"type": "number"}, "description": "5-year growth rates"},
                            "wacc": {"type": "number", "description": "Discount rate as decimal"},
                            "terminal_g": {"type": "number", "description": "Terminal growth as decimal"},
                            "terminal_exit_multiple": {"type": "number"}
                        },
                        "required": ["name", "prob"]
                    }
                },
                "base_cf": {"type": "number", "description": "Base owner cash flow / FCF (in $B or per-share, matching units)."},
                "growth_rates": {
                    "type": "array",
                    "description": "List of 5 annual growth rates, e.g. [0.12, 0.10, 0.08, 0.06, 0.05].",
                    "items": {"type": "number"}
                },
                "wacc": {"type": "number", "description": "Cost of capital / discount rate as decimal, e.g. 0.085 for 8.5%."},
                "terminal_exit_multiple": {"type": "number", "description": "Exit multiple on year-5 cash flow (e.g. 16.0 for 16x)."},
                "terminal_g": {"type": "number", "description": "Long-term terminal growth rate as decimal (default 0.025)."},
                "annuity_flow": {"type": "number", "description": "Separate annual services / installed-base recurring annuity cash flow (if unbundled)."},
                "annuity_cap_rate": {"type": "number", "description": "Capitalization rate for annuity flow (e.g. 0.075 for 7.5%)."},
                "net_debt": {"type": "number", "description": "Total net debt (Debt minus cash/marketable securities) in $B."},
                "shares_diluted": {"type": "number", "description": "Diluted share count in billions."},
                "demonstrated_cagr_5y": {"type": "number", "description": "Historical 5-year revenue CAGR in percent (e.g. 7.5 for 7.5%) from Section 7."}
            },
            "required": ["price"]
        }
    }
}]


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


def fetch_page(url, snap=None, cap=9000, url_cache=None):
    if any(bad in url for bad in LOW_TRUST):
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
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read(1_500_000).decode("utf-8", "replace")
    except Exception as e:
        # A FAILED fetch is still a tool result the model was served, and the run directory is
        # meant to explain the model's behaviour after the fact. Without this the audit trail
        # shows the model going quiet with no record of why.
        if snap is not None:
            snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"), "url": url,
                         "chars": 0, "text": "", "cached": False,
                         "error": f"fetch failed: {str(e)[:120]}"})
        return {"url": url, "error": f"fetch failed: {str(e)[:120]}"}
    txt = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = re.sub(r"&[a-z]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    rec = {"url": url, "chars": len(txt), "text": txt[:cap]}
    if url_cache is not None:
        url_cache[url] = rec
    if snap is not None:
        snap.append({"tool": "fetch_page", "ts": time.strftime("%H:%M:%S"),
                     "url": url, "chars": len(txt), "text": txt[:cap], "cached": False})
    return {**rec, "cache_hit": False}


def dispatch_tool(name, args, snap=None, query_cache=None, url_cache=None):
    """Unified dispatcher for all analyst tools."""
    if name == "search_web":
        return search_web(args.get("query", ""), args.get("why", ""), snap, query_cache=query_cache)
    elif name == "fetch_page":
        return fetch_page(args.get("url", ""), snap, url_cache=url_cache)
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
                    temperature=None, query_cache=None, url_cache=None):
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
    MAX_SEARCH_CALLS = 25
    MAX_MODEL_CALLS = 5

    while True:
        # Ephemeral Context Compaction:
        # Compact tool payloads from turns prior to the most recent assistant tool call.
        # The model has already read and digested them into its reasoning trace (<think>).
        # Pruning the raw JSON/HTML keeps context window lean and prevents attention dilution.
        last_asst_idx = -1
        for idx in range(len(msgs) - 1, -1, -1):
            if msgs[idx].get("role") == "assistant" and msgs[idx].get("tool_calls"):
                last_asst_idx = idx
                break

        active_msgs = []
        for idx, m in enumerate(msgs):
            if m.get("role") == "tool" and last_asst_idx != -1 and idx < last_asst_idx:
                active_msgs.append({
                    "role": "tool",
                    "content": "[Retrieved research digested into analyst thinking trace; pruned for context efficiency]"
                })
            else:
                active_msgs.append(m)

        # If search budget is exhausted, only expose financial modeling tool
        active_tools = TOOLS
        if search_calls >= MAX_SEARCH_CALLS:
            active_tools = [t for t in TOOLS if t["function"]["name"] == "run_financial_model"]

        body = {"model": model, "stream": False, "think": think, "messages": active_msgs,
                "options": opts}
        if active_tools and calls < (MAX_SEARCH_CALLS + MAX_MODEL_CALLS):
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
            if not report_is_deliverable(final_report):
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
                          f"report — forcing the memorandum turn instead of accepting it",
                          flush=True)
                msgs.append({"role": "user", "content":
                             "You have completed your research and reasoning. Write the complete "
                             "institutional memorandum and Section 12 machine contract NOW. Do not search again."})
                active_msgs_retry = []
                for idx, m in enumerate(msgs):
                    if m.get("role") == "tool" and last_asst_idx != -1 and idx < last_asst_idx:
                        active_msgs_retry.append({
                            "role": "tool",
                            "content": "[Retrieved research digested into analyst thinking trace; pruned for context efficiency]"
                        })
                    else:
                        active_msgs_retry.append(m)
                opts_retry = dict(opts)
                opts_retry["num_predict"] = 32768
                body = {"model": model, "stream": False, "think": "low", "messages": active_msgs_retry,
                        "options": opts_retry}
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
                    search_calls += 1
                    if search_calls > MAX_SEARCH_CALLS:
                        result = {
                            "status": "search_quota_met",
                            "message": (
                                f"Web search budget completed ({MAX_SEARCH_CALLS} calls). "
                                "Do not search again. Formulate your scenario drivers and invoke "
                                "run_financial_model to compute intrinsic values and Kelly sizing, "
                                "then proceed to write your memorandum."
                            )
                        }
                    else:
                        result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache)
                elif name == "run_financial_model":
                    model_calls += 1
                    if model_calls > MAX_MODEL_CALLS:
                        result = {"error": f"financial model call budget exhausted ({MAX_MODEL_CALLS}); "
                                           f"use computed results and finalize memorandum"}
                    else:
                        result = dispatch_tool(name, args, snap=None, query_cache=q_cache, url_cache=u_cache)
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
                if name == "run_financial_model" and isinstance(result, dict) and "result" in result:
                    call_rec.update(result)
                elif isinstance(result, dict):
                    call_rec.update(result)
                elif result is not None:
                    call_rec["result"] = result
                _write_snapshot(out_dir, model, seed, calls, stub_rejected, turns, t0, snap)

            if verbose:
                q = args.get("query") or args.get("url") or (f"price={args.get('price')}" if name == 'run_financial_model' else "")
                print(f"    [tool {calls}] {name}: {str(q)[:88]}", flush=True)
            msgs.append({"role": "tool", "content": json.dumps(result)[:12000]})

        if search_calls >= MAX_SEARCH_CALLS and model_calls >= MAX_MODEL_CALLS:
            # ALL BUDGETS REACHED -> force the answer, never just break.
            msgs.append({"role": "user", "content":
                         "Tool budgets are exhausted. Write the complete institutional memorandum "
                         "and Section 12 machine contract NOW from what you have. Do not search again."})
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
            eval_duration_total += resp.get("eval_duration") or 0
            turns.append({"turn": len(turns) + 1, **turn_metrics(resp),
                          "budget_exhausted": True})
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
