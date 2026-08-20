#!/usr/bin/env python3
"""capability_test.py — has the local model ever actually been ASKED to do the job?

Phase E recommended putting a frontier model in the depth tier. That recommendation embedded an
untested assumption: that the local model cannot do what the benchmark GOOG analysis did. RS2 has
never once asked it to. Every production constraint points the other way:

  * config.json think=False        — reasoning disabled to satisfy a format contract
  * S1 prompt "DO NOT select a valuation engine"
  * S3 prompt "The intrinsic value is NOT yours to compute"
  * FINAL_TASK "you may NEVER print a different value" than the engine header
  * AI_AUDIT_PROMPT treats the engine number as AUTHORITATIVE -> a model that CORRECTS a
    contaminated fair value is scored as a violation and the run repeats
  * stage carry truncated to 4,500 chars, severing cross-stage reasoning
  * the basis-decision evidence pack withheld capex/OCF/FCF (the `da` gate, defect D3)
  * financials/{T}.json fed FY figures labelled as current (defect D5)

This harness removes ALL of those and gives the model the same conditions the benchmark had:
honest, correctly-period-labelled data; the full RS2 framework (baked into the model); thinking
ON; one long context; and ownership of BOTH the engine choice and the intrinsic value.

It is deliberately NOT hinted. The pack contains no mention of one-off gains, no pre-computed
base_cf, no fair value. Whether the model notices that TTM net income ($244.2B) exceeds TTM
operating cash flow ($185.7B), and that one quarter printed a 93.6% net margin, is exactly what
is being measured.

Output: ab_reports/capability_test/{TICKER}_{ts}/ — isolated, never ingested by the overlay.

  python tools/audit_202608/capability_test.py GOOG
"""
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import rs2_data  # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
OUT = HERE / "ab_reports" / "capability_test"
CTX = 65536          # default; --ctx overrides. Pair large values with OLLAMA_KV_CACHE_TYPE=q8_0
# num_predict covers THINKING + CONTENT together. MEASURED 2026-08-20 (arm B): at think=max the
# model spent ~30k tokens reasoning and was cut off at SECTION 2.5 of 12 with only ~2k left for
# the report. A full RS2 report needs ~12k of content, so budget generously or the deliverable
# is silently truncated and looks like a quality failure.
MAX_TOKENS = 49152
TIMEOUT = 14400


def _b(v):
    return f"${v/1e9:,.3f}B" if isinstance(v, (int, float)) else "not available"


