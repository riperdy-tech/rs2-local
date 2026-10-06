"""The fixed text of PRIORS_REPORT.md: the rules, the definitions and the gaps.  Every number in the tables comes from tables.json; the few figures quoted in the gap
list were read from the 2016 and 2025 vintages when this text was written (`python -m valuation.priors_build.coverage` reprints them)."""

HEAD = """## How to read this report

**Vintages.** A vintage Y is cut at Dec 31 of year Y (the layer is asked for the state at Jan 1 of Y+1, so every filing used was filed strictly before it).
A valuation date T uses vintage year(T) - 1: its prior contains no filing made on or after Jan 1 of year(T), hence none accepted on or after T.  This
is conservative (a prior is on average about six months stale, never ahead).  Vintages 2012..2025 are built (`data/priors/<Y>/`); this report tables 2016, 2020, 2022, 2024 and 2025.
The no-look-ahead proof is `valuation/tests/test_priors.py`: every fact filed on or after the cut is replaced by a different value, a company that first files after the cut is added,
and the observations, the tables and the PriorSet for a date in the following year are identical.  A twin test shows the proof is sensitive: changing a fact filed before the cut changes the observations.

**Observation.** A company-year (CIK, fiscal year t) from the SEC companyfacts archive via `valuation/pit_data.py` (the production extractor, first-filed values, a fiscal year exists
only from its own annual report).  The state at t uses fiscal years <= t; the outcomes at t+k use fiscal years t+1..t+10, only those whose own annual report was filed before the cut.
Fiscal years sit on a chain index (a gap year jumps the index), so "t-7..t" and "t+k" mean years.  The unit of observation is the company-year; neighbouring years of one company overlap,
so n is not an independent-sample size.  Every company in the archive is in (20,175 members), delisted ones up to their last filing.

**Conventions (stated, none tuned to a result).** Quantiles are type 7 at P5/P10/P25/P50/P75/P90/P95.  A cell with n < 50 is merged with its adjacent neighbour (`merge_1d`: the smallest group joins
its smaller neighbour, the lower index on a tie) and flagged `merged`.  Size = revenue buckets (<$50M, $50-250M, $250M-1B, $1-5B, $5-20B, >$20B; nominal USD; non-USD reporters have no size bucket and use
the size-pooled cells).  Growth delivered = trailing 3-year CAGR (the latest year where fewer than four years are held), buckets <-10, -10..0, 0..5, 5..10, 10..20, 20..40, >40%.
Cyclicality and ROIC terciles/quintiles are measured inside each vintage.  The margin deviation is margin_t minus the median of the margins in t-7..t, record rule >= 5 defined years, |dev| >= 0.5 points (A2).
Retention and curve values are clipped to [0, 1] when put in a `Curve` (clips are flagged in `meta["flags"]`); a non-monotone measured curve is reported, never forced.  A curve stops at the last k with
n >= 50 and holds its last value to year 10 (flagged).

**What each table is.**
- `g1`: next-year revenue growth (tangible-book growth for financials) by size x growth delivered, with the baseline's error beside it.
- `growth_decay`: median per-observation ratio (g_k - T)/(g_1 - T) of year-alone growth by growth-delivered bucket, T = the pooled median year-alone growth at the longest horizon with >= 500 observations
  (where |g_1 - T| >= 0.02; the exclusions are counted); raw paths and the ratio of medians are in tables.json.
- `margin_retention` / `margin_target`: A2 on the point-in-time layer by cyclicality tercile x sign of the deviation; `margin_target` = the company's 8-year median margin + quantiles of the level five years on about the
  median-retention path.  Engine consequence: the engine blends m_T with the margin held (m_T(1-r_t) + r_t m_0), so a spread carried by m_T alone is scaled by (1 - r_t); the tables give r_t so the coordinator can decide whether to rescale.
- `ronic`: 3-year change in NOPAT over change in invested capital, defined where invested capital grew by >= 10% of its base (the unfloored distribution is reported beside it); `ronic_fade` is a measured PROXY (gap 8).
- `g_terminal`: annualised revenue growth over K_eff years (K_eff = the longest horizon with >= 200 complete observations, 10 from vintage 2020 on), complete, with delisted companies (those known at the cut to have stopped filing, at their last
  available horizon >= 3 years, a proxy of the business and not of the shareholders' outcome), and without companies that later stopped filing.
- `rote_target` / `rote_retention` / `excess_fade`: the same on return on tangible equity of financial companies.
- `ev_fcf_multiple`, `ptbv_of_rote`: the month-end close at the observation date (the first month-end session after the filing of year t's annual report) over the engine's own equity bridge; cross-check references only.
- `normalization_curve(score, horizon)`: the margin-retention medians by score quintile, interpolated at the score.
- `curve_position(name, state)` (Addendum E 1): the P5..P95 distribution, clipped to [0, 1], of the per-observation fraction of the gap still open at year 5 in the cell the company's curve is read from; its median equals the curve at year 5 (a test).
- Correlations: Spearman on the realised inputs, converted to the Gaussian-copula r; the PriorSet carries them in `meta["corr"]`.
- Cyclicality weights: NNLS of the four components on the winsorized reversion fraction, development years only, cross-fitted by year with the held-out year's companies removed from training; adopted only if the cross-fitted error beats the scaled equal weights.

## What the data cannot say (gaps, stated rather than filled)

1. **History starts with the XBRL era (fiscal year 2009 for the largest filers, 2010-2011 for the rest).**  The 2016 vintage therefore holds outcomes only to k = 6-7 and a 5-year margin record for few companies (the cyclicality score is defined for
   ~2.6% of operating observations); 10-year growth exists only for base years <= 2015, so conditioning g_terminal on a trailing trend (needs 5 years of record) leaves almost no complete 10-year observation (the `shrinking` stratum is mostly truncated horizons).
2. **SIC is a current-dated label for living companies only** (Damodaran indname, January 2026, through current tickers): about 1% of the observations of companies that later stopped filing have a SIC, against 75-82% of the others.  A delisted company is therefore classified by the balance-sheet tests alone
   (insurance reserves, lending book): delisted banks and insurers with those tags are found, delisted commodity companies are not, so **the commodity family is survivor-only** (0.3% of its 2025-vintage observations come from companies that later ceased, against 44% for operating).  SEC submissions for the delisted CIKs would close this; it is a download not made here (question).
3. **Prices exist only for survivors, month-end, 2014 on** (the approved monthly raw download).  `ev_fcf_multiple` and `ptbv_of_rote` are measured on survivors with a price; share-class companies are read at the largest-cap ticker.  No delisted price exists, so these two references carry a survivor bias that is not correctable here.
4. **No EDGAR acceptance timestamps in the store**: the cut rule is the filing date (conservative).
5. **Extractor coverage.**  Of operating company-years in the 2025 vintage 74% have revenue, 65% an operating margin, 46% a ROIC and 39% a 3-year growth; the rest are shells, filers without those lines, or companies with too short a record.  Nothing is imputed.
6. **Non-USD reporters** (0.6-3% of operating observations) are carried in their own units and have no size cell.
7. **`family_not_built`** (REITs, shells, holding companies) is classified and excluded.
8. **`ronic_fade` and `excess_fade` are proxies**: the retention of the excess of ROIC (ROTE) over the population median in the vintage, because the priors do not know the cost of capital.
9. **Survivorship is large and is reported, not removed**: 41-59% of the company-years in a vintage belong to companies that later stopped filing (the archive holds many small shells); the tables are shown with and without them where the brief asks (g_terminal, shrinking-company persistence).
"""
