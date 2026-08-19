# Phase F — Local-model configuration: what actually buys quality

**Date:** 2026-08-20 (overnight) · **Question asked:** "Qwen 3.8 is near Opus level — the problem
is how we configure and instruct our local model, not the model." · **Answer: correct.**

Four capability arms on GOOG, a 5-agent configuration sweep with adversarial review, and
independent verification of every load-bearing claim. Production pipeline untouched.

---

## 1. Headline

**The local model was never the bottleneck, and neither was quantization.**

Given honest data, freedom to own the analysis, thinking on and an adequate output budget, the
local model catches the exact contamination our pipeline published as a +97.4% margin of safety,
and builds a ten-year driver forecast. Our production pipeline, on the same data, published
**$702.49 / undervalued**. The gap is harness and instruction, not intelligence.

| Arm | Weights | Thinking | Sampling | Template / SYSTEM | Score | IV |
|---|---|---|---|---|---|---|
| A | Q4_K_M | `true` (=low) | 0.4/0.9 + penalties | production, 35,654 ch | 7/8 | $277 |
| B | Q4_K_M | `max` | 0.6/0.95, no penalties | production | **void** (truncated) | $262 |
| **C** | **UD-Q5_K_M** | `high` | 0.6/0.95, no penalties | deep, 20,847 ch | **8/8** | $171–181 |
| **D** | **Q4_K_M** | `high` | 0.6/0.95, no penalties | deep (byte-identical to C) | **8/8** | $310 |

Checkpoints: catches the one-off contamination · normalizes the base · builds a multi-year driver
path · handles the missing D&A honestly · uses true TTM capex · separates non-operating stakes ·
derives a discount rate · shows sensitivity/scenarios.

---

## 2. Your Q4-vs-Q5 question, answered cleanly

**Q5 bought nothing measurable.** Arms C and D differ *only* in weights — verified byte-identical
Modelfiles (0 differing non-FROM lines), same template, same system prompt, same sampling, same
`high` thinking, same 65,536 context, same 49,152 budget. **Both score 8/8.**

Their intrinsic values differ ($171–181 vs $310) but that is one unseeded draw each, and the
spread is itself the finding: **run-to-run variance in the headline number is large**, and we have
never measured it because RS2 has never sent a seed. Do not read Q4 vs Q5 from it in either
direction.

Practical consequence: the Q5 pull, the UD quant and the projector removal were not wasted (they
cost nothing and Q5 is marginally better on paper), but **they are not where the quality came
from**. Chasing quantization further is not worth GPU time until the noise floor is known.

### Retraction

The earlier "Q5 scored 8/8 vs Q4 7/8" reading is **withdrawn**. Arms A and C differed in *seven*
ways at once — quantization, thinking level, sampling, context, output budget, the CLIP projector,
and a 35,654- vs 20,847-character system prompt. No single-variable claim survives that. Arm D
exists precisely to fix it, and it shows the difference was not the weights.

Worse, arm A's system prompt **forbade** what the task demanded: production's SYSTEM contains
*"do NOT select an engine"*, ENGINE-OWNED FIELDS, CONSISTENT SIZING, ENGINE VERDICT and REGIME
JUDGMENT, while the task prompt said "YOU select the valuation engine, YOU compute intrinsic
value." Arm A was given contradictory instructions; arm C was not.

---

## 3. Thinking levels — you were right, and it is worse than a naming issue

Qwen3.8 sets reasoning effort through **text injected by the chat template**, validated against
`('xhigh','medium','low')` with `raise_exception` otherwise. Ollama's vocabulary is
`low/medium/high/max`. Consequences, all measured:

- On the correctly-templated model, **`think:"max"` returns HTTP 500** — it killed arm C's first
  attempt. `high` works and gives the deepest trace (3,166 chars), `true` 2,410, `medium` 1,948,
  `low` 1,833.
- On **production**, `think:true` produces the same trace length as `low` (1,837 vs 1,770 chars).
  My capability test ran at effectively the weakest setting — and still beat the pipeline.
- **Production's template is `TEMPLATE {{ .Prompt }}`** — no ChatML markers, no think block, and
  **no reasoning-effort line at all**. The mechanism Qwen uses to set reasoning depth is absent
  from production. (The RS2 framework does still reach the model — verified by recall test.)

---

## 4. The two findings that outrank everything above

### 4.1 The basis decision is run blind to cash flow

`run_rs2.py:939` — `if None not in (ni, da, cx)` — makes a missing D&A suppress net income, D&A,
capex, **operating cash flow and free cash flow together**. Fires on **22 of 88** names with
archived regime decisions.

