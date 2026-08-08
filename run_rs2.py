#!/usr/bin/env python3
"""
run_rs2.py — Python orchestrator for the local RS2 pipeline.

Replaces the manual-data flow of Run-RS2.ps1. For one ticker it:
  1. (optional) enrich_ticker.py   -> enrich/{T}.json   (yfinance behavioral)
  2. (optional) research_agent.py  -> research/{T}.md    (AgentWebSearch, Chrome)
  3. rs2_data.build_data_context   -> verified fed-data payload
  4. drives the staged rs2-analyst pipeline (6 stages + final assembly) over
     Ollama's REST API, with thinking on, feeding each stage the fed data +
     prior-stage results, then writes the report tree.

System prompt (RS2.txt) is baked into the `rs2-analyst` model, so each stage's
user message = [fed data] + [prior-stage results] + [stage task].

CLI:
  python run_rs2.py NVDA
  python run_rs2.py NVDA --no-research          # skip web search
  python run_rs2.py NVDA --no-enrich --no-research
  python run_rs2.py NVDA --name "NVIDIA Corporation"
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import ops                 # telegram alerts + verified VRAM unload barrier (stdlib-only)
import rs2_data            # local injector
import valuation_engine    # deterministic IV/MoS math (Engine 4/2 + dcf primitives)
import valuation_backbone  # deterministic reverse-DCF backbone (owns base_cf/growth/WACC)
import valuation_io        # LLM-assumption JSON extraction

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# INVERTED ARCHITECTURE (AUDIT.md C2): the deterministic reverse-DCF BACKBONE
# (valuation_backbone.py) owns base_cf/growth/WACC/IV. The model NO LONGER guesses DCF inputs.
# For a DCF-able name it emits only a believability STANCE on the price-implied growth.
# Only the cases the backbone returns NULL for (pre-profit option-led / financials) ask the
# model for value numbers — the one place its numeric judgment is legitimate.
STANCE_SCHEMA = ('{"valuation_stance":"undervalued|fair|overvalued",'
                 '"implied_growth_achievable":"low|medium|high","rationale":"<=240 chars"}')
ENGINE4_SCHEMA = ('{"engine":4,"core_value":<proven-business $/share>,'
                  '"options":[{"prob":<0-1>,"value":<$/share if it works>}],"drag":<$/share>}')
ENGINE2_SCHEMA = '{"engine":2,"normalized_eps":<$>,"normal_multiple":<10-25>}'
# Engine 5 / rNPV: the model supplies ONLY the development phase (closed set) and the per-share
# value if the asset is approved. Probability of approval, the net-cash floor and the dilution
# drag are all computed deterministically (valuation_backbone.PHASE_POS / rnpv).
ENGINE5_SCHEMA = ('{"engine":5,"phase":"preclinical|phase1|phase2|phase3|filed",'
                  '"value_if_approved_ps":<$/share if the lead asset is approved>}')
PROBS_SCHEMA = '{"bear":0.25,"base":0.50,"bull":0.25}'

STAGES = [
    ("S1_macro_classify", "Layers 0, 1, 1.5 — Classification / Macro / Base Rate",
     "Execute LAYER 0, LAYER 1, and LAYER 1.5 ONLY. Determine the ARCHETYPE (Step 0-1) FROM FIRST "
     "PRINCIPLES using the CLASSIFICATION CONTEXT (GICS sector) — the reverse-triage archetype is "
     "only a low-confidence hint. DO NOT select a valuation engine: the valuation METHOD is already "
     "determined by a deterministic backbone and stated in your context (reverse-DCF on owner "
     "earnings for most names — mid-cycle NORMALIZED for cyclical sectors "
     "(Energy/Materials/Industrials); justified P/B-ROE for financials). Skip the framework's "
     "engine-selection steps (0-2..0-4) entirely — no 'Selected Engine' output, no engine "
     "comparisons. Then full macro context with the 4-regime probability distribution (must sum "
     "100%) and sensitivity matrix, and the base-rate / historical-pattern check. Use the verified "
     "MACRO CONTEXT — do not recall macro from memory. STOP after Layer 1.5."),
    ("S2_quality", "Layers 2, 2.5 — Business Quality / Adjusted Financials",
     "Execute LAYER 2 and LAYER 2.5 ONLY. Business understanding, 7-type moat score + direction, "
     "Lynch classification, financial strength scorecard, capital-allocation scorecard, and "
     "intangibles-adjusted (R&D cap, SBC, leases, adjusted ROIC, owner earnings). Use ONLY the "
     "fed financial figures. STOP after Layer 2.5."),
    ("S3_valuation", "Layers 3, 3.5 — Expectations Test / Second-Order",
     "Execute LAYER 3 and LAYER 3.5 ONLY. The intrinsic value is NOT yours to compute — a deterministic "
     "BACKBONE (see the VALUATION block) already did it: for most names it shows the cash-flow growth the "
     "CURRENT PRICE implies vs the growth DEMONSTRATED (the EXPECTATIONS GAP); for FINANCIALS it shows the "
     "ROE the price implies vs the ROE delivered (the ROE gap).\n"
     "YOUR job is the analyst judgment the math cannot make: is that price-implied growth (or ROE) "
     "ACHIEVABLE / SUSTAINABLE? Reason from the moat (Stage 2), the RESEARCH BRIEF (competitive response, "
     "demand, bear case), end-market TAM, reinvestment runway, unit economics, and any embedded OPTIONALITY "
     "(a scarce asset or secular tailwind can justify a gap that trailing numbers do not). Then second-order "
     "effects. Numbers before narrative: anchor every claim to the fed data / brief.\n"
     "STANCE CALIBRATION (match the VALUATION block): a SMALL gap (≈ ≤5 pts) on a durable franchise is FAIR "
     "— a modest premium for quality is normal, NOT overvalued. Reserve OVERVALUED for a LARGE gap (~≥12 pts) "
     "the evidence can't support, OR a smaller gap with clear DETERIORATION (declining guidance, eroding "
     "moat). A NEGATIVE gap with an intact moat => undervalued. Be disciplined, not reflexively bearish.\n"
     "ENTRY DISCIPLINE (do not chase): if the VALUATION block shows the price is AT/ABOVE the analyst "
     "consensus fair value or the realistic MoS is thin (<15%), a great business is still FAIR here — a "
     "Hold / stage-in-on-weakness, NOT a fresh full BUY. 'undervalued' requires a genuine MoS, not just a "
     "negative growth gap on a stock already at analyst targets.\n"
     "At the very END output exactly ONE fenced ```json block:\n"
     "  • If the VALUATION block shows an EXPECTATIONS MODEL (growth gap OR financial ROE gap):\n"
     f"```json\n{STANCE_SCHEMA}\n```\n"
     "  • ONLY if it showed an rNPV SCAFFOLD (pre-profit clinical biotech, Engine 5): give the "
     "development phase of the LEAD asset and the per-share value IF it is approved — "
     f"```json\n{ENGINE5_SCHEMA}\n``` Do NOT supply a probability: the phase base rate, the "
     "net-cash floor and the dilution drag are computed for you. Ground the phase in the RESEARCH "
     "BRIEF; if the lead asset's phase is genuinely unclear, choose the EARLIER phase.\n"
     "  • ONLY if it said 'No DCF model — PRE-PROFIT / OPTION-LED' (Engine 4): value the option bridge "
     f"instead — ```json\n{ENGINE4_SCHEMA}\n``` (core/options/drag PER SHARE, $; probs base-rate disciplined; "
     "IV = core + Σ(prob×value) − drag, computed for you).\n"
     "  • ONLY if it said 'No cash-flow DCF … this is a FINANCIAL', or 'the company IS profitable, but "
     "capex exceeds D&A' (a REINVESTMENT profile — profitable, so NOT an option bridge), with no "
     "deterministic model: value on "
     f"normalized earning power instead — ```json\n{ENGINE2_SCHEMA}\n``` (normalized_eps = through-cycle "
     "EPS $/share from the fed data; normal_multiple 10-25 justified by ROE vs cost of equity; "
     "IV = eps × multiple, computed for you).\n"
     "STOP after the json block."),
    ("S4_scenarios", "Layers 4, 4.5 — Scenarios (Bayesian) / Horizon Arbitrage",
     "Execute LAYER 4 and LAYER 4.5 ONLY. Frame the three scenarios around the EXPECTATIONS GAP from "
     "the VALUATION block: bear = the price-implied growth is MISSED (thesis breaks / gap proves too "
     "rich); base = roughly MET; bull = MET-or-EXCEEDED (the optionality/acceleration plays out). Do the "
     "Bayesian reasoning — update each scenario's probability from the Stage-1 base rates and the "
     "research evidence — and the market-implied vs my-horizon arbitrage (does the market's time "
     "preference misprice this?).\n"
     "At the very END output exactly one fenced ```json block of probabilities (must sum to 1.0, "
     "base = highest):\n"
     f"```json\n{PROBS_SCHEMA}\n```\nSTOP after the json block."),
    ("S5_conviction", "Layers 5, 5.5, 6, 6.5 — Conviction / Behavioral / Portfolio / Kelly",
     "Execute LAYER 5, LAYER 5.5, LAYER 6 (portfolio fit) and LAYER 6.5 (Kelly sizing) ONLY. "
     "Conviction /15 + decay note + sizing; behavioral & positioning using the fed BEHAVIORAL DATA "
     "(short interest, ownership, options skew) — tag [Unconfirmed] only where truly absent; "
     "portfolio fit; Kelly size.\n"
     "CONVICTION DISCIPLINE: score 'Valuation attractiveness' from the ENTRY DISCIPLINE / ENTRY EDGE "
     "line in the VALUATION block, which ranks this name's margin of safety against the ANALYSED BOOK "
     "rather than an absolute bar. If it says the name is in the EXPENSIVE THIRD, dock that component "
     "hard — a superb business with no entry edge relative to the alternatives is not a 12+. If it "
     "says the name has better-than-median entry, do NOT reflexively dock: judge conviction on business "
     "quality, moat durability and the research evidence, and be willing to use the FULL 1-15 range.\n"
     "Conviction is a RANKING, not a grade. If most names score 7-9 the score conveys nothing — an "
     "average book should spread across the range, and a genuinely exceptional business with a real "
     "entry edge SHOULD reach 12+. Justify the number you give against those two axes explicitly.\n"
     "If Layer 5 vs 6.5 sizing gap > 20pp, flag. STOP after Layer 6.5."),
    ("S6_redteam_audit", "Layers 7, 7.5, 8, 9 — Monitoring / Correlation / Audit / Red Team",
     "Execute LAYER 7, LAYER 7.5, LAYER 8 and LAYER 9 ONLY. Thesis-integrity KPIs + thresholds, "
     "pre-mortem (3 failure modes + early-warning indicators), decision-journal entry; "
     "correlation-adjusted risk; the 37-point audit (pass/fail per group A-G); and the Red Team "
     "(short thesis 5-7 bullets grounded in the RESEARCH BRIEF's short-seller/regulatory items, "
     "long-vs-short logic combat, adversarial data, killed arguments). STOP after Layer 9."),
]

FINAL_TASK = (
    "You now have the complete worked analysis from all prior stages (provided above). Assemble the "
    "FINAL REPORT exactly per 'FINAL OUTPUT STRUCTURE (v2.0)': SECTION 0 through SECTION 12, fixed "
    "order, in a SINGLE code block. Do not re-derive — consolidate the numbers already produced. "
    "Enforce all 14 FINAL MANDATORY RULES. End with SECTION 12 Final Execution Opinion "
    "(Action, Conviction, Weight %, Strategy). Output in English.\n\n"
    "TWO STRUCTURAL REQUIREMENTS THE POST-COMPLETION AUDITOR REJECTS THE REPORT WITHOUT "
    "(the whole run repeats on rejection):\n"
    "A. Wherever the report presents fair value or margin of safety (Sections 4 and 11), the "
    "PRIMARY figures MUST be the authoritative fair value and MoS quoted verbatim from the "
    "VALUATION RESULT / VERIFIED ANCHOR. A scenario-weighted or supplementary value may appear "
    "ONLY alongside them, explicitly labeled 'scenario-weighted'. Never print a different number "
    "as 'Intrinsic Value' or 'Margin of Safety' in their place.\n"
    "B. If the analysis contains a CYCLICALITY CHECK (two bases disclosed), SECTION 3 MUST "
    "include one explicit sentence beginning 'Basis judgment:' stating which basis (latest-FY "
    "or mid-cycle) you judge fairer and why.\n\n"
    "AFTER the report code block, output exactly ONE fenced ```json block (machine-read; the "
    "prose stays for humans):\n"
    "```json\n{\"stance\": <1-5>, \"thesis_break\": <true|false>}\n```\n"
    "stance rubric — 5: BUY NOW (fresh full entry justified at today's price); 4: ACCUMULATE ON "
    "DIPS / stage in (constructive, prefer weakness); 3: HOLD (no strong directional view — let "
    "the numbers rank it); 2: REDUCE / avoid new money; 1: EXIT / sell. Adjacent phrasings of the "
    "same view MUST map to the same number. thesis_break: true ONLY for a structural, "
    "thesis-invalidating event (credible fraud/accounting signs, guidance collapse, moat rupture) "
    "— it forces an exit review regardless of valuation."
)


# ── Ollama REST ───────────────────────────────────────────────────────────
API_MODE = False      # --api: route every LLM call to api_llm/api_chat.py (cloud model) instead of Ollama


def ollama_chat(content, ctx, think=True, retries=2, temperature=None, timeout=600, max_tokens=None):
    if API_MODE:
        import api_llm.api_chat as api_chat
        return api_chat.api_chat(content, ctx=ctx, think=think, retries=retries,
                                 temperature=temperature, timeout=timeout, max_tokens=max_tokens)
    opts = {"num_ctx": ctx}
    if temperature is not None:
        opts["temperature"] = temperature  # override the model's baked temp (valuation stages want precision)
    body = json.dumps({
        "model": CONFIG["model"],
        "stream": False,
        "think": think,
        "messages": [{"role": "user", "content": content}],
        "options": opts,
    }).encode("utf-8")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(CONFIG["ollama_endpoint"], data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            txt = out.get("message", {}).get("content", "")
            if not txt.strip():
                # a 200 with empty content (VRAM-pressure failure mode) must retry/raise like any
                # other error — returning "" let an empty FINAL stage ship a degenerate verdict
                # as a "success" that overwrote the ticker's real call with no retry
                raise RuntimeError("Ollama returned 200 with empty message.content")
            return txt
        except Exception as e:
            last = e
            # transient Ollama 500s happen on context-size reloads / VRAM pressure
            wait = 8 * (attempt + 1)
            print(f"   [ollama retry {attempt+1}/{retries} after {wait}s: {str(e)[:80]}]", flush=True)
            time.sleep(wait)
    raise last


def keep_awake(on=True):
    """Block Windows SLEEP while a run is active — SYSTEM only, NOT the display. This box exposes no
    S0/S3 standby (only Hibernate, see `powercfg /a`), so a dark monitor does NOT enter Connected
    Standby / throttle background apps; the display is therefore left free to power off per the OS
    idle timeout while the run keeps going. SetThreadExecutionState(ES_SYSTEM_REQUIRED) holds the
    system awake; released (ES_CONTINUOUS alone) when the run ends. No-op off Windows."""
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) if on else ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def unload_model(name):
    """Force-free a model's VRAM and BLOCK until it is provably free. CRITICAL on this box:
    rs2-analyst and rs2-research are both ~23GB on a 24GB card, so they cannot co-reside.

    The old version POSTed keep_alive:0 and slept 2s. That 200 only means the request
    finished — ollama tears the llama-server subprocess down asynchronously, and destroying
    a 23GB CUDA context takes longer than 2s under load. The next load then raced the
    teardown and OOM'd ('cudaMalloc failed: out of memory'), which LDR wrote into
    research/{T}.md as if it were research. ops.wait_unloaded polls /api/ps + free VRAM
    until the release is an observed fact, so the race cannot happen.

    Returns True if the VRAM is confirmed free. A False return means the caller must NOT
    load the other model on top of it."""
    if not name or (API_MODE and name == CONFIG.get("model")):   # analyst never loaded in --api mode
        return True
    ok, detail = ops.wait_unloaded(
        CONFIG["ollama_endpoint"], name,
        need_free_mb=int(CONFIG.get("vram_free_required_mb", 20000)),
        timeout_s=int(CONFIG.get("vram_unload_timeout_s", 180)))
    if ok:
        print(f"[vram] unloaded {name} — {detail}", flush=True)
    else:
        print(f"[vram] ::UNLOAD FAILED:: {name} — {detail}", flush=True)
        ops.notify_telegram(
            f"[RS2 ops] vram_unload_failed — model={name} {detail}. "
            f"Loading the other ~23GB model now would OOM; the run is aborting this ticker.")
    return ok


# ── pre-steps (data acquisition) ──────────────────────────────────────────
def get_assumptions(stage_out, require_key, validator, schema_hint):
    """Parse the LLM's assumption JSON; one repair re-prompt on failure."""
    obj = valuation_io.extract_json(stage_out, require_key)
    if obj is not None and validator(obj):
        return obj
    fix = ollama_chat(
        f"Return ONLY a valid JSON object matching this schema, nothing else:\n{schema_hint}\n\n"
        f"Extract the numbers from this analysis:\n{stage_out[-4000:]}",
        8192, think=False)
    obj = valuation_io.extract_json(fix, require_key)
    return obj if (obj is not None and validator(obj)) else None


