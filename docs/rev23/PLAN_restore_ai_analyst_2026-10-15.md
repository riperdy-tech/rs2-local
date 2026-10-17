# Plan: restore the operator's design, with the AI analyst analysing the screener's book (2026-10-15)

**Status:** for the operator's approval (SPEC_rebuild AK.93).

## The target system (`docs/system-map/01_BIG_PICTURE.md`, `03_RS2_DEPTH.md`)
1. **The screener nominates the book:** today 61 research_now and 98 watchlist, 159 names (`factor_scores.json`).
2. **For each nominated stock, Muse (the local AI analyst) forms the judgment** from:
   - the prepared input package: filed figures, recent quarters, document excerpts, the company's state, and the population ranges with the
     company's own baseline;
   - **plus research and news**, gathered by the existing research tools (`deep_research.py`, `company_news.py`, `catalyst_research.py`,
     `world_news.py`, SearXNG) and given to Muse as a dated section.
3. **Code computes the value** from Muse's judged inputs (the engine), and enforces the guards: plausibility, repeatability, the gate.
4. **Scheduling:** verdicts flow on the depth schedule. Events (new filings, a price crossing the band) come first, then a rotation within 14
   days. The GPU stays one name at a time and pauses while the operator games.
5. **The code-only engine (v2.1) keeps running** as the **baseline** the AI system must beat (the paper book "Code baseline", live since
   today).

## What already exists (built and tested in this rebuild)
- **Muse** runs on the GPU through `llamacpp_server` at about 10 minutes per company. **In gate 2 it beat the code engine on growth
  forecasts.**
- **The pack builder, `valuation/muse/pack_v2.py`.** It is leak-free by design, so it carries no news; that was right for testing on past
  dates.
- **The engine** with near-term forecasts, the live runner, the verdict contract v4, the gate, the overlay, the paper books, the nightly
  shadow, and the test and audit machinery.

## What was lost, and is restored here
| Lost | Restored by |
|---|---|
| The AI analyst in live verdicts (AK.52's weight 0 from a sample-size cliff, 143 against 150) | Step 2: a continuous weight rule, fitted on gate 2 |
| The screener's nominated book (the shadow values all 2,000) | Step 1: the live AI system runs on the book |
| Research and news (excluded from leak-free test packs, never restored) | Step 3: a dated research section for live packs |

## The steps (each verified before the next; nothing touches real money)
1. **The book-scoped live runner** (CPU, about 2 days of build).
   - The live runner takes the book (research_now ∪ watchlist ∪ names already carrying a verdict) instead of the whole universe, and keeps
     DEP-00's triggers and rotation.
   - *Verify:* a dry run on today's 159 names; the job list equals `live_book()`'s.
2. **How Muse and the engine are combined (S5b),** a registration for your approval, then a fit.
   - Muse's judged inputs move the engine's inputs by a weight that **grows continuously with the evidence**, replacing the 150 cliff (both
     outside reviewers recommended this).
   - It is fitted on gate 2's data only, and frozen before any new test.
   - *Verify:* an independent recomputation of the fit; synthetic tests (a known weight is recovered; weight 0 under noise).
3. **Research and news for live packs** (CPU and network, about 2 days of build).
   - The research tools gather, for each name, recent filings, news and catalysts with dates and sources, cut at the valuation date.
   - It becomes the pack's dated section N. Muse reads it; code never takes a number from it without a filed source.
   - *Verify:* a 10-name review of packs by the coordinator; a leakage check (nothing dated after the valuation date).
4. **A fair test of the AI system against the code baseline** (GPU about 3 days), registered before data.
   - **The date:** 2026-09-25, untouched and prospective (the September quarter ends after the date; its results are filed by mid-November).
   - **The sample:** 450 companies (seed 20261010).
   - **The arms:** Muse + engine (the frozen step-2 weight) against the code baseline (v2.1) and v1 on the same companies, plus the run-rate
     and population baselines.
   - It uses the same bars and audit as gate 2b, with the annual horizon added in spring.
   - Research cannot be used on a past date, so this test uses the leak-free pack. **Research is judged on the live paper record** (step 5),
     against the same AI system without research.
5. **The AI system's paper book on the screener's book,** live and unpromoted, from about 10-25.
   - It is its own paper ledger (never `rn_depth`, which the real-money mirror copies until you approve a cutover).
   - It runs beside the code baseline, with monthly reports.
6. **Real money:** only after the step-4 test passes, the paper record is reviewed, and the open engine fixes are in (the discount rate v2.2;
   the level skew). It is your decision, with a small start and the ability to roll back.

## Honest dates
| When | What |
|---|---|
| 10-16 → 10-18 | Steps 1 and 3 built; step 2's registration to you |
| 10-19 → 10-22 | Step 2 fitted and frozen; step 4 registered; Muse runs on 09-25 (about 3 GPU-days; it waits while you game) |
| about 10-25 | Step 5: the AI paper book on the screener's book begins |
| mid-November | Step 4's verdict: the AI system against the code baseline on a prospective date |
| spring 2027 | The annual reads (07-31 and 09-25) |

## Decisions for you
1. Approve this target system and these steps.
2. Approve restoring research and news for live packs (section N), judged on the paper record.
3. Approve 2026-09-25 as the AI system's fair-test date (about 3 GPU-days).
4. Confirm a separate paper ledger for the AI system until you approve a cutover to `rn_depth`.
