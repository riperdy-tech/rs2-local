# Decisions for the operator, 2026-10-07 morning

Everything below is free, public data, and nothing is downloaded without your OK. Sizes come from the servers' headers,
checked last night; download nothing else.

## 1. Downloads (one approval each, or "all")

| # | What | Source | Size | Why it matters |
|---|---|---|---|---|
| D1 | SEC bulk `submissions.zip` | sec.gov `Archives/edgar/daily-index/bulkdata/submissions.zip` | 1.57 GB | The exact acceptance time of every filing (the 16:00 ET rule; without it a filing made on the valuation date is unused) and the delisting events (Form 25/15, 8-K items) for every company, including delisted ones. |
| D2 | EDGAR filing headers for annual reports | sec.gov, one small header per 10-K/20-F (about 100,000 at 10 requests a second, about 3 hours) | about 0.5 GB | The industry code (SIC) and company name as they were at each date. Without it, history uses today's SIC, stamped. |
| D3 | Merger, 8-K and bankruptcy-plan texts, only for delisting events found via D1 | sec.gov, per event | a few hundred MB | What shareholders received when a company left: the takeover price, or zero in bankruptcy. Without it those outcomes are "unobservable" and reported under three bounds. |
| D4 | SEC Financial Statement Data Sets, 2009 Q2 to 2026 Q3 | sec.gov `files/dera/data/financial-statement-data-sets/YYYYqN.zip` | about 66 MB per quarter, about 4.5 GB in total | Figures companies tag only by segment or dimension, such as APA's revenue, which plain companyfacts lacks. |
| D5 | Yahoo daily unadjusted closes and corporate actions (`yfinance`, `auto_adjust=False`) for every filer with a ticker | Yahoo Finance | about 7,000 tickers, a few hundred MB | **The blocker.** Gate 1 needs the real traded price on each valuation date. Our only local file is adjusted, month-end, and holds today's listings only. Yahoo lacks most delisted stocks; that gap is measured and reported. |

**Recommendation:** approve all five.
- **D5** blocks gate 1's holdout.
- **D1** is next most important.
- **D2–D4** improve accuracy and remove stamped compromises.

## 2. Gate 1 pass bars (`REGISTRATION_gate1_DRAFT.md`, section 7)

These are seven stated conventions to approve or change. They must be fixed before any holdout result exists.
1. Market cap ≥ $300M at the date for the gate's universe; smaller companies are reported separately.
2. Quarter-end valuation dates.
3. The top-minus-bottom quintile spread ≥ +3 percentage points a year.
4. No more than 15% of stocks below 0.4× or above 2.5× their price.
5. Each company type's share of those extremes within 10 points of its share of the universe.
6. The new engines' spread of value ÷ price, as an IQR of ln(value ÷ price), at least 0.30. This replaces "half the old
   engine's": the old engine cannot be computed for past dates.
7. Development dates re-set to 2019–2021 (plus 2022 for forecast accuracy only), so development never touches the
   2023–2024 test years.

## 2b. Overnight result you should know
- **Development round 1 of the new code-only engines failed structurally** (provisional figures): growth and
  operating companies at a median of 0.14× price, commodity names negative.
- **Causes:**
  - one of my own rules (a margin-spread rescale), now withdrawn;
  - terminal growth drawn from the wrong statistic;
  - a noisy return-on-capital measure;
  - pre-profit biotechs and regulated utilities in scope.
- **Round 2:** the fixes moved operating companies from 0.14× to about 0.70× price, measured with one refusal rule
  switched off as a diagnostic.
  - Uncertainty bands of a fixed width for every company made that rule refuse most companies.
  - Financials came out too high (2.5×) from a too-low cost of equity.
- **Round 3 (04:15–05:00):** the engine's cheap-vs-expensive ranking predicts 12-month excess returns (B1 and
  B2 pass: +6.8 points top minus bottom quintile), and its forecasts beat the naive baseline (B4).
  - Levels still lean low: operating companies at a median of 0.50× price, 43% of stocks outside 0.4×–2.5×
    (B3 fails).
  - Suspected cause: Damodaran's risk premium assumes analysts' growth, while our cash flows use base rates.
  - A diagnostic is running. **A decision for you follows:** use a risk premium consistent with our own engine,
    or keep Damodaran's.
- All of this is development (2020–2021; 2019 lacks enough history) on
  month-end prices, so every figure is provisional; the real test waits for your price-download approval.

## 3. Flagged, not decided by me
- **The screener's ticker→CIK map is stale for APA** (it points at the old Apache filer), possibly others. A separate
  task chip is waiting for you to start or dismiss.
