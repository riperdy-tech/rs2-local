#!/usr/bin/env python3
"""consensus_valuation.py — the unshackled depth tier, with the two guards that replace the rules.

DIRECTION (operator, 2026-08-20): stop constraining the model into a deterministic scaffold and
let it produce its own valuation from our static data, the way a cloud model would. Accept the
answer provided (a) it is not farfetched, and (b) repeated runs agree within a tolerance. Put our
diligence into the DATA instead.

That trade only works if (a) and (b) are actually enforced, so this module is those two tests.

GUARD 1 — PLAUSIBILITY. REDESIGNED 2026-08-24 from a deleter into an annotator; see
audit/N_guard_redesign_study_20260824.md and the docstring of plausibility() below. A sample is
refused only when it is not a genuine, complete statement of a view — no value parsed, empty
report, or truncation at the output cap. The four calibrated thresholds (analyst band, OCF
multiple, 52-week range, |MoS|) still compute and are recorded as FLAGS on the run and on the
verdict, but they no longer destroy a vote: under band-direction an outlier already widens the
band, and a wider band already cuts the position size, so rejection was punishing extremity twice
while deleting the evidence of doubt.

GUARD 2 — TOLERANCE. Run the analysis N times and measure the spread. Report the MEDIAN, and
flag when the runs disagree by more than TOL. This is the honest replacement for a deterministic
number: not "the model is right" but "the model is repeatable, and here is by how much".

MEASURED WARNING, do not skip: the two unshackled arms on GOOG landed at $171-181 and $310 — a
1.8x spread on configurations differing only in quantization. At n=1 this tier is NOT within any
sane tolerance. Consensus over several samples is not optional decoration; it is what makes the
output usable at all.

  python tools/audit_202608/consensus_valuation.py GOOG --samples 3
"""
import hashlib
import io
import json
import re
import statistics as st
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import common  # noqa: E402
common.enable_json_cache()
import capability_test as cap  # noqa: E402
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402
from fiduciary_gate import validate_fiduciary_contract  # noqa: E402

OUT = HERE / "ab_reports" / "consensus"
# THRESHOLDS — calibrated against four reference points on GOOG @ $343.54, not invented:
#   $702.49 published by our own pipeline on a contaminated base  -> MUST reject
#   $205    external frontier-model benchmark                     -> MUST pass
#   $280-310 a third model's argued range / our arm D $310        -> MUST pass
#   $171-181 our arm C                                            -> MUST pass
# ASYMMETRIC BY DESIGN. Sell-side targets skew optimistic and this book is structurally bearish
# (median MoS -51.8%), so being far BELOW analysts is ordinary and being far ABOVE them is the
# farfetched direction. A symmetric band would have rejected the $205 benchmark.
#
# Malfunction fence, written in convention (A): mos = IV/price - 1. It is ONE-SIDED BY
# CONSTRUCTION - |IV/price - 1| cannot exceed 1 on the downside, since IV/price - 1 >= -1 - so it
# trips only when IV > 2.5x price. Measured 2026-09-20: all six published trips are positive and
# a recorded -99.4% MoS passed it untouched. A downside fence must be written separately; this
# constant cannot supply one, and nothing here should be read as symmetric.
# NOT a shared definition: valuation_backbone.MOS_EXTREME_MAX is an independent literal holding
# the same value, and the two are free to drift.
MOS_EXTREME = 1.50
BAND_HIGH_MULT = 1.5        # above 1.5x the PV'd analyst HIGH -> farfetched ($702 is 1.63x)
BAND_LOW_DIV = 3.0          # below 1/3 of the PV'd analyst LOW -> farfetched (deliberately loose)
OCF_MULT_MAX = 75.0         # Informative annotation flag; catches truly detached trailing multiples (>75x)
TOL_PCT = 25.0              # runs disagreeing by more than this (max/min-1) are not converged
EARLY_TOL_PCT = 15.0        # 2-sample early-stop bar. DELIBERATELY TIGHTER than TOL_PCT: two
                            # draws agreeing is weaker evidence of stability than three
                            # (expected 2-sample spread ~1.1x the true scatter vs ~1.7x for
                            # three), so early publication demands closer agreement. Two samples
                            # inside 15% -> publish median of 2; anything else -> third sample,
                            # judged at TOL_PCT.
NUM_PREDICT = 65536         # output budget per sample. At the old ctx 65,536 the 49,152 cap was
                            # already the ctx wall (prompt ~16.4K), and one GOOG sample hit it -
                            # report cut mid-write, vote discarded. ctx 81,920 buys ~16K more.

IV_PATTERNS = [
    r"intrinsic value[^\n]{0,80}?\$\s*([\d,]+(?:\.\d{1,2})?)",
    r"\bbase (?:case )?IV\b[^\n]{0,40}?\$\s*([\d,]+(?:\.\d{1,2})?)",
    r"IV \(base\)[^\n]{0,30}?\$\s*([\d,]+(?:\.\d{1,2})?)",
    r"fair value[^\n]{0,80}?\$\s*([\d,]+(?:\.\d{1,2})?)",
    # "Probability-weighted IV ≈ $190" (AZN s3, 2026-08-22) — a real vote dropped because no
    # pattern covered bare "IV" plus a connector. Tight on purpose: literal IV, one of ≈/=/:,
    # then $, so the adjacent "50% CI $170-215" cannot match.
    r"\bIV\s*[≈=:]\s*\$\s*([\d,]+(?:\.\d{1,2})?)",
    # "IV (base case, 3-yr): $154" / "IV (probability-weighted): $159" (CIEN s2, 2026-08-22) —
    # a parenthetical qualifier between IV and the number. Bounded qualifier, no newline, then
    # an optional connector and $.
    r"\bIV\s*\([^)\n]{0,40}\)\s*[:=≈]?\s*\$\s*([\d,]+(?:\.\d{1,2})?)",
]


def extract_iv(report, price):
    """Best per-share intrinsic value the report states. Ignores figures that cannot be a per-share
    value for this name (a 10x-of-price filter), which is deliberately loose — the plausibility
    guard below is what judges the number, not the parser."""
    vals = []
    for p in IV_PATTERNS:
        for m in re.finditer(p, report, re.I):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if price and 0.02 * price <= v <= 10 * price:
                vals.append(v)
    return vals


