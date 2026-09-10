#!/usr/bin/env python3
"""deep_api_run.py - depth-tier analysis on a cloud API model.

Two jobs, one script:
  * REPLAY (default) - re-run a ticker the local tier has already finished, on its frozen pack.
    This is the A/B instrument: same bytes to both models, so a difference is the model.
  * FALLBACK (--fresh) - run a ticker the local tier has NOT done, building the pack from current
    data. This is the standby path for when the local box is off or the GPU is busy.
    See FALLBACK LIMITS below - a --fresh verdict is NOT equivalent to a local one.

STANDALONE. This file is additive: it imports the local engine read-only and writes only under
api_llm/deep_api/. It never modifies depth_pipeline.py, consensus_valuation.py, analyst_tools.py
or any Modelfile, and it never appends to cache/depth_ledger.jsonl or depth_overlay.json.

WHAT IS MIRRORED (from the local deep tier, verbatim):
  * the INPUT: the frozen _pack.md the local run already saved, byte for byte
  * 3 samples, tools AVAILABLE (search_web / fetch_page), model decides whether to call them
  * the same SearXNG backend, the same 12k-char tool-result truncation, the same 12-call budget
    and the same forced-conclusion prompt when the budget is spent
  * the same IV extraction, the same plausibility guard, the same band-direction verdict rule
    - all imported from the engine, not reimplemented

WHAT IS NOT MIRRORED, AND WHY (measured against DeepSeek's API docs, 2026-08-24):
  * temperature / top_p / top_k / penalties are NOT sent. Thinking mode "does not support"
    them - they are silently ignored. Qwen's 0.6/0.95/20 is Qwen's own thinking profile and
    transplanting it would be a no-op dressed up as a mirror. The cloud model runs at its
    vendor defaults, which is the honest analogue of Qwen running at Qwen's.
  * seed is NOT sent - undocumented in the API reference, so per-sample reproducibility is
    NOT claimed on this arm. Local seeds 1000+i; here the draws are independent.
  * reasoning_effort "high" is DeepSeek's scale, not Qwen's xhigh. Comparable in intent only.
  * CONSEQUENCE: cloud spread_pct is produced by a different sampling mechanism than local
    spread_pct. Direction and IV level compare; spread does not compare like-for-like.

FALLBACK LIMITS (--fresh), measured, not assumed:
  * SECTION 11 of the pack is a research brief written by the LOCAL rs2-research model through
    LDR. With the local box down that brief cannot be refreshed. --fresh uses whatever
    research/{T}.md holds and PRINTS ITS AGE; if the file is absent the pack simply has no
    SECTION 11. The run's own search tools (about 14 queries per sample) partly cover the gap.
  * The tools call the LOCAL SearXNG. If it is unreachable, search_web returns an error to the
    model rather than failing the run - so a run can silently degrade to no-research. --fresh
    probes SearXNG first and says so.
  * Price is today's from the data pack, not the price a local run was judged against.
  * Every output is stamped pack_source / research_brief_age_days / searxng_up, so a verdict
    produced under degraded conditions is identifiable after the fact.

  python api_llm/deep_api_run.py JKHY
  python api_llm/deep_api_run.py JKHY --samples 3 --effort high --dir JKHY_20260824_114148
  python api_llm/deep_api_run.py NVDA --fresh          # local tier never ran this name
  python api_llm/deep_api_run.py NVDA --fresh --model deepseek-v4-pro
"""
import json
import re
import statistics as st
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../RS2 Local/api_llm
ROOT = HERE.parent                              # .../RS2 Local
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "audit_202608"))

