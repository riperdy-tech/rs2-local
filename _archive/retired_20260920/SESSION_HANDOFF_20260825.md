# Session handoff — 2026-08-24/25: the cloud arm, from probe to published book

Session ran ~13:00 on 2026-08-24 through ~10:30 on 2026-08-25. It started as "can DeepSeek run a
sample ticker" and ended with 131 cloud verdicts live on stockpeak.net.

**Standing constraint set by the operator during this session, and honoured throughout: NEVER
modify the local RS2 AI engine.** `run_rs2.py`, `depth_pipeline.py`,
`tools/audit_202608/consensus_valuation.py`, `analyst_tools.py`, `capability_test.py` and every
Modelfile are set in stone. Everything built here is additive, lives in `api_llm/`, and imports
the engine read-only.

---

## 1. What was built

| File | Purpose |
|---|---|
| `api_llm/deep_api_run.py` | Depth-tier analysis on a cloud model. `--dir` replays a finished local run's frozen pack (A/B); `--fresh` builds the pack from current data (standby path); `--model` selects the model. |
| `api_llm/deep_api_batch.sh` | Batch driver. `bash api_llm/deep_api_batch.sh QUEUE_FILE [CONCURRENCY]`. |
| `api_llm/rederive_cloud.py` | Re-judges finished cloud runs under the current guard. No API calls. Writes `consensus_rederived.json` / `verdict_rederived.json` beside the originals; never overwrites them. |
| `api_llm/publish_cloud_verdicts.py` | Appends cloud verdicts to the shared ledger, writes report bundles, rebuilds the overlay, and (`--push`) pushes to the screener repo. |
| `api_llm/DEEPSEEK_V4_FLASH_AB_20260824.md` | The 28-ticker A/B write-up. |

Commit `ea35782` (2026-08-24 19:23) pushed the runner, batch driver, README section and
`.gitignore` entries. `rederive_cloud.py` and `publish_cloud_verdicts.py` are **not yet
committed** — see open items.

---

## 2. DeepSeek API facts, verified against the docs and probed live

Checked at api-docs.deepseek.com on 2026-08-24, then confirmed by direct probes:

- **Thinking mode ignores `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`.** No
  error, no effect. Porting Qwen's 0.6 / 0.95 / 20 thinking profile would have been a silent
  no-op dressed up as a mirror. The cloud arm therefore sends **no sampler parameters at all**.
- **`seed` and `top_k` are undocumented.** Not sent. Local seeds 1000+i; the cloud draws are
  independent. **Cloud `spread_pct` is therefore not comparable like-for-like with local's.**
- **`reasoning_effort`**: `low` / `high` / `max`; `medium` and `xhigh` both collapse to `high`;
  default `high`. Qwen's `high` maps through its own template to `xhigh`, Qwen's ceiling —
  DeepSeek has a further `max` above `high`. Comparable in intent only. Operator chose `high`.
- **With tools in play, `reasoning_content` must be echoed back on every subsequent request** or
  the API returns 400. Ollama has no such rule. This is the one non-obvious transport
  requirement; `chat_with_tools_api` does it unconditionally.
- **Limits**: 1M context, 384K max output, 2,500 concurrent connections for flash (500 for pro).
  Concurrency, not RPM, is the limit; excess returns 429.
- **Pricing per 1M** (peak / off-peak, off-peak is half; peak = 01:00–04:00 and 06:00–10:00 UTC
  Mon–Fri): flash $0.44/$0.22 miss-in, $0.014/$0.007 cache-hit, $1.32/$0.66 out. Pro is exactly
  3× flash.

---

## 3. Measurements

### 3.1 The 28-ticker A/B (flash vs local Qwen deep, byte-identical frozen packs)

- **Direction agreement 22/28 = 79%.** Six disagreements: ABNB, ADSK, AMZN, CLS, EXEL, JKHY.
  ADSK is the only full reversal (undervalued vs overvalued).