def extract_scorecard(report, price):
    """Extracts the complete 4-KPI Institutional Decision Vector from the report.
    Prioritizes the structured ```json:underwriting block; falls back to narrative regex."""
    card = {
        "base_iv": None,
        "bull_iv": None,
        "bear_iv": None,
        # The JSON copy loop below is driven by THIS dict, so a key the model emits but that is
        # absent here is discarded unrecoverably - `parsed` goes out of scope and this whitelist
        # is the function's only return. TASK asks for all three; measured 2026-09-20, GEV's
        # sample 2 emitted 0.4 / 0.35 / 0.25 and every one was dropped, which is why the
        # fiduciary validator's probability leg always ran on hardcoded defaults.
        "base_probability": None,
        "bull_probability": None,
        "bear_probability": None,
        # The Task 2 lesson applies to every later field: this whitelist IS the schema, so a
        # field the model emits but that is absent here is dropped unrecoverably.
        "base_cf_used": None,
        "base_cf_basis": None,
        "conviction_score": None,
        "business_quality_moat": None,
        "kelly_fraction_pct": None,
        "asymmetric_payoff_skew": None,
        "reentry_tranches": {"tranche_1_starter": None, "tranche_2_core": None},
        "thesis_invalidation_trigger": None
    }
    
    # 1. Primary: Structured JSON block from Section 12
    jm = re.search(r"```json:underwriting\s*(\{.*?\})\s*```", report, re.DOTALL)
    if not jm:
        jm = re.search(r"```json\s*(\{\s*\"base_iv\".*?\})\s*```", report, re.DOTALL)
    if jm:
        try:
            parsed = json.loads(jm.group(1))
            for k in card:
                if k in parsed and parsed[k] is not None:
                    card[k] = parsed[k]
            if card["base_iv"] and price and 0.02 * price <= card["base_iv"] <= 10 * price:
                return card
        except Exception:
            pass

    # 2. Fallback: Narrative extraction
    ivs = extract_iv(report, price)
    if ivs:
        card["base_iv"] = st.median(ivs)

    # Bull IV
    bull_m = re.search(r"\bbull(?:-case)?(?:\s*IV)?\s*[:=≈]?\s*\$\s*([\d,]+(?:\.\d{1,2})?)", report, re.I)
    if bull_m:
        try:
            bv = float(bull_m.group(1).replace(",", ""))
            if price and 0.02 * price <= bv <= 15 * price:
                card["bull_iv"] = bv
        except Exception:
            pass

    # Bear IV
    bear_m = re.search(r"\bbear(?:-case)?(?:\s*IV)?\s*[:=≈]?\s*\$\s*([\d,]+(?:\.\d{1,2})?)", report, re.I)
    if bear_m:
        try:
            brv = float(bear_m.group(1).replace(",", ""))
            if price and 0.01 * price <= brv <= 10 * price:
                card["bear_iv"] = brv
        except Exception:
            pass

    # Conviction Score (out of 15)
    conv_m = re.search(r"\bCONVICTION:\s*(?:[A-Z]+\s*)?\(?(\d+(?:\.\d+)?)\s*/\s*15", report, re.I)
    if conv_m:
        try:
            card["conviction_score"] = float(conv_m.group(1))
        except Exception:
            pass

    # Business Quality / Moat Score (1 to 5)
    moat_m = re.search(r"\b(?:Business Quality|Moat(?: Score)?)\s*[:=≈]\s*([1-5](?:\.\d+)?)\s*/\s*5", report, re.I)
    if moat_m:
        try:
            card["business_quality_moat"] = float(moat_m.group(1))
        except Exception:
            pass

    # Kelly fraction
    kelly_m = re.search(r"\bKelly\s*f\*?\s*=?\s*(\d+(?:\.\d+)?)\%?", report, re.I)
    if kelly_m:
        try:
            card["kelly_fraction_pct"] = float(kelly_m.group(1))
        except Exception:
            pass

    # Re-entry Tranches
    t1_m = re.search(r"≤\s*\$?([\d,]+(?:\.\d{1,2})?)\s*(?:with KPI|.*?starter)", report, re.I)
    if t1_m:
        try:
            card["reentry_tranches"]["tranche_1_starter"] = float(t1_m.group(1).replace(",", ""))
        except Exception:
            pass
    t2_m = re.search(r"≤\s*\$?([\d,]+(?:\.\d{1,2})?)\s*\((?:base|core)", report, re.I)
    if t2_m:
        try:
            card["reentry_tranches"]["tranche_2_core"] = float(t2_m.group(1).replace(",", ""))
        except Exception:
            pass

    # Invalidation Trigger
    inv_m = re.search(r"\bINVALIDATION(?:\s*\([^)]*\))?\s*:(.*?)(?:\n\s*[A-Z0-9_-]+:|\n\s*════|\Z)", report, re.I | re.DOTALL)
    if inv_m:
        card["thesis_invalidation_trigger"] = re.sub(r"\s+", " ", inv_m.group(1)).strip()

    # Derived Asymmetric Payoff Skew
    if price and card["bull_iv"] and card["bear_iv"] and (price - card["bear_iv"]) > 0:
        card["asymmetric_payoff_skew"] = round((card["bull_iv"] - price) / (price - card["bear_iv"]), 2)

    return card


def plausibility(iv, price, ticker):

    """(ok, [reasons], [flags]) — usability is an INTEGRITY question; the calibrated thresholds
    only ANNOTATE.

    REDESIGNED 2026-08-24, per audit/N_guard_redesign_study_20260824.md. The four thresholds below
    were fitted to four reference points on ONE ticker on ONE day and then applied to every name.
    Measured across the first 28 published verdicts they rejected 6 samples: all 6 AGREED with
    their surviving siblings on DIRECTION, 0 verdict directions changed, and the only live effect
    was narrowing bands — AVGO's spread fell 64% -> 2% and its size hint rose quarter -> full on
    evidence that did not support it. Two rejections turned on rounding (AMD at exactly 40.0x
    against a 40x cap). Against the real outlier signal the tests are near-orthogonal: they caught
    the single most divergent sample in the corpus and kept the next three.

    Rejection was the right mechanism for a POINT-ESTIMATE system, where one bad number BECAME the
    published answer. Under band-direction it is not. An outlier widens the band, a wider band
    raises the spread, and spread already cuts the position-size hint — the scheme penalises
    extremity proportionally on its own, and deleting a sample destroys the very quantity it uses
    to express doubt. Checked against the original malfunction: GOOG's $702.49 arriving beside
    $300 and $333 gives a $300-$702 band containing the $343.54 price -> hold, enormous spread,
    quarter size. Correct and honest with no guard acting at all.

    What is left is what a threshold cannot judge — whether the sample is a genuine, complete
    statement of a view. Completeness is enforced by the caller (empty-report retry, and
    done_reason == "length" for truncation); absolute impossibility is enforced upstream by
    extract_iv's 0.02x-10x-of-price envelope. So this function refuses one thing: a missing value.
    """
    flags = []
    if not iv or not price or iv <= 0:
        return False, ["no value extracted"], flags
    mos = iv / price - 1
    if abs(mos) > MOS_EXTREME:
        flags.append(f"mos_{mos*100:+.0f}pct_beyond_{MOS_EXTREME*100:.0f}pct")
    band = vb._consensus_band(ticker)
    if band and not band.get("stale"):
        wacc = 0.10
        lo, hi = band["low"] / (1 + wacc), band["high"] / (1 + wacc)
        if iv > hi * BAND_HIGH_MULT:
            flags.append(f"above_analyst_high_{iv/hi:.2f}x_cap_{BAND_HIGH_MULT}x")
        if iv < lo / BAND_LOW_DIV:
            flags.append(f"below_analyst_low_{iv/lo:.2f}x_floor_{1/BAND_LOW_DIV:.2f}x")
    # implied multiple on trailing OPERATING CASH FLOW — the test that catches a value built by
    # capitalising non-operating income, because OCF cannot contain a mark-to-market gain.
    _rec = ((rs2_data.load_json(common.SD / "fundamentals_ttm.json") or {})
            .get("tickers", {}).get(ticker.upper(), {}) or {})
    # Same alignment gate as build_pack: a TTM record anchored to a different fiscal year than the
    # newest annual one is stranded, and dividing by its OCF produces a nonsense ceiling. Measured
    # 2026-08-24: on LITE, PAYX, PCTY and SENEB the stale-OCF ceiling sits BELOW the share price,
    # so every defensible valuation would be auto-rejected (PCTY: $35.49 cap on a $153.34 stock).
    # When the gate fires the fence goes INERT rather than firing on a discarded figure.
    _hy = [int(y) for y in (rs2_data.load_json(common.SD / "fundamentals_history.json") or {})
           .get("tickers", {}).get(ticker.upper(), {}) if str(y).isdigit()]
    _stale = bool(_rec and _hy
                  and int(str(_rec.get("fy_leg_end", ""))[:4] or 0) != max(_hy))
    ttm = {} if _stale else (_rec.get("fields") or {})
    ocf = vb._num(ttm.get("ocf"))
    fin = rs2_data.load_json(common.SD / "financials" / f"{ticker.upper()}.json") or {}
    sh = vb._num(fin.get("Shares_Outstanding"))
    if ocf and sh and ocf > 0:
        mult = iv / (ocf / sh)
        if mult > OCF_MULT_MAX:
            # Annotation only, and this test is why. It compares a FORWARD-LOOKING value to
            # TRAILING cash flow, so it fires hardest on companies whose cash flow is growing.
            # Measured: it called AMD's $247 "not backed by cash" at 40.0x while the market was
            # paying $473.25 — 76.6x — for the same trailing OCF. Deleting on it removed the
            # bullish tail specifically, biasing high-multiple names toward "overvalued".
            flags.append(f"ocf_multiple_{mult:.1f}x_cap_{OCF_MULT_MAX:.0f}x")
    en = rs2_data.load_json(HERE / "enrich" / f"{ticker.upper()}.json") or {}
    hi52, lo52 = en.get("fifty_two_week_high"), en.get("fifty_two_week_low")
    if hi52 and iv > hi52 * 2:
        flags.append(f"above_52w_high_{iv/hi52:.2f}x")
    if lo52 and iv < lo52 / 3:
        flags.append(f"below_52w_low_{iv/lo52:.2f}x")
    return True, [], flags