# Import order matters. consensus_valuation and depth_pipeline each rewrap sys.stdout at import;
# analyst_tools documents that a wrapper collected by GC closes the buffer under the next one
# ("I/O operation on closed file", killed the first tool-enabled run). Holding a reference to
# every wrapper keeps them all alive, so none is finalised.
_STDOUT_KEEPALIVE = [sys.stdout]
import consensus_valuation as cv     # noqa: E402  extract_iv, plausibility, thresholds
_STDOUT_KEEPALIVE.append(sys.stdout)
import depth_pipeline as dp          # noqa: E402  band_verdict, SIZE_BUCKETS
_STDOUT_KEEPALIVE.append(sys.stdout)
import analyst_tools as at           # noqa: E402  TOOLS schema, search_web, fetch_page
import capability_test as cap        # noqa: E402  build_pack, TASK, PACK_REVISION

CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
LOCAL_CONSENSUS = ROOT / "ab_reports" / "consensus"     # read-only source of frozen packs
OUT = HERE / "deep_api"                                 # this arm's only write target
MODEL = "deepseek-v4-flash"     # --model overrides; pro is the same API shape at 3x the price
MAX_TOKENS = cv.NUM_PREDICT             # 65536, same output budget as local
CALL_TIMEOUT = 1800
TRANSPORT_RETRIES = 3                   # 429 / transient 5xx only; not an analysis behaviour

# Published prices per 1M tokens (api-docs.deepseek.com/quick_start/pricing, read 2026-08-24).
# Off-peak is half of peak; the window itself lives in deepseek_offpeak.py (shared with the gate).
PRICE = {"deepseek-v4-flash": {"hit": 0.014, "miss": 0.44, "out": 1.32},
         "deepseek-v4-pro": {"hit": 0.044, "miss": 1.32, "out": 3.96}}

# The RS2 analytical framework. The LOCAL tier gets it for free: it is baked into the
# rs2-analyst-deep Modelfile's SYSTEM block, so every local sample is written under it. The
# DeepSeek API has no baked system prompt, and the earlier cloud arm sent none - so the model was
# handed the fact pack + a TASK saying "produce SECTION 0-12 per the framework's FINAL OUTPUT
# STRUCTURE" while never being shown the framework. Measured 2026-08-26: 127 of 131 published
# cloud reports omitted every RS2 analytical layer (base rate, moat scoring, scenarios, red team,
# audit, ...) and produced a fact-pack echo + an IV instead. Attaching the SAME block as an
# explicit system message makes the cloud transport mirror the local one exactly. Read-only from
# the engine's Modelfile - nothing here modifies it. Deep and Deep-MTP5 carry a byte-identical
# block (verified), so the base Deep file is the canonical source.
_FRAMEWORK_MODELFILE = ROOT / "RS2-Analyst-Deep.Modelfile"
_FRAMEWORK_CACHE = None


def _rs2_framework():
    """The baked SYSTEM block, extracted and cached (read once, not per sample/tool-round)."""
    global _FRAMEWORK_CACHE
    if _FRAMEWORK_CACHE is None:
        mf = _FRAMEWORK_MODELFILE.read_text(encoding="utf-8")
        m = re.search(r'SYSTEM\s+"""(.*?)"""', mf, re.S)
        if not m:
            raise RuntimeError(f'no SYSTEM """...""" block in {_FRAMEWORK_MODELFILE.name} - '
                               "cannot attach the RS2 framework to the cloud call")
        _FRAMEWORK_CACHE = m.group(1).strip()
    return _FRAMEWORK_CACHE


from deepseek_offpeak import off_peak as _off_peak  # noqa: E402  one window definition, shared with the backstop gate


def _cost(usage, model, dt):
    p = PRICE.get(model)
    if not p:
        return None
    hit = usage.get("prompt_cache_hit_tokens") or 0
    miss = usage.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = (usage.get("prompt_tokens") or 0) - hit
    out = usage.get("completion_tokens") or 0
    usd = (hit * p["hit"] + miss * p["miss"] + out * p["out"]) / 1_000_000
    return usd * (0.5 if _off_peak(dt) else 1.0)


def _api_key():
    name = CFG.get("api_key_name", "LLM_API_KEY")
    key = json.loads((ROOT / ".secrets.json").read_text(encoding="utf-8")).get(name)
    if not key:
        raise RuntimeError(f"API key '{name}' missing from {ROOT / '.secrets.json'}")
    return key


