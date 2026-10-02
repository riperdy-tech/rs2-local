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
import math
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
import llm_provider  # noqa: E402  (the one door every analyst-model call goes through)
common.enable_json_cache()
import capability_test as cap  # noqa: E402
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402
from fiduciary_gate import validate_fiduciary_contract  # noqa: E402
from research_brief_guard import check_research_brief  # noqa: E402
from pack_data_sanity import check_pack_data_sanity  # noqa: E402
import pack_facts  # noqa: E402
import contract_fill  # noqa: E402

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
BEAR_TOL_PCT = 40.0         # P4.7 — 2-sample early-stop ALSO requires the bear-IV spread inside
                            # this bar (base-IV spread alone missed GEV-shaped disagreement where
                            # the base cases were close but the downside cases were not).
BEAR_TOL_PCT_NOTE = ("initial value carried from PHASE_4_ANALYST.md P4.7, not yet re-derived "
                      "from the P4.0 dispersion battery's bear-IV spread distribution")
NUM_PREDICT = 65536         # output budget per sample. At the old ctx 65,536 the 49,152 cap was
                            # already the ctx wall (prompt ~16.4K), and one GOOG sample hit it -
                            # report cut mid-write, vote discarded. ctx raised to 98,304 on 2026-09-27, measured on the RTX 3090.

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


from financial_model_tool import _normalize_cash_flow_life  # noqa: E402  (S3 3.4 V1: moved there)
from financial_model_tool import _to_b  # noqa: E402  (the desk's own share-count conversion)


def _norm_fly(val):
    if val is None or type(val) is bool:
        return None
    try:
        f = float(val)
        if f.is_integer():
            return int(f)
    except (ValueError, TypeError):
        pass
    return val


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
        "base_cf_reason": None,
        "conviction_score": None,
        "business_quality_moat": None,
        "kelly_fraction_pct": None,
        "asymmetric_payoff_skew": None,
        "reentry_tranches": {"tranche_1_starter": None, "tranche_2_core": None},
        "thesis_invalidation_trigger": None,
        # P4.0a declared inputs (Section 12 contract)
        "coe_used": None,
        "coe_source": None,
        "coe_adjustment_reason": None,
        "valuation_frame": None,
        "terminal_method": None,
        "terminal_multiple_or_g": None,
        "fade_years": None,
        "stage1_growth_path": None,
        "guidance_deviation_reason": None,
        "cycle_evidence": None,
        "verdict_label": None,
        # P4.2 declared inputs (Section 12 contract, momentum mandate)
        "momentum_view": None,
        "entry_timing": None,
        "momentum_flip_condition": None,
        "momentum_break_rule": None,
        "invalidation_rules": None,
        # P4 E5b momentum basis
        "position_basis": None,
        "momentum_evidence": None,
        # Item 4: market-engagement and scenario keys
        "catalysts": None,
        "bull_below_price_reason": None,
        "bear_above_price_reason": None,
        # E12 (pack revision 8): shares, net debt, bull/bear deviation
        "shares_basis": None,
        "shares_reason": None,
        "net_debt_reason": None,
        "excess_cash_reason": None,         # revision 18: a different excess_cash than DEFAULTS' needs a dated reason
        "scenario_deviation_reason": None,
        # E13 (pack revision 9): terminal multiple and valuation frame
        "terminal_multiple_reason": None,   # revision 9 name; revision 10 asks for terminal_reason
        "terminal_reason": None,
        "interest_addback": None,
        "wacc_reason": None,
        # Revision 12: cash-flow life
        "cash_flow_life": None,
        "cash_flow_life_reason": None,
        "finite_life_years": None,
        # Harness-filled per sample from tool snapshot (not declared by model)
        "desk_calls": None,
        "desk_iv_match": None,
        "desk_reverse_neutral_cagr": None,
        "coe_minus_anchor": None,
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
            if card.get("verdict_label"):
                card["verdict_label"] = str(card["verdict_label"]).strip().lower()
            if card.get("coe_source"):
                card["coe_source"] = str(card["coe_source"]).strip().lower()
            if card.get("terminal_method"):
                card["terminal_method"] = str(card["terminal_method"]).strip().lower()
            if card.get("valuation_frame"):
                card["valuation_frame"] = str(card["valuation_frame"]).strip().lower()
            if card.get("momentum_view"):
                card["momentum_view"] = str(card["momentum_view"]).strip().lower()
            if card.get("entry_timing"):
                card["entry_timing"] = str(card["entry_timing"]).strip().lower()
            if card.get("position_basis"):
                card["position_basis"] = str(card["position_basis"]).strip().lower()
            if card.get("momentum_evidence"):
                card["momentum_evidence"] = str(card["momentum_evidence"]).strip()
            if card.get("base_cf_reason"):
                card["base_cf_reason"] = str(card["base_cf_reason"]).strip()
            if card.get("bull_below_price_reason"):
                card["bull_below_price_reason"] = str(card["bull_below_price_reason"]).strip()
            if card.get("bear_above_price_reason"):
                card["bear_above_price_reason"] = str(card["bear_above_price_reason"]).strip()
            if card.get("cash_flow_life") is not None:
                card["cash_flow_life"] = _normalize_cash_flow_life(card["cash_flow_life"])
            if card.get("cash_flow_life_reason") is not None:
                card["cash_flow_life_reason"] = str(card["cash_flow_life_reason"]).strip()
            if card.get("finite_life_years") is not None:
                try:
                    card["finite_life_years"] = int(card["finite_life_years"])
                except (ValueError, TypeError):
                    pass
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

    # Verdict label fallback
    vm = re.search(r"\bVERDICT(?:\s*LABEL)?\s*[:=≈]?\s*(undervalued|hold|overvalued|fair)\b", report, re.I)
    if vm and not card.get("verdict_label"):
        card["verdict_label"] = vm.group(1).lower()

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


