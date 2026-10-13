# Coding brief T-priors: population priors at T (no GPU, no model)

Written by the coordinator on 2026-10-07. It implements `SPEC_rebuild.md` section 4, Addenda A–D (above all C 6:
every statistic point-in-time, as an expanding window) and the rulings in Addendum B 8–9.

## Where
- An integration branch `review-2026-10/rebuild-int`: rebuild-harness (the shared point-in-time layer
  `valuation/pit_data.py`) merged with rebuild-engines.
- The coordinator creates it; you branch `review-2026-10/rebuild-priors` from it.
- Worktree under `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\`.
- New module `valuation/priors.py`, implementing the `Priors.for_company(family, state, asof)` interface from
  `valuation/priors_interface.py`. Measurement scripts go under `valuation/priors_build/`.

## Hard rules
- **No look-ahead.** A prior for date T uses only observations whose outcome was accepted before 16:00 ET on T: the
  later year's annual report must have been filed before T.
  - Build vintages per year-end (the prior for dates in year Y uses everything known by Y−1-12-31, plus the filings
    accepted between that year-end and T, if you choose finer vintages; state which).
  - A test must prove that changing any observation dated after T changes nothing in the prior for T.
- **No returns or prices are used in any prior,** except the two valuation references below, which use prices known
  at the observation date only, never outcomes.
- The data comes from the shared layer only, inputs as known at T. Never `fundamentals_history.json`.
- **Delisted companies stay in.** Their observations count up to their last filing. Survivorship in priors is
  reported: the share of observations from companies that later delisted.
- No GPU, no model, no deletion, no downloads. Never edit the live rs2-local tree, `.env*` or secrets. Use `is None`,
  not `or`.

## What to measure (each as P5, P10, P25, P50, P75, P90, P95, with n per cell; a cell with n < 50 is merged with its
neighbour by a stated rule and flagged)

**State variables** (computed at T from filings known at T):
- size, by revenue bucket;
- revenue growth delivered (the latest year and the 3-year CAGR);
- operating margin and its deviation from the company's 8-year median;
- the cyclicality score;
- return on invested capital;
- family.

**Judgment-input priors, conditional on state:**
1. **`g1`:** next-year revenue growth, given size and growth delivered.
2. **`growth_decay`:** the curve of year-by-year growth t+1..t+10 for each growth-delivered bucket, as the median
   ratio of (growth_k − terminal) ÷ (growth_1 − terminal). Also report the raw paths.
3. **`margin_target` and `margin_retention`:** the measured fraction of the margin deviation remaining at k = 1..7, by
   cyclicality-score band (terciles) and the sign of the deviation, plus the level distribution of margins k years
   later. The A2 method, on the point-in-time layer.
4. **`ronic`:** incremental return on capital (Δ NOPAT ÷ Δ invested capital over 3-year windows), by family and
   return-on-capital tercile.
5. **`g_terminal`:** the distribution of 10-year-ahead revenue growth, and of revenue-trend persistence for shrinking
   companies, with delisted companies included. Report it with and without companies that later delisted.
6. **Financial family:** `rote_target` and `rote_retention`, by the A2 method on return on tangible equity.

**Engine references:**
7. **`ev_fcf_multiple`:** the distribution of EV ÷ FCFF₁ by growth and return state, using prices on the observation
   date. A cross-check reference only.
8. **`ptbv_of_rote`:** price ÷ tangible book against ROTE (binned), for financials, using prices on the observation
   date.
9. **`normalization_curve(score, horizon)`:** the margin-retention curve as a function of the cyclicality score.

**Measured structure (Addendum B 8–9):**
10. **The input correlation matrix** (growth, margin change, return on new capital), by family.
11. **The cyclicality-score weights:** the weights of the four components that best predict the measured margin
    reversion. A non-negative least-squares fit on development years 2009–2022 only, reported with the equal-weight
    baseline and the fit's out-of-sample error (cross-fitting by year). Adopt only if out of sample is better;
    otherwise keep equal weights.

**The mechanical baseline** (Gemini's naive prior, adopted): growth year 1 = trailing 3-year CAGR, margin held. It is
reported alongside each prior, because pass 1 shows it and gate 1 B4 compares against it.

## Output
- `Priors.for_company(...)` returns `PriorSet(inputs, curves, refs, source, placeholder=False)`, with `source` naming
  the vintage and the data hash.
- Vintages are cached on disk under `C:\Users\riper\stocks\stocks-workspace\data\priors\<vintage>\`.
- `PRIORS_REPORT.md` holds the tables for the 2016, 2020, 2022, 2024 and 2025 vintages, n per cell, merges,
  survivorship shares, the correlation matrix and the cyclicality-weight fit with its out-of-sample result.

## Tests
- the no-look-ahead proof;
- quantile and merge rules on synthetic panels;
- monotone curves where expected (report, never force, any non-monotone measured curve);
- that the engines run end to end on a real `PriorSet` for a few names (no value printed in the report).

## Deliverable
Write your report as your final reply (the coordinator saves it). Include:
- commits;
- what was measured;
- the key tables in compact form;
- deviations ("none" only if true);
- questions.

Run `date '+%H:%M'` before writing timestamps.