- **Tool usage is a near-exact mirror: 1,155 cloud calls vs 1,164 local**, unprompted.
- **Speed 5.7×**: 50.1h of local sample time vs 8.8h cloud. Cost $4.98.
- Cloud median IV below local on 17/28 — near a coin flip. An early "flash values lower"
  impression from n=2 did **not** survive the full set.

### 3.2 The self-agreement experiment (the one that settles it)

Ran flash a **second time** over the same 28 frozen packs, then re-judged run #1 under the new
guard so both runs faced the same judge.

| Comparison | Agreement |
|---|---|
| flash run #1 vs flash run #2 (same model, same pack, same guard) | **23/28 = 82%** |
| flash run #1 vs local Qwen | 22/28 = 79% |
| flash run #2 vs local Qwen | 21/28 = 75% |

**Flash agrees with Qwen (75–79%) about as often as it agrees with itself (82%).** The gap is one
to two tickers at n=28. Most of the apparent cross-model disagreement was run-to-run variance,
not a model difference.

Splitting it:

- **19/28 (68%)** agree with Qwen in both runs.
- **4/28 (14%)** disagree with Qwen in both runs — **ADSK, AMZN, EXEL, JKHY**. These are the real,
  repeatable model differences and are worth a human look.
- **5/28 (18%)** flash flips against itself — ABNB, CLS, EMBJ, GMED, INCY.

**The sharpest finding: all five self-flips were `hold` in run #1 and a directional call in run
#2. Not one directional-to-directional flip in 28 names.** `hold` is not a stable verdict — it is
where you land when the band happens to straddle the price. This is structural in the
band-direction rule and applies to the local arm too. A single run's `hold` is much weaker
evidence than a single run's directional call.

Caveat: run #2 ran 7 hours later. Packs were byte-identical but the models' own web searches hit
live pages that had moved on, and median spread rose 28.4% → 34.5%. So this measures variance
under production conditions (sampling *plus* web drift), not pure sampling noise.

### 3.3 Guard redesign, applied to the cloud arm

The 28-ticker sweep was judged by the pre-redesign guard (delete the sample). Re-judging under the
current guard (annotate, keep) restored **7 samples** and moved spreads materially: CIEN
9.2% → 85.7%, CART 11.6% → 55.8%, AVGO 1.4% → 21.2%, AMD unmeasurable → 99.3%.

**Zero direction changes across the 28.** But the convergence claim collapsed:

| | Old guard | New guard |
|---|---|---|
| Cloud converged | 14/28 | **11/28** |
| Local converged | 10/28 | 10/28 |

So "cloud converges more often" was mostly an artefact of the old guard deleting inconvenient
samples. The honest figure is a tie.

### 3.4 pro vs flash, identical pack (NVDA, `--fresh`, pack revision 2, same guard, same hour)

| | flash | pro |
|---|---|---|
| Verdict | HOLD | **OVERVALUED** |
| Band | $147.00–$301.79 | $89.53–$144.00 |
| Median IV | $186.00 (MoS −13.4%) | $125.00 (MoS −41.8%) |
| Spread | 105.3% | **60.8%** |
| Tool calls | 40 | 39 |
| Reasoning share of output | 70% | **89%** |
| Report length, 3 samples | 83,992 ch | 40,522 ch |
| Wall time | 14.3 min | 35.5 min |
| Cost | **$0.091** | $0.345 |

On this one name pro was the better analyst: unanimous direction, tighter band, all draws below
price. It bought that with more thinking and less writing. **n=1, and NVDA is a hard name.**

Against that: Artificial Analysis Intelligence Index puts **pro at 53 and flash at 52** — one
point, at 3× the price.

Also observed here: flash's sample 1 carried `ocf_multiple_58.2x_cap_40x`. Under the **old** guard
that sample would have been deleted, leaving $147–$186 and a verdict of **OVERVALUED**. Under the
new guard it is kept, the band widens to $301.79, and the verdict becomes **HOLD**. A live example
of the guard redesign changing a direction.

### 3.5 Model survey (reasoning capability vs cost per ticker)