def continue_report(model, pack, partial_report, ctx=98304, timeout=1800, seed=None,
                    draft_num_predict=None, temperature=None, think="high", num_batch=None):
    """Rescues a truncated memorandum by issuing a continuation turn to Ollama.
    Reclaims 40k+ tokens of headroom by feeding the pack + partial report as assistant turn."""
    cutoff_snippet = partial_report[-250:].strip()
    # S3 4.5 (2026-09-28): instruction 3's field list is now generated from FORM_FIELDS, so this
    # prompt and the TASK's contract cannot drift apart. Old literal (base_iv, bull_iv, bear_iv,
    # conviction_score, business_quality_moat, kelly_fraction_pct, asymmetric_payoff_skew,
    # reentry_tranches, thesis_invalidation_trigger) in git history at 3d02fbd.
    continuation_prompt = (
        "Your institutional memorandum was truncated at the context wall mid-sentence.\n\n"
        f"The cutoff point was:\n\"... {cutoff_snippet}\"\n\n"
        "CONTINUATION INSTRUCTIONS:\n"
        "1. Pick up IMMEDIATELY from that exact unfinished sentence and complete it seamlessly.\n"
        "2. Complete any remaining analysis sections (Valuation Triad, Balance Sheet Audit, Risks, Milestones).\n"
        "3. Conclude with SECTION 12 and the complete ```json:underwriting contract with these fields: "
        + ", ".join(cap.FORM_FIELDS) + ". The values, probabilities and Kelly size come from your desk runs; do not type them into the contract.\n\n"
        "Do NOT repeat the prior sections. Proceed directly with the continuation."
    )
    messages = [
        {"role": "user", "content": pack},
        {"role": "assistant", "content": partial_report},
        {"role": "user", "content": continuation_prompt}
    ]
    opts = {
        "num_ctx": ctx,
        **({"num_batch": num_batch} if num_batch else {}),
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
        "think": think,
        "messages": messages,
        "options": opts
    }
    try:
        resp = llm_provider.chat(body, timeout)
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
    good = [r for r in runs if counts_as_result(r)]
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
            "base_cf_used": None, "base_cf_basis": None,
            "coe_used": None, "coe_source": None, "coe_adjustment_reason": None,
            "valuation_frame": None, "terminal_method": None, "terminal_multiple_or_g": None,
            "fade_years": None, "stage1_growth_path": None, "guidance_deviation_reason": None,
            "cycle_evidence": None, "verdict_label": None,
            "momentum_view": None, "entry_timing": None, "momentum_flip_condition": None,
            "momentum_break_rule": None, "invalidation_rules": None,
            "position_basis": None, "momentum_evidence": None,
            "desk_calls": None, "desk_iv_match": None,
            "desk_reverse_neutral_cagr": None, "coe_minus_anchor": None,
            "desk_share_basis_matched": None,
            "catalysts": None, "bull_below_price_reason": None, "bear_above_price_reason": None,
            "code_fill_mode": None,
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
                "moat": san_card.get("business_quality_moat"),
                "flags": list(r.get("flags") or []),
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
            "base_cf_basis": san_fb.get("base_cf_basis"),
            "coe_used": san_fb.get("coe_used"),
            "coe_source": san_fb.get("coe_source"),
            "coe_adjustment_reason": san_fb.get("coe_adjustment_reason"),
            "valuation_frame": san_fb.get("valuation_frame"),
            "terminal_method": san_fb.get("terminal_method"),
            "terminal_multiple_or_g": san_fb.get("terminal_multiple_or_g"),
            "fade_years": san_fb.get("fade_years"),
            "stage1_growth_path": san_fb.get("stage1_growth_path"),
            "guidance_deviation_reason": san_fb.get("guidance_deviation_reason"),
            "cycle_evidence": san_fb.get("cycle_evidence"),
            "verdict_label": san_fb.get("verdict_label"),
            "momentum_view": san_fb.get("momentum_view"),
            "entry_timing": san_fb.get("entry_timing"),
            "momentum_flip_condition": san_fb.get("momentum_flip_condition"),
            "momentum_break_rule": san_fb.get("momentum_break_rule"),
            "invalidation_rules": san_fb.get("invalidation_rules"),
            "position_basis": san_fb.get("position_basis"),
            "momentum_evidence": san_fb.get("momentum_evidence"),
            "desk_calls": san_fb.get("desk_calls"),
            "desk_iv_match": san_fb.get("desk_iv_match"),
            "desk_reverse_neutral_cagr": san_fb.get("desk_reverse_neutral_cagr"),
            "coe_minus_anchor": san_fb.get("coe_minus_anchor"),
            "desk_share_basis_matched": san_fb.get("desk_share_basis_matched"),
            "catalysts": san_fb.get("catalysts"),
            "bull_below_price_reason": san_fb.get("bull_below_price_reason"),
            "bear_above_price_reason": san_fb.get("bear_above_price_reason"),
            "finite_life_years": san_fb.get("finite_life_years"),
            "cash_flow_life": san_fb.get("cash_flow_life"),
            "cash_flow_life_reason": san_fb.get("cash_flow_life_reason"),
            "code_fill_mode": None,
        }
        return san_fb, summary

    moats = [c["moat"] for c in valid_candidates if c["moat"] is not None]
    med_moat = st.median(moats) if moats else 3.0

    # Distance function to find the Medoid sample closest to consensus
    def dist_to_center(c):
        d_iv = ((c["card"]["base_iv"] - med_iv) / med_iv) ** 2 if med_iv else 0.0
        d_moat = ((c["moat"] - med_moat) / med_moat) ** 2 if (c["moat"] and med_moat) else 0.0
        return d_iv + d_moat

    # D6/P4.11: Exclude flagged samples (desk_not_used, iv_not_desk_backed) from medoid candidacy
    # when at least one clean sample exists.
    def _is_clean_candidate(c):
        c_flags = c.get("flags") or []
        if "desk_not_used" in c_flags or "iv_not_desk_backed" in c_flags:
            return False
        c_card = c.get("card") or {}
        if c_card.get("desk_calls") == 0:
            return False
        if c_card.get("desk_iv_match") is False:
            return False
        return True

    clean_candidates = [c for c in valid_candidates if _is_clean_candidate(c)]
    eligible_candidates = clean_candidates if clean_candidates else valid_candidates

    chosen = min(eligible_candidates, key=dist_to_center)
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
        "base_cf_basis": medoid_card.get("base_cf_basis"),
        "coe_used": medoid_card.get("coe_used"),
        "coe_source": medoid_card.get("coe_source"),
        "coe_adjustment_reason": medoid_card.get("coe_adjustment_reason"),
        "valuation_frame": medoid_card.get("valuation_frame"),
        "terminal_method": medoid_card.get("terminal_method"),
        "terminal_multiple_or_g": medoid_card.get("terminal_multiple_or_g"),
        "fade_years": medoid_card.get("fade_years"),
        "stage1_growth_path": medoid_card.get("stage1_growth_path"),
        # E10: carried whatever reason the model wrote (see consensus_ratios)
        "years12_ratio": medoid_card.get("years12_ratio"),
        "base_to_civ": medoid_card.get("base_to_civ"),
        "consensus_implied_value": medoid_card.get("consensus_implied_value"),
        # E12 stamps
        **{k: medoid_card.get(k) for k in ("bull_years12_ratio", "bear_years12_ratio", "base_shares_ratio",
                                           "bull_shares_ratio", "bear_shares_ratio", "desk_frame",
                                           "desk_net_debt", "shares_basis", "shares_reason",
                                           "net_debt_reason", "excess_cash_reason", "scenario_deviation_reason",
                                           "bull_bear_anchor",
                                           "terminal_multiple_reason", "interest_addback", "wacc_reason",
                                           "owner_earnings_source", "consensus_reference_status",
                                           "terminal_g_gap_bp", "terminal_reason", "base_window_gap",
                                           "finite_life_years", "cash_flow_life", "cash_flow_life_reason",
                                           # revision 17 (brief B 6): what the through-cycle package did to this
                                           # verdict, each added to its owner's schema so none is dropped
                                           "terminal_ronic", "terminal_ronic_gap_pts", "long_run_facts",
                                           "working_capital_deducted", "base_year_capped",
                                           "split_after_last_filing",
                                           "years12_held_by_desk", "desk_stamps")},
        "guidance_deviation_reason": medoid_card.get("guidance_deviation_reason"),
        "cycle_evidence": medoid_card.get("cycle_evidence"),
        "verdict_label": medoid_card.get("verdict_label"),
        "momentum_view": medoid_card.get("momentum_view"),
        "entry_timing": medoid_card.get("entry_timing"),
        "momentum_flip_condition": medoid_card.get("momentum_flip_condition"),
        "momentum_break_rule": medoid_card.get("momentum_break_rule"),
        "invalidation_rules": medoid_card.get("invalidation_rules"),
        "position_basis": medoid_card.get("position_basis"),
        "momentum_evidence": medoid_card.get("momentum_evidence"),
        "desk_calls": medoid_card.get("desk_calls"),
        "desk_iv_match": medoid_card.get("desk_iv_match"),
        "desk_reverse_neutral_cagr": medoid_card.get("desk_reverse_neutral_cagr"),
        "coe_minus_anchor": medoid_card.get("coe_minus_anchor"),
        "desk_share_basis_matched": medoid_card.get("desk_share_basis_matched"),
        "catalysts": medoid_card.get("catalysts"),
        "bull_below_price_reason": medoid_card.get("bull_below_price_reason"),
        "bear_above_price_reason": medoid_card.get("bear_above_price_reason"),
        "code_fill_mode": (medoid_card.get("code_fill") or {}).get("mode"),
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
    if basis in ("other", "owner_earnings_default"):
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

    From 2026-09-27 a forced report runs at the configured think level, so `forced_report` alone
    no longer means reduced effort; `reduced_thinking` does.

    Tolerates absent/None/malformed `turns`: the on-disk snapshots predate `turns` entirely, so
    absence is the normal case, not an error.
    """
    meta = meta or {}
    turns = [t for t in (meta.get("turns") or []) if isinstance(t, dict)]
    stub_rejected = bool(meta.get("stub_rejected"))
    forced_report = any(bool(t.get("forced_report")) for t in turns)
    budget_exhausted = any(bool(t.get("budget_exhausted")) for t in turns)
    desk_recovery_used = any(bool(t.get("desk_recovery")) for t in turns)
    window_retry_used = any(bool(t.get("window_retry")) for t in turns)
    if any("think" in t for t in turns):
        reduced_thinking = any("think" in t and t["think"] != meta.get("think_configured") for t in turns)
    else:
        reduced_thinking = bool(stub_rejected or forced_report or desk_recovery_used)
    return {
        "stub_rejected": stub_rejected,
        "forced_report": forced_report,
        "budget_exhausted": budget_exhausted,
        "desk_recovery_used": desk_recovery_used,
        "window_retry_used": window_retry_used,
        "reduced_thinking": reduced_thinking,
        "failure": meta.get("failure"),
        # revision 17, brief C8: the desk continuation record (None when it did not fire)
        "continuation_for_desk": meta.get("continuation_for_desk"),
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


def resolve_anchor_coe(ticker=None):
    """Resolve anchor CoE for a ticker as a decimal fraction (e.g. 0.0878)."""
    try:
        rf, _ = rs2_data.anchor_risk_free_rate()
        erp, _ = rs2_data.anchor_mature_erp()
        if rf is not None and erp is not None:
            loading = 1.0
            if ticker:
                sec, _ = rs2_data.sector_lookup(ticker)
                if sec:
                    l, _ = rs2_data.anchor_sector_loading(sec)
                    if l is not None:
                        loading = l
            return float(rf) + float(loading) * float(erp)
        level_pct, _ = rs2_data.anchor_level_cost_of_equity_pct()
        if level_pct is not None:
            return float(level_pct) / 100.0
    except Exception:
        pass
    return None


def check_base_cf_default_reason(scorecard: dict | None) -> list[str]:
    """Flag base_cf_off_default_without_reason when base_cf_basis is not owner_earnings_default and reason is empty."""
    flags = []
    sc = scorecard or {}
    b_basis = sc.get("base_cf_basis")
    b_reason = sc.get("base_cf_reason")
    if b_basis is not None and str(b_basis).strip() != "":
        if str(b_basis).strip().lower() != "owner_earnings_default":
            if b_reason is None or str(b_reason).strip() == "" or str(b_reason).strip().lower() in ("null", "none"):
                flags.append("base_cf_off_default_without_reason")
    return flags


def _pack_levels(pack_text):
    return pack_facts.from_text(pack_text)["levels"]


def _pack_window(pack_text):
    return pack_facts.from_text(pack_text)["base_window"]


def _year2_flow(base_cf, path):
    """base_cf ($B) grown two years along path, or None."""
    try:
        return float(base_cf) * (1 + float(path[0])) * (1 + float(path[1]))
    except (TypeError, ValueError, IndexError):
        return None


def _pack_reference(pack_text):
    """(the reference in force, the p90). Revision 18: a value printed outside the street-target fence is annotation only, so
    it is not returned here (its status is in the facts)."""
    import consensus_reference
    f = pack_facts.from_text(pack_text)
    civ = f["consensus_implied_value"] if consensus_reference.reference_in_force(f["reference_status"]) else None
    return civ, f["years35_p90"]


def next_fy_revenue_growth(pack_text: str | None = None) -> float | None:
    return pack_facts.from_text(pack_text)["next_fy_revenue_growth"]


def consensus_ratios(scorecard, enrich_data=None, pack_text=None, facts=None):
    """E10 ratios stamped on every sample WHATEVER reason the model wrote (Fable check,
    2026-09-24: a model that always fills guidance_deviation_reason would otherwise hide how far
    its base sits from consensus):
    - years12_ratio: (1+g1)(1+g2) / ((1+c1)(1+c2)) on consensus EPS growth;
    - base_to_civ: base IV / the pack's CONSENSUS-IMPLIED VALUE.
    Each is None when it cannot be computed."""
    import consensus_reference
    if facts is None:
        facts = pack_facts.from_text(pack_text)
    sc = scorecard or {}
    # revision 17: the fiscal-year reference and level only (the window no longer changes the arithmetic;
    # the BASE WINDOW CHECK's gap stays as information)
    civ = facts.get("consensus_implied_value")
    # revision 18 (brief 1.5): the levels are a reference's; outside the street-target fence they are a level check only
    lv2 = ((facts.get("levels") or {}).get("year2")
           if consensus_reference.reference_in_force(facts.get("reference_status")) else None)
    win = facts.get("base_window") or {}
    out = {"years12_ratio": None, "base_to_civ": None, "consensus_implied_value": civ,
           "base_window_gap": win.get("gap")}
    path = sc.get("stage1_growth_path") or []
    c1, c2, _ = consensus_reference.consensus_earnings_growth((enrich_data or {}).get("estimates"))
    y2 = _year2_flow(sc.get("base_cf_used"), path)
    try:
        if lv2 and y2 is not None:
            # E18: Base year-2 cash flow against the pack's fiscal-year year-2 level (revision 17: the
            # window choice is gone), whatever base was declared
            out["years12_ratio"] = round(y2 / lv2, 3)
        elif c1 is not None and len(path) >= 2:
            out["years12_ratio"] = round((1 + float(path[0])) * (1 + float(path[1]))
                                         / ((1 + c1) * (1 + c2)), 3)
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    try:
        if civ and sc.get("base_iv") is not None:
            out["base_to_civ"] = round(float(sc["base_iv"]) / civ, 3)
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return out


def _num_b(v):
    """A dollar or share figure in billions (the desk takes billions; raw counts are converted)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 1e9 if abs(x) > 1e6 else x


def _pack_shares_b(pack_text):
    sh = pack_facts.from_text(pack_text)["shares_outstanding"]
    return _num_b(sh) if sh is not None else None


def _pack_net_debt_b(pack_text):
    return pack_facts.from_text(pack_text)["net_debt_b"]


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _json_safe(x):
    """A verdict is published as JSON the site parses, and JSON has no infinity: a return on negative
    tangible equity (+inf, revision 17's long_run facts) is written "+inf" / "-inf"."""
    if isinstance(x, float) and math.isinf(x):
        return "+inf" if x > 0 else "-inf"
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    return x


def _pack_terminal_g(pack_text):
    return pack_facts.from_text(pack_text)["terminal_g_default"]


def _pack_interest_expense_b(pack_text):
    return pack_facts.from_text(pack_text)["interest_expense_latest_b"]


def _pack_reference_status(pack_text):
    return pack_facts.from_text(pack_text)["reference_status"]


def _pack_owner_earnings_source(pack_text):
    return pack_facts.from_text(pack_text)["owner_earnings_source"]


def _desk_terminal(d):
    """Revision 17: what the desk applied at a published value's terminal: the growth, the rate, the return
    on new investment (a number, or "unlimited"), the working capital deducted and the desk's own stamps."""
    return {"terminal_g": d.get("terminal_g"), "rate": d.get("discount_rate_applied"),
            "terminal_ronic": d.get("terminal_ronic"),
            "working_capital_deducted": d.get("working_capital_deducted"),
            "stamps": list(d.get("stamps") or [])}


