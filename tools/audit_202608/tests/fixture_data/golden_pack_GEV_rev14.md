# DATA PACK - GEV

## SECTION 0 - HOW TO READ THIS PACK

- `not available` means WE DO NOT HOLD THIS VALUE. It never means zero. A filed zero prints as `$0.000B`.
- `[Filed]` = reported to the SEC by the company. `[Arithmetic]` = exact arithmetic on filed values, with the window stated. `[Aggregator]` = a third-party vendor's restatement or estimate: useful, but not a filing, and its period is given where we know it.
- Money is in billions of the reporting currency unless a line says otherwise.
- Nothing here was verified by the code that assembled it. This is what our systems hold, with their known defects declared.

**Series continuity warning - read this before relying on any multi-year trend.** Each column is assembled from whichever XBRL tag the company filed that year, and companies change tags. Our extract does NOT record which tag produced each number, so a change of reporting basis is indistinguishable here from a change in the business. A large step between adjacent years that never reverts is far more often a basis change than an event. Worked example, live in this dataset: Philip Morris shows revenue $73.91B in FY2015 and $26.68B in FY2016 - a 64% collapse that never happened. The company switched from reporting revenue including excise taxes to excluding them. Verify any step you intend to lean on; do not treat one as a business event on this pack's word alone.

## SECTION 1 - IDENTITY & TAXONOMY
- Ticker: GEV | Sector: Industrials | Canonical Industry: Specialty Industrial Machinery
- Macro Strategic Cluster (1 of 24): Unknown
- Primary Archetype Category: compounder_general (Deconstruct into constituent value drivers per Pillar 1)
- Fiscal year ends: 2025-12-31   [derived from fundamentals_ttm.fy_leg_end]
- Rows below are labelled by FISCAL year, not calendar year.