Costs projected onto the measured per-ticker profile (339,614 in — 249,207 cacheable — 125,905
out), with output scaled by each model's Artificial Analysis eval verbosity.

| Model | AA Index | $/ticker (adj) | Max output | Note |
|---|---|---|---|---|
| Gemini 3.7 Flash (high) | **56** | $0.319 | — | Highest reasoning under the ceiling; efficient (64M eval tokens). Promo price expires 31 Dec 2026. Not OpenAI-shaped. |
| DeepSeek V4 Pro | 53 | $0.629 | 384k | 1 index point over flash at 3× price. |
| GLM-5.2 | 53 | $1.072 | — | Over pro; GLM-4.6's 16,384 output cap would truncate our reports. |
| DeepSeek V4 Flash | 52 | $0.209 peak / **$0.105 off-peak** | 384k | Current arm. |
| GPT-5.6 Luna | 52 | $0.174 | 128k | Same index, flat pricing, but AA flags it "very verbose". |
| Qwen3.7 Plus | **39** | $0.223 | 131k | Same family as the local model — and the weakest reasoner here. Family resemblance is not capability. |
| Kimi K3 | 60 | $1.944 | 975k | Best available, but 3.09× pro — over the operator's ceiling. |

**Index per dollar, off-peak flash wins outright: 497 vs Luna 299, Gemini 176, pro 169.**
DeepSeek's time-of-day halving is unique among these; the scheduling decision (run outside
01:00–04:00 and 06:00–10:00 UTC) is worth more than the model decision.

Actual flash cost measured three ways: **$0.178/ticker as billed** across the mixed-hours sweep,
$0.209 pure peak, $0.105 pure off-peak.

---

## 4. The overnight fallback sweep

137 names in the live book had no depth verdict (book 171, local had 34).

- **batch 3**: 100 names (19 `research_now` first, then watchlist), concurrency 4
- **batch 4**: 37 names (31 with a research brief, 6 without), concurrency 3
- Both `--fresh`, pack revision 3, current guard. **137/137 completed, zero non-zero exits.**
- Finished ~10:20 on 2026-08-25 (projected 9am; contention with the concurrent local sweep cost
  about 80 minutes).

**Load safety, measured rather than assumed: 0 failures in 2,825 tool calls at 7 concurrent
streams** (no hard errors, no zero-result searches) with the local sweep running alongside.
SearXNG latency 1.2–4.0s at 4 streams, 2.2–4.0s at 7, HTTP 200 throughout. `limiter: false`, so
nothing throttles us; the real ceiling is the upstream engines SearXNG queries, shared with the
local sweep. **The failure mode to watch is silent**: `search_web` returns `{"error": ...}` *to
the model* rather than failing the run, so overload produces worse analysis, not visible errors.
The tripwire is the `n_results == 0` rate.

Quality of the 137: all ran 3 samples, **0 truncated, 0 NOT_USABLE**, n_basis 3 on 129 and 2 on 8.
Median spread 38.5% (49 converge inside the 25% tolerance), median MoS −21%, 34 flagged samples.

---

## 5. Publication (operator decision: option A)

The operator chose **option A — same ledger, same overlay, `arm: cloud_api` stamped, pushed like
local** — over the alternative of a parallel cloud ledger.

**The accepted cost of that choice**: `depth_triggers` treats a name with a verdict as no longer
BASELINE work, so publishing stops the local sweep from queueing these 137 names. They return to
the local arm only on an 8-K, a 10-Q/10-K, an 8% move, a `PACK_REVISION` bump, or the 90-day
rotation.

Published: **131 verdicts** (hold 36, overvalued 78, undervalued 17). Excluded by design:

- replay runs (they would overwrite local verdicts for names local already did)
- `deepseek-v4-pro` (validated on one ticker, not 28)
- NVDA (a test run, not in the live book)
- the six no-brief names — **AWI, CTAS, IEX, KOF, LITE, MOG-A** — a pack with no SECTION 11 at all
  is a different animal from one with a stale brief