def _desk_scenario_inputs(calls, target_iv, role=None):
    """Inputs behind a published value: the latest desk scenario (or plain DCF) whose per-share
    value is within 1% of target_iv, with the call's top-level inputs filled in. With `role`
    ("base"/"bull"/"bear"), a scenario of that name is preferred, so a bull and a base with the
    same value are not confused."""
    try:
        tgt = float(target_iv)
    except (TypeError, ValueError):
        return None

    def close(v):
        try:
            return float(v) > 0 and abs(float(v) - tgt) / float(v) <= 0.010001
        except (TypeError, ValueError):
            return False

    for c in reversed([c for c in (calls or []) if c.get("tool") == "run_financial_model"]):
        params = c.get("params") or {}
        res = c.get("result") if isinstance(c.get("result"), dict) else c
        top = {k: params.get(k) for k in ("explicit_growth", "growth_rates", "shares_diluted", "net_debt",
                                          "valuation_frame", "discount_rate", "wacc", "base_cf",
                                          "terminal_ronic", "terminal_g", "finite_life_years")}
        scs = res.get("scenario_dcfs") or res.get("scenarios") or []
        scs = scs if isinstance(scs, list) else []
        if role:
            scs = sorted(scs, key=lambda x: 0 if isinstance(x, dict)
                         and str(x.get("name") or "").lower().startswith(role) else 1)
        for sc in scs:
            if not isinstance(sc, dict):
                continue
            d = sc.get("dcf") or {}
            if any(close(x) for x in (d.get("per_share_iv"), d.get("per_share_iv_gordon"), sc.get("iv"))):
                p_sc = next((s for s in (params.get("scenarios") or [])
                             if isinstance(s, dict) and s.get("name") == sc.get("name")), {})
                out = dict(top)
                out.update({k: v for k, v in p_sc.items() if v is not None})
                # The growth the desk actually applied to THIS scenario. Scenarios pass it as
                # growth_rates while the top level's explicit_growth is the base path, so a merge
                # alone reported the base path for bull and bear (dry run on AMD, 2026-09-25).
                applied = d.get("explicit_growth") or p_sc.get("explicit_growth") or p_sc.get("growth_rates")
                if applied:
                    out["explicit_growth"] = applied
                if d.get("finite_life_years") is not None:
                    out["finite_life_years"] = d.get("finite_life_years")
                out["name"] = sc.get("name")
                out["_desk"] = _desk_terminal(d)
                return out
        d = res.get("dcf_model") or {}
        if isinstance(d, dict) and any(close(d.get(k)) for k in ("per_share_iv", "per_share_iv_gordon")):
            out = dict(top)
            if d.get("explicit_growth"):
                out["explicit_growth"] = d["explicit_growth"]
            if d.get("finite_life_years") is not None:
                out["finite_life_years"] = d.get("finite_life_years")
            out["_desk"] = _desk_terminal(d)
            return out
    return None


def scenario_checks(snapshot_dir, scorecard, enrich_data=None, pack_text=None, price=None, facts=None):
    """E12 per-sample checks and stamps: the share count and net debt behind each published
    scenario, and bull/bear years 1-2 against the consensus EPS high/low path. Returns
    (flags, stamps)."""
    import consensus_reference
    if facts is None:
        facts = pack_facts.from_text(pack_text)
    sc = scorecard or {}
    calls = []
    try:
        if snapshot_dir:
            p = Path(snapshot_dir)
            if p.is_dir():
                p = p / "_research_snapshot.json"
            if p.exists():
                calls = json.loads(p.read_text(encoding="utf-8")).get("calls") or []
    except Exception:
        calls = []
    stamps = {"bull_years12_ratio": None, "bear_years12_ratio": None, "base_shares_ratio": None,
              "bull_shares_ratio": None, "bear_shares_ratio": None, "desk_frame": None, "desk_net_debt": None,
              "bull_bear_anchor": None,
              "owner_earnings_source": facts.get("owner_earnings_source"),
              "terminal_g_gap_bp": None,
              "consensus_reference_status": facts.get("reference_status"),
              "finite_life_years": None,
              # revision 17 (brief B 6): stamped on every verdict whether or not a desk call is found
              "terminal_ronic": None, "terminal_ronic_gap_pts": None,
              "long_run_facts": _json_safe(facts.get("long_run")) or None,
              "working_capital_deducted": None,
              "base_year_capped": True if facts.get("base_year_cap") else None,
              # revision 17 (brief C4): the factor a split after the last filing put on the filed share count
              "split_after_last_filing": facts.get("split_after_last_filing"),
              "years12_held_by_desk": None, "desk_stamps": None}
    flags = []
    g_anchor = facts.get("terminal_g_default")
    # S3 5.11: the share-count default is the pack's count when the facts carry one (revision 15);
    # SECTION 2's count otherwise. The desk's R1 uses the same reference, so this safety net and the
    # desk cannot disagree about which count is "the pack's".
    _sh_ref = facts.get("shares_default")
    if not (isinstance(_sh_ref, (int, float)) and _sh_ref > 0):
        _sh_ref = facts.get("shares_outstanding")
    pack_sh = _num_b(_sh_ref)
    est = (enrich_data or {}).get("estimates") or {}
    e0, e1 = (est.get("0y") or {}).get("eps") or {}, (est.get("+1y") or {}).get("eps") or {}
    prior = e0.get("year_ago")
    cum = {"bull": e1.get("high"), "bear": e1.get("low")}
    # Fable pre-(b) F1: one or two analysts give no range (LAMR, LIND: high = low = average)
    if (e1.get("analysts") or 0) < 3 or e1.get("high") == e1.get("low"):
        cum = {"bull": None, "bear": None}
        stamps["bull_bear_anchor"] = f"no consensus range ({e1.get('analysts') or 0} analysts)"
    else:
        stamps["bull_bear_anchor"] = "consensus high/low"
    lv = (facts.get("levels") or {}) if consensus_reference.reference_in_force(facts.get("reference_status")) else {}
    for role in ("base", "bull", "bear"):
        inp = _desk_scenario_inputs(calls, sc.get(f"{role}_iv"), role=role)
        if not inp:
            continue
        g = inp.get("explicit_growth") or inp.get("growth_rates")
        y2 = _year2_flow(_num_b(inp.get("base_cf")), g) if isinstance(g, list) else None
        if role != "base" and lv.get(f"{role}2") and y2 is not None:
            # E18: the scenario's year-2 cash flow against the pack's Bull/Bear year-2 level
            stamps[f"{role}_years12_ratio"] = round(y2 / lv[f"{role}2"], 3)
        elif role != "base" and not lv.get(f"{role}2") and isinstance(g, list) and len(g) >= 2 \
                and isinstance(prior, (int, float)) \
                and prior > 0 and isinstance(cum[role], (int, float)) and cum[role] > 0:
            try:
                stamps[f"{role}_years12_ratio"] = round((1 + float(g[0])) * (1 + float(g[1]))
                                                        / (cum[role] / prior), 3)
            except (TypeError, ValueError):
                pass
        sh = _num_b(inp.get("shares_diluted"))
        if pack_sh and sh:
            stamps[f"{role}_shares_ratio"] = round(sh / pack_sh, 3)
        if role == "base":
            stamps["desk_frame"] = inp.get("valuation_frame")
            stamps["desk_net_debt"] = _num_b(inp.get("net_debt"))
            if inp.get("finite_life_years") is not None:
                try:
                    stamps["finite_life_years"] = int(inp["finite_life_years"])
                except (ValueError, TypeError):
                    pass
        dt = inp.get("_desk") or {}
        if role == "base" and g_anchor is not None and _fnum(dt.get("terminal_g")) is not None:
            # revision 10: terminal_g itself is pinned to the anchor (AU (b) s1 cut it to 2.5%)
            stamps["terminal_g_gap_bp"] = round((_fnum(dt["terminal_g"]) - g_anchor) * 10000)
        if role == "base":
            # revision 17: the terminal return on new investment the desk applied to the Base, against the
            # pack's default (a value or "unlimited"); the working capital and the desk's own stamps
            applied = dt.get("terminal_ronic")
            applied_f = math.inf if applied == "unlimited" else _fnum(applied)
            stamps["terminal_ronic"] = applied
            default_ronic = facts.get("terminal_ronic")
            if applied_f is not None and default_ronic is not None:
                stamps["terminal_ronic_gap_pts"] = (None if applied_f == default_ronic
                                                    else round(abs(applied_f - default_ronic) * 100.0, 2)
                                                    if not math.isinf(applied_f - default_ronic) else "unlimited")
            stamps["working_capital_deducted"] = dt.get("working_capital_deducted")
            stamps["desk_stamps"] = list(dt.get("stamps") or [])
            stamps["years12_held_by_desk"] = "years12_held_by_desk" in stamps["desk_stamps"]

    if stamps["finite_life_years"] is None and sc.get("finite_life_years") is not None:
        try:
            stamps["finite_life_years"] = int(sc["finite_life_years"])
        except (ValueError, TypeError):
            pass

    def _has(field):
        v = str(sc.get(field) or "").strip()
        return bool(v) and v.lower() not in ("null", "none")

    terminal_reason = _has("terminal_reason") or _has("terminal_multiple_reason")
    tg = stamps["terminal_g_gap_bp"]
    if tg is not None and abs(tg) > 50 and not terminal_reason:
        flags.append("terminal_g_off_anchor_without_reason")
    # revision 17: the Base's terminal return on new investment more than 2 points from the pack's default
    tr_gap = stamps["terminal_ronic_gap_pts"]
    if tr_gap is not None and (tr_gap == "unlimited" or tr_gap > 2.0) and not terminal_reason:
        flags.append("terminal_ronic_off_default_without_reason")
    # E13 (f): the equity frame is the default; a firm frame needs a pre-interest flow and a WACC build
    if stamps["desk_frame"] == "firm":
        addback = _num_b(sc.get("interest_addback"))
        if not addback or addback <= 0:
            flags.append("firm_frame_on_equity_flow")
        else:
            filed = facts.get("interest_expense_latest_b")
            if filed is not None and addback > filed * 1.01:
                flags.append("interest_addback_above_filed")
        if not _has("wacc_reason"):
            flags.append("firm_frame_without_wacc_reason")

    ratios = [stamps[f"{r}_shares_ratio"] for r in ("base", "bull", "bear") if stamps[f"{r}_shares_ratio"]]
    if any(abs(r - 1) > 0.010001 for r in ratios) and not _has("shares_reason"):   # more than 1%
        flags.append("shares_off_pack_without_reason")
    # Contingent shares added to a Bear whose premise is that they do not vest. The ratio is taken
    # against pack_sh above, which is the share-count default (S3 5.11) when the facts carry one: a
    # diluted default is not contingent dilution, a warrant added to every scenario still is (AMD s3).
    if (stamps["bear_shares_ratio"] or 0) > 1.01:
        flags.append("dilution_in_bear")
    nd_default = facts.get("net_debt_b")
    if stamps["desk_frame"] == "firm" and nd_default is not None and stamps["desk_net_debt"] is not None \
            and not _has("net_debt_reason") \
            and abs(stamps["desk_net_debt"] - nd_default) > max(0.1, 0.05 * abs(nd_default)):
        flags.append("net_debt_off_default_without_reason")
    # Revision 12 (A1): cash_flow_life_missing and finite_life_mismatch
    cfl = sc.get("cash_flow_life")
    cfl_norm = _normalize_cash_flow_life(cfl)
    cfl_valid = (cfl_norm == "perpetual") or (isinstance(cfl_norm, int) and type(cfl_norm) is not bool and 1 <= cfl_norm <= 60)
    if not cfl_valid or not _has("cash_flow_life_reason"):
        flags.append("cash_flow_life_missing")

    # the last COMPLETED desk run: a refused call (budget exhausted, validation error) keeps whatever the model sent
    model_calls = [c for c in (calls or []) if isinstance(c, dict) and c.get("tool") == "run_financial_model"
                   and not c.get("error") and not c.get("validation_error")]
    if model_calls:
        last_c = model_calls[-1]
        p = last_c.get("params") or {}
        r = last_c.get("result") if isinstance(last_c.get("result"), dict) else last_c
        p_scs = p.get("scenarios") if isinstance(p.get("scenarios"), list) else []
        r_scs = r.get("scenario_dcfs") or last_c.get("scenario_dcfs") or []
        r_scs = r_scs if isinstance(r_scs, list) else []
        is_multi = len(p_scs) > 1 or len(r_scs) > 1

        if is_multi:
            for role in ("base", "bull", "bear"):
                s_p = next((s for s in p_scs if isinstance(s, dict) and str(s.get("name") or "").strip().lower().startswith(role)), None)
                s_r = next((s for s in r_scs if isinstance(s, dict) and str(s.get("name") or "").strip().lower().startswith(role)), None)
                fly = None
                if s_p and s_p.get("finite_life_years") is not None:
                    fly = s_p.get("finite_life_years")
                elif s_r:
                    dcf = s_r.get("dcf") if isinstance(s_r.get("dcf"), dict) else {}
                    if dcf.get("finite_life_years") is not None:
                        fly = dcf.get("finite_life_years")
                    elif s_r.get("finite_life_years") is not None:
                        fly = s_r.get("finite_life_years")
                if fly is None and p.get("finite_life_years") is not None and (s_p or s_r):
                    fly = p.get("finite_life_years")

                fly_norm = _norm_fly(fly)
                if cfl_norm == "perpetual":
                    if fly_norm is not None:
                        flags.append("finite_life_mismatch")
                        break
                elif isinstance(cfl_norm, int) and type(cfl_norm) is not bool and 1 <= cfl_norm <= 60:
                    if fly_norm != cfl_norm:
                        flags.append("finite_life_mismatch")
                        break
        else:
            single_fly = None
            if p_scs and len(p_scs) == 1 and isinstance(p_scs[0], dict):
                single_fly = p_scs[0].get("finite_life_years")
            elif r_scs and len(r_scs) == 1 and isinstance(r_scs[0], dict):
                dcf = r_scs[0].get("dcf") if isinstance(r_scs[0].get("dcf"), dict) else {}
                single_fly = dcf.get("finite_life_years") or r_scs[0].get("finite_life_years")
            if single_fly is None and p.get("finite_life_years") is not None:
                single_fly = p.get("finite_life_years")
            if single_fly is None:
                dcf_m = r.get("dcf_model") or last_c.get("dcf_model") or {}
                if isinstance(dcf_m, dict):
                    single_fly = dcf_m.get("finite_life_years")
            if single_fly is None:
                single_fly = r.get("finite_life_years")

            single_fly_norm = _norm_fly(single_fly)
            if cfl_norm == "perpetual":
                if single_fly_norm is not None:
                    flags.append("finite_life_mismatch")
            elif isinstance(cfl_norm, int) and type(cfl_norm) is not bool and 1 <= cfl_norm <= 60:
                if single_fly_norm != cfl_norm:
                    flags.append("finite_life_mismatch")
    return flags, stamps