This matters more than any sampling knob because published fair value is deterministic
(`run_rs2.py:1896`: "never a model number") and the report may not print a different one. So
`regime_decide` is the **only** LLM call that can move a published valuation — RS2's own comments
value it at ~80 points of margin of safety — and on a quarter of contested names it decides
"is the capex converting?" with capex, OCF and FCF withheld.

GOOG: all three samples voted `current_earnings`, citing the contaminated quarter itself, while
TTM net income $244.21B against OCF $185.68B sat unread in the same dictionary.

**P1 result:** see §6.

### 4.2 Truncated stages are published as successes

**Measured properly (P2 + log census), because my first estimate was wrong.** I initially
projected ~26,000-token stage prompts from a character ratio and claimed the input alone
overflowed. It does not, at the median. Asking the server instead:

- A synthetic late-stage prompt measures **17,090–18,074 tokens** — ~6,800 tokens of headroom.
- Across **921 real production requests** in the Ollama log: median **7,508**, p90 **20,182**,
  **max 24,851 — which exceeds `stage_ctx` 24,576**. **32 requests sit within 576 tokens of the
  wall.**

So it is the *tail*, not the typical call, that overflows — roughly 3.5% of requests — and that
tail is exactly where the 26 truncations come from.

**26 completions** in the Ollama log ended `truncated = 1` at exactly `n_tokens = 24575` — one
below `stage_ctx` — returning HTTP 200. **`done_reason` appears zero times in the codebase**;
`ollama_chat` only checks for *empty* content. An amputated stage clears the 400-character floor,
is carried forward and ships. Six are byte-identical retries failing at the identical token,
because the retry re-runs at the same context size.

This is not suboptimal. It is a quality failure the system reports as success.

---

## 5. Apply-now list (no GPU time, no judgment calls)

| Fix | File | Why |
|---|---|---|
| Un-gate the cash-flow block | `run_rs2.py:939` | print each available field independently |
| Print operating/pretax/tax + derived non-operating | `rs2_data.py` | **independently verified:** 124 of 244 live names (51%) carry \|non-op\| ≥10% of latest-FY pretax, 50 (20%) ≥25%; GOOG $29.79B = 18.8%. Fields already on disk, printed nowhere |
| `stage_ctx` 24576 → 49152 | `config.json` | prompts max 21,916 tokens leave 2,660 for generation |
| Hard-fail on `done_reason == "length"` | `run_rs2.py:218` | converts silent truncation into a loud failure |
| Escalate context on retry | `run_rs2.py:212` | 6 of 23 truncations are identical reruns into the same wall |
| `regime_decide` ctx 8192 → 16384 | `run_rs2.py:1033` | measured prompts 7,581–7,880 tokens = 4–8% headroom on the 80-point decision |
| Stage carry: head cut → tail-biased | `run_rs2.py:716` | `out[:cap]` discards conclusions; 35.5% of stage text dropped |
| `MIN_STAGE_CHARS` → structural gate | `run_rs2.py:1228` | an 873-char stub ending mid-sentence passes a floor sized for empty stubs |
| `repeat_penalty` 1.05 → 1.0 | `RS2-Analyst.Modelfile:35` | 64-token window = digits in numeric tables; Qwen specifies 1.0 |
| JSON repair at temp 0.0, full stage | `run_rs2.py:285` | it runs *because* parsing failed, then adds sampling variance; saw ~540 chars of a 5,986-token stage |
| Send and log a seed | `run_rs2.py:201` | every result to date is one unrepeatable draw |
| Move sampling out of Modelfiles | both Modelfiles | quantization is welded to temperature and penalties; every A/B inherits the confound |
| Drop `PARAMETER stop <think>` | deep Modelfile | `<think>` opens a block; inert only while the template pre-fills it |
| `api_chat.py:36` sends `RS2.txt` | `api_llm/api_chat.py` | every local-vs-cloud comparison used two different frameworks |

**Ahead of all of it — publishing integrity:** `reports/GOOG_20260814_002226/` still ships
`FINAL.md` arguing **$702.49 / undervalued** beside a `verdict.json` saying **$64.30 / overvalued**.
A repatch that moves `fair_value` must re-run `--refinal` or mark the prose stale.

---

## 6. P1 — un-gating the basis evidence: **REJECTED**, and it redirects the fix

29 contested names whose cash-flow block is gated off, paired old-pack vs un-gated-pack, 3 samples
each, nothing else changed. **3 of 29 majorities flipped — bidirectionally:**

| Ticker | old → new | direction |
|---|---|---|
| COHR | current_earnings → owner_earnings | toward the withheld evidence |
| KFY | current_earnings → owner_earnings | toward |
| **CASY** | **owner_earnings → current_earnings** | **against** |

The pre-registered rule (written before the run) rejects on bidirectional flips. **Rejected.**