Overlay now 165 tickers: 131 cloud + **all 34 local preserved**. Backup of the pre-publish ledger
at `cache/depth_ledger.jsonl.bak_before_cloud`.

Note the pack-revision inversion: **all 131 cloud verdicts are at revision 3 (current), while 31
of the 34 local verdicts are still at revision 1** and already queued for re-run by the trigger.
The cloud rows are on fresher pack data than most of the local ones they joined.

`build_report_bundles()` reads `ab_reports/consensus/{dir}`, which cloud runs do not have — it
would have skipped every cloud ticker and left verdicts with no reports behind them. So
`publish_cloud_verdicts.py` writes those bundles itself, in the same schema.

---

## 6. Real-world check on stockpeak.net

Verified live after the push:

- `stockpeak.net/data/depth_overlay.json` serves **165 tickers**, `generated_at` 2026-08-25T10:24,
  with `arm: "cloud_api"` on the 131 new rows.
- `stockpeak.net/data/depth_reports/MCO.json` serves the verdict plus all three full sample
  reports with substantive DCF prose.
- Front-page banner picked up the count: "DEPTH RUN 2026-08-25 · 3 SEEDED RUNS PER STOCK · 165
  ANALYZED".
- All 17 cloud `undervalued` names render as buy candidates: ATAT, BLBD, BWMX, CAH, CHE, CRM,
  DCBO, INTU, LAUR, NICE, PAYC, RMD, RNG, SAP, SYK, UTHR, UVE.

**Two problems found on the live site — data is correct, the UI is not:**

1. **"3 SEEDED RUNS PER STOCK" is now false for 131 of 165 rows.** Hardcoded at
   `components/desk/Shell.tsx:79` and `lib/i18n.ts:222`. The local arm seeds (1000/1001/1002); the
   cloud arm sends no seed because DeepSeek does not document one. The site asserts
   reproducibility it does not have on 79% of its rows.
2. **A viewer cannot tell the arms apart.** The rendered page never mentions model, arm or brief
   age — `deepseek`, `qwen`, `cloud_api` appear nowhere in the text. A cloud verdict built on a
   14-day-old brief looks identical to a local one with a fresh brief. The provenance is all in
   the JSON (`arm`, `model`, `research_brief_age_days`, `pack_revision`); the UI just does not
   read those fields.

The site reads the overlay through `lib/data-service.ts:387` (and bundles at line 383) — an
earlier claim in-session that "no app code reads it" was wrong, and is corrected here.

---

## 7. Open items

1. **Fix the site copy.** Make the banner count-driven ("165 ANALYZED · 34 LOCAL / 131 CLOUD") and
   drop or condition the "SEEDED" claim. A per-card provenance chip is the fuller fix. Screener
   repo, not the RS2 engine — operator's call, nothing changed.
2. **Commit `rederive_cloud.py` and `publish_cloud_verdicts.py`** (plus the `--fresh`, `--model`
   and `pack_revision` additions to `deep_api_run.py`) — currently uncommitted in the working tree.
3. **The four stable disagreements — ADSK, AMZN, EXEL, JKHY —** survive re-running and are where
   the two models genuinely see the business differently. Worth a human read.
4. **Six no-brief names held back**: AWI, CTAS, IEX, KOF, LITE, MOG-A. Publish with
   `--include-no-brief` if wanted.
5. **Neither arm is graded against outcomes.** Everything above measures agreement and
   repeatability, not accuracy. Grading against realized prices is the only thing that settles
   which arm is right — especially on the four stable disagreements.
6. **`hold` is unstable on both arms.** Consider whether a single-run `hold` should be publishable
   at all, or whether it should require a second run to confirm.

---

## 8. Provenance stamps now carried by every cloud verdict

`arm: cloud_api`, `model`, `pack_source` (`fresh` | `replay`), `research_brief_age_days`,
`searxng_up`, `pack_revision`, `published_by`, `published_at`. These survive into the ledger line
and the overlay row, so the two arms stay separable for grading later.
