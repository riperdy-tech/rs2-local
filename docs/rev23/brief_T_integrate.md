# Coding brief T-integrate: wire the rebuild together and run gate 1 on the development period (no GPU, no model)

Written by the coordinator on 2026-10-07. Read `SPEC_rebuild.md` (all, Addenda A–F override the body),
`REGISTRATION_gate1_DRAFT.md`, and the reports in `stocks-workspace/scratch/rev23/`: `REPORT_engines.md`,
`REPORT_muse.md`, `REPORT_priors.md`, and the harness report when present.

## Where
- Branch `review-2026-10/rebuild-gate1` from `review-2026-10/rebuild-int` (head at launch, which includes the final
  harness merge), in a new worktree under `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\`.
- Development dates only: quarter-ends from 2017-03-31 to 2022-12-31.
- The harness's holdout lock must refuse any 2023–2024 date. Do not create a freeze file.

## Work
1. **The adapter** from `valuation/pit_data.py` to the engines' `common.CompanyPIT`:
   - inputs as known at T, with the 16:00 ET acceptance rule;
   - provenance states, where `PIT_INVALID` and `AMBIGUOUS` are refused;
   - industry by the SIC as filed at T (filing headers where the layer has them, else stamped current).

   Replace the engines' interim `pit_companyfacts.py` use with the adapter. Keep the interim module for its tests only.
2. **Addendum F 4:** the `margin_target` spread rescaled by 1/(1 − r̄₅) of the cell, capped at 10×. Report the implied
   terminal-year spread as a diagnostic.
3. **The gate-1 engine** for the harness:
   - **Per stock and date:**
     - classification;
     - the population priors at T;
     - the discount rate at T (Damodaran files dated before T; Hamada with book D/E per Addendum B 3; cost of debt per
       Addendum B 5);
     - the family engine with every judgment input at the prior's P50 (no AI);
     - the output: the median IV, P10..P90, the secondary cross-check, model disagreement, terminal-value share,
       family and stamps.
   - The value is per share, at T, on the same share basis as the unadjusted close.
4. **Run the development period:** all 24 dates, the full gate-1 universe per the draft registration (annual report
   accepted before T, a traded close at T, a built family, market cap ≥ $300M at T, plus the sub-$300M group
   reported separately).
   - Produce every gate-1 metric (B1–B4) on development dates, under the three survivorship bounds.
   - **Report:** coverage and refusals by reason, family and date.
   - **Diagnostics the coordinator needs** to find structural defects:
     - the distribution of IV ÷ price by family and by industry;
     - the extremes (below 0.4× or above 2.5×) by family;
     - the terminal-value share distribution;
     - model disagreement by family;
     - the top 30 and bottom 30 IV ÷ price on two dates (2019-12-31 and 2022-06-30) with their key inputs (for a
       structural read, not for tuning).
   - **Compute time:** state it, and parallelise across CPU cores if the run exceeds about 2 hours.
5. **The leakage audit** (`valuation/muse/leakage_audit.py`) on pack v2 for 20 names at 2019-12-31 and 20 at
   2022-06-30, plus the Addendum E 5 check: `documents.py`'s Item 1 and Item 7 extraction on real cached filings for
   at least 20 names across the three families. If the cache lacks a document, fetch it through the repository's SEC
   helpers (UA, ≤ 10 requests per second); no other network.

## Rules
- No GPU, no model, no server.
- **Never delete files, including your own output:** regenerate into a new folder.
- No downloads beyond SEC filings through the helpers.
- Never edit the live rs2-local tree, `.env*` or secrets, and never touch `cache/DEPTH_PAUSED`.
- Use `is None`, not `or`.
- Commit on your branch only; no push or merge.
- No engine change motivated by a development return figure without a structural reason written down; state any you
  make. Never name or tune to a stock.
- Run `date '+%H:%M'` before timestamps.

## Deliverable
Your final reply is the report: commits, what ran, coverage, the B1–B4 development figures under three bounds, the
diagnostics, the leakage and extraction checks, compute time, deviations ("none" only if true), questions.