def continue_report(model, pack, partial_report, ctx=81920, timeout=1800, seed=None,
                    draft_num_predict=None, temperature=None):
    """Rescues a truncated memorandum by issuing a continuation turn to Ollama.
    Reclaims 40k+ tokens of headroom by feeding the pack + partial report as assistant turn."""
    cutoff_snippet = partial_report[-250:].strip()
    continuation_prompt = (
        "Your institutional memorandum was truncated at the context wall mid-sentence.\n\n"
        f"The cutoff point was:\n\"... {cutoff_snippet}\"\n\n"
        "CONTINUATION INSTRUCTIONS:\n"
        "1. Pick up IMMEDIATELY from that exact unfinished sentence and complete it seamlessly.\n"
        "2. Complete any remaining analysis sections (Valuation Triad, Balance Sheet Audit, Risks, Milestones).\n"
        "3. Conclude with Section 12: Machine Contract containing the complete ```json:underwriting block with all fields:\n"
        "   - base_iv, bull_iv, bear_iv\n"
        "   - conviction_score (out of 15)\n"
        "   - business_quality_moat (1 to 5)\n"
        "   - kelly_fraction_pct\n"
        "   - asymmetric_payoff_skew\n"
        "   - reentry_tranches: {tranche_1_starter, tranche_2_core}\n"
        "   - thesis_invalidation_trigger\n\n"
        "Do NOT repeat the prior sections. Proceed directly with the continuation."
    )
    messages = [
        {"role": "user", "content": pack},
        {"role": "assistant", "content": partial_report},
        {"role": "user", "content": continuation_prompt}
    ]
    opts = {
        "num_ctx": ctx,
        "num_predict": 32768,
        "temperature": temperature if temperature is not None else 0.6,
        "repeat_penalty": 1.05,
        "presence_penalty": 0.05
    }
    if seed is not None:
        opts["seed"] = seed
    if draft_num_predict is not None:
        opts["draft_num_predict"] = draft_num_predict

    body = {
        "model": model,
        "stream": False,
        "think": "high",
        "messages": messages,
        "options": opts
    }
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
        msg = resp.get("message") or {}
        rep_cont = msg.get("content") or ""
        think_cont = msg.get("thinking") or ""
        done_reason = resp.get("done_reason")
        gen_tok = resp.get("eval_count") or 0
        return rep_cont, think_cont, {"done_reason": done_reason, "generated_tokens": gen_tok}
    except Exception as e:
        print(f"  [continue_report error]: {e}", flush=True)
        return "", "", {"done_reason": "error", "error": str(e)}