def build_pack(t):
    """Honest, correctly-period-labelled facts. No derived valuation, no hints."""
    L = [f"# VERIFIED DATA PACK — {t}", ""]

    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    cm = fin.get("Calculated_Metrics") or {}
    price, shares = fin.get("Price"), fin.get("Shares_Outstanding")
    L += ["## MARKET (as fetched " + str(fin.get("Data_Fetched_Date")) + ")",
          f"- Price: ${price}", f"- Shares outstanding: {shares:,}" if shares else "- Shares: n/a",
          f"- Market cap: {_b(fin.get('Market_Cap'))}",
          f"- Beta (aggregator): {cm.get('Beta')}",
          f"- Cash & equivalents ONLY (excludes marketable securities): {_b(fin.get('Total_Cash'))}",
          f"- Total debt: {_b(fin.get('Total_Debt'))}",
          f"- Stock-based comp (TTM): {_b(fin.get('SBC_Stock_Based_Comp'))}", ""]

    ttm = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {}).get(t) or {}
    f = ttm.get("fields") or {}
    L += [f"## TRAILING TWELVE MONTHS (SEC 10-Q derived; through {ttm.get('through')}, "
          f"filed {ttm.get('filed')})",
          f"- Revenue: {_b(f.get('revenue'))}", f"- Net income: {_b(f.get('net_income'))}",
          f"- Operating cash flow: {_b(f.get('ocf'))}", f"- Capital expenditure: {_b(f.get('capex'))}",
          f"- Free cash flow: {_b(f.get('fcf'))}",
          f"- Depreciation & amortisation: {_b(f.get('da'))}"
          + ("   <- ABSENT from our SEC extract for this name" if f.get("da") is None else ""), ""]

    q = (rs2_data.load_json(SD / "fundamentals_quarterly.json") or {}).get("tickers", {}).get(t) or {}
    qs = (q.get("quarters") or [])[-8:]
    if qs:
        L += ["## QUARTERLY (10-Q filings, most recent last)",
              "| period end | revenue | net income | YoY revenue |", "|---|---|---|---|"]
        for r in qs:
            L.append(f"| {r.get('period_end') or r.get('end') or '?'} | {_b(r.get('revenue'))} | "
                     f"{_b(r.get('net_income'))} | "
                     f"{r.get('yoy_revenue') if r.get('yoy_revenue') is not None else 'n/a'} |")
        L.append("")

    h = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers", {}).get(t) or {}
    if h:
        yrs = sorted(int(y) for y in h)[-8:]
        L += ["## FISCAL-YEAR HISTORY (SEC companyfacts)",
              "| FY | revenue | net income | OCF | capex | FCF | D&A | equity |", "|---|---|---|---|---|---|---|---|"]
        for y in yrs:
            r = h[str(y)]
            L.append(f"| {y} | {_b(r.get('revenue'))} | {_b(r.get('net_income'))} | {_b(r.get('ocf'))} "
                     f"| {_b(r.get('capex'))} | {_b(r.get('fcf'))} | {_b(r.get('da'))} "
                     f"| {_b(r.get('equity'))} |")
        L.append("")

    ob = rs2_data.load_json(HERE / "cache" / f"openbb_{t}.json") or {}
    if ob:
        fg = ob.get("forward_growth") or {}
        L += ["## MARKET / CONSENSUS DATA",
              f"- Trailing P/E: {ob.get('pe_ratio')}   |  ROE: {ob.get('roe')}  |  P/B: {ob.get('pb_ratio')}",
              f"- Consensus forward growth: revenue CAGR {fg.get('revenue_cagr')}, "
              f"EPS CAGR {fg.get('eps_cagr')}  (source {fg.get('source')})"]
        en = rs2_data.load_json(HERE / "enrich" / f"{t}.json") or {}
        if en:
            # KEY BUG, found 2026-08-20 by auditing the reports: these read target_* while
            # enrich/{T}.json stores analyst_target_*. Every pack built before this fix showed
            # "low None / mean None" — data we HAD, withheld from the model by a typo, which is
            # the same defect class as the da-gate in run_rs2. Meanwhile the plausibility guard
            # was judging the output against those very targets via vb._consensus_band, i.e.
            # scoring the model on evidence it was never given.
            L.append(f"- Analyst targets: low {en.get('analyst_target_low')} / "
                     f"mean {en.get('analyst_target_mean')} / "
                     f"median {en.get('analyst_target_median')} / "
                     f"high {en.get('analyst_target_high')}")
            L.append(f"- 52-week range: {en.get('fifty_two_week_low')} - {en.get('fifty_two_week_high')}")
            L.append(f"- Short % float: {en.get('short_percent_float')}  |  "
                     f"Institutions: {en.get('held_percent_institutions')}")
        tr = ob.get("earnings_transcript") or ob.get("transcript_excerpt")
        if tr:
            L += ["", "## LATEST EARNINGS CALL EXCERPT", str(tr)[:6000]]
        L.append("")

    sector, industry = rs2_data.sector_lookup(t)
    L += [f"## CLASSIFICATION", f"- Sector: {sector} | Industry: {industry}", ""]

    rb = HERE / "research" / f"{t}.md"
    if rb.exists():
        L += ["## RESEARCH BRIEF (web, cited)", rb.read_text(encoding="utf-8", errors="replace")[:14000], ""]
    return "\n".join(L)


TASK = """You are performing a complete RS2 v2.0 equity analysis. T0 is today's price in the data
pack below.

YOU OWN THE ENTIRE ANALYSIS. Specifically, and unlike any constraint you may infer:
  * YOU select the valuation engine (Steps 0-2..0-4). Nothing has been pre-selected.
  * YOU compute intrinsic value. No backbone has computed it for you. There is no engine header
    to defer to and no pre-computed fair value, margin of safety or expectations gap.
  * YOU decide what cash-flow definition is appropriate and YOU build the forecast path — do not
    reduce the company to a single trailing number unless you can defend that as the right method.
  * Apply the framework's data-discipline rules to the pack itself. The data is what our systems
    hold; judge its reliability as you would any source.

Produce the full report, SECTION 0 through SECTION 12, per the framework's FINAL OUTPUT
STRUCTURE. Show your explicit forecast (per-year revenue, margin, capex, D&A or their
equivalents) and your discount-rate derivation. End with SECTION 12 Final Execution Opinion.

SOURCE EVERY FORECAST DRIVER. For each of revenue growth, margin, capital expenditure and
discount rate, state where the number came from: a figure in the data pack, a figure you
retrieved, or your own assumption. Any driver you cannot source is an [Assumption] and must be
labelled one.

Pay particular attention to periods BEYOND the data you were given. A guidance figure that
covers only the current year tells you nothing about later years, and quietly extending a
trend across a decade is the single easiest way to decide a valuation by accident. If the path
of a driver after the guided period is not established, say so, and show what the valuation
does across the plausible range instead of picking one silently.

Think carefully before writing. Numbers before narrative."""