def check_sample_harness_rules(
    scorecard, price, desk_info=None, enrich_data=None, momentum_state=None, pack_text=None, facts=None
):
    """Evaluates Item 4 harness checks per sample:
    - scenario_order_violation: implausible if not (bear_iv <= base_iv <= bull_iv) with all 3 present
    - scenario_not_desk_backed:bull / :bear: flag if IV not within 1% of any desk per-share output
    - bull_below_price_without_reason: flag if bull_iv < price and bull_below_price_reason is empty
    - bear_above_price_without_reason: flag if bear_iv > price and bear_above_price_reason is empty
    - bull_below_street_low_without_reason: flag if bull_iv < analyst_target_low and bull_below_price_reason is empty
    - catalysts_missing: flag if catalysts empty/None and (|mom_1m| >= 0.10 or |mom_6m| >= 0.25)
    - years12_off_consensus_earnings (E10): Base years 1-2 cash-flow growth more than a quarter
      away from consensus EPS growth, (1+g1)(1+g2) vs (1+c1)(1+c2), without guidance_deviation_reason
    - base_far_from_consensus_implied (E10): base IV outside 0.75x-1.33x of the pack's
      CONSENSUS-IMPLIED VALUE without guidance_deviation_reason
    - years35_above_base_rate_p90 (E10, information): years 3-5 average growth above the pack's
      conditional (else size-bucket) p90
    - years35_above_revenue_cap_without_reason: any of Base years 3-5 growth exceeds next-FY consensus
      revenue growth by more than 0.005 and guidance_deviation_reason is empty (review J6, 2026-09-27:
      LAMR's evidence-backed departures above the cap must not read as violations)

    Returns:
        (is_implausible, [reasons], [flags])
    """
    flags = []
    reasons = []
    implausible = False
    if facts is None:
        facts = pack_facts.from_text(pack_text)

    sc = scorecard or {}
    base_iv = sc.get("base_iv")
    bull_iv = sc.get("bull_iv")
    bear_iv = sc.get("bear_iv")

    # 1. scenario_order_violation when not (bear_iv <= base_iv <= bull_iv) with all three present
    if base_iv is not None and bull_iv is not None and bear_iv is not None:
        try:
            b_iv = float(base_iv)
            u_iv = float(bull_iv)
            d_iv = float(bear_iv)
            if not (d_iv <= b_iv <= u_iv):
                implausible = True
                flags.append("scenario_order_violation")
                reasons.append("scenarios out of order (bear <= base <= bull required)")
        except (ValueError, TypeError):
            pass

    # 2. scenario_not_desk_backed:bull / :bear
    desk_ivs = (desk_info or {}).get("desk_per_share_ivs") or []

    def _matches_any_desk(target):
        if target is None:
            return True
        try:
            t_val = float(target)
            if t_val <= 0:
                return False
            for d_val in desk_ivs:
                if d_val > 0 and (abs(t_val - d_val) / d_val) <= 0.010001:
                    return True
            return False
        except (ValueError, TypeError):
            return False

    if bull_iv is not None and not _matches_any_desk(bull_iv):
        flags.append("scenario_not_desk_backed:bull")
    if bear_iv is not None and not _matches_any_desk(bear_iv):
        flags.append("scenario_not_desk_backed:bear")

    # 3. bull_below_price_without_reason & bear_above_price_without_reason
    bull_reason = str(sc.get("bull_below_price_reason") or "").strip()
    if bull_reason.lower() in ("null", "none"):
        bull_reason = ""
    bear_reason = str(sc.get("bear_above_price_reason") or "").strip()
    if bear_reason.lower() in ("null", "none"):
        bear_reason = ""

    if bull_iv is not None and price is not None:
        try:
            if float(bull_iv) < float(price) and not bull_reason:
                flags.append("bull_below_price_without_reason")
        except (ValueError, TypeError):
            pass

    if bear_iv is not None and price is not None:
        try:
            if float(bear_iv) > float(price) and not bear_reason:
                flags.append("bear_above_price_without_reason")
        except (ValueError, TypeError):
            pass

    # 4. bull_below_street_low_without_reason
    en = enrich_data or {}
    street_low = en.get("analyst_target_low")
    if street_low is not None and bull_iv is not None and not bull_reason:
        try:
            if float(bull_iv) < float(street_low):
                flags.append("bull_below_street_low_without_reason")
        except (ValueError, TypeError):
            pass

    # 6. E10: the base case against consensus EARNINGS and the consensus-implied value. The AMD probe
    #    grew a cash-flow base at consensus REVENUE growth and valued "consensus" at half of it.
    import consensus_reference
    gdr = str(sc.get("guidance_deviation_reason") or "").strip()
    if gdr.lower() in ("null", "none"):
        gdr = ""
    path = sc.get("stage1_growth_path") or []
    c1, c2, _ = consensus_reference.consensus_earnings_growth(en.get("estimates"))
    civ = facts.get("consensus_implied_value")
    lv2 = ((facts.get("levels") or {}).get("year2")
           if consensus_reference.reference_in_force(facts.get("reference_status")) else None)
    y2 = _year2_flow(sc.get("base_cf_used"), path)
    if lv2 and y2 is not None and not gdr:
        # E18: the year-2 LEVEL is the anchor, whatever base the sample declared (ADI (b): a TTM
        # base on the rate path and a fiscal-year base on its own path were 68% apart). Revision 17:
        # the fiscal-year level at 5% (the desk holds a Base's years 1-2 at it, so this is rare; a held
        # Base carries years12_held_by_desk, not this flag)
        if abs(y2 / lv2 - 1) > consensus_reference.LEVELS_HOLD_TOL:
            flags.append("years12_off_consensus_earnings")
    elif not lv2 and c1 is not None and len(path) >= 2 and not gdr:
        try:
            ratio = (1 + float(path[0])) * (1 + float(path[1])) / ((1 + c1) * (1 + c2))
            if not consensus_reference.NEAR_LOW <= ratio <= consensus_reference.NEAR_HIGH:
                flags.append("years12_off_consensus_earnings")
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    p90 = facts.get("years35_p90")
    # revision 18 (brief 1.5): a reference printed outside the street-target fence is a level check only: no band applies
    if (civ and consensus_reference.reference_in_force(facts.get("reference_status"))
            and base_iv is not None and not gdr):
        try:
            if not consensus_reference.FAR_LOW <= float(base_iv) / civ <= consensus_reference.FAR_HIGH:
                flags.append("base_far_from_consensus_implied")
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    if p90 is not None and len(path) >= 5:
        try:
            g35 = ((1 + float(path[2])) * (1 + float(path[3])) * (1 + float(path[4]))) ** (1 / 3) - 1
            if g35 > p90:
                flags.append("years35_above_base_rate_p90")
        except (ValueError, TypeError):
            pass
    rev_cap = facts.get("next_fy_revenue_growth")
    if rev_cap is not None and len(path) >= 5:
        try:
            if any(float(path[i]) - rev_cap > 0.005 for i in (2, 3, 4)) and not gdr:
                flags.append("years35_above_revenue_cap_without_reason")
        except (ValueError, TypeError):
            pass

    # 5. catalysts_missing
    mom = momentum_state or {}
    cats = sc.get("catalysts")
    has_cats = bool(isinstance(cats, list) and len(cats) > 0)
    m1 = mom.get("mom_1m") if isinstance(mom, dict) else None
    m6 = mom.get("mom_6m") if isinstance(mom, dict) else None
    m1_known = isinstance(m1, (int, float))
    m6_known = isinstance(m6, (int, float))
    if (m1_known or m6_known) and not has_cats:
        if (m1_known and abs(m1) >= 0.10) or (m6_known and abs(m6) >= 0.25):
            flags.append("catalysts_missing")

    return implausible, reasons, flags


_SHARES_REASON_CITED_RE = re.compile(
    r"\b(10-K|10-Q|8-K|20-F|6-K|40-F|DEF\s*14A|S-1|424B\w*|(?:SECTION|DATA)\s*6B|(?:SECTION|DATA)\s*2(?!\.\d))\b",
    re.IGNORECASE,
)


def _is_shares_reason_cited(reason: str | None) -> bool:
    if not reason:
        return False
    return bool(_SHARES_REASON_CITED_RE.search(str(reason)))


