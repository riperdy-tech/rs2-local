# J — REASONING EFFORT AND SAMPLE COUNT: what is measured, what is not (2026-08-23)

**Operator questions.** (1) What do public Qwen3.8-27B benchmarks say about `high` vs `medium`
reasoning effort, on the kind of reasoning RS2 actually does — and is the quality worth the time?
(2) What else reduces depth-tier runtime, and specifically: what would 2 samples have decided
instead of 3?

**Short answers.** (1) **No public benchmark isolates medium vs xhigh on this model for anything
resembling our workload.** The one quantitative effort-ladder datapoint found is +0.43 on a 0–10
substance scale (agentic coding), against 0.18 run-to-run noise. That is not evidence for a
valuation engine, and per CLAUDE.md §0 the knob does not move on it. We own the harness that can
answer it in ~4 runs. (2) **3 flat is a deliberate operator decision, not an oversight** — the adaptive 2-escalate rule
exists and is bypassed because the operator chose 3 after weighing it. That decision now has a
second, stronger justification it did not have at the time: a 2-sample band is narrower than a
3-sample band *by construction*, so early-stopping biases the published direction verdict.

---

## 1. Reasoning effort — what the public record actually contains

### The ladder, corrected

Qwen3.8-27B exposes **off / low / medium / xhigh**. There is no distinct "high" tier: Ollama's
`high` maps to the template's `xhigh`, which is the maximum and the model's **default**. This
matches what `ba1b61d` and `F_config_findings` measured locally (`max` raises HTTP 500;
`high` → `xhigh`). **`medium` injects no instruction at all** — it is the neutral baseline;
`xhigh` injects explicit "check your assumptions and alternatives" text; `low` asks for brevity.

Our depth tier calls `high`, i.e. **`xhigh`, i.e. the most expensive setting the model has.**

### What is published

| Source | Finding | Relevance to RS2 |
|---|---|---|
| Artificial Analysis | Qwen3.8-27B **(xhigh)** = 52 Intelligence Index; GPQA-Diamond 89.2, LiveCodeBench v6 90.3, HLE 30.8 | **Only the xhigh variant is benchmarked.** No medium row exists to compare against. |
| Kodesage review | **medium → xhigh = +0.43 substance** (mean of accuracy + completeness, 0–10) vs **0.18 estimated noise**; medium was fastest and second-best overall; **low is both slower AND worse than medium** (more agentic rounds) | Closest thing to an effort ladder in public. Agentic coding, not valuation. |
| Willison / implicator | xhigh default adds **3–10× latency and tokens**; one SVG task: **22,276 reasoning tokens / 21 min at xhigh vs 3,715 tokens / 137 s with reasoning off** | Confirms the cost side. The comparison is xhigh-vs-**off**, not xhigh-vs-medium. |
| ReasonIF (2026) and related | Reasoning-oriented scaling **degrades instruction adherence**; failures are "especially stark for formatting-sensitive tasks"; harder task → worse format compliance | **Directly corroborates our own measurement** (below). |

### What we measured ourselves, which outranks all of it

`api_llm/QWEN38_AB_REPORT_20260818.md`, high-effort arm, 4 tickers:

- **~36–41 min/name ≈ 3.5× think-off cost, with ZERO verdict-direction changes in 4/4 names.**
  Conviction moved at most 1 point, always downward.
- **Thinking correlated with format-contract violations**: MU failed 2-for-2 under thinking
  (low: truncated at SECTION 5; high: no `Action:` line + freeform self-audit) and 1-for-1 clean
  without. Think-off was the only arm with 8/9+ contract compliance.
- Higher effort cited *more numbers for the same judgments* — denser evidence, identical calls.

**Counter-evidence, and it is why this is not a recommendation:** that A/B ran the **retired caged
6-stage pipeline**. The depth tier is a different task, and `F_config_findings` scored arms C and D
**8/8 at `high`** on the eight capability checkpoints. Nobody has ever run the depth tier at
`medium`. The measurement that would settle it does not exist yet.