def select_medoid_scorecard(
    runs: list,
    price: float,
    eff_tol: float = TOL_PCT
) -> tuple:
    """Select the Medoid (Central Anchor Sample) from valid runs and compute consensus dispersion.

    Eliminates independent column medians by identifying the single most central sample
    whose Base IV and Moat are closest to the multi-sample medians. The complete, coherent
    Section 12 contract is taken directly from this sample.

    FIELD OWNERSHIP (fixed 2026-09-20). The returned summary carries TWO distinct IVs and they
    must never be used interchangeably:
      * `base_iv`   — the medoid's own base case. The CONTRACT BASE. Owns MoS and Kelly sizing.
      * `median_iv` — cross-sample median. A DISPERSION statistic for the band, never a base.
    Before this, the summary exposed only `median_iv` while drawing bull/bear/conviction/Kelly
    from the medoid, which is the same cross-sample field mixing the medoid rule exists to stop.

    Returns:
        (medoid_scorecard, consensus_summary)
    """
    good = [r for r in runs if r.get("iv") and r.get("plausible") and not r.get("truncated")]
    if not good:
        return {}, {
            "median_iv": None, "median_bull_iv": None, "median_bear_iv": None,
            "iv_band_low": None, "iv_band_high": None, "spread_pct": None,
            "converged": False, "medoid_sample": None, "n_basis": 0,
            "median_conviction_score": None, "median_quality_moat": None,
            "median_kelly_fraction_pct": None, "asymmetric_payoff_skew": None,
            "reentry_tranches": None, "thesis_invalidation_triggers": [],
            "base_probability": None, "bull_probability": None, "bear_probability": None,
            "probabilities_defaulted": True,
            "base_cf_used": None, "base_cf_basis": None
        }

    ivs = [r["iv"] for r in good]
    spread = (max(ivs) / min(ivs) - 1) * 100 if len(ivs) >= 2 else None
    converged = bool(spread is not None and spread <= eff_tol)
    med_iv = st.median(ivs)

    # Validate each run's scorecard through the fiduciary validator
    valid_candidates = []
    for r in good:
        raw_card = r.get("scorecard") or {"base_iv": r.get("iv")}
        is_val, san_card, issues = validate_fiduciary_contract(raw_card, price)
        if is_val:
            valid_candidates.append({
                "sample": r.get("sample"),
                "iv": r.get("iv"),
                "card": san_card,
                "issues": issues,
                "moat": san_card.get("business_quality_moat")
            })

    if not valid_candidates:
        # Fallback if no full scorecard validated: synthesize baseline card from med_iv
        fb_card = {"base_iv": med_iv}
        _, san_fb, _ = validate_fiduciary_contract(fb_card, price)
        summary = {
            "median_iv": med_iv,
            "base_iv": san_fb.get("base_iv"),
            "median_bull_iv": None,
            "median_bear_iv": None,
            "iv_band_low": min(ivs),
            "iv_band_high": max(ivs),
            "spread_pct": round(spread, 1) if spread is not None else None,
            "converged": converged,
            "medoid_sample": good[0].get("sample"),
            "n_basis": len(good),
            "median_conviction_score": None,
            "median_quality_moat": None,
            "median_kelly_fraction_pct": None,
            "asymmetric_payoff_skew": None,
            "reentry_tranches": None,
            "thesis_invalidation_triggers": [],
            "base_probability": san_fb.get("base_probability"),
            "bull_probability": san_fb.get("bull_probability"),
            "bear_probability": san_fb.get("bear_probability"),
            "probabilities_defaulted": san_fb.get("probabilities_defaulted", True),
            "base_cf_used": san_fb.get("base_cf_used"),
            "base_cf_basis": san_fb.get("base_cf_basis")
        }
        return san_fb, summary

    moats = [c["moat"] for c in valid_candidates if c["moat"] is not None]
    med_moat = st.median(moats) if moats else 3.0

    # Distance function to find the Medoid sample closest to consensus
    def dist_to_center(c):
        d_iv = ((c["card"]["base_iv"] - med_iv) / med_iv) ** 2 if med_iv else 0.0
        d_moat = ((c["moat"] - med_moat) / med_moat) ** 2 if (c["moat"] and med_moat) else 0.0
        return d_iv + d_moat

    chosen = min(valid_candidates, key=dist_to_center)
    medoid_card = chosen["card"]

    summary = {
        "median_iv": med_iv,
        # CONTRACT BASE — the medoid's OWN base_iv, and the number that owns MoS and Kelly.
        # Added 2026-09-20 after GEV published "Kelly 8.98%" beside "MoS -1.7%": the medoid was
        # sample 2 (base $1,037.88, so its Kelly was legal) while `median_iv` was the three-sample
        # median ($934.54), and `depth_pipeline` computed MoS from the median but carried sample
        # 2's Kelly. RS2.txt line 352 defines MoS = (IV Base - Price) / IV Base with Kelly in the
        # same step, so both must read from ONE sample. `median_iv` remains the cross-sample
        # dispersion statistic and is NOT a base for sizing.
        "base_iv": medoid_card.get("base_iv"),
        "median_bull_iv": medoid_card.get("bull_iv"),
        "median_bear_iv": medoid_card.get("bear_iv"),
        "iv_band_low": min(ivs),
        "iv_band_high": max(ivs),
        "spread_pct": round(spread, 1) if spread is not None else None,
        "converged": converged,
        "medoid_sample": chosen["sample"],
        "n_basis": len(good),
        "median_conviction_score": medoid_card.get("conviction_score"),
        "median_quality_moat": medoid_card.get("business_quality_moat"),
        "median_kelly_fraction_pct": medoid_card.get("kelly_fraction_pct"),
        "asymmetric_payoff_skew": medoid_card.get("asymmetric_payoff_skew"),
        "reentry_tranches": medoid_card.get("reentry_tranches"),
        "thesis_invalidation_triggers": [medoid_card.get("thesis_invalidation_trigger")] if medoid_card.get("thesis_invalidation_trigger") else [],
        # Carried so depth_pipeline's CONTRACT_PASSTHROUGH can reach the validator with them -
        # its three probability entries were dead code while this summary omitted these keys -
        # and so a reader of consensus.json can see whether the probability-weighted edge test
        # was runnable. `probabilities_defaulted` is published for the same reason.
        "base_probability": medoid_card.get("base_probability"),
        "bull_probability": medoid_card.get("bull_probability"),
        "bear_probability": medoid_card.get("bear_probability"),
        "probabilities_defaulted": medoid_card.get("probabilities_defaulted"),
        "base_cf_used": medoid_card.get("base_cf_used"),
        "base_cf_basis": medoid_card.get("base_cf_basis")
    }
    return medoid_card, summary


OWNER_CF_TOL_PCT = 10.0        # a declaration within this of the figure it names is accepted

# Distinguishes "the caller supplied no trailing figure, go and load one" from "we hold none".
# A bare None cannot carry both meanings.
_UNSET = object()


def owner_cf_by_year(ticker):
    """{year: owner cash flow in $B} for every year where all three filed inputs are present.

    Empty when we hold nothing for the name. This feeds an annotation, so it must never raise:
    absence is not a defect.
    """
    import capability_test as cap
    try:
        hist = ((rs2_data.load_json(common.SD / "fundamentals_history.json") or {})
                .get("tickers", {}).get(str(ticker).upper(), {}) or {})
        out = {}
        for y, row in hist.items():
            if not (isinstance(row, dict) and str(y).isdigit()):
                continue
            v = cap.owner_cf(row.get("ocf"), row.get("capex"), row.get("sbc"))
            if v is not None:
                out[int(y)] = v / 1e9
        return out
    except Exception:
        return {}


def ttm_fcf_by_ticker(ticker):
    """Trailing twelve months OCF minus capex, in $B, or None when we hold no usable record.

    The trailing record carries OCF and capex but NO SBC (verified for GEV: its fields are
    capex, fcf, net_income, ocf, revenue). This figure therefore subtracts no stock compensation
    and is structurally higher than an owner cash flow - $12.438B against $3.453B for GEV.
    SECTION 5's SBC caveat already warns about exactly this reading; making the number checkable
    is what lets us SEE the analyst reach for it instead of only cautioning against it.
    """
    try:
        ttm = ((rs2_data.load_json(common.SD / "fundamentals_ttm.json") or {})
               .get("tickers", {}).get(str(ticker).upper(), {}) or {})
        f = ttm.get("fields") or {}
        ocf, capex = f.get("ocf"), f.get("capex")
        if ocf is None or capex is None:
            return None
        return (float(ocf) - float(capex)) / 1e9
    except Exception:
        return None


