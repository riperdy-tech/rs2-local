# J — REASONING EFFORT AND SAMPLE COUNT: what is measured, what is not (2026-08-23)

**Operator questions.** (1) What do public Qwen3.8-27B benchmarks say about `high` vs `medium`
reasoning effort, on the kind of reasoning RS2 actually does — and is the quality worth the time?
(2) What else reduces depth-tier runtime, and specifically: what would 2 samples have decided
instead of 3?

**Short answers.** (1) **No public benchmark isolates medium vs xhigh on this model for anything
resembling our workload.** The one quantitative effort-ladder datapoint found is +0.43 on a 0–10
substance scale (agentic coding), against 0.18 run-to-run noise. That is not evidence for a
valuation engine, and per CLAUDE.md §0 the knob does not move on it. We own the harness that can
answer it in ~4 runs. (2) **The adaptive 2-escalate rule is already implemented and is being
switched off by its own caller** — and switching it on is not a free 33%, because a 2-sample band
is narrower than a 3-sample band *by construction*, which biases the direction verdict.

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

## 2. Sample count — the rule you asked for already exists, and is disabled

`consensus_valuation.py` implements **adaptive 2-escalate**: run 2 samples; if both are plausible,
complete, and agree within `EARLY_TOL_PCT` (15%), publish the median of 2 and skip the third.
Anything else buys the third opinion, judged at `TOL_PCT` (25%).

It activates only when `--samples` is **absent** (`adaptive = "--samples" not in sys.argv`).

**`depth_pipeline.run_consensus` passes `--samples 3` on every ticker.** Production has therefore
never early-stopped. Removing those two argv entries turns the feature on.

### Why that is not a free 33%

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

**Decide the bar from that table.** If direction flips are ~0 at the 15% bar, take the saving. If
they are not, the options are: keep 3 samples; or early-stop but widen the 2-sample band by the
range ratio (~1.5×) before applying the direction rule, so 2-sample and 3-sample bands are
comparable — a methodology change requiring operator approval, not a tuning knob.

One archived case is on record here already: **GOOG (`H_model_verification`) would NOT have
early-stopped** — sample 2 hit the `num_predict` cap and was flagged truncated, leaving one usable
sample of the first two, which forces escalation. Truncation is itself an escalation trigger.

---

## 3. The other time levers, ranked by evidence

| # | Lever | Measured basis | Est. saving | Status |
|---|---|---|---|---|
| 1 | **Turn on adaptive early-stop** (drop `--samples 3`) | Feature exists, tested | ≤33% of analyst time | **Blocked on the band-narrowing measurement above** |
| 2 | **`xhigh` → `medium`** | None for this task | 3.5× is the high-vs-off gap; medium is between | **Blocked on the 4-run experiment in §1** |
| 3 | **MTP speculative decoding on the depth model** | Production analyst: **48.5 vs 35.8 tok/s (+35%)** from the MTP tag. `rs2-analyst-deep` is a raw UD-Q5_K_M blob with **no MTP head**. `F_config_findings`: Q5 vs Q4 quality was a wash (8/8 both) | ~+35% throughput | **CONTRADICTED**: `SESSION_SUMMARY` records "Q4 truncates, Q5 does not — 4/6 vs 0/6 on the depth tier" — at the OLD 49,152 budget. Must be re-tested at ctx 81,920 / num_predict 65,536 before it is believed in either direction. |
| 4 | **The empty-report pathology** | ANET s2: 118K chars of thinking, `done_reason=stop`, **zero report**. `4520df6` now retries once with a perturbed seed | Up to ~80 min per occurrence | Abort a sample once thinking passes a token bound with no report started, rather than paying for the full budget then retrying. Frequency is unmeasured — count `thinking_share_of_output` across the archive. |
| 5 | **`depth_ctx` 81,920** | Sized as prompt 16.4K + `num_predict` 65,536. Resident 22.2 GB. If real generation is 34–49K, the window is oversized and the KV cache is paying for it | Unquantified | Free to measure: `generated_tokens` p99 across the archive sets the honest ceiling. |
| 6 | **Tools** | With tools 36–43 min/sample; without, 1,374 s (23 min) | ~-40% if removed | **DO NOT REMOVE.** Tools fixed the invented-capex error that moved GOOG $317/$321/$273 → $204/$178/$149. Bound per-fetch latency instead (`MAX_TOOL_CALLS` is 12 and fetches are serial). |

**Ordering:** #1 and #2 are the only two large levers, both are gated on a cheap measurement, and
neither should move before its measurement exists. #3 is the one that looks free and is not.