### The experiment that settles it — 4 runs, ~2 hours, harness already built

`capability_test.py` already accepts `--think medium`, and `grade_capability.py` already scores
arms against the eight objective checkpoints that arms C/D scored 8/8 on at `high`.

```
python tools/audit_202608/capability_test.py GOOG --think medium --label deep-medium
python tools/audit_202608/capability_test.py PM   --think medium --label deep-medium
python tools/audit_202608/grade_capability.py
```

Read: score out of 8, wall-clock, and (from `consensus.json`) generated tokens. **If medium holds
8/8 at materially less time, the knob moves. If it drops a checkpoint — especially the
contamination catch or the series-continuity catch — it does not.**

Note: `think` is **hard-coded** `"high"` in `consensus_valuation.py` (both the tools and non-tools
branches). Making the depth tier configurable is a `depth_think` config key and three lines.

---

## 2. Sample count — the rule exists, is deliberately bypassed, and the bias argues for that

`consensus_valuation.py` implements **adaptive 2-escalate**: run 2 samples; if both are plausible,
complete, and agree within `EARLY_TOL_PCT` (15%), publish the median of 2 and skip the third.
Anything else buys the third opinion, judged at `TOL_PCT` (25%).

It activates only when `--samples` is **absent** (`adaptive = "--samples" not in sys.argv`).

**`depth_pipeline.run_consensus` passes `--samples 3` on every ticker,** so production has never
early-stopped. **This is a deliberate operator choice, taken after 2-escalate was discussed and
weighed — not a misconfiguration**, and this document originally mis-framed it as one. Removing
those two argv entries would turn the feature on; §2 below is the argument for *not* doing so.

### Why that is not a free 33% — and why 3-flat was the right call

The verdict is **band direction**: price above the whole band → overvalued, below → undervalued,
inside → hold. The band is `[min(IV), max(IV)]` over usable samples.

**The expected range of n draws grows with n** — `consensus_valuation.py`'s own comment states it:
~1.1× the true scatter for two draws, ~1.7× for three. So a 2-sample band is roughly **⅓ narrower
than a 3-sample band on the same underlying distribution**, entirely mechanically. A narrower band
contains the price less often, so **early-stopping systematically converts `hold` verdicts into
directional buy/sell calls.** That is a bias in the published output, not sampling noise, and it is
not fixed by tightening the early bar (the bar gates on agreement; it does not widen the band).

Worked example, reproduced by the replay tool's own fixture: three draws `{95, 130, 120}` at price
100 → band 95–130 contains 100 → **hold**. The first two draws `{120, 130}` agree within 8.3%, so
they early-stop → band 120–130, price below it → **undervalued**. Same model, same draws, opposite
action, purely from sample count.

### The measurement, on data already paid for — `tools/audit_202608/sample_count_replay.py`

Every archived consensus run stored per-sample IV, plausibility, truncation and wall-clock, so this
costs **zero GPU-hours**:

```
python tools/audit_202608/sample_count_replay.py
```

It (1) replays the production band rule over the full sample set and **must reproduce every stored
`verdict_depth.json` exactly, refusing to print counterfactuals if it cannot**; (2) replays the
adaptive rule over samples 1–2 and diffs the DIRECTION; (3) sweeps the early bar from 5% to 25%,
reporting for each: how many tickers early-stop, how many flip direction, how many change size
hint, and GPU-hours saved; (4) names every flipped ticker.

**Decide the bar from that table** *if* the question is ever reopened. The prior is now 3-flat,
and the band-width bias is an affirmative reason for it rather than merely a cost accepted. Should
it be revisited, the only defensible way to early-stop is to widen the 2-sample band by the range
ratio (~1.5×) before applying the direction rule, so 2-sample and 3-sample bands are comparable —
a methodology change requiring operator approval, not a tuning knob.

One archived case is on record here already: **GOOG (`H_model_verification`) would NOT have
early-stopped** — sample 2 hit the `num_predict` cap and was flagged truncated, leaving one usable
sample of the first two, which forces escalation. Truncation is itself an escalation trigger.