def _post(payload, key, meter):
    """One /chat/completions call. Returns the message dict; accumulates usage into meter."""
    body = json.dumps(payload).encode("utf-8")
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    last = None
    for attempt in range(TRANSPORT_RETRIES):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as r:
                out = json.loads(r.read().decode("utf-8"))
            u = out.get("usage") or {}
            now = datetime.now(timezone.utc)
            meter["calls"] += 1
            meter["prompt_tokens"] += u.get("prompt_tokens") or 0
            meter["completion_tokens"] += u.get("completion_tokens") or 0
            meter["cache_hit_tokens"] += u.get("prompt_cache_hit_tokens") or 0
            meter["reasoning_tokens"] += ((u.get("completion_tokens_details") or {})
                                          .get("reasoning_tokens") or 0)
            meter["usd"] += _cost(u, payload["model"], now) or 0.0
            ch = (out.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            msg["_finish_reason"] = ch.get("finish_reason")
            return msg
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            last = RuntimeError(f"HTTP {e.code}: {detail}")
            if e.code < 500 and e.code != 429:
                raise last                      # a 400 is a bug in the request, not weather
        except Exception as e:                  # noqa: BLE001
            last = e
        wait = 10 * (attempt + 1)
        print(f"    [retry {attempt+1}/{TRANSPORT_RETRIES} in {wait}s: {str(last)[:110]}]",
              flush=True)
        time.sleep(wait)
    raise last


def chat_with_tools_api(pack, out_dir, effort, key, meter):
    """Mirror of analyst_tools.chat_with_tools over the OpenAI-compatible API.

    DeepSeek-specific requirement (thinking-mode guide): when tools are in play, the assistant's
    reasoning_content must be passed back on EVERY subsequent request or the API returns 400.
    Ollama has no such rule, so this echo exists only to make the cloud transport legal.
    """
    # system = the RS2 framework the local tier bakes into its model; user = the pack (+TASK
    # +addendum, already appended by the caller). This mirrors the local prompt assembly exactly.
    msgs = [{"role": "system", "content": _rs2_framework()},
            {"role": "user", "content": pack}]
    snap, calls = [], 0
    t0 = time.time()
    report, thinking, finish = "", "", None
    while True:
        msg = _post({"model": MODEL, "messages": msgs, "tools": at.TOOLS,
                     "max_tokens": MAX_TOKENS, "reasoning_effort": effort, "stream": False},
                    key, meter)
        thinking += msg.get("reasoning_content") or ""
        finish = msg.get("_finish_reason")
        tcs = msg.get("tool_calls") or []
        if not tcs:
            report = msg.get("content") or ""
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "reasoning_content": msg.get("reasoning_content") or "", "tool_calls": tcs})
        for tc in tcs:
            calls += 1
            fn = tc.get("function") or {}
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:                   # noqa: BLE001
                args = {}
            if calls > at.MAX_TOOL_CALLS:
                result = {"error": f"tool-call budget exhausted ({at.MAX_TOOL_CALLS}); "
                                   "conclude with what you have"}
            elif name == "search_web":
                result = at.search_web(args.get("query", ""), args.get("why", ""), snap=snap)
            elif name == "fetch_page":
                result = at.fetch_page(args.get("url", ""), snap=snap)
            else:
                result = {"error": f"unknown tool {name}"}
            if name in ("search_web", "fetch_page"):
                q = args.get("query") or args.get("url") or ""
                print(f"    [tool {calls}] {name}: {str(q)[:88]}", flush=True)
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"),
                         "content": json.dumps(result)[:12000]})
        if calls > at.MAX_TOOL_CALLS:
            # Same rule as local: never break mid-conversation - re-ask WITHOUT tools so the
            # model must conclude. Breaking returned an empty report on the local arm.
            msgs.append({"role": "user", "content":
                         "Research budget is exhausted. Write the complete report NOW from what "
                         "you have. Mark anything you could not establish as [Unconfirmed] and "
                         "carry that uncertainty into your scenarios. Do not search again."})
            msg = _post({"model": MODEL, "messages": msgs, "max_tokens": MAX_TOKENS,
                         "reasoning_effort": effort, "stream": False}, key, meter)
            report = msg.get("content") or ""
            thinking += msg.get("reasoning_content") or ""
            finish = msg.get("_finish_reason")
            break
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "_research_snapshot.json").write_text(
        json.dumps({"model": MODEL, "seed": None, "_seed_note": "not sent: undocumented in the "
                    "DeepSeek API reference, so reproducibility is not claimed on this arm",
                    "rs2_framework_attached": True, "rs2_framework_chars": len(_rs2_framework()),
                    "tool_calls": calls, "elapsed_s": round(time.time() - t0), "calls": snap},
                   indent=2), encoding="utf-8")
    return report, thinking, {"tool_calls": calls, "finish_reason": finish,
                              "elapsed_s": round(time.time() - t0)}