# ── INVERTED valuation: deterministic backbone + model judgment (AUDIT.md C2) ──
def _valid_stance(d):
    return isinstance(d, dict) and str(d.get("valuation_stance", "")).lower() in (
        "undervalued", "fair", "overvalued")


def _valid_engine4(d):
    # The OPTIONS entries must be checked too, not just core_value. engine4_bridge does
    # float(o.get("value", 0)), and a null value there raises TypeError and kills the whole run
    # (seen live on CRSP: the model emitted an option with value null). Rejecting the payload
    # here falls through to "unvalued", which is a bad valuation instead of a dead ticker.
    if not (isinstance(d, dict) and int(d.get("engine", 0) or 0) == 4
            and isinstance(d.get("core_value", None), (int, float))):
        return False
    opts = d.get("options")
    if opts is None:
        return True
    if not isinstance(opts, list):
        return False
    return all(isinstance(o, dict) and isinstance(o.get("prob", None), (int, float))
               and isinstance(o.get("value", None), (int, float)) for o in opts)


# base_cf kinds anchored to the LATEST fiscal year — these are the ones a cyclical archetype
# should see mid-cycle-averaged alongside. midcycle_* is already averaged and ffo_reit is a REIT
# measure. blended_owner_earnings belongs here: the blend is 0.5x latest-FY OE + 0.5x latest-FY
# revenue x median margin — BOTH terms scale with the latest year, so a trough/peak year still
# dominates it. (Regression 2026-08-08: the blend rename silently emptied this gate and the
# cyclical disclosure stopped firing — MU routing.json logged not_a_single_year_base_cf x6.)
_LATEST_FY_KINDS = ("owner_earnings", "blended_owner_earnings", "fcf_fallback",
                    "ocf_minus_da_proxy", "fcf_ttm_yf")


# Canonical archetype names (rs2_data.ARCHETYPE_NAMES), hyphen/space tolerant. Order matters:
# C ("cyclical") LAST because it is the word most likely to appear incidentally next to another
# name ("B. Quality Compounder (with explicit Cyclical Overlay)").
_ARCH_NAME_PATS = (
    ("A", r"stable[\s-]+incumbent"),
    ("B", r"quality[\s-]+compounder"),
    ("D", r"product[\s-]+platform"),
    ("E", r"option[\s-]+led"),
    ("F", r"(?:pure[\s-]+)?regulatory"),
    ("C", r"cyclical"),
)
# Optional "C. " / "D) " / "C " menu prefix, then optional "(" — anchored so a name later in the
# line ("...with Quality Compounder characteristics") can never hijack the match.
_ARCH_PREFIX = r"(?:[A-F]\s*[.):]?\s*)?[(\s]*"


def _arch_letter_form(text):
    """'Archetype X ...' at the start of a value/line -> letter; an adjacent NAME overrides the
    letter (seen live on MU: '**Archetype Verdict:** **D. Cyclical**' — the letter is a
    menu-index slip, the name is what the model actually reasoned about -> C)."""
    m = re.match(r"Archetype\s+([A-F])\b(.{0,50})", text)
    if not m:
        return None
    for L, pat in _ARCH_NAME_PATS:
        if re.search(pat, m.group(2), re.I):
            return L
    return m.group(1)


def _arch_value(head):
    """Archetype letter from a declaration VALUE ('C. Cyclical', 'Archetype C (Cyclical)',
    'Cyclical', bare 'C'), or None. Letter match is CASE-SENSITIVE so the article 'a' in prose
    values ('a strong cyclical...') cannot read as archetype A."""
    head = head.strip()[:80]
    r = _arch_letter_form(head)
    if r:
        return r
    for L, pat in _ARCH_NAME_PATS:
        if re.match(_ARCH_PREFIX + pat, head[:60], re.I):
            return L
    lm = re.match(r"([A-F])(?=[.):\s]|$)", head)
    return lm.group(1) if lm else None


def _archetype(stage_text):
    """Archetype letter (A-F) the model chose in Stage 1, or None.

    Measured over the FULL S1 corpus (1,417 archived stage files, 2026-08-08) against the
    previous parser: unparsed 162 -> 9 (0.6%; all nine verified prose-only declarations with no
    canonical name or letter — anything but None there is a guess), zero regressions, and five
    prior MISparses fixed (CRS B->C, ENS D->C, MU E->C, SNA B->C, TTMI B->C — every one a
    transition/overlay phrase hijacking the old loose line scan). Tonight's MU repeats: 9/9 C,
    including two '**Archetype Verdict:** **D. Cyclical**' letter/name contradictions.

    Tiers, most explicit first; every tier is anchored to declaration-shaped text, never a scan
    of justification prose (AAPL's rationale "distinct from Stable Incumbent (A) or Option-Led
    (E) profiles" must not read as A):
      T1  "Archetype [Verdict|Selection|...]: <value>"  — colon after the Archetype label.
      T2  line-anchored forms: "Archetype C (Cyclical) [Actual]", "Cyclical (Archetype C)",
          "Classification/Selected/Verdict: <value>". Lines containing "triage" or "reject"
          are skipped (ARM: "Reverse-triage Archetype A ... is rejected").
      T3  the survival-probability template ("Probability of a <NAME> ... surviving"), name only.
    """
    seg = stage_text[:6000]
    for m in re.finditer(r"\bArchetype\b[^\n:]{0,40}:([^\n]*)", seg, re.I):
        r = _arch_value(re.sub(r"[*_`]", " ", m.group(1)))
        if r:
            return r
    for ln in seg.splitlines():
        low = ln.lower()
        if "triage" in low or "reject" in low:
            continue
        if re.search(r"\bArchetype\b[^\n:]{0,40}:", ln, re.I):
            continue  # T1-shaped: already tried above
        cl = re.sub(r"[*_`]", " ", ln)
        cl = re.sub(r"^[\s\-•■#>\d.()\[\]]*", "", cl)
        cl = re.sub(r"^\[?actual\]?\s*", "", cl, flags=re.I).strip()
        r = _arch_letter_form(cl)
        if r:
            return r
        m = re.match(r"([A-Za-z /-]{3,40})\(\s*Archetype\s+([A-F])\s*\)", cl)
        if m:
            for L, pat in _ARCH_NAME_PATS:
                if re.search(pat, m.group(1), re.I):
                    return L
            return m.group(2)
        m = re.match(r"(?:(?:first[\s-]principles\s+)?classification|selected|selection|verdict)"
                     r"\s*[:—-]\s*(.{0,90})", cl, re.I)
        if m:
            r = _arch_value(m.group(1))
            if r:
                return r
    m = re.search(r"Probability of (?:a |an )?([^\n]{0,60}?)\s*(?:archetype\s*)?surviving", seg, re.I)
    if m:
        for L, pat in _ARCH_NAME_PATS:
            if re.search(pat, m.group(1), re.I):
                return L
    return None


def _valid_engine5(d):
    # value_if_approved_ps must be STRICTLY POSITIVE. A zero is not a valuation — it is the model
    # declining to estimate (seen live on OSTX with no research brief), and it sails through an
    # isinstance check to produce IV = floor only and a -99.4% MoS, i.e. a fabricated screaming
    # SELL. Rejecting it here falls through to Engine 4 / unvalued, which is the honest outcome.
    return (isinstance(d, dict) and int(d.get("engine", 0) or 0) == 5
            and valuation_backbone.norm_phase(d.get("phase")) is not None
            and isinstance(d.get("value_if_approved_ps", None), (int, float))
            and d.get("value_if_approved_ps") > 0)


def _valid_engine2(d):
    return (isinstance(d, dict) and int(d.get("engine", 0) or 0) == 2
            and isinstance(d.get("normalized_eps", None), (int, float))
            and isinstance(d.get("normal_multiple", None), (int, float)))


def _multiple_res(method, inp, iv, price, ticker):
    """Result for the NULL-backbone cases (Engine 4 option bridge / Engine 2 financial multiple),
    where the model legitimately supplies per-share value numbers. A light unit-sanity FLAG (not a
    silent clamp) surfaces an obvious per-share/scale slip for review."""
    # upside vs price (iv/price - 1) — SAME convention as the reverse-DCF/financial mos_pct; the
    # old (iv-price)/iv understated MoS for Engine-4/2 names and made the brake tiers misfire
    mos = ((iv - price) / price) if (iv and price and price > 0) else None
    flag = None
    if iv and price and (iv > 20 * price or iv < price / 20):
        flag = "IV is >20x or <1/20 of price — likely a per-share/unit error in the model inputs"
    res = {"method": method, "ticker": ticker, "price": price,
           "iv": round(iv, 2) if iv else None, "mos_pct": round(mos * 100, 1) if mos is not None else None,
           "inputs": inp, "flag": flag}
    if iv and mos is not None:
        block = (f"VALUATION RESULT ({method}):\n- Base IV: ${iv:,.2f}/share\n"
                 f"- Margin of Safety: {mos*100:+.1f}% vs price ${price:,.2f}"
                 + (f"  [Unverified: {flag}]" if flag else ""))
    else:
        block = f"VALUATION RESULT ({method}): IV [Unverified]"
    return res, block


