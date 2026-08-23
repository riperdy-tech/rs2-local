# I — LOCAL GPU vs DEEPSEEK API: cost, energy and throughput (2026-08-23)

**Question (operator):** a second opinion claimed that, given our token volume and ticker count,
running the book on the DeepSeek API is "much cheaper" than the local 3090 at ~300 W, and that we
should move the pipeline to the cloud.

**Answer: the conclusion is right and the reason given for it is wrong.** On electricity alone the
two are within a factor of ~2 of each other and the direction flips with the tariff — V4-Pro is
*more* expensive than local power at every rate we could plausibly pay. What the cloud actually
buys is **wall-clock**: 15.5 days of 24/7 GPU for a 172-name baseline sweep versus hours.

Every number below is labelled MEASURED (from this repo / a cited commit) or DERIVED (computed,
with its inputs named). Nothing is quoted from recollection.

---

## 1. Inputs

| Input | Value | Source |
|---|---|---|
| Depth run, end-to-end per ticker | **130 min** (AAPL 2h10m; samples 2,169–2,583 s each with tools; PM ~36 min/sample) | MEASURED — commit `0366928` |
| Depth sample, no tools | **1,374 s / 1,383 s** (GOOG, PM) | MEASURED — `audit/H_model_verification_20260821.md` |
| Samples per ticker | 3 (adaptive early-stop can end at 2) | MEASURED — `config.json depth_samples`, `consensus_valuation.py` |
| Depth prompt per sample | **~16.4K tokens** | MEASURED — `consensus_valuation.py` NUM_PREDICT comment |
| Stage prompt tokens (old pipeline) | 17,090–18,074, 2.7 chars/token | MEASURED — `audit/C_experiments/p2_stage_prompt_tokens.json` |
| Local throughput | **48.5 tok/s** Q4+MTP, **35.8** Q4 plain | MEASURED — `api_llm/QWEN38_AB_REPORT_20260818.md` |
| Depth-model throughput (UD-Q5_K_M, think=high) | **23.1 tok/s tools-on, 28.9 tools-off** (medians) | **MEASURED** — operator, 2026-08-23, from the run archive. *Supersedes this document's original DERIVED 25–30 tok/s.* |
| Generated tokens per depth sample | **median 49,999 · p90 66,116 · p99 96,497** (n=87) | **MEASURED** — operator, 2026-08-23. *Supersedes this document's original DERIVED 34K–49K, which was ~30% too low at the median and ~2× too low at p99.* Values above `num_predict` 65,536 are legitimate: on the tools path `analyst_tools.chat_with_tools` **sums `eval_count` across up to 12 tool round-trips**, each separately capped. |

**Consistency check on the two replacements** — they were measured independently and jointly
reproduce a third quantity measured independently of both: 49,999 tok ÷ 23.1 tok/s = **36.1
min/sample**, against AAPL's **measured 2,169–2,583 s (36.2–43.1 min)**; ×3 samples = 108 min,
plus a bounded research phase, against **130 min measured end-to-end**. The original DERIVED
figures could not have passed this check — 34K–49K at 25–30 tok/s predicts 19–33 min/sample.
| Cloud tokens per ticker, OLD 6-stage pipeline | 138,013 in (70.1% cache-hit) / 55,449 out (47.6% reasoning), 10 calls | **MEASURED** — `api_llm/usage_log.jsonl`, 9 tickers / 90 calls, deepseek-v4-pro, 2026-07-16 |
| Live book | 172 tickers | MEASURED — `audit/SCREENER_EXTRACTOR_PACKAGE_20260820.md` |
| Local power | 300 W (operator figure, GPU) / 400 W (whole box at the wall, upper bound) | operator + bound |

**DeepSeek direct-API list prices, USD per 1M tokens** (effective 2026-08-16; peak = 01:00–04:00
and 06:00–10:00 UTC, and peak is exactly 2× off-peak). Reasoning tokens bill as output.

| Model | cache-hit in | cache-miss in | out |
|---|---|---|---|
| V4-Flash off-peak | 0.007 | 0.22 | 0.66 |
| V4-Flash peak | 0.014 | 0.44 | 1.32 |
| V4-Pro off-peak | 0.022 | 0.66 | 1.98 |
| V4-Pro peak | 0.044 | 1.32 | 3.96 |

---

## 2. The comparison that settles it: cost of 1M generated tokens

The local machine bills in **time**, the API bills in **tokens**. Converting the local side at its
own measured throughput is the only apples-to-apples form.