def owner_cf_basis_check(ticker, scorecard, years=None, ttm_fcf=_UNSET):
    """(note | None) — text when the declared base cash flow does not match the basis it names.

    ANNOTATION ONLY, in the same family as the other flags: it never changes direction, size, or
    whether a sample is usable (guard redesign 2026-08-24).

    Why this exists. The analyst was measured switching between readings of the same accounts
    without saying so — GEV, 2026-09-20, same dossier and same $951.04 price, one run near
    $12.4B and another near $5.0B. Declaring the basis turns an invisible disagreement into a
    checkable claim. `other` is the honest escape hatch and is deliberately NOT checked; every
    other basis in the list IS verified, `ttm_fcf` included, because the trailing reading is the
    one that actually overstated GEV.
    """
    sc = scorecard or {}
    claim = sc.get("base_cf_used")
    basis = str(sc.get("base_cf_basis") or "").strip().lower()
    if claim is None or not basis:
        return None
    if basis == "other":
        return None
    import capability_test as cap
    if basis not in cap.OWNER_CF_BASES:
        return (f"declared base cash flow basis '{basis}' is not one of "
                f"{', '.join(cap.OWNER_CF_BASES)}")
    try:
        claim = float(claim)
    except (TypeError, ValueError):
        return "declared base cash flow is not a number"
    if basis == "ttm_fcf":
        target = ttm_fcf_by_ticker(ticker) if ttm_fcf is _UNSET else ttm_fcf
        label = "trailing twelve months free cash flow (OCF minus capex)"
    else:
        if years is None:
            years = owner_cf_by_year(ticker)
        if not years:
            return None
        if basis == "latest_fy":
            latest = max(years)
            target, label = years[latest], f"the latest fiscal year (FY{latest})"
        else:
            target = sum(years.values()) / len(years)
            label = f"the multi-year average across {len(years)} years"
    if not target:
        return None
    if abs(claim - target) / abs(target) * 100.0 > OWNER_CF_TOL_PCT:
        return (f"declared base cash flow ${claim:,.2f}B as {label}, but that figure is "
                f"${target:,.2f}B")
    return None


def rescue_status(meta):
    """(stub_rejected, forced_report, budget_exhausted) for ONE sample, from a `chat_with_tools`
    meta dict.

    THREE markers. The distinction between the last two is the point, and an earlier version of
    this docstring got it wrong:

      * `stub_rejected` — the terminal turn was a tool-call envelope rather than a report, so the
        harness forced a memorandum turn at `think: "low"`, `num_predict` 32768.
      * `forced_report` — a turn carrying that same stub-retry marker (`analyst_tools.py:452`).
        This runs at `think: "low"`, so it is the marker that means the sample was reasoned at a
        DIFFERENT effort level from its siblings.
      * `budget_exhausted` — a turn produced because both tool budgets were reached
        (`analyst_tools.py:513`). That path forces the memorandum at the SAME `think` level, so it
        is a different PROVENANCE, not a reduced-effort one. The old docstring claimed
        `forced_report` covered "both tool budgets exhausted"; it does not. Reading only that key
        left a forced report publishing as though it had concluded naturally.

    Tolerates absent/None/malformed `turns`: the on-disk snapshots predate `turns` entirely, so
    absence is the normal case, not an error.
    """
    meta = meta or {}
    turns = meta.get("turns") or []
    return {
        "stub_rejected": bool(meta.get("stub_rejected")),
        "forced_report": any(bool(t.get("forced_report")) for t in turns if isinstance(t, dict)),
        "budget_exhausted": any(bool(t.get("budget_exhausted")) for t in turns
                                if isinstance(t, dict)),
    }


def run_progress(n_max, attempted, recorded, adaptive, broke_early):
    """Sample bookkeeping for consensus.json. Pure, so the derivation is testable.

    `early_stop` must describe WHAT THE LOOP DID, not what got recorded. The previous
    derivation - `adaptive and len(runs) == 2 and len(good) == 2` - cannot tell "the loop
    stopped at n=2 because the pair agreed" apart from "the loop ran 3 times and one sample
    raised before recording". Both leave len(runs) == 2, so a LOST sample was published as a
    legitimate early stop: judged against the tighter early bar, sized 'full', audited clean.

    `samples_attempted` is what makes the loss visible, because loss is
    `samples_run < samples_attempted`. Comparing against `samples_intended` instead would flag
    every real early stop as a loss - the plan is always 3 in adaptive mode even when the loop
    legitimately stops at 2.
    """
    attempted = int(attempted or 0)
    recorded = int(recorded or 0)
    return {
        "samples_intended": int(n_max or 0),
        "samples_attempted": attempted,
        "samples_run": recorded,
        "samples_lost": max(0, attempted - recorded),
        "early_stop": bool(adaptive and broke_early),
    }


def snapshot_research_brief(t, run_dir):
    """Copy research/{T}.md into `run_dir` (P1.7) and report its provenance:
    (asof ISO string or None, age_days or None, stale bool).

    `stale` is True when the brief is older than research_max_age_days — enforced HERE, where
    the brief is actually consumed (read into the pack), on every calling path (C4, Phase 1
    approval review). The age ceiling used to live only inside depth_pipeline.run_research's
    --force decision, which deep_research.fresh()'s own 7-day cache rule pre-empts (14 > 7, so
    it could almost never fire) — and depth_pipeline's --no-research path skips run_research
    entirely, consuming whatever brief happens to be on disk at ANY age. Never a silent read:
    the caller rides `stale` onto the verdict as a flag, same as pack_macro_degraded.

    Split out of main() so this is testable against a synthetic brief file without spawning the
    research/consensus subprocesses (mirrors depth_pipeline.stamp_and_route).
    """
    r_dir = rs2_data.CONFIG.get("out_research_dir") or "research"
    research_dir = Path(r_dir)
    if not research_dir.is_absolute():
        research_dir = HERE / research_dir
    research_file = research_dir / f"{t}.md"
    asof, age_days = None, None
    if research_file.exists():
        try:
            mtime = research_file.stat().st_mtime
            asof = datetime.fromtimestamp(mtime).isoformat()
            age_days = round((time.time() - mtime) / 86400, 2)
            import shutil
            shutil.copyfile(research_file, run_dir / "_research_brief.md")
        except Exception as e:
            print(f"  [consensus] WARN could not copy research brief: {e}", flush=True)
    max_age_days = float(rs2_data.CONFIG["research_max_age_days"])
    stale = bool(age_days is not None and age_days > max_age_days)
    if stale:
        print(f"  [consensus] WARN research brief is {age_days:.1f}d old "
              f"(> {max_age_days:.0f}d) — flagging stale_research_brief", flush=True)
    return asof, age_days, stale


def _load_evidence_store(store_dir):
    """(query_cache, url_cache) loaded from `store_dir`'s JSON files, or empty dicts when the
    store does not exist yet (its first sample). P4.0b: a battery shares ONE evidence store per
    name across every sample of a run, so sample k sees exactly what sample 1 saw for the same
    query/URL — `analyst_tools.search_web`/`fetch_page` already dedupe against whatever dict they
    are given; this just makes that dict persistent and shared instead of per-call and ephemeral.
    """
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    qc_path, uc_path = store_dir / "query_cache.json", store_dir / "url_cache.json"
    query_cache = json.loads(qc_path.read_text(encoding="utf-8")) if qc_path.exists() else {}
    url_cache = json.loads(uc_path.read_text(encoding="utf-8")) if uc_path.exists() else {}
    return query_cache, url_cache