def _fmt_rnpv(r):
    """VALUATION RESULT block for Engine 5 / rNPV (pre-profit clinical biotech)."""
    lines = [
        "VALUATION RESULT — ENGINE 5 / rNPV (risk-adjusted, deterministic):",
        f"- Phase [{r['phase']}] -> probability of approval {r['pos']*100:.1f}% "
        "(published BIO/Informa phase-transition base rates; NOT a model estimate).",
        f"- Net-cash floor ${r['net_cash_floor_ps']}/sh; value if approved "
        f"${r['value_if_approved_ps']}/sh (model).",
        f"- Runway {r['runway_years']}yr vs ~{r['years_to_approval']}yr to approval -> "
        f"dilution {r['dilution_pct']}% (equity it must issue to get there).",
        f"- IV = floor + P(approval) x upside / (1 + dilution) = ${r['iv']}/sh; "
        f"MoS {r['mos_pct']:+.1f}% vs ${r['price']}.",
    ]
    return "\n".join(lines)


def _fmt_reverse(res):
    dg = res["demonstrated_rev_cagr"]
    gap = res["expectations_gap_pts"]
    # NB: built line-by-line on purpose — a ternary spanning concatenated f-strings binds to the
    # WHOLE concatenation, which used to silently drop the header + base-cf line when dg was None.
    base = ("VALUATION RESULT (reverse-DCF expectations model — the GAP is the signal, not a price target):\n"
            f"- Base cash flow ${res['base_cf_b']}B ({str(res['base_cf_kind']).replace('_',' ')}), WACC {res['wacc_pct']}%.\n")
    if dg is not None:
        base += f"- Price IMPLIES {res['implied_growth']*100:.1f}%/yr growth; DEMONSTRATED {dg*100:.1f}%/yr.\n"
    else:
        base += f"- Price IMPLIES {res['implied_growth']*100:.1f}%/yr growth; demonstrated growth n/a.\n"
    base += f"- EXPECTATIONS GAP: {gap:+} pts.\n" if gap is not None else "- EXPECTATIONS GAP: n/a.\n"
    # Forward growth + analyst consensus band + entry-timing cue (the "don't chase at highs" discipline)
    fg, med, rmos = res.get("forward_growth"), res.get("consensus_median"), res.get("realistic_mos_pct")
    price = res.get("price")
    if fg is not None:
        base += f"- FORWARD analyst growth: {fg*100:+.1f}%/yr (the fresh consensus, vs trailing).\n"
    if med is not None:
        rich = "AT/ABOVE" if (price and price >= med) else "below"
        base += (f"- Analyst consensus fair value ~${med} (band ${res.get('consensus_low')}-${res.get('consensus_high')}); "
                 f"price is {rich} it. Fenced fair value ${res.get('fair_value')} => realistic MoS {rmos:+}%.\n"
                 if rmos is not None else
                 f"- Analyst consensus fair value ~${med}; price is {rich} it.\n")
    if rmos is not None and (rmos < 15):
        base += ("- ENTRY DISCIPLINE: realistic MoS is thin (<15%) / price near analyst target — this is a "
                 "DO-NOT-CHASE. A great business here is a Hold / stage-in on weakness, NOT a fresh full BUY.\n")
    return base + (f"- Model stance: {res['stance'] or 'n/a'} (implied growth achievable: {res['achievable'] or 'n/a'}). "
                   f"{res.get('rationale') or ''}")


def _extract_final(final_text):
    """Action / conviction(/15) / weight% from FINAL.md SECTION 12 (the model's execution opinion)."""
    seg = final_text[final_text.rfind("SECTION 12"):] if "SECTION 12" in final_text else final_text

    def f(pat):
        m = re.search(pat, seg, re.I)
        return m.group(1).strip() if m else None
    # The old pattern — [A-Za-z][A-Za-z /&\-]{2,45} — had two defects:
    #  1. the class excludes DIGITS and '$', so it stopped dead at the price level:
    #     "Hold / Stage-in on weakness below $195" published as "...below" (5 live names),
    #     dropping the one number that makes the call actionable;
    #  2. it was unanchored, so on a name whose SECTION 12 lacked a clean "Action:" line it
    #     matched the word "action" inside prose — FIX shipped an action of
    #     "will be severe due to the cyclical nature of t".
    # Anchor to a LABEL at line start and take the rest of that line, then strip markdown
    # and trailing [Actual]/[Estimate] tags.
    # Require a LABEL ("Action" + colon) and take the rest of that line. The colon is what
    # keeps prose out — SECTION 12 bullets vary wildly ("- Action:", "• Action:", "■ Action:",
    # "**Action:**"), so anchoring to line-start bullets would drop ~100 bundles.
    ma = re.search(r"\bAction\b\s*\*{0,2}\s*:\s*(.+?)\s*$", seg, re.I | re.M)
    action = None
    if ma:
        action = re.sub(r"\*+|_{2,}", "", ma.group(1)).strip()
        action = re.sub(r"\s*\[(?:Actual|Estimate|Assumption|Unconfirmed)[^\]]*\]", "", action, flags=re.I)
        action = action.split("|")[0]          # drop trailing "| Changed-Because: ..." fields
        action = action.strip(" .;—-").strip()
        action = action[:90].strip() or None
    conv = f(r"Conviction[^\n0-9]*([0-9.]+)\s*/\s*15")
    conv_val = float(conv) if conv else None
    if conv_val is None:
        # The number is not always on the "Conviction" line. The first unanchored-baseline pilot
        # (ABNB, 2026-08-07) wrote "**Step 12-2. Conviction**\n* **Score:** High (12/15)" — value
        # on the NEXT line, labelled "Score" — and conviction published as None. The "/15" scale
        # marker itself is the unambiguous anchor: within SECTION 12 the only X/15 IS conviction.
        conv = f(r"\b([0-9]{1,2}(?:\.[0-9])?)\s*/\s*15\b")
        conv_val = float(conv) if conv else None
    if conv_val is None:                       # the model sometimes writes conviction as words, not X/15
        cw = (f(r"Conviction[:\s*]*\*{0,2}([A-Za-z][A-Za-z/ \-]{2,18})") or "").lower()
        for key, val in (("very high", 13), ("medium/high", 11), ("medium-high", 11), ("high", 12),
                         ("medium/low", 6), ("medium-low", 6), ("very low", 3), ("low", 4), ("medium", 9)):
            if key in cw:
                conv_val = float(val)
                break
    # Weight may be a single number ("0.0% for new capital") OR a RANGE ("5-7% [Estimate]",
    # "5 to 7%", en/em dash). The old single-number pattern silently returned None on every
    # range — 203/1390 bundles, 24 of them live — so the sizing the model actually stated was
    # dropped on the floor. A range collapses to its MIDPOINT: that is the faithful reading of
    # the model's intent, and _dont_chase_brake applies min() caps downstream anyway.
    mw = re.search(r"Weight\s*%?[:\s*]*\*{0,2}([0-9.]+)\s*"
                   r"(?:(?:[-–—]|to)\s*([0-9.]+)\s*)?%", seg, re.I)
    if not mw:
        # Same next-line-label failure as conviction: "Step 12-3. Weight %" followed by
        # "* **Target Allocation:** 6% ..." — the number is within a short window after the
        # Weight heading but not on its line. 140 chars bounds the search to that step block.
        mw = re.search(r"Weight[\s\S]{0,140}?([0-9.]+)\s*"
                       r"(?:(?:[-–—]|to)\s*([0-9.]+)\s*)?%", seg, re.I)
    weight = None
    if mw:
        lo = float(mw.group(1))
        weight = round((lo + float(mw.group(2))) / 2, 2) if mw.group(2) else lo
    return action, conv_val, weight


def band_of(ticker):
    fs = rs2_data.load_json(Path(CONFIG["screener_data_dir"]) / "factor_scores.json") or {}
    return ((fs.get("tickers") or {}).get(ticker.upper()) or {}).get("fct_band")