## SECTION 1.5 - MACRO STATE & COST OF CAPITAL ANCHORS   [Primary Macro Context]
- MRI Capital-Market Anchors Status: as of 2026-09-23 | degraded: False | reasons: none
- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): 5.01%  [MRI anchor, as of 2026-09-23]
- Real 10-Year US Treasury Yield: 2.68%  [MRI anchor]
- 10-Year Breakeven Inflation Rate: 2.34%  [MRI anchor]
- Implied Equity Risk Premium (ERP): 4.35%  [MRI anchor]
- Implied Cost of Equity: 9.36%  [MRI anchor]
- Sector Cost of Equity Loading (industrials): 0.868x  [MRI anchor]
- COE ANCHOR for this name: rf 5.01% + adjusted loading 0.912× (Blume: 0.67 × raw 0.868 + 0.33) × implied ERP 4.35% = 8.98%  (asof 2026-09-23, source: MRI cost-of-capital anchor)
- Long-run nominal growth anchor for terminal_g: 3.75%  (asof 2026-09-23)
- 10Y-2Y Treasury Yield Spread (Curve Slope) [macro_state.json]: not available
- Investment Grade Credit Spread (BAA - 10Y) [macro_state.json]: not available
- High Yield Option-Adjusted Spread (OAS) [macro_state.json]: not available
- Current Macro Regime: Probabilities: [goldilocks 0.287, reflation 0.243, tightening 0.182, stagflation 0.174, recession 0.115] | headline goldilocks (margin 0.044 — contested)  [as of 2026-09-01]
- **MANDATE:** Use the verified 10-Year Treasury yield above (5.01%) as your base risk-free rate Rf for WACC. DO NOT search the web for Treasury yields or cost of capital anchors; they are verified above.
- **COE MANDATE:** Use `coe_used` within +-150 bp of the COE ANCHOR above (8.98%), or declare `coe_source: "own"` with a `coe_adjustment_reason`. Vendor beta (SECTION 2) is context only, never the input.
- **COST OF CAPITAL & CAPITALIZATION ANCHOR:** Derive terminal multiples from net capitalization rates (1 / [WACC - g]) and verified peer comps; do not force artificial multiple caps.
- [Arithmetic] DEFAULT EXIT MULTIPLE (net capitalization rate at the anchors): (1 + 3.75%) / (8.98% − 3.75%) = 19.86× the final-year cash flow: the multiple consistent with the terminal_g default. At another rate (the Bear's wider rate) the desk prints the scenario's own as implied_terminal_ev_fcf_gordon. A multiple whose implied terminal growth (exit_implied_terminal_g) is more than 0.5 points from the terminal_g default needs terminal_reason.

## SECTION 1.6 - STATE OF THE WORLD   [dated facts, not a forecast]

- MRI regime probability vector (as of 2026-09-01): [goldilocks 0.287, reflation 0.243, stagflation 0.174, recession 0.115, tightening 0.182] | headline goldilocks (margin 0.044 - contested)
- Active shocks (S4 register): none active  (as of 2026-09-22)
- Risk flag `elevated_volatility_ahead`: inactive - Expect higher market turbulence over the next 3 months. No evidence of lower returns or deeper drawdowns.  (as of 2026-09-22)
- Nominal 10-Year Treasury yield: 5.01%  (as of 2026-09-23)
- Real 10-Year Treasury yield: 2.68%  (as of 2026-09-23)
- 10-Year breakeven inflation: 2.34%  (as of 2026-09-23)
- Inflation trend: CPI YoY 3.35%, PCE YoY 3.70%  (as of 2026-09-23)
- WORLD NEWS: not available — MRI news feed unavailable this run (no live digest and no usable cache)

## SECTION 2 - MARKET   [Aggregator - vendor quote as of 2026-09-10 15:23]
- Price: $951.04
- Shares outstanding: 266,333,600   [source: vendor financials, as of 2026-09-10 15:23]
- Market cap: $253.294B
- Beta: 0.967   [Aggregator - the vendor does not state its window or benchmark. No RS2 code consumes beta; it is here only if you want to build your own cost of equity.]

**The three figures below are the VENDOR's restatement of the last annual report - not live, and not our SEC extract. The filed series is in SECTION 6.**
- Total cash (vendor): $8.848B
- Total debt (vendor): $1.172B   [our filed extract maps LONG-TERM debt only, so the two legitimately differ - and neither is a complete debt figure]
- Stock-based compensation (vendor): not available   [the period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. Prefer the filed per-year SBC series in SECTION 5 where it is present]

## SECTION 2.5 - PRICE ACTION (facts, not a valuation input)   [Arithmetic on price history, as of 2026-09-10 15:23]
- 12-1 month return: not available
- 6-month return: not available
- 1-month return: not available
- Distance from 52-week high (monthly proxy (unlabelled by the source)): not available
- Above/below 200-day mean, and its slope: not available
- Relative strength vs cluster ETF, 3-month: not available
- Relative strength vs IWM, 3-month: not available
- Realised volatility, 60-day: not available
- Regime-shift flags: none
- mom_break: not available
- Sector-neutral momentum z: not available
- Universe momentum z: not available

These are facts about price and are not a valuation input.

## RECENT COMPANY NEWS   [SearXNG news search (Reuters, Bing News), last 30 days, fetched 2026-09-27; third-party claims — the five most recent carry their opening text, read by code from the page shown after the arrow]
- The stock moved not available in 1 month and not available in 6 months (SECTION 2.5).
- no news returned (errors: stubbed)

## CATALYST BRIEF   [not available — no discovery run today]

## SECTION 3 - TRAILING TWELVE MONTHS   [Filed - SEC 10-Q derived; through 2026-06-30, filed 2026-07-22]
- Revenue: $41.367B
- Net income: $9.529B
- Operating cash flow: $14.139B
- Capital expenditure: $1.701B
- Free cash flow: $12.438B
- Depreciation & amortisation: not carried in the TTM extract for ANY name (the TTM build maps five fields only). Use the fiscal-year series in SECTION 5.
- [Arithmetic] Net income minus operating cash flow: $-4.610B
- [Arithmetic] OWNER EARNINGS (default base_cf): TTM net income $9.529B + D&A (FY2025) $0.853B − TTM capex $1.701B = $8.681B. Stock compensation is already expensed in net income, so it is counted once (sbc_treatment "deducted_in_cf"); working-capital swings are excluded. Net income is after interest, so this is an equity flow: value it in the equity frame. Use this as base_cf unless base_cf_reason states why another base is more representative.
- [Arithmetic] CASH BASIS (alternative base_cf): TTM operating cash flow $14.139B − TTM capex $1.701B − stock compensation (FY2025) $0.257B = $12.181B. Includes working-capital swings and, like every flow here, is after interest; declare base_cf_basis "other" with base_cf_reason if you use it.
- CASH-FLOW QUALITY: TTM operating cash flow exceeds net income + D&A by $3.757B (36%). That gap is working capital — customer prepayments, deposits or collection timing. It recurs only while advance bookings keep growing: count it as recurring owner cash flow only if you show it is structural to the business (deposits that grow with bookings), and never extrapolate a one-off swing. A base built on TTM OCF or FCF (including the CASH BASIS line) includes it; the OWNER EARNINGS default does not.
- EARNINGS QUALITY: in FY2025 net income ($4.884B) exceeded operating income ($1.388B) — non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not switch to an older fiscal year or to another base because of this line alone.

## SECTION 4 - QUARTERLY   [Filed - 10-Q; all 10 quarters we hold, oldest first]
| period end | revenue | net income | gross profit | YoY revenue | YoY net income |
| --- | --- | --- | --- | --- | --- |
| 2024-03-31 | $7.260B | $-0.130B | $1.150B | not available | not available |
| 2024-06-30 | $8.204B | $1.294B | $1.702B | not available | not available |
| 2024-09-30 | $8.913B | $-0.096B | $1.109B | not available | not available |
| 2024-12-31 | $10.559B | $0.484B | $2.123B | not available | not available |
| 2025-03-31 | $8.032B | $0.254B | $1.470B | +10.6% | not available |
| 2025-06-30 | $9.111B | $0.514B | $1.846B | +11.1% | -60.3% |
| 2025-09-30 | $9.969B | $0.452B | $1.897B | +11.8% | not available |
| 2025-12-31 | $10.956B | $3.664B | $2.322B | +3.8% | +657.0% |
| 2026-03-31 | $9.339B | $4.745B | $1.781B | +16.3% | +1768.1% |
| 2026-06-30 | $11.104B | $0.668B | $2.360B | +21.9% | +30.0% |

## SECTION 5 - FISCAL-YEAR INCOME & CASH FLOW   [Filed - SEC companyfacts; all 4 years we hold]
| FY | revenue | gross profit | operating income | net income | OCF | capex | FCF | D&A | SG&A | interest expense | SBC | cash basis [Arithmetic] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | $29.654B | $3.458B | $-2.881B | $-2.736B | $-0.114B | $0.513B | $-0.627B | $1.797B | $5.360B | not available | not available | not available |
| 2023 | $33.239B | $4.818B | $-0.923B | $-0.438B | $1.186B | $0.744B | $0.442B | $0.964B | $4.845B | not available | not available | not available |
| 2024 | $34.935B | $6.085B | $0.471B | $1.552B | $2.583B | $0.883B | $1.700B | $1.172B | $4.632B | not available | $0.155B | $1.545B |
| 2025 | $38.068B | $7.535B | $1.388B | $4.884B | $4.987B | $1.277B | $3.710B | $0.853B | $4.949B | not available | $0.257B | $3.453B |

- `SBC` is stock-based compensation as filed, per fiscal year. It is a real expense that is added back in OCF, so an owner-earnings figure that starts from OCF and does not subtract it is overstated. Use this series, not the single vendor scalar in SECTION 2, whose period is unreliable.

- `cash basis [Arithmetic]` = OCF minus capex minus SBC, on the filed values in this table and nothing else. Exact arithmetic, NOT a normalisation, and blank where any of the three inputs is absent.

## GROWTH BASE RATES   [Measured from our own fundamentals_history.json corpus]
- Latest annual revenue: $38.068B (FY2025)  ->  size bucket $10-50B
- 5y sustained growth, this size bucket: not available
- 10y sustained growth, this size bucket: not available
- Given the growth just delivered (+9.0% YoY revenue): outside the measured bucket range (15-25%, 25-40%, 40-70%, >70%) - no conditional table applies.
- **MANDATE:** stage-1 or fade growth above the p90 for this size bucket requires dated, company-specific evidence (e.g. signed capacity/backlog contracts, disclosed AI-demand commitments) - a growth rate alone is not evidence. This is a flag, not a veto.
- Survivorship caveat: this sample holds only companies that still exist today - failed and delisted companies are absent - so every rate above is biased upward. Source: our own screener corpus (fundamentals_history.json), not a published third-party table.

## SECTION 6 - FISCAL-YEAR BALANCE SHEET & CAPITAL STRUCTURE   [Filed, except columns marked [Arithmetic]]
**EXPLICIT LIQUIDITY & CAPITAL STRUCTURE CARD (Zero-Guess Anchor):**
- Total Cash & Cash Equivalents: $8.848B
- Total Debt (Filed / Vendor): $1.172B
- Net Liquidity Position: **Net Cash +$7.676B** (Cash + short-term investments minus Total Debt)
- [Arithmetic] NET DEBT (net_debt for the firm frame, which needs a pre-interest flow): total debt $1.172B − cash $8.848B − short-term investments $0.000B (none filed) = -$7.676B (negative = net cash). The equity frame (the default) takes no net_debt: the pack's flows are after interest, so the debt's cost is already in them, and cash counts through the interest it earns (which understates a very large cash pile; say so if it matters). In the firm frame use it as net_debt unless net_debt_reason says why.

### SECTION 6A - WORKING CAPITAL & OPERATING ASSETS
| FY | total assets | current assets | current liabs | working capital [Arithmetic] | change in WC [Arithmetic] | receivables | inventory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | not available | not available | not available | not available | not available | not available | not available |
| 2023 | $46.121B | $27.428B | $29.306B | $-1.878B | not available | not available | $8.253B |
| 2024 | $51.485B | $34.153B | $31.685B | $2.468B | $4.346B | $8.177B | $8.587B |
| 2025 | $63.016B | $40.216B | $40.972B | $-0.756B | $-3.224B | $9.803B | $10.429B |

### SECTION 6B - CAPITAL STRUCTURE, DEBT & EQUITY
| FY | cash | long-term debt | total liabs | equity | retained earnings | wtd-avg shares |
| --- | --- | --- | --- | --- | --- | --- |
| 2022 | $2.067B | not available | not available | $11.607B | not available | 274,000,000 |
| 2023 | $1.551B | not available | $37.741B | $8.380B | $0.000B | 274,000,000 |
| 2024 | $8.205B | not available | $40.892B | $10.593B | $1.611B | 278,000,000 |
| 2025 | $8.848B | $1.172B | $50.720B | $12.296B | $6.154B | 276,000,000 |

- `working capital` = current assets minus current liabilities. `change in WC` is the year-over-year difference of that.
- `long-term debt` is LONG-TERM ONLY; vendor total debt is given in the card above.
- `wtd-avg shares` is the weighted-average share count as filed and is **NOT SPLIT-ADJUSTED**.

**WORKING CAPITAL FLOAT & CUSTOMER PREPAYMENT NOTICE:**
- When customers make large advance down-payments or slot reservations (surging contract liabilities/deferred revenue), operating cash flow (OCF) surges temporarily from working-capital float. Do NOT treat this one-off prepayment float as recurring owner cash flow. Credit what it secures (capacity lock-in, a service or parts annuity) ONLY where the filings show the backlog or installed base behind it - cite the filing and the figure (charter v3.1 mandate 2).
- `wtd-avg shares` VERIFIED DILUTED for FY2025: our 276,000,000 matches the filed diluted count exactly (basic was 272,000,000).
- `capex` AGREES with the vendor for this company ($1.277B vs $1.277B), so the definitional gap below does not bite here.

### SECTION 6C - DETAILED DEBT COMPONENTS & INVESTMENTS   [Filed. Columns absent for this company are omitted entirely rather than shown empty]
| FY | current portion | short-term borrowings | finance leases | operating leases |
| --- | --- | --- | --- | --- |
| 2022 | not available | not available | not available | not available |
| 2023 | $0.145B | $0.145B | $0.311B | $0.718B |
| 2024 | $0.060B | $0.060B | $0.266B | $0.725B |
| 2025 | $0.063B | $0.063B | $0.278B | $0.843B |

- **WE DO NOT KNOW WHETHER THESE COLUMNS OVERLAP, SO WE DO NOT SUM THEM.** Which XBRL tag produced each number is not recorded (see SECTION 0), and the two long-term columns are measurably not interchangeable: across the live book they are identical on 72 of the 80 companies that carry both and disagree on 8, in one case by a factor of 650 (Marriott files $0.023B under one tag and $14.995B under the other). `current portion` and `short-term borrowings` agree on only 10 of the 35 names carrying both. So a total-debt figure is NOT provided here: adding these cells would double-count on most names, and picking one tag per company is a judgment call. YOU decide which components belong in your net-debt figure, and say which you used.
- The vendor's own total-debt scalar in SECTION 2 is an independent cross-check built on a different definition. Where it disagrees with every column here, treat the discrepancy as unresolved rather than picking the number that suits the case.
- Investments columns are securities held outside `cash`. Omitting them from net debt overstates leverage; on this book they run a median 32% of the cash balance.

## SECTION 7 - FILING-DERIVED QUALITY MEASURES   [Arithmetic on filed values; each line states its window; fiscal year 2025]
- Piotroski F-score: 6 out of 8 checks WE WERE ABLE TO EVALUATE (the denominator is what our data supported, not the standard 9)
- Accruals ratio: -0.0018   (accrual share of earnings; more positive means more of the reported profit is not yet cash)
- Net share issuance, 1 year: -0.7%   |   3-year CAGR: +0.2%   (negative = net buyback)
- Operating margin, latest: +3.6%   |   median over 4 years: -0.7%
- Revenue CAGR, trailing 5 fiscal years: not available
- Years of history available: 4
- Share-count split suspected in the series: False

The Beneish M-score is deliberately omitted: it imputes absent inputs and then publishes a score, which would present a guess as a measurement.

## SECTION 8 - CONSENSUS & MULTIPLES   [Aggregator, fetch date NOT RECORDED - age unknown, treat as potentially stale]
- Trailing P/E: not available   |   P/B: not available   |   PEG: not available   [trailing; the vendor does not state the period]
- Return on equity: not available   |   gross margin: not available   |   operating margin: not available   |   dividend yield: not available   [vendor-computed, expressed as fractions not percents]
- CONSENSUS ESTIMATES: not available — enrich record missing
- CONSENSUS-IMPLIED VALUE: not available — no consensus estimates

## SECTION 8.5 - PEER CONTEXT   [Aggregator, context not an anchor]
- Fields checked in `stocks.json`: trailing P/E (`peRatio`) - not available; EV/EBITDA - no field of that name exists in `stocks.json`'s per-ticker record. Only fields found usable are printed as values below.
- Cluster peers' trailing P/E: not available
- Cluster peers' EV/EBITDA: not available
- MRI sector trailing-P/E band (industrials): median 22.398x | p25 11.609x | p75 39.063x   [regime state: credit loose, growth neutral, inflation neutral, rate_band high, as of 2026-09-23]

## GUIDANCE & CONSENSUS   [company's own earnings release from SEC EDGAR, then research-brief claims]
COMPANY'S OWN WORDS: not available — no 8-K Item 2.02 on or before 2026-09-27

Research-brief rows (claims by another model, check before relying):
not available — research did not return dated guidance
- **MANDATE:** stage-1 years 1-2 start from guidance/consensus above when available; a deviation requires `guidance_deviation_reason` in the SECTION 12 contract.

## SECTION 12 - WHAT WE DO NOT HOLD
Declared so you can source it yourself or carry the uncertainty, instead of assuming it.

- **Segment revenue and margin in raw SEC XBRL: WE HAVE NONE.** Verified for this company: of the 3,767 fact rows in raw SEC companyfacts, ZERO carry a dimension. Segment breakdowns (e.g. Power, Wind, Electrification), contracted backlog, and management guidance are retrieved and structured in SECTION 11.
- **Marketable securities and short-term investments: NOT EXTRACTED for this company.** Many companies hold much of their liquidity here rather than in cash, so the `cash` column in SECTION 6 and the vendor cash figure in SECTION 2 can both understate liquid assets badly. The data is filed and sits in the source we download; it is not mapped for this name.
- **Stock-based compensation per year: HELD**, 2 year(s) of the 4 years in SECTION 5 (2024-2025) - in the SBC column of SECTION 5.
- **Effective tax rate: WITHHELD, and for this company the inputs are PROVABLY BROKEN.** Net income + tax does not equal pre-tax income, by more than 5%, in FY2023. Our pre-tax field admits a US-domestic-only tag. Do not reconstruct a tax rate from those years.
- **Debt components beyond long-term debt: HELD**, 3 year(s) of the 4 years in SECTION 5 (2023-2025) - in SECTION 6C - but WHETHER THEY OVERLAP IS NOT KNOWN, so no total debt is computed for you. Read the note under that table.
- **Which XBRL tag produced each number: NOT RECORDED.** See the continuity warning in SECTION 0.
- **Analyst Q&A from earnings calls: NOT HELD.** See SECTION 10.