def _save_evidence_store(store_dir, query_cache, url_cache):
    """Persist the (possibly grown) evidence-store dicts back to `store_dir`. Called after every
    sample, not only at the end, so a battery interrupted mid-run still leaves whatever evidence
    it already gathered on disk for the next attempt to reuse."""
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "query_cache.json").write_text(json.dumps(query_cache, indent=2), encoding="utf-8")
    (store_dir / "url_cache.json").write_text(json.dumps(url_cache, indent=2), encoding="utf-8")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "GOOG").upper()
    adaptive = "--samples" not in sys.argv
    n = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 3
    model = (sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv
             else "rs2-analyst-deep-mtp5")
    ctx = int(sys.argv[sys.argv.index("--ctx") + 1]) if "--ctx" in sys.argv else 81920
    # Reasoning effort. Default "high" = the template's xhigh = the model's MAXIMUM and its own
    # default; "medium" is the neutral baseline that injects no reasoning instruction. Exposed
    # 2026-08-23 so the medium-vs-xhigh cost/quality question can be measured rather than argued.
    # NAMED think_level, NOT think, and that matters: `think` is already the name of the
    # OUTPUT variable holding each sample's thinking text. Using it for the config value too
    # meant sample 2 passed sample 1's 124,693-char reasoning trace as the reasoning-effort
    # argument, and ollama rejected it instantly with HTTP 400. EXPE lost 2 of 3 samples to
    # this before it was caught. The bug was invisible while the value was hard-coded "high".
    think_level = sys.argv[sys.argv.index("--think") + 1] if "--think" in sys.argv else "high"
    draft_num_predict = int(sys.argv[sys.argv.index("--draft-num-predict") + 1]) if "--draft-num-predict" in sys.argv else None
    # ctx 81920 VERIFIED 2026-08-21 on rs2-analyst-deep: 22.2 GB resident, fully on GPU,
    # no CPU spill. Do not raise further without re-probing /api/ps for spill.

    # P4.0b — frozen-evidence dispersion battery options ------------------------------------
    # `--no-early-stop`: the battery needs FULL samples for dispersion, so the adaptive
    # 2-escalate break (below, `if adaptive and i == 2`) must never fire. Passing --samples
    # already sets adaptive False (unchanged, above); this makes that intent explicit and
    # covers the case where the caller wants a fixed default of 3 with no early stop too.
    no_early_stop = "--no-early-stop" in sys.argv
    adaptive = adaptive and not no_early_stop
    # `--out-dir`: the battery must never write into ab_reports/consensus (shared with
    # production runs) or any ledger — it gets its own isolated root instead of OUT.
    out_root = Path(sys.argv[sys.argv.index("--out-dir") + 1]) if "--out-dir" in sys.argv else OUT
    # `--pack-file`: reuse a saved _pack.md verbatim (see the pack-building block below).
    pack_file_arg = (Path(sys.argv[sys.argv.index("--pack-file") + 1])
                     if "--pack-file" in sys.argv else None)
    # `--evidence-store`: a persistent query/URL cache shared by every sample of this run.
    evidence_store_dir = (Path(sys.argv[sys.argv.index("--evidence-store") + 1])
                          if "--evidence-store" in sys.argv else None)
    # `--temperature`: overrides the Modelfile's `PARAMETER temperature 0.6`. Refused at
    # exactly 0 — Qwen's THINKING sampling profile (RS2-Analyst-Deep-MTP5.Modelfile's SAMPLING
    # note) warns explicitly against greedy decoding over a long reasoning trace.
    temperature = None
    if "--temperature" in sys.argv:
        try:
            temperature = float(sys.argv[sys.argv.index("--temperature") + 1])
        except (IndexError, ValueError) as e:
            print(f"[consensus] ::HARD FAIL:: --temperature could not be parsed ({e})", flush=True)
            raise
        if temperature == 0:
            print("[consensus] ::HARD FAIL:: --temperature 0 is refused — Qwen's thinking "
                  "sampling profile must not be greedy-decoded, never temperature 0.", flush=True)
            raise ValueError("temperature 0 is refused: Qwen thinking mode must not be greedy")

    fin = rs2_data.load_json(common.SD / "financials" / f"{t}.json") or {}
    price_override = None
    if "--price" in sys.argv:
        try:
            px_val = float(sys.argv[sys.argv.index("--price") + 1])
        except (IndexError, ValueError) as e:
            # C7 (Phase 1 approval review): this used to swallow a bad --price and silently
            # fall back to fin.get("Price") (the vendor quote). The caller (depth_pipeline)
            # passes its OWN live price_now.quote() here specifically to override the vendor
            # number — a silent fallback would value the ticker against a price nobody chose.
            print(f"[consensus] ::HARD FAIL:: --price could not be parsed ({e})", flush=True)
            raise
        asof_val = (sys.argv[sys.argv.index("--price-asof") + 1]
                    if "--price-asof" in sys.argv else None)
        price_override = {"price": px_val, "asof": asof_val}
    price = price_override["price"] if price_override else vb._num(fin.get("Price"))
    if pack_file_arg is not None:
        # P4.0b frozen-evidence battery: reuse a saved _pack.md VERBATIM instead of rebuilding,
        # so every sample of a battery run — and every arm compared against it — sees a
        # byte-identical pack. Whatever the frozen file already contains (TASK, and
        # RESEARCH_ADDENDUM if it was built with --tools in mind) rides through unchanged.
        pack = pack_file_arg.read_text(encoding="utf-8")
        pack_macro_degraded = False  # unknown: the pack was not rebuilt this run
        pack_source = f"frozen:{pack_file_arg}"
    else:
        pack_text = cap.build_pack(t, price_override=price_override)
        pack_macro_degraded = bool(getattr(pack_text, "macro_degraded", False)
                                   or getattr(cap, "LAST_PACK_MACRO_DEGRADED", False))
        pack = pack_text + "\n\n---\n\n" + cap.TASK
        pack_source = "fresh"
    pack_sha256 = hashlib.sha256(pack.encode("utf-8")).hexdigest()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = out_root / f"{t}_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    # Save the exact pack. Without it a consensus run is not re-auditable from its own directory
    # — found when three auditors had to reconstruct it independently to check the reports.
    (d / "_pack.md").write_text(pack, encoding="utf-8")

    # Snapshot research brief into run dir (P1.7); C4: age ceiling enforced where consumed.
    research_brief_asof, research_brief_age_days, research_brief_stale = \
        snapshot_research_brief(t, d)

    mode = (f"adaptive 2-escalate (early bar {EARLY_TOL_PCT:.0f}%, full {TOL_PCT:.0f}%)"
            if adaptive else f"{n} samples fixed")
    dnp_str = f" | draft_num_predict={draft_num_predict}" if draft_num_predict is not None else ""
    print(f"[consensus] {t} @ ${price} | model={model}{dnp_str} | {mode} -> {d}", flush=True)

    use_tools = "--tools" in sys.argv
    if use_tools:
        import analyst_tools
        if pack_file_arg is None:
            # The no-assumption rules only make sense when the model can actually look things up.
            pack += cap.RESEARCH_ADDENDUM
            (d / "_pack.md").write_text(pack, encoding="utf-8")
            pack_sha256 = hashlib.sha256(pack.encode("utf-8")).hexdigest()
            print("  [tools ENABLED] search-during-reasoning rules appended; every query and page "
                  "is snapshotted per sample", flush=True)
        else:
            # Frozen pack reused verbatim — a battery pack is built with --tools already in
            # mind, so the addendum (if needed) was baked in when it was built, not here.
            print("  [tools ENABLED] frozen pack reused verbatim; every query and page is "
                  "snapshotted per sample", flush=True)

    # P4.0b evidence store: one query/URL cache shared by every sample of THIS run. Loaded once
    # here so sample 1 already sees anything a prior (interrupted) attempt gathered; saved again
    # after every sample below so an interruption never loses what was already fetched.
    evidence_query_cache, evidence_url_cache = {}, {}
    if evidence_store_dir is not None:
        evidence_query_cache, evidence_url_cache = _load_evidence_store(evidence_store_dir)
        print(f"  [evidence-store] loaded {len(evidence_query_cache)} cached quer"
              f"{'y' if len(evidence_query_cache) == 1 else 'ies'}, "
              f"{len(evidence_url_cache)} cached page(s) from {evidence_store_dir}", flush=True)

    runs = []
    n_max = 3 if adaptive else n
    attempted = 0        # iterations ENTERED - the only honest denominator for sample loss
    broke_early = False  # set only by the adaptive early-stop branch below
    for i in range(1, n_max + 1):
        attempted = i
        t0 = time.time()
        resp, meta = {}, {}
        # P4.0b: hits/misses against the shared evidence store, accumulated across both the
        # initial chat_with_tools call and the empty-report retry (below) for THIS sample.
        sample_es_hits, sample_es_misses = 0, 0
        try:
            if use_tools:
                sd_i = d / f"sample{i}_research"
                rep, think, meta = analyst_tools.chat_with_tools(
                    model, pack, sd_i, think=think_level, ctx=ctx, num_predict=NUM_PREDICT,
                    seed=1000 + i, draft_num_predict=draft_num_predict, temperature=temperature,
                    query_cache=evidence_query_cache if evidence_store_dir is not None else None,
                    url_cache=evidence_url_cache if evidence_store_dir is not None else None)
                sample_es_hits += meta.get("evidence_hits") or 0
                sample_es_misses += meta.get("evidence_misses") or 0
                resp = {"done_reason": meta.get("done_reason"),
                        "eval_count": meta.get("generated_tokens"),
                        "eval_rate": meta.get("eval_rate"),
                        "eval_duration_s": meta.get("eval_duration_s")}
                msg = {}
            else:
                opts = {
                    "num_ctx": ctx,
                    "num_predict": NUM_PREDICT,
                    "repeat_penalty": 1.05,
                    "presence_penalty": 0.05,
                    "seed": 1000 + i
                }
                if draft_num_predict is not None:
                    opts["draft_num_predict"] = draft_num_predict
                if temperature is not None:
                    opts["temperature"] = temperature
                body = {"model": model, "stream": False, "think": think_level,
                        "messages": [{"role": "user", "content": pack}],
                        "options": opts}
                import urllib.request
                req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                             data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=7200) as r:
                    resp = json.loads(r.read().decode())
                msg = resp.get("message") or {}
                rep = msg.get("content") or ""
                think = msg.get("thinking") or ""
        except Exception as e:
            print(f"  sample {i}: FAILED {str(e)[:90]}", flush=True)
            continue
        # EMPTY-REPORT RETRY (found live on ANET s2, 2026-08-22): 118K chars of thinking,
        # done_reason=stop, ZERO report content - the model reasoned itself to a stop without
        # emitting the deliverable. One retry with a perturbed seed; a second empty is recorded
        # and the sample excluded as before (n_basis drops, verdict still emitted).
        if not (rep or "").strip() and not use_tools:
            print(f"  sample {i}: EMPTY report after {len(think):,}ch thinking - "
                  f"one retry, perturbed seed", flush=True)
            body["options"]["seed"] = 1000 + i + 50000
            req = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=7200) as r:
                resp = json.loads(r.read().decode())
            msg = resp.get("message") or {}
            rep = msg.get("content") or ""
            think = msg.get("thinking") or ""
        elif not (rep or "").strip() and use_tools:
            import analyst_tools as _at
            print(f"  sample {i}: EMPTY report after {len(think):,}ch thinking - "
                  f"one retry, perturbed seed", flush=True)
            rep, think, meta = _at.chat_with_tools(
                model, pack, d / f"sample{i}_research_retry", think=think_level, ctx=ctx,
                num_predict=NUM_PREDICT, seed=1000 + i + 50000, draft_num_predict=draft_num_predict,
                temperature=temperature,
                query_cache=evidence_query_cache if evidence_store_dir is not None else None,
                url_cache=evidence_url_cache if evidence_store_dir is not None else None)
            sample_es_hits += meta.get("evidence_hits") or 0
            sample_es_misses += meta.get("evidence_misses") or 0
            resp = {"done_reason": meta.get("done_reason"),
                    "eval_count": meta.get("generated_tokens"),
                    "eval_rate": meta.get("eval_rate"),
                    "eval_duration_s": meta.get("eval_duration_s")}
        (d / f"sample{i}.md").write_text(rep, encoding="utf-8")
        if think:
            (d / f"sample{i}_thinking.md").write_text(think, encoding="utf-8")
        truncated = resp.get("done_reason") == "length"

        # STATE-PRESERVING SESSION CONTINUATION (Problem D resolution):
        # If truncated mid-report (e.g. context wall in Sections 4-10) with substantial content,
        # do NOT discard the sample. Reclaim 40k+ tokens of headroom by feeding pack + partial report
        # as assistant turn and requesting immediate completion through Section 12.
        if truncated and len((rep or "").strip()) > 1500:
            print(f"  sample {i}: TRUNCATED mid-report at {len(rep):,}ch — triggering State-Preserving Continuation...", flush=True)
            rep_cont, think_cont, meta_cont = continue_report(
                model=model, pack=pack, partial_report=rep,
                ctx=ctx, timeout=1800, seed=1000 + i + 100,
                draft_num_predict=draft_num_predict, temperature=temperature)
            if rep_cont and rep_cont.strip():
                rep = rep.rstrip() + "\n\n" + rep_cont.strip()
                (d / f"sample{i}.md").write_text(rep, encoding="utf-8")
                if think_cont:
                    think = (think + "\n\n--- CONTINUATION THINKING ---\n\n" + think_cont) if think else think_cont
                    (d / f"sample{i}_thinking.md").write_text(think, encoding="utf-8")
                if meta_cont.get("done_reason") == "stop":
                    truncated = False
                    resp["done_reason"] = "stop"
                    resp["eval_count"] = (resp.get("eval_count") or 0) + (meta_cont.get("generated_tokens") or 0)
                    print(f"  sample {i}: Continuation SUCCESSFUL (rescued {len(rep_cont):,}ch, total {len(rep):,}ch, done_reason=stop)", flush=True)
        # EXACT token accounting from the server, not char estimates — this is what settles
        # where a truncated run actually spent its budget.
        p_tok, g_tok = resp.get("prompt_eval_count"), resp.get("eval_count")
        eval_rate = resp.get("eval_rate")
        eval_dur_s = resp.get("eval_duration_s")
        scorecard = extract_scorecard(rep, price)
        ivs = extract_iv(rep, price)
        iv = scorecard.get("base_iv") or (st.median(ivs) if ivs else None)
        ok, why, flags = plausibility(iv, price, t)
        # The declared cash-flow basis is CHECKED, not taken on trust - a self-reported value
        # nothing verifies is exactly the Task 2 defect. Annotation only: a flag and a reason.
        cf_note = owner_cf_basis_check(t, scorecard)
        if cf_note:
            flags = list(flags) + ["base_cf_basis_mismatch"]
            why = list(why) + [cf_note]
        if pack_macro_degraded and "macro_degraded" not in flags:
            flags = list(flags) + ["macro_degraded"]
        if research_brief_stale and "stale_research_brief" not in flags:
            flags = list(flags) + ["stale_research_brief"]
        # Carry the harness rescue status onto the sample. Without this the four-key copy out of
        # `meta` above drops it, and a band can mix a sample written at reduced reasoning effort
        # with normal siblings with no consumer able to tell.
        rescue = rescue_status(meta)
        # P4.0b: persist the evidence store after every sample (not only at the end) so an
        # interrupted battery run never loses evidence it already gathered.
        if evidence_store_dir is not None:
            _save_evidence_store(evidence_store_dir, evidence_query_cache, evidence_url_cache)
        runs.append({"sample": i, "iv": iv, "scorecard": scorecard, "all_iv_mentions": sorted(set(ivs))[:8],
                     "plausible": ok, "reasons": why, "flags": flags, "truncated": truncated,
                     "stub_rejected": rescue["stub_rejected"],
                     "forced_report": rescue["forced_report"],
                     "budget_exhausted": rescue["budget_exhausted"],
                     "done_reason": resp.get("done_reason"),
                     "prompt_tokens": p_tok, "generated_tokens": g_tok,
                     "eval_rate": eval_rate, "eval_duration_s": eval_dur_s,
                     "thinking_chars": len(think), "report_chars": len(rep),
                     "thinking_share_of_output": (round(len(think) / (len(think) + len(rep)), 3)
                                                  if (think or rep) else None),
                     "evidence_store_hits": sample_es_hits if evidence_store_dir is not None else None,
                     "evidence_store_misses": sample_es_misses if evidence_store_dir is not None else None,
                     "chars": len(rep), "secs": round(time.time() - t0)})
        rate_str = f" | {eval_rate} tok/s ({eval_dur_s}s)" if eval_rate else ""
        print(f"  sample {i}: IV ${iv if iv else '?'} | usable={ok}"
              + f" | gen {g_tok} tok (think {len(think):,}ch / report {len(rep):,}ch)"
              + rate_str
              + (f" ({'; '.join(why)})" if why else "")
              + (f" | flags: {', '.join(flags)}" if flags else "")
              + (" | TRUNCATED" if truncated else ""), flush=True)
        # ADAPTIVE EARLY STOP after sample 2: publish on two COMPLETE, PLAUSIBLE samples inside
        # the tighter bar. Every other outcome - spread beyond EARLY_TOL, an implausible or
        # truncated or unparseable sample - falls through and buys the 3rd opinion. The bar is
        # tighter than TOL_PCT on purpose; see EARLY_TOL_PCT.
        if adaptive and i == 2:
            g2 = [r for r in runs if r["iv"] and r["plausible"] and not r["truncated"]]
            if len(g2) == 2:
                sp2 = (max(r["iv"] for r in g2) / min(r["iv"] for r in g2) - 1) * 100
                if sp2 <= EARLY_TOL_PCT:
                    print(f"  [adaptive] 2 samples agree within {sp2:.1f}% "
                          f"(early bar {EARLY_TOL_PCT:.0f}%) — stopping, no 3rd sample",
                          flush=True)
                    broke_early = True
                    break
                print(f"  [adaptive] 2-sample spread {sp2:.1f}% > {EARLY_TOL_PCT:.0f}% — "
                      f"escalating to 3rd sample", flush=True)
            else:
                print(f"  [adaptive] only {len(g2)} usable of 2 — escalating to 3rd sample",
                      flush=True)

    good = [r for r in runs if r["iv"] and r["plausible"] and not r["truncated"]]
    ivs = [r["iv"] for r in good]
    spread = (max(ivs) / min(ivs) - 1) * 100 if len(ivs) >= 2 else None
    progress = run_progress(n_max, attempted, len(runs), adaptive, broke_early)
    early_stop = progress["early_stop"]
    # An early-stopped pair must meet the bar it stopped under; a 3-sample set (or a fixed-n
    # run) is judged at the standard tolerance.
    eff_tol = EARLY_TOL_PCT if early_stop else TOL_PCT
    converged = bool(spread is not None and spread <= eff_tol)
    med = st.median(ivs) if ivs else None

    # Medoid Consensus Aggregation (eliminates Frankenstein independent medians)
    medoid_card, scorecard_summary = select_medoid_scorecard(runs, price, eff_tol)
    med_conviction = scorecard_summary.get("median_conviction_score")
    med_quality = scorecard_summary.get("median_quality_moat")
    med_kelly = scorecard_summary.get("median_kelly_fraction_pct")
    med_bull = scorecard_summary.get("median_bull_iv")
    med_bear = scorecard_summary.get("median_bear_iv")
    med_skew = scorecard_summary.get("asymmetric_payoff_skew")

    verdict = ("CONVERGED" if converged and med else
               "NOT CONVERGED — runs disagree beyond tolerance" if med and spread is not None else
               f"NOT CONVERGED — only {len(good)} usable sample(s), spread undefined" if med else
               "NO USABLE SAMPLE — nothing parseable and complete")
    doc = {"ticker": t, "price": price, "model": model, "think": think_level,
           "draft_num_predict": draft_num_predict,
           "temperature": temperature,
           "pack_revision": cap.PACK_REVISION,
           "pack_source": pack_source, "pack_sha256": pack_sha256,
           "research_brief_asof": research_brief_asof,
           "research_brief_age_days": research_brief_age_days,
           "price_asof": price_override.get("asof") if price_override else None,
           "mode": ("adaptive" if adaptive else f"fixed_{n}"),
           "no_early_stop": no_early_stop,
           "evidence_store_dir": str(evidence_store_dir) if evidence_store_dir is not None else None,
           "samples_run": len(runs), "early_stop": early_stop,
           "samples_intended": progress["samples_intended"],
           "samples_attempted": progress["samples_attempted"],
           "samples_lost": progress["samples_lost"],
           "effective_tolerance_pct": eff_tol,
           "generated_at": datetime.now(timezone.utc).isoformat(),
           "runs": runs, "n_plausible": len(good),
           "median_iv": med, "spread_pct": round(spread, 1) if spread is not None else None,
           "tolerance_pct": TOL_PCT, "early_tolerance_pct": EARLY_TOL_PCT,
           "converged": converged, "verdict": verdict,
           "scorecard": scorecard_summary,
           "median_mos_pct": round((med / price - 1) * 100, 1) if med and price else None}
    (d / "consensus.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"\n[consensus] {verdict}")
    if med:
        print(f"  median IV ${med:,.2f} vs price ${price:,.2f} -> MoS {doc['median_mos_pct']:+.1f}%"
              + (f" | spread {spread:.1f}% (tolerance {TOL_PCT}%)" if spread is not None else ""))
        if med_conviction:
            print(f"  conviction: {med_conviction}/15 | quality: {med_quality}/5 | Kelly: {med_kelly}% | skew: {med_skew}")
    print(f"  -> {d/'consensus.json'}")


if __name__ == "__main__":

    main()