---

## 3. The other time levers, ranked by evidence

| # | Lever | Measured basis | Est. saving | Status |
|---|---|---|---|---|
| 1 | **Turn on adaptive early-stop** (drop `--samples 3`) | Feature exists, tested | ≤33% of analyst time | **Blocked on the band-narrowing measurement above** |
| 2 | **`xhigh` → `medium`** | None for this task | 3.5× is the high-vs-off gap; medium is between | **Blocked on the 4-run experiment in §1** |
| 3 | **MTP speculative decoding on the depth model** | Production analyst: **48.5 vs 35.8 tok/s (+35%)** from the MTP tag. `rs2-analyst-deep` is a raw UD-Q5_K_M blob with **no MTP head**. `F_config_findings`: Q5 vs Q4 quality was a wash (8/8 both) | ~+35% throughput | **Open — re-test.** This row originally cited `SESSION_SUMMARY`'s "Q4 truncates 4/6, Q5 0/6" as a counter-finding; **that is stale.** It was measured at the old 49,152 budget, and the current regime (`num_predict` 65,536, ctx 81,920) truncates **7/93 = 7.5%** overall. The old finding no longer bounds the decision in either direction, so the re-test is the whole question, not a tiebreak. |
| 4 | **The empty-report pathology** | ANET s2: 118K chars of thinking, `done_reason=stop`, **zero report**. **MEASURED frequency 2/93 = 2.2%** | ~80 min per occurrence, ~2% of names | **Covered.** `4520df6`'s perturbed-seed retry handles it at this rate. Not worth a pre-emptive abort heuristic. |
| 5 | ~~**`depth_ctx` 81,920 is oversized**~~ | — | — | **RETRACTED — this claim was wrong.** It rested on this document's DERIVED 34–49K generation estimate. Measured: **median 49,999, p90 66,116, p99 96,497, and 46 of 87 samples exceeded the old 49,152 cap.** The window is being used heavily; cutting it would truncate roughly half the sweep. Not a lever — a trap. |
| 6 | **Tools** | **MEASURED 23.1 tok/s tools-on vs 28.9 tools-off** (−20% on rate, more on wall-clock since tools runs also generate more) | ~-20% rate if removed | **DO NOT REMOVE.** Tools fixed the invented-capex error that moved GOOG $317/$321/$273 → $204/$178/$149. Bound per-fetch latency instead (`MAX_TOOL_CALLS` is 12 and fetches are serial). |

**Ordering, revised after the 2026-08-23 measurements:** **#2 (`medium` vs `xhigh`) is the only
live, cheap, untested lever left.** #1 is settled — the operator chose 3 flat and the band-width
bias supports that choice. #3 is genuinely open rather than contradicted, but needs its own run.
#4 is covered at its measured rate. **#5 was wrong and is withdrawn.**

### Corrections log (2026-08-23)

Three claims in the first version of this document did not survive measurement, and one framing
was unfair:

1. **`depth_ctx` oversized — WRONG.** Retracted above. The generation window is heavily used.
2. **MTP blocked by a truncation counter-finding — STALE.** 4/6 vs 0/6 was the old budget; the
   current rate is 7/93. The re-test instinct was right; the cited evidence was out of date.
3. **Empty-report frequency "unmeasured" — now 2/93 (2.2%)**, and already covered by the shipped retry.
4. **"Switched off by its own caller" — unfair framing.** 3-flat was a deliberate, recorded
   operator decision.

All four traced to the same root cause: this document and `audit/I` both leaned on a DERIVED
generation estimate (34–49K/sample at 25–30 tok/s) instead of the exact per-sample counts that
`consensus.json` had been storing all along. The measured figures are median 49,999 at 23.1 tok/s.
**The estimate was never checked against wall-clock, which would have failed it immediately** —
34–49K at 25–30 tok/s predicts 19–33 min/sample against 36–43 min measured. Measure first.