def extract_desk_snapshot_metrics(
    snapshot=None,
    base_iv=None,
    coe_used=None,
    ticker=None,
    coe_anchor=None,
    scorecard=None,
    pack=None,
    facts=None,
):
    """Inspects run_financial_model tool calls from a sample's research snapshot.

    Returns dict with:
        desk_calls: int (count of run_financial_model calls)
        desk_iv_match: bool (True if base_iv within 1% of any desk per_share_iv or blend result)
        desk_reverse_neutral_cagr: float or None (from neutral reverse DCF call if made)
        coe_minus_anchor: float or None (coe_used - anchor_coe)
        desk_matched_inputs: dict or None (inputs of desk call matching base_iv)
        desk_share_flags: list of str
        desk_share_implausible: bool
        desk_share_reason: str or None
    """
    if facts is None and pack:
        facts = pack_facts.from_text(pack)
    calls = []
    if isinstance(snapshot, list):
        calls = snapshot
    elif isinstance(snapshot, dict):
        calls = snapshot.get("calls", [])
    elif isinstance(snapshot, (str, Path)):
        p = Path(snapshot)
        if p.is_dir():
            p = p / "_research_snapshot.json"
        if p.exists():
            try:
                calls = json.loads(p.read_text(encoding="utf-8")).get("calls", [])
            except Exception:
                calls = []

    model_calls = [c for c in calls if isinstance(c, dict) and c.get("tool") == "run_financial_model"]
    desk_calls = len(model_calls)

    def _parse_float(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _parse_int(v):
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    def _parse_growth(g):
        if g is None or not isinstance(g, (list, tuple)):
            return None
        try:
            return [float(x) for x in g]
        except (ValueError, TypeError):
            return None

    desk_ivs = []
    reverse_neutral_cagr = None
    desk_anchor_from_params = None
    candidates = []

    for c in model_calls:
        params = c.get("params") or {}
        if isinstance(params, dict):
            a_p = params.get("coe_anchor") or params.get("anchor_coe")
            if a_p is not None and desk_anchor_from_params is None:
                desk_anchor_from_params = a_p

        res = c.get("result") or c
        if isinstance(res, dict):
            p_cf = params.get("base_cf")
            p_growth = params.get("explicit_growth") if params.get("explicit_growth") is not None else params.get("growth_rates")
            p_fade = params.get("fade_years")
            p_wacc = params.get("wacc") if params.get("wacc") is not None else params.get("discount_rate")
            p_shares = params.get("shares_diluted")

            # 1. Blend
            b = res.get("blend") if isinstance(res.get("blend"), dict) else (res if res.get("mode") == "blend" or params.get("mode") == "blend" else None)
            if b and isinstance(b, dict):
                for k in ("blended_per_share_iv", "per_share_iv"):
                    v = _parse_float(b.get(k))
                    if v is not None and v > 0:
                        desk_ivs.append(v)
                        candidates.append({
                            "iv": v,
                            "inputs": {
                                "mode": "blend",
                                "base_cf": None,
                                "stage1_growth_path": None,
                                "fade_years": None,
                                "wacc": None,
                                "shares_diluted": None,
                            },
                            "capped": False,
                        })

            # 2. DCF model
            dcf = res.get("dcf_model")
            if isinstance(dcf, dict) and not dcf.get("error"):
                dcf_ivs = []
                for k in ("per_share_iv", "per_share_iv_gordon"):
                    v = _parse_float(dcf.get(k))
                    if v is not None and v > 0:
                        desk_ivs.append(v)
                        dcf_ivs.append(v)
                is_capped = bool(dcf.get("years35_capped"))
                # revision 17: a Base the desk held at the levels was valued on the desk's path, not the requested one
                d_applied = is_capped or bool(dcf.get("years12_held"))
                d_growth = dcf.get("explicit_growth") if d_applied else p_growth
                d_fade = dcf.get("fade_years") if d_applied else p_fade
                for v in dcf_ivs:
                    candidates.append({
                        "iv": v,
                        "inputs": {
                            "base_cf": _parse_float(p_cf),
                            "stage1_growth_path": _parse_growth(d_growth),
                            "fade_years": _parse_int(d_fade),
                            "wacc": _parse_float(p_wacc),
                            "shares_diluted": _parse_float(p_shares),
                        },
                        "capped": is_capped,
                    })

            # 3. Scenario DCFs
            scs = res.get("scenario_dcfs") or []
            param_scs = params.get("scenarios") or []
            if isinstance(scs, list):
                for sc in scs:
                    if isinstance(sc, dict):
                        sc_name = sc.get("name")
                        p_sc = next((s for s in param_scs if isinstance(s, dict) and s.get("name") == sc_name), {})
                        d = sc.get("dcf") or {}

                        sc_cf = sc.get("base_cf") if sc.get("base_cf") is not None else (p_sc.get("base_cf") if p_sc.get("base_cf") is not None else p_cf)
                        sc_g = sc.get("explicit_growth") or p_sc.get("explicit_growth") or sc.get("growth_rates") or p_sc.get("growth_rates") or p_growth
                        sc_fade = sc.get("fade_years") if sc.get("fade_years") is not None else (p_sc.get("fade_years") if p_sc.get("fade_years") is not None else p_fade)
                        sc_wacc = sc.get("wacc") or p_sc.get("wacc") or sc.get("discount_rate") or p_sc.get("discount_rate") or p_wacc
                        sc_shares = sc.get("shares_diluted") if sc.get("shares_diluted") is not None else (p_sc.get("shares_diluted") if p_sc.get("shares_diluted") is not None else p_shares)

                        is_capped = bool(d.get("years35_capped")) if isinstance(d, dict) else False
                        # revision 17: a held Base (years12_held) was valued on the desk's path too
                        if is_capped or (isinstance(d, dict) and d.get("years12_held")):
                            cand_g = d.get("explicit_growth")
                            cand_fade = d.get("fade_years")
                        else:
                            cand_g = sc_g
                            cand_fade = sc_fade

                        ivs_found = []
                        if isinstance(d, dict) and not d.get("error"):
                            for k in ("per_share_iv", "per_share_iv_gordon"):
                                v = _parse_float(d.get(k))
                                if v is not None and v > 0:
                                    ivs_found.append(v)
                        v_iv = _parse_float(sc.get("iv"))
                        if v_iv is not None and v_iv > 0 and v_iv not in ivs_found:
                            ivs_found.append(v_iv)

                        for v in ivs_found:
                            desk_ivs.append(v)
                            candidates.append({
                                "iv": v,
                                "inputs": {
                                    "base_cf": _parse_float(sc_cf),
                                    "stage1_growth_path": _parse_growth(cand_g),
                                    "fade_years": _parse_int(cand_fade),
                                    "wacc": _parse_float(sc_wacc),
                                    "shares_diluted": _parse_float(sc_shares),
                                },
                                "capped": is_capped,
                            })

            # Raw scenarios if scenario_dcfs not present
            raw_scs = res.get("scenarios")
            if raw_scs and isinstance(raw_scs, list) and not scs:
                for sc in raw_scs:
                    if isinstance(sc, dict):
                        sc_name = sc.get("name")
                        p_sc = next((s for s in param_scs if isinstance(s, dict) and s.get("name") == sc_name), {})
                        sc_cf = sc.get("base_cf") if sc.get("base_cf") is not None else (p_sc.get("base_cf") if p_sc.get("base_cf") is not None else p_cf)
                        sc_g = sc.get("explicit_growth") or p_sc.get("explicit_growth") or sc.get("growth_rates") or p_sc.get("growth_rates") or p_growth
                        sc_fade = sc.get("fade_years") if sc.get("fade_years") is not None else (p_sc.get("fade_years") if p_sc.get("fade_years") is not None else p_fade)
                        sc_wacc = sc.get("wacc") or p_sc.get("wacc") or sc.get("discount_rate") or p_sc.get("discount_rate") or p_wacc
                        sc_shares = sc.get("shares_diluted") if sc.get("shares_diluted") is not None else (p_sc.get("shares_diluted") if p_sc.get("shares_diluted") is not None else p_shares)
                        v_iv = _parse_float(sc.get("iv"))
                        if v_iv is not None and v_iv > 0:
                            desk_ivs.append(v_iv)
                            candidates.append({
                                "iv": v_iv,
                                "inputs": {
                                    "base_cf": _parse_float(sc_cf),
                                    "stage1_growth_path": _parse_growth(sc_g),
                                    "fade_years": _parse_int(sc_fade),
                                    "wacc": _parse_float(sc_wacc),
                                    "shares_diluted": _parse_float(sc_shares),
                                },
                                "capped": False,
                            })

            # 4. Top-level per_share_iv (if not blend and not dcf)
            if res.get("mode") != "blend" and params.get("mode") != "blend" and not dcf and not scs and not raw_scs:
                v_top = _parse_float(res.get("per_share_iv"))
                if v_top is not None and v_top > 0:
                    desk_ivs.append(v_top)
                    candidates.append({
                        "iv": v_top,
                        "inputs": {
                            "base_cf": _parse_float(p_cf),
                            "stage1_growth_path": _parse_growth(p_growth),
                            "fade_years": _parse_int(p_fade),
                            "wacc": _parse_float(p_wacc),
                            "shares_diluted": _parse_float(p_shares),
                        },
                        "capped": False,
                    })

            # 5. Reverse DCF
            rev = res.get("reverse_dcf")
            if isinstance(rev, dict):
                neutral = rev.get("neutral_reference_structure")
                if isinstance(neutral, dict):
                    cagr = neutral.get("implied_10y_cagr_pct")
                    if cagr is not None and reverse_neutral_cagr is None:
                        try:
                            reverse_neutral_cagr = float(cagr)
                        except (ValueError, TypeError):
                            pass

    desk_iv_match = False
    matching_candidates = []
    if desk_calls > 0 and candidates and base_iv is not None:
        try:
            biv = float(base_iv)
            for cand in candidates:
                if cand["iv"] > 0 and (abs(biv - cand["iv"]) / cand["iv"]) <= 0.010001:
                    desk_iv_match = True
                    matching_candidates.append(cand)
        except (ValueError, TypeError):
            desk_iv_match = False

    # S3 3.8 retirement: no typed values remain to compare against, so the desk-contract-mismatch
    # scoring is gone. The matching candidate nearest base_iv is used directly.
    desk_matched_inputs = None
    desk_years35_capped = False
    if matching_candidates:
        biv = float(base_iv)
        best_cand = min(matching_candidates, key=lambda c: abs(c["iv"] - biv))
        desk_matched_inputs = best_cand["inputs"]
        desk_years35_capped = bool(best_cand.get("capped", False))

    desk_share_basis_matched = None
    share_flags = []
    share_implausible = False
    share_reason = None

    if desk_matched_inputs and facts:
        call_shares = desk_matched_inputs.get("shares_diluted")
        if call_shares is not None and call_shares > 0:
            # Revision 16: the desk takes a whole count or billions and converts with `_to_b`; the
            # candidates below are in billions, so the model's count is read the same way.
            desk_count = _to_b(call_shares)
            # S3 3.5 "S2b's share check in revision 15": candidates gain "default" (facts'
            # shares_default, 5.11), via the function contract_fill.fill's shares_basis shares —
            # one copy of the candidate list, not two.
            nearest_name, nearest_ratio = contract_fill.s2b_share_match(desk_count, facts)

            if nearest_ratio is not None:
                if nearest_name is not None:
                    desk_share_basis_matched = nearest_name

                ratio_r = round(nearest_ratio, 2)
                if nearest_ratio >= 1.099999:
                    share_flags.append(f"desk_share_count_mismatch_{ratio_r:.2f}x")

                raw_shares_reason = scorecard.get("shares_reason") if scorecard else None
                has_shares_reason = bool(
                    raw_shares_reason is not None
                    and str(raw_shares_reason).strip() != ""
                    and str(raw_shares_reason).strip().lower() not in ("null", "none")
                )

                # A departure is a count more than 1% from the share-count default (S3 5.11) when the
                # facts carry one, and from SECTION 2's count when they do not (revision-14 packs,
                # S2b). A reason attached to that count itself is not a departure and is not flagged.
                ref_count = facts.get("shares_default")
                if not (isinstance(ref_count, (int, float)) and ref_count > 0):
                    ref_count = facts.get("shares_outstanding")
                ref_matched = (isinstance(ref_count, (int, float)) and ref_count > 0
                               and max(desk_count, ref_count / 1e9) / min(desk_count, ref_count / 1e9) <= 1.010001)
                departs = not ref_matched
                if has_shares_reason:
                    if departs:
                        share_flags.append("desk_share_count_departure_with_reason")
                        if not _is_shares_reason_cited(raw_shares_reason):
                            share_flags.append("shares_reason_uncited")
                elif nearest_ratio > 1.250001:
                    share_implausible = True
                    share_reason = "desk share count off by more than 25% (units or omission)"

            # Annotation only, never an exclusion: a Base count 10x or more from the share-count default
            # (5.11), in either direction, is where a wrong unit or a wrong company's count shows up.
            default_count = facts.get("shares_default")
            if isinstance(default_count, (int, float)) and default_count > 0:
                default_b = default_count / 1e9
                far_ratio = max(desk_count, default_b) / min(desk_count, default_b)
                if far_ratio >= 9.999999:
                    share_flags.append(f"desk_share_count_far_from_default_{far_ratio:.2f}x")

    eff_anchor = coe_anchor if coe_anchor is not None else desk_anchor_from_params
    if eff_anchor is None and ticker:
        eff_anchor = resolve_anchor_coe(ticker)

    diff_coe = None
    if coe_used is not None and eff_anchor is not None:
        try:
            cu = float(coe_used)
            ea = float(eff_anchor)
            if cu > 1.0:
                cu /= 100.0
            if ea > 1.0:
                ea /= 100.0
            diff_coe = round(cu - ea, 6)
        except (ValueError, TypeError):
            pass

    return {
        "desk_calls": desk_calls,
        "desk_iv_match": desk_iv_match,
        "desk_reverse_neutral_cagr": reverse_neutral_cagr,
        "coe_minus_anchor": diff_coe,
        "desk_matched_inputs": desk_matched_inputs,
        # S3 A+B fixup (Task 3 replay, §7.5): desk_contract_flags stays in the scorecard as an
        # always-empty list. The scoring that used to populate it is retired (Task 2), but the field
        # itself is not one of the replay's ignored keys, so it must still exist and be identical.
        "desk_contract_flags": [],
        "desk_share_flags": share_flags,
        "desk_share_implausible": share_implausible,
        "desk_share_reason": share_reason,
        "desk_share_basis_matched": desk_share_basis_matched,
        "desk_per_share_ivs": desk_ivs,
        "desk_years35_capped": desk_years35_capped,
    }


class ResearchSnapshot(tuple):
    def __new__(cls, asof, age_days, stale, wrong_company=False):
        return super().__new__(cls, (asof, age_days, stale))

    def __init__(self, asof, age_days, stale, wrong_company=False):
        self.asof = asof
        self.age_days = age_days
        self.stale = stale
        self.wrong_company = wrong_company


def snapshot_research_brief(t, run_dir, validate=False):
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
    wrong_company = False
    if research_file.exists():
        try:
            brief_text = research_file.read_text(encoding="utf-8", errors="replace")
            if validate:
                ok, reason = check_research_brief(t, brief_text=brief_text)
                if not ok:
                    print(f"  [consensus] WARN research brief failed company verification ({reason}) "
                          "— NOT snapshotted as valid (flagging research_wrong_company)", flush=True)
                    wrong_company = True
            if not wrong_company:
                mtime = research_file.stat().st_mtime
                asof = datetime.fromtimestamp(mtime).isoformat()
                age_days = round((time.time() - mtime) / 86400, 2)
                import shutil
                shutil.copyfile(research_file, run_dir / "_research_brief.md")
        except Exception as e:
            print(f"  [consensus] WARN could not copy research brief: {e}", flush=True)
    max_age_days = float(rs2_data.CONFIG["research_max_age_days"])
    stale = bool(age_days is not None and age_days > max_age_days)
    if stale and not wrong_company:
        print(f"  [consensus] WARN research brief is {age_days:.1f}d old "
              f"(> {max_age_days:.0f}d) — flagging stale_research_brief", flush=True)
    return ResearchSnapshot(asof, age_days, stale, wrong_company=wrong_company)


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


def desk_backed(run):
    """A sample whose base IV no desk call produced is not a basis sample (GPOR (b) s2: zero tool
    calls, a hand-computed $425 inside 3.7% of the desk-backed $410 made the spread look like
    agreement). It stays in `runs` with its IV and flags; it is left out of the band, the median,
    the spread and n_basis."""
    fl = run.get("flags") or []
    return "desk_not_used" not in fl and "iv_not_desk_backed" not in fl


def counts_as_result(run):
    """Operator ruling 2026-09-27: a sample written at reduced thinking, or one whose harness run
    failed, is not a result. It stays in `runs` with its record; it never enters the band."""
    return (bool(run.get("iv")) and bool(run.get("plausible")) and not run.get("truncated")
            and desk_backed(run) and not run.get("reduced_thinking") and not run.get("failed_reason"))


def early_stop_check(g2, prior_base=None):
    """P4.7/B2 — pure decision for the adaptive 2-sample early stop. No I/O, no printing.

    `g2`: the two usable (plausible, complete) sample dicts, each carrying `iv` and `scorecard`.
    `prior_base`: the prior verdict's contract base (float), or None/falsy to skip that leg —
    depth_pipeline.main() passes None whenever there is no prior, or the only prior predates the
    analyst Phase 4 ruled valid (B2; see depth_gates.analyst_valid).

    Returns {stop, sp2, bear_sp2, bear_ok, prior_delta_pct, prior_ok}. `stop` is True only when
    the base-IV spread is <= EARLY_TOL_PCT AND the bear-IV spread is confirmed <= BEAR_TOL_PCT
    (a missing bear_iv on either sample fails closed: `bear_ok` False, same treatment as an
    unusable base sample) AND, when a prior was supplied, the 2-sample median sits within 25%
    of it.
    """
    ivs = [r["iv"] for r in g2]
    sp2 = (max(ivs) / min(ivs) - 1) * 100

    bear_vals = [(r.get("scorecard") or {}).get("bear_iv") for r in g2]
    bear_sp2 = None
    if all(v is not None for v in bear_vals) and min(bear_vals):
        bear_sp2 = (max(bear_vals) / min(bear_vals) - 1) * 100
    bear_ok = bear_sp2 is not None and bear_sp2 <= BEAR_TOL_PCT

    med2 = st.median(ivs)
    prior_delta_pct = None
    prior_ok = True
    if prior_base is not None and prior_base:
        prior_delta_pct = abs(med2 - prior_base) / prior_base * 100
        prior_ok = prior_delta_pct <= 25.0

    return {"stop": sp2 <= EARLY_TOL_PCT and bear_ok and prior_ok,
            "sp2": sp2, "bear_sp2": bear_sp2, "bear_ok": bear_ok,
            "prior_delta_pct": prior_delta_pct, "prior_ok": prior_ok}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "GOOG").upper()
    adaptive = "--samples" not in sys.argv
    n = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 3
    model = (sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv
             else "rs2-analyst-deep-mtp5")
    ctx = int(sys.argv[sys.argv.index("--ctx") + 1]) if "--ctx" in sys.argv else 98304
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
    # GPU memory margin at 98,304 (config depth_num_batch, 2026-09-27); None = Ollama's default
    num_batch = int(sys.argv[sys.argv.index("--num-batch") + 1]) if "--num-batch" in sys.argv else None
    # ctx raised to 98,304 on 2026-09-27, measured on the RTX 3090: 23.6 GB resident, fully on GPU,
    # no CPU spill. Do not raise further without re-probing /api/ps for spill.

    # P4.0b — frozen-evidence dispersion battery options ------------------------------------
    # `--no-early-stop`: the battery needs FULL samples for dispersion, so the adaptive
    # 2-escalate break (below, `if adaptive and i == 2`) must never fire. Passing --samples
    # already sets adaptive False (unchanged, above); this makes that intent explicit and
    # covers the case where the caller wants a fixed default of 3 with no early stop too.
    no_early_stop = "--no-early-stop" in sys.argv
    failfast_street = "--failfast-street" in sys.argv
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

    # P4.7/B2 — the prior verdict's contract base, passed by depth_pipeline.main() ONLY when
    # that prior is depth_gates.analyst_valid(prior); absent here for every other case (no prior,
    # an invalid-analyst prior, or a standalone/battery invocation). Used only to tighten the
    # 2-sample early-stop bar below; `doc["prior_base"]` stamps the value actually used, or the
    # sentinel string "none_valid" when none was supplied — never a fabricated float.
    prior_base = None
    if "--prior-base" in sys.argv:
        try:
            prior_base = float(sys.argv[sys.argv.index("--prior-base") + 1])
        except (IndexError, ValueError) as e:
            print(f"[consensus] ::HARD FAIL:: --prior-base could not be parsed ({e})", flush=True)
            raise

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
        pack_active_shocks, pack_momentum_state = None, None  # unknown: not rebuilt this run
        # S3 5.9 (C2): research_omitted is written only when the pack is built fresh; a frozen
        # `--pack-file` reuse reads a pack that was already filtered when it was built.
        pack_research_omitted = None
        sidecar = pack_facts.read_sidecar(pack_file_arg.parent)
        if sidecar is not None:
            facts = sidecar
            pack_facts_source = "sidecar"
            pack_facts_version_read = sidecar.get("version")   # S3 3.1: the sidecar's own version
        else:
            facts = pack_facts.from_text(pack)
            pack_facts_source = "text"
            pack_facts_version_read = None
        pack_facts_parity = None
        print(f"  [pack facts] source: {pack_facts_source}", flush=True)
    else:
        pack_text = cap.build_pack(t, price_override=price_override)
        pack_macro_degraded = bool(getattr(pack_text, "macro_degraded", False)
                                   or getattr(cap, "LAST_PACK_MACRO_DEGRADED", False))
        pack = pack_text + "\n\n---\n\n" + cap.TASK
        pack_source = "fresh"
        # Rule 11 (verdict stamping, C1 + P4.3 prep): the exact §1.6/§2.5 blocks THIS pack build
        # printed, so consensus.json (below) can record what the analyst actually saw.
        pack_active_shocks = list(getattr(cap, "LAST_PACK_ACTIVE_SHOCKS", []) or [])
        pack_momentum_state = dict(getattr(cap, "LAST_PACK_MOMENTUM_STATE", {}) or {})
        # S3 5.9 (C2): the SECTION 11 sub-sections this build dropped as off-topic.
        pack_research_omitted = list(getattr(pack_text, "research_omitted", []) or [])
        facts = pack_text.facts
        pack_facts_source = "build"
        pack_facts_version_read = facts.get("version")
        diffs = pack_facts.parity(facts, pack_facts.from_text(pack))
        pack_facts_parity = {"ok": len(diffs) == 0, "mismatches": diffs}
        if diffs:
            print(f"::PACK FACTS PARITY:: mismatches: {', '.join(diffs)}", flush=True)
    pack_sha256 = hashlib.sha256(pack.encode("utf-8")).hexdigest()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = out_root / f"{t}_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    # Snapshot research brief into run dir (P1.7); C4: age ceiling enforced where consumed; D8: company check.
    r_snap = snapshot_research_brief(t, d, validate=True)
    research_brief_asof, research_brief_age_days, research_brief_stale = r_snap
    research_wrong_company = getattr(r_snap, "wrong_company", False)
    no_research_arg = "--no-research" in sys.argv

    if research_wrong_company or no_research_arg:
        # Proceed with --no-research semantics: strip Section 11 from pack
        pack = re.sub(r"## (?:SECTION|DATA) 11 - DEEP RESEARCH BRIEF.*?(?=## (?:SECTION|DATA) 12|\Z)", "", pack, flags=re.DOTALL)
        pack_sha256 = hashlib.sha256(pack.encode("utf-8")).hexdigest()

    # Save the exact pack. Without it a consensus run is not re-auditable from its own directory
    # — found when three auditors had to reconstruct it independently to check the reports.
    (d / "_pack.md").write_text(pack, encoding="utf-8")
    pack_facts.write_sidecar(d, facts)

    # S3 3.2: the harness hands the desk every constant the pack holds, once per run, from the
    # facts object and the harness price. shares_default_b is 5.11's default, not SECTION 2's
    # count; a count of 0 gives None (a zero share count cannot be a default), tested with
    # `is not None`, never `or`.
    desk_context = {
        "price": price,                                   # the harness price, the one the verdict uses
        "shares_default_b": (_num_b(facts["shares_default"])
                             if facts["shares_default"] is not None and facts["shares_default"] > 0
                             else None),
        "coe_anchor": facts["coe_anchor"],
        "terminal_g_default": facts["terminal_g_default"],
        "terminal_g_anchor": facts["terminal_g_anchor"],
        "base_rate_table": facts["base_rate_5y"] or None,
        "revenue_cagr_5y_pct": facts["revenue_cagr_5y_pct"],
        "net_debt_default_b": facts["net_debt_b"],
        "interest_expense_latest_b": facts["interest_expense_latest_b"],
        "owner_earnings_default_b": facts["owner_earnings_default_b"],
        "base_window": facts["base_window"],
        "consensus_implied_value": facts["consensus_implied_value"],
        "levels": facts["levels"],
        # revision 17 (brief B 4): the through-cycle facts the desk values with; an older frozen pack's
        # sidecar carries None for each
        "terminal_ronic": facts["terminal_ronic"],
        "long_run": facts["long_run"],
        "working_capital": facts["working_capital"],
        "cash_basis_b": facts["cash_basis_b"],
        # revision 17, brief F6: the fiscal-year owner-earnings base the reference grows from, so the desk can tell an
        # owner-earnings base from the cash basis
        "reference_base_b": facts["reference_base_b"],
        # revision 18 (brief 1.7, 1.5): the excess cash the desk adds at face, and whether the reference is in force or
        # printed outside the street-target fence as a level check only
        "excess_cash": facts.get("excess_cash"),
        "reference_status": facts.get("reference_status"),
        "years35_cap": facts["next_fy_revenue_growth"],
        "shares_warning": facts["shares_warning"],       # R1b (5.11)
    }

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

    cds = facts.get("consensus_data_status")
    if cds != "ok":
        print(f"::PACK DATA:: {cds}", flush=True)

    runs = []
    n_max = 3 if adaptive else n
    attempted = 0        # iterations ENTERED - the only honest denominator for sample loss
    broke_early = False  # set only by the adaptive early-stop branch below
    failfast_record = None
    for i in range(1, n_max + 1):
        attempted = i
        t0 = time.time()
        resp, meta = {}, {}
        sample_retried = False
        report_continued = None
        # P4.0b: hits/misses against the shared evidence store, accumulated across both the
        # initial chat_with_tools call and the empty-report retry (below) for THIS sample.
        sample_es_hits, sample_es_misses = 0, 0
        try:
            if use_tools:
                sd_i = d / f"sample{i}_research"
                rep, think, meta = analyst_tools.chat_with_tools(
                    model, pack, sd_i, think=think_level, ctx=ctx, num_predict=NUM_PREDICT, num_batch=num_batch,
                    seed=1000 + i, draft_num_predict=draft_num_predict, temperature=temperature,
                    query_cache=evidence_query_cache if evidence_store_dir is not None else None,
                    url_cache=evidence_url_cache if evidence_store_dir is not None else None,
                    desk_context=desk_context)
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
                    **({"num_batch": num_batch} if num_batch else {}),
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
                resp = llm_provider.chat(body, 7200)
                msg = resp.get("message") or {}
                rep = msg.get("content") or ""
                think = msg.get("thinking") or ""
        except Exception as e:
            print(f"  sample {i}: FAILED {str(e)[:90]}", flush=True)
            continue
        first_meta = meta
        # EMPTY-REPORT RETRY (found live on ANET s2, 2026-08-22): 118K chars of thinking,
        # done_reason=stop, ZERO report content - the model reasoned itself to a stop without
        # emitting the deliverable. One retry with a perturbed seed; a second empty is recorded
        # and the sample excluded as before (n_basis drops, verdict still emitted).
        if not (rep or "").strip() and not use_tools:
            try:
                sample_retried = True
                print(f"  sample {i}: EMPTY report after {len(think):,}ch thinking - "
                      f"one retry, perturbed seed", flush=True)
                body["options"]["seed"] = 1000 + i + 50000
                resp = llm_provider.chat(body, 7200)
                msg = resp.get("message") or {}
                rep = msg.get("content") or ""
                think = msg.get("thinking") or ""
            except Exception as e:
                print(f"  sample {i}: RETRY FAILED {str(e)[:90]}", flush=True)
                continue
        elif not (rep or "").strip() and use_tools:
            try:
                sample_retried = True
                import analyst_tools as _at
                print(f"  sample {i}: EMPTY report after {len(think):,}ch thinking - "
                      f"one retry, perturbed seed", flush=True)
                rep, think, meta = _at.chat_with_tools(
                    model, pack, d / f"sample{i}_research_retry", think=think_level, ctx=ctx, num_batch=num_batch,
                    num_predict=NUM_PREDICT, seed=1000 + i + 50000, draft_num_predict=draft_num_predict,
                    temperature=temperature,
                    query_cache=evidence_query_cache if evidence_store_dir is not None else None,
                    url_cache=evidence_url_cache if evidence_store_dir is not None else None,
                    desk_context=desk_context)
                sample_es_hits += meta.get("evidence_hits") or 0
                sample_es_misses += meta.get("evidence_misses") or 0
                resp = {"done_reason": meta.get("done_reason"),
                        "eval_count": meta.get("generated_tokens"),
                        "eval_rate": meta.get("eval_rate"),
                        "eval_duration_s": meta.get("eval_duration_s")}
            except Exception as e:
                print(f"  sample {i}: RETRY FAILED {str(e)[:90]}", flush=True)
                continue
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
                draft_num_predict=draft_num_predict, temperature=temperature,
                think=think_level, num_batch=num_batch)
            report_continued = {
                "chars_rescued": len(rep_cont) if rep_cont else 0,
                "done_reason": (meta_cont or {}).get("done_reason"),
                "think": think_level,
            }
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

        # Harness-filled per sample from tool snapshot (P4.0a)
        snapshot_dir = None
        if use_tools:
            if sample_retried:
                snapshot_dir = d / f"sample{i}_research_retry"
                if not (snapshot_dir / "_research_snapshot.json").exists():
                    snapshot_dir = d / f"sample{i}_research"
            else:
                snapshot_dir = d / f"sample{i}_research"
                if not (snapshot_dir / "_research_snapshot.json").exists():
                    snapshot_dir = d / f"sample{i}_research_retry"

        calls = []
        if use_tools and snapshot_dir and (snapshot_dir / "_research_snapshot.json").exists():
            snap_file = snapshot_dir / "_research_snapshot.json"
            calls = json.loads(snap_file.read_text(encoding="utf-8")).get("calls") or []

        # S3 5.12: a revision-15 pack (its own first-line marker, not just cap.PACK_REVISION —
        # a frozen `--pack-file` reuse may carry an older stamp) never publishes a blend.
        filled, prov = contract_fill.fill(calls, scorecard, facts, price, ticker=t,
                                          allow_blend=not pack_facts.is_revision_15(pack))
        scorecard.update(filled)
        scorecard["code_fill"] = prov

        ivs = extract_iv(rep, price)
        # 0.0 is a value: a Base of 0.0 is judged (and refused) as the sample's number, not replaced by
        # a figure scraped from the memo.
        iv = scorecard.get("base_iv")
        if iv is None:
            iv = st.median(ivs) if ivs else None
        ok, why, flags = plausibility(iv, price, t)

        desk_info = extract_desk_snapshot_metrics(
            snapshot=snapshot_dir,
            base_iv=iv,
            coe_used=scorecard.get("coe_used"),
            ticker=t,
            scorecard=scorecard,
            pack=pack,
            facts=facts,
        )
        scorecard.update(desk_info)
        if desk_info["desk_calls"] == 0:
            flags = list(flags) + ["desk_not_used"]
            why = list(why) + ["desk not used (0 financial model calls)"]
        if not desk_info["desk_iv_match"]:
            flags = list(flags) + ["iv_not_desk_backed"]
            why = list(why) + [f"base IV ${iv} not backed by any desk calculation within 1%"]

        if desk_info.get("desk_years35_capped"):
            if "years35_capped_by_desk" not in flags:
                flags = list(flags) + ["years35_capped_by_desk"]

        for f in desk_info.get("desk_share_flags", []):
            if f not in flags:
                flags = list(flags) + [f]
        if desk_info.get("desk_share_implausible"):
            ok = False
            r_msg = desk_info.get("desk_share_reason") or "desk share count off by more than 25% (units or omission)"
            if r_msg not in why:
                why = list(why) + [r_msg]

        for f in check_base_cf_default_reason(scorecard):
            if f not in flags:
                flags = list(flags) + [f]

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
        if research_wrong_company and "research_wrong_company" not in flags:
            flags = list(flags) + ["research_wrong_company"]
            why = list(why) + ["research brief failed company verification (research_wrong_company)"]

        research_calls = meta.get("research_calls", 0)
        repeat_calls = meta.get("repeat_calls", 0)
        desk_runs = meta.get("desk_runs") or []
        desk_swing = (round(max(desk_runs) / min(desk_runs), 2)
                      if len(desk_runs) >= 2 and min(desk_runs) > 0 else None)
        if len(desk_runs) >= 2 and desk_swing is not None and desk_swing > 1.25:
            flags = list(flags) + [f"desk_input_revisions_{len(desk_runs)}_swing_{desk_swing:.2f}x"]
        if research_calls >= 5 and (repeat_calls / research_calls) > 0.15:
            flags = list(flags) + [f"research_repeats_{repeat_calls}_of_{research_calls}"]

        en_for_checks = rs2_data.load_json(HERE / "enrich" / f"{t}.json") or {}
        order_imp, rule_reasons, rule_flags = check_sample_harness_rules(
            scorecard=scorecard,
            price=price,
            desk_info=desk_info,
            enrich_data=en_for_checks,
            momentum_state=pack_momentum_state,
            pack_text=pack,
            facts=facts,
        )
        if order_imp:
            ok = False
        for r in rule_reasons:
            if r not in why:
                why = list(why) + [r]
        for f in rule_flags:
            if f not in flags:
                flags = list(flags) + [f]
        # E10: the consensus ratios go on every sample, whatever reason the model wrote.
        if isinstance(scorecard, dict):
            scorecard.update(consensus_ratios(scorecard, en_for_checks, pack, facts=facts))
            # E12: shares, net debt and bull/bear against the pack, per scenario
            e12_flags, e12_stamps = scenario_checks(snapshot_dir, scorecard, en_for_checks, pack, price, facts=facts)
            scorecard.update(e12_stamps)
            for f in e12_flags:
                if f not in flags:
                    flags = list(flags) + [f]

        # Carry the harness rescue status onto the sample. Without this the four-key copy out of
        # `meta` above drops it, and a band can mix a sample written at reduced reasoning effort
        # with normal siblings with no consumer able to tell.
        rescue = rescue_status(meta)
        first_rescue = rescue_status(first_meta)
        # P4.0b: persist the evidence store after every sample (not only at the end) so an
        # interrupted battery run never loses evidence it already gathered.
        if evidence_store_dir is not None:
            _save_evidence_store(evidence_store_dir, evidence_query_cache, evidence_url_cache)
        first_attempt_failure = (first_rescue["failure"] or "empty_report") if sample_retried else None
        window_retry_used = bool(first_rescue["window_retry_used"] or rescue["window_retry_used"])
        failed_reason = rescue["failure"] if rescue.get("failure") is not None else ("empty_report" if not (rep or "").strip() else None)
        runs.append({"sample": i, "iv": iv, "scorecard": scorecard, "all_iv_mentions": sorted(set(ivs))[:8],
                     "plausible": ok, "reasons": why, "flags": flags, "truncated": truncated,
                     "stub_rejected": rescue["stub_rejected"],
                     "forced_report": rescue["forced_report"],
                     "budget_exhausted": rescue["budget_exhausted"],
                     "desk_recovery_used": rescue["desk_recovery_used"],
                     "reduced_thinking": rescue["reduced_thinking"],
                     "window_retry_used": window_retry_used,
                     "continuation_for_desk": rescue["continuation_for_desk"],
                     **({"first_attempt_continuation_for_desk": first_rescue["continuation_for_desk"]}
                        if sample_retried else {}),
                     "sample_retried": sample_retried,
                     "first_attempt_failure": first_attempt_failure,
                     "report_continued": report_continued,
                     "failed_reason": failed_reason,
                     "report_turn_headroom_tokens": (meta or {}).get("report_turn_headroom_tokens"),
                     "done_reason": resp.get("done_reason"),
                     **llm_provider.run_row_provenance(meta, resp),
                     "prompt_tokens": p_tok, "generated_tokens": g_tok,
                     "eval_rate": eval_rate, "eval_duration_s": eval_dur_s,
                     "thinking_chars": len(think), "report_chars": len(rep),
                     "thinking_share_of_output": (round(len(think) / (len(think) + len(rep)), 3)
                                                  if (think or rep) else None),
                     "evidence_store_hits": sample_es_hits if evidence_store_dir is not None else None,
                     "evidence_store_misses": sample_es_misses if evidence_store_dir is not None else None,
                     "desk_calls": desk_info["desk_calls"],
                     "desk_iv_match": desk_info["desk_iv_match"],
                     "desk_reverse_neutral_cagr": desk_info["desk_reverse_neutral_cagr"],
                     "coe_minus_anchor": desk_info["coe_minus_anchor"],
                     "desk_matched_inputs": desk_info.get("desk_matched_inputs"),
                     "desk_share_basis_matched": desk_info.get("desk_share_basis_matched"),
                     "desk_validation_errors": meta.get("desk_validation_errors", 0),
                     "research_calls": research_calls,
                     "repeat_calls": repeat_calls,
                     "desk_runs": desk_runs,
                     "desk_swing": desk_swing,
                     "chars": len(rep), "secs": round(time.time() - t0)})
        # revision 17, brief C8: a sample that used the desk continuation is flagged, after continue_report and the
        # checks: `continuation_for_desk` when it counts as a result, `continuation_for_desk_failed` when it does not.
        # Annotation only: counts_as_result is unchanged, so a sample still without a complete desk run stays out of
        # the band exactly as before.
        if runs[-1]["continuation_for_desk"] is not None:
            flags = list(flags) + ["continuation_for_desk" if counts_as_result(runs[-1])
                                   else "continuation_for_desk_failed"]
            runs[-1]["flags"] = flags
        rate_str = f" | {eval_rate} tok/s ({eval_dur_s}s)" if eval_rate else ""
        print(f"  sample {i}: IV ${iv if iv else '?'} | usable={ok}"
              + f" | gen {g_tok} tok (think {len(think):,}ch / report {len(rep):,}ch)"
              + rate_str
              + (f" ({'; '.join(why)})" if why else "")
              + (f" | flags: {', '.join(flags)}" if flags else "")
              + (" | TRUNCATED" if truncated else ""), flush=True)

        # FAILFAST ON STREET RANGE (after sample 1 only)
        if failfast_street and i == 1:
            if ok and iv is not None:
                band = vb._consensus_band(t)
                band_stale = band.get("stale") if isinstance(band, dict) else getattr(band, "stale", False)
                band_low = band.get("low") if isinstance(band, dict) else getattr(band, "low", None)
                band_high = band.get("high") if isinstance(band, dict) else getattr(band, "high", None)
                if band and not band_stale and band_low is not None and band_high is not None:
                    wacc = 0.10
                    lo_d = band_low / (1 + wacc)
                    hi_d = band_high / (1 + wacc)
                    if iv < 0.5 * lo_d or iv > 2.0 * hi_d:
                        failfast_record = {
                            "sample": 1,
                            "iv": round(iv, 2),
                            "street_low_disc": round(lo_d, 2),
                            "street_high_disc": round(hi_d, 2),
                            "ratio_to_low": round(iv / lo_d, 3),
                            "ratio_to_high": round(iv / hi_d, 3),
                            "rule": "sample 1 below 0.5x discounted street low or above 2x discounted street high",
                        }
                        print(f"  [failfast] sample 1 IV ${iv:.2f} outside street range "
                              f"[0.5x lo={0.5*lo_d:.2f}, 2x hi={2.0*hi_d:.2f}] — stopping sampling",
                              flush=True)
                        break
        # ADAPTIVE EARLY STOP after sample 2: publish on two COMPLETE, PLAUSIBLE samples inside
        # the tighter bar. Every other outcome - spread beyond EARLY_TOL, an implausible or
        # truncated or unparseable sample - falls through and buys the 3rd opinion. The bar is
        # tighter than TOL_PCT on purpose; see EARLY_TOL_PCT.
        if adaptive and i == 2:
            g2 = [r for r in runs if counts_as_result(r)]
            if len(g2) == 2:
                d2 = early_stop_check(g2, prior_base)
                if d2["stop"]:
                    extra = []
                    if d2["bear_sp2"] is not None:
                        extra.append(f"bear spread {d2['bear_sp2']:.1f}% "
                                     f"(bar {BEAR_TOL_PCT:.0f}%)")
                    if d2["prior_delta_pct"] is not None:
                        extra.append(f"prior delta {d2['prior_delta_pct']:.1f}% (bar 25%)")
                    print(f"  [adaptive] 2 samples agree within {d2['sp2']:.1f}% "
                          f"(early bar {EARLY_TOL_PCT:.0f}%)"
                          + (f", {', '.join(extra)}" if extra else "")
                          + " — stopping, no 3rd sample", flush=True)
                    broke_early = True
                    break

                bear_str = "n/a" if d2["bear_sp2"] is None else f"{d2['bear_sp2']:.1f}%"
                why2 = [f"base spread {d2['sp2']:.1f}%/{EARLY_TOL_PCT:.0f}%",
                       f"bear spread {bear_str}/{BEAR_TOL_PCT:.0f}%"]
                if d2["prior_delta_pct"] is not None:
                    why2.append(f"prior delta {d2['prior_delta_pct']:.1f}%/25%")
                print(f"  [adaptive] early-stop bar not met ({'; '.join(why2)}) — "
                      f"escalating to 3rd sample", flush=True)
            else:
                print(f"  [adaptive] only {len(g2)} usable of 2 — escalating to 3rd sample",
                      flush=True)

    good = [r for r in runs if counts_as_result(r)]
    # the verdict writer (depth_pipeline.band_verdict) judges exactly these samples; this module
    # is the single owner of which samples count
    for r in runs:
        r["basis"] = any(r is g for g in good)
    pb_votes = {}
    for r in good:
        sc = r.get("scorecard") or {}
        pb = sc.get("position_basis")
        pb_str = str(pb).strip().lower() if pb else "none"
        pb_votes[pb_str] = pb_votes.get(pb_str, 0) + 1
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

    if failfast_record is not None:
        converged = False
        verdict = "FAILFAST — sample 1 outside street range"
    else:
        verdict = ("CONVERGED" if converged and med else
                   "NOT CONVERGED — runs disagree beyond tolerance" if med and spread is not None else
                   f"NOT CONVERGED — only {len(good)} usable sample(s), spread undefined" if med else
                   "NO USABLE SAMPLE — nothing parseable and complete")
    doc = {"ticker": t, "price": price, "model": model, "think": think_level,
           **llm_provider.doc_provenance(runs),
           "draft_num_predict": draft_num_predict,
           "temperature": temperature,
           "pack_revision": cap.PACK_REVISION,
           "pack_source": pack_source, "pack_sha256": pack_sha256,
           "pack_facts_source": pack_facts_source,
           "pack_facts_version": pack_facts.FACTS_VERSION,
           "pack_facts_version_read": pack_facts_version_read,
           "consensus_data_status": facts.get("consensus_data_status"),
           "research_brief_asof": research_brief_asof,
           "research_brief_age_days": research_brief_age_days,
           "research_brief_stale": research_brief_stale,
           "research_wrong_company": research_wrong_company,
           # Rule 11: the §1.6 active-shock list and the exact §2.5 momentum_state block this
           # pack build printed to the analyst — None on a frozen `--pack-file` reuse, since no
           # build_pack() call ran this time to know what it would have printed.
           "active_shocks_at_verdict": pack_active_shocks,
           "momentum_state": pack_momentum_state,
           "price_asof": price_override.get("asof") if price_override else None,
           "mode": ("adaptive" if adaptive else f"fixed_{n}"),
           "no_early_stop": no_early_stop,
           "evidence_store_dir": str(evidence_store_dir) if evidence_store_dir is not None else None,
           "samples_run": len(runs), "early_stop": early_stop,
           # P4.7/B2 — the prior base actually used for the early-stop's prior-delta leg, or the
           # sentinel "none_valid" when depth_pipeline chose not to supply one (no prior, or the
           # only prior predates the analyst Phase 4 ruled valid).
           "prior_base": prior_base if prior_base is not None else "none_valid",
           "samples_intended": progress["samples_intended"],
           "samples_attempted": progress["samples_attempted"],
           "samples_lost": progress["samples_lost"],
           "effective_tolerance_pct": eff_tol,
           "generated_at": datetime.now(timezone.utc).isoformat(),
           "runs": runs, "n_plausible": len(good),
           "median_iv": med, "spread_pct": round(spread, 1) if spread is not None else None,
           "tolerance_pct": TOL_PCT, "early_tolerance_pct": EARLY_TOL_PCT,
           "converged": converged, "verdict": verdict,
           "position_basis_votes": pb_votes,
           "scorecard": scorecard_summary,
           "median_mos_pct": round((med / price - 1) * 100, 1) if med and price else None}
    if pack_facts_source == "build":
        doc["pack_facts_parity"] = pack_facts_parity
        # S3 5.9 (C2): only written when the pack is built fresh — a frozen `--pack-file` reuse
        # reads a pack that was already filtered when it was built, so the key stays absent
        # rather than present-as-null (matches a pre-C record, where the key never existed).
        doc["research_omitted"] = pack_research_omitted
    if failfast_record is not None:
        doc["failfast"] = failfast_record
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
