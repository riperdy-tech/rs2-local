# Cross-check request 2: point-in-time data for backtests and an AI replay

You reviewed our earlier proposal: a valuation rebuild for a local-LLM stock analyst, with valuation families,
price-blind AI forecasts and validation by outcomes. You recommended:
- a development period of 2017–2022;
- a frozen code holdout of 2023–2024;
- a monthly AI replay from 2025-10 to 2026-06;
- outcomes judged on first-filed values.

We have now checked whether our data can support that, and it cannot as it stands. This document describes what we
found and what we propose. You cannot see our code or data, so everything is described here. Please answer the
questions at the end.

## Background you need

- **What a "briefing pack" is.** The AI analyst receives a text document of about 50,000 characters per stock. It
  holds about 12 years of financial statements, the latest earnings release and segment table from SEC filings,
  balance-sheet figures (cash, debt), the stock price, market cap, consensus estimates, news, and population base
  rates.
- **The point-in-time mode.** The pack builder already has a mode meant to build the pack as of a past date, using
  only what was public then. We tested it for 172 stocks as of 2026-01-02.
- **Why the replay must start after September 2025.** The AI model (Muse Glimmer 30B, run locally) has training
  knowledge up to about late August 2025, which we measured by probing it with dated events. Replays must use dates
  after that, or the model already knows what happened.
- **The data sources:**
  - **The screener's financial history file.** One value per company per fiscal year per field, for about 5,200
    companies, fiscal years 2014–2025. Built from SEC XBRL "companyfacts". **It stores the value currently on file:**
    if a company later restated a figure, the file holds the restated one, and it does not record which filing each
    value came from.
  - **SEC companyfacts itself (raw).** Every XBRL fact a company ever filed, each with the filing date and accession
    number. Restated values appear as later facts for the same period. Coverage starts around 2009–2011, depending on
    the company. It includes companies that later delisted, if they filed.
  - **Prices:** the pack builder fetches prices from Yahoo Finance (yfinance) with dividend and split adjustment, as of
    today.
  - **A vendor snapshot:** Yahoo-style summary data (total cash, total debt, trailing-twelve-month figures, analyst
    estimates) fetched in September and October 2026. It is only "as of now"; there is no history.

## What the check found (172 stocks, packs as of 2026-01-02)

All 172 packs built. Filing dates and prices on the date exist for 171. But the packs leak information from after
2026-01-02 in five ways, and the data has two structural gaps.

### Leak 1: the stock price is today's adjusted series, cut at the date
- **How it happens:** the builder downloads the full price history *today* with dividend and split adjustment, then
  takes the 2026-01-02 value. Adjusted prices are rescaled backwards every time a later dividend or split happens, so
  the 2026-01-02 "price" depends on dividends and splits paid *after* that date.
- **Size:**
  - 99 of 171 stocks differ from the actual traded close that day by more than 0.1%, 75 by more than 1%, and 18 by
    more than 5%.
  - Example: a stock that actually closed at $11.42 shows $7.44.
  - The adjusted price is never above the real one, so every leaked price is too low.
  - Two stocks split after the date. Their price is on the post-split basis while the share count is pre-split, so
    market cap is wrong by the split factor.
- **Why it matters:**
  - **Valuation:** price, market cap, past returns and "distance from 52-week high" all feed the analysis. A price
    biased low makes stocks look cheaper.
  - **Leakage:** a stock that later paid large dividends looks cheaper on the date, and dividends correlate with
    outcomes.

### Leak 2: missing balance-sheet figures are filled from today's vendor snapshot
- **How it happens:** when the filed long-term debt is missing or zero, or the filed cash is missing, the builder
  falls back to the vendor's "Total Cash" and "Total Debt". Those are today's figures (fetched September–October
  2026), not the date's.
- **Size:** 69 of 172 stocks.
- **Why it matters:** net debt and the equity bridge in the valuation then use balance sheets from up to nine months
  later. That includes, for example, debt raised or repaid after the date.

### Leak 3: a "data freshness" line prints today's trailing-twelve-month date
- **How it happens:** a header line says "trailing figures run through <date>", read from today's
  trailing-twelve-month file. In the 2026-01-02 packs it says dates from 2026-03-27 to 2026-08-01.
- **Size:** 122 stocks.
- **Why it matters:** it tells the model that data through mid-2026 exists, and it was found by simply searching each
  pack for dates later than 2026-01-02. It is a small code defect but a clear signal of the future.

### Leak 4: annual figures for recent listings were first filed after the date
- **How it happens:** 9 companies that listed recently filed their first annual report (10-K, 20-F or 40-F) between
  2026-02-27 and 2026-06-25. The financial history holds those fiscal-year figures, and the pack shows them as
  "filed", although on 2026-01-02 the only public source would have been the IPO prospectus (S-1 or F-1), if at all.
