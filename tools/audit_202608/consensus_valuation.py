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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import common  # noqa: E402
common.enable_json_cache()
import capability_test as cap  # noqa: E402
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402

OUT = HERE / "ab_reports" / "consensus"
# THRESHOLDS — calibrated against four reference points on GOOG @ $343.54, not invented:
#   $702.49 published by our own pipeline on a contaminated base  -> MUST reject
#   $205    external frontier-model benchmark                     -> MUST pass
#   $280-310 a third model's argued range / our arm D $310        -> MUST pass
#   $171-181 our arm C                                            -> MUST pass
# ASYMMETRIC BY DESIGN. Sell-side targets skew optimistic and this book is structurally bearish
# (median MoS -51.8%), so being far BELOW analysts is ordinary and being far ABOVE them is the
# farfetched direction. A symmetric band would have rejected the $205 benchmark.
MOS_EXTREME = 1.50          # existing shared definition of "malfunction, not a valuation"
BAND_HIGH_MULT = 1.5        # above 1.5x the PV'd analyst HIGH -> farfetched ($702 is 1.63x)
BAND_LOW_DIV = 3.0          # below 1/3 of the PV'd analyst LOW -> farfetched (deliberately loose)
OCF_MULT_MAX = 40.0         # IV implying >40x TTM operating cash flow ($702 implies 46.3x)
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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "GOOG").upper()
    adaptive = "--samples" not in sys.argv
    n = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 3
    model = (sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv
             else "rs2-analyst-deep")
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
    # ctx 81920 VERIFIED 2026-08-21 on rs2-analyst-deep: 22.2 GB resident, fully on GPU,
    # no CPU spill. Do not raise further without re-probing /api/ps for spill.

    fin = rs2_data.load_json(common.SD / "financials" / f"{t}.json") or {}
    price = vb._num(fin.get("Price"))
    pack = cap.build_pack(t) + "\n\n---\n\n" + cap.TASK
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = OUT / f"{t}_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    # Save the exact pack. Without it a consensus run is not re-auditable from its own directory
    # — found when three auditors had to reconstruct it independently to check the reports.
    (d / "_pack.md").write_text(pack, encoding="utf-8")
    mode = (f"adaptive 2-escalate (early bar {EARLY_TOL_PCT:.0f}%, full {TOL_PCT:.0f}%)"
            if adaptive else f"{n} samples fixed")
    print(f"[consensus] {t} @ ${price} | model={model} | {mode} -> {d}", flush=True)

    use_tools = "--tools" in sys.argv
    if use_tools:
        import analyst_tools
        # The no-assumption rules only make sense when the model can actually look things up.
        pack += cap.RESEARCH_ADDENDUM
        (d / "_pack.md").write_text(pack, encoding="utf-8")
        print("  [tools ENABLED] search-during-reasoning rules appended; every query and page "
              "is snapshotted per sample", flush=True)

    runs = []
    n_max = 3 if adaptive else n
    for i in range(1, n_max + 1):
        t0 = time.time()
        resp, meta = {}, {}
        try:
            if use_tools:
                sd_i = d / f"sample{i}_research"
                rep, think, meta = analyst_tools.chat_with_tools(
                    model, pack, sd_i, think=think_level, ctx=ctx, num_predict=NUM_PREDICT,
                    seed=1000 + i)
                resp = {"done_reason": meta.get("done_reason"),
                        "eval_count": meta.get("generated_tokens")}
                msg = {}
            else:
                body = {"model": model, "stream": False, "think": think_level,
                        "messages": [{"role": "user", "content": pack}],
                        "options": {"num_ctx": ctx, "num_predict": NUM_PREDICT, "seed": 1000 + i}}
                import urllib.request
                req = urllib.request.Request("http://localhost:11434/api/chat",
                                             data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=14400) as r:
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
            req = urllib.request.Request("http://localhost:11434/api/chat",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=14400) as r:
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
                num_predict=NUM_PREDICT, seed=1000 + i + 50000)
            resp = {"done_reason": meta.get("done_reason"),
                    "eval_count": meta.get("generated_tokens")}
        (d / f"sample{i}.md").write_text(rep, encoding="utf-8")
        if think:
            (d / f"sample{i}_thinking.md").write_text(think, encoding="utf-8")
        truncated = resp.get("done_reason") == "length"
        # EXACT token accounting from the server, not char estimates — this is what settles
        # where a truncated run actually spent its budget.
        p_tok, g_tok = resp.get("prompt_eval_count"), resp.get("eval_count")
        ivs = extract_iv(rep, price)
        iv = st.median(ivs) if ivs else None
        ok, why, flags = plausibility(iv, price, t)
        runs.append({"sample": i, "iv": iv, "all_iv_mentions": sorted(set(ivs))[:8],
                     "plausible": ok, "reasons": why, "flags": flags, "truncated": truncated,
                     "done_reason": resp.get("done_reason"),
                     "prompt_tokens": p_tok, "generated_tokens": g_tok,
                     "thinking_chars": len(think), "report_chars": len(rep),
                     "thinking_share_of_output": (round(len(think) / (len(think) + len(rep)), 3)
                                                  if (think or rep) else None),
                     "chars": len(rep), "secs": round(time.time() - t0)})
        print(f"  sample {i}: IV ${iv if iv else '?'} | usable={ok}"
              + f" | gen {g_tok} tok (think {len(think):,}ch / report {len(rep):,}ch)"
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
                    break
                print(f"  [adaptive] 2-sample spread {sp2:.1f}% > {EARLY_TOL_PCT:.0f}% — "
                      f"escalating to 3rd sample", flush=True)
            else:
                print(f"  [adaptive] only {len(g2)} usable of 2 — escalating to 3rd sample",
                      flush=True)

    good = [r for r in runs if r["iv"] and r["plausible"] and not r["truncated"]]
    ivs = [r["iv"] for r in good]
    spread = (max(ivs) / min(ivs) - 1) * 100 if len(ivs) >= 2 else None
    early_stop = adaptive and len(runs) == 2 and len(good) == 2
    # An early-stopped pair must meet the bar it stopped under; a 3-sample set (or a fixed-n
    # run) is judged at the standard tolerance.
    eff_tol = EARLY_TOL_PCT if early_stop else TOL_PCT
    converged = bool(spread is not None and spread <= eff_tol)
    med = st.median(ivs) if ivs else None
    # This string is THIS TOOL's own summary of convergence. It is NOT the published verdict —
    # depth_pipeline.band_verdict() decides direction and ignores it. Reworded 2026-08-24 because
    # the old third branch read "no plausible sample" and fired whenever spread was undefined,
    # which on a single-sample run libelled a perfectly good sample as implausible.
    verdict = ("CONVERGED" if converged and med else
               "NOT CONVERGED — runs disagree beyond tolerance" if med and spread is not None else
               f"NOT CONVERGED — only {len(good)} usable sample(s), spread undefined" if med else
               "NO USABLE SAMPLE — nothing parseable and complete")
    doc = {"ticker": t, "price": price, "model": model, "think": think_level,
           "pack_revision": cap.PACK_REVISION,
           "mode": ("adaptive" if adaptive else f"fixed_{n}"),
           "samples_run": len(runs), "early_stop": early_stop,
           "effective_tolerance_pct": eff_tol,
           "generated_at": datetime.now(timezone.utc).isoformat(),
           "runs": runs, "n_plausible": len(good),
           "median_iv": med, "spread_pct": round(spread, 1) if spread is not None else None,
           "tolerance_pct": TOL_PCT, "early_tolerance_pct": EARLY_TOL_PCT,
           "converged": converged, "verdict": verdict,
           "median_mos_pct": round((med / price - 1) * 100, 1) if med and price else None}
    (d / "consensus.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"\n[consensus] {verdict}")
    if med:
        print(f"  median IV ${med:,.2f} vs price ${price:,.2f} -> MoS {doc['median_mos_pct']:+.1f}%"
              + (f" | spread {spread:.1f}% (tolerance {TOL_PCT}%)" if spread is not None else ""))
    print(f"  -> {d/'consensus.json'}")


if __name__ == "__main__":
    main()
