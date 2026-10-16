# Cross-check request 20: the revision-24 Muse pilot failed its reading rule. Why, and what to change before the next pilot?

Written 2026-10-16 by the coordinator. **This document is self-contained.** Where an answer would rest on code you cannot see, say so
rather than assume. Critique freely: the coordinator rules on each point, and the operator decides.

- **Code:** `github.com/riperdy-tech/rs2-local`, branch `review-2026-10/rev24-muse` (the pilot ran at `2b799bd`).
- **Records:** branch `docs/rev23-records`, folder `docs/rev23/`: `PILOT_R24_REPORT.md`, `phase4/REGISTRATION_rev24_pilot.md`,
  `phase4/PHASE_4_AMENDMENTS.md`, and cross-checks 18 and 19.

## 1. The system
- **A stock screener** nominates about 160 US stocks.
- **A local AI analyst** values each one and gives a verdict (undervalued, hold or overvalued), with a long memorandum and a structured
  contract.
- **Code does all the arithmetic** through a "desk" tool and applies the gates.
- **Real money will depend on the verdicts.** It is halted. Everything here is paper and test only.

## 2. The model and its settings (identical to the earlier Muse acceptance test, checked by hash before and after every run)
| Item | Setting |
|---|---|
| Analyst model | **Muse Glimmer 30B**, GGUF `UD-Q5_K_M` (sha256 `27c27bc0…`) |
| Speculative decoding | DFlash2 drafter, Q8_0 (`b13b6783…`), `--spec-type draft-dflash`, `--spec-draft-n-max 15` |
| Server | llama.cpp build b11272 (`llama-server`), command line pinned by sha256 (`87f5b578…`) |
| Hardware | one RTX 3090, 24 GB; 21,811 MiB in use once loaded; everything on the GPU (`-ngl 99`, `-ngld 99`) |
| Context window | 98,304 tokens (`-c 98304`); KV cache q8_0 (`-ctk q8_0 -ctv q8_0`); flash attention on |
| Sampling (fixed on the server) | temperature 1.0, top-p 0.95, top-k 64, min-p 0. Per-request sampling is stripped; only the seed and the output limit pass through |
| Reasoning | "Reasoning strength: xhigh" (the model's maximum), the first line of the pinned system prompt (`SYSTEM_muse_v33.txt`, `decd1a19…`, the charter v3.3). Reasoning is returned separately (`--reasoning-format deepseek`) |
| Output limit | 65,536 tokens a sample |
| Tools offered | `search_web` (local SearXNG), `fetch_page`, `run_financial_model` (the desk) |
| Budgets | 25 web searches and 5 desk runs; the 7th refused desk call closes the desk |
| Seeds | 2401 (first sample), 2402 (repeats); one sample a run |
| Observed per run | median 23,257 generated tokens (17,037–44,572); about 56 tokens/s; median 54,000 characters of reasoning; a memo of 6,000–16,000 characters; 2–7 desk calls; 0–19 searches; 7–17 minutes |

**Supporting models:**
- **Deep research,** one brief per name, frozen: a separate helper, Qwen3 14B on Ollama ("rs2-research", a 32,768 context), searching
  through local SearXNG with a 900 s bound.
- **Discovery** (the news of the last 90 days), one per name, frozen: run on Muse itself, with search and fetch only.

## 3. What the analyst receives (the "briefing", about 95–110 KB, roughly 25–28k tokens)
- **Price and macro:**
  - the price and share count;
  - macro: risk-free rate, a cost-of-equity anchor, regime probabilities, shocks, world news;
  - price momentum.
- **The company's own record:**
  - 10 years of filed financials and recent quarters;
  - the full latest earnings release;
  - **PRIMARY SOURCES**: the company's own SEC filings, verbatim, cited as `PRIMARY P#`.
- **Consensus:** EPS and revenue estimates, revisions, the high/low range.
- **Research and news:** the research brief, the discovery ("catalyst") brief and recent company news.
- **DEFAULTS:** filed facts and conventions the desk uses unless the analyst decides otherwise (the base cash flow, the cost-of-equity anchor,
  the share count, working-capital intensity, excess cash).
- **New in revision 24:**
  - **no long-run defaults.** The long-run margin, the growth of years 3–5, the fade length, terminal growth and the terminal return on new
    investment (RONIC) have no default;
  - **POPULATION RANGES** instead: how comparable companies actually evolved, measured point-in-time from SEC filings (vintages 2016–2025):
    - **the long-run margin**, an earnings-margin estimate translated from operating-margin tables, five years out, P10/P25/(P50)/P75/P90;
    - **years 3–10 growth**, by growth band, P25–P75;
    - **10-year revenue CAGR**;
    - **ROIC five years out**, as context for RONIC;
  - **consensus years 1–2 printed as evidence:** "what analysts forecast; evidence, not a value the desk holds."
- **The TASK** (instructions) asks, in order:
  1. state near-term earnings, **normalized mid-cycle earnings**, and the transition between them;
  2. classify margin persistence (structural / partly / transient), cycle position (trough / mid / peak / not cyclical) and growth trajectory
     (accelerating / steady / decelerating / shrinking), each from its own evidence;
  3. choose each long-run input with the ranges "as context, not a target";
  4. cite at three levels:
     - in range, a rationale;
     - outside P10–P90, a sourced causal explanation;
     - the buy/sell "crux", verified primary-source quotes.

## 4. The desk (the arithmetic) and the gates
- **Years 1–5:** the base cash flow grown by the analyst's five growth rates, less working capital, which follows the scenario's own
  revenue path, normalized at the base.
- **Years 6 to 5+F** (F = the fade): growth fades linearly to terminal growth. The earnings margin moves proportionally from the year-5
  margin to the analyst's `long_run_margin`. Growth is paid for at a reinvestment of `g / RONIC`, with RONIC fading from the record's
  return to the analyst's terminal RONIC.
- **Terminal value:** Gordon growth on funded earnings, `TV = E(1+g)(1 − g/RONIC)/(r − g)`.
- **Corrected after cross-check 19:**
  - a RONIC below the discount rate is now valued as stated. It used to be raised to the rate silently, which priced value-destroying growth
    as neutral;
  - working capital is now normalized at the base, so a lower normalized base no longer creates a fake release of cash.
- **The plausibility gate** (rejects only):
  - terminal growth at or above the discount rate;
  - terminal growth above the long-run growth anchor (3.75%), or above 0 for a shrinking business, without a resolving citation;
  - an implied 10-year revenue CAGR outside the cohort's P5–P95 without one.

  The margin and RONIC against their five-year ranges are annotated only.
- **The crux rule:** a buy or sell call needs a "crux", the input the price gets wrong, with quotes found verbatim in the company's own
  material. Without one the label is hold.
- **Diagnostics, never gates:** the terminal-value share, the terminal reinvestment rate, reinvestment above earnings, and year-10
  earnings ÷ base.

## 5. The pilot (registered before any run)
- **Names:** UGI (a utility), Monolithic Power (MPWR), Micron (MU), Lamar (a REIT), AMD (the census's growth case), Costamare (a shipping
  lessor, the census's cyclical case).
- **Arms:**
  - `rev22`: the old briefing, with long-run defaults and the reference value shown; the control;
  - `iii_p50`: the new briefing with P50 printed;
  - `iii_no_p50`: the same without P50.

  UGI and LAMR have no population ranges (their families are not measured), so they ran rev22 and iii_p50 only.
- **Runs:** 22 runs, one sample each. Repeats at a second seed: MU and AMD in both iii arms, MPWR and CMRE in iii_no_p50.
- **Frozen:** quote, research, discovery and evidence cache per name, shared by the arms.
- **Measures, each separate, no value-to-price target:**
  - **(a)** clustering at P50 or a printed quantile;
  - **(b)** stability across seeds;
  - **(c)** cash-flow plausibility, scored blind with price, values and label masked, the scores hashed before unmasking;
  - **(d)** evidence: citations, crux validity, gate outcomes.
- **Reading rule:** expand only if (c) has no incoherent memo, (d) has no unverified crux and no unsupported outlier accepted, and (a)
  shows no systematic copying.

## 6. The result: **the reading rule fails on (c)**
**(c) Cash-flow plausibility (blind), 16 iii memos:**

| Arm | Coherent | Questionable | Incoherent |
|---|---|---|---|
| iii_p50 (8) | 1 | 1 | 6 |
| iii_no_p50 (8) | 2 | 4 | 2 |

By name: Costamare was coherent in 3 of 3 runs; Micron was incoherent in 4 of 4.

**Two systematic failures:**
1. **Stated normalization is not entered.**
   - In 9 of 16 memos the desk's year-10 earnings are 1.8× to 4.7× the analyst's own stated "normalized mid-cycle earnings".
   - AMD: it states normalized $12B, but its inputs reach $45–54B by year 10.
   - Micron: it states $80–90B, while its inputs reach $148–212B.
2. **Classifications contradict the entered path** (7 of 16):
   - "peak" or "decelerating" while years 1–2 accelerate (AMD +46% → +108%; MPWR +50%/+45%);
   - Micron classed "mid" at a 74.6% operating margin against its 8-year median of 24%.

   Years 1–2 almost always equal the consensus levels, even when the analyst classifies a peak.

**(a) Copying:**
- 1 of 12 chosen inputs at P50 in iii_p50, and 0 in iii_no_p50;
- 0 at a printed quantile; 0 outside P10–P90;
- the long-run margin's percentile spans 49–58 points across names.

**No systematic copying of the ranges.**

**(b) Stability:**

| Name and arm | Base value spread | Labels |
|---|---|---|
| CMRE iii_no_p50 | 0.8% | agree |
| MU iii_no_p50 | 2.5% | agree |
| MPWR iii_no_p50 | 2.8% | agree |
| MU iii_p50 | 11.9% | **split** (one seed lost its crux) |
| AMD iii_p50 | 16.9% | agree |
| AMD iii_no_p50 | **130%** | agree (both hold) |

**(d) Evidence:**
- the gate passed 16 of 16 and rejected nothing; almost no input fell outside P5–P95;
- every directional call had a verified crux, and those without one became hold;
- crux citations are mostly **"related"**: a quarter's results or guidance standing in for years 3–5 growth, RONIC or the fade. Only margin
  cruxes were causal, where a filed margin bounds a price-implied margin;
- 26–30% of crux citations did not resolve.

**Process:**
- 0 malformed desk calls and 0 server errors;
- every output field present and every classification valid;
- **4 memos lost their earlier sections after the crux follow-up** (the final memo says "unchanged from prior memorandum"), a harness
  defect.

**Deviations, recorded:**
- the coordinator saw two labels in the run log before scoring;
- the masking script missed "Strong Buy", some margin-of-safety columns and some direction phrases in about half the memos.

**Informational, no bar set (final value ÷ price):**

| Name | rev22 | iii_p50 | iii_no_p50 | Formula reference ÷ price (not shown in iii) |
|---|---|---|---|---|
| AMD | 0.53 | 0.36 / 0.42 | 0.56 / 0.24 | 0.52 |
| MPWR | 0.59 | 0.60 | 0.31 / 0.31 | 0.40 |
| MU | 1.97 | 1.58 / 1.77 | 1.85 / 1.89 | 1.75 |
| CMRE | 2.17 | 1.95 | 2.08 / 2.07 | 2.19 |
| UGI | 1.46 | 1.78 | — | 1.52 |
| LAMR | 0.88 | 0.70 | — | 1.09 |

Without seeing it, the new briefing's values still sit near the formula reference, and the skew cross-check 18 described remains: growth
names well below price, cyclicals near peak about 2× price.

## 7. The coordinator's hypotheses (untested)
- **H1, an interface defect, not only a model limit.**
  - The desk has no input for normalized earnings. The analyst writes its near-term earnings, normalized earnings and the transition as
    prose, then enters five growth rates and a margin separately, and nothing checks one against the other.
  - Failure 1 is what you would expect from that design.
- **H2, consensus years 1–2 have become the new anchor.**
  - The reference value and the long-run defaults are gone, but consensus levels are printed prominently. Muse takes them as years 1–2
    even when its own classification says "peak".
  - In growth names consensus implies +100% or more in year 1 or 2, so the path explodes. At a cyclical peak it holds peak earnings for two
    years.
- **H3, the value skew comes from years 1–2 and the base, not from showing the reference.**
  - The new briefing shares the base and the consensus years 1–2 with the old formula. If those two drive most of the value, removing the
    reference changes little, which matches the table above.
  - Testable offline, with no GPU: decompose each Base value into years 1–2, years 3–5 and the long run; then recompute with the analyst's
    *stated* normalized earnings entered.
- **H4:** showing P50 may hurt coherence (6 incoherent against 2), but n = 8 per arm is too small to say.
- **H5:** some of failure 2 may be Muse's capacity at 30B to keep its stated classifications consistent with numbers it writes 20,000
  tokens later. Earlier, Muse failed an acceptance test on crux form and label splits that a Qwen model passed, under an older briefing.

## 8. The coordinator's suggestions (not started; for your critique)
1. **Make the normalization part of the desk call.** The analyst passes:
   - `near_term_earnings` (years 1–2);
   - `normalized_earnings`;
   - `transition_years`.

   The desk builds years 1–5 from those, or checks the entered growth path against them and returns the mismatch to the analyst in the same
   turn as a reason request. A mismatch with no reason is annotated, never clamped. One source of truth, not prose beside numbers.
2. **Check the classifications against the entered path** (for example "peak" or "decelerating" with years 1–2 growth above the base
   trend). The desk returns the conflict as a reason request, and the verdict is annotated.
3. **Consensus years 1–2:** keep them as evidence, but print the company's own trend and the normalized level next to them, and require a
   stated reason when years 1–2 equal consensus while the classification says "peak".
4. **Fix the lost memo after the crux follow-up, and fix masking** (labels such as "Strong Buy", MoS columns, momentum percentages).
5. **Run H3's offline decomposition first** (no GPU), to see whether the skew really sits in years 1–2.
6. **Then a fresh registered pilot,** the same six names plus Kohl's (a shrinking retailer) and Heritage (an insurer at peak). The
   coordinator also asks whether new, unseen names should be held out for a later confirmation run.

## 9. Questions
1. **Diagnosis:** do H1 and H2 explain the failures, or is something else more likely (the briefing's length, the order of the TASK, the
   model's size)?
2. **Suggestion 1:** should the desk *build* years 1–5 from the stated near-term and normalized earnings, or keep free growth rates and
   *check* them? What could go wrong with each? How should a deliberate non-normalizing business (a secular grower) be handled?
3. **Consensus years 1–2:** keep them as evidence, show them later, or hide them in the first pass? Is there a better way to stop consensus
   becoming the new anchor without making the analyst ignore real near-term information?
4. **Classification checks:** which contradictions should code catch, and which should be left to review? How do we avoid a rule that
   forces a label?
5. **The skew (H3):** is the decomposition the right test, and what would convince you the skew is gone?
6. **The model:** is a 30B model at these settings plausibly able to do this task with a better interface, or should a larger or different
   model be tested? Are any of the settings in section 2 likely to matter: temperature 1.0, xhigh reasoning, a 98k window, speculative
   decoding?
7. **The next pilot:** names, arms, size; whether P50 should be dropped; whether to hold out unseen names; what bar would justify expansion.
8. **Anything else** a careful reviewer would challenge.

At the end, give: your diagnosis in one sentence, the one change you would make first, and the result in the next pilot that would most
worry you.