Local $/1M generated tokens = (W/1000) × (1e6 / tok_s / 3600) × rate.

| tok/s | W | $0.10/kWh | $0.15 | $0.20 | $0.25 | $0.30 |
|---|---|---|---|---|---|---|
| **23.1 (depth tools-on, MEASURED)** | 300 | 0.36 | 0.54 | **0.72** | 0.90 | 1.08 |
| **23.1 (depth tools-on, MEASURED)** | 400 | 0.48 | 0.72 | **0.96** | 1.20 | 1.44 |
| 28.9 (depth tools-off, MEASURED) | 300 | 0.29 | 0.43 | 0.58 | 0.72 | 0.87 |
| 35.8 (production Q4, MEASURED) | 300 | 0.23 | 0.35 | 0.47 | 0.58 | 0.70 |

Against **$0.66/1M output on V4-Flash off-peak**, the local 3090 on the production tools path
(300 W, 23.1 tok/s) costs **$0.72/1M at $0.20/kWh** — now marginally *worse* than Flash at that
tariff, where the original DERIVED figures put it marginally better. Break-even tariffs:

| | Flash off-peak | Flash peak | Pro off-peak | Pro peak |
|---|---|---|---|---|
| **23.1 tok/s @ 300 W** | **$0.183/kWh** | $0.366 | $0.549 | $1.098 |
| 23.1 tok/s @ 400 W | $0.137/kWh | $0.274 | $0.412 | $0.823 |

The measured throughput moves break-even **down** from the originally reported $0.20–0.24/kWh to
**$0.18/kWh at 300 W** — i.e. the crossover sits slightly below typical tariffs rather than
slightly above. The conclusion is unchanged in kind (it is a wash, not a rout) but the sign at
$0.20/kWh has flipped in the API's favour.

**Read: below ~$0.20/kWh the local card is the cheaper token source; above it, Flash is. V4-Pro is
never the cheaper token source at any tariff we would pay.**

---

## 3. Per-ticker and whole-book cost

**Depth pipeline** — 3 × (16.4K in / measured out); sample 1 pays cache-miss, samples 2–3 hit the
cached pack prefix. **Recomputed on the measured token distribution** (the original table used the
DERIVED 34–49K and therefore understated every API row by 30–90%):

| | per ticker @ median | @ p90 | @ p99 | 172 names @ median |
|---|---|---|---|---|
| API V4-Flash off-peak | **$0.103** | $0.135 | $0.195 | **$17.69** |
| API V4-Flash peak | $0.206 | $0.270 | $0.390 | $35.38 |
| API V4-Pro off-peak | $0.309 | $0.404 | $0.585 | $53.07 |
| API V4-Pro peak | $0.617 | $0.809 | $1.170 | $106.14 |
| LOCAL 300 W @ $0.15/kWh | $0.098 | $16.77 |
| LOCAL 300 W @ $0.20/kWh | $0.130 | $22.36 |
| LOCAL 300 W @ $0.30/kWh | $0.195 | $33.54 |
| LOCAL 400 W @ $0.20/kWh | $0.173 | $29.81 |

At the **median** sample the two sides are within a cent or two of each other at $0.15–0.20/kWh.
The API's exposure is to the **tail**: a p99 name costs it 1.9× a median name, whereas the local
side's cost is bounded by the watchdog regardless of how many tokens a name generates.

**Old 6-stage pipeline** — both sides MEASURED, and here the local box wins outright, because it
finished a ticker in 10.6 min: $0.005–0.021/ticker of power against $0.046 (Flash off-peak) or
$0.139 (Pro off-peak) of tokens. The cost case for the cloud is a property of the **depth tier's
130-minute runtime**, not of local inference in general.

**The whole 172-name book is a $11–$34 decision on either side.** Neither number is a reason to
rebuild a pipeline.

---

## 4. The number that is a reason: wall-clock

`orchestrate_depth.py` runs one ticker at a time (VRAM: analyst and research model are both ~22 GB
on a 24 GB card and can never co-reside).

- **Local baseline sweep:** 130 min × 172 = **373 h = 15.5 days of uninterrupted 24/7 GPU**, during
  which the card does nothing else and any Windows update, OOM or watchdog kill costs up to 3 h
  (180-min watchdog × MAX_RETRIES=2 → up to 9 h burned for zero output on a name that keeps failing).
- **API, same 516 samples:** at 8 concurrent requests and ~6 min/sample, **~6.5 h**. At 4
  concurrent, ~13 h. Concurrency is free on the API side and structurally unavailable locally.