def prior_verdict(ticker, exclude_dir=None):
    """Latest verdict.json for this ticker in the live reports tree — the call a
    re-analysis anchors to. Excludes the current run's own out_dir."""
    root = Path(CONFIG["out_reports_dir"])
    ex = Path(exclude_dir).resolve() if exclude_dir else None
    for d in sorted(root.glob(f"{ticker.upper()}_*"),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        if ex and d.resolve() == ex:
            continue
        v = rs2_data.load_json(d / "verdict.json")
        if v and v.get("action"):
            return v
    return None


def anchor_block(pv):
    """Continuity anchor injected into the FINAL prompt (the call-emission point).
    Root-cause fix for verdict flip noise (audit 2026-07-21): re-analyses were
    amnesiac — each run re-derived the call from scratch, so borderline names
    re-rolled every review. Persistence becomes the default; changing the call
    requires a named material reason (audited via Changed-Because)."""
    try:
        days = (datetime.now().date()
                - datetime.strptime(str(pv.get("date")), "%Y-%m-%d").date()).days
    except Exception:
        days = "?"
    return (
        "PREVIOUS VERDICT (continuity anchor)\n"
        f"Your previous analysis of {pv.get('ticker')} ({pv.get('date')}, {days}d ago) concluded — "
        f"Action: {pv.get('action')} | Conviction: {pv.get('conviction')}/15 | "
        + (f"Stance: {pv.get('stance_score')}/5 | " if pv.get('stance_score') else "")
        + f"Weight: {pv.get('recommended_weight_pct')}% | Fair value: ${pv.get('fair_value')} "
        f"(MoS {pv.get('mos_pct')}%).\n"
        "CONTINUITY RULE: your DEFAULT is to MAINTAIN that call. Change it ONLY if the worked "
        "analysis demonstrates a MATERIAL change since that date — new earnings/guidance, a thesis "
        "event, a large price move, or a fair-value revision beyond ~5%. Different wording or small "
        "sub-score wobbles are NOT grounds to change the call.\n"
        "In SECTION 12, immediately after the Action line, output exactly one line:\n"
        "Changed-Because: none (maintained previous call)\n"
        "or\n"
        "Changed-Because: <the specific material change justifying the new call>")


def _action_family(s):
    s = (s or "").upper()
    if any(w in s for w in ("AVOID", "REDUCE", "SELL", "TRIM", "EXIT", "UNDERWEIGHT")):
        return "BEAR"
    if "HOLD" in s or "WAIT" in s or "WATCHLIST" in s or "MONITOR" in s or "DO NOT CHASE" in s:
        return "HOLD"
    if any(w in s for w in ("BUY", "ACCUMULAT", "SCALE", "ADD", "OVERWEIGHT", "STARTER", "INITIAT", "ENTER")):
        return "BULL"
    return "?"


def _pct_of_52wk_high(ticker, price):
    """price / 52-week high, from enrich/{T}.json (None if not fetched). 1.0 == at the high."""
    en = rs2_data.load_json(HERE / "enrich" / f"{ticker.upper()}.json") or {}
    hi = en.get("fifty_two_week_high")
    try:
        return (price / hi) if (hi and price and hi > 0) else None
    except Exception:
        return None


# Deterministic stance cuts, calibrated 2026-08-06 against 241 live verdicts (quartiles of
# the COMPUTED expectations gap under each model-emitted stance):
#     undervalued  p25 -33.4  median -11.1  p75  -7.7
#     fair         p25  -2.6  median  +4.0  p75  +8.9
#     overvalued   p25 +14.7  median +20.4  p75 +26.8
# +15 sits just above the overvalued p25 and reproduces today's classification volume
# (72 vs the model's 76) while removing the instability; -7 is the matching boundary
# between the undervalued p75 and the fair p25.
STANCE_OVERVALUED_GAP = 15.0
STANCE_UNDERVALUED_GAP = -7.0


def _stance_from_gap(gap):
    """Stance from the DETERMINISTIC expectations gap, not the model's free-text opinion.

    Why: the model emits `valuation_stance` as a believability judgment, and it is NOT stable —
    two consecutive POWL runs on byte-identical inputs returned 'overvalued' (achievable low)
    and 'fair' (achievable medium) off the SAME computed gap of 28.5pts. That field is
    load-bearing far downstream: score_factors.apply_llm_overlay treats stance=='overvalued'
    as BEARISH and demotes the name out of research_now, so a coin flip was moving 55 of 173
    live names between 'demoted' and 'research_now' (MPWR and TSM swung the full distance).
    The gap itself is computed from financials and was identical across all three runs, so the
    gate is anchored to that instead. The model's opinion is preserved as `stance_model`.
    """
    if not isinstance(gap, (int, float)):
        return None
    if gap >= STANCE_OVERVALUED_GAP:
        return "overvalued"
    if gap <= STANCE_UNDERVALUED_GAP:
        return "undervalued"
    return "fair"


def _dont_chase_brake(action, conv, weight, vr, ticker=None):
    """Deterministic 'don't chase' brake — the systematic gap vs ChatGPT (RS2 flipped HOLD->BUY on
    15/39 names; ChatGPT pullback-gated 96%). Graduated on ChatGPT's own margin-of-safety bands:
      * MoS >= 25% (Strong) AND below the analyst median AND not within 5% of the 52wk high
            -> genuine bargain, a fresh BUY is fine (no brake).
      * 15% <= MoS < 25%  (Adequate, or Strong-but-extended) -> STAGE: keep a bull lean but this is
            'accumulate on weakness', not a full chase; conviction capped ~11, weight trimmed.
      * MoS < 15% OR price at/above the analyst median OR within ~2% of the 52wk high
            -> HOLD / do-not-chase: downgrade a BUY, cap conviction into Medium, starter size only.
    Returns (action, conv, weight, entry_timing, pullback_trigger, brake_applied)."""
    price = vr.get("price")
    med = vr.get("consensus_median")
    rmos = vr.get("realistic_mos_pct")
    rmos = rmos if rmos is not None else vr.get("mos_pct")
    at_or_above = bool(price and med and price >= med)
    p52 = _pct_of_52wk_high(ticker, price) if ticker else None
    near_high = bool(p52 is not None and p52 >= 0.98)
    # PERCENTILE TIERS (2026-08-07). These were absolute (>=25 strong, 15-25 adequate) and were
    # calibrated when fair value was the analyst median for 87% of names, so MoS clustered near
    # zero and 25% genuinely meant exceptional. With the stability fence the distribution moved
    # (median -38%, p75 -11%, p90 +30%), and absolute cuts inverted the brake's meaning: tier 1
    # and 2 stopped firing at all and tier 3 caught everyone, capping every name at conviction
    # 9.5. Measured live on AAPL and KO — the MODEL differentiated them (KO 'ACCUMULATE ON DIPS'
    # vs AAPL 'HOLD', both conviction 12.0) and the brake flattened both to 9.5. The
    # homogenization had simply moved downstream from the prompt into here.
    #
    # Tier on the CROSS-SECTION instead, matching the ENTRY DISCIPLINE rule so the prompt and the
    # brake cannot disagree about what "cheap" means:
    #     >= p75  cheapest quarter   -> may chase
    #     >= p33  mid                -> stage
    #     <  p33  expensive third    -> do not chase
    # If the calibration is stale, mos_cut() returns None and MoS-based tiering is SKIPPED
    # entirely — the brake then relies on the gap / at-or-above-median / near-52wk-high evidence.
    # Falling back to the absolute cuts would reintroduce exactly the bug this removes.
    _cut75, _cut33, _cut50 = (valuation_backbone.mos_cut(75), valuation_backbone.mos_cut(33),
                              valuation_backbone.mos_cut(50))
    strong = (rmos is not None and _cut75 is not None and rmos >= _cut75)
    adequate = (rmos is not None and _cut33 is not None and _cut75 is not None
                and _cut33 <= rmos < _cut75)
    expensive = (rmos is not None and _cut33 is not None and rmos < _cut33)
    fam = _action_family(action)

    # EXPECTATIONS OVERRIDE (2026-08-06). MoS is measured against fair_value, and for ~78% of
    # names fair_value is `consensus_snap` — the analyst median. So a fat MoS can mean nothing
    # more than "trading below Wall Street's target" while the reverse-DCF simultaneously says
    # the price bakes in growth the company has never delivered. POWL is the worked example:
    # MoS 36.3% vs consensus, gap +28.5pts (price implies 44.8% growth vs 16.3% demonstrated)
    # -> tier 1 fired, brake OFF, and the engine emitted a conviction-12 BUY on a name its own
    # DCF called rich. Keyed on the COMPUTED gap, never on `stance`, which is model-unstable.
    gap = vr.get("expectations_gap_pts")
    rich = isinstance(gap, (int, float)) and gap >= STANCE_OVERVALUED_GAP

    # tier 1 — genuine bargain: let a BUY chase. Blocked when the expectations gap says rich:
    # cheap-vs-consensus is not cheap-vs-fundamentals, and only the latter earns a chase.
    if strong and not at_or_above and not near_high and not rich:
        return action, conv, weight, ("buy" if fam == "BULL" else "stage"), None, False

    trig = vr.get("consensus_low")
    if not (trig and price and trig < price):
        trig = round(price * 0.90, 2) if price else None      # default -10% "buy below $X"

    # tier 2 — adequate-but-not-cheap (and not at highs / above median): STAGE, keep a bull lean
    if adequate and not at_or_above and not near_high:
        out_action = action if fam != "BULL" else "Accumulate on weakness (staged)"
        out_conv = min(conv, 11.0) if conv is not None else conv
        out_weight = min(weight, 5.0) if weight is not None else weight
        return out_action, out_conv, out_weight, "stage", trig, True

    # tier 3 requires ESTABLISHED evidence (thin MoS / at-or-above median / near 52wk high). A name
    # with NO MoS data at all (uncovered, fair value blanked) must pass through un-braked — missing
    # data is not a valuation judgment, and rewriting those BUYs silently excluded exactly the
    # names the expectations model finds cheapest.
    if rmos is None and not at_or_above and not near_high:
        return action, conv, weight, "stage", None, False

    # tier 3 — thin MoS / at-or-above median / near 52wk high: HOLD, do not chase
    entry = "wait_for_pullback" if expensive or near_high else "stage"
    out_action = "Hold / accumulate on weakness (do not chase)" if fam == "BULL" else action
    # A better-than-median MoS protects conviction from the cap. It must NOT when the expectations
    # gap says rich — otherwise a name lands on "do not chase" while still carrying a 12/15,
    # which is the same contradiction one field over. Was an absolute `rmos >= 15`, which after
    # the fence meant ~nothing cleared it and every name got capped.
    _protected = (rmos is not None and _cut50 is not None and rmos >= _cut50)
    out_conv = min(conv, 9.5) if (conv is not None and (rich or not _protected)) else conv
    out_weight = min(weight, 3.0) if weight is not None else weight
    return out_action, out_conv, out_weight, entry, trig, True


STAGE_FILES = ["S1_macro_classify.md", "S2_quality.md", "S3_valuation.md",
               "S4_scenarios.md", "S5_conviction.md", "S6_redteam_audit.md"]
MIN_STAGE_CHARS = 400        # a real stage is thousands; 400 only catches empty/error stubs
MIN_FINAL_CHARS = 2000       # a 13-section report; the OOM stubs were ~200 chars/section
MIN_RESEARCH_CHARS = 3000    # healthy briefs are 13-28KB; the poisoned ones were 1.0-2.1KB


def sanity_check(out_dir, ticker):
    """Post-analysis audit: prove this run actually produced an analysis before it counts
    as done. Added 2026-08-04 after whole days of runs completed 'successfully' while every
    research brief and downstream section was really four copies of a CUDA-OOM error string.

    An exit code of 0 was never evidence of a real result — nothing checked the artefacts.
    This does, and returns (ok, problems) so the caller can fail the ticker loudly."""
    p = []
    t = ticker.upper()

    # 1. the research brief this verdict rests on (catches BOTH a fresh failure and a
    #    previously-cached poisoned brief that was reused silently on this run)
    rp = Path(CONFIG["out_research_dir"]) / f"{t}.md"
    if rp.exists():
        rtxt = rp.read_text(encoding="utf-8", errors="replace")
        sig = ops.infra_error(rtxt)
        if sig:
            p.append(f"research brief is infra-error text ({sig}) — {rp.name} {len(rtxt)}B")
        elif len(rtxt) < MIN_RESEARCH_CHARS:
            p.append(f"research brief suspiciously small: {len(rtxt)}B < {MIN_RESEARCH_CHARS}B")
        # ZERO CITATIONS = the search engine returned nothing and the model answered from its own
        # recall. That is not research, and it is invisible to the error-signature and size checks:
        # POWL 2026-08-05 produced a clean, 6.6KB, entirely uncited brief while SearXNG was down,
        # and the verdict built on it (TRIM/EXIT) passed sanity. The brief's own header says
        # "Cite only the listed sources" — if there are none, the whole run is unsupported.
        elif not re.search(r"^- https?://", rtxt, re.M):
            p.append(f"research brief has ZERO source citations ({len(rtxt)}B) — search engine "
                     f"likely down; verdict would rest on model recall, not research")

    # 2. stage outputs
    for fn in STAGE_FILES:
        fp = out_dir / fn
        if not fp.exists():
            p.append(f"missing stage output {fn}")
            continue
        txt = fp.read_text(encoding="utf-8", errors="replace")
        sig = ops.infra_error(txt)
        if sig:
            p.append(f"{fn} is infra-error text ({sig})")
        elif len(txt.strip()) < MIN_STAGE_CHARS:
            p.append(f"{fn} nearly empty: {len(txt.strip())}B < {MIN_STAGE_CHARS}B")

    # 3. the final report
    fp = out_dir / "FINAL.md"
    if not fp.exists():
        p.append("missing FINAL.md")
    else:
        txt = fp.read_text(encoding="utf-8", errors="replace")
        sig = ops.infra_error(txt)
        if sig:
            p.append(f"FINAL.md is infra-error text ({sig})")
        elif len(txt.strip()) < MIN_FINAL_CHARS:
            p.append(f"FINAL.md nearly empty: {len(txt.strip())}B < {MIN_FINAL_CHARS}B")

    # 4. the structured verdict the website overlay actually consumes
    vp = out_dir / "verdict.json"
    if not vp.exists():
        p.append("missing verdict.json")
    else:
        try:
            v = json.loads(vp.read_text(encoding="utf-8-sig"))
        except Exception as e:
            p.append(f"verdict.json unparseable: {str(e)[:80]}")
            v = None
        if isinstance(v, dict):
            if not v.get("action"):
                p.append("verdict.json has no action")
            s = v.get("stance_score")
            if not isinstance(s, int) or isinstance(s, bool) or not 1 <= s <= 5:
                p.append(f"verdict.json stance_score invalid: {s!r}")
            if v.get("ticker", "").upper() != t:
                p.append(f"verdict.json ticker mismatch: {v.get('ticker')!r} != {t}")
    return (not p), p


# ── POST-COMPLETION AUDIT (2026-08-08, operator order) ───────────────────────────────────────
# Every completed ticker is audited before it may count as done: TIER 1 re-derives the
# deterministic facts and diffs them against what the run recorded (data source, engine
# arithmetic, routing invariants — "actually knowing it was done correctly", not file sizes);
# TIER 2 hands the assembled report to the model as a VERIFIER with the authoritative numbers
# attached. A failed audit exits non-zero, so orchestrate marks the name failed and retries it
# exactly like a watchdog kill — a bad analysis must never publish.

LABEL_LEDGER = Path(__file__).resolve().parent / "cache" / "label_history.jsonl"


def _append_label_ledger(ticker, run_name, label):
    """Per-run archetype-label telemetry (operator order: watch label wobble as baseline results
    come out). Append-only ledger; returns (prior_label, changed)."""
    prior = None
    try:
        if LABEL_LEDGER.exists():
            for ln in LABEL_LEDGER.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if rec.get("ticker") == ticker:
                    prior = rec.get("label")
    except OSError:
        pass
    changed = prior is not None and label is not None and prior != label
    try:
        with LABEL_LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ticker": ticker, "run": run_name, "label": label,
                                 "prior": prior, "changed": changed}) + "\n")
    except OSError:
        pass
    return prior, changed