**And the probe could not test its own motivating case.** GOOG's lattice contains exactly ONE cell
(`current_earnings`), so it failed the "≥2 cells = a real choice" filter and was excluded — as was
GOOGL. That is the actual finding: GOOG's failure was never a bad choice among alternatives, it
was that **the missing D&A collapsed the lattice to a single option**, making the vote a
three-sample ratification of the sole survivor. Extra evidence cannot help a decision with nothing
to switch to.

**Consequence — the fix moves from code to data.** Un-gating the evidence remains correct on
principle (withholding OCF/FCF from a question about cash conversion is indefensible) but is
**not demonstrated to change outcomes**. The **D&A backfill** is the intervention that matters: it
creates the alternative cells so a choice exists at all, *and* un-gates the evidence as a free
side effect. That promotes the screener-side backfill above every config change in §5.

Caveat carried into P3: 3 flips in 29 may be inside sampling noise, which had never been measured.

---

## 6b. P3 — the noise floor, and the finding that outranks P1

21 repeats of the **identical** prompt, nothing changed, on P1's three flippers. Any variation is
pure sampling noise. `decision instability` = how often production's own 3-sample majority rule
lands somewhere other than the modal answer:

| Ticker | vote split (21 runs) | 3-sample decision instability |
|---|---|---|
| COHR | 21 × current_earnings | **0.0%** (0 of 19 windows) |
| KFY | 19 current / 2 owner | 5.3% |
| **CASY** | **14 current / 7 owner** | **21.1%** (4 of 19 windows) |

**Production corroborates it.** Across **281 archived regime decisions, 28 (10.0%) were
non-unanimous.** ATAT appears four times with 2-1 splits resolving *differently* across runs —
`[current, midcycle, midcycle] → midcycle`, then `[current, midcycle, current] → current_earnings`,
then again `→ current_earnings`, then `[midcycle, current, midcycle] → midcycle`. Same company.
The published earnings basis — worth ~80 points of margin of safety — is decided by which way a
2-1 split happens to fall, and **nothing alarms on it.** DFIN shows the same pattern
(owner / current / owner across three runs).

**This re-reads P1.** The rejection turned on CASY — the single noisiest name of the three, at
21.1% instability. A 3-sample test cannot resolve a decision that unstable, so **P1 was
underpowered by construction.** I honour the pre-registered verdict — un-gating is *not
demonstrated* — but the design, not the hypothesis, is what failed.

The one clean signal points the other way: **COHR is perfectly stable on the old pack (21/21,
0 of 19 windows differ) yet flipped to `owner_earnings` under the un-gated pack.** A flip on a
deterministic name is very unlikely to be noise. That is suggestive, not proof, and it is the only
part of P1 worth building on.

**Standing constraint for all future work:** no A/B of the basis decision at 3 samples can
attribute anything on an unstable name. Either raise samples until the majority is stable, or
measure instability first and exclude the unstable names. The same applies to every capability arm
in §1 — which is why arms C and D landing at $171–181 and $310 on identical configs is expected,
not anomalous.

---

## 7. Settings versus data

No setting reaches these:

- **D&A null for 31% of the book** (42 of 290 fully, 48 partially) — but **recoverable**: SEC
  companyfacts carry the whole tag family and a backfill rescues 445 year-cells, which also
  un-gates §4.1 for those names as a side effect. This is the highest-value data job.
- **Segment revenue and margin: hard stop.** SEC companyfacts carry no dimensional facts —
  sampling 2,651 rows across 80 GOOG tags, the key universe has no axis or member. Building
  segments on a call-transcript narrative would substitute a weaker method, which is why
  ENGINE 3 was retired.
- **Quarterly OCF and capex** — the most direct one-off detector — ingested nowhere.
- **Marketable securities / investment holdings** — never ingested, so the $94B SpaceX
  double-count is invisible in both directions.
- **`GOOG` FY2022 revenue** is `null` in `fundamentals_history.json` while `financials/GOOG.json`
  carries $282.836B. Two files disagree; the pipeline reads the empty one.

---

## 8. What n=1 cannot tell you

At 15–25 minutes per run, a single comparison cannot separate a real effect from run-to-run
variance — and that variance has never been measured, because no seed has ever been sent. Arms C
and D landing at $171–181 and $310 on identical configurations except weights is the clearest
possible demonstration.

So: temperature, top_p, presence penalty and KV cache type should **not** be A/B-ed yet. The
exception is anything deterministic — context-wall truncation, code gates, template validation —
which is confirmable with one run or none. Fix what is provable offline, buy the noise floor with
60 short calls, then compare knobs.

---

*Four capability arms, one 8-agent sweep, adversarial review. Production pipeline unmodified;
all experimental output isolated under `ab_reports/`.*