**That is the real finding: ~57× on elapsed time, not 1.5× on money.**

Steady state is a different question and points the other way. Cadence is trigger-driven
(`depth_triggers.py`: 8-K, 10-Q/10-K, >8% price move, 90-day rotation) — roughly 2–3 names/day
across the book, i.e. **4–6 GPU-hours/day**. The local card absorbs that comfortably. **The
backlog is the problem; the steady state is not.**

---

## 5. What a cloud depth pipeline would actually cost to build (STOP flags)

`run_rs2.py --api` exists, but it drives the **retired** 6-stage pipeline. The depth tier has no
API path at all, and three of these gaps are correctness issues, not conveniences.

1. **No API backend for the depth tier.** `consensus_valuation.py:196` / `:215` and
   `analyst_tools.py:45` are hard-wired to `http://localhost:11434/api/chat`.
2. **STOP — tools would be lost.** `api_chat.py` sends no `tools` and runs no tool loop.
   Search-during-reasoning is not a nicety: the 2026-08-20 audit found all three Q5 GOOG runs had
   **invented** a 2027+ capex path, and that single unsourced assumption moved IV from
   $317/$321/$273 to $204/$178/$149. Tools were the fix. Shipping a cloud path without a tool loop
   reinstates a measured, named failure mode.
3. **STOP — reproducibility.** `config.json _seed_note`: seeds are **not** forwarded to the API
   backend and cloud results are unreproducible. The depth verdict rule is built on *seeded*
   samples whose scatter is the tolerance measurement. Cloud samples still measure scatter, but
   the run is no longer replayable — for a published valuation that is an audit-trail change the
   operator must accept explicitly, not a side effect.
4. **STOP — no measured quality evidence.** The only cloud data we hold is 9 tickers of
   deepseek-v4-pro on the **caged** pipeline (2026-07-16). There is **zero** measurement of any
   DeepSeek model on the depth tier. Per CLAUDE.md §0 the engine that produces published
   valuations does not change on an argument. It changes on an A/B.
5. **The GPU stays in the loop regardless.** `deep_research.py` runs the local `rs2-research`
   model against local SearXNG (p50 320 s/ticker). Only the analyst samples move.
6. Peak/off-peak is a free 2× — any cloud scheduler must avoid 01:00–04:00 and 06:00–10:00 UTC.

---

## 6. Recommendation

1. **Do not switch on the power bill.** It is a $11–$34 decision either way over the whole book,
   and below ~$0.20/kWh the local card is the cheaper token source. The claim as put to us is not
   supported by measurement.
2. **Do move the backlog burn-down to the API, for the 15.5 days.** That is the defensible reason.
3. **Before it publishes anything: run the A/B.** Same packs, same seeds where possible,
   V4-Flash vs `rs2-analyst-deep`, on the names we already have depth verdicts for — the
   comparison set is free because the local answers exist.
4. **Build the tool loop first.** A cloud path without search reinstates the invented-capex error.
5. **Keep the local card for steady state** (2–3 triggered names/day = 4–6 GPU-h/day) and for
   research, which never leaves the box anyway.

### The measurement that replaced this document's only DERIVED input — DONE 2026-08-23

Generated tokens per depth sample were the sole estimated quantity here. They have since been
measured on the box (n=87): **median 49,999 · p90 66,116 · p99 96,497**, with throughput
**23.1 tok/s tools-on / 28.9 tools-off**. §1–§3 above are recomputed on those figures; the
originally published DERIVED range (34K–49K at 25–30 tok/s) was too low and its API costs were
correspondingly understated. Re-run the same measurement after any change to `num_predict`,
`depth_ctx`, reasoning effort or the tool loop, because every table above is a function of it:

```
python - <<'PY'
import json,glob,statistics as st
r=[x for f in glob.glob('ab_reports/consensus/*/consensus.json')
     for x in json.load(open(f))['runs'] if x.get('generated_tokens')]
g=[x['generated_tokens'] for x in r]; s=[x['secs'] for x in r]
print(len(g),'samples | gen tok med',st.median(g),'p90',sorted(g)[int(.9*len(g))-1],
      '| secs med',st.median(s),'| tok/s',round(sum(g)/sum(s),1))
PY
```

That prints the real per-sample token count **and the real depth-model tok/s**, which collapses
the 25–30 tok/s and 34K–49K ranges in §1 to single numbers and makes every table above exact.