def _searxng_up():
    try:
        u = at.SEARX + "/search?" + urllib.parse.urlencode({"q": "probe", "format": "json"})
        with urllib.request.urlopen(urllib.request.Request(u, headers=at.UA), timeout=8):
            return True
    except Exception:                       # noqa: BLE001
        return False


def _brief_age_days(t):
    """Age of the LOCAL research brief that build_pack folds in as SECTION 11, or None if absent.
    Reported because --fresh cannot refresh it: only the local rs2-research model writes it."""
    rb = ROOT / "research" / f"{t}.md"
    if not rb.exists():
        return None
    return round((time.time() - rb.stat().st_mtime) / 86400, 1)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: deep_api_run.py TICKER [--samples 3] [--effort high] "
                 "[--dir NAME | --fresh] [--model ID]")
    t = args[0].upper()
    n = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 3
    effort = sys.argv[sys.argv.index("--effort") + 1] if "--effort" in sys.argv else "high"
    fresh = "--fresh" in sys.argv
    if "--model" in sys.argv:
        global MODEL
        MODEL = sys.argv[sys.argv.index("--model") + 1]
    # An unpriced model makes _cost return None, and the caller's `or 0.0` then books the whole
    # run at $0.00 with no error. This checks the DEFAULT MODEL too, not just --model: a vendor
    # id change is exactly how an unpriced model gets here. Refuse rather than record a spend
    # figure that is false by construction.
    if MODEL not in PRICE:
        sys.exit(f"no published price for '{MODEL}' - add its peak $/1M to PRICE (off-peak is "
                 f"halved in _cost) before running. Priced: {', '.join(sorted(PRICE))}")
    src, local, brief_age, searx = None, {}, _brief_age_days(t), None

    if fresh:
        # FALLBACK PATH. Build the pack from current data exactly as consensus_valuation does -
        # same builder, same TASK, same addendum - so the only difference from a local run is
        # which model reads it and how fresh SECTION 11 is.
        searx = _searxng_up()
        pack = cap.build_pack(t) + "\n\n---\n\n" + cap.TASK + cap.RESEARCH_ADDENDUM
        fin = cv.rs2_data.load_json(cv.common.SD / "financials" / f"{t}.json") or {}
        price = cv.vb._num(fin.get("Price"))
        if not price:
            sys.exit(f"no price in the data pack for {t} - cannot judge a band against nothing")
        brief_msg = (f"research/{t}.md, {brief_age} days old (only the LOCAL model can refresh it)"
                     if brief_age is not None else "ABSENT - pack has no SECTION 11")
        searx_msg = "up" if searx else "UNREACHABLE - no web research beyond the pack"
        print("[deep-api] FALLBACK MODE - no local run replayed.", flush=True)
        print(f"[deep-api]   research brief: {brief_msg}", flush=True)
        print(f"[deep-api]   SearXNG: {searx_msg}", flush=True)
    else:
        # A/B PATH. Source of truth for the input is the local run's frozen pack: same bytes to
        # both models, or the comparison measures data drift instead of model difference.
        if "--dir" in sys.argv:
            src = LOCAL_CONSENSUS / sys.argv[sys.argv.index("--dir") + 1]
        else:
            cands = sorted(LOCAL_CONSENSUS.glob(f"{t}_*"))
            if not cands:
                sys.exit(f"no local deep run for {t} in {LOCAL_CONSENSUS} - replay needs one. "
                         f"For a ticker the local tier has not done, use --fresh.")
            src = cands[-1]
        pack = (src / "_pack.md").read_text(encoding="utf-8")
        local = json.loads((src / "consensus.json").read_text(encoding="utf-8"))
        price = local.get("price")  # the price the LOCAL arm was judged against, not today's

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = OUT / f"{t}_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "_pack.md").write_text(pack, encoding="utf-8")
    key = _api_key()
    meter = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0,
             "reasoning_tokens": 0, "usd": 0.0}
    print(f"[deep-api] {t} @ ${price} | {MODEL} effort={effort} | {n} samples | "
          f"pack {len(pack):,}ch from {'current data' if fresh else src.name} -> {d}", flush=True)
    if not fresh:
        print(f"[deep-api] local arm said: {local.get('verdict')} | median IV "
              f"{local.get('median_iv')} | spread {local.get('spread_pct')}%", flush=True)

    runs = []
    for i in range(1, n + 1):
        t0 = time.time()
        try:
            rep, think, meta = chat_with_tools_api(pack, d / f"sample{i}_research", effort,
                                                   key, meter)
        except Exception as e:                  # noqa: BLE001
            print(f"  sample {i}: FAILED {str(e)[:120]}", flush=True)
            continue
        if not (rep or "").strip():
            # Same failure the local arm hit on ANET s2: long reasoning, zero deliverable.
            # Local retries once with a perturbed seed; seeds do not exist here, so the retry
            # is a plain re-draw.
            print(f"  sample {i}: EMPTY report after {len(think):,}ch thinking - one retry",
                  flush=True)
            rep, think, meta = chat_with_tools_api(pack, d / f"sample{i}_research_retry", effort,
                                                   key, meter)
        (d / f"sample{i}.md").write_text(rep, encoding="utf-8")
        if think:
            (d / f"sample{i}_thinking.md").write_text(think, encoding="utf-8")
        truncated = meta.get("finish_reason") == "length"
        ivs = cv.extract_iv(rep, price)
        iv = st.median(ivs) if ivs else None
        ok, why, flags = cv.plausibility(iv, price, t)
        runs.append({"sample": i, "iv": iv, "all_iv_mentions": sorted(set(ivs))[:8],
                     "plausible": ok, "reasons": why, "flags": flags, "truncated": truncated,
                     "done_reason": meta.get("finish_reason"),
                     "tool_calls": meta.get("tool_calls"),
                     "thinking_chars": len(think), "report_chars": len(rep),
                     "thinking_share_of_output": (round(len(think) / (len(think) + len(rep)), 3)
                                                  if (think or rep) else None),
                     "chars": len(rep), "secs": round(time.time() - t0)})
        print(f"  sample {i}: IV ${iv if iv else '?'} | usable={ok} | "
              f"{meta.get('tool_calls')} tool calls (think {len(think):,}ch / "
              f"report {len(rep):,}ch)" + (f" ({'; '.join(why)})" if why else "")
              + (f" | flags: {', '.join(flags)}" if flags else "")
              + (" | TRUNCATED" if truncated else "")
              + f" | {round(time.time()-t0)}s | ${meter['usd']:.3f} cumulative", flush=True)

    good = [r for r in runs if r["iv"] and r["plausible"] and not r["truncated"]]
    ivs = [r["iv"] for r in good]
    spread = (max(ivs) / min(ivs) - 1) * 100 if len(ivs) >= 2 else None
    converged = bool(spread is not None and spread <= cv.TOL_PCT)
    med = st.median(ivs) if ivs else None
    verdict = ("USABLE - plausible and converged" if converged and med else
               "NOT USABLE - runs disagree beyond tolerance" if med and spread is not None else
               "NOT USABLE - no plausible sample")
    doc = {"ticker": t, "price": price, "model": MODEL, "think": effort,
           "mode": f"fixed_{n}", "samples_run": len(runs), "early_stop": False,
           "effective_tolerance_pct": cv.TOL_PCT,
           "generated_at": datetime.now(timezone.utc).isoformat(),
           "runs": runs, "n_plausible": len(good), "median_iv": med,
           "spread_pct": round(spread, 1) if spread is not None else None,
           "tolerance_pct": cv.TOL_PCT, "early_tolerance_pct": cv.EARLY_TOL_PCT,
           "converged": converged, "verdict": verdict,
           "median_mos_pct": round((med / price - 1) * 100, 1) if med and price else None,
           # band_verdict carries pack_revision onto the verdict and depth_triggers re-queues
           # anything below current, so a --fresh run must stamp the revision it actually built
           # against. A replay inherits the frozen pack's revision (absent = pre-versioning = 1).
           "pack_revision": cap.PACK_REVISION if fresh else local.get("pack_revision", 1),
           "arm": "cloud_api", "pack_source": "fresh" if fresh else "replay",
           "source_pack_dir": None if fresh else src.name,
           "research_brief_age_days": brief_age, "searxng_up": searx, "usage": meter,
           "_spread_caveat": "sampling mechanism differs from the local arm (no seeds, vendor "
                             "default sampler); spread is not comparable like-for-like"}
    (d / "consensus.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

    v = dp.band_verdict(doc)            # identical verdict rule as the local tier
    v["consensus_dir"] = d.name
    v["arm"] = "cloud_api"
    v["pack_source"] = doc["pack_source"]
    v["research_brief_age_days"] = brief_age
    v["searxng_up"] = searx
    (d / "verdict_depth.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
    # DELIBERATELY NOT WRITTEN: cache/depth_ledger.jsonl, cache/depth_overlay.json, reports/.
    # This arm is an experiment; nothing it produces may enter the live decision path.

    print(f"\n[deep-api] {t}: {str(v['direction']).upper()}"
          + (f" | band ${v['iv_band_low']}-${v['iv_band_high']} vs price ${price}"
             if v.get("iv_band_low") else "")
          + (f" | size {v['size_hint']}" if v.get("size_hint") else ""), flush=True)
    if fresh:
        print("[deep-api] FALLBACK verdict - cloud model, "
              + ("brief absent" if brief_age is None else f"brief {brief_age}d old")
              + (", SearXNG up" if searx else ", NO web research")
              + ". Not equivalent to a local depth verdict.", flush=True)
    else:
        lv = (json.loads((src / "verdict_depth.json").read_text(encoding="utf-8"))
              if (src / "verdict_depth.json").exists() else {})
        print(f"[deep-api] LOCAL said: {str(lv.get('direction','?')).upper()} | band "
              f"${lv.get('iv_band_low')}-${lv.get('iv_band_high')} | "
              f"median ${lv.get('median_iv')}", flush=True)
    print(f"[deep-api] {meter['calls']} API calls | {meter['prompt_tokens']:,} in "
          f"({meter['cache_hit_tokens']:,} cached) | {meter['completion_tokens']:,} out "
          f"({meter['reasoning_tokens']:,} reasoning) | ${meter['usd']:.3f}"
          f" | {'off-peak' if _off_peak(datetime.now(timezone.utc)) else 'PEAK'}", flush=True)
    print(f"[deep-api] -> {d / 'verdict_depth.json'}", flush=True)


if __name__ == "__main__":
    main()