- **Why it matters:** the AI sees audited annual results that were not yet public.

### Leak 5: restated values cannot be detected
- **How it happens:** the financial history holds the value now on file, with no record of which filing it came from.
  A figure restated in a 2026 filing appears in a 2026-01-02 pack as if it had been known then.
- **Size:** unmeasurable with this file, so it potentially affects every stock.
- **Why it matters:** restatements are not random. They often follow problems, which correlate with returns.

### Gap 1: the financial history starts in 2014
- **What it means:** with fiscal years 2014–2025, a company has at most 3–8 years of history as of a 2017–2022 date.
  The margin-reversion statistics we measured from the population need at least 5–8 years of history per company;
  "as of end-2016" there are 3 usable company-years in total. Population priors for the development period cannot be
  built from this file.

### Gap 2: no history of the vendor snapshot or analyst consensus
- **What it means:** consensus estimates, the vendor's trailing figures and analyst targets exist only as of today. A
  point-in-time pack therefore has no consensus, and every part of the old design built on consensus is unavailable.
  That includes its "owner-earnings base" for the current year.

### Also declared, not measured
- **Current values used for every past date:** the sector cost-of-equity loading, the long-run growth anchor and the
  industry taxonomy.
- **A survivor-only population:** the base-rate population includes only companies alive today, so companies that
  failed are missing.

## What we propose

1. **One shared point-in-time data layer**, used by the valuation engines, the population priors and the backtest
   harness alike, built directly on raw SEC companyfacts:
   - every value is taken as first filed (the earliest filing for that period and concept), with its filing date and
     accession number;
   - delisted companies are kept, which reduces survivorship bias;
   - coverage goes back to about 2009–2011, which makes 5–8-year histories possible for 2017–2022 dates.
2. **A filing counts only if its filing date is strictly before the valuation date.**
3. **A fiscal year exists only from its own annual-report filing date.** IPO prospectus data is not used. A company
   with no annual report filed before the date is excluded for that date.
4. **The valuation-date price is the actual traded close that day, unadjusted,** with share counts on the same basis.
   Dividend- and split-adjusted total-return series are used only to measure outcomes after the date.
5. **No same-day snapshot or vendor fallback in point-in-time mode.** A missing value is "not available", never
   filled from today.
6. **Industry betas and the equity risk premium come from dated public datasets.** We have Damodaran's industry beta
   files, one per year from January 2017 to January 2026, and his implied-ERP history. The file dated on or before
   each valuation date is used.
7. **Outcomes for forecast accuracy** (revenue, margins) come from the first filing after the date that reports the
   period, again as first filed.
8. **Consensus estimates are dropped from the new design's inputs,** because no history exists. The AI's forecasts
   come from filings, base rates and (in live use) research. In the replay, research is switched off, because live
   web search would leak the future.

## Questions

1. **Is raw SEC companyfacts, "as first filed", sound enough as the backbone for this?**
   - Known issues we are aware of: tag changes over time, companies that tag inconsistently, segment and dimension
     facts, and foreign filers (20-F and 40-F) with fewer tags.
   - What else will bite, and how would you handle "first filed" when a company files a 10-K and an amended 10-K/A
     shortly after?
2. **Prices:** we have only Yahoo Finance data, which is adjusted by default. Is the unadjusted close
   (`auto_adjust=False`, column "Close") plus the actions history enough to rebuild exact as-of prices and share
   bases? Or is a different free source needed? What about delisted stocks, which Yahoo often lacks entirely, and
   which our survivorship fix depends on?
3. **Survivorship:** with delisted companies present in SEC data but missing price histories, how should the backtest
   treat them?
   - Exclude them, which keeps the bias?
   - Assign a −100% outcome on delisting for bankruptcy, which is wrong for acquisitions?
   - Something else?
4. **Is it acceptable to run the AI replay without consensus estimates,** given that live use would have them? Or
   does that make the replay unrepresentative of the live system? Would you instead remove consensus from the live
   system too, for consistency?
5. **Data freshness:** in live use, the newest filing may be days old. In the replay, is "filed strictly before the
   valuation date" the right rule, or should there be a lag (for example 1–2 trading days) for the market to absorb a
   filing?
6. **What other leakage paths should we test for** that are typical in this kind of point-in-time LLM replay?
   Examples: the model's own knowledge of company names and outcomes despite the training cutoff; news; the industry
   taxonomy.
7. **Given these constraints,** do the splits still make sense (development 2017–2022, holdout 2023–2024, AI replay
   2025-10 to 2026-06)? Or would you change them?