# Appended ONLY when the analyst is given search tools (consensus_valuation --tools).
RESEARCH_ADDENDUM = """

RESEARCH RULES — you have web search available, so DO NOT ASSUME WHAT YOU CAN LOOK UP.

1. When your reasoning needs a fact you do not have, SEARCH FOR IT. Do not substitute an
   assumption, a trend extrapolation, or a "reasonable" placeholder. This applies especially to
   forward-looking drivers: guidance for years beyond the data pack, capital-expenditure plans,
   management commentary on future spending, competitor capacity, regulatory outcomes, and
   current macro (rates, policy).
2. Search DURING your reasoning, not after you have decided. A number found to justify a
   conclusion you already reached is not evidence.
3. NEVER search to re-source financial-statement figures already in your pack. Revenue, net
   income, operating cash flow, capital expenditure, free cash flow and share counts come from
   SEC filings and are authoritative — a web page restating them is less reliable, not more.
   Search for what the filings CANNOT tell you: the future, and the outside world.
4. Cite what you retrieve. Every retrieved figure gets its source named inline, and stays
   [Actual] only if it came from the company or a regulator; a secondary report is [Estimate].
5. If you search and still cannot establish a number, that is a legitimate finding: mark it
   [Unconfirmed], state what you could not resolve, and carry the uncertainty into your
   scenarios rather than burying it in a point estimate."""


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "GOOG").upper()
    model = _arg("--model", CONFIG["model"])
    ctx = int(_arg("--ctx", CTX))
    # Ollama accepts true/false/low/medium/high/max. MEASURED 2026-08-20: `true` yields the
    # same trace length as `low` (1,837 vs 1,770 chars) while medium/high/max give ~50% more
    # (2,540/2,713/2,652) — so `think: true` is NOT the model's default xhigh. Qwen3.8's own
    # chat template defaults to xhigh, which Ollama does not expose; "max" is its request for
    # the model's highest level. Depth tier should use "max".
    think = _arg("--think", "max")
    if think in ("true", "false"):
        think = think == "true"
    label = _arg("--label", f"{model.replace(':','_').replace('/','_')}-{think}")
    # Sampling: omitted entirely unless overridden, so the MODELFILE's profile governs.
    # rs2-analyst-deep bakes Qwen's thinking profile (0.6 / 0.95 / no penalties).
    temp = _arg("--temp")

    pack = build_pack(t)
    content = f"{pack}\n\n---\n\n{TASK}"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = OUT / f"{t}_{ts}_{label}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "_pack.md").write_text(content, encoding="utf-8")
    print(f"[capability] {t} | model={model} think={think} ctx={ctx} | "
          f"pack {len(content):,} chars -> {d}", flush=True)

    opts = {"num_ctx": ctx, "num_predict": int(_arg("--num-predict", MAX_TOKENS))}
    if temp is not None:
        opts["temperature"] = float(temp)
    # --qwen-thinking applies Qwen's official thinking-mode profile as a REQUEST override, so a
    # model whose Modelfile bakes the non-thinking profile (production rs2-analyst: 0.4/0.9 with
    # presence 0.1 / repeat 1.05) can be tested on equal footing. Penalties go to zero: Qwen
    # documents that on long reasoning traces a repetition penalty bans common-but-necessary
    # tokens and degenerates the completion.
    if "--qwen-thinking" in sys.argv:
        opts.update({"temperature": float(temp) if temp is not None else 0.6, "top_p": 0.95,
                     "top_k": 20, "min_p": 0, "presence_penalty": 0.0, "repeat_penalty": 1.0})
    body = {"model": model, "stream": False, "think": think,
            "messages": [{"role": "user", "content": content}], "options": opts}
    req = urllib.request.Request(
        f"{CONFIG.get('ollama_url', 'http://localhost:11434')}/api/chat",
        data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))
    msg = resp.get("message") or {}
    out, think = msg.get("content") or "", msg.get("thinking") or ""
    (d / "REPORT.md").write_text(out, encoding="utf-8")
    if think:
        (d / "_thinking.md").write_text(think, encoding="utf-8")
    print(f"[capability] done in {time.time()-t0:.0f}s | report {len(out):,} chars | "
          f"thinking {len(think):,} chars -> {d/'REPORT.md'}", flush=True)


if __name__ == "__main__":
    main()
