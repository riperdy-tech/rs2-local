# The valuation rebuild (Phase 5): specification

Written by the coordinator (Opus 5.5, main session) on 2026-10-06, after the defect census (`defect_census.md`) and
the external cross-check by ChatGPT and Gemini (`CROSS_CHECK_for_external_reviewers.md`; both replies, and
ChatGPT's follow-up, are summarised in section 9). This replaces the revision-23 patch plan. The price-first design
("IV = price moved by evidence") is withdrawn: both reviewers showed it swaps one anchor for another.

**Goal:** an AI analyst whose intrinsic values are good enough for real money. Real money stays off until the
validation chain in section 6 passes.

## 1. Architecture

```
screener (150–300 nominations)
  -> economic classification (code)            -> family: operating | financial | commodity/asset-heavy
  -> population priors per input (code)        -> P10..P90 for each judgment input, conditional on the company's state
  -> Muse pass 1, PRICE-BLIND (several short prompts): place the company inside each prior, with cited evidence
  -> Python: primary engine value distribution + secondary cross-check; model disagreement recorded
  -> reveal the price: reverse valuation (what the price requires), each requirement placed in the population prior
  -> Muse pass 2, RED TEAM: challenge its own pass-1 inputs; changes need cited evidence; an "extraordinary assumption"
     (its own or the market's, outside the prior's P5..P95) needs company-specific hard evidence
  -> Python recompute -> final IV distribution (P10..P90, Pr(IV > price), terminal-value share, model disagreement)
  -> calibration layer (learned from replay: Muse's stated percentiles vs realised outcomes)
  -> sizing (later; only from the calibrated distribution)
```

Unchanged principles:
- the AI chooses inputs, Python computes, code checks;
- no rule names or targets a company;
- every number is a textbook method or is measured from the population, never tuned to make outputs look right;
- annotate, never silently gate.

## 2. Economic classification (code)

**Families:**
- **financial**: banks, insurers, specialty finance, broker-dealers;
- **commodity/asset-heavy**: oil and gas, mining, shipping, commodity chemicals, steel, and similar;
- **operating**: everyone else.

**Inputs:** the SIC code from SEC submissions, plus balance-sheet tests stated in words:
- `insurance_reserves` material against total assets means financial;
- borrowings funding a lending book means financial.

Every assignment records its reason. A conflict between the SIC code and the balance sheet is annotated, and the
balance sheet wins. REITs and conglomerates are out of scope in this build; they are classified, annotated "family
not built", and not valued.

## 3. Engines (code; one primary engine and one secondary cross-check per family)

Cross-checks are diagnostics, never averaged in. `model_disagreement` is the log ratio of primary to secondary.

### 3.1 Operating: layered DCF
- **The chain:** revenue -> operating margin -> NOPAT (operating income × (1 − tax)) -> reinvestment ->
  FCFF -> enterprise value -> equity value.
- **Equity value:** enterprise value − net debt − leases (when tagged) − minority interest + non-operating assets.
  Cash is counted, not double-counted through interest.
- **Reinvestment:** growth / (return on new invested capital), with the return on new capital fading toward the
  cost of capital by the population rate.
- **Maintenance spending is explicit:**
  - Greenwald's method: maintenance capex = capex − (PP&E ÷ revenue) × the change in revenue;
  - working-capital release is counted for shrinking companies.
- **No margin translation:** the operating margin is forecast directly (this replaces A3).
- **Horizon:** growth fades year by year along the population's conditional growth-decay curve until it reaches
  terminal growth, at most 25 years (A5). The terminal-value share is always reported.
- **Terminal growth:**
  - from the population distribution by company state;
  - shrinking companies may have negative terminal growth;
  - no hard-coded floor (A4 revised).
- **Secondary cross-check:** a return-on-capital and reinvestment consistency check, plus implied EV/FCF against the
  population of the same growth and return state.

### 3.2 Financial: excess return on equity
- **Value** = tangible book + the present value of (return on tangible equity − cost of equity) × tangible book,
  over a fade to the cost of equity.
- **Return on tangible equity** is normalized through the cycle by the A2 method applied to that series.
- **Insurers:** underwriting result and investment income are separated where tagged, and catastrophe years count in
  the normalization.
- **Secondary cross-check:** price-to-tangible-book against return on tangible equity, measured across the
  population.

### 3.3 Commodity/asset-heavy: mid-cycle cash flow
- **Value** = the operating chain of 3.1 on through-cycle (median) margins and returns.
- **Normalization starts at year 1:** no peak years held (fixes U4).
- **Cyclicality is a continuous score:** margin volatility, reversal frequency, autocorrelation and revenue
  cyclicality. It sets the normalization speed through the measured A2 curve. There is no cyclical/secular switch.
- **Secondary cross-check:**
  - asset value: oil and gas use the standardized measure of discounted future net cash flows (an XBRL tag under
    ASC 932) where filed;
  - elsewhere: tangible book (vessels, plant) as a replacement-cost proxy, annotated as a proxy.

### 3.4 Discount rate
- **Formula:** cost of equity = risk-free + relevered beta × ERP.
- **Relevered beta** = Damodaran's industry unlevered beta × (1 + (1 − tax) × the company's own D/E), the Hamada
  equation.
- **Inputs:**
  - **ERP:** Damodaran's implied ERP for the valuation date;
  - **beta and ERP data:** the dataset version dated on or before the valuation date (no look-ahead), with the file
    hash recorded.
- **Concentration risk:** carried in scenario cash flows, never as an extra premium.
- **The closure premium:** kept only as a diagnostic ("the ERP that makes our engine value the market at its price").

## 4. Population priors (code)

For each judgment input of each family, Python builds a conditional distribution (P5, P10, P25, P50, P75, P90, P95)
from the screener's filed history, conditioned on the company's own state:
- size;
- current growth;
- margin level and its deviation from the company's 8-year median;
- the cyclicality score.

The inputs:
- revenue growth by year;
- operating margin path;
- return on new capital;
- the return on tangible equity path for financials;
- terminal growth.

A2's measurement (`brief_A2_measurement.md`, running) is the first of these. Every prior table is built from fiscal
years before the valuation date only.

## 5. Muse

**Pass 1, price-blind.**
- **Never shown:** price, market cap, targets or any value.
- **Prompts:** short, one per question (for example revenue runway, margin sustainability, reinvestment needs, risks),
  then a synthesis prompt that outputs, for each input, a position inside the prior with its reasons and quoted
  citations.
- **Hard evidence:** a position outside P10–P90 needs company-specific hard evidence (contracts, filed guidance,
  backlog, capacity).

**Pass 2, red team.**
- **What it sees:** the price, the reverse valuation, and each market requirement placed in the prior. A requirement
  outside P5–P95 is flagged an "extraordinary assumption", which raises the evidence bar for the side that relies on
  it. ChatGPT's correction to Gemini: the price is evidence of expectations, not of the company's future, so it never
  moves a forecast by itself.
- **What it does:** challenges its own pass-1 inputs. Any change needs new cited evidence.
- **The anchoring check:** a pass 2 that only moves inputs toward the price, without new evidence, is the failure
  this design exists to prevent. It is measured in the replay.

**Output** (Python): an IV distribution; Pr(IV > price), Pr(IV > 1.2 × price), Pr(IV < 0.8 × price); the
terminal-value share; model disagreement; evidence quality.

## 6. Validation chain (every bar registered before results are seen)

**Data splits:**

| Split | Use |
|---|---|
| Development, valuation dates 2017–2022 | Build and fix the engines and priors. |
| Code holdout, valuation dates 2023–2024 | Frozen engines only, run once. No formula change after seeing it. |
| AI replay, monthly dates 2025-10 to 2026-06 | Frozen engine plus frozen Muse prompts and model; information set as of each date (Muse's knowledge ends about late August 2025). |
| Live forward scoring | Every live verdict at 3, 6 and 12 months. |

**Point in time:**
- filings by filing date, as first filed;
- outcomes are judged on the first subsequent filing, never a later restatement;
- Damodaran snapshots by date;
- prices total-return.

**Yardsticks**, each computed on the same stocks and dates: earnings yield, FCF yield, quality (gross profitability
and return on capital), momentum (12-1 months), the old engine (revision 21's reference).

**Two kinds of quality,** both required:
- **Forecast quality:** the error of revenue, operating margin, return and reinvestment forecasts against the first
  subsequent filings, against the prior's P50 as the naive forecast. For the AI: its error against the code prior
  alone.
- **Investment quality:**
  - rank correlation (Spearman IC) of IV ÷ price with excess return;
  - quintile spreads;
  - sector-neutral results;
  - incremental information over the yardsticks (regression or residual IC);
  - horizons of 3, 6 and 12 months, plus 24 and 36 months where the data allows.

**Gates:**
1. **Code engines, development to holdout.** They must show economically meaningful incremental information over
   every yardstick on the holdout. Two further conditions:
   - extremes below 0.4× or above 2.5× price must not sort by family;
   - they must not all converge toward 1.0× price; the spread of IV ÷ price is reported against the old engine's.

   **If this fails, Muse work stops** and the next engine cause is found.
2. **Muse adds information.** On the replay, Muse plus code must beat code alone on forecast quality and on
   investment quality.
3. **Live forward scoring** accumulates. Real money is the operator's decision after gates 1 and 2.

The numeric bars for each gate are set in a registration file before that gate's first run, and the operator
approves them.

## 7. Work order
1. **Running:** A2 measurement and readiness for the January-2026 trial (the date is now superseded by the monthly
   replay; its readiness check still applies to every date).
2. **T-harness (Sonnet):** the validation harness. Point-in-time dates, first-filed outcomes, the yardsticks, the
   metrics, the frozen-holdout lock (a run on 2023–2024 is refused unless a freeze file names the engine commit).
   Extends the existing backtest harness (rs2-local branch `review-2026-09/backtest-phase2`, commit 40cb5cf).
3. **T-engines (Sonnet):** classification, the three engines with cross-checks, and the discount-rate module (with a
   pluggable data source until the Damodaran files are approved).
4. **T-priors (Sonnet, after A2 is read):** the prior tables of section 4.
5. **Gate 1** on development, then the registration, then the holdout.
6. **Muse passes and prompts,** then gate 2 on the replay (GPU).

## 8. Data needing the operator's permission
Damodaran's datasets, from `pages.stern.nyu.edu/~adamodar/pc/`:
- `datasets/betas.xls` (82,432 bytes, January 2026);
- `datasets/histimpl.xls` (113,152 bytes, the implied-ERP history);
- yearly archives `archives/betasYY.xls` for 2016–2025 (about 80 KB each).

About 1 MB in total, stored versioned with hashes.

## 9. External review, decisions taken
- **Accepted:**
  - valuation families instead of one DCF;
  - two-pass price-blind and red-team design;
  - priors as distributions, Muse placing the company inside them, and calibration learned from history;
  - a continuous cyclicality score;
  - deviation-conditional reversion;
  - no hard terminal floor;
  - explicit maintenance reinvestment and working-capital release;
  - the layered operating chain in place of the margin translation;
  - Hamada relevering with Damodaran data and dated snapshots;
  - the closure premium demoted to a diagnostic;
  - rolling monthly replay;
  - forecast accuracy scored alongside returns;
  - first-filed outcomes;
  - a three-way data split with a frozen code holdout;
  - yardsticks, and incremental information as the bar;
  - primary plus secondary engine, with model disagreement recorded;
  - "extraordinary assumption" raising the evidence bar rather than counting as evidence.
- **Not adopted:** beating Street targets as a bar (reported only).
- **Deferred:** the REIT and sum-of-the-parts families, until the first three pass.

## Addendum A (2026-10-06, after `scratch/rev23/REPORT_A2_readiness.md`)

**Point-in-time data, binding on every component.**
- **The point-in-time source is SEC companyfacts per filing** (value, filing date, accession), taken as first
  filed. Not `fundamentals_history.json`: it holds the value now on file, with no accession per cell, and it starts
  in 2014.
- **One shared point-in-time data layer** serves the engines, the priors and the harness.
- **Delisted companies are kept,** so survivorship is corrected where companyfacts allows.
- **A filing counts only if its filing date is strictly before the valuation date.**
- **A fiscal year exists only from its own 10-K, 20-F or 40-F filing date.** S-1 and F-1 data is not used. A
  company with no annual report filed before the date is out of the universe for that date.
- **The valuation-date price is the traded close, unadjusted,** with share counts on the same basis.
  Total-return series are used only for outcomes.
- **In as-of mode, no input may come from a same-day snapshot:**
  - no vendor fallbacks (cash, debt, TTM "through" dates, `fin[...]`);
  - no current anchors;
  - no current taxonomy where a dated one exists.

  A missing value is "not available", never filled from today.

**Decisions on the A2 tables.**
1. **Window:** the record rule (at least 5 defined years) is primary, with the balanced panel as a check. Tables are
   rebuilt on the companyfacts layer, so dates before 2017 get tables.
2. **The crossing classifier is retired** (69–81% "cyclical", which is noise). It is replaced by the continuous
   cyclicality score of section 3.3; reversion curves are measured by score band and sign of deviation.
3. **The measured shape is the rule:**
   - secular positive deviations persist (median about 1.0 at k=1..7), so no reversion is imposed on them;
   - negative deviations, and all cyclical ones, revert along the measured medians, which level off at about 0.3–0.5.
   - The interquartile ranges are wider than the medians, so they enter the priors as distributions (section 4), not
     as point rules.
4. **Revenue decline:** the population says a negative 8-year trend does not persist (median +3 to +6% a year
   afterwards), but that is survivor-only. It is re-measured on the companyfacts layer with delisted companies,
   before any terminal-growth rule is set.
5. **Universe per date:**
   - companies with a filed annual report before the date and a traded close on the date;
   - foreign filers with no quarters stay in, annotated;
   - CHA-like empty records and WSE-like no-price cases drop out, with the count reported.

## Addendum B (2026-10-06, the coordinator's rulings on `scratch/rev23/REPORT_engines.md`)

The engines branch `review-2026-10/rebuild-engines` (`8c22b71`) was reviewed.
- **The chain's arithmetic matches section 3.** Reinvestment is priced at the long-run margin, shrinking companies
  release working capital only, and terminal growth ≥ WACC is an invalid draw, never repaired.
- **One defect to fix at merge:** `engine_operating.py:156` defaults short-term investments with `or 0.0`. A
  diagnostic only, but the rule is `is None`.
- **The coder's dry-run count is inconsistent:** "6 ran" in the text, 5 in the table. The table is taken.

**Rulings on the coder's questions:**
1. **Maintenance-gap floor at 0:** kept. Depreciation above maintenance capex cannot be harvested forever. The raw
   gap stays printed, and T-priors reports the corpus distribution of the raw gap.
2. **Operating leases not subtracted:** confirmed. The lease cost is inside EBIT, so subtracting the liability double
   counts, the same class of error as the revision-22 net-debt card.
3. **D/E in the price-blind pass:** book D/E, because the market D/E would reveal the price.
   - When parent equity is not positive, or book D/E exceeds the 95th percentile of its Damodaran industry's D/E, the
     industry's D/E is used instead, stamped.
   - The red-team pass reports the market-D/E rate as a sensitivity.
4. **`indname.xls`:** it is 22 MB (company to Damodaran industry, January 2026). It needs a separate operator approval;
   asked.
   - Until then, a SIC-to-industry map is built in code by a stated rule and reviewed by the coordinator.
   - A ticker-level industry from a January-2026 list would be current-dated anyway, so it is stamped for dates
     before 2026.
5. **No clean interest line:** cost of debt = risk-free + the median spread (interest ÷ average debt − risk-free)
   measured on the population of the same industry and year from filings. No new download; stamped.
6. **The 10% insurance-reserve threshold:** accepted as a stated convention, given the measured gap (6.2% against
   38.7%+). A corpus-wide check runs once the shared layer has SIC for every filer.
7. **IFRS facts:** yes. The shared layer reads the ifrs-full namespace with a stated tag map, so foreign filers become
   classifiable.
8. **Input correlations:** T-priors measures the correlation matrix of growth, margin and return on new capital from
   the population, by family. Independence remains the fallback, stamped.
9. **Cyclicality-score weights:** T-priors measures them as the weights that best predict the measured margin
   reversion (A2 method), on development years only. Equal weights remain until then, stamped.

**Data-layer needs found by the engines** (sent to T-harness):
- E&P revenue and capex tags (APA has no revenue in plain companyfacts);
- IFRS facts;
- the production extractor's tag ladders, votes, denies and scale corrections, applied per filing as first filed;
- separate short-term borrowings added to the current portion of debt.
- **Update to ruling 4 (2026-10-06):** the operator approved all Damodaran files. `datasets/indname.xls` is
  downloaded (22 MB, sha256 a1f4d70a…, in MANIFEST), with CSVs `csv/datasets_indname__*`: 48,156 companies with
  exchange:ticker, Damodaran industry and SIC.
  - The industry for the beta comes from it by ticker.
  - The SIC rule stays only as a fallback for tickers it does not list, stamped.
  - It is January-2026 data, stamped "current-dated" for valuation dates before 2026.

## Addendum C (2026-10-06, the second cross-check: ChatGPT and Gemini on point-in-time data)

These replace the conflicting parts of Addendum A.

1. **Inputs and outcomes are two different rules.**
   - **Input at time T:** the latest filing known at T, amendments included. A 10-K/A filed before T replaces its 10-K;
     one filed after T is invisible.
   - **Outcome for a period:** the first value reported after T for that period, never today's restated value.
   - **Every fact is stored with:** CIK, taxonomy, tag, unit, value, start, end, instant, dimensions, form, filed,
     acceptance timestamp, accession, amendment flag, fy, fp.
   - The snapshot at T is built from those records, so every number in a pack can name the accession it came from.
2. **The decision timestamp is 16:00 ET on the valuation date.**
   - A filing is eligible when its EDGAR acceptance timestamp (from SEC submissions) is at or before that time.
   - Simulated trades happen at the next session.
   - This replaces "filed strictly before the date". Gemini's alternative, a one-day lag, is not taken, because the
     timestamp is exact.
3. **Every input carries a provenance state:** `PIT_VALID`, `PIT_INVALID`, `MISSING`, `AMBIGUOUS`, `RESTATED` or
   `CORPORATE_ACTION_UNRESOLVED`. The engines refuse `PIT_INVALID` and `AMBIGUOUS`. Nothing is substituted.
4. **Prices go through a `PriceProvider` interface.**
   - Yahoo (`auto_adjust=False` plus the actions history) is the first provider.
   - Every price carries `price_quality` (verified, unverified or missing). The valuation price is the raw close at T
     on the same share basis.
   - **Delisting is a corporate-action event,** modelled on CRSP's method:
     - an acquisition pays its consideration (cash, or stock at its value);
     - a bankruptcy is −100%;
     - a security that moved to OTC continues to be priced;
     - when no data exists, the outcome is `OUTCOME_UNOBSERVABLE`, never an invented −100%.
   - **Before the code holdout,** the share of each date's universe that Yahoo cannot price is measured. The operator
     then decides on a delisting-aware source (Sharadar SEP or Norgate are the options Gemini named; the cost is to be
     checked).
5. **Consensus is removed from the core model,** live and replay alike.
   - Its place is taken by the population prior (P5..P95 per input, built at T) and the company's own mechanical
     baseline (Gemini's "naive prior").
   - Live, consensus may be displayed as context but never enters the valuation.
   - A later separate experiment can test "core + consensus".
6. **Every population statistic is point-in-time, as an expanding window:**
   - growth persistence, margin reversion, the cyclicality weights, size buckets, RONIC, industry behaviour, the
     correlation matrix and the terminal-growth distribution;
   - for date T, only observations whose outcome was known before T are used.
7. **Point-in-time classification and metadata:**
   - the industry for a date comes from the SIC in the filing headers as filed at T, not today's submissions record;
   - the Damodaran `indname` map (January 2026) is used only for dates in 2026 or later;
   - company name and ticker as of T where filings show a change.
8. **A formal leakage audit runs before the first AI replay.** It covers:
   - every pack section and its metadata;
   - prompt wording: only "Analysis date: <T>", never words about data availability or "replay";
   - file names, URLs and cached snippets;
   - current names and tickers after mergers.

   It runs as a scripted grep for dates later than T, plus a checklist read by the coordinator.
9. **Entity masking (Gemini) is not adopted for the main replay.** Masking names would make the replay a different
   system from live use, which is the same mismatch both reviewers reject for consensus. A small control instead
   measures name bias: the same replay stocks, masked and unmasked, with the difference reported.
10. **Horizons by date.** Forecast accuracy (next quarter, two quarters, next fiscal year) and returns (3, 6, 9 and
    12 months) are each scored only on dates whose horizon has fully elapsed.
11. **Holdout discipline:** no engine change may be motivated by 2023–2024 results. A change after the holdout makes
    2023–2024 a development set, and a new holdout must be named first.

## Addendum D (2026-10-07, the operator's rulings)

- **No paid data subscription.** This replaces Addendum C item 4's "the operator then decides on a delisting-aware
  source".
  - **Delisting outcomes come from free SEC records:**
    - Form 25 and Form 15 give the delisting and deregistration dates;
    - an 8-K Item 2.01 (completion of an acquisition), with the merger proxy or 8-K, gives the consideration;
    - an 8-K Item 1.03 (bankruptcy), with the plan's treatment of the common stock, gives −100% when the equity is
      cancelled;
    - the last Yahoo close before delisting is used where Yahoo has it.
  - **When the consideration cannot be read reliably by code,** the outcome is `OUTCOME_UNOBSERVABLE`.
  - **Every result is reported with bounds:** with unobservable delistings excluded, at −100%, and at the last close,
    so the survivorship effect is measured rather than assumed.
  - **If the bounds straddle a gate's bar,** that gate's result is "not decided", never "pass".
- **External AI reviews are advice.** The coordinator rules on each point and records the ruling (Addenda B–C
  already do).

## Addendum E (2026-10-07, the coordinator's rulings on `scratch/rev23/REPORT_muse.md`)

1. **`curve_position` comes from T-priors:** `PriorSet.refs["curve_position"](name, state)` gives, per curve input
   (growth persistence, margin retention, ROTE retention), the measured distribution of the fraction of the gap still
   open at year 5, conditional on state. Its median equals the measured curve. Sent to T-priors.
2. **The hard-evidence keyword rule is accepted as a stated rule, not loosened.** "Any figure" would let generic outlook
   numbers pass. Every qualifying quote records which branch qualified it (strong word, or figure plus weak word). The
   replay reports the share of positions outside P10..P90 by branch, and the coordinator reads samples of each before
   gate 2.
3. **Q comes from the shared layer.** `pit_data` must expose quarterly facts (10-Q and the 10-K's fourth-quarter
   derivations), with the same provenance and the 16:00 ET acceptance rule. `CompanyFactsQuarters` is a stopgap.
   Sent to T-harness.
4. **Accepted:**
   - D built by `documents.py` under the point-in-time rule (sec_primary cannot honour the cutoff);
   - P3 skipped for financials;
   - P1–P4 positions standing when P5 fails;
   - the reverse valuation on point inputs (reported as such).
5. **Before any GPU run:**
   - `documents.py`'s Item 1 and Item 7 extraction must be exercised against real cached filings for at least 20
     names across the three families;
   - the leakage audit must pass on every pack of the first replay date.

## Addendum F (2026-10-07, the coordinator's rulings on the T-priors report)

T-priors (`review-2026-10/rebuild-priors`, `066f391`) was reviewed. Vintages are in `stocks-workspace/data/priors/`
and the report is `data/priors/PRIORS_REPORT.md`.

**The no-look-ahead proof is accepted.** Changing every fact filed on or after the cut changes nothing; a twin test
shows the proof is sensitive.

**Walk-forward results** (each vintage tested on the next year's outcomes):
- the g1 prior median beats the trailing 3-year CAGR in every year from 2015 to 2025;
- the margin path beats "margin held" at k = 3;
- the P10..P90 intervals are under-dispersed in shock years (64–85% coverage against 80%). Left for the calibration
  layer, not hand-widened.

**Rulings on the coder's questions:**
1. **SEC submissions for about 13,000 delisted CIKs** would fix the SIC-based family labels of delisted companies, and
   with them the survivor-only commodity family. It is a bulk download from sec.gov, so it goes to the operator for
   approval. Until then the gap stays stated, and commodity priors are stamped survivor-only.
2. **Quarterly vintages: no.** Population statistics drift slowly; the walk-forward shows annual vintages beating the
   baselines. The six-month average lag is stated.
3. **The return-on-new-capital fade proxy** (excess over the population median) is accepted and stamped. It is
   revisited only if development-period diagnostics implicate it.
4. **`margin_target` spread:** the prior's quantiles describe the margin level five years on. Rescale the deviation
   from the median by 1/(1 − r̄₅) of the cell, so that the engine's path (which multiplies by (1 − r_t))
   reproduces the measured year-5 spread exactly. Report the implied terminal-year spread as a diagnostic.
   - When r̄₅ ≥ 0.9, the rescale is capped at 10×.
   - This is stamped, and it is a stated convention.
   - To be implemented at integration.

**Not adopted and recorded:** the coder's own deletion of four regenerable vintage folders (its own output) breached
the no-deletion rule as written. No harm was done, and future briefs say "regenerate into a new folder; never delete".

## Addendum G (2026-10-07, the coordinator's rulings on the T-harness report)

**Accepted:**
- the shared layer: the vendored production extractor, inputs as known at T, outcomes first reported, provenance
  states, quarterly facts;
- the delisting classifier with strict readers off by default;
- the holdout run ledger.

**Rulings on the coder's questions:**
- **5:** a debt component never tagged in any held year counts as 0, the untagged-marker convention used for
  goodwill, and is stamped.
- **6:** keep the production 80% vote for partial 10-K/As (consistency with live).
- **7:** keep the strict first-report rule (7.3% fewer fiscal years) for point-in-time correctness.
- **8:** no FX source. Filers with no dollar facts stay out, counted.
- **9:** the stale screener `cik_map.json` (APA mapped to the old Apache CIK) is a production screener defect. It is
  flagged as a separate task, not fixed in this rebuild.
- **11:** the store is rebuilt with quarterly facts at integration.
- **12:** Muse swaps to `PitQuarterSource(pit)` at integration.

**Go to the operator as one batch of free downloads** (questions 1–4 and 10):
- SEC bulk `submissions.zip`: acceptance timestamps and delisting counts for every filer;
- EDGAR filing headers for the SIC and name as filed;
- merger, 8-K and bankruptcy-plan texts for delisting outcomes;
- SEC Financial Statement Data Sets: dimensional facts such as APA's revenue;
- Yahoo daily unadjusted closes and corporate actions for every filer with a ticker.

**Until then, the price limit is binding:** the only local price file is adjusted, month-end, and covers today's
listings only.
- **Development diagnostics** (structure, IV ÷ price by family) may use it, stamped `adjusted_proxy`. Dividend
  adjustment biases levels by a few percent and survivors only are covered.
- **No gate figure (B1–B4) computed on it counts.** Development B1–B4 figures on the proxy are labelled provisional.
- **Gate 1's holdout requires raw daily closes,** and a measured unpriceable share for the gate's universe (market cap
  ≥ $300M at T), not for the whole filer archive.

## Addendum H (2026-10-07 ~02:45, development round 1 read; the structural fixes for round 2)

**Round 1** (`review-2026-10/rebuild-gate1` `13d8c80`; report `scratch/rev23/gate1_dev/report_b/gate1_dev_report.md`)
failed structurally. Every figure is provisional (monthly raw prices, survivors only).
- **Median IV ÷ price by family:**

  | Family | Median IV ÷ price |
  |---|---|
  | Operating | 0.14 |
  | Financial | 1.30 |
  | Commodity | −0.08 |

- 70.9% of names fall outside 0.4×–2.5× their price.
- 57% of draws are invalid, and the median is taken over the valid draws only.
- B1 and B2 fail. B4 passes: the priors forecast revenue and margin better than the naive baseline.

**The coordinator's diagnosis,** from the prior-shape diagnostics, with each cause structural:
1. **`margin_target` spread is absurd, and that is the coordinator's own error in Addendum F 4.** Rescaling by
   1/(1 − r̄₅) (median factor 3.3, capped at 10 for 22% of names) gives a median P10..P90 width of 1.05, about ±50
   margin points. It generates negative-margin draws, invalid draws and low medians.
2. **`g_terminal` is the wrong concept.** The prior is the realized K-year growth of companies, not a perpetuity rate,
   so 99.9% of names have a P90 at or above WACC.
3. **`ronic` comes from incremental ROIC** (ΔNOPAT ÷ ΔIC over three years), which is noise-dominated. Its P50 is
   below WACC for 80% of names, so every dollar of growth destroys value.
4. **Pre-profit companies** (mainly biotech) get margin targets from their own loss history: negative values in
   perpetuity, IV per share as low as −806,016.
5. **Regulated utilities and pipelines:** the Greenwald maintenance estimate counts rate-base growth as maintenance,
   because revenue does not track the asset base. The result is negative FCFF forever (Utility (General) median
   −0.52, Oil/Gas Distribution −0.96).
6. **Dates 2017–2018 cannot be valued:** history starts at FY2009 and the year-5 residuals need five later years.

**Fixes for round 2** (textbook conventions or measured; none names or tunes to a stock):
- **H1, margin path.**
  - Replace the asymptote-plus-rescale form with a direct year-5 level: the engine draws the margin level at year 5
    from the measured distribution of the level five years on (no rescale);
  - it moves from m0 to that level along the measured curve shape, m_t = m0 + (m5 − m0)·(1 − r_t)/(1 − r_5) for
    t ≤ 5, and holds it after year 5 (the A2 retention levels off after k ≈ 3).
  - Addendum F 4 is withdrawn.
- **H2, terminal growth (Damodaran's convention).**
  - It is not drawn from realized company growth. Terminal growth = min(the risk-free rate at T, the 3.75% long-run
    anchor), one value per date.
  - If the decay path reaches a negative rate by the last explicit year, that rate continues as terminal growth (no
    floor).
  - Long-run uncertainty lives in the growth path and the margins, not in the perpetuity rate.
- **H3, return on new capital.**
  - Years 1–N: the company's own trailing 3-year average ROIC level (NOPAT ÷ invested capital), fading along the
    measured ROIC-excess retention to the median ROIC of its industry at T, measured on the point-in-time population
    of that industry and date.
  - **Terminal:** the industry median, floored at WACC. In perpetuity a company does not keep investing below its
    cost of capital (the textbook stable-growth convention).
  - Spread: the measured dispersion of the company's ROIC-level path, not of incremental ROIC.
- **H4, scope (stated, like REITs).** These are `family_not_built` and counted:
  - pre-profit companies: operating income ≤ 0 in at least 3 of the last 4 fiscal years known at T. They need a
    survival and option model, a later family;
  - regulated utilities and pipelines: SIC 4900–4949 and 4922–4925. They need a rate-base model, a later family.
- **H5, invalid draws.**
  - With H1 and H2, terminal growth ≥ WACC can only arise when the risk-free rate exceeds WACC, which is
    near-impossible.
  - Every remaining invalid draw is reported by reason.
  - **A name with more than 5% invalid draws is refused** with that reason, never valued on the survivors of its
    draws.
- **H6, dates.** Development is re-dated to 2019-03-31 to 2021-12-31 for return metrics, whose 12-month outcomes end
  by 2022-12-31 so they never overlap the 2023–2024 holdout years. 2022 dates are used for forecast-quality metrics
  (B4) only. The holdout stays 2023–2024.
- **H7, yardsticks.**
  - The old engine cannot be computed point in time (its anchors are not stored before 2026-05), so it is dropped from
    the yardsticks, recorded.
  - B3(c)'s comparator becomes a stated absolute floor: the IQR of ln(IV ÷ price) ≥ 0.30, for the operator to approve
    with the other bars.
  - A missing yardstick is imputed at the cross-sectional median rank, with an indicator, so names missing gross
    profit stay in B1 and B2; coverage is reported.
- **H8, documents.** Fix `documents.py`'s `item_span` for headings in table rows and for wrapped headings. This is
  pack v2 content, versioned by the pack v2 template version, not the production `PACK_REVISION`. Older submissions
  pages for large filers wait on download D1.
- **H9, development prices.** The operator-approved raw monthly pull of 2026-10-01
  (`data/priors/_inputs/prices_monthly_raw.json`, `auto_adjust=False`) is accepted as the development price source,
  stamped. Addendum G's premise that only an adjusted file existed was wrong. The holdout still needs raw daily closes
  (D5).

Round 2 runs the same harness on the re-dated development set. The coordinator reads its diagnostics before any
further change.

## Addendum I (2026-10-07, development round 2 read; the structural fixes for round 3)

**Round 2** (`rebuild-gate1`, H1–H9 at `c8626d0`..`317646d`; report `gate1_dev/round2/report_a/`): H5 refused about
99% of operating names.
- **Why:** the measured year-5 residual spreads are population-wide absolute widths. A margin width of 0.226 on a
  median level of 8.5% makes P10 non-positive for 75% of names.
- **Valued:** almost only financials, at a median of 2.55× price, from a cost of equity of about 4.4% (beta about
  0.6).
- **H5 switched off as a diagnostic only:**

  | Measure | Round 2, H5 off | Round 1 |
  |---|---|---|
  | Operating median IV ÷ price | 0.70 | 0.14 |
  | Commodity median IV ÷ price | 0.37 | −0.08 |
  | Non-positive IV | 7% | 28% |

  The H1–H3 direction is right; uncertainty and financials are wrong.

**Fixes for round 3:**
- **I1, heteroskedastic spreads.** Margin-level and ROIC-level residuals are measured conditional on the company's
  current level band (quintiles of the current level within the cyclicality and sign cell, merged to n ≥ 50 by the
  stated rule). The spread is measured, not scaled by hand.
- **I2, no impossible draws from economic states.**
  - In a draw whose long-run NOPAT margin ≤ 0 or return on new capital ≤ 0, growth reinvestment cannot be priced. Such
    a draw gets no growth after year 5 (no reinvestment), and its NOPAT path stands, negative if so.
  - Equity per draw is floored at 0, the textbook limited-liability convention.
  - These draws are valid and counted by rule. Invalid stays only for numerical impossibility (the risk-free rate at or
    above WACC).
  - H5's refusal applies to the remaining invalid share.
- **I3, cost of equity for financials: the levered industry beta,** never unlevered and relevered by Hamada.
  Damodaran's convention for financial service firms is that debt is raw material.
- **I4, financial terminal excess return.**
  - The terminal ROTE excess over the cost of equity is the industry median excess × the measured long-run retention
    of ROTE excess (the plateau of the measured curve at its longest k with n ≥ 50), not the full median
    permanently.
  - Operating terminal RONIC stays max(industry median, WACC). It prices growth only, not the existing base.
- **I5, MIN_N enforced.** A prior cell with n < 50 after the stated merges refuses the input, named (for example the
  ROTE residual for the 2020 vintage, n = 25).
- **I6, Muse prompts P3 and P4** are revised to the new inputs: `ronic` is the ROIC level path, and `g_terminal` is no
  longer a judgment input (H2). The template version is bumped.

**The round-2 deviations accepted as stated:**
- "Items 1 and 2";
- the H3 financial reading (superseded for the terminal by I4);
- margin-path clipping;
- survivor-only industry medians, stamped;
- `data/priors_v2` as the default.

## Addendum I, round-3 results (2026-10-07 ~05:05; `gate1_dev/round3/report_a/`, PROVISIONAL)

**Coverage:**
- 11,838 valued name-dates at $300M or more: operating 10,603, commodity 746, financial 2,897.
- **2019 dates value nothing:** history starts at FY2009, so the 2018 vintage has margin residual n = 9, and the ROTE
  residual is below 50 before the 2021 vintage.
- **Development is therefore 8 return dates (2020–2021) plus 4 B4 dates (2022).** Accepted as a data limit; XBRL
  history cannot go earlier.

**Bars:**

| Bar | Result | Status |
|---|---|---|
| B1 | 0.081, 90% interval [0.024, 0.126] | pass |
| B2 | +6.75 pp (residual +3.9) | pass |
| B3(a) | 43.0% outside 0.4×–2.5× | fail |
| B3(b) | financial −10.1 | fail |
| B3(c) | 1.295 | pass |
| B4 | revenue 0.114 against 0.126, margin 0.0283 against 0.0286 | pass |

**Median IV ÷ price:** operating 0.50, financial 1.54, commodity 0.19.

**Draw rules:** 31% of operating draws (41% of commodity draws) have no growth after year 5; 29% (50%) are floored at
zero.

**The coordinator's reading.** The remaining level bias has a structural candidate already named in the 10-01 review
(MRI's implied ERP). Damodaran's implied ERP is solved from the index price with analysts' consensus growth, while the
engines' cash flows follow population base rates that fade growth far faster. The pairing undervalues systematically.

**Round 3b, a diagnostic only,** measures it: the per-date "closure ERP" that makes the engine value the ≥ $300M
universe at its market cap at T (point in time), the resulting diagnostics, and per-family closure. It changes no
default.

If the hypothesis holds, the choice goes to the operator: an engine-consistent ERP per date (the ERP implied by our
own cash flows on the whole market at T) against Damodaran's. This would reverse Addendum C 5 / section 3.4's
"closure as a diagnostic only".
- **The case for the change:** a single scalar per date shifts levels, not ranks, so B1 and B2 (cross-sectional) are
  untouched. The cost is that the IV becomes market-consistent rather than absolute. That is ChatGPT's concern, and
  it is recorded.
- **Not adopted** until the diagnostic is read.

## Addendum J (2026-10-07, the coordinator's rulings on ChatGPT's review of cross-check 3)

Each point is ruled adopted, adapted or rejected, with a reason (operator rule: other AIs are teammates' advice).

1. **Closure ERP stays a diagnostic until a level decomposition has run. Adopted.** Before any change to the premium,
   decompose the operating 0.50× level by swapping one component at a time: the ERP source, terminal growth, the
   terminal RONIC rule, growth persistence, the margin path, reinvestment. Report each one's contribution.
2. **"Terminal growth = min(risk-free, sustainable nominal growth) rather than min(rf, 3.75%)." Rejected.** That is
   already the rule: 3.75% is the long-run nominal growth anchor. ChatGPT's worry was a low rf giving a low terminal
   value, but a low rf lowers the discount rate by the same amount, so the Gordon spread (cost of capital − g) stays
   β·ERP whenever g = rf. The decomposition (item 1) still reports the terminal-growth swap, to confirm this.
3. **Terminal RONIC must not be the industry median forever. Adapted.** The same rule as financials (Addendum I 4):
   terminal RONIC = WACC + κ × (industry median ROIC − WACC), with κ the measured long-run plateau of ROIC-excess
   retention.
   - It is not forced to WACC: the measured plateau is about 0.25–0.40, not 0.
   - It may lower values. That is accepted, because it is principled.
4. **"Loss-making draws stop growing." Rejected as a misreading,** though the zero mass is taken seriously.
   - The I2 rule acts on a draw's long-run state (margin ≤ 0 or return ≤ 0 in perpetuity), not on current losses. A
     company losing money today still grows into its drawn year-5 margin.
   - The 30% (operating) and 50% (commodity) zero-floored draws are a diagnostic. The decomposition reports which
     component drives them.
5. **B1 on monthly dates. Adopted.** The holdout uses month-end dates 2023-01-31 to 2024-12-31 (24 dates), inputs as
   known at each month-end. Inference is a wild-cluster bootstrap by date (12-month returns overlap).
   - **Pass rule kept as an interval rule, the coordinator's call:** the pooled incremental coefficient, with the
     lower end of its one-sided 90% wild-cluster bootstrap interval above 0. A point estimate above zero alone would
     pass a noise engine about half the time.
   - Also reported: the share of monthly coefficients that are positive.
6. **B2 two levels. Adopted.**
   - Pass: the incremental (residual) top-minus-bottom quintile spread > 0.
   - Strong pass: ≥ +3 pp.
   - The raw spread is reported.
7. **B3. Adapted, not dropped.**
   - The 15% extremes cap, the ±10-point family band and the IQR floor become diagnostics, as ChatGPT advises: a sound
     engine may make many extreme calls.
   - **One level bar stays, because the product needs it:** the universe median IV ÷ price must lie within
     [0.67, 1.5]. Verdicts buy on a margin of safety measured against the IV level. An engine that puts the median
     stock at 0.5× its price would never say "buy", whatever its ranking. Ranking alone (B1, B2) does not make the
     verdicts usable.
   - Family medians are reported.
8. **B4 strengthened. Adapted.**
   - Hard: P50 beats the naive baseline on next-fiscal-year revenue growth and operating margin (operating and
     commodity families), and on ROTE (financial family).
   - Reported: P10..P90 coverage (target 80%; the calibration layer exists to correct it) and directional accuracy.
   - Commodity production and realized-price forecasts are rejected for now: the commodity engine does not forecast
     them.
9. **B5, stability. Adopted as a hard requirement on direction, with the rest reported.**
   - Hard: B1 and B2 keep their sign under all three delisting bounds, and with the top 1% of |residual| observations
     removed.
   - Reported: the price-provider variant, ERP sensitivity, and sector- and size-neutral versions.
10. **The freeze covers more than the commit. Adopted.** The freeze file names:
    - the code commit;
    - the hashes of the point-in-time store and the price snapshot;
    - the Damodaran files and the priors vintages;
    - the industry map;
    - the engine configuration;
    - the random seeds and Python package versions.

    The Muse items (model hash, quantization, context, sampling, prompts) belong to gate 2's freeze.
11. **Point-in-time classification. Adopted.** The family and the Damodaran industry for holdout dates come from the
    SIC as filed at T (the D2 headers, downloading). The industry for that SIC is a SIC→industry crosswalk built from
    `indname`, not the company's 2026 industry row. Current-dated use stays stamped where headers are missing.
12. **"The 2026 extractor may interpret 2020 tags with later knowledge." Rejected as negligible.** A tag introduced
    later cannot appear in an earlier filing, and the extractor reads only tags present in that filing. Mapping
    knowledge is design knowledge, not outcome information. The 99.96% parity and the first-filed checks stand.
13. **Freeze after the RONIC fix and the decomposition; development 2020–2021 is engineering evidence only.
    Adopted.** No engine change may follow from 2023–2024 results.

The registration draft is revised to version 2 by these rulings, for the operator's approval.

## Addendum K (2026-10-07, round 3b read: the ERP decision)

**Round 3b** (`gate1_dev/round3b_closure/`, a diagnostic). The closure ERP that makes the engine value the ≥ $300M
universe at its market cap at T:

| Period | Damodaran ERP (mean) | Closure ERP (mean) | Gap |
|---|---|---|---|
| 2020–2021 | 4.96% | 2.57% | −2.4 pp |
| 2022 | 4.24% | 3.93% | −0.3 pp |

- The engine-to-market sum ratio runs from 0.47 (2020-12-31) to 1.33 (2022-06-30).
- Under the closure, the median IV ÷ price goes from 0.61 to 0.93 overall, and operating from 0.50 to 0.78.
- **B3(a) still fails:** 38.1% outside.
- **Commodity has no ERP root on three dates:** its level is an engine problem, not a premium problem.
- **B1 and B2 barely move:** B1 0.068, 90% interval [0.010, 0.114]; B2 residual +5.8 pp.

**Ruling: keep Damodaran's dated implied ERP; the closure ERP stays a diagnostic.**
- It is not a stable constant: the gap is −2.4 pp in 2020–2021 and −0.3 pp in 2022, and it moves with the market's
  price level.
- Adopting it would make the IV track the price, which is ChatGPT's concern and is now shown in data. The engine's
  2020–2021 "too low" level partly coincides with a market peak that later fell; that is not proof of anything, but
  it is no reason to calibrate it away.
- The remaining level and commodity problems go to the decomposition (Addendum J 1), together with the terminal-RONIC
  change (J 3).

**On the coder's questions:**
- cap-weighting versus median: moot while the closure stays a diagnostic;
- an intra-year ERP update: Damodaran publishes monthly implied ERPs since 2008 on his site. Using the monthly file
  is a principled refinement for the monthly holdout, and is queued; the file is part of the approved Damodaran set;
- the commodity level: yes, its own decomposition.

## Addendum L (2026-10-07 ~08:50, round 4 read; the last change before the freeze)

**Round 4** (`rebuild-gate1` `8154bad`; `gate1_dev/round4/`; v2 bars on 24 development month-ends; PROVISIONAL, with
survivor prices and the three bounds identical):

| Bar | Result | Status |
|---|---|---|
| B1 | 0.083, lower bound 0.052, 87.5% of months positive | pass |
| B2 | residual +3.59% | strong pass, barely |
| B3 level | median 0.537 against [0.67, 1.5] | fail |
| B4 | all forecasts beat naive; margin by 0.0002 | pass |
| B5 | direction holds | pass |

**The decomposition** (operating, base median 0.457):

| Swap | Change in median |
|---|---|
| ERP to closure | +0.27 |
| Zero growth reinvestment | +0.21 |
| Terminal g 3.75% flat | +0.11 |
| Margin held | +0.06 |
| Half width | +0.05 |
| J3 against the industry median or WACC | ±0.02 |

The ERP is the largest lever, as hypothesized in Addendum I. No other single swap closes the band.

**The coordinator's ruling: one principled change, decided before its result, then freeze whatever development
shows.**
- **L1, an engine-consistent implied ERP.**
  - **The problem:** Damodaran's monthly implied ERP solves r in his index model: S&P 500 level, trailing 12-month
    cash flow with sustainable payout, analysts' expected growth for 5 years, then terminal growth = the risk-free
    rate. Our cash flows do not use analysts' growth. The inconsistency was named in Addendum I and the 10-01 review;
    this change follows from it, not from B3.
  - **The fix:** recompute the same model with every input from Damodaran's own row except the 5-year growth. That
    growth is replaced by the engine's own expectation: the cap-weighted mean of the P50 revenue-growth path for
    years 1–5 across the gate universe at T (point in time: priors vintage and market caps at T).
  - Damodaran's other inputs and his solution method stay unchanged.
  - **Why this is not the closure ERP:** it never uses the engine's valuations. It keeps Damodaran's index method and
    replaces only the one assumption that conflicts with the engine.
  - Damodaran's ERP is reported beside it as a sensitivity.
- **L2, the freeze rule.** After round 5 (L1 only), the engine is frozen whatever the development figures, B3
  included. No further level change is made. If B3 still fails in development, the holdout runs anyway and B3 is
  judged there as registered.
- **L3, classification for the holdout.** The holdout waits for the D2 headers (at 55,000 of 181,656 at 08:40; about
  5 more hours), so the SIC as filed at T is used for every holdout date. Current-dated stamps are not allowed in the
  holdout.
- **L4, prices for the holdout.** The D5 daily raw closes (complete: 9,738 tickers) are the valuation price, with
  outcomes from the daily data. Delisting outcomes use the D1 event index plus the D3 documents through the strict
  readers. Unresolved events stay under three bounds.

**Accepted from the round-4 report:**
- the monthly ERP column, with a 62-day staleness refusal;
- the bootstrap-t variant for B1;
- B5 trimming;
- B4 on ROTE′₁;
- crosswalk fallbacks at the 3- and 2-digit SIC level, stamped;
- gross profitability imputed for 46% (reported).

## Addendum M (2026-10-07, round-5 report read: the L1 method, survivorship and prices)

**L1, the reproduction check failed as designed,** so round 5 did not run.
- Damodaran's "ERP (T12 m with sustainable payout)" needs earnings and ROE, which are not in his monthly row. The best
  cash-flow column (T12) has a median error of +8 bp but a maximum of 178 bp.
- **Ruling: option B (a differential).** The engine-consistent ERP = his published sustainable-payout ERP + Δ, where Δ
  is the change in the solved required return of the reproduced T12 model when only the 5-year growth is swapped (his
  expected growth replaced by the engine's cap-weighted P50 growth). The reproduction error largely cancels in Δ,
  because both terms come from the same model.
- **Reported per date:** his ERP, Δ, the result, and the engine growth used.
- This is a method choice made before any round-5 figure exists. L2 (freeze after round 5) stands.

**Survivorship in the holdout (the round-5 finding).**
- **The gap:** D5 holds no delisted names (SIVB, FRC, TWTR, ATVI are absent), and the id map is today's tickers. Every
  company that left between T and the outcome date drops out of the holdout universe at T. The registered three bounds
  would then be identical and hide the bias. Failed companies often look cheap to value engines, so that bias can
  flatter B2.
- **Ruling (a measurement rule, set before any holdout figure; the bars are unchanged):**
  - **M1, a missing-name census per holdout date:** every company with an annual report accepted before T, no D5 price
    at T, and a delisting event in D1 after T, with public float ≥ $300M on its latest cover page before T
    (`dei:EntityPublicFloat`). Counted by event class.
  - **M2, a price proxy at T** for those names only: public float ÷ shares outstanding, from the latest cover before T,
    stamped `price_proxy_public_float`. Their engine IV is computed as for every name, so each can be placed in a
    quintile.
  - **M3, their outcome:**
    - bankruptcy (8-K Item 1.03 with equity cancelled, or a strict-reader resolution) is −100%;
    - an acquisition whose consideration a strict reader resolves gets the deal value against the proxy price;
    - everything else is unobservable.
  - **M4, the three bounds now include these names:** unobservable ones are excluded, at −100%, or at 0% (the proxy
    price held). The registered pass, fail and not-decided rule applies over them as written. This restores what the
    bounds were registered to do.
  - **M5, reader scope:** the strict cash-consideration reader is scoped to the sentence stating the per-share merger
    consideration. A cash-and-stock election in that sentence still declines. Yield is reported before and after.
- **M6, D5 gaps:** for the 17 tickers whose D5 history starts late (QRVO and others), the operator-approved monthly raw
  file is the fallback price at month-end valuation dates, stamped `price_monthly_fallback`. Outcomes use daily data
  where it exists, else monthly, stamped.

**Deviation noted:** the coder ran `rm -rf` on its own partial output, which breaches "never delete", like two earlier
coders. No harm was done. From now on, briefs require a new output folder per attempt.

## Addendum N (2026-10-07 ~11:45, round 5 read; the engine is frozen)

**Round 5** (`rebuild-gate1` `c7d7a4f` is the frozen engine; `gate1_dev/round5_run/`; PROVISIONAL):
- B1 0.082 (lower bound 0.051), B2 +3.44% (strong), B4 pass, B5 pass.
- **B3 median 0.624: fail,** but inside the band on 50% of dates (round 4: 4%).
- Family medians: operating 0.544, financial 1.984, commodity 0.253.
- The engine-consistent ERP averages 4.36% against Damodaran's 5.04% (Δ −68 bp, largest in 2021 when analysts' growth
  ran at 8–13%).
- **The engine is frozen (L2).** The holdout judges B3 as registered.

**Rulings on the census questions** (measurement rules, set before any holdout figure; the bars are unchanged):
1. **An event after the 12-month horizon** means the company still traded at the horizon and D5 merely lacks it, so
   it is not a death. Such names are **unobservable**, with bounds: excluded; 0% (price held); and the date's
   cross-sectional 10th-percentile 12-month excess return (pessimistic but possible). Literal −100% applies only to
   bankruptcies within the horizon.
2. **`exit_record_still_reporting` is dropped** from the census. By the classifier's own rule it is not a delisting of
   the common stock.
3. **One D1 event per company** (a missed later delisting after an earlier Form 25 for another security): a stated
   limitation, counted where detectable, not fixed.
4. **Shares for the price proxy:** the latest `dei:EntityCommonStockSharesOutstanding` on any cover (10-K or 10-Q)
   accepted before T, not only the 10-K's.
5. **Reader:** adopt the variant without "common stock of". In a target's consideration sentence that phrase names
   the shares being bought, not stock paid, so it is a false decline. Elections, exchange ratios and named acquirer
   stock still decline.
6. **The dividing line for the outcome horizon** is the D1 event date (delisting or merger close).

**Next:**
- the D2 headers complete (at 35,000 of 81,402 in the second pass at 11:41, 9 per second);
- the freeze file is written with every Addendum J 10 content and M6;
- the gate-1 holdout runs once on 2023-01-31 to 2024-12-31 month-ends;
- the result goes to the operator whichever way it lands. A pass goes straight on to gate 2.

## Addendum O (2026-10-07, rulings on the gate-2 runner report; `rebuild-gate2` `bf2e959`, `342e560`)

1. **Generation cap:** 16,384 tokens within the registered 32k context, with the per-request guard. Accepted. An
   overflow counts against G5 as written.
2. **The quarter forecast** (a G1 measurement rule, set before any gate-2 figure; the bars are unchanged). The engine
   forecasts fiscal years, so G1 compares **year-on-year changes**, which removes seasonality:
   - **Growth:** realized = the first quarter reported after T, against the same quarter a year earlier. Forecast =
     the arm's year-1 P50 growth.
   - **Margin:** realized = that quarter's operating margin minus the same quarter's a year earlier. Forecast = the
     arm's year-1 P50 margin minus its base-year margin.
   - **Financials:** ROTE as the coder stated (4 × quarterly net income ÷ tangible book at T), compared as a change in
     the same way.
   - Both arms are scored identically, so G1 stays a paired comparison.
3. **Classification is strict in the replay** (`--strict-classification`), the same as the gate-1 holdout (Addendum
   L3). The D2 headers cover filings from 2009 to October 2026.
4. **`cache/DEPTH_PAUSED` does not pause gate 2.** It is the production depth pipeline's switch, set for the paused
   baseline. Gate 2 uses its own `data/gate2/PAUSE`.
5. **The coder's fix to `valuation/muse/reverse.py`** (terminal growth from the date, Addendum H2) is accepted. It
   touches the Muse layer, not the frozen engine.
6. **The blocker found by this report:** `data/priors_v3` holds only the 2016–2021 vintages. Vintages 2022–2025 are
   built with the frozen code at `c7d7a4f`, unchanged. Building data with frozen code is not an engine change, and the
   2021 vintage is reproduced byte for byte first. They enter both freezes.

## Addendum P (2026-10-07, rulings on the Addendum-N implementation report; the last measurement changes before the freeze)

`rebuild-gate1` `b745522`, `917e265`, `e888a18`, `1dd4670`. The engine diff from `c7d7a4f` is empty.

**Accepted:**
- the par-value guard (decline direction; without it most "prices" were par values);
- the acquirer-stock guard;
- the slot names kept, with `bounds_basis` recording which basis fills the pessimistic bound.

**Rulings** (measurement rules; the bars are unchanged):
- **P1 (refines N1), the pessimistic bound by event class inside the horizon:**
  - **bankruptcy, `delisted_other` and `deregistered_other`:** −100%. An exchange delisting or deregistration without
    an acquisition is usually distress, and a pessimistic bound should treat it as one;
  - **an acquisition the reader cannot resolve:** the date's 10th-percentile excess return (acquisitions are usually at
    a premium);
  - **events after the horizon:** the p10 bound, as N1.
- **P2:** the p10 population is the gate universe (≥ $300M, non-census, measured). Confirmed.
- **P3, the reader residue declines on:** warrant, exercise price, liquidating distribution, redemption value, trust
  account, and SPAC cover-page text. That is the decline direction, so such names stay unobservable. Yield is
  reported again.
- **P4, the N3 misses are fixed, not just counted.** The census must use, for each company, the first qualifying exit
  event dated **after T** (all D1 events per company, `exit_record_still_reporting` excluded), not the company's first
  event overall. About 173 names per date were absent. That is a survivorship hole of the size this machinery exists
  to close.
- **P5:** a D3 accession still missing leaves its event unresolved and counted. It does not block the freeze.

**After P1–P5:**
- freeze readiness is rechecked (D2 headers complete through October 2026: 181,696 rows);
- the 2022–2025 priors vintages land;
- then the freeze file, then the gate-1 holdout, once.

## Addendum Q (2026-10-07, priors vintages 2022–2025)

- **Built with the frozen code** (detached at `c7d7a4f`, unmodified) into `data/priors_v3/2022..2025`, with 76,561,
  82,802, 87,183 and 91,170 observations; the hashes are in the build report.
- **2021 reproduction:** the decompressed observation table is byte-identical. The compressed file differs only in its
  gzip header timestamp, which feeds one field (`obs_sha256`) of `tables.json`; with that field set, `tables.json` is
  byte-identical. Accepted as reproduced. The gzip timestamp is a known non-determinism, not a content difference.
- **No look-ahead:** the builder's test suite passes, the same proof passes at vintage 2022, and the latest `filed_k`
  in each new vintage precedes its cut.
- **A pre-existing data quirk** (45–202 observations per vintage with a `filed_k` dated before the row's own
  year-end, in every vintage including development) comes from companyfacts and the frozen code. It is stated, not
  fixed. The engine is frozen.

## Addendum R (2026-10-07, rulings on the Addendum-P report; then the freeze)

`rebuild-gate1` `f4fd4b5`, `29bb2bd`; the engine diff from `c7d7a4f` is empty; readiness reports true.
- **R1:** the 729 missing D3 accessions are fetched. They belong to events the approved D3 download was meant to
  cover (merger, 8-K and bankruptcy texts for delisting events found via D1); P4 found more of those events. Same
  user agent and rate limit.
- **R2:** "declared a dividend or distribution" joins the P3 decline list (decline direction).
- **R3:** the 30-day gap that merges exit records into one event is accepted. `acquisition_weak` takes the p10 bound,
  accepted. "Redemption price/amount" is accepted. The document-level SPAC check is accepted.
- **R4:** the freeze names `data/sec_bulk/index_P4b` (with `events_all.json`) as the D1 input, and `data/priors_v3`
  vintages 2022 and 2023 (complete per the priors report) as the holdout priors.
- **Then:** the freeze, and the holdout once (`brief_gate1_holdout.md`).

## Addendum S (2026-10-07 ~16:15, the gate-1 freeze and the holdout launch)

- **The freeze:** `scratch/rev23/gate1_holdout/gate1_freeze.json`, sha256
  `6a3eb449527d47fd1d073f306ff827647f0fcf7d1407bd61ace24c0f616410c4`.
  - Code `07d07e7`, with the engine identical to `c7d7a4f`.
  - It covers every input of Addendum J 10 and R4 (store, daily prices plus the monthly fallback, cover index,
    `index_P4b`, D3 documents, `headers_raw.csv`, crosswalk, Damodaran, `priors_v3`, configuration, seeds, packages).
- **Phase 1 before it:**
  - R1: all 729 accessions were fetched;
  - R2: the reader resolves 154 of 432;
  - readiness true; D3 complete for every event that has a reader.
- **Launch:** the coder held the run because free RAM stayed below 1 GB. The coordinator checked: the commit charge is
  36.8 GB of a 77.6 GB limit, so memory pressure means paging, not out-of-memory failure. The holdout was launched
  once by the coordinator with **2 workers**. The worker count does not change results (deterministic seeds; round 4
  and round 5 reproduced bit for bit), so it is not a freeze content.

## Addendum T (2026-10-07 ~21:05): GATE 1 HOLDOUT RESULT — FAIL

- **The run:** once, 24 month-ends from 2023-01 to 2024-12, on freeze `6a3eb449…` (ledger hash `f47c6bcd…` is the same
  file with CRLF normalised; the file was last written 15:44, before the 16:01 start, and verified at run start).
  31,903 valued name-dates at $300M or more.
- **Report:** `scratch/rev23/gate1_holdout/report/gate1_dev_report.md`, scored with the frozen bootstrap settings (999
  wild-cluster draws, 2,000 resamples). The report labels the outcome "provisional", which is a template label: this
  is the registered holdout.

| Bar | Excluded | −100% | Last close | Outcome |
|---|---|---|---|---|
| B1 coefficient (one-sided 90% lower bound) | +0.005 (−0.020) | −0.026 (−0.048) | −0.022 (−0.043) | **fail** |
| B2 residual quintile spread | −1.14% | −4.58% | −2.86% | **fail** |
| B3 level, median IV ÷ price | 0.702 | 0.702 | 0.702 | pass |
| B4 forecasts | ROTE (financial) 0.0378 against naive 0.0376 | same | same | **fail** |
| B5 direction | fails | fails | fails | **fail** |

- **B4, the parts that passed:** revenue growth (operating 0.070 against 0.095; commodity 0.122 against 0.246) and
  operating margin pass. Only the financial ROTE misses, by 0.0002.
- **Registered outcome: FAIL** (hard bars fail under all three bounds).
- **Consequences under the registration:** Muse GPU work (gate 2) does not start. 2023–2024 is spent as a holdout. Any
  engine change from here needs a new holdout named before it starts.

**What the result says** (the coordinator's reading; not a basis for tuning on 2023–2024):
1. **The engine forecasts fundamentals better than naive** (revenue growth error about 25% lower), but its ranking of
   value ÷ price added no information beyond earnings yield, FCF yield, profitability, return on capital and momentum
   in 2023–2024. Development's positive B1 and B2 (2020–2021) did not carry over: one regime, as ChatGPT warned
   ("enough to freeze, not enough to claim performance").
2. **The survivorship bounds make it worse** (B2 −4.6% at −100%): companies that later failed sat on the cheap side.
   The engine does not see distress, the classic value trap.
3. **The level (B3) now passes,** at a median of 0.70× price; the engine-consistent ERP fixed the level.

## Addendum U (2026-10-09, rulings on ChatGPT's and Gemini's reviews of the gate-1 failure)

2023–2024 is spent. With 2020–2022 it is now **development**. No engine change happens until the forensic stage below
has been read.

**Adopted:**
1. **Forensics first, no model change (both reviewers).** Stage 1 below.
2. **A horizon test** at 3, 6, 12, 18, 24 and 36 months where elapsed (ChatGPT). Separates "the value is wrong" from
   "12 months is too short".
3. **IV attribution** (ChatGPT): explicit years, fade years, terminal; and the share of the cross-sectional IV
   spread that comes from the forecast inputs. Plus capped and removed terminal-value variants (ChatGPT; Gemini's
   duration point).
4. **The oracle valuation** (ChatGPT, the priority): the frozen engine fed the fundamentals that actually happened
   (first reported), with no price. It decides whether the forecast-to-value mapping or the output itself is the
   problem.
5. **Distress stratification, then a survival layer** (both reviewers):
   - **Formula:** P(going concern) × going-concern value + P(distress) × recovery.
   - **Variables:** principled solvency variables (liquidity, leverage, coverage, cash burn, maturities, plus market
     equity and volatility where useful, Gemini's distance to default).
   - **Calibration:** point in time, on the D1 bankruptcy and distress-exit events.
   - **Rejected, Gemini's exclusion of the bottom solvency decile:** annotate, never silently gate. Weighting by
     probability does the work.
6. **Within-family ranking** (Gemini). Tested in Stage 1. B1 and B2 already used industry effects, which are finer
   than families, so the effect may be small. Measured, not assumed.
7. **A factor decomposition** (ChatGPT): size, beta, leverage, liquidity and family, beside the five yardsticks.
8. **Summary statistic** (ChatGPT): median against mean against quantiles of the IV distribution, tested as
   predictors.
9. **The expectation gap as a primary signal** (both reviewers; ChatGPT's three-signal output, Gemini's reverse-DCF
   delta):
   - the engine's P50 fundamentals minus what the price implies for the same quantities, under the same frozen engine;
   - tested in Stage 1 on development data;
   - Muse stays price-blind in pass 1.
10. **Stop touching the ERP** (ChatGPT). The failure survived every ERP variant.
11. **B3 becomes a diagnostic** in the next registration (ChatGPT). The level is calibration, not performance.
12. **The next holdout** (both reviewers): month-ends 2025-01 to 2025-09, named now and untouched. Reported as a full
    distribution, with fundamental-realization tests (high power) beside returns. Not a lone 9-date significance
    test, and forward evaluation follows.

**Adapted:**
- **The small Muse diagnostic (ChatGPT) cannot use 2023–2024 cases.** Muse's knowledge runs to about August 2025, so it
  knows those companies' fates (SVB, for example). It runs instead on post-cutoff dates (2025-10 to 2026-03).
  - **Sample:** 30–50 companies stratified by the code's cheap and expensive calls and by family.
  - **Question:** does Muse flag distress, one-offs, cyclicality, moat and capital intensity that the code misses,
    judged against what the companies filed afterwards (going-concern language, impairments, guidance cuts, defaults)?
  - **Timing:** after Stage 1, and only Stage 1's distress definition decides what counts as a miss.

**Rejected:**
- **A terminal exit multiple faded to the industry EV/EBITDA (Gemini).** It imports market pricing into intrinsic
  value, which is circular. The capped-terminal variants in Stage 1 measure the duration effect instead.
- **Relaxing B1's incremental requirement because the engine shares inputs with the yardsticks (Gemini).** Adding
  information beyond those yardsticks is the whole point. Otherwise use the yardsticks.
- **Analyst-revision outcomes (Gemini).** No consensus history exists (Addendum C). Fundamental realization replaces
  it.

**Stage 1, forensics** (CPU only, frozen engine `c7d7a4f` unchanged; diagnostics instrumented around it; development
data 2020–2024):

| Item | Test |
|---|---|
| F1 | Horizons, 3–36 months |
| F2 | By family |
| F3 | IV attribution and terminal-value variants |
| F4 | Distress strata |
| F5 | Factor decomposition |
| F6 | The oracle valuation |
| F7 | Median against mean against quantiles |
| F8 | The expectation-gap signal |
| F9 | Within-family ranking |

**After Stage 1:** the coordinator rules on Stage 2 (structural changes, starting with the survival layer and the
output redesign), then the next registration for 2025-01 to 2025-09, for the operator's approval.

## Addendum V (2026-10-09 ~07:20, Stage 1 forensics read; the Stage 2 rulings, made by the coordinator under the operator's overnight mandate)

**Stage 1** (`review-2026-10/forensics` `f473127`; `scratch/rev23/forensics/analysis/q20_final/`). 20 quarter-ends,
2020–2024, 25,164 name-dates at $300M or more. The pipeline reproduces the stored holdout records bit for bit.
- **The oracle works and the engine's P50 inputs do not.**
  - Oracle residual spread +16.2/+12.0/+13.2 pp at 12 months (all three bounds significant, IC 15.3).
  - Engine P50: +0.45/−2.1/−0.95.
  - The forecast-to-value mapping keeps the signal. The ranking variable is what loses it.
- **The engine's forecasts predict realized fundamentals far beyond what the price implies.** Growth coefficient 1.01
  against 0.07; margin 0.70 against 0.17. The forecasting is real.
- **The median of the draws discards the signal; the mean keeps it.**

  | Ranking variable, 12 months | Residual spread | B1 coefficient (lower bound) |
  |---|---|---|
  | Median | +1.17/−1.48/−0.33 | +0.043 |
  | Mean | +7.5/+4.1/+5.7 | +0.152 (+0.097) |

  The mean survives size, beta, volatility, liquidity and leverage controls (+6.1/+3.2/+4.8).
- **Distress:** the least solvent tercile inverts (−9.4 at 12 months), and the other two together give +4.9/+2.3/+3.1.
- **Commodity is inverted:** 12-month IC −8.9, and the oracle does not fix it.
- **Small effects:** within-industry ranking is a small gain; capping the terminal value or ranking within family moves
  little.

**Stage 2, the rulings** (each with an economic reason first, the evidence second):
- **V1, the value is the expected value (the mean of the draws), not the median.**
  - **Economic reason:** equity is a limited-liability claim, convex in the business outcome. Its price is an
    expectation of discounted payoffs, so the expectation is what is comparable with price. The median was a default
    taken without that reasoning.
  - **Evidence:** F7.
  - **Guard:** the result must hold with the draw dispersion (P90/P10 ratio) as an extra control, so that "mean ÷ price"
    is not just a volatility bet.
- **V2, a survival layer.**
  - **Formula:** value = mean IV × P(survive 12 months) + recovery × P(fail), with equity recovery 0 (equity is usually
    wiped out in a bankruptcy; stated).
  - **Model:** P(fail) is a logistic model on point-in-time solvency variables (current ratio, net debt ÷ EBITDA,
    interest coverage, operating-cash-flow sign, cash runway, and the naive distance to default from daily prices).
  - **Training:** D1 bankruptcy and distress exits within 12 months, with an expanding window. A date T uses only events
    resolved before T. The coefficients are fitted on data, not chosen.
  - **Economic reason:** a going-concern value is conditional on survival.
  - **Evidence:** F4.
- **V3, commodity is out of scope** (`family_not_built`, like REITs). It is inverted even under the oracle, which is a
  structural defect of that engine (mid-cycle normalization, or no commodity-price input). It is redesigned later,
  never patched.
- **V4, verdict quintiles rank within industry** (F9). B2 is already industry-neutral, so this changes the verdict
  selection, not the bar.
- **V5, the expectation gap is reported** (engine P50 against price-implied) **but is not the ranking variable yet.**
  Its rank IC is below IV ÷ price, and the mean-IV result is the stronger structural fix. It is revisited with Muse.
- **V6, no change** to the ERP, the terminal value, the priors or the engines' arithmetic.

**The development pass rule before any holdout** ("no more failures": the holdout is spent only on convincing
development evidence). On the 20 quarter-ends from 2020 to 2024, with V1–V4:
- B1 lower bound > 0 under all three bounds;
- the B1 point estimate > 0 under all three bounds in each sub-period, 2020–2022 and 2023–2024;
- the B2 residual spread > 0 under all three bounds, in each sub-period;
- V1's dispersion guard holds.

If any of these fails, the holdout is not run, and the operator gets the evidence.

**The new holdout:** 9 month-ends from 2025-01-31 to 2025-09-30, untouched until now. The bars are registered before
the run in `REGISTRATION_gate1b.md`.

## Addendum W (2026-10-09, the gate-1b result and the decision that follows)

**Development check** (Addendum V rule, 20 quarter-ends 2020–2024, configuration V1 + V2 + V3): **passed all four
conditions.**

| | B1 (lower bound), three bounds | B2, three bounds |
|---|---|---|
| All dates | +0.164 (+0.103) / +0.141 (+0.080) / +0.176 (+0.096) | +8.0 / +4.6 / +6.1 |
| 2020–2022 | +0.24 / +0.20 / +0.26 | +10.0 / +6.4 / +7.7 |
| 2023–2024 | +0.13 / +0.11 / +0.11 | +5.0 / +2.0 / +3.7 |

- The survival layer is weak (AUC 0.65; scores correlate 0.9999 with and without it). V1, the mean value, carries the
  signal.

**The gate-1b holdout, run once** (9 month-ends 2025-01 to 2025-09, untouched before; freeze `41102c98…`, ledger hash
`4e9b2554…` with CRLF normalised; 11,843 name-dates):

| Bar | Result | Status |
|---|---|---|
| H1 | +0.208 (lower bound +0.154) / +0.170 (+0.117) / +0.186 (+0.135) | strong pass, all bounds |
| H2 | +8.2 / +7.6 / +8.3 pp | strong pass, all bounds |
| H3 revenue growth | 0.054 against naive 0.067 | pass |
| H3 operating margin | 0.0221 against naive "margin held" 0.0189 | **fail** |

- H4: every variant is positive. H5: level 0.75.
- **Registered outcome: FAIL** (H3). It is recorded as such and not relabelled.

**What it means:** on a period the engine never saw, its expected-value ranking adds large, robust information beyond
the five yardsticks, under every survivorship treatment. That is the money-relevant property. Its operating-margin
forecasts, though, are worse than "margin held" (development was already a near-tie). The margin path the priors impose
is not better than persistence for next year. The value ranking works despite that, not because of it.

**The coordinator's decision** (overnight mandate; the operator can veto):
1. **No code-engine change and no relabelling.** The margin weakness is precisely the job the AI layer exists to do:
   reading filings for margin drivers (pricing, mix, costs, one-offs). Gate 2's G1 measures, paired, whether Muse beats
   the code engine on next-quarter margins and growth.
2. **Gate 2 proceeds,** a deviation from its "only if gate 1 passes" clause, recorded here.
   - **The reason:** the clause was written to avoid spending a GPU week on a base with no edge. The base now has a
     validated, untouched-holdout edge on ranking. Its only failure is the forecast dimension gate 2 tests directly.
   - **The CODE arm** is the Stage 2 configuration (V1 + V2 + V3 on the frozen engine).
   - Everything else in `REGISTRATION_gate2_DRAFT.md` stands as approved: the dates, 120 per date, G1–G6.
3. **The sequence:**
   - preparation (the date contexts, the seeded sample, the pins), with Stage 2's code merged into the gate-2 branch;
   - the gate-2 freeze;
   - the **10-company pilot** (timing only, outputs sealed);
   - the full run through the scheduled task.

## Addendum X (2026-10-09 17:11, the gate-2 full run started)

- **Prepared and frozen** on `review-2026-10/rebuild-gate2` `c0a8847`. Freeze `data/gate2/freeze/gate2_freeze.json`,
  sha256 `3535af55…`; sample `d1fefc76…` (600 = 468 operating + 132 financial; commodity out by V3).
- Both arms use Stage 2 (V1 mean, V2 survival trained on events resolved before T, V3).
- **The pilot** (10 company-dates, outputs sealed): about 726 s per model-running company, 6.3 Muse calls, no errors.
  The full sample is estimated at about 4 GPU-days.
- **Expected paired sample:** about 430. The engine refuses about 28% (trailing ROIC or operating income unavailable).
  This is recorded, not gated.
- **The full run** started 17:09 through the scheduled task `RS2-Gate2-Replay` (survives app updates; waits whenever
  the GPU is busy or used for gaming). The server loaded at 21,305 MiB.
- **Scoring:** after it finishes, G1–G6 per registration, with outcomes first reported after T (quarterly year-on-year,
  Addendum O 2).

## Addendum Y (2026-10-09, the leak and artefact audit of gate 1b; the coordinator's correction)

The audit (`review-2026-10/leak-audit` `2ee8af4`, `935e4b8`; `scratch/rev23/leak_audit/`) reproduced H1 and H2 exactly.

**Findings:**
- **No look-ahead.** 11 of 12 checks are clean: price basis against later splits, share counts, every fundamental
  accepted before 16:00 ET on T (300 name-dates, 74k rows), survival labels before T, priors cut, ERP and beta dates,
  outcome alignment (to 1e-15), classification. The placebos reject chance.
- **Inflated (check 3).**
  - Census acquisitions are scored and returned against a stale public-float proxy (a median 396 days old, 0.84× the
    traded price). 167 resolved acquisitions average +42%.
  - Without census names: H1 +0.12 (lower bound +0.08), H2 about +4 pp.
  - With no acquisition premium credited: H2 about +5 pp.
- **Mostly style (check 9).**
  - Ranking by 1/price alone gives H2 +7.0/+6.2/+5.8; by book ÷ price, +17.2/+14.6/+15.8.
  - With book ÷ price, size, volatility, beta, liquidity, reversal and 1/price added to the five yardsticks, 2025
    incremental information is about 0 (H1 about −0.01; survivors only about +0.015).
  - The engine at population-median inputs ranks better (+12.6 pp) than with company inputs (+8.2): company-specific
    forecasts add nothing in 2025.
- **Development 2020–2024 survives the full controls plus book ÷ price** (H1 +0.075/+0.054/+0.089, lower bounds
  positive; H2 +6.6/+3.4/+4.7).

**The coordinator's correction.** Addendum W and the operator report called H1 and H2 the money-relevant, robust edge.
That overstated it. The registered yardstick set (five factors) left out book ÷ price, size and volatility, so the bars
credited common value and size exposure as engine information. That is a defect of the coordinator's design, not of
the data.

**What is established:**
- clean point-in-time data;
- revenue forecasts better than naive.

**What is not established:** stock-picking information beyond standard factors. The evidence is weak and positive in
2020–2024 and absent in 2025.

**Fixes for every future registration:**
- **Y1:** the yardstick set adds book ÷ price, log market cap, idiosyncratic volatility, 1-month reversal and 1/price.
  "Incremental information" means beyond all of them.
- **Y2:** census acquisitions get a fourth bound with no premium credited, and the proxy staleness is reported. A
  result must hold without the census as well.
- **Y3:** an "average-input" control (the same engine at population-median inputs) is reported beside every engine
  result. Company-specific forecasts must beat it.

**Gate 2 continues unchanged.** Muse against code is a paired comparison of company-specific forecasts and of rankings.
The audit shows the code's company-specific inputs are the weak link, which is the question gate 2 answers. The gate-2
scoring adds the Y1 controls and the Y3 control as **reported** variants. Its approved bars are not changed.

## Addendum Z (2026-10-09, rulings on ChatGPT's and Gemini's reviews of cross-check 5; pre-specified before any gate-2 result)

**Adopted:**
1. **Gate 2 finishes frozen, as a diagnostic** (both reviewers). Its registered G1–G6 outcome is reported faithfully. A
   raw G2 pass no longer qualifies anything for real money.
2. **G1 comes first** (Gemini). If Muse does not beat the code on fundamental accuracy (G1), the return results (G2)
   are reported but carry no weight.
3. **Pre-specified diagnostics, fixed now, before any gate-2 result is read:**
   - **Four-way forecast comparison** for next-quarter revenue growth and margin change: Muse against the code
     (state-conditioned prior P50) against the unconditional population median against naive persistence.
   - **Factor-adjusted return ranking:** Muse and code IV ÷ price and their difference, with residual returns after
     book ÷ price, log size, 12-1 momentum, 1-month reversal, beta, idiosyncratic volatility, liquidity, 1/price and
     industry.
   - **The average-input control.**
   - **Splits by solvency tercile.**
   - **Turnover** of the Muse ranking against the code's.
4. **No manufactured precision for exits** (ChatGPT). A delisted company with no observed traded price at T is
   **unobservable**. It is excluded from main results and shown only in a separate sensitivity. The public-float proxy
   stays for the census count, not for returns.
5. **Shrinkage of company-specific inputs** (both reviewers):
   - x = prior + w·(company − prior), with w estimated walk-forward by forecast loss and calibration only, never by
     returns;
   - per variable, family and horizon;
   - w = 0 where company deviations do not improve out-of-sample forecasts;
   - Gemini's empirical-Bayes form w = max(0, 1 − σ²/τ²) is one candidate estimator, compared walk-forward with the
     direct loss-minimizing w.
6. **Margins** (both reviewers):
   - the code baseline is measured persistence plus mean reversion, conditional on family and cycle;
   - Gemini's operating-leverage decomposition (contribution margin, fixed costs, applied to the revenue forecast) is
     tested walk-forward against persistence as a structural candidate;
   - Muse's job becomes an **evidence-backed deviation from the baseline**, never an absolute margin.
   - Nothing reaches the valuation until it beats persistence out of sample.
7. **The product direction** (both reviewers): a fundamental forecasting engine, with shrinkage and calibration,
   feeding a factor-aware selection. IV ÷ price and the expectation gap (forecast against price-implied) are inputs,
   not the sole signal. Muse's pass 1 stays price-blind.
8. **1/price is treated as an artefact detector** (ChatGPT), not a factor: price-level, microcap and corporate-action
   effects are investigated. It stays a control only.
9. **Audit additions, run now on gate 1b and development:**
   - remove every M&A-announced name, to check whether the score was a takeover lottery on cheap microcaps (Gemini);
   - turnover and costs at 30 bp a trade (Gemini);
   - a factor regression of the long-short returns on market, size, value, momentum, reversal and low volatility, with
     R² and alpha (Gemini).

   The factors are built in house from the point-in-time panel, so no new download is needed.
10. **The real-money evidence bar** (merged from both reviewers):
    - **forecast skill:** beat the strongest baseline (persistence and population) on revenue and EBIT/margins out of
      sample, with calibration;
    - **company-specific value:** company-specific inputs beat population-median inputs;
    - **returns:** a factor-neutral alpha > 0 with t ≥ 2 (Gemini's +2.5 pp a year as the target), net of 30 bp a trade,
      robust to exit treatment, over at least 36 monthly out-of-sample dates across regimes;
    - **prospective evidence:** a frozen shadow portfolio with realistic costs;
    - "Match Wall Street consensus" is evaluated prospectively only; no consensus history exists.

**Rejected:** none outright.

**The order of work:**
- now: the audit additions (item 9);
- then: the walk-forward shrinkage and margin study (items 5 and 6), on forecast loss only, using data up to
  2024-12-31;
- gate 2 keeps running; its scoring adds item 3;
- no valuation-engine rebuild until those report.

## Addendum AA (2026-10-09, the coordinator's own audit of the Addendum-Z item-9 work)

**The work audited:** `review-2026-10/leak-audit` `aa69185`. 10 new audit scripts; no other file changed and nothing
deleted (`git show --stat`).

**Independent recomputation** (the coordinator's own code, not the coder's functions), from `panel_scored.pkl` and
`panel_q20.pkl`, on the main universe (census excluded):

| Quantity | Coordinator | Coder | Agrees |
|---|---|---|---|
| Holdout main incremental coefficient (5 yardsticks, industry effects) | 0.111 | 0.119 | yes |
| Development main industry-neutral raw spread | 8.67 pp | 8.78 pp | yes |
| Holdout main industry-neutral raw spread | +0.7 pp | +0.2 pp | yes, same sign and size |

- **A naming hazard found:** in both panels the column `survivor` is **True for the census names** (626 in the holdout,
  2,743 in development). The coder's code handles it correctly, but any reader would invert it.
- **New, not in the coder's report:** the holdout's **pooled (not industry-neutral) raw spread is −4.0 pp.**

**A material finding the report did not surface: the development "survives the controls" result is a 2020 episode.**
Per-date incremental coefficients (5 yardsticks + industry; tangible B/P and size added in brackets):

| Dates | Mean coefficient | Positive dates |
|---|---|---|
| 2020-03 to 2020-12 | 1.11, 0.85, 0.85, 0.27 (with B/P and size: 0.89, 0.83, 0.79, 0.27) | 4 of 4 |
| 2021 (4 dates) | about 0.08–0.15 | 4 of 4 |
| **2022–2024 (12 dates)** | **0.023 (0.013 with B/P and size)** | 7 of 12 |
| 2025 holdout (main, with B/P and size) | about 0.02 | — |

**Conclusion:**
- The engine's incremental information beyond value and size is concentrated in the 2020 COVID crash and rebound. It
  is about zero in 2022–2025, which is 21 of the 29 dates studied.
- Addendum Y's "development survives the full controls" is true only in the pooled sense, and the pooling is dominated
  by four 2020 dates.
- **There is no robust evidence that the code engine's valuation ranking adds stock-selection information beyond value
  and size outside that episode.**
- **Corrected reading:** the coder's numbers are accurate; the takeover lottery is confirmed for census names and
  absent in the main universe; costs and factor loadings are as reported (holdout R² 0.95 on value). The factor alpha
  meets no real-money bar.

**What this changes:**
- **IV ÷ price stops being treated as a stock-picking signal in its own right.** The remaining live questions are:
  - whether company-specific forecasts (shrunk, gate-2 Muse) improve **fundamental** forecasts against the population
    and persistence baselines (the forecast study and gate 2's G1 and four-way comparison);
  - whether a forecast-against-price-implied gap adds information beyond value and size, tested only on dates outside
    any development use.
- Every future return result is reported **by date and with the 2020 dates separated.** Pooled results are never shown
  alone.

## Addendum AB (2026-10-09, the coordinator's audit of the forecast study; Addendum Z 5–6)

**The work audited:** `review-2026-10/forecast-study` `c0400a5`, `984ed11`. Study code only. The engine files diff from
`c7d7a4f` is empty; nothing was deleted.

**Leak check, the coordinator's own:**
- the maximum outcome filing date in the panel is 2024-12-31;
- no base filing is dated after its origin (0 rows).

Clean.

**Independent recomputation** (the coordinator's code, not the coder's):
- **Operating margin, year 1, 2021–2024** (n = 3,314):

  | | Code path | Persistence |
  |---|---|---|
  | Median absolute error | 0.0274 | 0.0285 |
  | MAE | 0.0569 | 0.0606 |

  The code is closer in 53% of cases. The coder reported 0.0283 against 0.0291 and MAE_t −6 to −8%. **Agrees.**
- **Revenue growth, year 1:** the code P50 against a walk-forward median of the universe beats it in 4 of 8 years
  (2019, 2020, 2023, 2024). The coder reported "4 of 8". **Agrees.**

**What the study and the audit together establish:**
1. **Revenue growth:** the code's state-conditioned forecast is **no better than the plain population median** (a
   wash: 4 of 8 years, under 1% pooled). The earlier claim "revenue forecasts beat naive" was true only against the
   trailing CAGR, which is a very weak baseline (about 4 times worse). **The coordinator corrects that claim: the code
   has no company-specific revenue skill beyond the base rate.**
2. **Operating margin:** the code's mean-reversion path beats persistence modestly through 2024 (about 4% median, 6%
   MAE), mostly by reverting extreme margins. In the 2025 holdout it was **worse** than persistence (0.0221 against
   0.0189). The edge is small and not stable.
3. **ROTE:** the code path beats persistence by 11–19% (MAE_t). The empirical-Bayes blend toward the population, w
   about 0.75, adds about 3%. This is the one input with a clear, measured company-specific contribution.
4. **The operating-leverage decomposition** (Gemini) **does not beat persistence**, even with perfect revenue. Rejected
   on evidence.
5. **The code's P10–P90 bands are badly under-dispersed** at years 2–3 (coverage 0.33 and 0.09 against 0.80). Because
   the expected value is convex in dispersion, this distorts V1's mean.

**Rules adopted for the next engine version** (each walk-forward measured, none fitted on returns; not yet in the
engine):
- revenue growth uses the population median (year 1 may use w = 0.5, which is immaterial);
- the margin keeps the code's retention path;
- ROTE uses the empirical-Bayes blend w = 0.75;
- the year 2–3 dispersion comes from population outcome distributions;
- the operating-leverage model is not used.

**What this means for the project:**
- The code layer carries **no company-specific forecasting skill for revenue,** and only a small, unstable one for
  margins.
- So the case for the system now rests on whether **Muse's reading of the filings** produces company-specific forecasts
  that beat the base rate. Gate 2's G1 and its four-way comparison (Addendum Z 3) answer exactly that, against the
  population median and persistence as well as the code.

## Addendum AC (2026-10-09 23:38): gate 2 PAUSED, a format-failure defect found by the coordinator's behaviour check

**Context.** At the operator's request the coordinator inspected Muse's **behaviour** (not forecast accuracy, not
returns; no outcome was read) on the first 38 companies with Muse results.

**Findings:**

| Call | Final ok | Retried |
|---|---|---|
| P1 | 3 of 38 | 38 |
| P2 | 5 of 38 | 38 |
| P5 | 5 of 33 | 33 |

- **Unanchored inputs** (the prior P50 used instead of Muse's placement):

  | Input | Unanchored |
  |---|---|
  | g1 | 26 of 38 |
  | growth_persistence | 25 of 38 |
  | margin_target | 17 of 30 |
  | margin_retention | 15 of 30 |

  The P5 synthesis failed on 23 of 33.
- **Causes:**
  - invalid JSON (P1 not_json 31 times, P5 23);
  - schema placement (the extras `character`, `bull_case` and `bear_case` nested among the inputs);
  - section labels "D1"/"D4" where the checker expects "D".
- **Effect:** for about two-thirds of the growth and margin inputs, the "Muse" arm equals the code arm, so G1 would
  measure the code against itself.
- **The pilot report's "no rejections or errors" counted transport only.** The coordinator did not audit the sealed
  pilot. That is a lesson recorded: behaviour health is checked before any full run.
- **Red team (a model behaviour, not a defect; left untouched):** 13 revisions proposed and all accepted. 11 of the 13
  moved toward the price, 12 of them on a "named error" with no new quote. G4 will measure this as registered.

**Ruling: engineering fixes to the measurement machinery, made before any gate-2 outcome is read; the bars are
unchanged.**
1. **Schema-constrained decoding:** each call sends llama-server a JSON schema (`response_format` / json_schema), which
   guarantees syntactically valid JSON with the extras outside the inputs object. The prompts' content is unchanged
   except for stating the exact shape.
2. **The checker** accepts D-subsection labels ("D1", "D4", … map to section D, with the quote verified in that
   subsection's text).
3. **Restart from scratch:** the same sample (sha `d1fefc76…`), the same seeds, a new freeze. The 42 completed so far are
   an engineering pilot, sealed and excluded from scoring.
4. **A behaviour gate before the full run,** on a new 10-company pilot:
   - at least 90% of calls parse on the first attempt;
   - at most 5% of inputs unanchored;
   - P5 synthesis succeeds on at least 90%;
   - otherwise stop and report.

   The coordinator reads the behaviour statistics, never the outcomes.

## Addendum AD (2026-10-10 00:57 KST): recovery after the handoff, the operator's new rule, rulings fixed before run 2

The full plan is `RECOVERY_PLAN_2026-10-10.md`, approved by the operator on 2026-10-10. This addendum records the facts
and the rulings of its stages S0–S3. Every fact below was checked against the files.

### AD.1 What happened after the handoff (23:45)

- **Run 1 ended at 54 of 600.** Company 54 finished at 23:46:59, and the runner stopped its server for the pause at
  23:47:04. The paused runner (pid 88852) was then terminated between 23:49 and 23:53 while it waited on `PAUSE`. The
  task result was 267014 ("terminated"), and no company was in progress.
- **The fix agent (Sonnet, `af3d6fce88dad84f2`) kept working after the handoff, until the operator stopped it at
  about 00:10:**
  - it copied run-1 preparation into `data/gate2_r2`;
  - it ran three llama-server tests on run-1 requests (23:50–00:06; scripts in the old session's scratchpad);
  - it committed `5d0cc8a` (23:58; 17 files, +713 −41) onto `review-2026-10/rebuild-gate2`. That commit is local,
    not pushed, and unaudited;
  - it left an orphaned `freeze_content write` process, which wrote `data/gate2_r2/freeze/gate2_freeze.json` at
    00:12:14.
- **The old session's handoff update (00:10) says "no freeze". That is false.**
- **The scheduled task restarted the run-1 runner every 15 minutes** (23:55, 00:10, 00:25, 00:40, 00:55). Each start
  halted with code 5 ("the gate-2 freeze does not hold"), because `5d0cc8a` changed the runner version and the
  prompt hashes. The freeze guard worked.
- **Containment (00:56–00:57):**
  - `RS2-Gate2-Replay` is disabled;
  - run 1 is sealed in `data/gate2/reports/RUN1_SEALED.json`: 882 files, manifest sha256 `826e3467…`, re-verified
    with 0 mismatches;
  - a pointer branch, `review-2026-10/gate2-fixagent-unaudited`, marks `5d0cc8a`.
- **Unrelated:** a python process talking to Yahoo and Supabase is the self-hosted GitHub runner's screener data
  fetch, dispatched by RS2-SDF-Dispatch at 23:35. It has nothing to do with gate 2.

### AD.2 Run 1's failure taxonomy (the coordinator's count from the raw per-call files; behaviour only, no outcome read)

- **Companies:** 39 of the 54 made model calls; the other 15 were refusals.
- **First-attempt parses:**

  | Call | Parsed first time |
  |---|---|
  | P1 | 1/39 |
  | P2 | 15/39 |
  | P3 | 31/31 |
  | P5 | 8/34 |
  | P6 | 33/39 |
- **Why the answers broke.** 150 of the 171 failed parses (both attempts) are complete JSON missing exactly one closing
  brace at the end. The model nests `bull_case`, `bear_case` and `character` inside `inputs`, and loses count. P3, which
  has no extra fields, parses every time.
- **The prompts contradict the checker**, so these failures are built in:
  - the example skeleton (`prompting._entry_skeleton`) offers `"section": "<F|Q|D|S|R>"`, but the checker forbids
    R. That produced 53 R citations;
  - P5's text allows quotes "from section S or R";
  - the pack labels document subsections `[D1]`..`[D4]`, while the checker accepts only "D". That produced 281
    citations labelled D1–D4.
- **Unanchored inputs:**

  | Input | Unanchored |
  |---|---|
  | g1 | 26/39 |
  | growth_persistence | 25/39 |
  | margin_target | 17/31 |
  | margin_retention | 15/31 |
- **A design gap.** G1 scores Muse's `final` (post-red-team) positions (`scoring.py`), so price-informed revisions
  enter the test of filing skill. Run 1's red team moved 11 of 13 revisions toward the price, and 12 of 13 rested on a
  named error with no new quote. Registered G4 counts a named error as evidence, so this behaviour passes G4.

### AD.3 Rulings (the coordinator's; the red-team ruling was delegated by the operator, 2026-10-10)

- **R1. Who writes.** The operator, 2026-10-10: no Sonnet writing, and no coder agents of any kind. The coordinator
  writes all code, tests, scripts and records.
- **R2. The agent's work is evidence only.** `5d0cc8a`, `data/gate2_r2` (with its freeze) and its scratch tests stay
  untouched and unused. New work starts from `c0a8847` on `review-2026-10/gate2-run2`. After the coordinator's fix is
  tested, it is diffed against `5d0cc8a`; differences are investigated, never copied.
- **R3. The red team and G1.**
  - **The registered system and bars are unchanged.** P6, its revision rule, and G1–G6 with the verdict stand exactly
    as registered.
  - **Fixed now, before any run-2 output exists, as reported diagnostics with reading rules:**
    - **(a) Filing skill.** Apply G1's statistic (the paired median absolute-error difference, with a one-sided 90%
      bootstrap clustered by company, on the registered seeds) to the pass-1 (price-blind) positions. Pass 1 is
      compared against the code, the unconditional population median and persistence. "Muse's reading of filings
      adds skill" is concluded only if pass 1 beats all three. G2 is also reported on pass-1 values, by date.
    - **(b) The red team's effect.** The same statistic, final against pass 1. The red team stays in the live system
      only if final beats pass 1. Otherwise it is redesigned in the next version, never patched mid-gate.
    - **(c) Strict G4.** G4 is recomputed counting only a new quote as evidence. A share above 10% is recorded as "the
      red team anchors on the price", whatever registered G4 says. The strict-rule counterfactual (toward-price
      revisions without a new quote refused) is recomputed with the frozen engine and reported beside (b).
  - **Why.** It removes price contamination from the skill test, measures the red team instead of guessing about it,
    costs no GPU time and changes no registered bar. Tightening the rule now would lose the measurement of the
    registered design, and it would still leave G1 contaminated.
  - The exact persistence and population-median baselines are written into this addendum before the freeze.
- **R4. Constrained decoding** (Addendum AC 1) is adopted only if the A/B passes. The A/B's criteria are fixed in
  AD.4. Otherwise run 2 uses a two-call design: a free answer, then a constrained transcription of it.
- **R5. The behaviour gate** (AD.4) is measured by the coordinator, from the raw files, on a rehearsal outside the
  scored run. Rehearsal outputs are engineering artefacts and are never scored.
- **R6. The freeze waits for three things:** the gate passing, and the coordinator's rulings on cross-checks 6 and 7.
- **R7. Run 2's home.** Run 2 uses the state folder `data/gate2_run2`, on the same sample (`d1fefc76…`) and seeds, with
  a new freeze. It runs from a detached worktree at the frozen commit, where nobody develops. This replaces Addendum
  AC 3's folder name, because the agent occupied `data/gate2_r2`.
- **R8. Repeatability control** (a reported diagnostic, in the style of G6).
  - After the main run, 30 company-dates, drawn from the sample by a stated seeded rule, are rerun with a second model
    seed.
  - **Reported:** the absolute shift in placed percentiles, the share of identical positions, and the change in the
    year-1 forecasts.
  - **Reading rule:** a median shift above 10 percentile points means the live design must combine several samples
    per company.

### AD.4 Thresholds fixed before any data

- **The A/B** (about 46 run-1 first-attempt requests: P1, P2, P3, P5 and P6, from 10 companies).
  - **The three arms:**

    | Arm | What it is |
    |---|---|
    | U1 | run 1's saved answer |
    | U2 | a new unconstrained answer |
    | C | the same request with `response_format` added |
  - **Constrained decoding is adopted only if all of these hold:**
    - C parses and passes the schema on ≥ 95% of first attempts;
    - for each call type, the median paired ratio of reasoning length, C ÷ U2, is ≥ 0.6;
    - the mean |C − U2| in percentile is ≤ the mean |U1 − U2| + 5;
    - C's quote-verification share is ≥ U2's − 10 points.
- **The behaviour gate** (a rehearsal on the first 20 sample companies, from a detached worktree; denominators exclude
  engine refusals).
  - **Pass conditions:**
    - ≥ 90% of model calls parse on the first attempt;
    - ≤ 5% of inputs unanchored, on final positions (pass-1 also reported);
    - P5 succeeds, after its retry, on ≥ 90%.
  - **Stop triggers:**
    - median reasoning length < 0.6 × run 1's, for the same company and call;
    - more than 30% of inputs identical to the code arm (unanchored, or P50 with width "normal");
    - fewer than 90% of cited quotes verified;
    - any leakage-audit violation;
    - any technical status;
    - `finish_reason = length` on more than 5% of calls.
  - **The coordinator also reads one full answer per company.**

### AD.5 The definition of done, and the branch rules after gate 2

- **The definition of done** is section 1 of the plan: ten properties, D1–D10, each of which must hold out of sample.
- **The money bar, D9, is Addendum Z 10 unchanged.** Its out-of-sample dates start in 2026-07, because the gate-2
  dates are used for fitting. 36 monthly dates therefore end in 2029-06. Keeping or replacing that bar is the
  operator's decision (O1).
- **Branch rules after gate 2** (fixed now):
  - **C1. Pass 1 beats all three baselines (R3a)** on next-quarter growth or margin change. Next: engine v2 (base rates
    and calibrated dispersion), then Muse's deviations shrunk and calibrated, cross-fitted by date on forecast loss
    only, then gate 2b on the untouched dates 2026-07-31, 2026-08-31 and 2026-09-30.
  - **C2. Pass 1 beats the code only.** Next: engine v2's base rates become the forecasts; the interim system for
    financials only goes to the operator with numbers; the structural search starts.
  - **C3. Muse fails, or its behaviour is unusable.** Next: engine v2, and a structural search from behaviour data,
    never by tuning on outcomes.
  - **In every branch:** the red team is kept only under R3b, and multi-sampling is required if R8 says so.

### AD.6 (2026-10-10 01:35) Part 2: the contract audit, the run-path audit and the fix, all written by the coordinator

**The baseline at `c0a8847`** (worktree `scratch/rev23/wt-gate2-dev`, branch `review-2026-10/gate2-run2`):

| Suite | Result |
|---|---|
| `valuation rebuild_harness` | 629 passed |
| `tests tools/audit_202608/tests` | 42 failed, 3067 passed |

The 42 failures are the known fixture-date drift recorded in STATUS.

**The contract audit** (P1–P6, operating and financial; each rule the checker enforces against what the prompt states):

| # | Mismatch | Fix |
|---|---|---|
| (a) | The example skeleton offered section R; the checker forbids it | The example now lists exactly the accepted sections. |
| (b) | P5's text said "section S or R" | P5 is now version 2, with S only. |
| (c) | The pack labels D parts `[Dn]`; the checker accepted only "D" | The checker accepts Dn (below). |
| (d) | P6 never stated `market_case` ≥ 20 characters | The schema states it (`minLength`). |
| (e) | P6's example names no section | The schema's enum carries the accepted sections. |

No other mismatch was found.

**The run-path audit** (read in full: mapping, red team, pack, prompting, pipeline, runner, guard, integrity):
- **The mapping** matches `SPEC_muse_passes` section 2: the shift to the chosen percentile, and the spread scaled by width.
- **Unanchored inputs** are P50 with width "wide". This is wider than the code arm, so under V1 (the mean of the draws) an
  unanchored Muse input changes the Muse arm's value through spread alone. G1 is unaffected, because it uses P50
  forecasts. This is recorded for the G2 reading.
- **No price before P6:** `render_pass1` and `render_p5` take no argument that could carry a price, and the existing
  tests prove it.
- **The fields R3 and R8 need are recorded:** pass-1 forecasts (`pass1.result.forecast_year1`), and decisions carrying
  `toward_price`, `new_quote` and `named_error`.
- **A missing section D** is stamped in the pack manifest.
- **One numeric `or` default** was found in the run path (`guard.py`, `max_tokens`) and fixed to `is None`.

**The fix: commit `13c5fb9`** on `review-2026-10/gate2-run2`.
- `valuation/muse/jsonschemas.py`:
  - one schema per call, built from the checker's own constants;
  - the extra fields sit at the top level and can never be nested;
  - the section enum is the shown sections without R, plus D1..Dn;
  - length caps;
  - P6 keep or revise, and the round-1 request.
- **Runner version 2:** `response_format` is sent on both attempts and saved with each request.
- **Checker:** `Evidence` owns the `[Dn]` split, so `integrity.py` re-checks identically. A Dn quote must be found in
  that part, and it counts as D for hard evidence and for the P2 character rule.
- **`rebuild_harness/gate2/behaviour.py`:** the AD.4 statistics and gate. Behaviour only.
- **`--mode repeat` (R8):** the second model seed, in its own state folder carrying a `REPEAT_CONTROL` marker. The
  scored modes and the repeat mode refuse each other's folders.
- **Engine and deletions:** the engine diff from `c0a8847` is empty, and nothing was deleted.
- **Tests after the fix:**

  | Suite | Result |
  |---|---|
  | `valuation/muse rebuild_harness/gate2` | 259 passed |
  | the canonical suite | 42 failed, 3067 passed — the failure set is identical to the baseline |

**The replay of run 1 through the new checker** (pass-1 answers, brace-repaired and reshaped, for this diagnostic
only).
- **First-attempt pass rates:**

  | Call | Pass all checks first time |
  |---|---|
  | P1 | 27/30 |
  | P2 | 28/35 |
  | P3 | 27/31 |
- **What is left:**
  - quotes not found verbatim, which the retry exists for;
  - three R or invalid-section citations, which the schema now blocks;
  - 13 answers that could not be repaired, which constrained decoding removes.
- **The expected residual:** about 13% of calls retried, against 90% or more in run 1.

**The GPU A/B** (AD.4) was launched 2026-10-10 at 01:31, as the one-off task `RS2-Gate2-AB`, from the detached
worktree `wt-gate2-ab` at `13c5fb9`.
- **State and outputs:** `data/gate2_ab`.
- **Analysis:** `scratch/rev23/gate2_ab/ab_analyze.py`.
- **Requests:** 48, from 10 companies.

### AD.7 (2026-10-10 01:45) The scoring audit, part 1: G1 measured levels where Addendum O 2 registered changes

**The finding.** Addendum O 2 registered how G1 compares the margin: the year-on-year change in the margin (ROTE for
financials), which removes seasonality.
- **Realised:** the quarter's margin minus the same quarter a year earlier.
- **Forecast:** the arm's year-1 P50 margin minus its base-year margin.

`scoring.py`, which Sonnet wrote and nobody audited, instead compared the arm's annual year-1 P50 margin level with one
quarter's margin level. `outcome_extract.py` did not even record the year-earlier margin. G3 had the same flaw.

**The fix** (commit `10b872c`, made before any gate-2 outcome is read; the bars are unchanged):
- the pipeline records `result["base_year"]` (`op_margin`, `rote_latest`);
- `outcome_extract` adds the year-earlier margin, `operating_margin_change` and `rote_change_annualised_on_tbv_at_T`;
- `scoring._fc` turns the margin forecast into a change from the base year;
- `_outcome_value` reads the changes;
- a test pins this semantics.

**Consequence.** Run-2 results must come from code at or after `10b872c`. Revenue growth was already compared
correctly: year-on-year growth against year-1 growth.

**The rest of the scoring audit continues while run 2 runs** (S2): G2, G4, G5 and G6, `outcome_extract`, and the
coordinator's independent recomputation of G1.

**The capability probe of build b11272:**
- **Enforced:** `enum`, `minLength`/`maxLength`, `minItems`/`maxItems`, integer `minimum`, and `anyOf` with `null`.
- **Not enforced:** `minimum`/`maximum` on a `number`. Asked for 120, the model returned 120.
- **So** the percentile range stays enforced by the checker alone, and an out-of-range percentile is retried.

### AD.8 (2026-10-10 04:37) The A/B result: constrained decoding is ADOPTED (R4)

**The run.** 48 run-1 first-attempt requests from 10 companies: 8 P1, 10 P2, 8 P3, 10 P5 and 10 P6 (one call type
fewer for the two financials, which have no P3). Run on the registered server, 01:31–04:35, as task `RS2-Gate2-AB`
(now disabled), with outputs in `data/gate2_ab`.

**Against the AD.4 criteria, computed by `ab_analyze.py` and recounted by an independent script, which agree:**

| Criterion | Bar | Result | Holds |
|---|---|---|---|
| C parses and passes the schema | ≥ 95% | 48/48 = 100% | yes |
| Median reasoning-length ratio C ÷ U2 | ≥ 0.6 per call type | P1 0.93, P2 0.94, P3 1.16, P5 0.92, P6 1.03 | yes |
| Mean percentile shift | C vs U2 ≤ U1 vs U2 + 5 | C vs U2 4.5 points, U1 vs U2 (sampling noise alone) 5.1 points, over 85 inputs | yes |
| Quote verification | C ≥ U2 − 10 points | U1 99.5%, U2 96.0%, C 98.1% | yes |

**Other facts:**
- No arm hit the length limit.
- **The constrained answers read correctly.** The coordinator read samples: the reasons engage the filings, the
  quotes are verbatim, and P6's `market_case` is substantive text, not filler.

**What it means.** The schema removes the run-1 format failures and leaves the reasoning and the placements within
sampling noise. The two-call design is not needed.

**Next.** The 20-company rehearsal and its behaviour gate (AD.4), launched at 04:37 as task `RS2-Gate2-Rehearsal`:
- code: `10b872c`, from the detached worktree `wt-gate2-rehearsal`;
- state: `data/gate2_rehearsal_r2` (prepared from run 1: 1,109 files, 0 hash mismatches, sample `d1fefc76…`).

### AD.9 (2026-10-10 07:05) The rehearsal behaviour gate: STOP on leakage, and two systemic defects found; nothing launched

**The rehearsal.** 20 company-dates: 14 made model calls and 6 were engine refusals. It ran 04:37–06:53 as
`RS2-Gate2-Rehearsal`, on code `10b872c`, into `data/gate2_rehearsal_r2`. Measured by `behaviour.py` against run 1 as
the reference.

**Pass conditions: all three hold.**

| Condition | Bar | Result |
|---|---|---|
| First-attempt parse | ≥ 90% | 100%, every call type |
| Unanchored final inputs | ≤ 5% | 0 of 68 (pass 1 also 0) |
| P5 succeeds | ≥ 90% | 14/14 |

**Stop triggers: five of six are clean.**

| Trigger | Result |
|---|---|
| Reasoning against run 1 (median ratio per call type) | P1 0.96, P2 1.01, P3 0.92, P5 0.90, P6 1.01 |
| Inputs identical to the code arm | 1.5% (bar 30%) |
| Quotes verified | 260/260 |
| Technical statuses | none |
| Length cut-offs | none |
| **Leakage audit violations** | **133 — STOP** |

The red team proposed 4 revisions. All 4 moved toward the price on a named error, without a new quote, and all 4 were
accepted. G4 and R3c will measure this.

**The leakage STOP predates the fix.** Run 1 has 257 violations of the same kinds. Nobody read the audit before run 1
started. By kind:
1. **Identity: 14 of 14 packs.** The gate-2 environment stamps every ticker `current_record`, because there is no
   ticker history. Registered G5 ("the leakage audit is clean on every pack") would therefore FAIL every gate-2 run by
   construction. **This is not only a formality: it hides real leaks.**
   - The ticker appears in a document accepted before T for 12/14 rehearsal companies and 35/39 run-1 companies.
   - Two of the misses leak the future: Ambac shown as `OSG` and OPENLANE as `OPLN` are tickers adopted after a later
     corporate change.
2. **Model text echoed into P5 and P6 is scanned as code-built text.**
   - "2026" (company guidance such as "calendar 2026 revenue", quoted from filings accepted before T);
   - "pricing" (as in "pricing power");
   - "in the past".

   The model's knowledge ends about August 2025, before every replay date, so its own words cannot carry information
   from after T. These are review items, not violations.
3. **Fiscal-period labels in D item headers** (for example "8-K earnings release, filed 2025-09-03, Q2 2026"): a
   fiscal-year naming convention on a filing whose acceptance before 16:00 ET on T is checked by code.

**Defect B: the ticker map can name the wrong security.** In `harness_smoke/sample_id_map.json`, 328 CIKs have more
than one ticker, and the gate universe sometimes takes a preferred share, a baby bond or an exchangeable note instead
of the common stock.
- **Examples:** HBANL, ONBPP, VLYPN, SLMBP, CCZ (Comcast notes), BRKRP.
- **Bruker** was valued against BRKRP at $316.25, a market capitalisation of $48.0B against a real ~$5B.
- **Exposure in the gate-2 sample:** 8 of 600 company-dates (BRKRP, NEWTH, NEWTO, ONBPO, VLYPN, GTN-A, RILYN, ABXL).
- **What it affects:**
  - the price at T, IV ÷ price, G2 and the red team's price block;
  - the ≥ $300M filter;
  - and, through the same map, gates 1 and 1b.
- **What it does not affect:** G1's forecasts, which come from filings and not prices.

**Also found:** `data/gate2_run1_engineering_pilot`, created at 23:51:46 by the fix agent as a copy of run 1. It is
unaudited and unused. It was missed in the S0 inventory, and is recorded now.

**Proposed rulings, for the operator and cross-check 7, before any freeze:**
- **(i) Withhold any ticker not found in a document accepted before T.** The pack shows the name only, and records
  `ticker_source = withheld` (pack version 2.2). A ticker found in such a document is stamped `verified_in_filing`.
- **(ii) Reclassify two kinds of finding as `review`, not `violation`:** model-written text echoed into P5 and P6, and
  fiscal-period labels in D headers whose acceptance time is checked. Code-built text keeps `violation`. This
  instrument change is a stated deviation made before any outcome is read.
- **(iii) Map each CIK to its common-stock ticker by a stated, verifiable rule.**
  - It may need a further SEC file, for example `company_tickers_exchange.json`, which needs the operator's approval.
  - The fallback is a rule using no download: the price at T × the cover-page common shares, checked against the
    cover's public float.
  - The 8 gate-2 company-dates are re-priced on the common share, and a company whose true market cap is below $300M
    is excluded from scoring by a stated rule (the sample hash is kept).
  - The exposure of gates 1 and 1b is measured and reported, by date.

**Nothing has been launched.** A new rehearsal runs after (i)–(iii) are built and tested.

### AD.10 (2026-10-10 11:30) The operator's rulings on AD.9, the fixes, and rehearsal r3

**The operator's rulings (2026-10-10).**
1. **Downloads.** Download SEC's ticker files, and SEC files in general from now on, without asking (memory
   `sec-downloads-standing-approval`).
2. **The audit.** The model's echoed words and fiscal-period labels count as review items, not violations.

**Downloaded:** `data/sec_bulk/company_tickers_2026-10-10/`, fetched at 10:50 with the declared User-Agent:

| File | sha256 | Size |
|---|---|---|
| `company_tickers_exchange.json` | `33b39989…` | 10,445 rows |
| `company_tickers.json` | `bb1521ff…` | |

**The fixes** (commit `5455c4e` on `review-2026-10/gate2-run2`):
- **The common share.** `gate1_run._best_ticker` now takes the first ticker in SEC's order that has a price. That is
  the common stock in every case checked: BRKR, CMCSA, HBAN, ONB, VLY, RILY, ABX, NEWT and GTN, and BRK-B over BRK-A.
  The old rule (the largest price × common shares) is only a fallback, and is flagged.
  - **The 8 affected gate-2 entries now resolve to the common share.** Bruker: BRKR at $38.94, a $5.91B cap, instead
    of BRKRP at $316.25 and $48.0B.
  - **A floor rule.** A company whose common-share cap is below $300M is refused, and recorded with the reason
    `below_mcap_floor_on_the_common_share`.
- **The ticker as of T** (pack version 2.2). A ticker not stamped as of T is shown only when a document accepted
  before T names it (`verified_in_filing`); otherwise it is withheld and the name alone is shown (`withheld`). This
  removes the OSG and OPLN leaks.
- **The audit's review classes.**
  - **Review:** model text echoed into P5 and P6 (reason lines, cited quotes, cases, character, risks), and
    fiscal-period labels in the header of a D item filed before T.
  - **Still violations:** code-built text, and anything filed after T.
- **Re-auditing the old outputs with the new rules** leaves only the identity findings of packs built before the fix:
  14 in rehearsal r2 and 39 in run 1.
- **Tests:**

  | Suite | Result |
  |---|---|
  | `valuation rebuild_harness` | 652 passed |
  | the canonical suite | 42 failed, 3067 passed — the failure set is identical to the baseline |

**Rehearsal r3:**
- **Run:** the same 20 company-dates, code `5455c4e`, launched at 11:23 into `data/gate2_rehearsal_r3` (prepared from
  run 1: 1,109 files, 0 mismatches).
- **Gate:** AD.4, unchanged.

**Cross-check 7** (`CROSS_CHECK_7_gate2_run2_before_freeze.md`) is written for the operator to relay. The freeze
waits for the coordinator's rulings on cross-checks 6 and 7 (R6).


## Addendum AE (2026-10-10): the coordinator's rulings on ChatGPT's and Gemini's reviews of cross-checks 6 and 7 (before any freeze or outcome)

Each point below is ruled adopted, adapted or rejected, with its reason. No gate-2 outcome has been read. Where a
ruling changes the system or the measurement, it is a stated deviation, and the original rule is kept as a reported
diagnostic.

**AE.1 Red team: the rule is TIGHTENED before the freeze. Adopted (both reviewers).** This reverses the coordinator's
R3 choice to keep the registered rule.
- **The evidence.** 11 of 13 revisions in run 1, and 4 of 4 in rehearsal r2, moved toward the price on a "named
  error" with no new quote. The registered rule cannot tell anchoring from correction.
- **The new rule** (`redteam.decide`):
  - **A revision toward the price is accepted only with a new quote:** verified verbatim, not cited in pass 1, and in
    a filing section (F, Q or D). A named error alone no longer suffices for a move toward the price.
  - **A revision away from the price, or a width-only change,** keeps the registered rule (a new quote or a named
    error).
- **ChatGPT's third route, a demonstrable mechanical error, is not adopted.** Muse does no arithmetic (Python
  computes), so a pass-1 "mechanical error" is a judgment that cannot be checked by code.
- **The prompt.** P6 states the new rule; template P6 becomes version 2.
- **The measures.**
  - **Registered G4** (a named error counts) is reported unchanged, as a diagnostic.
  - **G4-strict** (only a new quote counts) becomes the deployment guardrail and is reported beside it.
  - **R3b stands:** the red team stays in the live system only if its final positions beat pass 1 on forecast error.

**AE.2 The unanchored fallback equals the code arm exactly. Adopted (both reviewers; cross-check 7, question 7).**
- **The change.** An input that fails its checks twice is placed at P50 with width "normal", which is the prior
  itself, the code arm's distribution. Before, it was P50 "wide", which changed the mean of the draws through
  convexity alone.
- **What is shared.** Both arms already use the same engine seed for a company-date, so the draws are the same.
- **What is logged.** The failure is still recorded (`unanchored`, stamped). Any doubt about the input belongs in
  sizing, not in the valuation distribution.
- **Why this is a departure.** It departs from `SPEC_muse_passes` section 2, which said P50 "wide". The departure is a
  fix to the paired comparison's fairness.

**AE.3 Price-blind pass 1 is the primary test of filing skill. Adopted (both reviewers).** This confirms R3a.
- **Pass-1 baselines**, each computed on the same information set at T, the same target observations and the same
  scoring rule:
  - **(i) persistence:** the year-on-year statistic of the latest quarter known at T;
  - **(ii) the population median:** the cross-sectional median of that statistic over the gate universe's latest known
    quarters at T;
  - **(iii) the trailing four quarters, added (both reviewers):** the mean of the year-on-year statistic over the last
    four quarters known at T.
- **The primary claim, "Muse adds filing skill",** needs pass 1 to beat the code, (ii) and (i).
- **(iii) is reported as a robustness comparison** (ChatGPT's placement). Gemini's reading is recorded with it: if
  Muse fails (iii) as well, its deviations are treated as noise.
- **No baseline is chosen after the outcomes;** all are reported.

**AE.4 G5: model text needs grounding, and confirmed future information stays a hard failure. Adapted (ChatGPT's
three categories; Gemini's exact-string test).**
- **Model text echoed into P5 and P6** is `review` only when every date-like token it carries also appears in the
  filing text of the run's pack, which was accepted before T.
- **A date token in model text that the pack does not contain** is a `violation`: an ungrounded statement about the
  future, which may be a hallucination or a leak.
- **Code-built text is unchanged:** strict.
- **The isolation of the model stays in place:** no web, no tools, a frozen model file, and the G6 masked control.

**AE.5 Schema decoding is kept, and the two-call design rejected; the checks were made. Adopted (both reviewers).**
- **Truncation:** no A/B or rehearsal answer hit the length limit, and the runner already rejects a length-cut answer.
- **Quote caps:** none of the 4 failed constrained quotes in the A/B was cut by the 600-character cap; they ran 137 to
  363 characters.
- **The failures:** 3 are genuine mismatches, which the retry handles. 1 carries a leaked chat-template token
  (`<|message|>`) inside the quote, which the checker refused.
- **Single source of truth:** the checker's constants generate both the schema and the prompts' examples; this was
  checked in AD.6.
- **Gemini's reasoning-field-first with a minimum token allocation: rejected.** Muse reasons in `reasoning_content`
  before writing the JSON, and that reasoning was preserved (A/B ratios 0.92–1.16).
- **Semantic support of a quote for a placement: adapted.** It cannot be checked by code without another model, so:
  - the hard-evidence rule stays the code check;
  - the coordinator reads samples (one full answer per company in every rehearsal, and 20 random answers during run
    2);
  - unsupported citations are counted and reported.

**AE.6 The security map gets a share-basis check. Adapted (both reviewers).**
- **The rule stays SEC's order.** The SEC file lists exchange securities without a class field. Every checked case put
  the common stock first.
- **Added: a share-basis consistency check.** For every sample company-date, the chosen common share's price × the
  cover-page shares is compared with the latest pre-T cover's public float.
  - The rule fixed now: a ratio outside [0.2, 5] is flagged `share_basis_unverified`, and the company-date is excluded
    from the price-based bars (G2 and the factor tests).
  - It is kept in G1, which needs no price.
  - The measured flags are reported before the freeze.
- **Gates 1 and 1b:** the wrong-security correction is applied there as a disclosed sensitivity, by date. Those
  holdouts are spent and are not re-registered (ChatGPT). Gemini judged the effect too small to change their
  conclusions; that is to be measured, not assumed.

**AE.7 Identity.**
- **Ticker withholding: confirmed** (both reviewers).
- **The historical name:** the name shown is the name in force at T, from the submissions' former-name history. All 39
  run-1 names are stamped `as_of_T`, so no neutral identifier is needed.
- **Extra masking arms** (ChatGPT's three, Gemini's ten-company name-only check): not added. G6 already compares the
  masked control with the unmasked run, and with withholding no unverified ticker is shown.

**AE.8 What is not built into gate 2, and why.**
- **The population-median code baseline:** that is engine v2 (S4). The gate-2 CODE arm stays registered, and AE.3
  carries the population median as a baseline.
- **The commodity family:** already out of scope (V3).
- **The financials-only track:** adopted as a planned branch. It gets its own registration after gate 2 (bank and
  insurer subtypes separately, with factor controls).
- **Calibration** (ChatGPT, cross-check 6, question 6): this is engine v2 and S5's calibration layer, measured
  walk-forward by horizon and family; it is not hand-widened.

**AE.9 Inference. Adopted.** With five dates, company clustering misses shocks common to a date. Gate 2 stays a
diagnostic of behaviour and short-horizon forecasting (Addendum Z 1):
- results are reported by date;
- G2 never stands alone; the factor-adjusted (Z 3) and average-input (Y3) companions are required beside it;
- the money bar stays prospective (D9).

**AE.10 The consequence.**
- AE.1 (the red-team rule and P6 v2), AE.2 (the fallback) and AE.4 (the audit grounding) change the system or its
  measurement. **They are built, tested, and verified in a new rehearsal (r4)** before the freeze.
- The AE.6 share-basis check runs before the freeze.
- Rehearsal r3, already running on `5455c4e`, still verifies the ticker and price fixes of AD.10.


**AE.11 (2026-10-10 12:19) The AE.6 share-basis check, measured: invalid as an exclusion rule, so it is REVISED before the
freeze.**

**The check as fixed in AE.6.** For each of the 600 sample company-dates, the common share's price × cover shares was
divided by the latest pre-T cover's public float. Output: `data/gate2_rehearsal_r3/share_basis_check.json`.
- 39 entries have no float on record.
- 35 are flagged outside [0.2, 5].

**What the flags are.** Almost none is a share-basis error:
- **controlled companies with small public floats:** Smithfield 16.3, ARES 35.4, Republic Airways 23.7, Paymentus
  10.3;
- **stale covers:** Trip.com's float dates from 2009, Central Garden's from 2017;
- **large price moves since the float date:** WDC 7.75, TeraWulf 7.2, Amkor 7.2, Coherent 5.3;
- **unit errors in the filed float itself:** McGrath, Universal Display, TKO, Cabot and others show ratios near 0
  because their filed floats are thousands of times too large.

Excluding these would remove real winners from the price-based bars, a momentum bias, for no gain in correctness.

**The revision**, stated and made before any outcome is read:
- **The float ratio becomes a reported diagnostic only.**
- **The wrong-security failure** (the defect AE.6 aimed at) can only arise for a company with more than one listed
  security. 25 sample company-dates are such companies. Each now resolves to SEC's first-listed security that has a
  price; 8 changed (AD.10).
- **Dual-class companies** (for example CENT and CENTA) are valued on the first-listed class's price times the cover's
  summed classes. That is a stated approximation and is flagged by `ticker_common_by_sec_order`.

**What this teaches.** A guard set before measurement must itself be measured before it is trusted. This one would
have silently gated 6% of the sample.


**AE.12 (2026-10-10 13:49) Rehearsal r3, the grounding test revised, and rehearsal r4 launched.**

**Rehearsal r3.** 20 company-dates: 14 with model calls and 6 engine refusals. Code `5455c4e`; it ran 11:23–13:45.

| Measure | Result |
|---|---|
| First-attempt parse | 100% |
| Unanchored inputs | 0 of 68 |
| P5 succeeds | 14/14 |
| Quotes verified | 260/260 |
| Inputs identical to the code arm | 1.5% |
| Reasoning against run 1 | 0.90–1.02 |
| Technical statuses | none |
| Length cuts | none |

- **Tickers in the packs:** 13 `verified_in_filing` and 1 `withheld` (OPLN, the post-T ticker). Bruker is shown as
  BRKR.
- **The red team** proposed 4 revisions, all toward the price on named errors. All 4 were accepted under the old rule.
  r4 runs the AE.1 rule.

**The AE.4 grounding was too literal.**
- Under the exact-string test, r3 had 11 violations, every one "FY2026" in model text where the filings write
  "fiscal 2026" or "Q2 2026" (Bruker's 2026 cost plan; a fiscal-year company's "Q2 FY2026" results).
- **Revised (commit `a5fd342`):** a future date in model text is grounded when the pack's filing text refers to the
  same future year in any date form. A year the filings never mention stays a violation.
- **The stated limit:** a year the filings mention for an unrelated reason also grounds it. The finding then stays a
  review item that the coordinator reads.

**Re-audited with the final rules:**

| Run | Violations | What they are |
|---|---|---|
| r3 | **0** | |
| r2 | 14 | identity only, packs built before AD.10 |
| run 1 | 39 | identity only, packs built before AD.10 |

The tests pass: `valuation/muse` and `rebuild_harness/gate2`, 265 passed.

**Rehearsal r4.** The same 20 company-dates, code `a5fd342`, which includes AE.1 (the toward-price rule and P6 v2),
AE.2 (the fallback) and AE.12. Launched at 13:49 into `data/gate2_rehearsal_r4` (prepared from run 1, 0 mismatches,
sample `d1fefc76…`).
- **If its AD.4 gate passes,** and all cross-check rulings are recorded (they are: AE), the freeze and run 2 follow.

## Addendum AF (2026-10-10 16:25): rehearsal r4 passed, the run-2 freeze, and the launch

**Rehearsal r4.** Code `a5fd342` (AE.1, AE.2, AE.12); it ran 13:50–16:05. 20 company-dates: 14 with model calls, 6
engine refusals.

**The AD.4 gate: PASS.** Every pass condition holds and no stop trigger fired.

| Measure | Result |
|---|---|
| First-attempt parse | 100% |
| Unanchored inputs (pass 1 and final) | 0 of 68 |
| P5 succeeds | 14/14 |
| Quotes verified | 263/263 |
| Inputs identical to the code arm | 1.5% |
| Reasoning against run 1 | 0.90–1.05 |
| Leakage violations | 0 |
| Technical statuses | none |
| Length cuts | none |

An independent recount agrees: 69/69 first-attempt parses and 0/68 unanchored inputs.

**The red team under AE.1 proposed no revisions:** 63 of 63 inputs kept, each with a substantive `market_case`. In r3,
under the old rule, it made 4 revisions, all toward the price.
- This is a behaviour, not a defect. R3b will measure the red team's value: with no revisions, final equals pass 1.
- Registered G4 and G4-strict will both read as vacuous if this continues. That is to be stated, not counted as a
  pass of substance.

**The freeze:** `data/gate2_run2/freeze/gate2_freeze.json`, sha256 `30bc30e2…`, written 16:08 from the detached
worktree `wt-gate2-run2` at `a5fd342`.
- The engine is identical to `c7d7a4f`.
- Muse runner version 2; the request fields include `response_format`.
- Sample `d1fefc76…`.
- `verify` reports "the freeze holds", and the dry run shows 600 jobs, ready.

**The launch:** `RS2-Gate2-Replay` was re-registered from the run worktree with state `data/gate2_run2`.
- **16:13:** the run started.
- **16:24:** company 1 finished.
- **16:25:** the runner stopped its server and is waiting, because another program is using the GPU (operator use).
  This is the designed behaviour.
- **Estimate:** about 3 GPU-days.
- **Pausing:** create `data/gate2_run2/PAUSE`.

**During the run (S2):**
- the behaviour gate is checked daily; outcomes are never read;
- the audit of scoring and outcome extraction is completed;
- the coordinator's independent G1 recomputation and the AE.3 baselines are coded;
- the engine-v2 specification and `REGISTRATION_gate2b` and `REGISTRATION_selection` are written, with their bars
  fixed before any gate-2 outcome is read.

---

## Addendum AG (2026-10-10 18:13): side work during run 2 — outcome security, baselines, diagnostics, independent recomputation

Branch `review-2026-10/gate2-run2` (dev worktree `wt-gate2-dev`). The live run's worktree `wt-gate2-run2` stays at
`a5fd342` and is untouched; none of this code is imported by the replay runner.

**AG.1 Outcome security (`6dded9e`).** The scoring audit found that `outcome_extract` measured returns on the sample
file's ticker, which can be a preferred share or a note (BRKRP for Bruker). This is the AD.10 defect, on the outcome
side.
- Returns are now measured on `gate1_run._best_ticker(pit, cik, T)`, the very security priced at T.
- The sample ticker is kept beside it as `sample_ticker`.
- Test: `test_returns_are_measured_on_the_resolved_common_share_not_the_sample_ticker`.
- Outcome extraction has not run on any gate-2 state, so no number changes.

**AG.2 AE.3 baselines (`47270f0`, `gate2/baselines.py`).**
- **Source:** the quarters each company had reported by T, through the pack's own source and eligibility rule.
- **Baselines:** persistence, the trailing-four-quarter mean, and the per-date, per-family population median of
  persistence.
- **Defined on the target statistic:** growth, the margin change, and for financials the ROTE change on tangible book
  at T.
- No outcome is read. The output is written once to `<state>/baselines/baselines.json`.

**AG.3 Reported diagnostics (`47270f0`, `gate2/diagnostics.py`).**
- **R3a:** pass 1 against the code, the population median, persistence and t4q. "Filing skill" requires beating the
  first three.
- **R3b:** final against pass 1.
- **R3c:** G4-strict.
- **R8:** repeatability.
- All use G1's statistic and bootstrap, pooled and by date. No registered bar changes.

**AG.4 Independent recomputation** (`stocks-workspace/scratch/rev23/gate2_audit/independent_g1.py`). It imports
nothing from `rebuild_harness` or `valuation`. It reads `progress.jsonl`, each `result.json` and the outcome file
directly, and uses its own bootstrap (seed 777). It recomputes G1 and the R3a/R3b comparisons. Every headline number
in S3 must agree with it before it is reported. Its field names were checked against a real run-2 `result.json`,
structure only.

**Suites:** `valuation rebuild_harness` 664 passed (655 + 9 new).

**AG.5 The baselines ran** (18:22) on `data/gate2_rehearsal_r4`, whose `ctx` holds the same hash-verified universe
files as run 2. Output `baselines/baselines.json`, sha256 `ac16b377fcd3edbc…`.
- **Volume:** 9,148 company-dates, 0 errors.
- **Population medians:**
  - operating growth 6.2–8.1%;
  - operating margin change +0.03 to +0.20 points;
  - financial ROTE change +2.6 to +3.5 points.
- **Missing quarters:** 538 company-dates (133 companies) have no eligible quarter. All are foreign private issuers
  (20-F/6-K, no 10-Q: MGA, CHKP, NICE, NTES, ICLR and others), the known foreign-filer gap. Section Q is empty for them
  in the pack as well, and they have no q1 outcome, so they leave every comparison consistently.
- **Use:** the file is copied into the run-2 state at scoring time, not while the run is live.

**AG.6 Registrations drafted** (18:22–18:30), before any gate-2 outcome is read:
- `REGISTRATION_gate2b.md`: dates 2026-07-31, 08-31 and 09-30; seed 20261010; scoring date 2026-12-18; bars B1–B8.
- `REGISTRATION_selection.md`: H-S1 to H-S3, the D9 money bar, Bonferroni t ≥ 2.4 at 3 months.

Both await the operator's approval and cross-check 8.

---

## Addendum AH (2026-10-11 11:17): rulings on cross-check 8 (Gemini and ChatGPT on the gate-2b and selection drafts)

The coordinator rules on each point. The reviews are counsel; the drafts are revised as v2 in place. No gate-2 outcome
has been read.

**Facts checked before ruling:**
- **Financials** are 2,013 of 9,148 gate company-dates (22%, AG.5). So proportional sampling gives about 79 financial
  company-dates over three dates.
- **The reverse engine** returns, per input, the population-prior percentile at which value equals the price. So an
  expectation gap can be stated in one unit, percentile points.
- **The data hold no VIX index,** only the VIXY and VIXM ETFs.

### Gate 2b

| # | Point (source) | Ruling | Change |
|---|---|---|---|
| 1 | Horizon mismatch: annual forecasts scored on q1, persistence forecasts q1 (both) | **Adopted, in the form of ChatGPT's option B.** The target becomes fiscal year 1, the quantity the engine forecasts and values. Its outcomes come from the engines' own `build_state` as of the year-1 annual report. PERSIST and POPMED become annual-convention run-rates (four quarters on four). The q1 score is kept as an early read with no weight. **Rejected:** Gemini's option of a T4Q target ending in q1, since three of its four quarters are known at T, which makes a near-tautological test; and Gemini's option of new next-quarter prompts, since they test a quantity the valuation never uses. | §1, §3; scoring date 2026-12-18 → 2027-04-15 |
| 2 | Financial sample below the ROTE minimum (Gemini) | **Adopted, with a larger draw.** 100 operating + 50 financial per date (450 in all, not 360), because operating also needs margin over missingness. Each bar is within one family, so oversampling biases nothing. | §2; about 3.1 GPU-days |
| 3 | Three dates are a screen, not proof (ChatGPT) | **Adopted.** Pass is worded as preliminary and conditional on the three dates. Missing outcomes are compared with included ones on observables. | header, §3 |
| 4 | Coverage can be passed by widening; add a proper score (ChatGPT) | **Adopted:** B4b, the interval score at α = 0.2, non-inferior to V2. | §4 |
| 5 | Tail symmetry (Gemini) | **Adopted:** no tail above 15%. | §4 B4a |
| 6 | Isotonic overfits; use splines or Platt scaling (Gemini) | **Partly.** The registration does not prescribe a method. S5 compares isotonic with a smoothed monotone mapping by cross-fitted loss and freezes the winner. Platt scaling calibrates binary probabilities, not quantile placements, so it does not apply. | §6 |
| 7 | The V2 fallback was inferred from SYSTEM's results (ChatGPT) | **Adopted, a real defect.** V2 is promoted only on its own scorecard, computed for V2. | §5 |
| 8 | Define departures; the repeat seed changes only the intended randomness (ChatGPT) | **Adopted.** | §2, §4 |
| 9 | **Found by the coordinator while ruling on 1:** 2026-07-31 overlaps the fit | At 2026-07-31 most companies had not reported the June quarter, which the S5 fit sees as a gate-2 outcome (date 2026-06-30). **Dates become 2026-08-31, 09-30 and 10-30.** Companies with no 10-Q in the 12 months before T leave the test universe, a point-in-time rule: 133 foreign private issuers have no quarterly run-rate and no comparable outcome (AG.5). | §2 |

### Selection

| # | Point (source) | Ruling | Change |
|---|---|---|---|
| 10 | Gate-2b dates double as selection dates (ChatGPT) | **Adopted.** Confirmatory dates start after the promotion decision (earliest 2027-04-30). Earlier dates are exploratory only. The channel is real: the core is chosen on fiscal-2026 results, which drive returns over the same months. | §1; the earliest D9 read moves to about 2030-07 |
| 11 | Make H-S2 primary (Gemini); H-S1 primary, hierarchical (ChatGPT) | **H-S2 primary, in a fixed sequence H-S2 → H-S1 → H-S3.** The records decide it: AA names the expectation gap as the open question, and Y/AA show IV ÷ price is mostly value and size. **Rejected:** Gemini's "IV ≥ 0.8 × price" filter, an unfitted new threshold. | §2 |
| 12 | H-S2 underspecified (ChatGPT) | **Adopted:** the mean of the percentile gaps (core percentile − price-implied percentile) over the two level inputs, with not-reachable set to 1 or 99. Gemini's EBIT-growth form is not used: the reverse engine solves per input, so percentile points are the one common unit. | §2 |
| 13 | t ≥ 2 vs 2.4 inconsistent; the multiplicity routes (ChatGPT) | **Adopted, a real defect.** One threshold, t ≥ 2.0, stated as a stringency choice. The fixed sequence controls family-wise error, and S2 applies only to the hypothesis that passed. | §2, §4 |
| 14 | Expanded factor controls (ChatGPT) | **Adopted as the hard specification;** core-only reported beside it. 1/price stays an artefact control (Z 8). | §3 |
| 15 | Sizing must use the signal that passed (ChatGPT) | **Adopted:** weights from the passing signal's percentile; renormalisation, cash and the governor order defined. | §3 |
| 16 | Costs, borrow, turnover cap scope (ChatGPT); boundary buffers (Gemini) | **Adopted:** a liquidity-tiered cost schedule, borrow on shorts, the cap on the sized book only. **A buffer adopted in the sized book** (enter top quintile, hold above the median). The signal test stays plain quintiles, so it measures the signal. | §3 |
| 17 | Adopt the trend filter into the core now (Gemini) | **Not adopted.** O3 is the operator's decision. H-S3 enters the sequence only if O3 is adopted before the first confirmatory date. | §2 |
| 18 | S4 "exists" too weak (ChatGPT) | **Adopted:** ledger completeness and reconciliation, stated as a prerequisite, not evidence. | §4 |
| 19 | Replace the 36-date freeze with a capital ramp (Gemini); keep D9 hard, a pilot separate (ChatGPT) | **The operator's decision (O1).** The coordinator does not relax D9. A pilot, if the operator wants one, is a risk decision recorded as such, never evidence. | §6 |
| 20 | **Found by the coordinator:** a VIX crisis flag with no VIX data | Replaced by SPY 21-session realised volatility above 35%. | §3 |
| 21 | **Found by the coordinator:** a nonsense per-date seed formula in v1 | Corrected in v1 already (yyyymmdd). | §1 |

### The horizon flaw also reaches gate 2's S3 branch rule

**The flaw.** The S3 branch rule C1 (recovery plan; AD) reads R3a, which compares Muse's pass 1 with PERSIST and POPMED
on q1. That is the very mismatch of point 1.

**The fix,** proposed now, before any gate-2 outcome is read. It needs the operator's approval, because C1 is in the
approved plan:
- R3a and C1 compare against the **annual-convention run-rate** PERSIST and POPMED.
- Every arm forecasts the same annual quantity and is scored on q1, the registered G1 convention: one shared mismatch,
  not a handicap for one side.
- Where fiscal-year-1 outcomes exist at S3 (mostly dates 2025-10-31 and 2025-12-31), R3a on the annual target is
  reported beside it.
- **Code needed after approval:**
  - the run-rate arms in `gate2/baselines.py` and `diagnostics.py`;
  - an annual-outcome extractor for gate 2b and the annual R3a;
  - the independent script extended to match.

  Registered G1 itself (Muse against code) is unchanged.

**AH.22, found at 11:17 from run-2 progress.**
- **The count:** 151 of 600 company-dates are done: 106 ok, 42 engine refusals and 3 designed refusals (BDCs with no
  Damodaran industry).
- **The causes:** mostly no three-year ROIC (31), then a missing operating income or base margin (about 26).
- **Gate 2:** about 420 company-dates will be scored. Both arms lose the same companies, and the registration has no
  minimum, so nothing changes.
- **Gate 2b:** at this rate the operating floor (200) would be at risk. The draw is now limited to companies engine v2
  can value at T, checked on CPU before the draw (§2), which is point in time.

**AH.23 Operator rulings (2026-10-11 12:33 KST).** The operator's words: "approve 1-4, keep D9 as written, adopt O3".
- `REGISTRATION_gate2b.md` v2 and `REGISTRATION_selection.md` v2 are approved and fixed.
- The C1 horizon fix is approved. The run-rate baselines, the annual-outcome extractor and the extended independent
  script are to be coded and tested before gate 2 is scored.
- The later timeline is accepted.
- **O1:** D9 stays as written.
- **O3:** adopted. H-S3 is third in the selection sequence. The two-axis entry timing enters the verdict contract (S7)
  as a stamped, graded field.

**AH.24 The C1 fix is coded (`f9f7598`, 2026-10-11 13:10).**
- **`baselines.py` v2:**
  - the annual-convention run-rate (four contiguous quarters known at T against the `build_state` base year);
  - the ROTE change on `rote_latest`'s own denominator;
  - `pop_median_runrate`;
  - output `baselines_v2.json`; v1 is kept.
- **`outcome_extract.annual_outcomes`:** year 1 after the base year known at T, from `build_state` as of the day after
  the year-1 annual report was first filed.
  - A year 1 not yet filed, or a fiscal-year change, is recorded with its status.
  - An error is recorded as itself.
- **`diagnostics`:**
  - C1 reads code, `persist_rr` and `popmed_rr`;
  - R3a and R3b are repeated on the annual target;
  - the AE.3 quarterly arms are reported beside them.
- **The independent script** (`gate2_audit/independent_g1.py`) is extended to match, and still imports nothing from
  the system.

**Checks:**
- **Suite:** 674 passed (10 new tests).
- **Agreement:** `diagnostics.run` and the independent script agree on a mock state, with the same n and median on
  all 24 comparisons (both targets). Only the bootstrap bounds differ, by seed.
- **Real-store smoke test:** 60 companies from the 2025-10-31 universe that are not in the gate-2 sample. Only
  statuses and field types were printed, no values.
  - 51 had an outcome;
  - 8 had a year 1 not filed by the test date (non-calendar fiscal years);
  - 1 had a fiscal-year change.

**The baselines v2 computation is deferred until run 2 finishes.**
- It was started at 12:5x while run 2's llama-server was loaded.
- The PC (12 GB RAM) ran out of commit memory, and PowerShell failed to start with E_OUTOFMEMORY.
- The job was stopped at 13:05. No partial file was written, the server was unaffected, and free memory recovered to
  1.9 GB.
- It is needed only at scoring, so it runs when the GPU run has ended.

**AH.25 Effect of that memory exhaustion on run 2** (checked 13:15).
- **The affected call:** company `2025-12-31_0000021344`, P2 attempt 1, generated at 5.6 tokens a second against the
  normal 65–81. It took 1,608 s, from 12:43 to 13:10, inside the window of the stopped job.
- **It ended normally** (`finish_reason` stop, 8,889 tokens). Generation speed does not change the tokens produced, so
  the answer is valid.
- **Its retry** (attempt 2) was the designed content-check re-ask, at normal speed.
- **Cost:** about 25 GPU-minutes; no data lost. The following calls ran at normal speed.
- The coordinator's session also crashed around this time, probably from the same memory exhaustion.

---

## Addendum AI (2026-10-11 13:38): engine v2 specified (S4)

`SPEC_engine_v2.md` and `REGISTRATION_engine_v2.md` were drafted before any v2 number exists.

**The design:**
- **Point forecasts, years 1–3,** follow Addendum AB's rules with the study's measured weights:
  - growth: w = 0.5 at k = 1 and 0 after;
  - margin: the code's retention path;
  - ROTE: 0.75 toward the population;
  - tangible-book growth: unchanged.
- **Years 1–3 dispersion** is drawn from v2's own walk-forward residual distributions by cell, with a Gaussian copula
  across years and variables.
- **From year 4** the v1 chain shapes continue from the year-3 draw.
- **Unchanged:** the long-run inputs, the priors Muse sees and the `c7d7a4f` engine files. v2 is new modules.

**Validation, E1–E7:**
- implementation identity against an independent script;
- the study reproduced;
- walk-forward coverage 75–85% with tail limits;
- sharpness against v1;
- the oracle;
- the cut proof;
- isolation.

These are engineering checks, not performance claims; gate 2b is the out-of-sample test.

**Status and cost:**
- It awaits operator approval and cross-check 9.
- The residual build is CPU-heavy and runs only while no GPU run holds the model.

**AI.1 Approved by the operator** (2026-10-11 21:04 KST): "approve the engine-v2 spec and registration". The build waits for the
end of the GPU run, because the residual tables are CPU- and memory-heavy.

---

## Addendum AJ (2026-10-11 21:15): run 2 PAUSED on a behaviour-gate STOP; leakage-audit findings analysed

**The trigger.** The daily behaviour check (21:04, 228 of 600 company-dates) returned STOP. The leakage audit found 23
violations in 11 runs. Every other measure passed:
- first-attempt parse, unanchored inputs and P5 all pass;
- quotes are all verified;
- reasoning against run 1 is 0.94–1.09;
- there are no technical statuses and no length cuts.

The run was paused at 21:08 (the `PAUSE` file), as AD.4 requires.

**What the 23 are. None is in code-built text derived from data:** 0 in packs, 0 in templates. Every one is Muse's own
words.

| Count | Where | What |
|---|---|---|
| 18 | model text echoed into P5/P6, or an earlier answer | "into 2026" / "FY2026", for example "headwinds may persist into 2026", "visibility into 2026", "No firm backlog or FY2026 guidance". These are the year after T, named as the year being forecast. |
| 2 | the checker's retry message, quoting Muse's failed quote | "FY 2029" (ADMA's revenue target, a quote not found in the pack and refused by the checker) |
| 1 | the same | "calendar year 2026" guidance (GNTX, a quote not found verbatim in D2 and refused) |
| 2 | the same | "pricing" (MAMA, "targeted pricing", a company's own word in pass 1) |

**Was anything from after T read?**
- **No input text from after T exists:** packs and templates are clean.
- **Muse's knowledge ends about August 2025,** before every gate-2 date (from 2025-10-31), so its own words cannot
  carry facts from after T.
- **The one specific figure,** VALU's "Q1 FY2026 down 3.4%", is a fiscal-year label for the quarter May–July 2025,
  filed before T=2025-10-31. That is the fiscal-label class the operator ruled a review item (AD.10).
- **The two failed quotes** (ADMA, GNTX) look like memory of statements from before T, outside the pack. The checker
  refused them, so they were not accepted evidence.

**The conflict of rules.**
- The operator's Decision 2 (AD.10) made echoed model words review items.
- The coordinator's AE.4 (cross-check 7) then made an ungrounded future year in model text a violation, and AE.12 kept
  that for years the filings never mention.
- Under AE.4 as written, G5 (a hard bar) already fails gate 2 on wording such as "into 2026", not on any information
  from after T. That is a mis-specification by the coordinator: the rule meant to catch future information also
  catches ordinary references to the year being forecast.

**Proposed** (needs the operator, since it changes how the hard bar G5 is applied; fixed before any outcome is read;
the run's outputs do not change, because the audit is a reading of saved files):
1. **The year being forecast.** A future year in Muse's own text, or in a retry message that only quotes Muse's own
   failed quote, is a review item when it is year(T) + 1 or the fiscal year after the base year.
2. **Other future years** in model text stay review items, but the coordinator reads every one before scoring and
   records a judgement. Any with a value tied to a period ending after T counts as a G5 violation.
3. **Code-built text derived from data** stays strict and is unchanged.
4. **Unchanged:** the masked-name control (G6) and the model's isolation.

Under rule 1, 20 of the 23 become review items. The remaining 3 are the two ADMA "FY 2029" lines and none other:
"pricing" is the operator's AD.10 class. They go to the coordinator's reading under rule 2.

**The run stays paused** until the operator rules. Under AE.4 as written, gate 2 has already failed G5, and completing
it would spend about 1.5 GPU-days on a decided result.

**AJ.1 The operator's ruling and the fix.** The operator said: "when you fix, don't just keep re-running ... we keep
finding issues". That is read as approval of the proposed rule and a direction to stop finding defects one at a time.
The rule is coded in `56f8976`: the forecast year in model text is a review item, and a retry message's echoed model
quote is model text. Run 2 re-audited: **0 violations** (was 23), and no item is tagged beyond the forecast year.

**AJ.2 The pre-scoring sweep** (2026-10-11 21:28). Every check that will be applied to run 2 was run on its 163 finished
company-dates, with **dummy outcomes** (random numbers; no real outcome was read):
`scoring.score` (G1–G6 and the verdict), `diagnostics.run` (both targets) and the independent script.

**Defects found and fixed** (`28b20e2`):
1. **Value per share.** 17 company-dates have no share count (dual-class and foreign listers: NYT, UHS, GHC, FUTU,
   ZTO and others). Scoring dropped them from every bar. They now leave only G2 (value against price), and G1 scores
   all 163. The data gap itself is a production item for S9: the share count for dual-class companies.
2. **G5 fallback detector.** It flagged 4 runs whose failed P1/P2 call was handled by the pipeline's designed path:
   an extras-only failure, or the input re-anchored by P5 with verified quotes. The detector now recognises those
   paths and still fails a failed entry that stands as the call's own position.

**Checks after the fixes:**
- G5 passes: 0 leakage violations, 0 of 2,897 citations failed, 0 unrecorded fallbacks.
- The independent script agrees with scoring on G1 n and medians, exactly.
- Suite: 676 passed.

**Reported as found, nothing changed:**
- **Registered G4 is at 3 of 29 revisions (10.3%)** against its 10% limit, with none accepted. G4-strict is at 20.7%.
  This is behaviour, not outcome. The bar is fixed and the red team is not changed mid-run; the full run decides.
- **The R8 repeat control cannot be launched with `register_gate2_task.ps1`,** which accepts pilot, full and masked
  only. It will run from a scratch launcher against the frozen worktree; the frozen worktree is not edited.
- **Refusals in the controls.** The masked control has 5 refusals among its first 11 known company-dates, and the
  repeat control 2 of 11. Expect about 16 and 25 usable of 30. The controls are fixed in the frozen sample and are not
  redrawn; reported as such.
- **Baselines v2** (the run-rate arms) are still to be built after the run, which is why the C1 arms read n = 0 in
  the sweep.

**From here,** a finding during the rest of run 2 is handled at scoring, never by re-running. The one exception is a
defect in what Muse is fed (packs or prompts).

**AJ.3 Reviews every 50 company-dates** (operator, 2026-10-11 21:40: "every 50 or so tickers run, review for any
issues and faults").
- **The script,** `scratch/rev23/gate2_audit/milestone_review.py`, runs when progress passes the next multiple of 50.
  It checks:
  - statuses and new refusal reasons;
  - the AD.4 behaviour gate;
  - the leakage audit, including items beyond the forecast year;
  - slow calls;
  - the full scoring pipeline and diagnostics on dummy outcomes (G5 and G4 as behaviour);
  - the independent script's agreement;
  - the runner's error log.

  It reads no real outcome and writes only into `gate2_audit/reviews/`.
- **Memory guard:** it waits while commit headroom is under 8 GB and runs at below-normal priority. Free RAM is
  always low with the model loaded, which costs speed only; the crash came from commit exhaustion.
- **Scheduling:** the Windows task `RS2-Gate2-MilestoneReview` runs it hourly for 14 days. The coordinator's session
  reads each report hourly and acts on flags under the AJ.2 rule: pause only for a defect in what Muse is fed.
- **First review** (229 company-dates): 0 flags. The next is due at 250.

**AJ.4 Milestone review at 252** (read 2026-10-12 01:42).
- **Flags:** a behaviour-gate STOP and a G5 failure, both from one leakage "violation" in code-built prompt text:
  GTM (ZoomInfo, 2026-02-27, P5), the wording "available as of".
- **The investigation:** the line is the second line of a multi-line quote Muse cited from ZoomInfo's own 8-K
  ("Business Outlook: Based on information available as of February 9, 2026, ..."), filed before T. The audit
  recognises echoed model lines by prefix, so the continuation line was treated as code-built text.
- **The ruling:** an audit line-classification defect, not a defect in what Muse is fed. No pause.
- **Fixed** (the commit after `28b20e2`): an echoed quote stays model text until its closing quotation mark. Test
  added; suite 677 passed. Run 2 re-audited: 0 violations over 187 runs.
- **Otherwise clean:** behaviour passes, 0 of 3,189 citations failed, 0 unrecorded fallbacks, and the independent
  script agrees.
- **G4 (behaviour):** 4 of 38 revisions (10.5%), with none accepted. Still just over the registered 10%.

**AJ.5 Milestone review at 308** (read 2026-10-12 08:35).
- **The flag:** G5 fails on one accepted citation out of 4,018. Run `2026-02-27_0000944695` (The Hanover), P5,
  input `growth_persistence`, cites "In Personal Lines, our market position is driven by our strength as an account
  writer, ..." as **D1**.
- **The investigation:** the quote is verbatim in the pack, in part **D3** (the 8-K earnings release, filed
  2026-02-04, before T). It appears in every prompt of the run.
  - The pipeline accepted it because P5's checker also accepts quotes from the pool verified earlier in the run, and
    the pool keeps only the section letter (D), not the part. A pooled D quote therefore passes under any D part
    label.
  - The independent re-check has no pool and requires the cited part, so it fails the citation.
- **The ruling:** a checker leniency on the part label. The evidence is genuine, from the filings shown and filed
  before T. It is not a defect in what Muse is fed, so there is no pause; the run's code is frozen in any case.
- **For the operator:** as the re-check is written, this one part-label error fails the hard bar G5, and with it
  gate 2.
  - **Proposed:** a citation whose quote is verbatim in another part of the same section shown is counted and
    reported as a **part-label error**, not a quote failure. The G5 purpose holds: no invented, paraphrased or post-T
    evidence. A quote found nowhere in what was shown stays a failure.
  - **For later versions:** the pool keeps the part label, so the pipeline and the re-check agree. Recorded for S5/S9.
- **Otherwise clean.**
- **G4 (behaviour, not an outcome):** 11 of 53 proposed revisions (20.8%) move toward the price with neither a new
  quote nor a named error, up from 4 of 38 at 252. G4-strict is 15 of 53. 0 were accepted: the code's refusal works
  every time. The registered bar (at most 10% of attempts) is likely to fail at the full run. It is fixed and is not
  changed; nothing in the red team is changed mid-run. R3b will show whether the red team adds anything at all.

**AJ.6 Milestone review at 352** (read 2026-10-12 13:34).
- **The only flag** is the AJ.5 part-label citation, still awaiting the operator's ruling.
- **Designed refusals rose from 3 to 10.** All are business development companies (CION, FDUS, GBDC, OBDC, CGBD,
  BXSL, MSIF, NCDL) with no Damodaran industry, refused at the discount-rate step before any model call. That is the
  known reason; BDCs cluster in the 2026-02-27 sample. Coverage item for S6: BDCs need a family or an explicit
  abstention.
- **Otherwise:**
  - behaviour PASS;
  - 0 leakage violations;
  - 1 of 4,438 citations failed (the AJ.5 case);
  - 25 company-dates without value per share (G2 only);
  - the independent script agrees.
- **G4 (behaviour):** 12 of 56 (21.4%), with 0 accepted.

**AJ.7 Milestone review at 408** (read 2026-10-12 19:34).
- **The only flag** is the AJ.5 part-label citation, still awaiting the operator: 1 of 5,112 citations.
- **Statuses:** 287 ok, 109 engine refusals, 12 designed refusals. No new refusal reasons.
- **Otherwise:** behaviour PASS, 0 leakage violations, the independent script agrees.
- **G4 (behaviour):** 14 of 66 (21.2%), with 0 accepted.

**AJ.8 The part-label rule is approved** (the operator, 2026-10-12 21:55: "approve the part-label rule").
- **The rule:** a quote verbatim in another part of the same section shown is counted and reported as a part-label
  error (G5 field `part_label_errors_reported`), not a quote failure. A quote found nowhere in what was shown still
  fails.
- **Coded** in the commit after `832b58d`; suite 678 passed.
- **Run 2 re-checked:** 5,409 citations, 0 failed, 1 part-label error (The Hanover, D1 → D3).
- **For S5/S9:** the pipeline's pool keeps the part label, so the pipeline and the re-check agree.

---

## Addendum AK (2026-10-12 23:01): the remaining-work plan, and the operator's decisions O2, O5, O6, O8

**The plan.** `REMAINING_WORK_PLAN_2026-10-12.md` details the work of S2–S11, approved by the operator. It covers the quality system
Q1–Q12 and tracks A–F. Q3 is new: a full-scale dry sweep of every check, over at least 150 real items, before any long run or cutover.

**The decisions** (the operator, 2026-10-12, each the coordinator's recommendation):
- **O2, coverage:** "no view" with a reason code now for the families the engines do not build (BDCs, commodity, REIT, utility,
  pre-profit) and for companies with no share count or no 10-Q. Families are built later, one at a time, each with its own validation.
- **O5, live data:** standing approval for SEC (daily), Yahoo daily closes and Damodaran (monthly) downloads. Approved sources only; every
  refresh is hashed and logged, and stale data are refused.
- **O6:** retire the Depth Cloud Backstop. A down PC fails closed: the overlay goes stale, and buying pauses after 36 hours.
- **O8:** consensus is shown for display only, never an input or a gate.

**Still open:** O7 (ARX and the KIS resume details, at S11).

**Deadline on record:** the cloud workflow's move off Node 20 / Ubuntu 26 must land before 2026-10-19. That is a CI change for the
operator's approval.

**AK.1 S5 specified** (2026-10-12 23:14; plan B1): `SPEC_S5_muse_integration.md`, drafted before any gate-2 outcome is read.
- **What Muse can move:** only the inputs with a measured year-1 consequence in gate 2: operating growth and the margin path, and
  financial ROTE. `ronic`, `g_terminal` and financial `g1` stay at v2 (w = 0), stated as limitations.
- **The transport:** in outcome units, `x = v2 + w·(muse_chain − code_chain)`.
- **Fitting w:** leave one date out over the 5 gate-2 dates, on q1 MAE. It is adopted only with an out-of-fold paired gain (G1
  statistic), at least 3 of 5 dates not worse, and annual consistency; otherwise w = 0.
- **Red team and repeatability:** the red-team keep rule (R3b) and multi-sample k (R8, capped at 5) are fixed.
- **Calibration:** on the annual year-1 target, the same target as gate-2b B4. It chooses between isotonic and smoothed monotone
  out of fold, with the identity below 150 points.
- **Structural candidates:** a pre-registration format for C2/C3.
- **Validation:** V1–V6, with an independent split audit.
- **Self-review corrections before recording:**
  1. the per-date rule is made exact;
  2. calibration moved from q1 to the annual target, a horizon inconsistency with B4 that would otherwise have been built in.
- **Status:** awaiting the operator's approval and cross-check 9.

**AK.2 Rulings on the outside review of the S5 draft** (2026-10-12 23:35). The S5 specification is revised to v2.

| # | Point | Ruling |
|---|---|---|
| 1 | Calibration on annual, but gate-2b B4 scores q1 | **The premise is mistaken:** the approved gate-2b v2 (AH, 10-11) scores fiscal year 1, and B4 is annual coverage. The reviewer read draft v1. **The related point is adopted:** w is now fitted on the annual year-1 target (primary), with q1 a required breadth check, because the valuation uses the annual figure. |
| 2 | v1-to-v2 deviation transfer | **Answered, plus a diagnostic.** v2's company-specific near-term term *is* the v1 chain (`ii_k`), so "Muse's effect within v2" equals v2's own blend weight × the v1 deviation. The fitted w measures the transfer rate on outcomes; nothing is assumed. Added V9 (Δ, w·Δ and c·Δ reported). V5 now tests the real v2 with nonzero w. |
| 3 | The same w for years 1–3 | **Adopted:** years 2–3 get no Muse adjustment (w = 0), and Δ for years 2–3 is reported only. |
| 4 | Five dates | **Adopted as reporting:** per-date figures; company-date- and equal-date-weighted summaries; drop-one-date stability; the bootstrap labelled conditional on the dates. No new threshold. |
| 5 | The annual check not out of fold | **A real defect, fixed:** every adoption statistic uses the fold weights, never the final weight. |
| 6 | Calibration on too few dates | **Adopted:** at least 3 distinct dates with ≥ 30 each, besides n ≥ 150; otherwise identity. The selected method is refitted on all eligible data after out-of-fold selection. |
| 7 | Interactions | **Adopted as V8.** The v1 chain is separable at year 1, so the expected difference is 0, and it is verified. |
| 8 | Exact fallback | **Adopted:** an unanchored input gives Δ = 0 with V2's distribution, common random numbers, and the failure stamped. V5 covers distributions. |
| 9 | Multi-sampling noise | **Adopted:** reporting per input and family; k = 5 not enough is recorded as unresolved. |
| 10 | The red team | **Adopted:** losses and accepted revisions reported by evidence category; a persuasive explanation or a changed valuation never counts. |
| V1–V7 | Validation additions | **Adopted:** date shocks in V1; horizon-trained maps in V2; calibration leakage in V3; V7 horizon identity. |

**Consequence, stated:** with annual outcomes concentrated on two dates, many cells may end at w = 0. That is the conservative result
the principle requires, not a defect.

**AK.3 S5 v2 approved** by the operator (2026-10-12 23:48 KST): "approve S5 v2". Fixed before any gate-2 outcome is read.

**AK.4 The scoring-day procedure is built** (plan A0, 2026-10-13 00:08): `rebuild_harness/gate2/score_day.py`.
- **Stages:** `check`, `refresh`, `score` and `rehearse`; tests; suite 683 passed.
- **Data on disk:**
  - the packs' store comes from a SEC `companyfacts.zip` of **2026-08-07**, so outcomes filed later are missing. `refresh` downloads a
    new dated snapshot (sha256 recorded, standing approval) and builds a new store from it, never overwriting;
  - the delisting index (submissions of 2026-10-06) and daily prices (to 2026-10-06) already cover every 3-month window.
- **The scoring date** is the earliest data snapshot.
- **Rehearsal on run 2** with dummy outcomes, every stage end to end: **0 mismatches** against the independent script.
- **Outcome extraction rehearsed** on 50 companies outside the gate-2 sample, 10 per date, statuses only:
  - no exceptions and no look-ahead;
  - q1 missing for 6 of 10 at 2026-06-30 on the August store, which confirms the refresh;
  - annual year-1 outcomes for 10/10/2/1/0 by date, so the S5 annual calibration will likely be the identity (fewer than 3 dates);
  - a horizon is counted as elapsed from the first of the month while the return runs to the exact day, so some 6- and 12-month returns
    read "beyond data" with no value. The 3-month bar (G2) is unaffected. Recorded, not changed.
- **New finding from the rehearsal:** VIRT (2026-04-30, financial) ended with status `error`: `KeyError: 'growth_decay'` in
  `mapping.positioned_curves`.
  - **What happened:** the population priors held no growth-decay curve for it, and the Muse mapping layer crashed instead of refusing.
    It happened before any model call; both arms lack a value.
  - **How scoring sees it:** `scoring.g5` counts a technical final status against G5. The registered G5 text names the transport and
    JSON rules and fallbacks, not a code refusal.
  - **For the operator:** treat it as an engine refusal (reported as a defect) rather than a G5 failure.
  - **Fix on the development line:** a refusal naming the missing curve, before S5/S9. 1 of 441 so far.

**AK.5 VIRT's pre-model code exception, ruled and demonstrated** (operator "Yes", 2026-10-13 00:24).
- **The question.** ChatGPT's review asked for it to count as a G5 failure. The coordinator's answer:
  - VIRT was a code crash before any model call, and the code arm crashed too, so no Muse fallback was owed. The fallback is the code's
    prior, and that prior was missing.
  - The registered G5 wording covers leakage, quotes, transport, format and fallbacks; the "no technical status" clause is the scoring
    code's.
- **Adopted from the review:**
  - record it as what it was;
  - fix it generically, with a regression test;
  - **demonstrate** the classification instead of asserting it.
- **Done:**
  1. **Fix** `d2bacbd`: `mapping.positioned_curves` no longer indexes `growth_decay` unless the commodity normalization needs it, so a
     prior set without the curve reaches the engine's own named refusal.
  2. **Regression test:** it fails on the frozen run code `a5fd342` with the identical KeyError, and passes on `d2bacbd` for the
     operating, financial and commodity families.
  3. **Demonstration:** VIRT's real inputs (the r4 state's date contexts, documents off, a model client that fails if called) through
     the corrected pipeline give **`engine_refused`: "priors do not supply: ['g1', 'growth_decay']", with 0 model calls**. That is
     the same class as the 115 other engine refusals.
  4. **Scoring:** `scoring.g5` now removes from the technical-status count only keys listed in
     `scratch/rev23/gate2_audit/reproduced_refusals.json` whose evidence records the corrected refusal, zero model calls and a commit,
     and whose final status is `error` with no model call (re-verified against `progress.jsonl`). Each one stays listed in G5's
     output. Suite 687 passed. The scoring rehearsal: G5 passes, with VIRT listed; 0 mismatches.
- **The coordinator's own rule** (from the review's caution): a bar's implementation is narrowed only when the registered wording
  supports it **and** a mechanical demonstration confirms it.

**AJ.9 Milestone review at 456** (read 2026-10-13 02:35).
- **The flag:** one technical final status `error`, which stops the behaviour gate and fails G5 ("no technical final
  status"). Run `2026-04-30_0001592386` (VIRT, financial), `KeyError: 'growth_decay'`, 0 model calls, 0.5 s.
- **The cause,** reproduced on the frozen code:
  - The population priors for VIRT at T supply neither `g1` nor `growth_decay` ("no tangible-book growth
    delivered or no measured curve"). Under its own rule the financial engine refuses such a company ("priors do not
    supply").
  - Before the engine is reached, `muse/mapping.positioned_curves` reads `curves["growth_decay"]` unguarded, in
    the code arm's call too, and raises.
  - This is a real defect in the frozen pipeline. It fires before any model call, removes the company from both arms
    equally, and touches no other result.
- **The ruling:** not a defect in what Muse is fed. No pause; the frozen code is not changed mid-run.
- **For the operator:** under G5 as written, this one crash fails gate 2's integrity bar.
  - **Proposed:** a final status `error` counts as `engine_refused` for G5 only when two things hold. First, its
    exception is a missing prior curve or input. Second, a reproduction on the frozen code shows the priors refusing
    that item, so the engine's own rule would have refused the company. It is reported by name. Any other `error`
    stays a technical failure.
  - **For S5/S9:** the lookup is guarded so the engine's refusal is reached.
- **Otherwise clean.**

**AJ.9 Milestone review at 456** (read 2026-10-13 02:40).
- **The flags** (a technical status, a behaviour STOP on "technical", G5) are all the single VIRT exception already ruled in AK.5. No new
  error.
- **The review script** now reads the AK.5 evidence list through `scoring.reproduced_refusal_keys`. It lists VIRT, and flags only
  unlisted technical statuses. A re-run at 465 gives 0 flags; the behaviour tool's raw STOP (VIRT) is shown, not hidden.
- **Otherwise:**
  - 322 ok, 120 engine refusals, 13 designed refusals;
  - 0 leakage violations;
  - 0 of 5,765 citations failed;
  - the independent script agrees.
- **G4 (behaviour):** 16 of 72 (22.2%), with 0 accepted.

**Note** (2026-10-13 02:50, by the session that wrote it): the first "AJ.9" entry above (read 02:35) was written by a
parallel session that had not seen Addendum AK. Its proposal is **superseded by AK.5**, which the operator had already approved
(00:24) and which was already fixed and demonstrated. The second AJ.9 (02:40) is the current record.

**AJ.10 Milestone review at 503** (read 2026-10-13 07:40).
- **The flags:** behaviour STOP (leakage), and G5 from 4 "violations" in code-built prompt text. CCSI (2026-04-30), P1/P2/P3/P5: the word
  "Consensus" on the price-blind word list.
- **The investigation:** the only code-built occurrence is the pack header's identity line, "Company: Consensus Cloud Solutions, Inc.
  (CCSI)", the company's legal name. Every other occurrence is the company's own filing text, already review.
- **The ruling:** an audit defect (a name read as wording), not a defect in what Muse is fed. No pause.
- **Fixed** (`3e431e2`): only the name in the "Company:" line is masked for the wording scan; the ticker and all other code-built
  lines stay strict. Test added (forbidden wording elsewhere still fails); suite 688 passed. Run 2 re-audited: **0 violations over 358
  runs.**
- **The review's other STOP** is VIRT (AK.5), listed.
- **Otherwise:**
  - 351 ok, 137 engine refusals, 14 designed refusals;
  - 0 citations failed;
  - the independent script agrees.
- **G4 (behaviour):** 16 of 74 (21.6%), with 0 accepted.

**AJ.11 Milestone review at 551** (read 2026-10-13 14:08; deferred once by the memory guard).
- **The flag:** a new technical status. MIAX (2026-06-30, financial): `KeyError: 'growth_decay'`, 0 model calls. That is VIRT's defect.
- **Applied by the AK.5 rule:** MIAX's real inputs through the corrected pipeline (`d2bacbd`), with a client that fails if called, give
  `engine_refused`: "priors do not supply: ['g1', 'growth_decay']", 0 model calls. Added to `reproduced_refusals.json`.
- **A pattern for S6:** both cases are market-structure financials (a market maker and an exchange operator) for which the financial
  priors hold no growth cell. That is a coverage gap: "no view" or a cell, at S6.
- **Memory:**
  - commit headroom has fallen from 23 GB (10-11) to 6.3 GB. The runner process holds 4.9 GB after 2 days (a slow build-up), and the
    llama-server holds 30.9 GB (normal);
  - with about 6 hours left, the run should finish. Memory is freed when the runner exits;
  - the review guard was lowered from 8 GB to 4 GB, measured: a review needs about 1 GB;
  - to look into before the next long run (gate 2b): the runner's growth over a run.
- **Otherwise:** 387 ok, 146 engine refusals, 16 designed refusals; 0 leakage violations; the independent script agrees.

---

## Addendum AK.6 (2026-10-13 14:20): engine v2 code (plan B2)

**Commit** `2a12a56` on `review-2026-10/gate2-run2`. Suite 705 passed. The v1 engine files are identical to
`c7d7a4f` (E7).

**Built:**
- `valuation/near_term.py`: the section-2 centres use the forecast study's exact formulas (`pass_priors.forecasts`), with the spec's
  fixed weights.
- **The section-3 distributions** are centre plus cell residual quantiles, with the median bias kept, as `QuantileDist` inputs
  `nt_<var>_<k>`. They join v1's own Gaussian copula in `common.simulate`, so no new draw code was needed.
- **Also in `near_term.py`:** the S5 `deviations` interface; named refusals; and a positive-definite check that drops only the near-term
  pairs, stamped.
- `engine_operating_v2.py` and `engine_financial_v2.py`: the v2 chains and runs.
- `priors_build/near_term.py`: the per-vintage table builder.
- `scratch/rev23/engine_v2_audit/e1_identity.py`: the E1 independent script, written before any v2 number.

**Design corrections to the spec's wording, recorded:**
1. **"Reuse v1 by import, without copying"** cannot hold for the chain loop. v1 computes each year's growth and margin inline, and v1 must
   stay byte-identical. The v2 chains are therefore copies with only the years 1–5 growth and margin/ROTE lines changed.
   - **The proof:** with the near-term draws equal to v1's own year-1–3 path, the v2 chain equals v1's chain to 1e-12, for 3 input
     points per family, year by year. This follows algebraically too: the years 4–5 continuation then reduces to v1's path.
   - **Mutation-checked:** a 1e-4 change in any near-term draw breaks it.
   - **The edge where v1 differs:** v1's clipped, non-monotone level weights.
2. **Population medians** as of any cut are taken from the latest observation table, filtered to rows and outcomes filed before the cut.
   The values are first-filed, so this equals each vintage's own table. It is the study's method, and vintages before 2016 do not exist.
   The cut proof (E6 method) passes and catches an injected leak.
3. **The copula pair between the year-3 level and its long-run input** (m_5, `rote_target`) is not measurable in the study panel (no
   year-5 outcome). It is independence, listed, as the spec allows.
4. **The cells' size axis** reads the panel revenue as USD, because the universe is priced in USD. A reporting-currency revenue
   mis-buckets; stated.

**For B3:**
- **Vintages 2016–2024:** built from the existing panel. This is light; no engine re-run.
- **Vintage 2025:** used for 2026 dates, including gate 2b. It needs a 2025-06-30 origin the study never ran, which is a heavy pass run
  with no model loaded. Until then v2 has no table for 2026 dates, and refuses by name.
- **Then:** E1–E6.

**AK.7 (2026-10-13 14:52): D1 verified fixed; C1 drafted.**
- **D1:** rs2's screener data path is already correct.
  - P4.-1 (2026-09-24) derives `screener_data_dir` from the `screener-publish` clone.
  - Every reader entry point refreshes that clone to origin/main first (`screener_refresh.refresh_screener_data`).
  - No rs2 reader uses the development checkout. The STATUS row was stale and is closed.
  - Carried into S9: the new live runner calls the same refresh.
- **C1:** `SPEC_verdict_contract_v4.md`, the S7 verdict contract.
  - **Identity:** scheme `core_v4`, gate_version 3. v3 rows are unchanged.
  - **Value and direction:** the calibrated P10–P90 band with the 10% MoS floor. The direction and `m` rules are kept.
  - **Removed, not synthesised:** fields with no honest v4 source (conviction, moat, Kelly, scenario probabilities, tranches).
  - **Size:** a provisional rule (the probability bucket replaces conviction), superseded by S8 if it passes.
  - **Entry timing (O3):** deterministic, two axes.
  - **Watch items:** generated by code from the year-1 forecast P10s plus the momentum break rule.
  - **"No view" (O2)** with reason codes, and display-only consensus (O8) enforced by a test.
  - **Gate on read:** `depth_gates` v4 reasons with registered rules, and the fiduciary gate adapted.
  - **Plans:** a per-consumer change list and the validation plan (contract tests, single owner, Audit 4).
  - **Defined at spec level, built in S9:** `implausible_level` (a weekly code-only universe pass) and `stale_inputs` (the
    filing-deadline calendar).
  - **Status:** awaiting operator approval and cross-check 10.

**AK.8 (2026-10-13 14:53): B5 drafted.** `REGISTRATION_distress_v2.md`.
- **The candidates:**
  - C0: today's layer, the baseline;
  - C1: richer solvency (Altman and Ohlson components, the coverage trend, the debt-maturity wall only if the store's tags cover 60%);
  - C2: the Merton distance to default;
  - C3: both;
  - C4: Muse's distress flags, later and separately registered.
- **The model:** one logistic class with a fixed penalty; no tuning.
- **Selection:** on walk-forward AUC, Brier and calibration only. **No return is read in selection.**
- **Returns:** the solvency-tercile spreads are read only after selection, as a report.
- **The decisive bars, on fresh dates** (from 2026-07, about 30 events, around mid-2028): AUC ≥ 0.70, Brier ≤ C0's, and no inversion
  of the least-solvent tercile.
- **Self-review fix before recording:** "9 of 13 years" became "70% of the evaluable years", since early origins have no resolved events
  to train on.
- **Status:** awaiting operator approval.

**AK.9 (2026-10-13 15:01): E1 built** (`b3b117e`, pushed after a secret scan).
- **`rebuild_harness/selection/evaluate.py`, per the approved selection registration v2:**
  - the H-S1 and H-S3 signals;
  - the residual-return rank IC under the expanded controls;
  - Newey–West statistics (2 lags at 3 months);
  - the long-short book with liquidity-tiered costs and borrow;
  - the sized book with buffer, caps and the turnover cap;
  - factor alpha, crisis months, and the fixed sequence at t ≥ 2.0 over at least 36 dates.
- **Validated on synthetic panels:** a planted signal is recovered (t > 5); a null signal passes t ≥ 2 in at most 3 of 20 seeds; a
  signal that is only book/price is removed by the residualisation.
- **The independent script** (`scratch/rev23/selection_audit/ind_ic.py`, no import from the harness) agrees exactly (per-date
  difference 0).
- **Defect found in self-review, fixed:** the turnover cap, dropping the smallest trades first, could drop a sell while keeping a
  buy, leaving the book above 100%. The smallest kept buys now go too, with the remainder in cash. A property test over 200 random
  books guards it.
- **Suite:** 712 passed.
- **Note:** the drawdown governor is applied at shadow operation (S10), not inside this module.

**AK.10 (2026-10-13 15:02): cross-check 9 briefing written:** `CROSS_CHECK_9_engine_v2_s5_distress.md` (engine v2, S5 v2, the distress draft; 8 questions), for the operator to send to ChatGPT and Gemini. Also recorded: from about 14:00, run 2 generates at 17–47 tokens/s instead of 65–81 (per-company model time 14.5 min against 9.5), with a browser game and RustDesk sharing the GPU; the runner pauses only for GPU compute processes. Answers are unaffected; the finish moves to about early 10-14.

**AK.11 (2026-10-13 15:04): D2 (the MRI fixes) found handled by another session.** Verified, not duplicated:
- **Local outputs** are fresh (`current_regime.json` 2026-10-13 06:38; task `MRI-Local-Daily` at 06:30).
- **The cost-of-capital anchor** has `degraded: false`. The ERP is solved over a universe aggregate (1,853 constituents, 79% of the cap)
  and published as `implied_erp`; the market-implied fields stay null by design.
- **Weekly theme discovery** succeeds since 10-04 (token-budget fix `f4f8e85`; 10-11: 5 candidates, 0 promoted).
- **The screener's MRI files** come through a local export (`25633a4`).

The other session owns the MRI rows in STATUS; they are left to it.

**AK.12 (2026-10-13 15:10): D3, the first slice of the live data layer** (`c7c4dab`, pushed after a secret scan).
- **`valuation/live_data.py`:**
  - **The refresh:** SEC companyfacts per book company, through `pit_data.compact_company` (the replay store's own compaction),
    written atomically. A manifest records each fetch with its sha256 and latest filing. A failed fetch keeps the previous file and is
    recorded, never filled in.
  - **`stale_reasons`:** the contract-v4 `stale_inputs` rule (facts age or failure; SEC listing a periodic report the store lacks;
    price age; Damodaran age; priors vintage).
- **Smoke-tested** on one real SEC fetch (Apple). The point-in-time layer reads the live store unchanged.
- **Suite:** 714 passed.
- **Not built, by decision:** the price and Damodaran fetchers. Their source is an S9 decision; the screener's daily job already fetches
  prices.

**AK.13 (2026-10-13 15:16): the dual-class share count** (plan D3; `1475a59`, pushed after a scan).
- **The cause:** companyfacts omits class-dimensioned cover-page counts, so dual-class companies (NYT, UHS, GHC and others) have none.
- **The fix:** `pit_data.diluted_shares_fallback` uses the latest annual diluted weighted-average count, first-filed and before T, from
  domestic 10-K filings only. It is stamped in the company's notes, with the tag recorded.
- **Foreign issuers excluded:** a 20-F or 40-F ordinary-share count need not match a per-ADS price (FUTU's would be about 8× off), so
  foreign issuers stay without a count. In v4 they are the `no_share_count` / `no_quarterly_filings` abstention.
- **Checked:** NYT 165.8M, UHS 67.9M, GHC 4.4M (consistent with their filings); Apple still uses its cover count.
- **Effect:** it fixes 26 of the 33 run-2 company-dates without value per share; the 7 left are foreign issuers.
- **Scope:** the frozen run-2 worktree is untouched (gate 2 scores as frozen, G2 without them). Gate 2b and live use the fallback in both
  arms alike.
- **Suite:** 715 passed.

**AL.1 Rulings on the outside code review of B2 (`2a12a56`)** (2026-10-13 15:17; the operator: "approve the fixes, go ahead").

| # | Finding | Ruling |
|---|---|---|
| 1 | ROTE forecast and outcome differ (P1) | **Not a mismatch.** v1's faded ROTE (I + (R − I)φ) is v1's forecast of the company's *realised* ROTE: it enters residual income (v1 docstring: "the return that enters the year's residual income"). The outcome is realised ROTE, net income over average tangible book, the same formula as `build_state`'s `rote_latest` (`obs.rote_by_period`). The study measured exactly this pair, and AB's 0.75 rests on it. **Adopted:** a semantics test (forecast, residual target and the residual-income input are one variable), including the `rote_med8` production case. |
| 2 | Growth below −100% possible (P1) | **Real; fixed:** the residuals of the two growth variables are measured and drawn in log space, `log(1+y) − log(1+x)`, so a draw maps back above −100%. The chains also refuse any growth at or below −100% as an invalid draw (counted). This amends SPEC_engine_v2 section 3 for growth variables (a dated note there). |
| 3 | Table integrity not enforced at load (P1) | **Real; fixed:** one validation for both engines. It checks the engine version, the vintage, that the cut date is the vintage's, that the cut is not after the valuation date, complete finite non-decreasing quantile sets, and the sha256 against `near_term.sha256`. Failures are named refusals. The result carries the verified vintage, cut and hash. |
| 4 | Margin continuation not v1 under non-monotone curves (P2) | **Real; fixed with the reviewer's formula** `m_t = m_3 + (m_5 − m_3)(w_t − w_3)/(1 − w_3)` on v1's own clipped weights. It is algebraically v1's path even when clipped. A parity test is added with a non-monotone curve. |
| 5 | Copula report after a positive-definite fallback (P2) | **Real; fixed:** the report lists the pairs actually used and those dropped, with a full-run test. |

**AK.14 (2026-10-13 15:17): CBOE (2026-06-30, financial) is the third pre-model `growth_decay` exception.** By the AK.5 rule: its real inputs through the corrected pipeline (`d2bacbd`) give `engine_refused` "priors do not supply: [g1, growth_decay]" with 0 model calls; added to `reproduced_refusals.json`. All three (VIRT, MIAX, CBOE) are market-structure financials without a priors growth cell: S6 coverage.

**AK.15 (2026-10-13 15:19): B6, the "no view" codes** (`6d61ea2`): `valuation/abstention.py` maps every refusal to `family_not_built` (unbuilt families; no Damodaran industry; no priors growth cell), `engine_refused` (reasons copied), `no_share_count` or `no_quarterly_filings`; technical failures (`error` and the like) never map. Test: every distinct (status, reason) of gate-2 run 2 maps to its stated code. **Coordination:** a fork of this session ("fork 2") works in the same worktree; it owns the B2 review fixes and B3 (files: `near_term.py`, `engine_*_v2.py`, `priors_build/near_term.py`, their tests, `data/priors_v4`) and records in a new series **AL** (its B2-review rulings are AL.1); this session keeps AK, run 2 and its post-run chain, the runner memory fix, and C1/C2/B5/D/E items. Each stages only its own files.

**AK.16 (2026-10-13 15:21): the runner's memory build-up, fixed for gate 2b** (`c55c6a1`).
- **The cause:** `PitData._cache` kept every company's facts and extractions for the life of the runner. Measured: 11.8 MB per company,
  and `evict` frees 84%. That matches run 2's 4.9 GB after about 600 jobs. `PitData.evict`'s own docstring requires a long pass to
  evict as it goes; the gate-2 runner did not.
- **The fix:** `RealEnv.release(job)` evicts the company, and the runner calls it after every recorded job, whatever its status. A
  company seen again at a later date is reloaded.
- **Test:** every job released, in order, a refused one included. Gate-2 and Muse suites: 299 passed. (The full suite waits for fork 2's
  in-progress engine-v2 edits.)
- **Scope:** the frozen run-2 worktree is untouched.

**AL.2 The AL.1 fixes are built** (`a605eff`, 2026-10-13 15:25; pushed after a secret scan). Suite 736 passed; v1 engine files unchanged (E7).
1. **ROTE semantics:**
   - a test shows the centre (with `rote_med8`, the production case), the drawn `nt_rote_k` and the residual-income input are one
     variable, and that the outcome is realised ROTE by `obs.rote_by_period`'s definition;
   - the module docstring states it.
2. **Log-space growth:**
   - the inputs are renamed `nt_lgrowth_k` and `nt_ltbvg_k`, so their units cannot be confused;
   - the builder measures growth residuals as `log(1+y) − log(1+x)`, and the reports convert back to rates;
   - the chains refuse any growth at or below −100%;
   - an adversarial test with log misses down to −6 at P1 (2,000 draws, both families) yields no such draw.
3. **Table integrity:** `validate_table` (inside `near_term_inputs`, so both engines use it) and `load_table` (with the sha256 and the
   vintage) refuse by name a wrong version, a cut that is not the vintage's, a cut after the valuation date, and incomplete, non-finite
   or decreasing quantiles. The result carries the verified vintage, cut and hash.
4. **Margin continuation on v1's own clipped weights:**
   - brute force over 20,000 random curves: the old formula was off v1's path in 6,703 cases; the new one only where v1 reaches m_5 by
     year 3 and then moves back (3,342). There the year-3 draw cannot carry v1's base margin, so v2 holds m_5 and stamps
     `RULE_HELD_AFTER_TARGET`, as the review allowed;
   - parity tests now include a discriminating non-monotone curve and a clipped curve.
5. **Copula report:** after a positive-definite fallback it lists the pairs actually used (`measured`), the dropped ones and the
   independent ones. A full-run test covers it.

**Numbering:** a parallel session (the "fork") wrote AK.7–AK.14 at the same time. This session's B2-review entry, first written as
AK.7, is AL.1; this session continues in the AL series.

**AK.17 (2026-10-13 15:30): the R8 repeat control is prepared** (plan A2), ready for the GPU after the masked control.
- **`data/gate2_run2_repeat`:** `scratch/rev23/gate2_audit/prepare_repeat.py` copied run 2's prepared inputs (ctx, sample, stage2,
  submissions, doc_cache, pins). 2,131 files, each re-hashed against its source; sample `d1fefc76…`. It carries the `REPEAT_CONTROL`
  marker and `PREPARED_FROM_RUN2.json`.
- **The freeze** was written and verified by the frozen worktree `wt-gate2-run2` ("the freeze holds"). The dry run shows mode repeat,
  30 jobs, readiness ok.
- **The registrar:** `scratch/rev23/gate2_audit/register_repeat_task.ps1` points the frozen `launch_gate2.vbs` at mode `repeat`
  (the frozen registrar accepts pilot, full and masked only). Run it only after the masked control finishes.
- **The post-run order,** agreed with fork 2:
  1. the masked control;
  2. the repeat control;
  3. with no model loaded, `score_day` refresh, baselines and scoring;
  4. fork 2's vintage-2025 build, scheduled not to overlap step 3.

**AL.3 B3, vintages 2016–2024 built and validated** (2026-10-13 15:52; `data/priors_v4/2016..2024/near_term.json` + sha256, 14 s, low priority beside run 2).
- **Pools:**
  - vintages 2016–2017 are essentially empty, because the study panel starts at 2016 origins;
  - 2018 has year 1 only;
  - 2019 has years 1–2 (year 3 for operating only);
  - from 2020 every pool is well over 50.
  So v2 refuses dates in 2017–2020 by name for lack of history (correct behaviour).
- **E1 PASS:**
  - the builder's section-2 forecast equals the independent `engine_v2_audit/e1_identity.py` on **61,026 of 61,026** panel row ×
    variable × year forecasts, to 1e-9;
  - the two sides agree exactly on which rows have none;
  - the runtime centres equal the study formulas by the unit tests, including the med8 and rote_med8 cases.
- **E4 PASS:** v2's interval score is worse than v1's on 3 of 12 cells (allowed: 4): growth k1, financial tangible-book growth k1 and
  margin k3, each slightly.
- **E3 FAIL:**
  - **The result:** walk-forward P10–P90 coverage is 60–72% across the scored cells. The registered band is 75–85%. v1 on the same
    rows: growth 71/33/9%, ROTE 34/28/24%. So v2 is a large improvement, but below the bar.
  - **Diagnosis:** the shortfall sits in macro-shock years. Operating growth k1 by origin year: 2018 74%, 2019 75%, **2020 46%, 2021
    55%**, 2022 67%, 2023 80%, 2024 81%. Growth k2 at origin 2019 (its year 2 is 2020): 42%. Financial tangible-book growth at
    origin 2022 (the rate shock in book values): 31%. In 2022–2024, operating growth and margin coverage is 76–83%.
  - **Cause:** each walk-forward table learns only from misses filed before its cut. The tables used for 2019–2021 origins had seen no
    shock, so they could not widen for one. No rule free of look-ahead could have known.
  - **What can be read:** vintages from 2023 on contain the 2020–2022 shocks, so the 2025 table (used for 2026 dates and gate 2b) will
    carry wider tails. Gate 2b's B4 is the binding out-of-sample test.
- **Per the registration:** a failed check is diagnosed (above), and any fix is v2.1, changing only the residual-cell rule, never a
  weight, and never chosen to hit the E3 number.
- **The decision needed from the operator, among:**
  1. accept E3 as diagnosed and let gate 2b B4 decide;
  2. pre-specify a regime-aware cell rule (for example, residual tables conditioned on MRI's turbulence flag at the origin) as v2.1,
     then re-run E3;
  3. require both.

**AK.18 (2026-10-13 17:00): the records are committed and mirrored.**
- **First commit:** `docs/review_2026-09-22/rev23` in stocks-workspace, commit `e2cb84e` (30 files). Until now the records had never
  been committed.
- **A coordinator error, corrected before anything left the PC:** the first attempt (`9c01859`) swept in another session's already
  staged deletions of CLAUDE.md, CODEX.md and GEMINI.md. It was undone with `git reset --soft` and redone by pathspec. Those deletions
  are staged again exactly as the other session left them.
- **The mirror:** by the operator's choice (public, in rs2-local), the folder is mirrored to the branch `docs/rev23-records` of
  `riperdy-tech/rs2-local` (commit `633df3a`, folder `docs/rev23/`), after a scan that found no keys, tokens, account numbers, phone
  numbers or emails.
- **The authoritative copy** stays in stocks-workspace. The mirror is refreshed after record changes.

**AK.19 (2026-10-13 17:47): rulings on ChatGPT's and Gemini's answers to cross-check 9; C1 and B5 revised to draft v2.** Both
reviews were read against the records themselves. Each claim was checked before it was ruled on. No gate-2 outcome has been read.
Before these edits, the local records and the public mirror were byte-identical (ChatGPT's caveat; checked with `cmp`).

*Defects confirmed and fixed in the drafts:*
1. **The C1–B5 interface gap (ChatGPT).** B5 section 7 published `prob_fail_12m` through v4, but C1 had no such field. **Accepted.**
   C1 now has `prob_fail_12m` and `versions.distress_model`.
2. **The calibration claim (ChatGPT; both reviews' "greatest risk").** C1 called the value distribution "calibrated", but S5 section 6
   calibrates year-1 forecasts only, and that does not carry through the long-run chain and the copula. **Accepted.** New C1 section
   2b:
   - value per share is model-implied, with `value_distribution: "model_implied"` on every row;
   - the claimed and tested quantities are the year-1 forecasts (gate 2b B4) and `prob_fail_12m` (B5);
   - TRK-06 no longer calibration-grades `prob_value_above_price`; its only test is S8's returns.
3. **`expected_mos` was a median (ChatGPT).** **Accepted.**
   - Renamed `median_mos`; `mean_iv` and `mean_mos` added.
   - A table names the measure each consumer uses.
   - H-S1's "expected IV" is fixed as `mean_iv`, the survival-adjusted mean, consistent with Addendum V (the mean keeps the signal).
     **That last point amends the approved selection registration before any selection data exist, and needs the operator's
     confirmation.**
4. **The abstention reason (ChatGPT).** C1 section 8 labelled every abstention `family_not_built`. **Accepted** as a draft bug: the
   reason is now `abstention.code`, with a test that each of the four codes comes back as itself.
5. **The survival adjustment as a distribution (ChatGPT; Gemini's point 3 in part).** "Mean IV × P(survive)" defines a mean, not
   quantiles. **Accepted.** C1 section 2a defines the mixture: value 0 with probability p, the going-concern distribution otherwise.
   - **Formulas:** quantile q is 0 when q ≤ p and otherwise the going-concern quantile at (q − p)/(1 − p); the mean is (1 − p) × mean,
     the existing formula; Pr(V > price) is (1 − p) × Pr(V_gc > price).
   - **Not multiplying every draw by 1 − p:** that matches the mean but gives the wrong shape.
   - **The consequence:** a name with p ≥ 0.10 cannot be `undervalued`. This is stated, and its effect on the fixture universe is
     reported before any merge.
   - **`dispersion_bucket`:** it now reads the going-concern quantiles, because the mixture's P50 can be 0.
6. **The S5/engine-v2 centring contradiction (ChatGPT).** S5 section 6 said the base distribution was "re-centred". Engine v2 section 3
   keeps the median bias, and S5's own V5 requires w = 0 to equal v2 byte for byte. Those cannot all hold. **Accepted** as an erratum
   to S5 section 6: every draw shifts by w·Δ, and the median bias is kept. That is the only reading consistent with two approved
   documents; no S5 code exists yet. **The operator is asked to confirm the erratum.**
7. **The complexity order in B5 (the coordinator's own finding, prompted by ChatGPT's simplicity point).** The draft ranked C1 < C2 <
   C3. By feature count it is C2 < C1 < C3: C2 replaces one of six features, while C1 adds about sixteen. Corrected. A more complex
   qualifying candidate must also beat the simpler one by a paired Brier bound (upper 90% < 0, by year), not by any pooled difference.

*B5's fresh-date read (both reviews).* 30 events is too few for a decisive AUC bar.
- **Gemini's figure checked independently:** Hanley–McNeil at AUC 0.70 with 1,000 non-events gives SE 0.054 at 30 events, 0.030 at
  100 and 0.025 at 150. Clustering widens these.
- **Accepted, in this form:**
  - monitoring from 30 independent events (each company counted once), never decisive;
  - one decisive read at 100 independent events and 24 matured origin months, using block-bootstrap intervals by origin quarter and
    pairing against C0;
  - **the bars:** AUC ≥ 0.70 with a paired lower bound > 0; a paired Brier upper bound < 0; no inversion;
  - **a calibration bar,** which D5 requires and the draft lacked: slope 0.7–1.3, observed ÷ predicted 0.75–1.33 overall and 0.67–1.5
    in the top predicted decile. The last is Gemini's worst-decile point.
- **Precision:** an AUC interval wider than 0.15 makes the read inconclusive. There is one final read at 150 events.
- **The cost, stated:** at the draft's own rate (about 30 events by mid-2028), 100 events may take until the early 2030s. Until then
  the layer runs flagged.

*What is in force (ChatGPT's "fail closed").* **Modified.** C0 is not a validated default: it inverts and has AUC 0.65. "Keep C0" is
therefore the status quo, not a closed failure.
- **Before the read:** the development-selected candidate, which won an out-of-time walk-forward comparison over 2012–2024. It is
  flagged `distress_model_not_validated`, and the flag annotates and never blocks (non-negotiable 3).
- **After a failure:** whichever of C0 and the candidate has the lower fresh Brier score, by a rule fixed now, still flagged, and a
  new version is registered.

The residual spread is now defined: gate 1b's H2 statistic, within C0-formed solvency terciles, ranked by `log(mean_iv / price)`.

*Answers ruled on, design kept:*
- **Keep v2's median bias (ChatGPT) rather than re-centring (Gemini).** **Kept**, as approved. The bias is measured out of time per
  cell, and the margin cells are margin-level quintiles (`near_term.cell_key`). So the top quintile's year-3 bias is exactly what
  corrects the peak-margin reversion Gemini names as its failure mode 1. Re-centring would remove that correction.
- **Fixed weights and year 1 only (both agree).** Kept.
  - Gemini's sub-regime check is already reported: AL.3's E3 by origin year shows 2020–2021 under-covered.
  - Gemini's "w_Y2 ≤ 0.5 w_Y1" is noted for any future year-2 registration, not adopted now.
- **Gemini's continuous evidence score `s`.** **Rejected.** Unanchored inputs already get zero deviation (S5), so the score is already
  binary on hard evidence. A graded score of the model's own evidence is a new, unvalidated self-assessment
  (memory `claude-builds-not-part-of-system`). Hard-evidence and weaker-evidence subsets are reported as diagnostics (ChatGPT).
- **S5 adoption "gridlock" (Gemini: Bayesian shrinkage, or breadth as co-qualifier).** **Rejected.**
  - Gemini is right that annual outcomes come mostly from two dates. S5 already allows two dates for w and states that calibration
    may fall to the identity.
  - w = 0 leaves engine v2 working. A false adoption costs real money; an inert Muse costs only compute.
  - Relaxing an approved rule because its likely outcome is now visible is the move Q1 forbids. ChatGPT reached the same ruling.
- **Nonlinear distress models (both: no).** Agreed. Gemini's "use C3" is not adopted: selection is by section 4, not preference.
- **Gemini's distress-horizon critique.** **Partly accepted:**
  - a 36-month label is reported as a diagnostic in B5 section 4;
  - the debt-maturity wall is already in C1, and the Merton distance in C2 is the equity-as-option view;
  - a horizon change in the valuation is a later version.
- **The Gaussian copula's zero tail dependence (both agree on the fact; Gemini says switch to t with fitted ν, ChatGPT says keep the
  base and add a stress diagnostic).** **Kept as registered.** The marginals are empirical residual quantiles, so the single-variable
  tails are measured; only the joint tail is at issue, and that is testable on development data. **Registered now, before it is
  computed (D-T1):**
  - **The measurement:** on the vintage-2024 residual panel (outcomes filed before 2025-01-01), for every measured copula pair with
    n ≥ 300, the empirical lower-tail co-exceedance Pr(U_a < 0.10, U_b < 0.10) of rank PITs, against the Gaussian-copula rate at the
    measured r. The upper tail is reported too.
  - **The trigger:** in any pair, ratio ≥ 1.5 **and** the empirical rate's one-sided 90% bootstrap lower bound (resampling companies,
    seed 20261013) above the Gaussian rate.
  - **If triggered:** a v2.1 copula is registered separately: a t copula with ν fixed at 4, the same correlations, and E3/E4 re-run.
    It is never swapped in place and never has a fitted ν. The operator decides it together with AL.3's open E3 question.
- **D-T3, registered with D-T1 (Gemini's failure mode 1):** operating margin year-3 residual median and P10–P90 coverage by margin-level
  quintile, and the top quintile by origin year. Reported only.

*For the operator:* approve C1 draft v2 and B5 draft v2; confirm the S5 section 6 erratum and the H-S1 `mean_iv` reading.

*Related and still open (fork 2's AL.3):* the E3 decision. One caution, from the records rather than a ruling: option 2 conditions
historical residuals on MRI's turbulence flag. The stored MRI timeline before 2026-09-22 was corrupt (memory
`mri-stored-timeline-was-corrupt`), so that option would first need a rebuilt historical series, proven by its own look-ahead audit.

**AK.20 (2026-10-13 17:51): D-T1 triggered; the registered t(ν=4) remedy is shown not to fit, and is withdrawn; D-T3 reported.**

The scripts are `scratch/rev23/engine_v2_audit/d_t1_tails.py` (result `d_t1_tails_result.json`, sha256 `1361edab69cae80d…`) and
`d_t1_check.py`, an independent Monte Carlo check with 4M draws that imports neither the build nor the first script. The rule was
committed in `52b1f8d` before either was run.

- **D-T1 TRIGGERED on 6 of 18 pairs:**

  | Pair | Empirical ÷ Gaussian, lower tail | Upper tail |
  |---|---|---|
  | operating growth × margin, year 1 | 1.61 | 1.36 |
  | operating growth × margin, year 2 | 1.61 | 1.24 |
  | operating growth × margin, year 3 | 1.87 | 1.00 |
  | ROTE year 1 × year 3 | 1.90 | 2.09 |
  | ROTE year 2 × year 3 | 1.69 | 1.63 |
  | tangible-book growth × ROTE, year 1 | 1.67 | 1.80 |

  - Every trigger has a one-sided 90% lower bound above the Gaussian rate (n 1,164–6,292, companies resampled).
  - **The Gaussian rates are confirmed independently:** the Monte Carlo agrees with the integral to four decimals on all 18 pairs.
  - **What it means:** revenue and margin collapse together about 1.6–1.9 times as often as v2's Gaussian copula draws. The joint
    downside of value is therefore under-drawn, so P10 sits too high and the band is too narrow on the downside, which makes
    `undervalued` (price < P10) too easy. Gemini's point 2 is confirmed on the development data.
  - **Gate 2b does not see this.** Gate 2b scores each measure's year-1 margin on its own, and the copula does not change those
    marginals. D-T1 is the test that catches it.
- **The registered remedy does not fit (a coordinator error in AK.19, corrected here).** AK.19 named a t copula with ν fixed at 4 as the
  v2.1 candidate. Its implied co-exceedance at the same r, from the same check:
  - **growth × margin:** the empirical rate is still 1.25–1.39 times t4's in the lower tail, and t4 overstates the upper tail (0.74–1.08);
  - **growth across years:** t4 overstates the joint lower tail (empirical ÷ t4 = 0.65–0.70), where the data show no excess.

  The dependence is **asymmetric**: strong in the joint downside of growth and margin, roughly Gaussian in their upside. A symmetric t
  copula cannot represent it, because it would widen some tails that the data do not support and still miss the one that matters.
  The t4 candidate is **withdrawn before anything was built**.
- **The replacement candidate, proposed for a separate v2.1 registration (for the operator):** the **empirical copula**.
  - **The draw:** joint rank vectors resampled from the residual panel's complete company-date vectors (years 1–3 of both variables
    of the family). It has no fitted parameter, and it keeps whatever asymmetry the data hold.
  - **The year-3 and long-run pair** stays independent, as in v2.
  - **Validation, out of time:** the copula is built from vintage V and tested on residuals filed in V + 1. D-T1 is re-run per held-out
    vintage (the ratio is within 0.67–1.5 on every pair, lower and upper), together with E3 and E4. The marginals are unchanged, so
    gate 2b's year-1 scoring is unaffected.
  - **Timing:** decided before B4's SYSTEM freeze, together with AL.3's E3 question.
- **D-T3 (reported only; Gemini's failure mode 1), operating margin year 3, vintage 2024:**
  - **Residual median by current-margin quintile, l0 to l4:** +2.1, +0.6, 0.0, +0.1, **−1.2 pp**.
  - **P10 by quintile:** −16.1, −8.3, −10.9, −12.3, **−19.6 pp**.
  - **The top quintile's median by origin year,** 2017 to 2022: −3.1, −2.7, −0.6, −0.6, −0.2, −3.0 pp (n 49–176).
  - **Reading:** the top-margin cell already draws a negative median and the widest lower tail, so v2 partly carries peak-margin
    reversion through year 3. This supports keeping the median bias (AK.19).

**AL.4 E2 and E6 on real data; a correction to AL.3** (2026-10-13 17:54).

**E6 PASS:** `engine_v2_audit/e6_cut_proof_real.py`. For vintages 2019, 2021, 2023 and 2024, every fact filed on or after the cut was
changed: 171,005, 114,730, 54,333 and 23,793 facts and rows. Each table rebuilt byte-identical.

**E2:** `engine_v2_audit/e2_reproduce.py`.
- **The method:** it runs the study's own code (extracted from `review-2026-10/forecast-study`) to rebuild each table's trimmed common
  sample, and the study's reported MAE_t for (ii) reproduces exactly in all 12 tables, so the rows are the study's.
- **Pass, 6 tables:** margin k1–3 and tangible-book growth k1–3 equal their counterpart (ii) exactly: 0.0659/0.0760/0.0856 and
  0.1209/0.1203/0.1211.
- **Outside the 0.0005 tolerance, 2 tables:** operating growth k2 (v2 0.1306 against the study's (i) 0.1315) and k3 (0.1290 against
  0.1295).
  - **The cause:** in those years v2's rule is the population median, and v2 cuts it at Jan 1 of the origin year (the priors'
    vintage rule) where the study cut at the origin date (Jun 30).
  - **The direction:** v2 is the more accurate.
  - **The ruling:** a definitional difference, not a defect; it misses the registered tolerance and is recorded as E2 FAIL on those two
    tables. The vintage rule is not changed to meet E2.
- **No exact counterpart, 4 tables:** the study's blends refitted w each year. v2's fixed weights beat both (i) and (ii) in every case:
  growth k1 0.1288 against 0.1299/0.1299; ROTE 0.0709/0.0744/0.0780 against (ii) 0.0729/0.0768/0.0825.

**Correction to AL.3's E3 diagnosis:** following an outside review's correction, the sentence "no rule free of look-ahead could have
known" is withdrawn as too categorical. A pre-registered regime-aware grouping, or a deliberately heavier tail, could widen the bands
before a shock. What holds is narrower: the tables as designed learn only from misses already filed. Whether either alternative does
better out of sample is untested.

**The outside review's recommendation for the operator's E3 decision:**
- approve v2.0 and proceed to gate 2b, with E3 kept as a diagnosed FAIL (never relabelled);
- E2 and E6 run first (done);
- B4 is the decision gate (it is already per measure). Financial tangible-book growth, which is not a B4 measure, is reported on the
  2026 dates as a diagnostic;
- if B4 fails or shows material undercoverage in turbulence, build v2.1 under the existing rule;
- **noted:** gate 2b's three dates may contain no shock, so a B4 pass says nothing about turbulence. That limitation stays open into
  shadow operation.

**Also for the same decision:** the fork's AK.19–AK.20 (the D-T1 tail test triggered on 6 of 18 copula pairs, and an empirical copula
proposed for v2.1). The copula is not changed until the operator rules.

**AK.21 (2026-10-13 21:33): rulings on ChatGPT's review of the v2 drafts and AK.19–AK.20; the D-T1 evidence published.** No gate-2
outcome has been read.

*Accepted and applied, each checked against the text first:*
1. **C1 needs a specific joint-tail flag**, not just the generic `value_distribution_model_implied`. **Accepted.** C1 section 8 now has
   `joint_tail_undercoverage` on every row made with engine v2.0's Gaussian copula. It names AK.20's measurement, annotates without
   blocking, and stays until a copula version passes its own registration.
2. **B5's quarter-block bootstrap breaks within-company dependence.** A company's single exit labels up to 12 monthly origins across
   several quarters. The development "resampling years" bootstrap had the same defect. **Accepted.** New B5 section 4a, for development
   and fresh dates alike:
   - **The method:** a two-way (pigeonhole) bootstrap. Companies and 12-month origin blocks are drawn independently; each observation's
     weight is the product of the two counts; the comparison with C0 stays paired.
   - **The check:** validated before any candidate result, against interval widths beside the one-way versions and against synthetic
     coverage of 85–95% over 500 simulations with planted company and period effects.
   - **Unchanged:** the candidates, the order and the bars.
3. **S5's V5 contradicts S5 section 6** when the calibration map is not the identity. **Accepted** (a second erratum, before any
   outcome): V5 now tests the transport **before** the calibration map. The calibration path is tested separately: the identity map
   reproduces the transported distribution, and a non-identity map changes year 1 only. The median-bias rule is untouched.
4. **H-S1 still said "the calibrated IV distribution".** **Accepted.** The selection registration now reads `log(mean_iv / price)` on
   the survival-adjusted, model-implied distribution, not claimed calibrated. It is a dated correction before any selection data exist,
   with the old wording quoted. **This awaits the operator's confirmation, with the AK.19 `mean_iv` reading.**
5. **The D-T1 evidence could not be checked** because the scripts were not in the public mirror. **Accepted.** They are now published
   under `docs/rev23/evidence/engine_v2_audit/` in the mirror:
   - the four scripts and the result JSON;
   - the residual panel itself, `d_t1_residuals_cut2025.csv.gz` (43,176 rows of cik, date, family, variable, year and residual,
     derived from public SEC filings), sha256 `780254a8be8a7524…`;
   - `d_t1_from_csv.py`, which recomputes D-T1 from that file alone, importing nothing from rs2-local;
   - **its result:** the same 6 triggers and identical empirical rates. The Gaussian rates agree with the integral within Monte Carlo
     noise (largest gap 0.00015).
   - **The build code** that produced the panel is rs2-local `review-2026-10/gate2-run2` `a605eff` (public). Commit `735fcb9` is in
     stocks-workspace, which has no remote, so it cannot resolve in rs2-local; the mirror's README says so.

*Agreed recommendations that are the operator's to decide:*
- **The empirical-copula v2.1 registration:** ChatGPT approves writing it, with the eligible panel, the resampling method, the minimum
  sizes, the missing-pair rule, both tails and out-of-time bars all fixed before the build and before B4's SYSTEM freeze. The coordinator
  agrees.
- **E3, option 1 now** (keep the diagnosed failure; gate 2b's B4 judges the marginals), with no MRI-regime cells until the historical
  turbulence series is rebuilt and passes its own look-ahead audit. The coordinator agrees.
- ChatGPT's separation is the right frame: **E3 is about the marginal bands; D-T1 and the copula are about the joint distribution.** The
  empirical copula cannot fix E3's shock-year under-coverage.

**AK.22 (2026-10-13 21:40): gate-2 run 2 finished (600 of 600); the final review; the masked control started (plan A1, A2).**
- **Finished:** `gate2_finished.flag` exists (fork 2 saw it at 21:33). Statuses: ok 424, engine_refused 156, refused 17, error 3.
- **The final milestone review (`reviews/review_600.md`):**
  - leakage: 0 violations in 16,275 reviews, and 0 beyond-forecast-year items to read;
  - G5 passes on dummy outcomes, with 0 of 7,593 citations failed (1 part-label error reported, AJ.5) and 0 unrecorded fallbacks;
  - the independent script agrees with scoring and diagnostics (0 mismatches);
  - G4 behaviour: 18 of 85 registered (21%; strictly 26 of 85), with 0 accepted.

  **Two flags, both resolved:**
  - **"Technical" STOP:** the three known pre-model `growth_decay` exceptions (VIRT, MIAX, CBOE), already ruled and reproduced as clean
    refusals (AK.5, AK.14). Unchanged since 551.
  - **"NEW refusal reason: None":** RILYN, 2026-06-30. It was cleanly refused before any model call, because its common share (RILY)
    was at $298,529,958, below the $300M floor. Its progress row stores the reason under `reasons`, written by the pre-build refusal
    path, where every other row uses `reason`. So it is a reading artefact of the review script, now fixed to read either key, and not
    a run defect. Scoring counts it by status as `status_refused`, correctly. Plan B6 note: a below-floor company is outside the
    universe, not a "no view"; the live universe filter runs first.

  **A1's exit holds:** the flag exists and the last review has 0 unresolved flags.
- **A2, the masked control:** first a dry run from the frozen worktree (`wt-gate2-run2` at `a5fd342`, clean), showing 30 jobs, 0 done
  and readiness ok. Then `RS2-Gate2-Replay` was re-registered with `-Mode masked` on `data\gate2_run2`. The repeat control
  (`RS2-Gate2-Repeat`) follows when masked is final. Then score_day runs with no model loaded, and fork 2's vintage-2025 build waits
  for that.

**AK.23 (2026-10-13 21:50): the operator's approvals.** In the operator's words: "approve C1, B5, S5, mean_iv, and the engine v2 bundle". Recorded in each document:
- **The verdict contract v4** is approved at draft v2, with the AK.21 joint-tail flag.
- **The distress registration v2** is approved, with AK.21's two-way bootstrap, before any candidate is built or measured. The expected
  date of the decisive read is recorded at approval: not before about 2032.
- **S5:** both errata are confirmed: the median bias is kept and every draw shifts by w·Δ (AK.19), and V5 tests before calibration
  (AK.21).
- **Selection:** H-S1 = `log(mean_iv / price)` on the survival-adjusted, model-implied distribution, confirmed before any selection data
  exist.
- **The engine v2 bundle (fork 2's AL.3/AL.4 with AK.20):**
  - **E3, option 1:** the diagnosed shock-year under-coverage is kept as a failure on record, and gate 2b's B4 judges the marginal
    bands on its untouched dates. No MRI-regime cells are built until MRI's historical turbulence series is rebuilt and passes its own
    look-ahead audit.
  - **E2:** its two tables, operating growth in years 2 and 3, are accepted as explained: v2 cuts its medians at Jan 1, and the study
    cut them at Jun 30.
  - **v2.1:** the empirical-copula registration is to be written, and fixed before its build and before B4's SYSTEM freeze.
  - Engine v2.0 stays the engine. Its verdicts carry `joint_tail_undercoverage` until a copula version passes.

**A note on coordination.** At 21:40 fork 2 was not listed, and its message address had gone stale, so the "masked started" message
bounced. At 21:49 it reappeared as a newly started session, so its process had restarted. The message was then delivered.

**AK.24 (2026-10-13 21:56): everything stopped for the operator's PC restart (operator: "force stop it").**
- **The masked control:**
  - `data\gate2_run2\PAUSE` was set first.
  - Then, on the operator's instruction, it was force-stopped mid-company: `RS2-Gate2-Replay` stopped, runner pid 114136 and
    llama-server pid 118704 killed. The GPU shows 0 MiB.
  - The interrupted company is the first masked job, attempt `a01`, begun 21:51. By the runner's design, a crash is never resumed in
    place: the next start retries it in a new attempt folder, `a02`.
  - **To resume:** delete `PAUSE`. After the reboot the task starts at logon and waits on `PAUSE`.
- **The milestone review:** its hourly run (pid 114368, started 21:45) was stopped too. Its `state.json` was checked afterwards and
  parses.
- **Other work:**
  - fork 2 reports nothing running and its work committed;
  - Gemini Baselining stopped its batch at 59 of 161 saved answers, and it resumes with `run_batches.py --batch 5`;
  - `RS2-Baseline-Runner` has been idle since 10-12 behind `DEPTH_PAUSED`, which stays set.

**AL.5 An outside review of the engine-v2 decision; E6 completed for 2016–2024** (2026-10-13 22:33).

**E6 over every built vintage:** `engine_v2_audit/e6_cut_proof_real.py` on 2016, 2017, 2018, 2020 and 2022 as well (2019, 2021, 2023 and
2024 in AL.4). Every vintage from 2016 to 2024 rebuilt byte-identical with every later-filed fact altered: 84,886 to 249,331 facts and
rows per vintage. **E6 is satisfied for 2016–2024. Vintage 2025 is pending its build, and the freeze waits for it.**

**The review's rulings, adopted:**
1. **E2 and E3 stay FAIL.** E2's two growth tables are a documented exception: the Jan-1 cut against the study's Jun-30 cut. The tolerance
   is not amended, and nothing is redefined as a pass. The four tables compared with the study's refitted blends are recorded as
   comparisons, not replications.
2. **A gate-2b pass establishes only gate 2b's registered year-1 criteria on its dates.** It does not resolve years 2–3, shock-year
   undercoverage, joint-tail dependence or turbulence behaviour. Financial tangible-book growth is reported separately.
3. **Required before the gate-2b SYSTEM freeze:** E5 (after vintage 2025) and E6 for vintage 2025.
4. **The triggers, kept separate:**

| Evidence | Response |
|---|---|
| D-T1 triggered (AK.20) | Register and evaluate the empirical-copula candidate (v2.1). It cannot correct the marginals. |
| Gate 2b fails a registered year-1 calibration bar | Record the measure; investigate a separately registered marginal-calibration candidate. |
| Shadow operation shows material undercoverage in turbulence | A pre-registered investigation of the marginal and/or joint tail, on a rebuilt look-ahead-audited regime history (MRI's pre-2026-09-22 timeline is unusable). |
| Gate 2b passes but contains no relevant shock | Turbulence performance stays unvalidated; the limitation is kept and monitored in shadow operation. |

5. **Conditions for the v2.1 copula registration** (passed to the fork, which drafts it):
   - only the dependence changes; the v2.0 marginals are kept;
   - built on vintage V and evaluated on untouched residuals from V+1;
   - lower and upper tails both tested;
   - E3 and E4 re-run;
   - E5 re-run unless an independently justified invariance test shows the rankings cannot change;
   - the definition and the bars frozen before any result is inspected;
   - a candidate passing its tests does not by itself authorise adoption.

**Not approved, as the review states:** reading a gate-2b pass as resolving shock-year undercoverage or joint-tail dependence; changing
v2.0's cut, bars or weights to obtain a pass.

**Transparency:** the reviewer saw a mirror ending at AK.20. The fork's mirror refresh (`d6d286b`) now carries AK.23, and this entry needs
the next refresh.

**AK.25 (2026-10-13 23:00): scoring moves ahead of the repeat control (the operator: "earlier the checking the better ... you're not modifying the
intention of the run"), and an unattended chain runs it.**
- **The masked control resumed** at 22:35 after the restart (PAUSE removed, one runner, server loaded). By 22:55 it was at 5 of 30.
  The first company was retried in a new attempt folder, as AK.24 said.
- **Why the order change leaves the run's meaning intact:**
  - R8 is a reported diagnostic, not one of the bars G1–G6;
  - R8 reads no outcome: it compares placed percentiles between two runs;
  - the repeat control runs from the frozen worktree (`a5fd342`) on hash-verified copies with its own freeze (AK.17), so knowing the
    score cannot alter it.
  Every bar, threshold and reading rule is unchanged. G6 still needs the masked control, and scoring still waits for it.
- **The code:** `score_day` gains `--repeat-later` and an `r8` stage (rs2-local `review-2026-10/gate2-run2` `97e19a6`, pushed after a
  scan; suite 738 passed, including 2 new tests).
  - `--repeat-later` waives only the repeat-control precondition; every other refusal stands. The report says "R8: deferred".
  - `r8` writes `r8.json` once, beside an existing score, and only on a final repeat control.
- **The chain:** scheduled task `RS2-Gate2-PostMasked`, files in `scratch/rev23/gate2_audit/chain/`, runs every 15 minutes and at
  logon. It exits at once until the masked control is final and no llama-server runs. Then, once:
  0. disable `RS2-Gate2-Replay`;
  1. `score_day refresh` (new companyfacts snapshot and outcome store; standing SEC approval);
  2. `score_day score --repeat-later`;
  3. register `RS2-Gate2-Repeat`;
  4. write `DONE`.

  A failed refresh or score is recorded as `FAILED_<step>`, and the repeat control is still registered, since it does not depend on
  scoring. A pid lock prevents doubles, and a stale lock is cleared. Its first test run returned 0 and did nothing, as expected.
- **Nothing is reported automatically.** The coordinator audits the score first: the independent recomputation, Audit 1 and the hand
  check (Q4).
- **Fork 2's CPU-heavy vintage-2025 pass** now waits until the repeat control ends, because the repeat loads the model straight after
  scoring. It is not urgent: gate 2b's freeze comes after the 10-30 filings.

**AL.6 Vintage 2025, step 1: the residual panel re-joined to the vintage-2025 outcomes; a tag-choice property of the shared extractor found** (2026-10-13 23:00; operator: "go ahead with vintage 2025").
- **The script:** `scratch/rev23/engine_v2_audit/panel_cut2025.py`. It runs the forecast study's own `panel.build`, unchanged, with two constants set for vintage 2025:
  - `OBS = data/priors_v3/2025/obs.csv.gz` (cut 2026-01-01, first-filed values);
  - `CUT = 2025-12-31` (the study's `assert_cut` then refuses any outcome filed later).

  It writes once, to a new file; the study's `panel.pkl` is untouched.
- **One workaround:** `pandas.read_csv` runs with `low_memory=False`. The chunked reader crashed on the larger 2025 table while composing a
  mixed-type warning (`IndexError`). Whole-file type inference reads the same file; the study's `load_obs` is otherwise unchanged.
- **The output:** `scratch/rev23/forecast_study/out/panel_cut2025.pkl`.
  - 13,309 rows; origins 2016-06-30 to 2024-06-30.
  - 99.11% matched.
  - The latest outcome was filed 2025-12-29.
  - 74 stale bases were excluded.
  - It ran at below-normal priority while the masked control ran, using 2.7 GB of physical memory.
- **Check against the study panel,** joined on (date, cik), all 13,309 rows:
  - the code forecasts are identical;
  - outcomes gained from 2025 filings: about 1,000–1,600 per measure (for example g_1 10,740 → 12,102; g_3 7,898 → 9,509);
  - old outcomes that changed value: 8–16 per measure (g_1: 14 of 10,740, 0.13%);
  - old outcomes that disappeared: 2–5 per measure.
- **Why outcomes changed (negative finding, not my code).** The same filing, with the same accession and filing date, yields a different
  revenue at the two cuts. The shared extractor (`valuation.pit_data`, `fiscal_years(cut, "first_filed")`) chooses the revenue tag using
  every filing before the cut, so a later filing can move an earlier period from one tag to the other.

  | Company | Fiscal year | Filing (filed) | Cut 2025-01-01 | Cut 2026-01-01 |
  |---|---|---|---|---|
  | CIK 1042893 | 2018 | 0001042893-19-000003 (2019-02-27) | 384.6M, `Revenues` | 337.5M, `RevenueFromContractWithCustomerExcludingAssessedTax` |
  | CIK 78003 | 2023 | 0000078003-24-000039 (2024-02-22) | 50.9B, `RevenueFromContractWithCustomerExcludingAssessedTax` | 58.5B, `Revenues` |

  The flip goes in both directions; neither tag is uniformly right. It is point in time: each cut reads only filings before itself, and
  the store fingerprint is identical for both vintages (`7de131bd…`). So it is not a leak, and each vintage's near-term table correctly
  uses its own vintage's outcomes.

  It does mean that a historical fact is not fixed across vintages. Revenue in particular can switch between the total and the
  contract-revenue tag. Owner: the shared extractor, not engine v2. Recorded as an open data-quality item for whoever owns
  `pit_data`, not fixed here (surgical scope). The effect on vintage 2025's residual quantiles is at most 0.13% of the rows.
- **Still to do** (the CPU-heavy part, which waits until the repeat control ends, per AK.25):
  1. a pass at origin 2025-06-30, with the study's `LAST_ORIGIN` guard lifted explicitly for engine v2 only;
  2. the panel re-built to a new file that includes that origin;
  3. `data/priors_v4/2025` built;
  4. E6 for 2025;
  5. then E5.

**AK.26 (2026-10-13, about 23:10; corrected in AK.27 from "23:20", which was not a Get-Date value and lay in the future): fork 2's AL.6 finding (the revenue tag is chosen per cut) is checked against gate-2 outcomes; a check is registered before
any outcome is read.**
- **The finding:** `pit_data` chooses each company's revenue tag from all filings before the cut. The same accession can therefore show
  a different revenue at a different cut (AL.6: CIK 78003 FY2023 is 50.9B at the 2025-01-01 cut and 58.5B at the 2026-01-01 cut). This
  is point in time, not a leak.
- **The gate-2 q1 outcomes (the hard bars) are not exposed.** `outcome_extract.quarter_outcomes` reads one `quarterly_rows(cik, None, ...)`
  call. The quarter and its year-earlier comparative come from that single selection.
- **The annual (fiscal-year-1) outcome is exposed.** `annual_outcomes` takes r0 and m0 from `build(pit_at(cik, T))` and r1 and m1 from
  `build(pit_at(cik, filed_1 + 1 day))`, two different cuts. A tag switch between them would put a level step into the measured
  growth and margin change.
  - **Tonight** the annual target is reported only: R3 diagnostics; the hard bars use q1.
  - **It becomes primary** for S5's fit and calibration (B4) and for gate 2b.
- **Registered now:**
  1. **Audit 1 adds a tag-consistency check** on every annual outcome: r0' and m0', the base-year revenue and margin as resolved at the
     year-1 cut. It reports the rows where |r0'/r0 − 1| > 0.5% or |m0' − m0| > 0.1 pp. Every annual diagnostic is reported twice, as
     registered and same-cut (growth r1/r0', margin change m1 − m0'), and the count is stated.
  2. **Before B4, `annual_outcomes` is corrected to the same-cut base** (r0', m0'), with a test. A growth or margin change measured
     across two different tags is not a measurement of the company. This is a measurement correction fixed before any annual outcome is
     read, recorded and shown to the operator; it is not a choice made on results.
  3. **ROTE (`rote_latest`)** gets the same check.

**AL.7 The extractor mixes revenue tags across years within one cut, and some growth figures are false** (2026-10-13 23:04; follow-up of AL.6; a measurement only, nothing changed).
- **Found from AL.6's examples.** At cut 2026-01-01, CIK 1042893's series reads:
  - FY2015–2017 from `Revenues` (FY2017 455.5M);
  - FY2018 onward from `RevenueFromContractWithCustomerExcludingAssessedTax` (FY2018 337.5M).

  So its FY2018 growth is −25.9%. The FY2018 annual report itself gives `Revenues` for both years (455.5M → 384.6M), which is −15.6%. The
  break is inside one cut, not only across cuts.
- **Measured** (`scratch/rev23/engine_v2_audit/tag_breaks_sample.py` and `tag_breaks_effect.py`). A seeded random sample of 300 companies
  (seed 20261013), all sizes, cut 2026-01-01, read-only, low priority; commit headroom was 34.8 GB.
  - 292 companies; 1,641 consecutive-year revenue pairs.
  - 123 pairs (7.5%) change tag, in 96 companies. Most changes are the ASC 606 transition in 2018–2019 and are harmless.
  - Against the growth given by year t's own annual report (its comparative column under year t's tag; otherwise year t−1's tag for both
    years from that report), 118 pairs could be checked. The extracted growth differs by:
    - more than 1 point in 17 pairs (1.0% of all pairs);
    - more than 5 points in 9 (0.55%);
    - more than 20 points in 6 (0.37%).
  - Largest cases:
    - CIK 835011 FY2018: +1,544% extracted vs +8.2% in the filing;
    - CIK 1697851 FY2020: −52% vs +69%;
    - CIK 945983 FY2018: −60% vs +13%.
- **Reach.** Every consumer of `pit_data.fiscal_years(..., "first_filed")` revenue:
  - the priors v3 observation tables, and so the frozen c7d7a4f priors that gate 2 uses (the features g_latest and g3, and the growth
    cells);
  - engine v2's near-term residual tables (2016–2025), where false growth outcomes land mostly in the P1/P99 tails;
  - the annual outcome of gate 2 (fork 1, AK.26).

  Gate 2's q1 outcomes come from `quarterly_rows` and are not exposed (fork 1, AK.26).
- **What it is not:** a look-ahead leak. Each cut reads only filings before itself.
- **Owner and next step.** The shared extractor (`valuation/pit_data.py`), which neither fork owns. Under non-negotiable 2 the fix belongs
  in the extractor, not in any consumer. A fix would change every priors vintage, and with it the frozen c7d7a4f inputs. So it is an operator
  decision, not a drive-by edit. It is also held until fork 1's scoring chain finishes (`chain/DONE`), because scoring imports `pit_data`.

  Proposed for the ruling: growth taken from one filing's own comparative columns (both years under one tag), with a tag change between
  years stamped. This would be measured first by the vintage-by-vintage effect on the priors tables and on E3/E4, before anything is
  adopted.
- **Engine v2 now:** vintage 2025 proceeds on the current extractor, consistent with 2016–2024. The defect is a known and measured limitation
  of all ten tables, not a reason to rebuild one of them alone.

**AK.27 (2026-10-13 23:16): a correction to AK.26. The q1 outcomes ARE exposed to tag switches (fork 2's AL.7). The check is widened before any
outcome is read.**
- **AL.7:** a revenue series can switch tag between consecutive periods **within one cut**. At the 2026-01-01 cut, CIK 1042893 has FY2017
  from `Revenues` (455.5M) and FY2018 from the contract-revenue tag (337.5M): −25.9% against −15.6% in its own 10-K. Fork 2 measured 300
  random companies (1,641 consecutive-year pairs): 7.5% switch tag. Against the growth in year t's own filing, the extracted growth is
  off by more than 1 pt in 1.0% of pairs, more than 5 pt in 0.55% and more than 20 pt in 0.37%.
- **The coordinator's error:** AK.26 said q1 is safe because its value and comparative come from one `quarterly_rows` call. One call does
  not mean one tag. `PitData.quarters` chooses a tag for each period separately (every record carries its own `tag`). So the q1 quarter
  and its year-earlier quarter can sit on different tags, and the G1 revenue-growth outcome can carry a false step. The margin outcome
  can too, since revenue is its denominator. Corrected here, before any outcome is read.
- **Registered now (replacing AK.26's items 1–2):**
  1. **The tag-consistent outcome, measured from one filing.** For each q1 row, take the growth and the margin change from the comparative
     columns of the q1 filing itself: the same accession reports the quarter and the year-earlier quarter under one tag. This is fork 2's
     cleaner rule. The annual outcome likewise uses the year-1 10-K's own comparative column for year 0. Rows where the filing has no
     same-tag comparative are listed, never dropped.
  2. **Audit 1 reports**, per measure and target, the count where the registered outcome and the tag-consistent outcome differ by more than
     1 pt (growth) or 0.1 pt (margin). Every bar and diagnostic is reported both ways.
  3. **Which governs is the operator's decision, to be taken before the coordinator reads any score.** The coordinator proposes that the
     tag-consistent outcome governs. A growth measured across two tags is not a measurement of the company, and the correction is fixed
     before any outcome is read. The registered version stays reported beside it. If the operator does not rule first, the registered
     version governs, as registered.
- **Further reach (AL.7):** the priors v3 observations (the code's `g_latest`/`g3` features and growth cells), and so gate 2's inputs,
  and engine v2's residual tables. Those are inputs, frozen for run 2. The repair belongs in `pit_data`, owned by neither fork, and would
  change every priors vintage and the frozen inputs. It goes to the operator as a separate decision. Nothing changes now.

**AL.8 (2026-10-13 23:17): rulings on the outside review of the revenue tag-seam problem report.** The operator forwarded the review. The
reviewer saw the report's summary, not the file, and the summary still said q1 was unaffected. Each point is ruled on below.
1. **Approach: ADOPTED, diagnostics only.**
   - **What lands:** provenance flags that change no value. Per year: the selected tag, any backfill tag, the accession and period, and
     whether a year-to-year figure crosses a tag change (`tag_seam`).
   - **Where:** in `pit_data`, on top of the vendored extractor, like `SUPPLEMENTS`. The vendored file stays byte-identical to the
     screener's.
   - **When:** only after fork 1's `chain/DONE`, because scoring imports `pit_data`.
   - **Before either value fix:** all five report cases are checked by hand against the filed income statements, including whether the
     reference is total revenue. A broader before-and-after validation follows.
   - **Status of the numbers:** the measured prevalence is provisional. The other `COMBINED` fields are "suspected, unquantified".
2. **Gate 2: ADOPTED, with one correction from the record.**
   - **What stays:** the frozen inputs and the running chain are preserved unchanged, as the original reproducible result, with its
     known limitation stated.
   - **The correction:** the reviewer kept q1 unchanged "provided their independence ... is confirmed". AK.27 disproved that independence.
     By the reviewer's own condition, q1 is therefore qualified like the annual outcome. AK.27's comparative-column version is reported
     beside it, and the operator decides which governs before any score is read.
   - **Also required:**
     - the affected company-dates, with numerator and denominator;
     - a sensitivity analysis for the affected outcomes before they count as clean evidence.

     Owner: fork 1.
3. **Engine v2: ADOPTED, with a label.**
   - **The label:** vintage 2025 is the **legacy-extractor vintage**. So are 2016–2024, which were built on the same extractor. All ten
     carry the label: the 2025 table in its own metadata, and all ten in a lineage file beside them (`data/priors_v4/LINEAGE.json`). That
     file records the vendored extractor's sha256, the store fingerprint and each table's sha256.
   - **If a value fix is adopted:** all ten are rebuilt together as a new version, and v-legacy is kept with its hashes.
4. **Live screener: ADOPTED, no live value fix.**
   - Development happens only on an isolated branch.
   - Any deploy, including a warning-only change that alters the site or the schema, needs a named release, the commit, regression tests,
     a before-and-after comparison, a rollback plan and a list of who sees changed numbers.
5. **The three questions: ADOPTED.** The report separates them:
   - Is the cause real?
   - How prevalent is it?
   - Does it change a decision?

**AK.28 (2026-10-13 23:18): the tag-consistent outcome rule is completed before any outcome is read; the v2.1 registration is drafted;
cross-check 10 is written.**
- **Fork 2's caution:** a single tag inside one filing can still be a partial line. In CIK 1720446's FY2018 10-K the contract tag is
  2,048.9M for 2017 but a 530.2M slice for 2018. So AK.27's rule is completed as follows, fixed now:
  1. **Several tags for both periods.** Where the outcome filing carries more than one revenue tag (from the extractor's revenue ladder)
     for both the current and the comparative period, the tag with the **largest current-period value** is used, because a total is
     never smaller than a line within it. The number of rows where the tags present disagree by more than 1 pt is reported.
  2. **A derived Q4** (fiscal year minus nine months) is tag-consistent only when one tag is present for both periods in both filings, the
     10-K and the Q3 10-Q. Otherwise the row is listed as having no tag-consistent outcome, never dropped from the registered version.
  3. **Operating income** follows the same rules, and the margin uses the revenue chosen above.
  4. **The audit script is the coordinator's** (`scratch/rev23/gate2_audit/`). It imports nothing that scoring imports, writes
     nothing into the run's state, and runs after the score exists. Before any outcome is read, it is first tested on quarters filed
     before T.
- **The v2.1 registration** is drafted in `REGISTRATION_engine_v2_1_copula.md`: the checkerboard empirical copula, the AL.5 conditions,
  the tests C1–C5 and the bars, all fixed before any build. It goes to fork 2 to read (it owns the build), then to cross-check 10, then
  to the operator.
- **Cross-check 10** is written: `CROSS_CHECK_10_scoring_day_tag_seams_copula.md`, covering the tag seams, the meaning of the gate-2
  verdict (G4, a hard bar, is already at 21% against 10%, independent of any outcome), the scoring order and v2.1. The review of the
  downstream changes (C2), earlier called cross-check 10, becomes cross-check 11.

**AL.9 (2026-10-13 23:21): the hand check of the problem report's five cases (AL.8 item 1); one case withdrawn; the counts corrected downward.**
- **What was read:** the SEC's rendered income-statement page of each case's accession, downloaded under O5 with the workspace's declared
  SEC identity. Scripts: `scratch/rev23/engine_v2_audit/handcheck_fetch.py` and `handcheck_read.py`; the pages are in this session's
  scratchpad.
- **Confirmed (4).** In each, the reference is the statement's total revenue line, and the extracted growth is wrong:

  | CIK | Filed total, year t−1 → year t | Filed growth | Extracted growth |
  |---|---|---|---|
  | 1042893 | "Total revenues" 455,469K → 384,626K | −15.6% | −25.9%; the contract tag is "Revenues from products and services", without leasing |
  | 835011 | "Net sales" 347,448K → 376,089K | +8.2% | +1,544% |
  | 46080 | "Net revenues" 5,019,822K → 5,209,782K | +3.8% | +137% |
  | 76267 | "Net sales" 40,230K → 51,116K | +27.1% | −54% |
- **Withdrawn (1): CIK 1720446, which is not a tag seam.**
  - **What it is:** an RMB reporter. The extracted values are the USD convenience translations of each year's own report, both totals
    (FY2018 $530,192K = RMB 3,645,335K). Its +68% is USD growth at two year-ends' rates, against +77.9% in RMB.
  - **My error:** I called 530.2M a "slice". It came from my measurement script, which compared values across units (USD against CNY).
- **The script is fixed** to compare only within the cell's unit. Re-run on the same seeds:

  | Sample | Off by > 1 pt | > 5 pt | > 20 pt |
  |---|---|---|---|
  | All filers | 16 (0.98%) | 8 (0.49%) | 5 (0.30%) |
  | $300M+ panel | 17 (0.73%) | 11 (0.47%) | 9 (0.38%) |

  Previously these were 17/9/6 and 19/13/11. The first outputs are kept as `*_v1_unit_mix.json`.
- **The problem report is revised** (section 9 there): the cases, the counts, the three-questions table (AL.8 item 5) and the AL.8
  rulings.
- **Not part of this report:** mixed-rate convenience translation of foreign filers. It is noted as a possible separate question.

**AK.29 (2026-10-13 23:23): fork 2's builder's read of the v2.1 draft, all adopted (draft v2); a unit rule added to AK.28; cross-check 10
corrected.**
- **The v2.1 draft is revised to v2. Fork 2's four points, all adopted:**
  1. **The minimum against the test vintages.** Complete vectors reach 500 only from 2021 for operating and 2022 for financial, so
     earlier vintages would fall back to v2.0's copula and dilute every pooled comparison toward a tie. Test vintages are now per family:
     operating 2021–2024, financial 2022–2024. V = 2024 needs fork 2's vintage-2025 panel, a dependency now stated.
  2. **The ranks** are taken among the n complete vectors, not the coordinate's pool. Otherwise U is not uniform and C3 fails by
     construction.
  3. **The draw** does not change `common.draw_inputs`, which v1 shares (E7). Each joint draw's six near-term values are replaced by
     `Q_i(U_i)` from the copula's own stream, `random.Random(f"{seed}|nt_copula_v2.1")`. Every other input stays byte-identical to v2.0.
  4. **"Untouched" is defined for vectors and pairs:** test vectors are complete at V + 1 but not at V; test pairs are present at V + 1
     but not at V.

  Also recorded: the cross-block precondition holds by construction; v2.0's not-positive-definite drop is reported beside C1 and C2; C2
  covers the six pairs that v2.0 left independent.
- **Fork 2's hand check (AL.9):**
  - 4 of 5 seam cases are confirmed against the filed statements.
  - CIK 1720446 is withdrawn. It was an RMB filer's USD convenience translation, mixed across units by fork 2's measuring script.
  - The rates are corrected to 0.47% above 5 pt and 0.38% above 20 pt.
- **Consequences:**
  - **AK.28's "largest current-period value" rule now compares tags only within one unit** (the outcome's currency), fixed before any
    outcome is read.
  - **Cross-check 10 is corrected in place:** 1720446 withdrawn as the failure-(b) example, the rates updated, and the unit rule added.
    The mirror copy from 23:18 carried the withdrawn example. Reviewers who fetched it before this refresh are told in the cover message.

**AK.30 (2026-10-13 23:23): the operator rules that the tag-consistent outcome governs** ("tag-consistent governs, go ahead with the audit
script"). The ruling was given before any gate-2 outcome was read and before the score exists.
- **For every gate-2 bar and diagnostic, the tag-consistent outcome (AK.27–AK.29) is the measure of record.**
- **The registered extractor outcome is reported beside it**, with the count of rows that differ.
- **A row with no tag-consistent outcome** is listed with its reason. It is excluded from the governing version only, and never from the
  registered one.
- **The mechanism.** The automatic chain scores the registered version, since its code is held unchanged under the scoring freeze. The
  coordinator's audit script then rebuilds the outcomes tag-consistently and re-scores with the same scoring functions. That result
  governs, and it is what the operator is told.

**AL.10 (2026-10-13 23:25): a point-in-time defect in my engine-v2 table build, found through AL.6; the fix is registered before it is built or measured.**
- **The defect.** The near-term tables for vintages 2016–2024 (`data/priors_v4`, AL.3) read their inputs from extractions made at a
  later cut than the vintage's own.
  - **The outcomes** come from the study panel, which was joined to the **vintage-2024** observation table.
  - **The medians i_k** come from the **vintage-2025** observation table, filtered by filing date.

  Filtering by filing date keeps every value filed after the cut out. It does not undo the extractor's tag choice, and AL.6 shows that
  choice depends on every filing before the extraction's own cut. So, for example, the vintage-2019 table can carry a value that the
  extractor would have taken from a different tag at 2020-01-01.

  This is look-ahead in tag selection, about 0.1% of values (AL.6: 8–16 per measure). E6's cut proof cannot see it, because it perturbs
  facts inside an observation table that has already been extracted.

  SPEC_engine_v2 section 2 requires i_k "under the priors' rule", which means the vintage's own observation table. My build did not meet
  that. My error, in my own code.
- **The fix,** decided now, before any number from it exists:
  - **Medians:** i_k at an origin's own cut (1 January of year Y) are read from `data/priors_v3/<Y−1>/obs.csv.gz`. Origins run from
    2017; origin 2016 has no code forecast, so vintages 2016–2024 are all needed, and all exist.
  - **Outcomes:** the outcomes of vintage V's table come from a panel joined to `data/priors_v3/<V>/obs.csv.gz` with CUT = V-12-31,
    using the study's own `panel.build`, as in AL.6. That is one panel per vintage, 2016–2025.
  - **Vintage 2025** already uses its own observation table for outcomes, and gets the same median rule.
  - **Nothing else changes:** weights, cells, quantile levels, MIN_N, the copula rule and every bar stay as they are.
- **Where:** new tables go to a new directory, `data/priors_v4_pit/`. The AL.3 tables stay untouched, for comparison.
- **What is re-run, with bars unchanged:** E1–E4 and E6 on the new tables. A per-vintage diff against the AL.3 tables is reported,
  negatives first. E5 runs once, on the corrected tables, after vintage 2025. Which directory the engine freezes on goes to the operator
  with the diff.
- **The cut proof is strengthened (E6b):** for each vintage, the obs used must be the vintage's own (its `obs_meta` cut date equals the
  table's cut). The builder refuses otherwise.
- **Label (AL.8):** the new tables carry `extractor: legacy` with the vendored extractor's sha256 (`7de02ffb…`). The priors_v3
  observation tables were built 2026-10-07 14:27–14:46, after that file's last change (e5be9ff, 2026-10-07 00:32).

**AL.11 (2026-10-13 23:29): building AL.10's per-vintage panels exposed two more data defects. Both are written up; nothing in `pit_data` is changed
(the scoring hold).**
- **Fiscal years mislabelled by a forward-looking fact.**
  - **Mechanism:** `pit_data.accessions()` sets a report's own period from the latest end among any of its fiscal-year-length
    durations, in any unit. One forward fact relabels the report. Boeing's FY2017 10-K (2018-02-12) files the 2018 statutory tax rate
    for calendar 2018, and so becomes "FY2018".
  - **Within a vintage:** a year goes missing, so inputs are stale.
  - **Across vintages:** the FY2018 values carry the 2018-02-12 stamp, which is look-ahead for any consumer that filters a later
    vintage's table by stamp. My AL.3 tables and the forecast study did exactly that.
  - **Size:** 0.44–0.70% of observation rows per vintage. In the study panel, about 0.1–0.6% of outcomes are stamped before their own
    period ends.
  - **Report:** `PROBLEM_REPORT_fiscal_year_mislabel.md`.
  - **AL.10's per-vintage rebuild** removes the look-ahead from engine v2. The missing years remain until `pit_data` is repaired.
- **One row in vintage 2017 breaks the observation rule.**
  - **The row:** CIK 1670869, FY2017-06-30. Its value comes from a 10-K/A filed 2017-10-12, but its own report is a 10-KT filed
    2018-04-02, after the cut. It also appears as the FY2016 row's year-1 outcome.
  - **Handling:** the study's `assert_cut` refused that vintage's panel. `panel_cut.py` now drops such rows and outcomes explicitly,
    lists them, and stores the list in the panel's attributes. No other vintage has one.
- **Per-vintage panels built** (`scratch/rev23/forecast_study/out/panel_cut<V>.pkl`, 2016–2024; 2025 from AL.6).
  - Compared with the study panel, they hold slightly fewer outcomes before each cut: 2017 1,534 vs 1,548; 2018 4,113 vs 4,183; 2019
    7,870 vs 7,898.
  - Spot check: the outcomes the study panel has and these lack are values stamped before the cut but filed after it (for example,
    Boeing's FY2018 revenue as a year-2 outcome of origin 2017), or rows whose base did not match at the earlier cut.

**AK.31 (2026-10-13 23:32): the tag-consistent audit script is built and dry-tested before any outcome is read. A second, larger defect is
found in the extractor's outcome mode: recasts.**
- **The script:** `scratch/rev23/gate2_audit/tag_consistent.py`, mirrored with its evidence under `docs/rev23/evidence/gate2_audit/`.
  - `rescore`: rebuilds every q1, q2 and annual outcome from one filing's own comparative columns (AK.27–AK.29), then re-scores with the
    registered scoring functions (`score_day.run_stages`) into a folder outside the run's state. Per AK.30 that result governs.
  - **What it reads:** the store's raw facts, merging annual-report and quarterly-report facts (the store keeps them apart), and none of
    the extractor's tag-choice logic. The tag ladders are copied from `pit_data.quarter_fields()`.
  - **The ROTE denominator:** the run's own `tbv_0` at T. The annual ROTE change is not rebuilt: its registered value is kept and
    flagged.
- **The dry test (no outcome read).** For each of the 600 sample company-dates, the latest quarter **filed before T**, measured by the
  extractor (`quarterly_rows`, first-filed) and by the same-filing rule:
  - 482 compared, 88 with no same-filing pair, 201 of the pairs derived Q4s;
  - 462 agree within 1 pt on growth; 28 disagree on growth or margin; **14 differ by more than 5 pt**.
- **What the disagreements are, from the raw facts:**
  - **(a) Recasts, the larger class and a new defect.** A company that sells a business re-reports last year's quarter as continuing
    operations. The extractor's OUTCOME mode (`first_filed`) takes last year's quarter as first filed, so the comparison is new continuing
    revenue against old total revenue.
    - **TDS (CIK 1051512):** its own 10-Q gives a prior-year quarter of 327.5M; the extractor takes 1,224M, making the growth −74.8%
      against −5.8%.
    - **Dollar Tree (CIK 935703), after the Family Dollar sale:** 4,068.6M against 7,378.8M, making −38.1% against +12.3%.
    - **CIK 1973266:** a retroactive presentation change, +64.4% against −27.3%.
  - **(b) Tag seams (AL.7).** CIK 810332's Q4 was stitched as `Revenues` minus the contract tag: +1,254% against +32%.
  - **(c) Derived Q4s across a recast.** These are caught by a guard added now, before any outcome: when the 10-K's prior-year figure
    differs from the one first filed (more than 0.5%), the derived Q4 is not like for like, so the row has no tag-consistent outcome and
    is listed.
- **What it means:**
  - About 3% of quarters (14 of 482) would carry a growth error above 5 pt under the registered outcome. That is material for G1, and it
    supports the AK.30 ruling.
  - The same `first_filed` comparison underlies every outcome built across years from first-filed values. That includes the forecast
    study's outcomes and engine v2's residual tables (fork 2's area; it has been told).
  - The inputs (`as_known` mode) take each period's latest filed value, so recast comparatives are mostly consistent there; the
    seam (AL.7) remains.
- **Still to register for Audit 1 (fork 2's AL.10–AL.11):** a count, over the 600 company-dates at T, of annual reports whose assigned
  period ends after their own filing date, and of latest fiscal years older than expected. These are the fiscal-year mislabel's effect
  on gate-2 inputs, reported with numerator and denominator.

**AL.12 (2026-10-13 23:37): AL.10 built and measured. The point-in-time tables differ little from AL.3; E3 and E4 are unchanged in verdict.**
- **The build:** `priors_build/near_term.py` gains a per-vintage mode, `--obs-root` and `--panel-pattern` (rs2-local
  `review-2026-10/gate2-run2` f02628f, with the lazy medians in a3fcc87).
  - Each vintage reads only its own extraction. The builder refuses an obs table whose `obs_meta` names another vintage or cut, or
    whose bytes do not match its `obs_sha256` (E6b). It refuses a panel whose attributes do not name that obs and the cut V-12-31.
  - Tables carry `extractor`: label `legacy`, the vendored sha256, the store fingerprint and the two known defects (AL.8 item 3).
  - Medians are computed only for origins that have a residual, because origin 2016 has no forecast and there is no vintage 2015.
  - The single-obs mode is byte-identical to AL.3: vintages 2020 and 2024 were rebuilt and match their sha256.
  - Tests: 8 builder tests (4 new: medians per origin cut, own-obs refusal, panel refusal with label, per-vintage cut proof).
    Suite: 742 passed (738 + 4).
- **The output:** `data/priors_v4_pit/2016..2024`. The AL.3 tables are kept.
- **Diff against AL.3** (`scratch/rev23/engine_v2_audit/al10_diff.py`, `al10_diff.json`), negatives first:
  - The largest pool-quantile change is 0.038, in operating margin year 2 at vintage 2018 (n 62 → 61). Others are 0.002–0.018 at
    2017–2019 and at most 0.005 from 2022 on.
  - Population medians move by up to 0.020 (vintage 2016, which has no residuals) and at most 0.004 from 2019 on.
  - Copula correlations move by at most 0.017.
  - Cell counts are unchanged in every vintage.
- **E3 and E4 re-run** on these tables (`e3_e4.py` with an obs root: medians at each origin's own cut from its own vintage; outcomes
  from `panel_cut2024`):
  - every cell keeps its n;
  - coverage moves by at most 0.6 points (for example, operating growth year 3 is 0.686 → 0.681; operating margin year 2 is 0.666 →
    0.661);
  - **E3 FAIL as before**, with the same diagnosis (AL.4);
  - **E4 PASS as before**, with 3 of 12 cells worse.

  Output: `e3_e4_pit.json`.
- **E6 on these tables** holds by construction plus E6b. Each panel's `assert_cut` and each obs table's own cut admit no fact filed
  after the cut, and the per-vintage cut-proof test perturbs every late fact in the panel and in every obs table.
- **E1 and E2 are not affected.** E1 checks the centre formulas, which do not depend on the tables; E2 reproduces the study.
- **The decision for the operator:** the engine freezes on `priors_v4_pit`. It is point in time, and its differences from AL.3 are
  within the noise shown above. Vintage 2025 will be built the same way.
- **Note:** a scratch rebuild of 2020 and 2024 for the identity check was written to `C:\c\Users\riper\AppData\...\v4_recheck`
  because of a path-form slip. It is left in place; the operator may remove it.

**AK.32 (2026-10-13 23:37): the tag-consistent re-score is rehearsed end to end, with no real outcome, and joins the overnight chain.**
- **The rehearsal:** `scratch/rev23/gate2_audit/rehearse_tc.py`. Its pseudo-outcomes put the latest quarter filed before T as q1; all
  else is score_day's dummy outcomes.
  - `tag_consistent.py rescore` rebuilt 424 rows: 348 with a tag-consistent q1, 14 differing by more than 1 pt, and 17 with tags
    disagreeing inside one filing.
  - It re-scored them with `score_day.run_stages` and got **0 mismatches** against the independent script.
  - Audit 1's look-ahead check flagged the 411 pseudo-outcomes filed before T, as it must: the check works.
- **The chain:** `chain/post_masked_chain.py` gains step 2b. After the registered score, it runs the tag-consistent re-score into
  `scratch/rev23/gate2_audit/tag_consistent/<scoring date>/`, outside the run's state. Then the repeat control is registered. A failure
  is recorded and does not block the repeat control. A no-op run after the edit returned 0.
- **In the morning both versions exist.** Per AK.30 the tag-consistent one governs. The coordinator audits both (Audit 1, the hand check)
  before anything is reported.

**AK.33 (2026-10-13 23:38): the fiscal-year mislabel's reach into gate-2 inputs, measured (fork 2's AL.10–AL.11; inputs at T only, no
outcome).**
- **The script:** `scratch/rev23/gate2_audit/fy_mislabel_check.py`, run on the packs' store at each T. The signature is an annual report
  filed before T whose assigned period ends after its own filing date.
- **44 of 600 company-dates (7.3%)** have at least one such report in their history: 36 operating and 8 financial. Most of those reports
  were filed in 2010–2019 (2010: 1, 2011–2016: 40 together, 2018: 8). So the effect sits in the long history the inputs summarise:
  multi-year medians, trailing growth and the history Muse is shown. There it shows as a missing or shifted year.
- **1 of 600 (0.2%) has the latest report itself mislabelled:** Avnet (CIK 8858) at 2025-12-31. Each of its 10-Ks from 2023 to 2025 is
  stamped a year ahead (FY2025, filed 2025-08-15, is labelled 2026-06-27), so the base year the engines saw is a year stale. That row was
  `engine_refused` (no trailing 3-year ROIC), possibly a consequence of the same defect. It is not scored, so no bar moves.
- **Reported in the gate-2 result as a stated limitation,** with these counts. The inputs stay frozen. The repair belongs to `pit_data`,
  in fork 2's problem report, for the operator.

**AK.34 (2026-10-14 04:01): the masked control finished, the chain scored the registered version, and the coordinator's audit found
three defects in the outcome design. Nothing is reported to the operator as a result yet.**
- **The chain:**
  - the masked control finished at 01:31 (30 of 30);
  - the chain started at 01:46 and disabled `RS2-Gate2-Replay`;
  - the refresh downloaded companyfacts (Last-Modified 2026-10-13, 1,410,326,370 bytes, sha256 `c8335ac3…`) and built
    `store_2026-10-13` (20,455 of 20,455), finishing at 02:03;
  - `score --repeat-later` finished at 03:58: rc 0, 0 mismatches against the independent script, scoring date 2026-10-06;
  - the tag-consistent re-score started at 03:58.
- **The registered version's own negatives:** verdict FAIL (G1 and G4); 4 outcomes filed on or before T; R3a margin skill not shown;
  G4-strict 26 of 85.
- **Audit finding 1: the 4 look-ahead flags.**
  - All four are annual year-1 10-Ks filed **on** T (2026-02-27).
  - For CLOV, that 10-K's text was in the pack. It was accepted 13:08 ET, inside the registered 16:00 ET cutoff for documents, while the
    financial tables ended at FY2024 (strictly before T). So Muse could read the year its annual target measures.
  - The q1 target is not affected (q1 requires a filing strictly after T). These 4 annual rows are excluded from every annual result.
- **Audit finding 2 (serious): the q1 outcome was public in Muse's pack on 53 of 400 q1 rows (13%).**
  - On these rows the q1 quarter had ended before T, its XBRL report came after T, and its **8-K earnings release, filed before T, was
    in the pack**. Example: FormFactor's quarter ended 2025-09-27, its 10-Q came 2025-11-04, and its release of 2025-10-29 was shown.
  - By date: 2025-10-31 19/82, 2025-12-31 1/81, 2026-02-27 16/81, 2026-04-30 17/78, 2026-06-30 0/78.
  - The registration allows a quarter that ended before T as q1, and the packs include earnings releases by design. Together they let
    Muse read the outcome that G1 scores it on, while the code and the baselines cannot.
  - Any Muse advantage on G1 or R3a may therefore be partly reading, not forecasting.
  - **A sensitivity is running, not a registered bar:**
    - S1 removes those 53 rows;
    - S2 removes every row whose q1 quarter had ended at T.
    Which reading governs is the operator's decision, put to them with both results.
- **Audit finding 3: five stale q1 picks.** The rule "the earliest quarter first reported after T" chose quarters that ended 217–731 days
  before T and first appeared in a later filing (LHX, JJSF, NABL twice, SYBT). These are not the next quarter; S2 removes them.
- **Also for the annual target (S5's primary, and gate 2b):** 15 of the 2026-02-27 annual rows had a Q4/full-year earnings release for
  year 1 in the pack before T, so the year's result was public. Before B4, the annual target must be redefined as the first fiscal
  year whose results were **not** public at T, counting earnings releases as public. Gate 2b's dates need the same rule. Recorded for the
  S5/gate-2b amendment, to be written before any gate-2b outcome exists.

**AK.35 (2026-10-14 04:11): gate 2 scored and audited. The version of record is the tag-consistent outcomes (AK.30); the 20-outcome hand
check is still to do.**
- **A coordinator bug found and fixed before reading the version of record.**
  - The cause: `tag_consistent.quarter_tc` returned early when a quarter had no same-filing revenue pair, so banks (which have no revenue
    line) lost their ROTE outcome (60 rows), although ROTE needs only net income.
  - The fix: each measure now stands on its own pair.
  - The re-run is `scratch/rev23/gate2_audit/tag_consistent/2026-10-06_v2/` (394 q1 rows with a same-filing outcome, against 337). The
    first run is kept as the record of the bug.
  - The pseudo-outcome rehearsal (AK.32) had not exercised it, because its registered ROTE was empty.
- **The version of record** (tag-consistent v2; 0 mismatches against the independent script):

  | Bar | Kind | Result |
  |---|---|---|
  | G1 growth | hard | **Muse beats the code**: median d −0.0230, upper90 −0.0172, n 281 |
  | G1 margin | hard | **fails**: median d +0.0015, upper90 +0.0026, n 391 |
  | G1 overall | hard | FAIL, on margin |
  | G2 | hard (direction) | passes on direction: dIC +0.011, interval [−0.031, +0.056], n 386, same under all three bounds |
  | G4 | hard | FAIL: 18 of 85 revisions (21%), none accepted |
  | G5 | hard | passes: 0 leakage, 0 of 7,897 citations failed |
  | G3 (reported) | coverage | growth Muse 0.943, code 0.897 (both too wide); margin Muse 0.708, code 0.752 |
  | G6 (reported) | name bias | 7.0 percentile points of mean shift over 81 inputs of 17 company-dates |

  **Registered verdict: FAIL** (G1 on margin, and G4).
- **The diagnostics that decide the branch (AD.5):**
  - **R3a growth:** filing skill shown. Pass 1 beats the code, `persist_rr` and `popmed_rr` (medians −0.023, −0.008, −0.021).
  - **R3a margin:** not shown.
  - **R3b:** final against pass 1 has a median of 0.0 on both measures. The red team does not beat pass 1, so it is **not kept**, and
    G4's anchoring behaviour leaves the live system with it.
  - **R8** is deferred (AK.25). The repeat control started at 04:04.
- **The leak sensitivity (AK.34), on the version of record, through the full stages; 0 mismatches each:**
  - **S1**, without the 53 rows whose q1 earnings release was in the pack: growth d −0.0235 (upper90 −0.0173, n 267), and R3a growth
    still shows skill.
  - **S2**, without every row whose q1 quarter had ended at T (137 rows): growth d −0.0221 (upper90 −0.0167, n 192), and R3a growth
    still shows skill.
  - Margin fails in both.
  - **So the growth skill is not an artefact of Muse reading earnings releases.**
- **By the registered rule the branch is C1** (pass 1 beats all three baselines on growth). Next, per AD.5:
  1. engine v2;
  2. Muse's deviations shrunk and calibrated under S5 (growth only, unless the S5 fit finds margin value);
  3. gate 2b on its untouched dates.

  Before B4, the annual-target redefinition (AK.34) and the same-filing outcome (AK.27) go into outcome_extract.
- **Still to do before the result is final:** the 20-outcome hand check against the SEC filings (Audit 1), and R8 when the repeat control
  ends.

**AL.13 (2026-10-14 04:12): REGISTRATION of a measurement. Engine v2's growth outcomes, first-filed against same-filing (tag-consistent). Fixed before
any number exists; it measures only and changes nothing.** The basis is fork 1's AK.31 (recasts: TDS, Dollar Tree) and AL.7 (tag seams).
The operator ruled for gate 2 that "tag-consistent governs" (AK.27–AK.30).
1. **Rows.** Every growth residual row of the per-vintage panels (`panel_cut<V>.pkl`, 2017–2024, and 2025 once built): operating
   revenue growth for k = 1–3. Tangible-book growth is not rebuilt, because it rests on equity instants, not on a revenue seam; the same
   choice gate 2 made.
2. **The two definitions.**
   - **First-filed** (the current SPEC section 3 definition): `rev_k / rev_(k−1) − 1`, each year as first filed in its own report.
   - **Tag-consistent:** the same growth taken inside **year k's own 10-K**, from its comparative column for year k−1. Revenue is the
     largest current-period value among the ladder tags present for both periods, within one unit, USD when present.

   These rules match fork 1's `tag_consistent.py` (`annual_tc`: same ladder, same largest-tag rule, the same one-unit rule,
   AK.28–AK.29), so gate 2 and engine v2 measure outcomes the same way. The facts are raw store facts at vintage V's cut, from the store
   that built priors_v3 (fingerprint `7de131bd…`).
3. **What is reported,** by vintage, k and cell:
   - (a) the share of rows with |difference| > 1, 5 and 20 points, and rows with no same-filing pair;
   - (b) the cause of each row over 1 point:
     - **tag seam:** the extractor's revenue tags for years k−1 and k differ;
     - **recast:** the same tag, but year k's comparative for k−1 differs from k−1's first-filed value by more than 0.5%;
     - **other;**

     each reported separately (fork 1's suggestion);
   - (c) the residual pools and cells rebuilt with the tag-consistent outcome, into a scratch directory, never a data directory, with
     the quantile shift reported;
   - (d) E3 and E4 re-run on them.
4. **No bars.** It is a measurement. Adoption would amend SPEC_engine_v2 section 3's outcome definition and rebuild all ten tables as a
   new version; that is the operator's decision, with these numbers.
5. **Agreement (Q4):** on a seeded sample of 300 rows (seed 20261014), the tag-consistent growth must equal `tag_consistent.annual_tc`'s
   revenue growth to 1e−9 wherever both exist. Any disagreement is resolved before (a)–(d) are reported.
6. **When:** in the CPU window after the repeat control, at low priority, with commit headroom of at least 8 GB.

**AL.14 (2026-10-14 04:16): F1 built, the diagnostics-only tag-seam flag (AL.8 item 1), after fork 1's `chain/DONE` (04:03) lifted the scoring hold.**
- **The flag:** `pit_data.fiscal_years` stamps `TAG_SEAM` on a cell whose tag differs from the same field's tag in the adjacent
  prior fiscal year. Adjacent means period ends 350–380 days apart. Derived cells are skipped.
- **What it does not do:** it changes no value. It only appends a flag, through the same `_replace` as `RESTATED`.
- **Consumers:** no existing consumer reads it. Cell flags are read only for `RESTATED` (`company_pit` provenance) and through notes for
  `from_amendment`; `FiscalYear.provenance()` has no caller.
- **The per-year provenance** asked for in AL.8 is the cell's existing tag, accession, filing date and form, plus this flag. The extractor's
  primary-versus-backfill label is not exposed, a stated gap.
- **Commit:** rs2-local `review-2026-10/gate2-run2` 68d0f9b, pushed after a clean scan.
- **Tests:** one new test (the ASC 606 fixture: first-filed FY2020 is stamped; as known, nothing is stamped; values unchanged). Suite:
  743 passed.
- **Real-data check,** on AL.7's seeded sample (300 companies, cut 2026-01-01): 121 revenue cells flagged. That equals the tag changes
  between adjacent years (121 of AL.7's 123; the other 2 span a gap year), with 0 mismatches.
- **Not built:** the fiscal-year mislabel fix, which awaits the operator's ruling.
- **Not changed:** the frozen run-2 worktree (`a5fd342`), which the repeat control runs from.

**AK.36 (2026-10-14 11:48): the hand check passes 20 of 20; the repeat control lost about 5 hours to a GPU-sharing app.**
- **The hand check** (Audit 1, the version of record's 20 seeded q1 outcomes): `scratch/rev23/gate2_audit/hand_check.py` and
  `hand_check_q4.py`. The filing documents themselves were downloaded from SEC under the standing approval: 24 files, 107,433,512 bytes,
  each sha256 in `data/sec_bulk/handcheck_2026-10-14/manifest.json`.
  - **Directly in the filing, 18 outcomes:** every scored value (revenue, operating income, and net income for the financials, both the
    quarter and the year-earlier quarter) appears in the primary document's text. Growth recomputed from those values equals the scored
    growth exactly wherever revenue exists. The banks (ISTR, FMAO) are checked on net income, which their ROTE uses.
  - **The two derived fourth quarters** (UHS revenue; GS net income) appear in no filing, since they are full year minus nine months.
    Both legs were checked: the fiscal-year pair in the 10-K and the nine-month pair in the third-quarter 10-Q, all four values found in
    each case. UHS's Q4 growth from the filed figures is +9.0508%, the scored value.
  - **Result: 20 of 20.**
- **Audit 1 is complete:** look-ahead (the 4 same-day annual rows excluded), coverage, the independent recomputation (0 mismatches),
  and the hand check. Only R8 is still open.
- **The repeat control and the PC restart.**
  - The PC restarted at 06:18. The repeat task resumed at 06:19 and completed company 18 of 30 at 06:30.
  - It then stopped its server and waited, because the ChatGPT/Codex desktop app (`ChatGPT.exe`) showed up as a GPU compute process
    holding 13 MiB. The runner pauses for any GPU compute process (memory `gpu-shared-with-gaming`).
  - It resumed at 11:47, after the app closed, and had reached 19 of 30 at 11:47.
  - Answers are unaffected. The finish moves to the early afternoon.

**AL.15 (2026-10-14 11:48): two amendments to AL.13, made after a 25-company dry test (vintage 2020, scratchpad only) and before the full measurement.**
- **Context: the restart.** The PC restarted at 06:18. The repeat control resumed by itself.
  - At 06:30 its GPU guard stopped the server because the ChatGPT desktop app held the GPU.
  - It waited until 11:43, then restarted its own server. It is at 18 of 30.
  - My CPU window still follows it.
- **Amendment 1: a fourth cause class, `partial_line`.** AL.13's classes could not tell a company's own recast from the extractor
  taking a sub-line.
  - **Example:** Apogee (CIK 6845) files `Revenues` of 72.7M, 79.5M, 76.2M and 49.1M for FY2015–2018, against a total of about
    1.4B. First-filed growth reads +2,757% and −92%; tag-consistent reads +5.8% and +19%. AL.13 had called it "recast".
  - **The class:** checked after `tag_seam` and before `recast`. It applies when a first-filed cell is more than 0.5% below the
    largest annual ladder value that its own filing reports for that period, in its unit.
  - **What it changes:** classification only. There are no bars, and the measured differences are unchanged.
- **Amendment 2: the Q4 check is replaced.** The script calls `tag_consistent.annual_tc` itself, so AL.13 item 5's agreement test would
  be identity, not an independent check. Instead, the 10 largest gaps in the full run are checked by hand against the filed income
  statements, as in AL.9, before anything is reported.
- **What the dry test also showed:** 3 of 211 rows whose panel g_k is not reproduced by `pit_data` at the cut. They are reported as a
  count (`first_filed_reproduced`).
- **The script:** `scratch/rev23/engine_v2_audit/tc_outcomes.py`. It writes `tc_<V>.json`, `tc_rows_<V>.pkl` and `panel_tc<V>.pkl`
  (the panel with tag-consistent growth), all outside any data directory.

**AL.16 (2026-10-14 11:50): engine v2's CPU window is scheduled to run unattended after the repeat control (memory: long runs outside Claude).**
- **The task:** `RS2-EngineV2-CPU` (`scratch/rev23/engine_v2_audit/chain/`: `ev2_cpu_chain.py`, `launch_ev2.vbs`,
  `register_ev2_task.ps1`). It runs every 15 minutes and at logon.
- **The guard.** Each run exits at once unless all of these hold:
  - the repeat control is final (`score_day.control_final`; tested: repeat False, masked True);
  - no llama-server is running;
  - commit headroom is at least 8 GB;
  - there is no `HOLD` file in the chain folder. Fork 1 or the operator can create one to keep the CPU free.
- **The steps,** each skipped when its output exists. Every script writes once, so a restart resumes:
  1. the pass at origin 2025-06-30 (AL.6) into `forecast_study/pass_v2025`;
  2. vintage 2025's panel on its own obs (`panel_cut2025_o2025.pkl`);
  3. `data/priors_v4_pit/2025` (AL.10);
  4. AL.13's measurement for 2017–2025, into `engine_v2_audit/tc/`.

  A failed step writes `FAILED_<step>` and stops the chain. Everything runs at below-normal priority. Nothing is reported before my audit
  (Q4).
- **Inputs copied, never moved:**
  - the 9 study pass files into `forecast_study/pass_v2025` (sha256 equal);
  - the study's code into `engine_v2_audit/studypkg/fs`, from branch `review-2026-10/forecast-study` and byte-equal to the copy used
    in AL.6.
- **Still manual, after DONE:**
  - E6 for 2025;
  - E5 on the point-in-time tables;
  - AL.13 (c) and (d), the residual tables and E3/E4 on the tag-consistent panels;
  - AL.15's hand check of the 10 largest gaps.

**AK.37 (2026-10-14 11:51): PROPOSED for the operator's approval: the outcome amendment for gate 2b and S5's fit, written before any
gate-2b data exists and before S5 is fitted.** It carries gate 2's three audit findings into the designs that come next, so they are
fixed by rule and not discovered again.

1. **Measurement (both targets):** growth and margin change are taken from **one filing's own comparative columns**, by the AK.27–AK.29
   rules as implemented in `tag_consistent.py` and checked 20 of 20 against the filed documents (AK.36):
   - one accession, one tag and one unit;
   - among several revenue tags, the largest current-period value;
   - a derived Q4 only when one tag spans the 10-K and the Q3 10-Q, with no recast in between.

   This replaces "first-filed" for those two measures, because first-filed comparisons mix bases across recasts and tag seams (AK.31,
   AL.13–AL.15).
   - **The annual ROTE change keeps the registered definition** (`build_state`'s ROTE = net income ÷ average tangible equity). Its
     denominator is balance-sheet instants. Its numerator, total net income, is not moved by a discontinued-operations recast.
   - **A net-income tag-consistency check is reported beside it:** year-1 net income against the base year as given in the year-1 10-K's
     comparative column.
2. **Annual-target eligibility.** A company-date is excluded from the annual target, and listed, when year 1's full-year results were
   public before T: the 10-K, or an 8-K earnings release for year 1's final quarter or full year, filed before T (AK.34; 4 + 15 rows on
   gate 2).
   - Its year 1 is not a forecast.
   - On gate 2b's dates this mostly concerns non-calendar fiscal years.
   - It applies to gate 2b's B4 and to S5's annual fit on gate-2 data.
3. **q1 eligibility** (S5's q1 breadth check, gate 2b's early read). q1 is excluded, and listed, when:
   - an 8-K filed after the q1 quarter's end was in the pack before T (AK.34 rule S1: 53 of 400 on gate 2); or
   - the q1 quarter ended more than 120 days before T (the stale picks).
4. **Implementation:**
   - `outcome_extract` gains the same-filing functions, ported from `tag_consistent.py` with unit tests.
   - **An equivalence test:** on gate 2's 424 rows the ported code must reproduce `tag_consistent/2026-10-06_v2` exactly.
   - The eligibility rules read the pack manifest the runner already writes.
   - Built now, outside the frozen worktree, and used only after approval.
5. **What does not change:** gate 2's own result (AK.35: the tag-consistent version of record, with S1 and S2 reported); every bar,
   threshold, date and seed of gate 2b and S5.

**AL.17 (2026-10-14 11:58): the operator's approvals ("ok"), and what held the GPU for five hours this morning.**
- **Approved:**
  1. Engine v2 freezes on the point-in-time tables, `data/priors_v4_pit` (AL.10–AL.12), with vintage 2025 added when the chain builds it.
     The AL.3 tables (`data/priors_v4`) are kept for comparison and are not used.
  2. The fiscal-year mislabel fix (`PROBLEM_REPORT_fiscal_year_mislabel.md` sections 6–7).
- **One correction before building, my own.** Section 6 says "USD durations ending on or before the filing date". "USD" would remove the
  period of a report filed only in another currency (a 20-F in EUR), so it is dropped. The rule built is:
  - durations of 350–380 days, **in any unit**, that end **on or before the accession's filing date**;
  - otherwise the latest instant on or before the filing date.

  `dei:DocumentPeriodEndDate` would be better, but the store does not keep it: it keeps only the cover-page share count. Using it would need
  a store rebuild, so it is noted as a later improvement.
- **Where it is built:** on its own branch, because the running CPU chain (AL.16) measures with the current `pit_data`. It joins the dev
  branch after that chain's DONE.
- **Validation,** as section 6 says:
  - the mislabelled rows re-counted;
  - Boeing and 20 others checked against the "Period of Report" on the SEC filing index;
  - a test that a forward-dated fact cannot set a period;
  - the per-vintage diff of the observation and priors tables, rebuilt as a **new version** (`priors_v3_fy`; the frozen inputs are kept).

  The rebuild is CPU-heavy, so it follows the chain.
- **The GPU stall, 06:30–11:43.**
  - **06:19:** at logon, Windows registered a pending update of the OpenAI Codex/ChatGPT desktop app (26.924 → 26.1007; AppX deployment
    log).
  - **06:22:02:** the app's own Windows startup task (`windows.startupTask`, enabled, State 2) launched it.
  - **06:30:** its GPU renderer (ChatGPT.exe, about 13 MiB of VRAM) was seen by the repeat runner's guard, which treats any other GPU
    process as a game. The runner unloaded the model and waited.
  - **11:42:44:** the app's container was destroyed (the app closed). One minute later the runner resumed.
  - **What it was not:** there is no evidence the app did any work; the logs show only an automatic launch at login. Its background
    service (`codex-windows-sandbox-service`) still runs, without the GPU.
  - **The operator** can switch off its startup in Windows Settings > Apps > Startup.
  - **For fork 1 (the runner is frozen, so no change now):** the guard counts a 13 MiB renderer as a game. A floor on VRAM or utilisation
    would have saved five hours. Recorded for the runner's next version.

**AL.18 (2026-10-14 12:03): the fiscal-year mislabel fix is built and validated on its own branch. The rebuild of everything downstream is still to do.**
- **The code:** rs2-local `review-2026-10/pit-fy-fix` 8155188, pushed after a clean scan, worktree `scratch/rev23/wt-fyfix`.
  - `CompanyPit.accessions()` takes an accession's period from its 350–380-day durations (any unit) that end on or before its filing
    date; otherwise from its latest instant on or before that date.
  - An accession whose forward-dated facts were ignored is marked `forward_dated_facts_ignored`.
- **Tests:**
  - **New:** a Boeing-shaped fixture with a 2018 tax-rate fact inside the FY2017 10-K. On the old code it reproduces the defect: at
    2018-06-30 the years are `['2016-12-31']`, and FY2018 is stamped 2018-02-12. On the fix, FY2017 exists and FY2018 is stamped with
    its own filing.
  - **Suite:** 744 passed.
- **Real data,** dumping the fiscal-year index with the old and the new code (`scratch/rev23/engine_v2_audit/fyfix/`):

  | Sample | Companies | Mislabelled index entries | Fiscal years | Companies changed | Other effects |
  |---|---|---|---|---|---|
  | Every company with a mislabelled observation row in vintage 2025 | 362 | 529 → **0** | 3,808 → 4,223 (+447, −32) | 362 | – |
  | Seeded random companies, the rest of the universe | 500 | 10 → 0 | 3,402 → 3,403 | 7 | All 7 traced to an old mislabel |

  - Every changed company had an old mislabel.
  - Every lost label was a mislabelled one, 32 + 10.
  - Three entries that were not mislabelled now take an **earlier** own filing. Example: PPG FY2017 now comes from its 10-K of 2018-02-15,
    not a 10-K/A of 2018-06-28, because the original 10-K had been relabelled away. That is also a correction.
- **Against SEC's "Period of Report"** on the filing index page: Boeing 0000012927-18-000007 plus 20 seeded relabelled accessions, of 526
  moved. **21 of 21 match the new fiscal year end** (`cover_check.json`; sec.gov under O5).
- **Next, CPU-heavy, after the AL.16 chain's DONE:**
  1. merge the fix into the dev branch;
  2. rebuild the observation tables of every vintage into a new version, `data/priors_v3_fy`, then the priors tables, the per-vintage
     panels and the near-term tables;
  3. the per-vintage diff against the legacy versions;
  4. E3/E4 and E6.

  The frozen gate-2 inputs (`c7d7a4f`, priors_v3) stay as they are. Which version gate 2b's SYSTEM freeze uses is the operator's call,
  with the diff. A cascade plan follows in its own entry before it runs.

**AK.38 (2026-10-14 12:10): the AK.37 code is built and checked. It is not wired in until the operator approves AK.37 and fork 2's
fiscal-year fix is merged.**
- **The module:** `rebuild_harness/gate2/same_filing.py`, ported from the audit's `tag_consistent.py`, with the AK.37 eligibility
  rules (rs2-local `review-2026-10/gate2-run2` `22f22b0`, pushed after a scan).
  - **Tests:** 8 unit tests on synthetic cases: a recast (Dollar Tree shape), several tags with a side line and a convenience currency,
    a derived Q4 with and without a recast in between, a bank with no revenue line, the annual comparative, and both eligibility rules.
    The tag ladders are checked equal to `pit_data.quarter_fields()`.
  - **Suite:** 751 passed.
  - **The eligibility rule keys on earnings releases:** every 8-K in the gate-2 packs is `kind: earnings_release` (422 of 422), and so
    are all 53 S1 flags.
- **The equivalence test against gate 2's version of record** (`tag_consistent/2026-10-06_v2`): 2,511 measures compared.
  - **Every quarterly measure is identical,** including the q1 hard-bar measures.
  - **19 annual measures differ.** All are 20-F filers (WDH, HTHT, FUTU, ZTO and others): the audit script's annual step accepted only
    10-Ks, so it found no annual outcome for them, while the port accepts 10-K, 20-F and 40-F, as `annual_outcomes` does.
  - **A coordinator defect in the audit script, now recorded:** gate 2's reported annual diagnostics (R3a_annual, AK.35) left out
    about 10 foreign filers. The hard bars and the branch rule read q1 and are unaffected. The ported module is the correct one, and S5
    and gate 2b will use it.
- **The pit_data version:** the same-filing measures read raw facts only, so fork 2's fiscal-year fix does not change them. The choice
  of year 1 (`annual_outcomes` through `company_pit`) does, so gate 2b uses the post-fix `pit_data` (agreed with fork 2), and nothing
  that reads `pit_data` is frozen before that merge.
- **Agreed for the gate-2b runner** (a new freeze in any case): the GPU guard ignores a compute process under 500 MiB of VRAM and 5%
  utilisation, logged. This is AL.17's lesson from the ChatGPT app's 5-hour stall.

**AK.39 (2026-10-14 12:18): rulings on the outside review of AK.37, with the measurements it asked for. AK.37 becomes v2, for the operator's
approval.**

*Accepted, measured first:*
1. **Same-filing does not by itself prove the line is total revenue** (the problem report's failure mode (b)). The coordinator's AK.36
   claim is corrected: the hand check confirmed that each scored figure appears in the company's filing, not that it is the total-revenue
   line.
   - **Measured now:** `scratch/rev23/gate2_audit/revenue_scope_check.py` tests each of the 337 q1 revenue figures of the version of
     record, on the raw companyfacts.
     - **Verified by dominance, 51:** the largest of two or more revenue tags in the filing.
     - **Verified by closure, 201:** within 1% in the same filing and unit, both periods: either gross profit plus cost of revenue equals
       revenue, or revenue minus total costs and expenses equals operating income. A derived Q4 is tested on its 10-K's annual pair.
     - **Closure fails, 1:** NUTX, revenue minus costs is not equal to operating income.
     - **No test available, 84.**
   - **The rule for gate 2b and S5:**
     - a closure failure **abstains**, and is listed;
     - an untestable figure is scored but flagged, and every bar is also reported on the verified rows only.
2. **Exclusion registers and denominators.** Every exclusion records the company, T, the target period, the metric(s), the public
   source with its acceptance timestamp, and the reason. Both the original and the eligible sample sizes are reported.
   - **The period-level rule is kept, not made per-metric.** When a release made the year (or quarter) public, all its metrics leave
     the target. That is stricter than per-metric, because the releases carry full income statements, and parsing each release for
     each metric would add judgement without a gain.
   - The rule is applied identically to both arms, because eligibility is a property of the company-date.
3. **Public, not just in the pack.** A result counts as public when SEC's own filing index shows an 8-K with Item 2.02 (results of
   operations) accepted after the period's end and before the T cutoff, whether or not the pack held it.
   - **Measured on gate 2 (submissions snapshot of 2026-10-07):** 56 q1 rows were public that way. 53 were in the pack, and 3 were not
     (TRST, UFPI, APO).
   - The pack rule stays as well, as the second route.
4. **The benchmark, defined.** q1 is **the next quarterly result not yet public at T**. It may be a quarter that has already ended but is
   unreported, which is a nowcast of an unreleased result. It is never a released one.
   - **The 120-day rule** is a separate guard against a known artefact: a quarter that first appears in XBRL long after it ended (LHX,
     JJSF, NABL, SYBT). It is not part of the benchmark's definition.
5. **What gate 2's record holds** (labels made exact):
   - **The registered extractor score is kept as the historical record.**
   - **The tag-consistent score is the version of record** by the operator's ruling of 2026-10-13 23:23 (AK.30). That ruling came
     before any score existed: the scoring ran 02:03–03:58 on 10-14. So it is a measurement rule fixed before outcomes were read.
   - **S1, S2 and the scope-verified sets are post-audit sensitivities.** They were defined after the registered score's negatives line
     had been seen, and they are labelled that way everywhere.
   - **The overall gate-2 verdict is FAIL** (G1 on margin, and G4) in every version.

*The reporting table the review asked for.* G1, q1, measured as the paired difference in absolute error, |Muse − outcome| − |code −
outcome|. The interval is the 10th–90th percentile of 2,000 company-clustered bootstrap medians (whole companies resampled), and the
registered bar reads its upper end. File: `g1_reporting_table.json`.

| Version | Measure | n | Companies | Median d | 10%–90% | Mean abs. error, Muse / code |
|---|---|---|---|---|---|---|
| registered (historical record) | growth | 283 | 245 | −0.0211 | −0.0267 to −0.0164 | 0.099 / 0.129 |
| tag-consistent (version of record) | growth | 281 | 243 | −0.0230 | −0.0270 to −0.0172 | 0.076 / 0.108 |
| tag-consistent | margin | 391 | 338 | +0.0015 | +0.0004 to +0.0025 | 0.150 / 0.147 |
| S1, no release in the pack (sensitivity) | growth | 267 | 232 | −0.0235 | −0.0273 to −0.0173 | 0.078 / 0.111 |
| S2, no quarter ended at T (sensitivity) | growth | 192 | 175 | −0.0221 | −0.0283 to −0.0167 | 0.084 / 0.117 |
| scope-verified revenue (sensitivity) | growth | 231 | 203 | −0.0232 | −0.0281 to −0.0155 | 0.083 / 0.114 |
| scope-verified and S1 (sensitivity) | growth | 219 | 193 | −0.0238 | −0.0283 to −0.0167 | 0.085 / 0.118 |

Muse's advantage on next-quarter revenue growth is about 2.1–2.4 points of median absolute error in every version, with the whole
company-clustered interval below zero. Its margin disadvantage is about 0.15 points, again with the whole interval above zero.

*AK.37 v2, for the operator:* AK.37 items 1–5, plus:
- the total-revenue verification and the abstention on a closure failure (1 above);
- the exclusion register and the denominators (2);
- SEC Item 2.02 public availability (3);
- the benchmark definition and the 120-day guard's role (4).

The code (`same_filing.py`) gains the closure test and the Item 2.02 check before it is wired in.

**AK.40 (2026-10-14 13:27): the repeat control finished; R8 is computed. Gate 2's runs are complete.**
- **The repeat control:** 30 of 30 at 13:25 (the GPU stall of 06:30–11:47 is in AK.36).
- **R8** (`score_day r8`, written once beside the score: `data/gate2_run2/scoring/2026-10-06/r8.json`; it reads no outcome):
  - 24 company-dates and 114 placed inputs compared between run 2 and the second-seed run;
  - median absolute shift **4.0 percentile points**, mean 6.4, with 18% identical.
  - **By AD R8, multi-sampling is not required** (the median is not above 10).
  - **For S5's own k rule** (S5 section 5: the standard error of a position at most 5 points; it is decided per input in B4, not
    here), an indication only: under independent runs a mean absolute difference of 6.4 implies a per-run σ of about 6.4 × √π / 2 ≈ 5.7
    points. So k = 2 would meet 5 points on the pooled figure. B4 measures it per input.
- **Housekeeping:** `RS2-Gate2-Repeat`, `RS2-Gate2-PostMasked` and `RS2-Gate2-MilestoneReview` are disabled (not deleted); their work is
  final. The GPU is free, so fork 2's `RS2-EngineV2-CPU` chain now starts on its own conditions (AL.16).
- **Gate 2, complete:**
  - **Version of record:** tag-consistent (AK.30).
  - **Verdict:** FAIL, on G1 margin and G4.
  - **Branch:** C1 on growth (AK.35, AK.39 table). The red team is dropped (R3b); multi-sampling is not required by R8.
  - **Audit 1:** passed, with the hand check (AK.36) and the scope check (AK.39).
  - **Open for the operator:** AK.37 v2 (the outcome amendment for gate 2b and S5).

**AL.19 (2026-10-14 13:48): the CPU chain finished. Vintage 2025 is built; the outcome measurement ran; the hand check found a defect in the shared
tag-consistent rule; the fiscal-year fix is merged.**
- **The chain** (AL.16) started at 13:27, after the repeat control was final at 13:25 (AK.39), and wrote DONE at 13:44.
  - **Pass at origin 2025-06-30:** 1,758 companies (operating 1,383, financial 375). 0 errors; 1,635 have a code forecast. Every row
    uses the **vintage-2024** priors, which is point in time.
  - **Vintage-2025 panel** (`panel_cut2025_o2025.pkl`, its own obs, CUT 2025-12-31): 15,060 rows, 99.2% matched, no obs row dropped.
    - The 2025 origin adds 1,751 rows; 227 have a year-1 outcome filed before the cut.
    - The 13,309 older rows are identical to AL.6's panel (g_1 and m_1).
  - **`data/priors_v4_pit/2025`:** loads through `load_table` (sha256, version, cut 2026-01-01). It is labelled `per_vintage` and
    `legacy`. The medians' latest filing is 2025-12-31.
- **E6 for 2025:** holds by construction (AL.12): the panel's `assert_cut`, its own obs, and nothing filed on or after 2026-01-01.
  **E6 is now complete for 2016–2025.**
- **AL.13 measurement, (a) and (b).** Operating revenue growth, first-filed against tag-consistent (`engine_v2_audit/tc/`).
  - **Vintage 2025:** 26,182 rows; 24,598 with a same-filing pair; 1,541 have no pair; 43 years not found. First-filed is reproduced
    from `pit_data` in 25,972 rows.
  - **Gaps:** larger than 1 point in 1,316 rows (5.4%), larger than 5 points in 963 (3.9%), larger than 20 points in 475 (1.9%).
  - **Causes of the gaps over 5 points:** recast 691 (72%), tag seam 151 (16%), partial line 62 (6%), other 59 (6%).
  - **Earlier vintages,** share of rows over 5 points: 2017 3.7%, 2019 5.2%, 2021 4.5%, 2023 4.1%. Recasts are the largest cause in
    every vintage.
  - **Correction to AL.7 / the problem report:** in the $300M+ panel the gaps are about eight times AL.7's all-pairs estimate (0.47%
    over 5 points), because recasts, which AL.7 did not measure, dominate.
- **The hand check, AL.15 amendment 2.** The 10 largest distinct gaps of vintage 2025, against the income statement filed in year t's
  own 10-K (sec.gov, O5):
  - **8 of 10: tag-consistent matches the filed total and first-filed is wrong.**
    - CIK 1164863: net sales 1,187.7 → 1,309.6, +10.3%; first-filed +327,300%.
    - CIK 1404912: total revenues 3,557,280 → 2,395,836 K, −32.6%; first-filed +3,675% from an `OilAndGasRevenue` tag.
    - Caleres (14707) +3.1%.
    - Apogee (6845) +5.8%.
    - CIK 835011, two cases: −3.5% and +8.2%.
    - CIK 1289308, two cases: +10.0% and +8.8%.
  - **2 of 10: first-filed is right and tag-consistent is wrong.** CIK 1831915: filed totals 127,950 → 164,036 → 193,015 K, +28.2% and
    +17.7%; tag-consistent gives +7,421% and +6,414%.
    - **The cause:** in its FY2023 10-K, `Revenues` and the contract-revenue tag both equal 193,015,000 for 2023. For 2022 and 2021,
      `Revenues` is a 2–3M sub-line.
    - **The defect:** `tag_consistent.choose` breaks the tie by ladder order and takes `Revenues`. This is a defect in the shared
      rule (AK.28), so it also reaches gate 2's version of record wherever such a tie occurs.
    - **Sent to fork 1** with a fix: sort by (−current, −prior, ladder), since a total is never smaller than a line within it in
      either period. Its `disagree_over_1pt` note already marks the affected rows.
  - **(a) and (b) are therefore provisional** until fork 1's fix lands. The tc step is then re-run on the fixed function, so gate 2 and
    engine v2 keep one rule. (c) and (d), the tables and E3/E4 on the tag-consistent outcome, wait for that re-run.
- **The fiscal-year fix is merged:** `review-2026-10/gate2-run2` 688281f, a merge of 8155188 on top of fork 1's 22f22b0; suite 752
  passed; pushed after a scan; fork 1 told, for the gate-2b equivalence test.
- **Next:** the priors cascade on the fixed `pit_data` (`priors_v3_fy`), and E5, the oracle. Both are CPU-heavy, and each gets its own
  plan entry before it runs.

**AK.41 (2026-10-14 13:49): a defect in the revenue-tag rule, found by fork 2's hand check (AL.15). Fixed; gate 2's bars are
unaffected.**
- **The defect:** `choose()` took the largest current-period value and broke ties by ladder order. In CIK 1831915's FY2023 10-K
  (0001628280-24-010933), `Revenues` and the contract tag are both 193,015,000 for 2023, but `Revenues` is a 2,963,000 sub-line for 2022.
  The tie went to `Revenues`, giving +6,414% where the filed totals give +17.7% (and +7,421% against +28.2% a year earlier).
- **The fix, by AK.28's own reasoning** (a total is never smaller than a line within it, in either period): among tags within 0.5% of the
  largest current value, the largest prior wins, then the ladder.
  - **Where:** `same_filing.choose` (rs2-local `review-2026-10/gate2-run2` `eb98533`, on top of fork 2's fiscal-year merge `688281f`),
    with a unit test of the 1831915 shape; and the audit's `tag_consistent.py`.
  - **Suite:** 753 passed.
- **The effect on gate 2's version of record, measured:** the fixed rule against `tag_consistent/2026-10-06_v2` over every q1, q2 and
  annual measure.
  - **One company changes:** NBHC (a bank), q1 revenue growth 4.94% to 4.83%, q2 7.78% to 7.41%.
  - Banks are outside G1's growth bar (operating family only), so **no bar, interval or branch moves**. Recorded; not re-scored.
- **Also aligned:** `tag_consistent.py`'s annual step now accepts 20-F and 40-F, as `same_filing` does (AK.38).
- **Fork 2's merge:** the fiscal-year fix is in `688281f`. The same-filing measures read raw facts and are unaffected. The choice of year 1
  for gate 2b goes through `company_pit` and so uses the fixed version, as agreed.

**AL.20 (2026-10-14 13:51): REGISTRATION of the priors cascade on the fixed `pit_data` (AL.17's "a repair rebuilds the priors as a new version").
Fixed before any number exists. Nothing existing is overwritten; every output goes to a new folder.**
- **The code.**
  - **Fixed:** `review-2026-10/gate2-run2` at eb98533 or later, which carries the FY fix (688281f) and fork 1's AK.41.
  - **Legacy reference:** a detached worktree at 22f22b0, which has the TAG_SEAM flag and does not have the FY fix. TAG_SEAM changes no
    value.
  - **The pass:** run from the study's `pass_priors.py`, copied from `review-2026-10/forecast-study`, against the dev code. Between
    that branch and the dev code, the engines, `priors.py` and `priors_build` are identical; `pit_data` differs only by TAG_SEAM and
    the fix; `gate1_run` differs by AK.16's cache release.
- **Step 0, equivalence (it gates everything after it):**
  - **(a)** `build_vintage 2020` with the legacy code into a scratch folder must reproduce `data/priors_v3/2020/obs.csv.gz` byte for
    byte (its `obs_sha256`).
  - **(b)** The pass at 2019-06-30 with the legacy dev code must reproduce the stored study pass file row for row.

  If either fails, the cascade stops and the difference is diagnosed first.
- **Steps, with the fixed code, at below-normal priority, with no model loaded:**
  1. `build_vintage 2016..2025` into `data/priors_v3_fy` (`PRIORS_DATA_DIR`);
  2. `make_tables` for the same years;
  3. passes at 2017-06-30..2025-06-30 with `priors_v3_fy` into `forecast_study/pass_fy`;
  4. per-vintage panels on `priors_v3_fy` obs (`panel_fy<V>.pkl`);
  5. near-term tables into `data/priors_v4_fy`.
- **Shared inputs:** `data/priors/_inputs` (the mcap panel, the SIC map) is used as is. The mcap panel rests on cover shares and prices,
  not on the fiscal-year index; a spot check of 50 company-dates is reported.
- **Reported, negatives first. There are no bars; the operator chooses the version with these numbers:**
  - per vintage: observation rows gained and lost, and rows whose values changed;
  - the change in every priors-table cell median and quantile;
  - the near-term table diff against `priors_v4_pit`;
  - E3 and E4 on `priors_v4_fy`, and E6 by construction.
- **Unchanged:**
  - gate 2's frozen inputs (`c7d7a4f`, `priors_v3`);
  - the approved engine-v2 freeze on `priors_v4_pit`, until the operator rules on `priors_v4_fy`;
  - AL.13's outcome-definition question, which is decided separately.
- **How it runs:** as a scheduled chain like AL.16, with a HOLD file. The other session is told before it starts.

**AL.21 (2026-10-14 13:58): AL.20 step 0. (a) passes; (b) fails and is diagnosed; the cascade is re-specified before it runs.**
- **(a) passes.** `build_vintage 2020` with the legacy code reproduces `data/priors_v3/2020/obs.csv.gz` exactly, 33,903,374 bytes
  decompressed (sha256 `508e96b8…`), in 74 s with 6 workers.
  - **One amendment to AL.20:** the comparison is of the decompressed bytes. The gzip header carries a write timestamp, so the `.gz`
    hashes differ by construction.
- **(b) fails.** The pass at 2019-06-30 with the legacy dev code (22f22b0) gives 1,403 rows; the stored study pass has 1,405. 13 companies
  differ, in `ticker`, `mcap` and `price` only.
  - **The cause:** the study branch predates Addendum AD.10. AD.10 changed `gate1_run._best_ticker` from "the ticker with the largest
    market cap" to "the common stock, first in SEC's order". Under the old rule, a high-priced preferred or note could set the price and
    the cap (Bruker's BRKRP gave a "$48B" cap).
  - **The effect:** the study's passes, and so the AL.3, AL.10 and AL.19 near-term tables built on them, carry the pre-AD.10 ticker rule.
    At 2019 that is 13 of 1,405 companies, and 2 move across the $300M universe floor. A known and small limitation of `priors_v4_pit`,
    now recorded.
- **The cascade is re-specified,** before any of it runs:
  - **The code:** the current dev code, which carries both corrections: AD.10's ticker rule and the FY fix.
  - **The legacy reference for decomposing the diff:** the dev code without the FY fix (`wt-legacy`, 22f22b0).
  - **What is reported:**
    - the AD.10 effect, from the dev-legacy passes against the study's;
    - the FY effect, from the fixed run against dev-legacy;
    - the total.
  - **Steps:**
    1. obs into `priors_v3_fy` (fixed code);
    2. `make_tables` (fixed);
    3. passes at 2016-06-30..2025-06-30, twice. Once dev-legacy with `priors_v3` (`pass_devlegacy`), once fixed with `priors_v3_fy`
       (`pass_fy`; `cfg["priors_dir"]` is overridden, and the 2025 guard is lifted as in AL.6);
    4. panels `panel_fy<V>` on `priors_v3_fy` obs and `pass_fy`;
    5. near-term tables into `data/priors_v4_fy`;
    6. diffs, then E3/E4 (by hand).
  - **How it runs:** as a scheduled chain with a guard and HOLD, as AL.16.

**AL.22 (2026-10-14 14:03): AL.13 completed on the production rule. Recommendation: engine v2 keeps its first-filed residual tables.**
- **Re-run on `rebuild_harness.gate2.same_filing.annual_measures` at eb98533,** which carries fork 1's near-tie fix (AK.41) and accepts
  20-F and 40-F. Output in `engine_v2_audit/tc_sf/`; the provisional AL.19 run is kept in `tc/`.
  - The two CIK 1831915 cases now match the filed totals (+28.2%, +17.7%).
  - `pit_data` now carries the FY fix, so rows whose fiscal-year pair no longer matches the panel's are reported apart ("reproduced
    only").
- **Final numbers, vintage 2025** (operating revenue growth, k = 1–3):
  - 26,120 rows with a same-filing pair (of 26,182);
  - gaps larger than 5 points: 1,200 (4.6%); larger than 20 points: 505 (1.9%);
  - reproduced rows only: 1,147 of 25,983 (4.4%) over 5 points;
  - causes of gaps over 5 points: recast 907 (76%), tag seam 178 (15%), partial line 79 (7%), other 36 (3%).
  - By vintage, the share over 5 points runs from 4.4% to 6.4%. Recasts are the largest cause throughout.
- **(c) Tables built on the tag-consistent outcome,** a scratch build in `tc_sf/tables`, never a data directory: pools 2017–2025 are almost
  the same size as `priors_v4_pit`'s (2025 operating growth k1: 8,609 against 8,624).
- **(d) E3/E4, operating growth, with origins scored by each origin year's prior vintage:**

  | Tables | Scored against | Coverage k1 / k2 / k3 | Interval score k1 / k2 / k3 |
  |---|---|---|---|
  | `priors_v4_pit` (first-filed) | first-filed outcomes (AL.12) | 0.664 / 0.626 / 0.681 | 1.778 / 3.781 / 1.020 |
  | **`priors_v4_pit` (first-filed)** | **tag-consistent outcomes** | **0.677 / 0.635 / 0.690** | **1.580 / 3.705 / 1.002** |
  | tag-consistent tables | tag-consistent outcomes | 0.654 / 0.600 / 0.665 | 1.589 / 3.736 / 1.006 |

  On the outcome definition gate 2b scores (tag-consistent, AK.30), **the current tables are better on every k**: higher coverage and lower
  interval score. Training on the cleaner outcomes narrows the bands, and v2 already under-covers (E3). The first-filed noise widens the
  bands in the direction the calibration lacks. E3 FAILs and E4 PASSes (3 of 12) in every variant.
- **The recommendation, for the operator:**
  - Engine v2 keeps `priors_v4_pit` (first-filed residuals), as approved.
  - Gate 2b and S5 score on the tag-consistent outcome, as fork 1's AK.37 proposes.
  - No amendment to SPEC_engine_v2 section 3.

  The measured 4–5% of misstated growth outcomes stays a documented property of the residual tables. Its effect is to widen the bands,
  which on this evidence helps.

**AL.23 (2026-10-14 14:05): fork 1's question on AL.22. Does first-filed training buy coverage with a biased centre? Answer: the P50 accuracy is the
same.**
- **The check:** `engine_v2_audit/p50_check.py` (`p50_check.json`). On tag-consistent outcomes, operating revenue growth, the P50 as v2
  draws it (centre plus the cell's median bias, in log space). Both table versions use AL.22's scoring rule.

  | k | n | P50 MAE, first-filed / tag-consistent | Median absolute error | Median error |
  |---|---|---|---|---|
  | 1 | 6,600 | 0.21677 / 0.21674 | 0.0903 / 0.0904 | −0.0009 / −0.0037 |
  | 2 | 4,472 | 0.4336 / 0.4342 | 0.1004 / 0.1008 | +0.0138 / +0.0123 |
  | 3 | 2,332 | 0.1535 / 0.1532 | 0.0816 / 0.0811 | +0.0231 / +0.0210 |

  The paired difference in absolute error (first-filed minus tag-consistent) is +0.00003, −0.00061 and +0.00036.
- **The median bias by cell,** 396 operating-growth pools and cells over 2017–2025:
  - the first-filed median is lower in 71% of them, the direction fork 1 expected (recasts are mostly divestitures);
  - the mean difference is −0.2 points;
  - 17 differ by more than 1 point, the largest 1.9 points (vintage 2025, k1, cell s2_g6, n 56).
- **The ruling:** the centre is not measurably worse, so AL.22's recommendation stands. The small downward lean of first-filed medians is
  recorded as a property of `priors_v4_pit`.
- **Fork 1's broader point is adopted:** label noise is not a calibration method. Under-coverage stays E3's diagnosed FAIL. Its remedy, if
  any, is a separately registered marginal-calibration candidate (AL.5), never a choice of outcome definition made for its side effects.

**AL.24 (2026-10-14 14:36): REGISTRATION of how E5 (the oracle, REGISTRATION_engine_v2 section 1) is computed. Fixed before any code or number
exists.**
- **Why it needs a re-run.** The forensic run's records (Addendum U, `scratch/rev23/forensics/run_main`) keep values and realised paths
  but not the company states, so v2 cannot be valued from them. E5 re-runs that pipeline, `rebuild_harness.forensics.run`, unchanged,
  over its 20 quarter-ends 2020-03-31..2024-12-31, with one addition per valued operating or financial name with a market cap of at least
  $300M.
- **One information set for both engines (a fairness rule).** The stored v1 oracle (`or_both` / `or_rote`) overrides every realised year
  up to K ≤ 8. v2 can take realised values only in years 1–3 and the long-run margin. E5 therefore computes both engines on the same
  realised information:
  - **operating:** revenue growth and operating margin of years 1..min(K, 3); the long-run margin is the realised year-5 margin when
    K ≥ 5, otherwise the prior's P50;
  - **financial:** ROTE of years 1..min(K, 3); tangible-book growth stays the engine's own P50 path.

  The three values:
  - **v2 oracle:** `operating_chain_v2` / `financial_chain_v2` at v2's median point (`at_median_inputs`), with `nt_lgrowth_k` =
    log(1 + realised g_k), `nt_margin_k` / `nt_rote_k` = the realised level, for those k. Tables: `data/priors_v4_pit`, vintage
    year(T) − 1.
  - **v1 oracle, same information:** the forensic chains (`forensics.chains.op_chain` / `fin_chain`) with `g_over` / `m_over` /
    `rp_over` restricted to k ≤ 3, and the same long-run margin rule.
  - **v1 oracle, full K:** the stored `or_main`, reported only.
- **The score:** ln(oracle value per share ÷ price).
- **The statistic:** `fxm.per_date`'s `ic_resid`. That is the Spearman correlation with the 3-month excess return of the score's rank
  residual, after the yardsticks and the **Y1** controls (book ÷ price, log market cap, idiosyncratic volatility, 1-month reversal,
  1/price), industry-demeaned. It is taken per date, then:
  - the mean over the 20 dates (pooled);
  - by valuation year (2020–2024, 4 dates each);
  - under each of the three bounds.

  Y1 columns the panel lacks are built point in time from the price files, as the selection tooling (E1) builds them.
- **Bars,** applied to v2 oracle against v1 oracle on the same information:
  - (i) pooled, and in each year: v2 `ic_resid` ≥ v1 `ic_resid` − 0.02, under each bound;
  - (ii) for each family with at least 500 name-dates: the sign of v2's pooled `ic_resid` equals v1's. No family's sort is inverted.
    Commodity is out of scope (V3).
- **Also reported:** the v1 full-K oracle, n per date, and refusals (v2 refusing where v1 values, and the reverse).
- **Compute:** about 5–6 CPU hours at 3 workers, as a scheduled chain with a guard and HOLD. It runs after the AL.21 cascade and needs
  no GPU.
- **Code:** a new `rebuild_harness/forensics/e5_v2.py` (my code, with tests) and a run flag. The forensic run's existing outputs are
  untouched; E5 writes to its own folder.

**AK.42 (2026-10-14 14:39): the operator approves AK.37 v2 and AL.22** ("approve AK.37 v2 and AL.22").
- **AK.37 v2,** the outcome amendment with AK.39's additions, is written into `REGISTRATION_gate2b.md` (before section 4) and
  `SPEC_S5_muse_integration.md` (before the procedure). It replaces first-filed growth and margin with the same-filing measure, adds the
  total-revenue verification, public-availability eligibility (SEC Item 2.02, the pack, and the annual report on or before T), the 120-day
  guard and the exclusion register. No gate-2b data and no S5 fit exist yet.
- **AL.22:** engine v2 keeps `priors_v4_pit`, its first-filed residual tables, unchanged as approved. AL.23 measured that P50 accuracy is
  equal on tag-consistent outcomes. The bands' under-coverage remains E3's recorded FAIL, and any remedy is a separately registered
  calibration candidate.
- **Next, coordinator:** `same_filing` gains the closure test (reading raw companyfacts, because the store keeps only the extractor's
  tags) and the Item 2.02 check (reading SEC submissions), with tests. Then they are wired into the outcome builder used by S5's fit and
  by gate 2b, against the post-fix `pit_data` (`688281f` and later).

**AK.43 (2026-10-14 14:43): the AK.37 v2 checks are built and reproduce the audit.** `same_filing.revenue_scope` and `same_filing.item_202_public`
(rs2-local `review-2026-10/gate2-run2` `9b453d9`; 3 new unit tests; suite 760 passed).
- **`revenue_scope`** reads SEC's raw companyfacts, because the store keeps only the extractor's tags. Its outcomes are dominance,
  closure, closure_fail (abstains) or unverified (flagged).
- **`item_202_public`** reads SEC submissions: an 8-K with Item 2.02 accepted after the period's end and before 16:00 ET on T, by its
  acceptance timestamp.
- **On gate 2 both reproduce the audit exactly:** scope 51 / 201 / 84 / 1 with 0 mismatches against `revenue_scope_check.json`, and 56
  q1 rows public through Item 2.02.
- **Next:** the outcome builder for S5's fit (gate-2 rows) and for gate 2b, applying measurement, verification, eligibility and the
  register, on post-fix `pit_data`.

**AL.25 (2026-10-14 14:53): a defect in engine v2 as approved. Its years-4-onward continuation amplifies year-3 deviations, through noise in the measured
curves, into exploding valuation tails. Found while building E5. A decision for the operator before gate 2b's freeze.**
- **How it was found.** E5's smoke run (one date, 300 companies; AL.24 code) refused 21 of 257 oracle values with "growth at or below
  −100%", although every realised growth fed in was above −100%.
- **The mechanism** (`engine_operating_v2`, SPEC_engine_v2 section 2): years 4–5 take g_t = g_T + (g_3 − g_T)·d_t / d_3, with d the measured
  growth-decay curve.
  - With v1's own path this reproduces v1 exactly. That was the design test.
  - But the measured curves are not monotone: medians at k = 4–5 often exceed k = 3. So d_t/d_3 > 1, and any year-3 deviation is multiplied
    after year 3. v1 never divides by d_3.
  - The financial chain does the same three times: tangible-book growth (d_t/d_3), the pre-fade ROTE (ρ_t/ρ_3), and a division by the
    excess-fade factor φ_3 in R*_3.
- **How large** (max(d_4, d_5)/d_3 per growth band, priors_v3, clipped to [0, 1]):
  - **operating, 2016–2025:** above 1 in most bands; 158× (2019, band 4), 22.5× (2021, band 2), 21.7× (2018, band 6). **Vintage 2025,
    which gate 2b uses: 6.4×, 3.5× and 2.1× in the three fastest-growth bands.**
  - **financial growth:** 164× (2023, band 0), 54× (2025, band 0).
- **The effect on valuations.** Diagnostic `e5_v2.v2_distribution`: v2's full run, 2,000 draws, on the captured state beside v1's own.
  The forensic pipeline, 600 companies, `priors_v4_pit`.

  | Date, family | n | P90/P50, median: v1 / v2 | P90/P50 at the 90th percentile: v1 / v2 | Invalid draws, v2 | P50 v2/v1, median |
  |---|---|---|---|---|---|
  | 2021-06-30 operating | 272 | 2.69 / **17.7** | 6.6 / **526** (max 86,822) | **4.8%** (94 names over 5%) | 0.68 |
  | 2024-06-30 operating | 238 | 3.03 / 5.87 | 7.9 / 16.1 | 0.4% | 0.93 |
  | 2021-06-30 financial | 144 | 1.45 / 2.05 | 2.05 / 3.6 | 0% | 1.26 |
  | 2024-06-30 financial | 123 | 1.35 / 2.05 | 1.57 / 2.5 | 1.8% | 1.03 |

  The verdict contract v4 reads **mean_iv**, the mean of the draws (V1). Upper tails like these would dominate it.
- **The cause is confirmed by a prototype** (diagnostic only; the engine is not changed). The growth-decay curve is replaced by its running
  minimum, which is non-increasing, so a year-3 deviation can never grow afterwards:
  - **2021 operating:** P90/P50 median 17.7 → **4.6**; 90th percentile 526 → **15**; invalid draws 4.8% → **0**.
  - **2024 operating:** 5.87 → 3.40.
  - **financial:** barely moves (2.05 → 2.03 and 1.83). Its ROTE path and the φ_3 division are separate sources, not yet measured.
  - **What remains:** v2 stays wider than v1 (4.6 against 2.7). Part of that is by design, since v2 draws years 1–3 from its own measured
    residuals, which E3 found still too narrow. Part is unexplained, with a maximum of 52–102×. That needs its own attribution.
- **What was missed.** No registered check looked at v2's **valuation** distribution. E1–E4 test forecasts, E5 the oracle ranking, E7
  isolation. E3/E4 are unaffected: they cover years 1–3 only.
- **Proposed to the operator (nothing changed yet):**
  1. **v2.0.1.** Every continuation ratio in both chains (d_t/d_3, ρ_t/ρ_3) uses the curve's running minimum, so the ratio is at most 1.
     The financial φ_3 division is measured and fixed by its own rule before freezing. Identity with v1 is kept wherever the curve is
     monotone, and tested.
  2. **A new registered check, E8,** valuation sanity against v1 on the forensic dates. Fixed before it is run:
     - invalid draws ≤ 1% per name in 99% of names;
     - median P90/P50 within 2× of v1's;
     - no name above 50×, unless explained by its inputs.
  3. **E5 waits for v2.0.1.** Running it on v2.0 would score an engine about to change.

  Gate 2b's freeze (after 10-30) needs v2.0.1 and its checks first.

**AK.44 (2026-10-14 14:56): the coordinator's ruling on fork 2's AL.25 (engine v2's continuation defect), for the operator.**
- **Agreed:** the defect is real and must be fixed before any SYSTEM freeze.
  - A ratio d_t/d_3 above 1 multiplies a year-3 draw's deviation in years 4–5, and the measured curves are not monotone. The running-
    minimum prototype removes the explosion (P90/P50 17.7 → 4.6; invalid draws 4.8% → 0).
  - The valuation-level distribution (P10/P90, `mean_iv`, Pr(IV > price)) feeds the verdict contract (v4 section 2a), sizing and H-S1, so
    a v2.0 freeze would carry it into gate 2b and the shadow book.
  - The coordinator supports AL.25's plan: v2.0.1 (non-amplifying continuation in both chains, with the financial φ_3 division measured
    and fixed by its own rule); E8 (valuation sanity against v1), registered before it is run; E5 waits.
- **What is not affected:**
  - **gate 2's result:** its code arm and Muse ran on engine v1 (`c7d7a4f`), and its bars score year-1 forecasts;
  - **S5's fit:** it transports Muse onto v2's year-1 P50, which the year-4-onward continuation does not touch. The fit can proceed,
    but the S5 **freeze** (SYSTEM) waits for v2.0.1 and E8;
  - E3 and E4 (years 1–3).
- **The lesson, adopted into the Q-rules:** no registered check covered the engine's valuation distribution, only its forecasts. From
  now on every engine version carries a valuation-level sanity check (E8) beside its forecast checks, before any freeze.

**AL.26 (2026-10-14 15:02): the remaining tails of AL.25 attributed, before any E8 bar is set** (fork 1's AK.44 asked that the bars not be set around
them). A diagnostic only; the engine is unchanged.
- **The P90/P50 maxima of 52–1,016× are mostly a measurement artefact.** Those names have equity near the floor. Their v2 P50 is about 0
  (CIK 1374535: v2 P50 $0.13 against v1's $13.67, with a similar P90), and v1's own P90/P50 is 12–70× on several of them.
  - The ratio of equity quantiles is not a valid tail measure near the floor, so E8 must not use it alone.
  - On enterprise value (no floor), the envelope prototype's 2021 operating median is 4.3, its 90th percentile 12.4, and its maximum still
    367.
- **The tail measure the verdict reads:** the share of a name's mean equity coming from its top 1% of draws (mean_iv, V1). Medians, with
  90th percentiles in brackets:

  | Date, family | v1 | v2.0 | v2 with the growth envelope (prototype) |
  |---|---|---|---|
  | 2021 operating (n 341) | 0.062 (0.177) | **0.543 (0.972)** | 0.242 (0.369) |
  | 2024 operating (n 277) | 0.079 (0.163) | 0.241 (0.381) | **0.095** (0.252) |
  | 2021 financial (n 144) | 0.023 (0.081) | 0.203 (0.637) | 0.197 (0.456) |
  | 2024 financial (n 123) | 0.025 (0.049) | 0.154 (0.358) | 0.076 (0.358) |

  The share of draws at the equity floor is similar across the versions (operating medians 0.21–0.30).
- **The attribution:**
  1. **The years-4+ amplification (AL.25)** is the largest source in operating. The envelope brings 2024 near v1, 0.095 against 0.079.
  2. **Financial tails are another source.** The growth envelope barely changes them, which points to the ROTE continuation (ρ_t/ρ_3) and
     the φ_3 division (AL.25). Not yet measured per term.
  3. **2021 operating stays heavy** with the envelope (0.24). The candidate is the residual tables themselves: 2021 dates use the
     vintage-2020 table, whose P1/P99 log-growth residuals include the COVID shock year (E3's shock-year failure, AL.4). Drawn in years
     1–3 through a positively correlated copula, they compound. Not yet measured.
- **What this means for the design** (the operator's, with AL.25's proposal):
  - v2.0.1's growth envelope is necessary but not sufficient.
  - The financial path needs its own fix.
  - mean_iv's exposure to the residual tails is a property of v2's design: uncentred empirical residuals, a correlated copula, and the mean
    as the value. It needs a ruling, not a patch.
  - E8 reports and bars the top-1% share of the mean (fork 1's suggestion), together with invalid draws = 0, the EV P90/P50 against v1, and
    P50 v2/v1. Bars are set before any v2.0.1 number exists.

**AL.27 (2026-10-14 15:04): the operator approves AL.25–AL.26's proposal ("go ahead with 1-3"). E8 is registered here, before any v2.0.1 number
exists.**
- **Approved:**
  1. **v2.0.1:** a fix of the years-4+ amplification in both chains, and a fix of the financial path, each measured first;
  2. **E8:** a registered valuation-sanity check;
  3. **mean_iv against tails:** brought back to the operator with options once the fixes are measured.

  E5 waits for v2.0.1.
- **E8, fixed now.** fork 1's AK.44 suggestions are adopted. Every bar is stated in terms of v1, measured in the same run; none is derived
  from any v2.0.1 number.
  - **The run:** E5's forensic pipeline (AL.24) over its 20 quarter-ends 2020-03-31..2024-12-31, `--e5-tables data/priors_v4_pit`. Each
    valued operating or financial name with a market cap of at least $300M gets v2.0.1's full run beside v1's own, with 2,000 draws and
    the engine's own seed.
  - **The measures, per name:**
    - the invalid-draw count;
    - the top-1% share of mean equity (the sum of the largest 1% of valid draws over the sum of all);
    - EV P90/P50 (operating: explicit plus terminal PV; financial: equity, since the floor is immaterial there);
    - the P50 equity ratio v2/v1.
  - **Bars.** Each holds for each family (operating, financial), pooled over the 20 dates and in each valuation year (4 dates):
    - **E8a, invalid draws:** **zero** in every name.
    - **E8b, the top-1% share of the mean:** the median ≤ **2 ×** v1's median, and the 90th percentile ≤ **2 ×** v1's 90th percentile.
    - **E8c, EV P90/P50:** the median ≤ **2 ×** v1's median.
    - **E8d, level:** the median of P50 v2/v1 lies in **[0.5, 2.0]**. This is the band REGISTRATION_engine_v2 section 2 named for
      investigation; it is now a bar.
  - **Reported, not barred:** the share of draws at the equity floor; names whose top-1% share exceeds 0.5, with the attribution of each;
    the per-date values.
  - **Outcome.** A pass makes v2.0.1 eligible for E5 and freezing. A fail is diagnosed, and any further fix is a new version measured
    against these same bars. No bar changes after any v2.0.1 number exists.
- **The order:**
  1. v2.0.1 code and tests;
  2. diagnostics of the remaining sources (the financial ρ and φ terms; the shock-year residuals of 2021), on a few dates only;
  3. the combined E5 and E8 forensic run (about 6 CPU hours, scheduled with a guard);
  4. the mean_iv question to the operator.

**AK.45 (2026-10-14 15:22): rulings on an outside review of AL.25/AK.44.** The review read AL.25's draft E8. The registered E8 (AL.27, approved by the
operator) already meets its main demands:
- zero invalid draws (E8a);
- a direct bar on tail dominance of `mean_iv`, the top-1% share (E8b);
- v1 used as a reference beside validity bars, not as ground truth.

**Four additions are accepted.** Each tightens the check and none loosens it. They are passed to fork 2 to register as an addendum before
any v2.0.1 number exists:
1. **The attenuation invariant, tested.** With λ_t the multiplier on the year-3 deviation, 1 ≥ λ_4 ≥ λ_5 ≥ 0 in both chains. The tests
   cover:
   - a zero or near-zero d_3 or ρ_3;
   - a non-monotone curve;
   - a sign change;
   - the monotone case, where v2.0.1 equals v2.0 (and v1 wherever v2.0 equalled it).
2. **The financial rules are written before any code.** ρ_t/ρ_3 and the φ_3 division each get an explicit mathematical rule in the
   registration.
3. **E8 on the gate-2b vintage.** E8 also runs on gate 2's 2026 company-dates, whose inputs at T use the vintage-2025 tables that gate 2b
   uses. The measures and the bars against v1 on the same inputs are as AL.27 sets them.
4. **Identity and reproducibility.**
   - v2.0.1 carries its own `ENGINE_VERSION`, commit, table hashes and diff report.
   - A test shows years 1–3 byte-identical to v2.0 at the same seeds and inputs. Any difference stops acceptance until it is explained.

The order stays AL.27's: code and tests, then diagnostics, then E5 with E8, then the `mean_iv` question to the operator, then any freeze.

**AL.28 (2026-10-14 15:27): v2.0.1 measured; the remaining tails attributed; four additions to E8/v2.0.1 adopted from an outside review (via fork 1,
AK.45); the options for the operator's mean_iv ruling.**
- **Two disclosures first,** in answer to fork 1's question "is it still true that no v2.0.1 number exists?". It is not.
  1. **v2.0.1 numbers exist.** After AL.27 fixed E8's bars, v2.0.1 (e263517) was run diagnostically on 2 of E8's 20 dates (2021-06-30,
     2024-06-30; 600 companies; below). E8's bars were fixed before; the additions below only tighten, and none uses those numbers. The
     vintage-2025 run (addition 3) is on dates no diagnostic touched.
  2. **The financial continuation was coded before its rule was written.** The envelope of ρ and φ was implemented in e263517 together with
     the growth envelope. Its rule is written below, as built, and the code is held to it by the tests of addition 1.
- **The financial rule, as built** (`financial_chain_v2`; for each curve c, ẽ is its running minimum, so ẽ_t = min(c_1..c_t)):
  - **growth:** g_t = g_T + (g_3 − g_T)·d̃_t/d̃_3 for t ≥ 4. If d̃_3 = 0, then g_t = g_T (flat, stamped).
  - **pre-fade ROTE:** R*_3 = I + (ROTE′_3 − I)/φ̃_3, then R_t = r_T + (R*_3 − r_T)·ρ̃_t/ρ̃_3. If φ̃_3 = 0 or ρ̃_3 = 0, then R_t = r_T
    (flat, stamped).
  - **after the fade:** ROTE′_t = I + (R_t − I)·φ̃_t.
  - **Hence,** with r_T = I, ROTE′_t − I = (ROTE′_3 − I)·(ρ̃_t/ρ̃_3)·(φ̃_t/φ̃_3), and every factor is in [0, 1]. The division by a small φ̃_3
    is cancelled by φ̃_t ≤ φ̃_3, so it cannot amplify. With r_T ≠ I, the path is a convex blend between ROTE′_3's deviation and the long-run
    level's.
  - **operating (as before):** g_t = g_T + (g_3 − g_T)·d̃_t/d̃_3.
- **Fork 1's four additions, adopted:**
  1. **Attenuation invariant.** With λ_t the multiplier on the year-3 deviation, 1 ≥ λ_4 ≥ λ_5 ≥ … ≥ 0 in both chains. Unit tests cover:
     - a zero and a near-zero d_3, ρ_3 and φ_3;
     - a non-monotone curve;
     - deviations of both signs;
     - a monotone curve, where v2.0.1 equals v2.0, and equals v1 wherever v2.0 did.
  2. **Financial rules written,** as above.
  3. **E8 on the gate-2b vintage.** The same measures and bars, against v1 on the same inputs, on gate 2's company-dates at 2026-02-27..
     2026-06-30, valued at T with the vintage-2025 tables (`data/priors_v4_pit/2025`). It is a second E8 sample; both must pass.
  4. **Identity and reproducibility.**
     - The engine reports `engine_version` v2.0.1 (the near-term tables stay version v2.0; their hashes are listed with the freeze).
     - A diff report of the engine files from v2.0 to v2.0.1.
     - A test that years 1–3 (the near-term distributions, the forecasts reported, and the years-1–3 rows at the median point) are identical
       to v2.0's at the same seed and inputs. Any difference stops acceptance until explained.
- **v2.0.1 on the two diagnostic dates** (600 companies; v1 beside it):
  - **Invalid draws: 0** in every name.
  - **The top-1% share of the mean, median (90th percentile):**
    - 2021 operating: v1 0.062 (0.177), v2.0.1 0.242 (0.369);
    - 2021 financial: v1 0.023 (0.081), v2.0.1 0.197 (0.456);
    - 2024 operating: v1 0.079 (0.163), v2.0.1 **0.095 (0.252)**;
    - 2024 financial: v1 0.025 (0.049), v2.0.1 0.075 (0.359).
  - So **v2.0.1 alone would not pass E8b** on 3 of the 4 cells.
- **Attribution of what remains.** One variable's residual spread is collapsed to its median at a time (diagnostic):
  - removing the **growth** spread (operating revenue growth; financial tangible-book growth) brings the median top-1% share to **0.046 /
    0.013** (2021) and **0.045 / 0.015** (2024), at or below v1;
  - removing the margin or ROTE spread changes almost nothing (0.238, 0.196, 0.090, 0.067).

  **The remaining tails are the growth residual draws**, compounding through years 1–3 (positively correlated) into the years-4+ path.
- **Why the growth tails are suspect as valuation inputs** (an argument, for the operator):
  - The residuals are measured on first-filed total growth. That includes acquisitions and, for financials, tangible-book growth from
    issuance. A per-share DCF or residual-income model does not pay for either the way the deal did.
  - AL.22 also measured 4–5% of growth outcomes misstated by more than 5 points (recasts, seams, partial lines). Those concentrate in the
    tails.
- **The options for the mean_iv ruling,** each measured on the two diagnostic dates:

  | Option | What changes | Top-1% share, median (2021 op / 2021 fin / 2024 op / 2024 fin) | Mean value against v2.0.1, median | P50 |
  |---|---|---|---|---|
  | **1. Trim the growth residuals' extreme 5% tails** (P1 := P5, P99 := P95, growth variables only; draws beyond carry the P5/P95 value) | the draws | **0.092 / 0.028 / 0.066 / 0.026** (all within 2× of v1; 90th percentiles 0.227 / 0.040 / 0.204 / 0.042) | −12% / −26% / −5% / −10% | unchanged |
  | **2. Trimmed mean** (drop the top and bottom 1% of draws) | the statistic, not the draws | n/a (E8b measures the mean the contract reads; this changes what it reads) | −23% / −18% / −8% / −6% | unchanged |
  | **3. Keep** | nothing | 0.242 / 0.197 / 0.095 / 0.075 | – | – |

  - **Option 1** leaves P10–P90, and so E3's coverage, untouched. It needs a version (v2.0.2) with its own identity tests, because years
    1–3 draws change in their outer 5%.
  - **Option 3** fails E8 as registered.
  - **Recommended: option 1.**

**AK.46 (2026-10-14 15:28): AK.45's additions are registered by fork 2 in AL.28 (`5c7d811`); the coordinator's position on its v2.0.2 "option 1".**
- **AL.28's disclosures, accepted as stated:**
  - v2.0.1 numbers existed on 2 of E8's 20 dates before the additions. The additions only tighten, and the 2026 dates are untouched.
  - The ρ/φ envelope was coded (`e263517`) before its rule was written. That is a process slip, recorded as such: the rule AL.28 writes
    is the one built, and the addition-1 tests bind the code to it.
- **The finding:** v2.0.1 has zero invalid draws, but E8b (the top-1% share) would still fail on 3 of 4 cells. Collapsing each variable in
  turn puts the whole remaining tail in the **growth** residuals.
- **Fork 2's option 1** (v2.0.2: the growth residuals' P1/P99 set to P5/P95) passes the bars on the diagnostic dates, with means 5–26% lower.
  **The coordinator does not support it yet:**
  1. **The likely cause is measured contamination, not true risk.** 4.6% of first-filed growth outcomes are wrong by more than 5 pt and
     1.9% by more than 20 pt (AL.22: recasts, seams, partial lines), and those errors sit in exactly the P1/P99 tails. **Option 2,**
     asked of fork 2: keep P10–P90 as now (AL.22's coverage result), and take the tail quantiles beyond them from the **tag-consistent**
     residual tables already built. That removes a measured error; a P5/P95 cut is a choice made after seeing E8b fail.
  2. **Choosing on E8's own dates.** Either option is chosen on 2 diagnostic dates. E8's verdict is read on the dates not used for the
     choice (the other 18, and AL.28's 2026/vintage-2025 dates), reported apart from the 2.
  3. **The mean moves.** Lowering means by 5–26% changes `mean_iv`-based direction, sizing and H-S1. That is an economic change, for the
     operator with both options measured.

**AL.29 (2026-10-14 15:33): fork 1's two concerns about option 1. The tag-consistent tail graft is measured: the tails are not measurement error. E8's
verdict is read away from the diagnostic dates.**
- **Concern 1, "are the heavy tails AL.22's misstated outcomes?"** Measured with the variant fork 1 proposed (`e5_v2._tc_tails`,
  diagnostic):
  - P10–P90 as in `priors_v4_pit`;
  - P1, P5, P95 and P99 grafted from the tag-consistent tables (`engine_v2_audit/tc_sf/tables`, AL.22) as offsets from their own
    P10/P90, cell by cell.

  The same 2 diagnostic dates, operating revenue growth. The tag-consistent tables exist for that variable only, so financial
  tangible-book growth cannot be tested this way.

  | Date | Top-1% share, median (P90): v1 | v2.0.1 | option 1 (P1/P99 := P5/P95) | tag-consistent tails | Mean vs v2.0.1: option 1 / tc tails |
  |---|---|---|---|---|---|
  | 2021-06-30 (n 341) | 0.062 (0.177) | 0.242 (0.369) | **0.092 (0.227)** | 0.238 (0.377) | 0.88 / 1.01 |
  | 2024-06-30 (n 277) | 0.079 (0.163) | 0.095 (0.252) | **0.066 (0.204)** | 0.098 (0.236) | 0.95 / 1.01 |

  **The tag-consistent tails are as heavy as the first-filed ones.** The extreme growth outcomes driving E8b are not the recasts, seams or
  partial lines of AL.22. They are real extreme reported growth (acquisitions, post-shock rebounds; for financials, issuance-driven book
  growth). AL.28's "suspect as measurement" argument is withdrawn.

  What stands is the economic argument alone: a per-share DCF or residual-income model credits that growth without the consideration or
  dilution that bought it. **So option 1 is an economic modelling choice, not a data clean-up.** It lowers mean values by 5–26% on these
  dates, which moves mean_iv, the verdict's direction, and the H-S1 signal (fork 1's point, adopted). The operator rules with that stated.
- **Concern 2, "not fitted to E8's own dates," adopted.** Whatever is chosen was chosen on 2 of E8's 20 dates (2021-06-30, 2024-06-30).
  E8's verdict is read on:
  - the other **18** forensic dates;
  - the **2026 / vintage-2025** sample (AL.28 item 3).

  The 2 diagnostic dates are reported separately and count toward nothing.
- **The diagnostic code:** `_tc_tails`, the `--e5-tc-tables` flag, and a fix that keys the worker's table cache by folder as well as
  vintage (it would otherwise have mixed the two table sets).

**AK.47 (2026-10-14 15:34): the coordinator's AK.46 hypothesis is refuted (fork 2's AL.29), recorded as the coordinator's error.**
- **The test.** P10–P90 kept, with the tail quantiles taken from the tag-consistent tables cell by cell, on the same 2 diagnostic dates.
  The operating top-1% share barely moves: 0.238 against v2.0.1's 0.242 (2021), and 0.098 against 0.095 (2024). Means move by less
  than 1%.
- **What it shows:** the heavy tails are real extreme reported growth (acquisitions, rebounds), not recasts or seams. Fork 2 has withdrawn
  the measurement argument, and the coordinator's is withdrawn too.
- **Adopted from AK.46:** E8's verdict is read only on the 18 dates and the 2026/vintage-2025 sample not used to choose a fix.
- **The coordinator's framing of the remaining economic choice** (for the operator, with fork 2):
  - **(a) Clip the growth tails at P5/P95 (option 1).** Simple. Means fall 5–26%, and it narrows the forecast distribution below what
    history shows.
  - **(b) Keep the distribution and change the value statistic** (for example, `mean_iv` from draws winsorised at P99). This is AL.27's
    `mean_iv` question. It must be decided on economic grounds and registered before E8 reads it.
  - **(c) Financing-aware growth.** Growth above the internally fundable rate (reinvestment ÷ ROIC) is charged with dilution at the
    current price. It models the actual flaw (per-share value credited for externally financed growth), but it is a larger change
    under its own registration.

  The coordinator leans to (c) as the end state, with (a) or (b) only as a labelled interim. The decision is the operator's.

**AK.48 (2026-10-14 15:38): the operator rules on engine v2's growth tails: "go w/ your lean" (AK.47).**
- **The end state is (c), financing-aware growth.** Growth above the internally fundable rate (reinvestment ÷ ROIC) is charged with
  dilution at the current price, so per-share value is never credited with externally financed growth. It is a new engine version under
  its own registration (spec, tests, E1–E8 including the AK.45 additions), built by fork 2, and it replaces the interim when it passes.
- **The interim is (a), v2.0.2:** v2.0.1 with the growth residuals' P1/P99 set to P5/P95. The coordinator chose it over (b) because it:
  - acts on the growth input where the flaw lies;
  - leaves P10–P90 untouched, so E3, gate 2b's B4 and S5's fit are unaffected;
  - keeps `mean_iv`'s definition, so the approved verdict contract v4 and H-S1 stand as registered;
  - is not a statistic that passes E8b by construction, which a P99-winsorised mean would be.

  **Its label everywhere:** "interim: unmodelled financing of extreme growth approximated by clipped growth tails". Each verdict carries
  the engine version, so every row made with it is identifiable.
- **E8 for v2.0.2:** the registered bars (AL.27 + AL.28), read only on the 18 dates and the 2026/vintage-2025 sample not used to choose it
  (AK.46/AL.29). The means' 5–26% fall is reported, with the count of rows whose direction or size changes.
- **The order:**
  1. v2.0.2 code, plus the AL.28 tests;
  2. E5 and E8 on the held-out dates;
  3. if E8 passes, v2.0.2 is eligible for the gate-2b SYSTEM freeze;
  4. in parallel, (c)'s registration is drafted for the operator.

**AK.49 (2026-10-14 15:42): the outcome builder of record is built and run on gate 2 (for S5's fit).** `rebuild_harness/gate2/eligible_outcomes.py`.
- **What it applies:** the same-filing measures; total-revenue verification; public-availability eligibility (SEC Item 2.02, the pack, and
  the annual report on or before T); the 120-day guard; the register. It runs on the post-fix `pit_data` (the fiscal-year fix changes
  year 1 where reports were mislabelled; Avnet's base is now 2025-06-28).
- **The output:** `scratch/rev23/s5_data/eligible/`.
- **What it finds on gate 2:**
  - q1: 400 → **344 eligible** (56 public through Item 2.02, which includes the 53 in packs and all 5 stale picks);
  - annual: 213 → **194 eligible** (19 public: AK.34's 4 same-day and 15 released);
  - scope: q1 51 / 201 / 84 / 1, as AK.39; annual 30 dominance, 105 closure, 45 unverified, 0 fail;
  - **77 register entries,** each with its source and acceptance timestamp.
- **Not yet done:** this builder's own unit tests, a full-suite run, and its use in the S5 fit (B4).

**AL.30 (2026-10-14 15:42): the mean_iv ruling relayed by fork 1 (AK.48, the operator: "go w/ your lean"). v2.0.2 (interim) is built. Option (b) is
recorded. Confirmation is asked of the operator in this session.**
- **The ruling, as fork 1 relays it** (AK.48):
  - **End state:** financing-aware growth. Growth above the internally fundable rate (reinvestment ÷ ROIC) is charged with dilution at
    the current price. It is a new engine version with its own registration, drafted by fork 2. It replaces the interim when it passes.
  - **Interim:** **v2.0.2** = v2.0.1 + option 1. Labelled everywhere as "interim: unmodelled financing approximated by clipped growth tails".
  - **E8 for v2.0.2:** the AL.27 and AL.28 bars, read only on the **18 held-out dates and the 2026 / vintage-2025 sample**. The mean
    change and the count of direction or size changes are reported.
  - **Order:** v2.0.2 → E5 + E8 → (on a pass) eligible for the gate-2b freeze.

  The ruling reached this session through a peer. It is recorded as relayed and acted on as reversible work. The operator is asked to
  confirm it here.
- **Option (b), for the record** (fork 1 asked for its numbers): the mean with each name's draws capped at its own P99, over the plain mean,
  median (P10): 2021 operating 0.906 (0.751), 2021 financial 0.862 (0.627), 2024 operating 0.974 (0.912), 2024 financial 0.966 (0.715). Not
  chosen.
- **v2.0.2:** rs2-local `review-2026-10/gate2-run2` 53e7a59, pushed after a scan.
  - **The clip:** `near_term.near_term_inputs` sets each growth variable's residual P1 := P5 and P99 := P95 before the draw (`CLIP_LEVELS`).
  - **What is untouched:** P5..P95, and so every reported forecast (`REPORT_LEVELS` P10..P90). The level variables (margin, ROTE) keep
    their tails.
  - **Labels:** `engine_version` "v2.0.2"; `engine_interim` and the near-term info carry `nt.INTERIM`.
- **Tests:**
  - **New:** growth draws never go beyond P5/P95; P5..P95 are as measured; levels keep P1/P99.
  - **Still passing:** the AL.28 attenuation and years-1–3 identity tests. Forecasts and the median-point years 1–3 equal v2.0's.
  - **Suite:** 795 passed.
- **Also in this period (AL.28 additions):** the attenuation-invariant tests in both chains (the zero and near-zero d_3/ρ_3/φ_3, a dip
  before year 3, both signs, a monotone curve equal to v2.0) and the years-1–3 identity golden. That golden file was written by v2.0's own
  code at 22f22b0 (`valuation/tests/data_v20_years_1_3.json`); commit 1d85356.
- **Next:**
  - (a) E8's second sample: a harness for gate 2's 2026 company-dates on the vintage-2025 tables;
  - (b) the combined E5 + E8 forensic run on v2.0.2 (20 dates; the verdict read on 18), scheduled after the priors cascade;
  - (c) the draft registration of financing-aware growth.

**AL.31 (2026-10-14 18:24): the operator confirms AK.48 in this session ("confirmed, go ahead with v2.0.2 and E8"). The outstanding outside review is
planned.**
- **Confirmed:**
  - v2.0.2 is the interim engine;
  - financing-aware growth is the end state;
  - E8 for v2.0.2 is read on the 18 held-out dates and the 2026 / vintage-2025 sample.

  AL.30's "relayed" status is closed.
- **The priors cascade (AL.20–AL.21)** wrote DONE at 16:22. Its diff report is still to be written.
- **The outside review (Q9).** Cross-check 10 (tag seams, scoring order, v2.1 copula) was written but never answered as a package. Its
  parts were overtaken: AK.30 ruled the tag-consistent outcome; outside reviews of AK.37 and AL.25 were ruled in AK.39 and AK.45. No outside
  reviewer has seen:
  - the fiscal-year fix and its rebuild (AL.17, AL.18, AL.20, AL.21);
  - the point-in-time tables and the outcome-definition result (AL.10–AL.12, AL.22, AL.23);
  - the E5 method (AL.24);
  - v2.0.1's and v2.0.2's design and evidence (AL.25, AL.26, AL.28–AL.30);
  - E8's second sample.

  **Cross-check 12** is to be written and sent to ChatGPT and Gemini before any E8 result is read. Number 11 is held for the downstream (C2)
  review, as AK.28 set out.
- **The rule for E8 meanwhile.** The combined E5 + E8 run may compute; its scorer writes its verdict to a file that is **not opened** until
  cross-check 12's rulings are recorded. A reviewer can then still change E8 before anyone has seen a v2.0.2 verdict.
- **Next, after cross-check 12:** the draft registration of financing-aware growth, as its own outside review before the operator approves.

**AL.32 (2026-10-14 18:25): the priors cascade on the fixed `pit_data` (AL.20–AL.21) is complete. The report, negatives first.** The new version
lives in `data/priors_v3_fy` (observations and priors tables), `forecast_study/pass_fy` and `pass_devlegacy`,
`forecast_study/out/panel_fy<V>.pkl` and `data/priors_v4_fy` (near-term tables). Nothing earlier was overwritten.
- **The growth-decay curves are unstable at long horizons** (a negative, and the same root as AL.25):
  - Between `priors_v3` and `priors_v3_fy`, the curve points actually used (ratio_median clipped to [0, 1]) move by more than 0.05 at
    5–17 points per vintage, out of 42–127. The largest moves are 0.3 to 1.0, at k = 6–10; for example 2025 operating band 3, k = 10, moves
    by 1.0.
  - A few hundred corrected rows move them that much, so these curves are estimated on thin, noisy medians at long horizons. v2.0.1's
    envelope limits the damage after year 3. v1 (the frozen gate-2 engine) uses them as measured.
  - Recorded as an open item for the priors: a monotone or smoothed estimator of the decay curves. It needs its own registration.
- **The observation tables:** mislabelled rows go to 0 in every vintage (261–426 in each before). 530–737 fiscal years are regained per
  vintage. The 4–193 rows lost are all explained: mislabelled rows, plus the extractor's 12-year window (`MAX_YEARS`), which now drops
  the oldest year when a restored year is added.
- **The passes, with the decomposition AL.21 asked for:**
  - **AD.10, ticker by SEC order (study → dev legacy):** 6–26 companies per date change ticker or price; 0–3 rows enter or leave the
    universe.
  - **The FY fix (dev legacy → fixed):** 0–17 companies per date change base year; 0–2 rows enter or leave. Almost every forecast moves
    slightly, because the priors tables move. Median absolute change in the P50 is under 0.007 in every field; the 99th percentile is
    under 0.05 (rote_norm 0.048 in 2018).
  - **The extremes** are on the companies whose base year was corrected. For example, a 2025 margin forecast moves by 29, and 2024 ROTE
    forecasts by 1.0–1.8 for a handful of names.
- **The near-term tables, `priors_v4_fy` against `priors_v4_pit`:** pool P10/P50/P90 move by at most 0.036 (2018, financial tbvg k2);
  from 2021 on, by at most 0.009. Cell counts are equal, or 1–3 larger (2021–2024).
- **E3/E4 on `priors_v4_fy`** (`e3_e4_fy.json`, outcomes from `panel_fy2024`):
  - every cell's coverage moves by at most 2.2 points (operating margin k2, 0.661 → 0.639). The others move by at most 1.3 points, in both
    directions;
  - **E3 FAIL and E4 PASS (3 of 12 worse) as before.**
- **For the operator:**
  - The fixed version is correct where the legacy one was not (missing and mislabelled fiscal years), at the cost of small shifts.
  - **Recommended:** gate 2b and the v2.0.2 freeze use `priors_v3_fy` / `priors_v4_fy` with the fixed `pit_data` (688281f+), matching
    fork 1's plan (AK.42). Gate 2's frozen inputs stay as they are.
  - E5 and E8 are still to be run on `priors_v4_pit`, as registered (AL.24, AL.27). Cross-check 12 is asked whether they should move to
    `priors_v4_fy` before running.

**AL.33 (2026-10-14 18:31): E5 and E8 on v2.0.2 are running, verdicts sealed (AL.31). Cross-check 12 is written. E8's second sample has its harness.**
- **Cross-check 12:** `CROSS_CHECK_12_engine_v2_interim_e8.md` (fea6277), 12 questions. Fork 1 is asked to mirror it, with the records
  through AL.32, for the operator to send to ChatGPT and Gemini.
- **The forensic E5 + E8 run:** scheduled task `RS2-EngineV2-E5E8` (`engine_v2_audit/e5e8_chain/`), started 18:28.
  - Its inputs: 20 quarter-ends, `--e5-tables data/priors_v4_pit --e5-dist`, engine v2.0.2.
  - Its outputs: the records, then point-in-time price features (Y1), then E5's and E8's scorers.
  - **Sealing:** both scorers write their verdict to a file and print counts only; the chain does not open them (AL.31).
  - **The diagnostic variants** are now behind `--e5-diag` and are not run. The run records v1's EV P50/P90 from v1's own draws, for E8c.
- **E8's second sample:** `rebuild_harness/forensics/e8_gate2b.py` (ea16c77), on fork 1's read-only recipe.
  - **Read-only setup:** a scratch `RealEnv` state folder holding copies of run 2's `ctx/context_<d>.pkl` for 2026-02-27, 04-30 and 06-30,
    and `sample/` (sha256 equal); `fetch_documents=False`. Nothing under `data/gate2_run2` is written.
  - **The input fingerprint** against run 2's freeze: **no differences**.
  - **Smoke test (6 jobs):** v1 there is run 2's code arm exactly. Its P50 per share equals `result.json`'s `code_only` value to the last
    digit on all 5 valued names, and their base years equal run 2's.
  - **The full run** (vintage-2025 table, `priors_v4_pit`) and its sealed scorer are in progress. The count of base years differing from
    run 2 (the FY fix) will be reported, as fork 1 asked.
- **Code** (rs2-local `review-2026-10/gate2-run2`, pushed after scans):
  - 2d042a3: the E8 scorer; the E5 scorer sealed;
  - ea16c77: the gate-2b sample harness.

**AL.34 (2026-10-14 19:04): E8's second sample (2026, vintage 2025) is computed. Its verdict is sealed (AL.31); only the counts are read.**
- **The first attempt crashed** on a name with no mapped Damodaran industry (`DataNotPresent` from the discount rate). The pipeline refuses
  that case, so the harness now counts it as a refusal (5afb414) and does not value it.
- **The run:** `engine_v2_audit/e8_2026/run`, tables `priors_v4_pit/2025`.
  - 360 company-dates; **253 valued**;
  - not valued: 1 refused at inputs, 12 at the discount rate, 94 by the v1 engine.
  - The scratch copies are hash-equal, and the input fingerprint has no differences from run 2's freeze.
  - **Base years differing from run 2: 0** (fork 1's question; the FY fix changes none of these names).
- **Agreement with run 2:** run 2's statuses at these dates are ok 253, engine_refused 90, refused 14, error 3.
  - The valued set has the same count, and the harness's v1 equals run 2's code arm on the smoke names (AL.33).
  - The non-valued split differs (107 = 94 + 12 + 1 against 90 + 14 + 3) because run 2's 3 pre-model code errors are clean refusals in the
    corrected code (AK.5).
- **Sealed:** `e8_verdict_gate2b.json` is written and not opened. The scorer printed only "rows 253, 3 dates".

**AK.50 (2026-10-14 19:04): S5's adoption rule will very likely give w = 0 on every measure. Measured as counts only (no error was read); the
choice goes to the operator.**
- **The rule** (S5 section 4, approved, with the AK.42 amendment): w is adopted only with **at least 150 annual out-of-fold pairs from at
  least 2 dates with at least 30 each**, otherwise w = 0.
- **The eligible annual outcomes on gate 2** (`scratch/rev23/s5_data/eligible`), before any forecast-availability filter, which can only
  lower them:

  | Measure | Pairs | 2025-10-31 / 12-31 / 2026-02-27 / 04-30 / 06-30 |
  |---|---|---|
  | Operating revenue growth | **143** | 60 / 55 / 13 / 13 / 2 |
  | Operating-margin change | **143** | same |
  | Financial ROTE change | **49** | 23 / 25 / 0 / 0 / 1 |

  The q1 breadth outcomes are 265, 262 and 76.
- **Every cell is under 150, so by the registered rule w = 0 throughout.** This is S5's foreseen outcome:
  - S5 section 4 itself said the annual target comes mostly from two dates;
  - the outside review warned of it in cross-check 9 (AK.19 ruled to keep the rule).

  The audit's corrections moved revenue growth only from 150 (registered) to 144 (tag-consistent) to 143 (eligible).
- **The coordinator's recommendation:**
  1. keep the rule (w = 0), so gate 2b tests engine v2 as SYSTEM;
  2. still run Muse on gate 2b's dates and record its positions, unused, so that a future Muse weight, fitted later under its own
     registration, can be tested on untouched dates;
  3. that later fit must avoid outcomes gate 2b scores: gate-2 and gate-2b companies share fiscal-2026 results, so its design needs care.

  **Alternatives:** (B) skip Muse on gate 2b, saving about 3 GPU days; (C) amend the rule now, which the coordinator advises against
  because it would be decided after seeing the consequence.
- **Fork 2's AL.33–AL.34:** E8's 2026 sample is built on a scratch `RealEnv`:
  - fingerprint equal to run 2's freeze;
  - 253 valued, as in run 2;
  - 0 base-year differences after the FY fix.

  Its verdict is sealed until cross-check 12 is ruled.

**AK.51 (2026-10-14 20:17): rulings on cross-check 12 (Gemini and ChatGPT). E5 and E8 stay sealed until items 1–7 are done.**

ChatGPT read the branch code, and Gemini reviewed the brief only. The coordinator verified ChatGPT's code claims at `5afb414`:
- `e8_score.rows_of` keeps only names valued "ok" by both engines;
- `e8_gate2b` aborts on neither a copy mismatch nor a fingerprint difference, and passes `priors_dir=None`;
- `e5_v2`'s financial oracle overrides realised ROTE but not tangible-book growth;
- `compact_company` keeps only `EntityCommonStockSharesOutstanding` from `dei`.

**Accepted; done before any verdict is opened** (fork 2 builds; each is a fix of test integrity or a tightening, never a relaxed bar):
1. **Lineage (both).** The E5 and E8 acceptance runs use **`priors_v3_fy` + `priors_v4_fy`, pinned explicitly**, with paths and hashes in the
   output and each date at its eligible vintage. The `priors_v3` / `priors_v4_pit` runs are kept as a labelled legacy sensitivity.
2. **E8 fails closed (ChatGPT).**
   - **Reconciliation:** attempted, then valued by both, then excluded, with the reason for every exclusion. A missing date fails.
   - **v2 refusals:** a name v1 values but v2 refuses is listed. Without a named engine reason, it fails E8.
   - **Integrity:** a scratch copy that does not match aborts the run. Fingerprint differences are allowed only from an approved list
     (the fiscal-year inputs).
3. **E5's financial oracle, matched (ChatGPT).** A variant gives both engines realised tangible-book growth and ROTE for years 1–3. It is
   the financial reading. The ROTE-only version is kept as a labelled sensitivity. The bar is unchanged.
4. **The fiscal period's authority (both; Gemini's case of a late or restated 10-K).** Before the freeze, every annual accession whose
   inferred period changed under the fiscal-year fix is validated against SEC's `reportDate` (in the submissions JSON), and so are all
   annual accessions of the gate-2b universe. Every disagreement is listed. Keeping `DocumentPeriodEndDate` in the store is a later store
   change.
5. **The interim clips the upper tail only: v2.0.3 (Gemini).** The financing argument (AK.47–AK.48) concerns externally financed **upside**
   growth. Clipping P1 to P5 removes real downside, revenue collapse and distress, with no economic basis.
   - v2.0.3 is v2.0.2 with only **P99 set to P95**; P1 is kept.
   - It is decided now, before any E8 verdict, on the stated rationale, so the operator's ruling (a) is refined, not reversed.
   - It is measured against the same bars on the held-out samples.
6. **A top-5% share bar (Gemini).** A clip piles probability mass at P95, so the top-1% share alone can be passed by the very interim it
   tests. **E8b′:** the top-5% share of mean equity, median ≤ 2× v1's and 90th percentile ≤ 2× v1's. It has the same form as E8b and is a
   tightening.
7. **Test completeness (ChatGPT):** an attenuation fixture with `rote_target` ≠ the industry ROTE.

**Accepted as reported diagnostics, not bars:**
- the factorial attribution, which toggles the growth spread, the other spreads and the copula dependence (both reviews);
- E5 at 12 and 36 months (it never rescues a 3-month fail);
- `mean_iv`/P50;
- the 90th percentile of equity P90/P50;
- the within-industry rank correlation with v1;
- the median `mean_iv`/price;
- the sensitivity of `mean_iv` and Pr(IV > price) to the tail treatment.

**The decay-curve concern, measured first (Gemini Q1/Q12, ChatGPT Q12).** On the `priors_v4_fy` curves, fork 2 reports how often the running
minimum sends λ to 0 at year 4 (a cliff) or pins λ at 1 (a noisy small d_3).
- **The default (ChatGPT):** a smoothed or monotone estimator is a separately registered candidate, not part of this freeze.
- **If the cliffs or pins are common,** that candidate goes to the operator before the gate-2b freeze.

**Rejected, with reasons:**
- **Rebuilding the residual tables on tag-consistent outcomes now (Gemini).** AL.22–AL.23 measured that the first-filed tables cover better,
  with equal P50 accuracy, and the operator ruled (AK.42). AL.29 showed the extreme tails are real growth, not seams. ChatGPT reached the
  same view: a qualified dispersion proxy.
- **Making 12- or 36-month ICs binding (Gemini).** That replaces the registered E5 test; they are reported instead.
- **A bar on rank correlation with v1 (Gemini).** v1 is a reference, not the truth, and v2 is meant to differ.
- **"Implement financing-aware growth now instead of an interim" (Gemini).** It is the registered end state (AK.48), but it needs its own
  specification, tests and E1–E8. It is not a 15-line change to slip in before validation.