def deterministic_audit(t, out_dir, val_res, level="full"):
    """TIER 1: re-derive and cross-check everything checkable without a model.

    Returns (ok, checks) where checks is a list of {check, ok, detail}. `level` "valonly"
    limits to the artefacts a --valonly run produces (no FINAL/verdict)."""
    checks = []

    def rec(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})

    vr = val_res or {}
    # 1. BACKBONE REPRODUCIBILITY — recompute the deterministic engine now and diff against
    #    what the run recorded. base_cf/kind/period must match EXACTLY (they change only when
    #    the fundamentals files change; a mid-sweep rebuild would make the book internally
    #    inconsistent and must surface). The gap gets a ±3pt band: market cap moves intraday.
    method = vr.get("method")
    if method in ("reverse_dcf", "financial_pb_roe"):
        bb2 = valuation_backbone.backbone(t)
        if method == "reverse_dcf" and bb2.get("ok"):
            same_base = (vr.get("base_cf_b") is not None and bb2.get("base_cf") is not None
                         and abs(vr["base_cf_b"] - round(bb2["base_cf"] / 1e9, 2)) < 0.011)
            rec("backbone.base_cf", same_base,
                f"run {vr.get('base_cf_b')}B vs now {round((bb2.get('base_cf') or 0)/1e9, 2)}B")
            rec("backbone.kind", vr.get("base_cf_kind") == bb2.get("base_cf_kind"),
                f"run {vr.get('base_cf_kind')} vs now {bb2.get('base_cf_kind')}")
            g1, g2 = vr.get("expectations_gap_pts"), bb2.get("expectations_gap_pts")
            rec("backbone.gap", g1 is None or g2 is None or abs(g1 - g2) <= 3.0,
                f"run {g1} vs now {g2}")
        elif method == "financial_pb_roe" and bb2.get("method") == "financial_pb_roe":
            r1, r2 = vr.get("roe"), bb2.get("roe")
            rec("backbone.roe", r1 is None or r2 is None or abs(r1 - r2) < 0.005,
                f"run {r1} vs now {r2}")
        else:
            rec("backbone.method", False,
                f"run method {method} vs now {bb2.get('method') or bb2.get('reason')}")

    # 2. DATA-SOURCE INTEGRITY for THIS ticker (the data_health checks that matter per-run).
    fin = rs2_data.load_json(Path(rs2_data.CONFIG["screener_data_dir"]) / "financials" / f"{t}.json") or {}
    price_f, shares_f, mcap_f = (fin.get("Price"), fin.get("Shares_Outstanding"),
                                 fin.get("Market_Cap"))
    if all(isinstance(x, (int, float)) and x > 0 for x in (price_f, shares_f, mcap_f)):
        ident = price_f * shares_f / mcap_f
        rec("data.mcap_identity", 0.975 <= ident <= 1.025,
            f"price*shares/mcap = {ident:.3f}")
    hist = valuation_backbone._hist(t) or {}
    ydig = {k: v for k, v in hist.items() if str(k).isdigit()}
    if ydig:
        latest = ydig[max(ydig, key=int)]
        import statistics as _st
        for fld in ("revenue", "net_income", "ocf"):
            vals = [abs(ydig[y].get(fld)) for y in ydig
                    if isinstance(ydig[y].get(fld), (int, float)) and ydig[y].get(fld)]
            lv = latest.get(fld)
            if len(vals) >= 4 and isinstance(lv, (int, float)) and lv:
                med = _st.median(vals)
                rec(f"data.scale.{fld}", valuation_backbone._pow1000_ratio(lv, med) is None,
                    f"latest {lv:.3g} vs series median {med:.3g}")
    bb_now = valuation_backbone.backbone(t)
    if bb_now.get("base_period") == "ttm":
        rec_t = valuation_backbone._ttm_record(t) or {}
        thr = str(rec_t.get("through", ""))
        try:
            age = (datetime.now() - datetime.strptime(thr, "%Y-%m-%d")).days
        except ValueError:
            age = None
        rec("data.ttm_fresh", age is not None and 0 <= age <= 400, f"through {thr} ({age}d)")
        rec("data.ttm_anchor",
            str(rec_t.get("fy_leg_end", ""))[:4] == str(max((int(y) for y in ydig), default=0)),
            f"fy_leg {rec_t.get('fy_leg_end')} vs history max {max((int(y) for y in ydig), default=None)}")

    # 3. ROUTING COHERENCE — the S1 hook's own invariants.
    rj = out_dir / "routing.json"
    arch = None
    s1p = out_dir / "S1_macro_classify.md"
    if s1p.exists():
        arch = _archetype(s1p.read_text(encoding="utf-8", errors="replace"))
    if rj.exists():
        try:
            r = json.loads(rj.read_text(encoding="utf-8"))
            rec("routing.parseable", True)
            rec("routing.arch_matches_s1", r.get("archetype") == arch,
                f"routing {r.get('archetype')} vs re-parse {arch}")
            if r.get("disclosed"):
                rec("routing.disclosed_shape",
                    isinstance(r.get("latest_fy"), dict) and isinstance(r.get("midcycle"), dict)
                    and r.get("in_use") in ("latest_fy", "midcycle"),
                    f"in_use={r.get('in_use')}")
        except json.JSONDecodeError as e:
            rec("routing.parseable", False, str(e)[:100])

    # 4. LABEL TELEMETRY (never fails the run — it builds the wobble dataset the selector
    #    decision was deferred for).
    prior, changed = _append_label_ledger(t, out_dir.name, arch)
    rec("label.telemetry", True,
        f"label={arch} prior={prior}{' CHANGED' if changed else ''}")

    if level == "full":
        # 5. VERDICT ARITHMETIC — identities the emitter must satisfy.
        vp = out_dir / "verdict.json"
        if vp.exists():
            try:
                v = json.loads(vp.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                v = {}
            conv = v.get("conviction")
            rec("verdict.conviction_range",
                conv is None or (isinstance(conv, (int, float)) and 0 <= conv <= 15), conv)
            rec("verdict.scales", v.get("conviction_scale") == 15
                and v.get("stance_score_scale") == 5,
                f"{v.get('conviction_scale')}/{v.get('stance_score_scale')}")
            fv, pr, mos = v.get("fair_value"), v.get("price"), v.get("mos_pct")
            if all(isinstance(x, (int, float)) and x for x in (fv, pr)) and isinstance(mos, (int, float)):
                rec("verdict.mos_identity", abs(mos - (fv / pr - 1) * 100) <= 0.15,
                    f"mos {mos} vs (fv/price-1) {round((fv/pr-1)*100, 1)}")
            st, gap_v = v.get("stance"), v.get("expectations_gap_pts")
            if st is not None and isinstance(gap_v, (int, float)):
                rec("verdict.stance_from_gap", st == _stance_from_gap(gap_v),
                    f"stance {st} vs recompute {_stance_from_gap(gap_v)} (gap {gap_v})")

    ok = all(c["ok"] for c in checks)
    return ok, checks


AI_AUDIT_PROMPT = """You are the POST-COMPLETION AUDITOR for this equity analysis. Verify — do
NOT re-analyze. The engine's VALUATION RESULT and verdict.json are AUTHORITATIVE data; the final
report is the text under audit.

VIOLATIONS (each one fails the report):
1. COMPETING VALUATION: the report's PROSE contradicts the ENGINE VALUATION header (which the
   engine writes into the report deterministically — do not flag its absence from the model's
   own sections): a different figure presented as the fair value / intrinsic value / MoS, a
   price level asserted to carry a margin of safety inconsistent with the authoritative fair
   value, or a stance contradicting the authoritative stance. (A clearly-labeled
   SCENARIO-WEIGHTED or probability-weighted price from the report's own scenario section is
   PERMITTED and is not a competing valuation.)
2. FABRICATION: a company-specific figure that appears in neither the engine data, the data
   context, nor the research brief, and is not arithmetic on them. Figures from model memory
   are fabrication even when plausible.
3. MISSING BASIS JUDGMENT: a CYCLICALITY CHECK disclosed two bases (latest vs mid-cycle) and the
   report never states WHICH basis it judged fairer and why.
4. INTERNAL CONTRADICTION: stance, action, conviction and entry guidance contradict each other
   or the report's own prose.
5. UNGROUNDED EVENT CLAIM: a factual claim about recent company events with no supporting
   content in the research brief or data context.

NOT violations (record in notes at most): rounding or judgment bands within ~3% of an
authoritative trigger/level; a different-but-labeled metric (e.g. EV/Sales where the brief used
P/S); presentation, ordering, or formatting choices; conservative re-statements that do not
change the figure.

Output STRICT JSON only, no prose before or after:
{"pass": true/false, "violations": [{"type": "...", "detail": "..."}], "notes": "..."}
A report passes only if there are NO violations from the list above."""


def ai_audit(t, out_dir, think):
    """TIER 2: the model verifies the assembled report against the authoritative engine data.
    Returns (status, violations) with status in {"pass", "fail", "inconclusive"} — inconclusive
    (auditor output unparseable twice) does NOT fail the run: the deterministic tier already
    guards correctness, and an audit-infrastructure hiccup must not block the book."""
    def read(name, cap):
        p = out_dir / name
        return p.read_text(encoding="utf-8", errors="replace")[:cap] if p.exists() else ""

    def read_ht(name, head, tail):
        """Head+tail slice: _fed_data.md carries the FINANCIALS block and VERIFIED ANCHOR at
        the END (~24K offset of ~27K) — a head-only cap amputated exactly the figures the
        auditor must verify against, and it called provided data 'memory-based hallucination'
        twice before this was measured."""
        p = out_dir / name
        if not p.exists():
            return ""
        t_ = p.read_text(encoding="utf-8", errors="replace")
        if len(t_) <= head + tail:
            return t_
        return t_[:head] + "\n…[middle elided for the auditor]…\n" + t_[-tail:]

    brief = ""
    rp = Path(CONFIG["out_research_dir"]) / f"{t}.md"
    if rp.exists():
        brief = rp.read_text(encoding="utf-8", errors="replace")[:12000]
    # Context budget: the pack must FIT. Sized for final_ctx (32768): ~45KB of evidence is
    # ~13-14K tokens, leaving room for thinking + the JSON verdict. The first live proof run
    # shipped ~61KB into stage_ctx (24576): ollama returned 200-with-empty-content three
    # times and the raise crashed the ticker AFTER a good verdict — the auditor must never
    # be the thing that kills a healthy run.
    ctx = (f"{AI_AUDIT_PROMPT}\n\n=== ENGINE VALUATION RESULT (authoritative) ===\n"
           f"{read('S4_valuation_result.md', 4000)}\n\n=== verdict.json (authoritative) ===\n"
           f"{read('verdict.json', 2000)}\n\n=== ROUTING/DISCLOSURE ===\n"
           f"{read('routing.json', 1500)}\n\n=== DATA CONTEXT the run was given (macro/market "
           f"figures in the report trace here) ===\n{read_ht('_fed_data.md', 8000, 12000)}\n\n"
           f"=== RESEARCH BRIEF ===\n{brief}\n\n"
           f"=== FINAL REPORT UNDER AUDIT ===\n{read('FINAL.md', 18000)}\n")
    for attempt in (1, 2):
        try:
            out = ollama_chat(ctx if attempt == 1 else
                              ctx + "\n\nREMINDER: output ONLY the JSON object.",
                              CONFIG["final_ctx"], think)
        except Exception as e:
            # auditor infrastructure failure (empty content, timeout, OOM) — the run's own
            # artefacts are fine; record inconclusive rather than failing a healthy ticker
            print(f"   [audit] tier-2 attempt {attempt} infra error: {str(e)[:120]}", flush=True)
            continue
        m = re.search(r"\{.*\}", out or "", re.S)
        if m:
            try:
                j = json.loads(m.group(0))
                viols = j.get("violations") or []
                return ("pass" if j.get("pass") and not viols else "fail"), viols
            except json.JSONDecodeError:
                pass
    return "inconclusive", []


def emit_verdict(out_dir, ticker, price, val_res, final_text, exit_review=False):
    """Write reports/{T}_{ts}/verdict.json — the structured handoff the orchestrator aggregates
    into the website overlay. Adapted to the inverted shapes (reverse-DCF gap / financial ROE-gap /
    option bridge); stance is the headline judgment, action/conviction parsed from FINAL SECTION 12,
    then passed through the deterministic don't-chase brake."""
    raw_action, raw_conv, raw_weight = _extract_final(final_text or "")
    vr = val_res or {}
    action, conv, weight, entry_timing, pullback, braked = _dont_chase_brake(
        raw_action, raw_conv, raw_weight, vr, ticker)
    seg12 = final_text[final_text.rfind("SECTION 12"):] if "SECTION 12" in (final_text or "") \
        else (final_text or "")
    cb = re.search(r"Changed-Because[:\s]*\*{0,2}\s*(.+)", seg12, re.I)
    # Structured stance (1-5) + thesis_break — the machine-read disposition; the prose
    # action stays for humans. Fallback derives from keywords so old-format finals
    # still emit a stance (tagged, so the transition is auditable).
    sj = valuation_io.extract_json(final_text or "", "stance")
    stance_src = "json"
    if isinstance(sj, dict) and isinstance(sj.get("stance"), (int, float)) \
            and not isinstance(sj.get("stance"), bool) and 1 <= sj["stance"] <= 5:
        # bool is an int subclass: {"stance": true} would otherwise publish 1 = EXIT
        stance = int(round(sj["stance"]))
        thesis_break = bool(sj.get("thesis_break"))
    else:
        stance = {"BULL": 4, "HOLD": 3, "BEAR": 2}.get(_action_family(action), 3)
        thesis_break = False
        stance_src = "fallback_keywords"
    if braked:
        # Brake caps land in/next to the powerless middle band (3), so brake
        # re-tiering can no longer flip portfolio membership by itself.
        stance = min(stance, 3 if _action_family(action) == "HOLD" else 4)
    # stance vs stance_score measure DIFFERENT AXES and may legitimately disagree:
    # stance = deterministic valuation judgment (gap vs fundamentals); stance_score = action
    # disposition (model call, brake-capped). "Overvalued + accumulate-on-dips" is a coherent
    # position, so agreement is NOT forced — the tension is surfaced instead. 94% of published
    # convictions are <=10, so a bare number was indistinguishable from a /10 scale; both scales
    # are now explicit in every verdict (handoff BUGs C and D).
    _stc = _stance_from_gap(vr.get("expectations_gap_pts") if vr.get("expectations_gap_pts")
                            is not None else vr.get("roe_gap_pts")) or vr.get("stance")
    stance_conflict = bool((_stc == "overvalued" and stance >= 4)
                           or (_stc == "undervalued" and stance <= 2))
    verdict = {
        "stance_score": stance, "thesis_break": thesis_break, "stance_source": stance_src,
        "conviction_scale": 15, "stance_score_scale": 5,
        "stance_conflict": stance_conflict,
        **({"exit_review": True} if exit_review else {}),
        "changed_because": cb.group(1).strip().strip("*").strip()[:300] if cb else None,
        "ticker": ticker.upper(), "date": datetime.now().strftime("%Y-%m-%d"), "price": price,
        "method": vr.get("method"),
        # Recomputed here as the single source of truth, so repatch_verdicts.py (which replays
        # emit_verdict over a SAVED S3 val_res carrying the old model stance) gets the
        # deterministic value too. Falls back to whatever vr held when there is no gap.
        "stance": _stc,
        "stance_model": vr.get("stance_model") or vr.get("stance"),
        "expectations_gap_pts": vr.get("expectations_gap_pts") if vr.get("expectations_gap_pts") is not None
        else vr.get("roe_gap_pts"),
        "fair_value": vr.get("fair_value"), "mos_pct": vr.get("mos_pct"),
        "realistic_mos_pct": vr.get("realistic_mos_pct"), "fair_value_method": vr.get("fair_value_method"),
        "consensus_median": vr.get("consensus_median"), "consensus_stale": vr.get("consensus_stale"),
        "action": action, "conviction": conv, "recommended_weight_pct": weight,
        "entry_timing": entry_timing, "pullback_trigger": pullback,
        "raw_action": raw_action, "raw_conviction": raw_conv, "brake_applied": braked,
        "band_at_analysis": band_of(ticker), "report": out_dir.name,
    }
    # atomic: a torn verdict.json is silently skipped by publish_reports._scan and gets the run's
    # already-published site bundle DELETED — never leave a half-written one visible
    vtmp = out_dir / "verdict.json.tmp"
    vtmp.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    vtmp.replace(out_dir / "verdict.json")
    print(f"   [verdict] {ticker}: method={vr.get('method')} stance={vr.get('stance')} "
          f"action={action} conv={conv} entry={entry_timing}"
          + (f" (BRAKE: was '{raw_action}' {raw_conv})" if braked else ""), flush=True)
    return verdict


def _fmt_financial(res):
    g = res["roe_gap_pts"]
    base = ("VALUATION RESULT (financial ROE/P-B expectations model — the ROE gap is the signal):\n"
            f"- Delivered ROE {res['roe']*100:.1f}%; price implies ROE {res['implied_roe']*100:.1f}% "
            f"(P/B {res['current_pb']}x vs justified {res['justified_pb']}x).\n")
    if res.get("fair_value") is not None and res.get("mos_pct") is not None:
        base += (f"- ROE EXPECTATIONS GAP: {g:+} pts; fenced fair value ~${res['fair_value']}/sh "
                 f"(MoS {res['mos_pct']:+}% vs price).\n")
    else:
        base += f"- ROE EXPECTATIONS GAP: {g:+} pts; fair value n/a.\n"
    med, price, rmos = res.get("consensus_median"), res.get("price"), res.get("realistic_mos_pct")
    if med is not None:
        rich = "AT/ABOVE" if (price and price >= med) else "below"
        base += (f"- Analyst consensus fair value ~${med} (band ${res.get('consensus_low')}-"
                 f"${res.get('consensus_high')}); price is {rich} it.\n")
    if rmos is not None and rmos < 15:
        base += ("- ENTRY DISCIPLINE: realistic MoS is thin (<15%) / price near analyst target — this is a "
                 "DO-NOT-CHASE. A great franchise here is a Hold / stage-in on weakness, NOT a fresh full BUY.\n")
    return base + (f"- Model stance: {res['stance'] or 'n/a'} (implied ROE achievable: {res['achievable'] or 'n/a'}). "
                   f"{res.get('rationale') or ''}")


def valuation_result(stage_out, bb, price, ticker):
    """Inverted valuation. DCF-able -> reverse-DCF backbone owns the numbers; financial -> P/B-ROE
    backbone owns them; in both cases we parse only the model's believability STANCE (the GAP is the
    signal). NULL backbone (pre-profit) -> the model supplies Engine-4 value numbers, the one place
    its numeric judgment is legitimate. Returns (result_dict, markdown_block)."""
    if bb.get("ok") and bb.get("method") == "financial_pb_roe":
        st = get_assumptions(stage_out, "valuation_stance", _valid_stance, STANCE_SCHEMA) or {}
        fv = bb.get("fair_value")
        res = {"method": "financial_pb_roe", "ticker": ticker, "price": price,
               "roe": bb["roe"], "implied_roe": bb["implied_roe"], "current_pb": bb["current_pb"],
               "justified_pb": bb["justified_pb"], "fair_value": fv,
               # upside vs price (fv/price - 1) — same convention as the reverse-DCF mos_pct;
               # fair value is consensus-fenced in the backbone, so realistic == fenced mos
               "mos_pct": bb.get("mos_pct"), "realistic_mos_pct": bb.get("realistic_mos_pct"),
               "fair_value_method": bb.get("fair_value_method", "financial_pb_roe"),
               "consensus_low": bb.get("consensus_low"), "consensus_median": bb.get("consensus_median"),
               "consensus_high": bb.get("consensus_high"), "consensus_stale": bb.get("consensus_stale"),
               "roe_gap_pts": bb["expectations_gap_pts"],
               # stance is DETERMINISTIC (see _stance_from_gap); the model's own read is kept
               # alongside as telemetry so the two can be compared, never as a gate.
               "stance": _stance_from_gap(bb["expectations_gap_pts"]),
               "stance_model": str(st.get("valuation_stance", "")).lower() or None,
               "achievable": str(st.get("implied_growth_achievable", "")).lower() or None,
               "rationale": st.get("rationale")}
        return res, _fmt_financial(res)
    if bb.get("ok"):
        st = get_assumptions(stage_out, "valuation_stance", _valid_stance, STANCE_SCHEMA) or {}
        res = {"method": "reverse_dcf", "ticker": ticker, "price": price,
               "base_cf_b": round(bb["base_cf"] / 1e9, 2), "base_cf_kind": bb["base_cf_kind"],
               "wacc_pct": bb["wacc_pct"], "implied_growth": bb["implied_growth"],
               "demonstrated_rev_cagr": bb["hist_revenue_cagr_5y"],
               "expectations_gap_pts": bb["expectations_gap_pts"],
               # deterministic FORWARD-anchored, consensus-fenced value — never a model number
               "fair_value": bb.get("fair_value"), "mos_pct": bb.get("mos_pct"),
               "realistic_mos_pct": bb.get("realistic_mos_pct"), "fair_value_method": bb.get("fair_value_method"),
               "forward_growth": bb.get("forward_growth"),
               "consensus_low": bb.get("consensus_low"), "consensus_median": bb.get("consensus_median"),
               "consensus_high": bb.get("consensus_high"), "consensus_stale": bb.get("consensus_stale"),
               # stance is DETERMINISTIC (see _stance_from_gap); the model's own read is kept
               # alongside as telemetry so the two can be compared, never as a gate.
               "stance": _stance_from_gap(bb["expectations_gap_pts"]),
               "stance_model": str(st.get("valuation_stance", "")).lower() or None,
               "achievable": str(st.get("implied_growth_achievable", "")).lower() or None,
               "rationale": st.get("rationale")}
        return res, _fmt_reverse(res)
    # NULL backbone -> financial (multiple) or pre-profit (option bridge)
    sl = (rs2_data.sector_lookup(ticker)[0] or "").lower()
    # A PROFITABLE reinvestment-heavy name is NOT option-led: value it on normalized earning power
    # (Engine 2), never on the Engine-4 option bridge. Without this the backbone's split reason
    # would still land these on the option path. See valuation_backbone's reinvestment_negative_fcf.
    if bb.get("reason") == "reinvestment_negative_fcf" or any(k in sl for k in ("financial", "bank", "insurance")):
        e2 = get_assumptions(stage_out, "normalized_eps", _valid_engine2, ENGINE2_SCHEMA)
        if e2:
            iv = valuation_engine.engine2_cycle(e2["normalized_eps"], e2["normal_multiple"])
            return _multiple_res("engine2_financial", e2, iv, price, ticker)
    # Engine 5 / rNPV — pre-profit clinical biotech. Preferred over the Engine-4 bridge when the
    # backbone built a scaffold: the probability comes from the published phase base-rate table
    # and the floor/dilution from the balance sheet, so the model supplies only the phase (closed
    # set) and the value if the asset works, instead of Engine 4's four free numbers.
    sc = bb.get("rnpv_scaffold")
    if sc:
        e5 = get_assumptions(stage_out, "phase", _valid_engine5, ENGINE5_SCHEMA)
        if e5:
            r = valuation_backbone.rnpv(sc, e5["phase"], e5["value_if_approved_ps"], price)
            if r:
                r.update({"ticker": ticker, "price": price, "inputs": e5})
                return r, _fmt_rnpv(r)

    e4 = get_assumptions(stage_out, "core_value", _valid_engine4, ENGINE4_SCHEMA)
    if e4:
        iv = valuation_engine.engine4_bridge(e4.get("core_value", 0), e4.get("options", []), e4.get("drag", 0))
        return _multiple_res("engine4_option", e4, iv, price, ticker)
    res = {"method": "unvalued", "ticker": ticker, "price": price, "reason": bb.get("reason")}
    return res, (f"VALUATION RESULT: no model ({bb.get('reason')}) and no parseable Engine-4/2 "
                 "inputs. IV [Unverified].")


def resolve_name(ticker):
    """Company name for web-research queries. Zero-network first: the screener's
    financials/{T}.json already carries Name (defeatbeta/yfinance-fed upstream);
    yfinance only as a fallback for names outside the screener universe."""
    fin = rs2_data.load_json(Path(CONFIG["screener_data_dir"]) / "financials" / f"{ticker.upper()}.json") or {}
    name = str(fin.get("Name") or "").strip()
    if name:
        return name
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return info.get("longName") or info.get("shortName") or ""
    except Exception:
        return ""


def run_enrich(ticker):
    print(f"[enrich] yfinance {ticker} ...", flush=True)
    r = subprocess.run([sys.executable, str(HERE / "enrich_ticker.py"), ticker],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[enrich] WARN: {r.stderr[-300:]}", flush=True)


def run_research(ticker, name):
    """Analyst-grade deep research via LDR (research-venv): iterative search + full-page
    reads + citations -> research/{T}.md. Runs on a clean model, no Chrome/GPU contention."""
    rv_py = Path(CONFIG["research_venv_python"])
    if not rv_py.exists():
        print("[research] WARN: research-venv not found — skipping deep research.", flush=True)
        return
    print(f"[research] deep research (LDR) {ticker} ...", flush=True)
    cmd = [str(rv_py), str(HERE / "deep_research.py"), ticker]
    if name:
        cmd.append(name)
    # explicit utf-8 (errors=replace): text=True alone decodes the child's utf-8 output via the
    # ANSI codepage (cp1252) on Windows — the source of the 'â€”' mojibake, and a stray 0x9D/0x9F
    # byte would raise UnicodeDecodeError and abort the whole ticker run
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # surface LDR progress lines + any error
    for line in (r.stdout or "").splitlines():
        if "[deep_research]" in line:
            print("   " + line, flush=True)
    # free the research model's VRAM before RS2 stages load rs2-analyst (no double-load).
    # Done BEFORE the exit-code check so a failed research run still releases the GPU.
    freed = unload_model(CONFIG.get("research_model"))
    # exit 3 = deep_research refused to write an infra-poisoned brief (ollama 500 / OOM).
    # Analysing on top of that is what silently shipped verdicts built on error text, so
    # it is fatal for the ticker: orchestrate marks it failed and retries the name.
    # sys.exit (not raise): an unhandled exception surfaces as a bare 'exit 1' and the
    # orchestrator can't say WHY the ticker failed. These codes are mapped in
    # orchestrate.run_one -> 3 research infra, 7 vram not released.
    if r.returncode == 3:
        print(f"[research] ::HARD FAIL:: {ticker} research aborted (infra error) — "
              f"not analysing on an empty brief.", flush=True)
        keep_awake(False)
        sys.exit(3)
    if r.returncode != 0:
        print(f"[research] WARN: {r.stderr[-500:]}", flush=True)
    if not freed:
        print(f"[research] ::HARD FAIL:: {ticker} — research model VRAM not released; "
              f"refusing to load {CONFIG.get('model')} on top of it (would OOM).", flush=True)
        keep_awake(False)
        sys.exit(7)


# ── pipeline ──────────────────────────────────────────────────────────────
def stage_prompt(data_ctx, accum, task):
    prior = accum if accum.strip() else "(this is the first stage)"
    return (f"{data_ctx}\n\n"
            f"=== PRIOR-STAGE RESULTS (completed; build on these, do not contradict) ===\n{prior}\n\n"
            f"=== YOUR TASK FOR THIS STAGE ===\n{task}")


def final_assembly(t, out_dir, accum, val_block, val_res, price, exit_review, think, use_anchor):
    """Final report + verdict emission, shared by the normal pipeline and --refinal."""
    print(f">> FINAL ASSEMBLY (Sections 0-12) [ctx {CONFIG['final_ctx']}]"
          + ("  [anchored]" if use_anchor else ""), flush=True)
    t0 = time.time()
    anchor = rs2_data.market_anchor(t)
    if exit_review:
        anchor += ("\n\nEXIT REVIEW: this name fell out of the quant research list; the reader may "
                   "still hold it. SECTION 12 must give an explicit HOLD / TRIM / SELL call for a "
                   "current holder, not a fresh-money buy case.")
    if val_block:
        anchor += "\n\n" + val_block + (
            "\n(Use this deterministic valuation verbatim — the expectations gap / IV is "
            "authoritative; do not recompute it.)"
            "\n\nAUDIT COMPLIANCE — a post-completion verifier rejects the report (and the whole "
            "run retries) on any of these:\n"
            "1. Every valuation figure (MoS, fair value, gap, stance, weight) must be COPIED from "
            "the VALUATION RESULT above, never recomputed. If you disagree with a figure, argue "
            "it in prose NEXT TO the authoritative number — do not print your own number in its "
            "place.\n"
            "2. If a CYCLICALITY CHECK disclosed two bases, state EXPLICITLY which basis you judge "
            "fairer and why, in the section where you use it.\n"
            "3. Every factual claim about company events or figures must trace to the research "
            "brief or the data context you were given. No figures from memory.")
    if use_anchor:
        pv = prior_verdict(t, exclude_dir=out_dir)
        if pv:
            anchor += "\n\n" + anchor_block(pv)
        else:
            print("   [anchor] no previous verdict found — running unanchored", flush=True)
    final_prompt = (f"{anchor}\n\n"
                    f"=== COMPLETE WORKED ANALYSIS (all stages) ===\n{accum}\n\n"
                    f"=== TASK ===\n{FINAL_TASK}")
    final = ollama_chat(final_prompt, CONFIG["final_ctx"], think, retries=1, timeout=1200,
                        max_tokens=16384)   # api backend: 13-section report needs a bigger output cap
    # ENGINE-WRITTEN AUTHORITATIVE HEADER (2026-08-08). Four instruction layers (stage prompt,
    # task compliance note, FINAL_TASK structural requirement, Modelfile rule 15) failed to make
    # the model quote the deterministic fair value / MoS — measured over proof runs 4-9, zero
    # mentions every time. Facts the published report MUST carry are therefore TYPED BY THE
    # ENGINE, not requested from the model; the post-completion auditor polices the prose for
    # CONTRADICTIONS of this block instead of for its presence.
    if val_block:
        vr_ = val_res or {}
        fv_line = ""
        if vr_.get("fair_value") is not None or vr_.get("mos_pct") is not None:
            fv_line = (f"AUTHORITATIVE: fair value ${vr_.get('fair_value')} "
                       f"({vr_.get('fair_value_method')}) | MoS {vr_.get('mos_pct')}% vs price "
                       f"${vr_.get('price')} | stance {vr_.get('stance')}\n")
        final = ("═══ ENGINE VALUATION — deterministic, written by the engine (the analyst "
                 "prose below may argue with it, but these are the authoritative figures) ═══\n"
                 + fv_line + val_block.strip() + "\n═══ END ENGINE VALUATION ═══\n\n" + final)
    (out_dir / "FINAL.md").write_text(final, encoding="utf-8")
    print(f"   done in {time.time()-t0:.1f}s\n[DONE] -> {out_dir / 'FINAL.md'}", flush=True)
    return emit_verdict(out_dir, t, price, val_res, final, exit_review=exit_review)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--name", default=None, help="company name for web queries")
    ap.add_argument("--no-enrich", action="store_true")
    ap.add_argument("--no-audit", action="store_true",
                    help="skip the post-completion audit (debugging only — every production "
                         "run must audit; operator order 2026-08-08)")
    ap.add_argument("--no-research", action="store_true")
    ap.add_argument("--no-think", action="store_true")
    ap.add_argument("--api", action="store_true",
                    help="use the cloud LLM in api_llm/config.json instead of local Ollama; "
                         "reports isolated to api_llm/reports (never ingested by the overlay)")
    ap.add_argument("--valonly", action="store_true",
                    help="fast: run S1+S3+S4 only (valuation), skip S2/S5/S6/final report")
    ap.add_argument("--exit-review", action="store_true",
                    help="this name fell OUT of the quant research list; frame the analysis as a "
                         "holder's exit review (explicit HOLD/TRIM/SELL call in SECTION 12)")
    ap.add_argument("--anchor", action="store_true",
                    help="continuity anchor: show the model its own previous verdict at the final "
                         "stage; maintaining it becomes the default (root-cause flip fix; A/B phase "
                         "— not yet enabled in the orchestrator)")
    ap.add_argument("--refinal", metavar="REPORT_DIR", default=None,
                    help="A/B instrument: regenerate ONLY the final assembly + verdict from an "
                         "existing completed report dir; output isolated to ab_reports/ (never "
                         "ingested by the overlay)")
    args = ap.parse_args()
    if args.api:
        # Cloud-LLM A/B mode: same pipeline, prompts and deterministic backbone; only the model
        # transport changes. Reports go to api_llm/reports so the orchestrator/overlay (which
        # aggregate CONFIG out_reports_dir) can never ingest a test verdict.
        global API_MODE
        API_MODE = True
        CONFIG["out_reports_dir"] = str(HERE / "api_llm" / "reports")
        import api_llm.api_chat as _ac
        print(f"[api] backend {_ac.CONFIG['base_url']}  model={_ac.CONFIG['model']}  "
              f"-> reports in api_llm/reports", flush=True)
    keep_awake(True)   # hold the system awake for the whole run (Modern-Standby teardown guard)

    t = args.ticker.upper()
    think = not args.no_think

    if args.refinal:
        # Regenerate ONLY the final call from a frozen, completed analysis — the
        # A/B instrument for measuring emission variance. No data acquisition, no
        # stages, no state writes; output goes to ab_reports/ which the
        # orchestrator/overlay never read. Model left warm for sequential reps.
        src = Path(args.refinal)
        if not src.is_dir():
            src = Path(CONFIG["out_reports_dir"]) / args.refinal
        if not src.is_dir():
            sys.exit(f"--refinal: report dir not found: {args.refinal}")
        val_res = rs2_data.load_json(src / "S3_valuation_inputs.json")
        val_block = ((src / "S4_valuation_result.md").read_text(encoding="utf-8")
                     if (src / "S4_valuation_result.md").exists() else None)
        old_v = rs2_data.load_json(src / "verdict.json") or {}
        price = (val_res or {}).get("price") or old_v.get("price")
        exit_review = bool(old_v.get("exit_review"))
        cap = int(CONFIG.get("stage_carry_char_cap", 4500))
        accum = ""
        for sid, title, _task in STAGES:
            p = src / f"{sid}.md"
            if not p.exists():
                sys.exit(f"--refinal: {p.name} missing in {src} (need a full 6-stage report)")
            out = p.read_text(encoding="utf-8")
            carry = out if len(out) <= cap else out[:cap] + "\n…[truncated]"
            extra = ("\n\n" + val_block) if (sid == "S3_valuation" and val_block) else ""
            accum += f"\n\n----- {title} -----\n{carry}{extra}"
        arm = "anchor" if args.anchor else "plain"
        out_dir = HERE / "ab_reports" / f"{t}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{arm}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[refinal] source={src.name} arm={arm} -> {out_dir.name}", flush=True)
        final_assembly(t, out_dir, accum, val_block, val_res, price, exit_review, think,
                       use_anchor=args.anchor)
        keep_awake(False)
        return

    name = args.name if args.name is not None else resolve_name(t)

    # 1-2. acquire data
    if not args.no_enrich:
        run_enrich(t)
    # Warm the OpenBB cache BEFORE anything reads the consensus band (build_data_context's
    # valuation block AND the verdict backbone) — otherwise a first-ever run fences the prompt's
    # fair value on the enrich band while the verdict later uses the fresh OpenBB band.
    try:
        import openbb_data
        openbb_data.fetch(t)
    except Exception as e:
        print(f"[openbb] cache warm failed (non-fatal): {str(e)[:100]}", flush=True)
    if not args.no_research:
        run_research(t, name)   # LDR deep research (no Chrome; runs before GPU inference)

    # 3. assemble fed data
    data_ctx = rs2_data.build_data_context(t)
    if args.exit_review:
        data_ctx += (
            "\n\n## EXIT REVIEW CONTEXT\n\n"
            "This name has FALLEN OUT of the quant engine's research list (signal decayed vs the "
            "universe — a RELATIVE statement, not automatically a sell). The reader may STILL HOLD "
            "the stock. Purpose of this analysis: a holder's exit review. Do NOT build a fresh-money "
            "buy case; in SECTION 12 give an explicit HOLD / TRIM / SELL call with the reasoning and "
            "what would change it.\n")
    fin = rs2_data.load_json(Path(CONFIG["screener_data_dir"]) / "financials" / f"{t}.json") or {}
    price = fin.get("Price")

    # 4. output tree
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(CONFIG["out_reports_dir"]) / f"{t}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_fed_data.md").write_text(data_ctx, encoding="utf-8")
    # snapshot the deep-research brief INTO the run so the report is self-contained (publish_reports.py
    # prefers this over the shared research/{T}.md, which may be refreshed by a later run).
    _rb = Path(CONFIG["out_research_dir"]) / f"{t}.md"
    if _rb.exists():
        (out_dir / "research.md").write_text(_rb.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[out] {out_dir}\n", flush=True)

    cap = int(CONFIG.get("stage_carry_char_cap", 4500))
    accum = ""
    bb = valuation_backbone.backbone(t)   # deterministic reverse-DCF backbone (computed once)
    if bb.get("method") == "financial_pb_roe":
        bb_msg = (f"FINANCIAL | ROE {bb['roe']*100:.1f}% vs implied {bb['implied_roe']*100:.1f}% | "
                  f"P/B {bb['current_pb']}x vs justified {bb['justified_pb']}x | gap {bb['expectations_gap_pts']}pts")
    elif bb.get("ok"):
        # Report the SAME series the gap is measured against (FFO/share for REITs), not always
        # revenue: logging "implied 0.4% vs demonstrated 28.4% | gap -2.2pts" for O was arithmetic
        # nonsense on its face and would send anyone reading the log chasing a non-existent bug.
        _demo = bb.get("demonstrated_cagr")
        if _demo is None:
            _demo = bb.get("hist_revenue_cagr_5y") or 0
        bb_msg = (f"base_cf ${bb['base_cf']/1e9:.2f}B [{bb['base_cf_kind']}] WACC {bb['wacc_pct']}% | "
                  f"implied {bb['implied_growth']*100:.1f}% vs demonstrated "
                  f"{_demo*100:.1f}% [{bb.get('demonstrated_cagr_kind', 'revenue_cagr_5y')}] | "
                  f"gap {bb['expectations_gap_pts']}pts")
    elif bb.get("reason") == "reinvestment_negative_fcf":
        bb_msg = f"NULL ({bb.get('reason')}) -> PROFITABLE but capex > D&A: normalized-earnings path"
    elif bb.get("rnpv_scaffold"):
        bb_msg = f"NULL ({bb.get('reason')}) -> clinical-stage biotech: Engine 5 / rNPV path"
    else:
        bb_msg = f"NULL ({bb.get('reason')}) -> pre-profit / option-led path"
    print(f"[backbone] {t}: {bb_msg}", flush=True)
    val_res = None
    val_block = None
    stages = [s for s in STAGES if s[0] in ("S1_macro_classify", "S3_valuation", "S4_scenarios")] if args.valonly else STAGES
    # GUARANTEED VRAM RELEASE (2026-08-08): normal paths call _release() at their existing
    # sites (idempotent); the __main__ wrapper force-unloads on any uncaught exception. Proof
    # run 7 died at a stage-level empty-content raise, left rs2-analyst resident, and the next
    # run's research barrier hard-failed on the leaked VRAM.
    _released = {"done": False}

    def _release():
        if not _released["done"]:
            _released["done"] = True
            unload_model(CONFIG["model"])
            keep_awake(False)

    for sid, title, task in stages:
        print(f">> {title}", flush=True)
        t0 = time.time()
        content = stage_prompt(data_ctx, accum, task)
        out = ollama_chat(content, CONFIG["stage_ctx"], think)
        (out_dir / f"{sid}.md").write_text(out, encoding="utf-8")
        print(f"   done in {time.time()-t0:.1f}s -> {sid}.md", flush=True)

        # ── inverted valuation hooks (deterministic backbone + model judgment) ──
        extra = ""
        if sid == "S1_macro_classify":
            # CYCLICAL ROUTING. The archetype is a CLASSIFICATION (the model is good at those);
            # it selects the normalization BASIS only — every number stays deterministic, and the
            # model never sees or sets a valuation. Guarded to genuinely single-year base_cf kinds
            # so it can only ever average, never invent.
            arch = _archetype(out)
            if arch == "C" and bb.get("ok") and bb.get("base_cf_kind") in _LATEST_FY_KINDS:
                bb2 = valuation_backbone.backbone(t, force_midcycle=True)
                shown = bb2.get("ok") and bb2.get("base_cf_kind", "").startswith("midcycle")
                if not shown:
                    # fcf_ttm_yf is a single trailing figure with no history to average; record
                    # the attempt rather than no-op silently.
                    (out_dir / "routing.json").write_text(json.dumps({
                        "archetype": arch, "disclosed": False, "reason": "no_averageable_history",
                        "base_cf_kind": bb.get("base_cf_kind")}, indent=2), encoding="utf-8")
                if shown:
                    print(f"   [routing] archetype C (cyclical) — DISCLOSING both bases: latest-FY "
                          f"${bb['base_cf']/1e9:.2f}B (gap {bb['expectations_gap_pts']}pts) vs "
                          f"mid-cycle ${bb2['base_cf']/1e9:.2f}B (gap "
                          f"{bb2['expectations_gap_pts']}pts). base_cf UNCHANGED.", flush=True)
                    (out_dir / "routing.json").write_text(json.dumps({
                        "archetype": arch, "disclosed": True, "base_cf_changed": False,
                        "in_use": "latest_fy",
                        "latest_fy": {"kind": bb["base_cf_kind"], "base_cf": bb["base_cf"],
                                      "implied_growth": bb["implied_growth"],
                                      "gap_pts": bb["expectations_gap_pts"]},
                        "midcycle": {"kind": bb2["base_cf_kind"], "base_cf": bb2["base_cf"],
                                     "implied_growth": bb2["implied_growth"],
                                     "gap_pts": bb2["expectations_gap_pts"]}}, indent=2),
                        encoding="utf-8")
                    # DISCLOSE, do not overwrite. Whether the latest year is a trough/peak (average
                    # it) or a secular high (do not) cannot be settled from ~10 noisy annual points
                    # -- see _midcycle_of_kind for the four approaches measured and how each failed.
                    # So give the analyst layer both numbers and let it judge; every figure the
                    # engine scores stays exactly as the deterministic backbone computed it.
                    extra = ("\n\n## CYCLICALITY CHECK (you classified this CYCLICAL)\n"
                             f"- The VALUATION block's base cash flow is a SINGLE fiscal year "
                             f"({bb['fiscal_year']}): ${bb['base_cf']/1e9:.2f}B, implying "
                             f"{bb['implied_growth']*100:.1f}%/yr growth, gap "
                             f"{bb['expectations_gap_pts']:+.0f}pts.\n"
                             f"- On a MID-CYCLE average of the same metric it would be "
                             f"${bb2['base_cf']/1e9:.2f}B, implying {bb2['implied_growth']*100:.1f}%/yr, "
                             f"gap {bb2['expectations_gap_pts']:+.0f}pts.\n"
                             "- Neither is automatically right. If the latest year is a cycle TROUGH "
                             "or PEAK, the mid-cycle figure is the fairer read. If the business has "
                             "grown SECULARLY (the average is dragged down by a much smaller past), "
                             "the latest year is the fairer read and the mid-cycle number understates "
                             "it. Decide which from the business evidence and SAY WHICH YOU USED. "
                             "The engine scores the single-year figure; argue explicitly if you "
                             "think that overstates or understates the gap.")
            elif arch and bb.get("ok") and str(bb.get("base_cf_kind", "")).startswith("midcycle"):
                # MIRROR disclosure for names the SECTOR RULE already averaged. Measured
                # 2026-08-07: 42 live names carry a midcycle base, and for 55% of them the
                # latest-FY figure is >1.5x the average (HWM $1.8B run-rate vs $0.63B average,
                # POWL 3.15x) — a secular grower's average is dragged down by a much smaller
                # past, and the model never saw the single-year basis to argue it. Fires for ANY
                # parsed archetype: the averaging was imposed by sector, not by the model's
                # letter, so the model must see both bases regardless of what it classified.
                bb3 = valuation_backbone.backbone(t, force_latest=True)
                shown = bb3.get("ok") and bb3.get("base_cf_kind") in _LATEST_FY_KINDS
                if not shown:
                    (out_dir / "routing.json").write_text(json.dumps({
                        "archetype": arch, "disclosed": False, "reason": "no_latest_fy_base",
                        "base_cf_kind": bb.get("base_cf_kind")}, indent=2), encoding="utf-8")
                if shown:
                    print(f"   [routing] mid-cycle base in use — DISCLOSING both bases: mid-cycle "
                          f"${bb['base_cf']/1e9:.2f}B (gap {bb['expectations_gap_pts']}pts) vs "
                          f"latest-FY ${bb3['base_cf']/1e9:.2f}B (gap "
                          f"{bb3['expectations_gap_pts']}pts). base_cf UNCHANGED.", flush=True)
                    (out_dir / "routing.json").write_text(json.dumps({
                        "archetype": arch, "disclosed": True, "base_cf_changed": False,
                        "in_use": "midcycle",
                        "latest_fy": {"kind": bb3["base_cf_kind"], "base_cf": bb3["base_cf"],
                                      "implied_growth": bb3["implied_growth"],
                                      "gap_pts": bb3["expectations_gap_pts"]},
                        "midcycle": {"kind": bb["base_cf_kind"], "base_cf": bb["base_cf"],
                                     "implied_growth": bb["implied_growth"],
                                     "gap_pts": bb["expectations_gap_pts"]}}, indent=2),
                        encoding="utf-8")
                    extra = ("\n\n## CYCLICALITY CHECK (mid-cycle base in use)\n"
                             f"- The VALUATION block's base cash flow is a MID-CYCLE AVERAGE: "
                             f"${bb['base_cf']/1e9:.2f}B, implying "
                             f"{bb['implied_growth']*100:.1f}%/yr growth, gap "
                             f"{bb['expectations_gap_pts']:+.0f}pts.\n"
                             f"- On the LATEST fiscal year ({bb3['fiscal_year']}) alone it would "
                             f"be ${bb3['base_cf']/1e9:.2f}B, implying "
                             f"{bb3['implied_growth']*100:.1f}%/yr, gap "
                             f"{bb3['expectations_gap_pts']:+.0f}pts.\n"
                             "- Neither is automatically right. If the business has grown "
                             "SECULARLY (the average is dragged down by a much smaller past), "
                             "the latest year is the fairer read and the mid-cycle number "
                             "understates earning power. If the latest year is a cycle PEAK, "
                             "the average is the fairer read. Decide which from the business "
                             "evidence and SAY WHICH YOU USED. The engine scores the mid-cycle "
                             "figure; argue explicitly if you think that overstates or "
                             "understates the gap.")
            elif arch:
                # telemetry only — lets the archetype/route agreement be measured over time.
                # Same "disclosed" key as the branch above so the field is uniform across runs.
                (out_dir / "routing.json").write_text(json.dumps({
                    "archetype": arch, "disclosed": False, "reason": "not_a_single_year_base_cf",
                    "base_cf_kind": bb.get("base_cf_kind"),
                    "method": bb.get("method") or bb.get("reason")}, indent=2), encoding="utf-8")
        if sid == "S3_valuation":
            val_res, val_block = valuation_result(out, bb, price, t)
            extra = "\n\n" + val_block
            (out_dir / "S3_valuation_inputs.json").write_text(json.dumps(val_res, indent=2), encoding="utf-8")
            (out_dir / "S4_valuation_result.md").write_text(val_block, encoding="utf-8")
            if val_res.get("method") == "reverse_dcf":
                print(f"   [valuation] reverse-DCF gap {val_res['expectations_gap_pts']}pts | "
                      f"stance {val_res.get('stance')} (achievable {val_res.get('achievable')})", flush=True)
            elif val_res.get("method") == "financial_pb_roe":
                print(f"   [valuation] financial ROE-gap {val_res['roe_gap_pts']}pts | fair "
                      f"${val_res.get('fair_value')} MoS {val_res.get('mos_pct')}% | stance {val_res.get('stance')}", flush=True)
            else:
                print(f"   [valuation] {val_res.get('method')} IV {val_res.get('iv')} "
                      f"MoS {val_res.get('mos_pct')}%" + (f" [{val_res['flag']}]" if val_res.get('flag') else ""), flush=True)
        elif sid == "S4_scenarios":
            probs = get_assumptions(out, "base", valuation_io.valid_scenario_probs, PROBS_SCHEMA)
            if probs and val_res is not None:
                val_res["scenario_probs"] = probs
                (out_dir / "S3_valuation_inputs.json").write_text(json.dumps(val_res, indent=2), encoding="utf-8")
                print(f"   [valuation] scenario probs {probs}", flush=True)
        print("", flush=True)

        carry = out if len(out) <= cap else out[:cap] + "\n…[truncated]"
        accum += f"\n\n----- {title} -----\n{carry}{extra}"

    if args.valonly:
        (out_dir / "val_summary.json").write_text(json.dumps(val_res or {}, indent=2), encoding="utf-8")
        if val_res and val_res.get("method") == "reverse_dcf":
            print(f"[VALONLY DONE] {t}: reverse-DCF gap {val_res['expectations_gap_pts']}pts "
                  f"stance {val_res.get('stance')} -> {out_dir / 'val_summary.json'}", flush=True)
        else:
            print(f"[VALONLY DONE] {t}: {(val_res or {}).get('method')} "
                  f"IV {(val_res or {}).get('iv')} MoS {(val_res or {}).get('mos_pct')}%", flush=True)
        _release()
        # diagnostic runs still get the deterministic audit (no FINAL/verdict to check)
        if not args.no_audit:
            aud_ok, checks = deterministic_audit(t, out_dir, val_res, level="valonly")
            (out_dir / "audit.json").write_text(json.dumps(
                {"tier1_pass": aud_ok, "tier1": checks, "tier2": "skipped_valonly"}, indent=2),
                encoding="utf-8")
            if not aud_ok:
                bad = "; ".join(f"{c['check']}: {c['detail']}" for c in checks if not c["ok"])
                print(f"[AUDIT] ::FAILED:: {t} (valonly tier-1) — {bad}", flush=True)
                sys.exit(11)
            print(f"[AUDIT] ok — {t}: {len(checks)} deterministic checks passed", flush=True)
        return

    # Final assembly consolidates prior stages — it does NOT need the bulky raw
    # research/priming blocks again. Compact verified anchor + the engine's
    # computed VALUATION RESULT (authoritative IV/MoS) + the stage results.
    final_assembly(t, out_dir, accum, val_block, val_res, price, args.exit_review, think,
                   use_anchor=args.anchor)

    # Prove the run produced a real analysis before it is allowed to count as done.
    ok, problems = sanity_check(out_dir, t)
    if not ok:
        _release()
        detail = "; ".join(problems)
        print(f"\n[SANITY] ::FAILED:: {t} — {len(problems)} problem(s): {detail}", flush=True)
        ops.notify_telegram(
            f"[RS2 ops] sanity_failed — {t} produced a bad/empty analysis "
            f"({len(problems)} problem(s)). Report: {out_dir.name}. Ticker will retry.\n{detail[:600]}")
        # non-zero exit -> orchestrate marks the name failed and re-queues it, exactly like
        # a watchdog kill, instead of publishing a hollow verdict to the overlay
        sys.exit(6)
    print(f"[SANITY] ok — {t}: stages, FINAL.md and verdict.json all present and substantive",
          flush=True)

    # POST-COMPLETION AUDIT (operator order 2026-08-08): tier-1 re-derives the deterministic
    # facts; tier-2 has the model VERIFY the assembled report against the authoritative
    # numbers while it is still loaded. Either failure fails the ticker (exit 7/8) so
    # orchestrate retries it — a bad analysis must never publish.
    aud_ok, checks, ai_status, viols = True, [], "skipped", []
    if not args.no_audit:
        # A defect in the AUDITOR must never kill a run whose artefacts are sound (the first
        # live proof did exactly that: an oversized tier-2 context crashed MU after a good
        # verdict). Auditor exceptions record as infra-inconclusive; the exits below fire only
        # on POSITIVE findings.
        try:
            aud_ok, checks = deterministic_audit(t, out_dir, val_res, level="full")
            if aud_ok:
                ai_status, viols = ai_audit(t, out_dir, think)
        except Exception as e:
            ai_status = "inconclusive"
            checks.append({"check": "audit.infra", "ok": True,
                           "detail": f"auditor exception: {str(e)[:200]}"})
            ops.notify_telegram(f"[RS2 ops] audit_infra — {t}: auditor raised "
                                f"{str(e)[:150]}; run passed on artefact checks only.")
    _release()   # free VRAM so the next ticker's research starts clean
    if not args.no_audit:
        (out_dir / "audit.json").write_text(json.dumps(
            {"tier1_pass": aud_ok, "tier1": checks,
             "tier2": ai_status, "tier2_violations": viols}, indent=2), encoding="utf-8")
        if not aud_ok:
            bad = "; ".join(f"{c['check']}: {c['detail']}" for c in checks if not c["ok"])
            print(f"\n[AUDIT] ::FAILED:: {t} tier-1 (deterministic) — {bad}", flush=True)
            ops.notify_telegram(f"[RS2 ops] audit_failed — {t} tier-1 deterministic audit: "
                                f"{bad[:500]}. Report: {out_dir.name}. Ticker will retry.")
            sys.exit(11)   # 3=research infra, 6=sanity, 7=VRAM hard-fail — audit gets 11/12
        if ai_status == "fail":
            vtxt = "; ".join(f"{v.get('type')}: {v.get('detail')}" for v in viols)[:500]
            print(f"\n[AUDIT] ::FAILED:: {t} tier-2 (AI verifier) — {vtxt}", flush=True)
            ops.notify_telegram(f"[RS2 ops] audit_failed — {t} tier-2 AI verifier found "
                                f"material violations: {vtxt}. Report: {out_dir.name}. "
                                f"Ticker will retry.")
            sys.exit(12)
        if ai_status == "inconclusive":
            print(f"[AUDIT] tier-2 inconclusive (auditor output unparseable) — run passes on "
                  f"tier-1; logged for review", flush=True)
            ops.notify_telegram(f"[RS2 ops] audit_inconclusive — {t}: tier-2 auditor output "
                                f"unparseable twice; run passed on tier-1 only. {out_dir.name}")
        else:
            print(f"[AUDIT] ok — {t}: {len(checks)} deterministic checks + AI verifier "
                  f"({ai_status})", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        main()
    except SystemExit:
        raise                     # deliberate exits already released the model at their sites
    except BaseException:
        # Uncaught crash anywhere in the pipeline: force-release the analyst model before the
        # traceback, or the resident instance strands ~22GB and every subsequent run's VRAM
        # barrier hard-fails until the keep_alive expires (proof runs 7->8, 2026-08-08).
        try:
            unload_model(CONFIG["model"])
            keep_awake(False)
        except Exception:
            pass
        raise
