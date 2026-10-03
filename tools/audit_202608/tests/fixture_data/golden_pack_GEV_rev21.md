# DATA PACK - GEV   (pack revision 21)

## DATA 0 - HOW TO READ THIS PACK
- `not available` (NA in tables) means we do not hold the value; it never means zero, and a filed zero prints 0.000. [Filed] = reported to the SEC by the company; [Arithmetic] = exact arithmetic on filed values, with the window stated; [Aggregator] = a vendor's restatement or estimate, not a filing. Money is in billions of the reporting currency unless a line or table header says otherwise. Nothing here was verified by the code that assembled it.
- Series continuity: each year's column comes from whichever XBRL tag the company filed that year, and we do not record which. A step between adjacent years that never reverts is far more often a change of reporting basis than an event: Philip Morris shows revenue $73.91B in FY2015 and $26.68B in FY2016 because excise taxes left the revenue line. Verify any step you lean on.

## DATA 1 - IDENTITY & TAXONOMY
- Ticker: GEV | Sector: Industrials | Canonical Industry: Specialty Industrial Machinery
- Macro Strategic Cluster (1 of 24): Unknown
- Primary Archetype Category: compounder_general (Deconstruct into constituent value drivers per Pillar 1)
- Fiscal year ends: 2025-12-31   [derived from fundamentals_ttm.fy_leg_end]
- Rows below are labelled by FISCAL year, not calendar year.

## DATA 1.5 - MACRO STATE & COST OF CAPITAL ANCHORS   [MRI anchors as of 2026-09-23, degraded: False, reasons: none; verified: do not search the web for them]
- Rates: rf (nominal 10y) 5.01% | real 10y 2.68% | breakeven 10y 2.34% | MRI universe premium (context; not used in the reference) 4.35% | MRI market cost of equity (context) 9.36% | sector cost-of-equity loading (industrials) 0.868x
- COE ANCHOR for this name: 8.98% = rf_eff 5.01% (the larger of rf 5.01% and the growth anchor 3.75%) + adjusted loading 0.912× (Blume: 0.67 × raw 0.868 + 0.33) × the market-consistent premium 4.35% (rs2 closure, as of 2026-09-20) | long-run nominal growth anchor 3.75% (asof 2026-09-23)
- Curve 10y-2y not available | IG spread (BAA - 10Y) not available | HY OAS not available
- Regime probabilities (as of 2026-09-01): goldilocks 0.287, reflation 0.243, tightening 0.182, stagflation 0.174, recession 0.115 | headline goldilocks, margin 0.044, contested

## DATA 1.6 - STATE OF THE WORLD   [dated facts, not a forecast]

- Active shocks (S4 register): none active  (as of 2026-09-22)
- Risk flag `elevated_volatility_ahead`: inactive - Expect higher market turbulence over the next 3 months. No evidence of lower returns or deeper drawdowns.  (as of 2026-09-22)
- Inflation trend: CPI YoY 3.35%, PCE YoY 3.70%  (as of 2026-09-23)
- WORLD NEWS: not available — MRI news feed unavailable this run (no live digest and no usable cache)

## DATA 2 - MARKET   [Aggregator - vendor quote as of 2026-09-10 15:23]
- Price: $951.04
- Shares outstanding: 266,333,600   [source: vendor financials, as of 2026-09-10 15:23]
- Shares dilution factor: 1.0081 = basic EPS 2.49 / diluted EPS 2.47 (quarter ended 2026-06-30); applied to the default at 1.05 or above (convertibles, options or warrants)
- Shares default: 266,333,600   [the desk's shares_diluted unless you pass another count with shares_reason]
- Market cap: $253.294B
- Beta: 0.967   [Aggregator - the vendor does not state its window or benchmark. No RS2 code consumes beta; it is here only if you want to build your own cost of equity.]

**The three figures below are the VENDOR's restatement of the last annual report - not live, and not our SEC extract. The filed series is in DATA 6.**
- Total cash (vendor): $8.848B
- Total debt (vendor): $1.172B   [our filed extract maps LONG-TERM debt only, so the two legitimately differ - and neither is a complete debt figure]
- Stock-based compensation (vendor): not available   [the period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. Prefer the filed per-year SBC series in DATA 5 where it is present]

## DATA 2.5 - PRICE ACTION (facts, not a valuation input)   [Arithmetic on price history, as of 2026-09-10 15:23]
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
- The stock moved not available in 1 month and not available in 6 months (DATA 2.5).
- no news returned (errors: stubbed)

## CATALYST BRIEF   [not available — no discovery run today]

## DATA 3 - TRAILING TWELVE MONTHS   [Filed - SEC 10-Q derived; through 2026-06-30, filed 2026-07-22; $B]
- Revenue 41.367 | net income 9.529 | operating cash flow 14.139 | capital expenditure 1.701 | free cash flow 12.438 | [Arithmetic] net income minus operating cash flow -4.610 | D&A: not carried in the TTM extract for any name; use DATA 5
- [Arithmetic] OWNER EARNINGS 8.681 = TTM net income 9.529 + D&A (FY2025) 0.853 − TTM capex 1.701. Stock compensation is already expensed in net income, so it is counted once (sbc_treatment "deducted_in_cf"); working-capital swings are excluded.
- [Arithmetic] CASH BASIS 12.181 = TTM operating cash flow 14.139 − TTM capex 1.701 − stock compensation (FY2025) 0.257. Includes working-capital swings.
- CASH-FLOW QUALITY: TTM operating cash flow exceeds net income + D&A by $3.757B (36%). That gap is working capital — customer prepayments, deposits or collection timing. It recurs only while advance bookings keep growing: count it as recurring owner cash flow only if you show it is structural to the business (deposits that grow with bookings), and never extrapolate a one-off swing. A base built on TTM OCF or FCF (including the CASH BASIS line) includes it; the OWNER EARNINGS default does not.
- EARNINGS QUALITY: in FY2025 net income ($4.884B) exceeded operating income ($1.388B) — non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not switch to an older fiscal year or to another base because of this line alone.

## DATA 4 - QUARTERLY   [Filed - 10-Q; all 10 quarters we hold, oldest first; $B]
| period end | revenue | net income | gross profit | YoY revenue | YoY net income |
| --- | --- | --- | --- | --- | --- |
| 2024-03-31 | 7.260 | -0.130 | 1.150 | not available | not available |
| 2024-06-30 | 8.204 | 1.294 | 1.702 | not available | not available |
| 2024-09-30 | 8.913 | -0.096 | 1.109 | not available | not available |
| 2024-12-31 | 10.559 | 0.484 | 2.123 | not available | not available |
| 2025-03-31 | 8.032 | 0.254 | 1.470 | +10.6% | not available |
| 2025-06-30 | 9.111 | 0.514 | 1.846 | +11.1% | -60.3% |
| 2025-09-30 | 9.969 | 0.452 | 1.897 | +11.8% | not available |
| 2025-12-31 | 10.956 | 3.664 | 2.322 | +3.8% | +657.0% |
| 2026-03-31 | 9.339 | 4.745 | 1.781 | +16.3% | +1768.1% |
| 2026-06-30 | 11.104 | 0.668 | 2.360 | +21.9% | +30.0% |

## DATA 5 - FISCAL-YEAR INCOME & CASH FLOW   [Filed - SEC companyfacts; all 4 years we hold; $B]
| FY | revenue | gross profit | operating income | net income | OCF | capex | FCF | D&A | SG&A | interest expense | SBC | cash basis [Arithmetic] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | 29.654 | 3.458 | -2.881 | -2.736 | -0.114 | 0.513 | -0.627 | 1.797 | 5.360 | NA | NA | NA |
| 2023 | 33.239 | 4.818 | -0.923 | -0.438 | 1.186 | 0.744 | 0.442 | 0.964 | 4.845 | NA | NA | NA |
| 2024 | 34.935 | 6.085 | 0.471 | 1.552 | 2.583 | 0.883 | 1.700 | 1.172 | 4.632 | NA | 0.155 | 1.545 |
| 2025 | 38.068 | 7.535 | 1.388 | 4.884 | 4.987 | 1.277 | 3.710 | 0.853 | 4.949 | NA | 0.257 | 3.453 |

- `SBC` is stock-based compensation as filed, per fiscal year. It is a real expense that is added back in OCF, so an owner-earnings figure that starts from OCF and does not subtract it is overstated. Use this series, not the single vendor scalar in DATA 2, whose period is unreliable.

- `cash basis [Arithmetic]` = OCF minus capex minus SBC, on the filed values in this table and nothing else. Exact arithmetic, NOT a normalisation, and blank where any of the three inputs is absent.

## GROWTH BASE RATES   [Measured from our own fundamentals_history.json corpus]
- Latest annual revenue: $38.068B (FY2025)  ->  size bucket $10-50B
- 5y sustained growth, this size bucket: not available
- 10y sustained growth, this size bucket: not available
- Given the growth just delivered (+9.0% YoY revenue): outside the measured bucket range (15-25%, 25-40%, 40-70%, >70%) - no conditional table applies.
- Survivorship caveat: this sample holds only companies that still exist today - failed and delisted companies are absent - so every rate above is biased upward. Source: our own screener corpus (fundamentals_history.json), not a published third-party table.

## DATA 6 - FISCAL-YEAR BALANCE SHEET & CAPITAL STRUCTURE   [Filed, except columns marked [Arithmetic]; $B]
**EXPLICIT LIQUIDITY & CAPITAL STRUCTURE CARD (Zero-Guess Anchor):**
- Total Cash & Cash Equivalents: $8.848B
- Total Debt (Filed / Vendor): $1.172B
- Net Liquidity Position: **Net Cash +$7.676B** (Cash + short-term investments minus Total Debt)
- [Arithmetic] NET DEBT: total debt $1.172B − cash $8.848B − short-term investments $0.000B (none filed) = -$7.676B (negative = net cash).

### DATA 6A - WORKING CAPITAL & OPERATING ASSETS   [$B]
| FY | total assets | current assets | current liabs | working capital [Arithmetic] | change in WC [Arithmetic] | receivables | inventory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | NA | NA | NA | NA | NA | NA | NA |
| 2023 | 46.121 | 27.428 | 29.306 | -1.878 | NA | NA | 8.253 |
| 2024 | 51.485 | 34.153 | 31.685 | 2.468 | 4.346 | 8.177 | 8.587 |
| 2025 | 63.016 | 40.216 | 40.972 | -0.756 | -3.224 | 9.803 | 10.429 |

### DATA 6B - CAPITAL STRUCTURE, DEBT & EQUITY   [$B]
| FY | cash | long-term debt | total liabs | equity | retained earnings | wtd-avg shares |
| --- | --- | --- | --- | --- | --- | --- |
| 2022 | 2.067 | NA | NA | 11.607 | NA | 274,000,000 |
| 2023 | 1.551 | NA | 37.741 | 8.380 | 0.000 | 274,000,000 |
| 2024 | 8.205 | NA | 40.892 | 10.593 | 1.611 | 278,000,000 |
| 2025 | 8.848 | 1.172 | 50.720 | 12.296 | 6.154 | 276,000,000 |

- `working capital` = current assets minus current liabilities. `change in WC` is the year-over-year difference of that.
- `long-term debt` is LONG-TERM ONLY; vendor total debt is given in the card above.
- `wtd-avg shares` is the weighted-average share count as filed and is **NOT SPLIT-ADJUSTED**.

**WORKING CAPITAL FLOAT & CUSTOMER PREPAYMENT NOTICE:**
- When customers make large advance down-payments or slot reservations (surging contract liabilities/deferred revenue), operating cash flow (OCF) surges temporarily from working-capital float. Do NOT treat this one-off prepayment float as recurring owner cash flow. Credit what it secures (capacity lock-in, a service or parts annuity) ONLY where the filings show the backlog or installed base behind it - cite the filing and the figure (charter v3.1 mandate 2).
- `wtd-avg shares` VERIFIED DILUTED for FY2025: our 276,000,000 matches the filed diluted count exactly (basic was 272,000,000).
- `capex` AGREES with the vendor for this company ($1.277B vs $1.277B), so the definitional gap below does not bite here.

### DATA 6C - DETAILED DEBT COMPONENTS & INVESTMENTS   [Filed. Columns absent for this company are omitted entirely rather than shown empty; $B]
| FY | current portion | short-term borrowings | finance leases | operating leases |
| --- | --- | --- | --- | --- |
| 2022 | NA | NA | NA | NA |
| 2023 | 0.145 | 0.145 | 0.311 | 0.718 |
| 2024 | 0.060 | 0.060 | 0.266 | 0.725 |
| 2025 | 0.063 | 0.063 | 0.278 | 0.843 |

- **WE DO NOT KNOW WHETHER THESE COLUMNS OVERLAP, SO WE DO NOT SUM THEM.** Which XBRL tag produced each number is not recorded (see DATA 0), and the two long-term columns are measurably not interchangeable: across the live book they are identical on 72 of the 80 companies that carry both and disagree on 8, in one case by a factor of 650 (Marriott files $0.023B under one tag and $14.995B under the other). `current portion` and `short-term borrowings` agree on only 10 of the 35 names carrying both. So a total-debt figure is NOT provided here: adding these cells would double-count on most names, and picking one tag per company is a judgment call. YOU decide which components belong in your net-debt figure, and say which you used.
- The vendor's own total-debt scalar in DATA 2 is an independent cross-check built on a different definition. Where it disagrees with every column here, treat the discrepancy as unresolved rather than picking the number that suits the case.
- Investments columns are securities held outside `cash`. Omitting them from net debt overstates leverage; on this book they run a median 32% of the cash balance.

## DATA 7 - FILING-DERIVED QUALITY MEASURES   [Arithmetic on filed values; each line states its window; fiscal year 2025]
- Piotroski F-score: 6 out of 8 checks WE WERE ABLE TO EVALUATE (the denominator is what our data supported, not the standard 9)
- Accruals ratio: -0.0018   (accrual share of earnings; more positive means more of the reported profit is not yet cash)
- Net share issuance, 1 year: -0.7%   |   3-year CAGR: +0.2%   (negative = net buyback)
- Operating margin, latest: +3.6%   |   median over 4 years: -0.7%
- Revenue CAGR, trailing 5 fiscal years: not available
- Years of history available: 4
- Share-count split suspected in the filed series: False. After the last filing: none detected.

The Beneish M-score is deliberately omitted: it imputes absent inputs and then publishes a score, which would present a guess as a measurement.

## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator, fetch date NOT RECORDED - age unknown, treat as potentially stale]
- Trailing P/E: not available   |   P/B: not available   |   PEG: not available   [trailing; the vendor does not state the period]
- Return on equity: not available   |   gross margin: not available   |   operating margin: not available   |   dividend yield: not available   [vendor-computed, expressed as fractions not percents]
- CONSENSUS ESTIMATES: not available — enrich record missing
- CONSENSUS-IMPLIED VALUE: not available — no consensus estimates

## DATA 8.5 - PEER CONTEXT   [Aggregator, context not an anchor]
- Fields checked in `stocks.json`: trailing P/E (`peRatio`) - not available; EV/EBITDA - no field of that name exists in `stocks.json`'s per-ticker record. Only fields found usable are printed as values below.
- Cluster peers' trailing P/E: not available
- Cluster peers' EV/EBITDA: not available
- MRI sector trailing-P/E band (industrials): median 22.398x | p25 11.609x | p75 39.063x   [regime state: credit loose, growth neutral, inflation neutral, rate_band high, as of 2026-09-23]

## GUIDANCE & CONSENSUS   [company's own earnings release from SEC EDGAR, then research-brief claims]
COMPANY'S OWN WORDS: not available — no 8-K Item 2.02 on or before 2026-09-27

Research-brief rows (claims by another model, check before relying):
not available — research did not return dated guidance

## PRIMARY SOURCES   [the company's own SEC filings, verbatim; cite as PRIMARY P#]
Each item below is a company filing's text as filed (HTML cleaned, nothing paraphrased); a quoted line starts with `> `. Cite an item as source `PRIMARY P#` (for example `PRIMARY P1`) with the quote copied exactly from its text.

[P1] 8-K Item 2.02 earnings release (EX-99), filed 2026-07-22, accession 0001996810-26-000147, period Q2 2026, https://www.sec.gov/Archives/edgar/data/1996810/000199681026000147/gevpressrelease2q26.htm
> 1 Defined as remaining performance obligation (RPO) *Non-GAAP Financial Measure
> Page 1
> GE Vernova reports second quarter 2026 financial results and raises 2026 financial guidance Strong performance with significant orders and backlog growth, margin expansion, and cash generation Second Quarter 2026 Highlights: •Orders of $24.2B, +88% organically led by robust growth in Power and Electrification •Backlog1 growth of $13.0B sequentially from equipment and services •Gas Power equipment backlog and slot reservation agreements grew from 100 to 116 GW; now anticipate reaching at least 125 GW by year-end 2026 •Revenue of $11.1B, +22%, +12% organically* led by Power and Electrification •Net income of $0.6B; net income margin of 5.8% •Adjusted EBITDA* of $1.2B; adjusted EBITDA margin* of 11.3%, up +340 basis points organically* •Cash from operating activities of $5.5B; free cash flow* of $5.1B, more than all of 2025 •$13.1B cash balance; $3.9B in capital returned to shareholders year-to-date CAMBRIDGE, Mass., (July 22, 2026) – GE Vernova Inc.
> (NYSE: GEV), a unique industry leader enabling the world to electrify to thrive and decarbonize, today reported financial results for the second quarter ending June 30, 2026. “We delivered strong financial results in the second quarter as global demand for our products and solutions continues to grow. With a backlog of $176 billion, continued revenue growth and margin expansion, and significant free cash flow generation, GE Vernova’s momentum is building, and we are raising our 2026 financial guidance,” said GE Vernova CEO Scott Strazik. “We now expect to have at least 125 GW of gas equipment under contract by year-end 2026.
> To meet this demand, we remain on track to deliver 20 GW of annual gas turbine output in the third quarter of 2026, with 24 GW in 2028, and we are implementing actions to produce 30 GW in 2030. We are also seeing continued demand growth in Electrification, with data center orders reaching over $5 billion year-to-date, more than double our 2025 total. I am proud of how our team is executing with discipline, and I am confident there is substantial value creation ahead.” In the quarter, orders of $24.2 billion increased +88% organically, with robust equipment growth in Power and Electrification, and services growth in all segments.
> Revenue of $11.1 billion was up +22%, +12% organically*, led by equipment growth at Electrification and Power, along with higher services, partially offset by equipment at Wind. Margins expanded significantly from higher volume, price, and productivity. Free cash flow* of $5.1 billion increased $4.9 billion, primarily due to higher positive benefits from working capital and stronger adjusted EBITDA*. Power •Orders of $16.7 billion increased +134% organically and revenues of $5.5 billion increased +14% on a U.S. GAAP basis and organically* led by Gas Power equipment. Segment EBITDA margin grew +240 basis points, +320 basis points organically*.
> •Signed 20 gigawatts (GW) of new gas equipment contracts, including 18 GW of slot reservation agreements and 2 GW of orders. Converted 10 GW of existing slot reservation agreements to orders and shipped 3 GW of equipment; resulting in backlog growth from 44 to 53 GW and an increase in slot reservation agreements from 56 to 63 GW. Electrification •Orders of $6.3 billion increased +66% organically, driving a book-to-bill ratio of approximately 1.7, with continued strong demand for grid equipment. Revenues of $3.6 billion increased +68%, +29% organically*, driven by Power Transmission and Grid Systems Integration. Segment EBITDA margin grew +390 basis points, +700 basis points organically*.
> •Increased equipment backlog to $40.6 billion, up $16.6 billion, or 69% year-over-year, including $5 billion from Prolec GE. Wind •Orders of $1.2 billion decreased (40)% organically due to lower equipment at Onshore Wind. Revenues of $2.0 billion decreased (10)%, (11)% organically*, primarily driven by equipment at Onshore Wind as a result of soft orders in the first half of 2025. Segment EBITDA losses grew from lower Onshore Wind equipment volume and higher Offshore Wind project costs, partially offset by Onshore Wind services.
> [… 188 characters omitted …]
> Page 2
> [… 1,247 characters omitted …]
> •Funded $0.3 billion in research and development (R&D) spending, to advance breakthrough energy transition technologies, as part of its commitment to invest $5 billion in R&D from 2025 through 2028. "We had a strong first half of 2026 as we executed our financial strategy. Our backlog continued to expand driven by equipment growth at Power and Electrification, with healthy margins from favorable price and disciplined underwriting, and services growth at Power,” said GE Vernova CFO Ken Parks.
> “Given our significant free cash flow generation, we ended the quarter with a cash balance of $13.1 billion, up $4.3 billion in the year, even as we returned more capital to shareholders so far this year than in the full year of 2025 through our share repurchase actions and quarterly dividend payment. Based on our strong financial performance, we have increased our full year expectations for revenue and free cash flow.” 2026 Guidance GE Vernova is raising its 2026 financial guidance and now expects revenue of $45.5-$46.5 billion, up from $44.5-$45.5 billion, and free cash flow* of $11.5-$12.5 billion, up from $6.5-$7.5 billion; adjusted EBITDA margin* guidance remains 12%-14%.
> Segment guidance is: •Power: 18%-20% organic revenue* growth, up from 16%-18%, and 17%-19% segment EBITDA margin. •Electrification: Revenue of $14.5-$15.0 billion, inclusive of approximately $3.1 billion from Prolec GE, up from $14.0-$14.5 billion, inclusive of approximately $3.0 billion from Prolec GE, and 18%-20% segment EBITDA margin. •Wind: Organic revenue* down low-double digits and approximately $400 million of segment EBITDA losses. Total Company Results
> [… 918 characters omitted …]
> Page 3
> Results by Reporting Segment The following segment discussions and variance explanations are intended to reflect management’s view of the relevant comparisons of financial results. Effective January 1, 2026, GE Vernova realigned the reporting of certain of its business units within the Power, Electrification, and Wind segments. 2025 segment financial information can be accessed here. Power
> Three months ended June 30 | Six months ended June 30
> (Dollars in millions) | 2026 | 2025 | Year-on-Year | 2026 | 2025 | Year-on-Year
> Orders | $16,729 | $7,109 | 135% | $26,736 | $13,372 | 100%
> Revenues | $5,477 | $4,785 | 14% | $10,449 | $9,234 | 13%
> Cost of revenues(a) | $3,866 | $3,450 | $7,504 | $6,818
> Selling, general, and administrative expenses(a) | $472 | $462 | $918 | $930
> Research and development expenses(a) | $154 | $133 | $286 | $242
> Other segment (income)/expenses(b) | $(45) | $(46) | $(100) | $(59)
> Segment EBITDA | $1,031 | $785 | $245 | $1,842 | $1,303 | $539
> Segment EBITDA margin | 18.8% | 16.4% | 240 bps | 17.6% | 14.1% | 350 bps
> (a) Excludes depreciation and amortization expenses. (b) Primarily includes equity method investment income and other interest and investment income. Second Quarter 2026 Performance: Orders of $16.7 billion increased +134% organically, primarily from strength in Gas Power equipment, driven by higher volume and price, with 52 heavy-duty units, including 15 HA turbines, and 61 aeroderivative turbines. Services orders increased 12% organically, primarily driven by Nuclear Power and continued growth at Gas Power. Revenues of $5.5 billion increased +14% on a U.S. GAAP basis and organically*, led by aeroderivative volume and price, with services revenue growth at Nuclear Power and Gas Power. Segment EBITDA was $1.0 billion and segment EBITDA margin was 18.8%, up +240 basis points, +320 basis points organically*, primarily driven by higher volume and favorable price at Gas Power, partially offset by the impact of inflation. Electrification
> Three months ended June 30 | Six months ended June 30
> (Dollars in millions) | 2026 | 2025 | Year-on-Year | 2026 | 2025 | Year-on-Year
> Orders | $6,347 | $3,283 | 93% | $13,460 | $6,649 | 102%
> Revenues | $3,637 | $2,162 | 68% | $6,597 | $4,001 | 65%
> Cost of revenues(a) | $2,512 | $1,505 | $4,539 | $2,777
> Selling, general, and administrative expenses(a) | $341 | $306 | $694 | $636
> Research and development expenses(a) | $112 | $100 | $219 | $182
> Other segment (income)/expenses(b) | $1 | $(64) | $(56) | $(113)
> Segment EBITDA | $671 | $314 | $357 | $1,200 | $519 | $681
> Segment EBITDA margin | 18.4% | 14.5% | 390 bps | 18.2% | 13.0% | 520 bps
> (a) Excludes depreciation and amortization expenses. (b) Primarily includes equity method investment income and other interest and investment income. Second Quarter 2026 Performance: Orders of $6.3 billion increased +66% organically, due to continued strong demand for grid equipment with strength in North America. Revenues of $3.6 billion grew +68% on a U.S. GAAP basis, inclusive of Prolec GE, +29% organically*, primarily due to increased volume in switchgear and transformers at Power Transmission and in alternating current substation solutions and high voltage direct current solutions at Grid Systems Integration. Segment EBITDA was $0.7 billion and segment EBITDA margin was 18.4%, up +390 basis points, +700 basis points organically*, due to volume, productivity, and price at Power Transmission and Power Conversion & Storage. *Non-GAAP Financial Measure
> Page 4
> Wind
> Three months ended June 30 | Six months ended June 30
> (Dollars in millions) | 2026 | 2025 | Year-on-Year | 2026 | 2025 | Year-on-Year
> Orders | $1,249 | $2,063 | (39)% | $2,448 | $2,702 | (9)%
> Revenues | $2,026 | $2,245 | (10)% | $3,459 | $4,095 | (16)%
> Cost of revenues(a) | $2,123 | $2,226 | $3,772 | $4,066
> Selling, general, and administrative expenses(a) | $137 | $141 | $265 | $276
> Research and development expenses(a) | $34 | $40 | $70 | $73
> Other segment (income)/expenses(b) | $7 | $3 | $9 | $(8)
> Segment EBITDA | $(275) | $(165) | $(110) | $(657) | $(312) | $(346)
> Segment EBITDA margin | (13.6)% | (7.3)% | (630) bps | (19.0)% | (7.6)% | (1,140) bps
> (a) Excludes depreciation and amortization expenses. (b) Primarily includes equity method investment income and other interest and investment income. Second Quarter 2026 Performance: Orders of $1.2 billion decreased (40)% organically, driven by lower Onshore Wind equipment orders, primarily in North America. Revenues of $2.0 billion decreased (10)%, (11)% organically*, due to lower Onshore Wind equipment deliveries as a result of soft orders in the first half of 2025, partially offset by higher Onshore Wind services and higher Offshore Wind deliveries and installations. Segment EBITDA losses were $(0.3) billion and segment EBITDA margin was (13.6)%, down (630) basis points on a U.S. GAAP basis and organically*, primarily at Onshore Wind due to lower equipment deliveries and at Offshore Wind due to higher project costs, partially offset by lower costs at Onshore Wind services. *Non-GAAP Financial Measure
> [… 2,896 characters omitted …]
> ORGANIC REVENUES, EBITDA, AND EBITDA MARGIN BY SEGMENT (NON-GAAP)
> Revenue(a) | Segment EBITDA | Segment EBITDA margin
> For the three months ended June 30 | 2026 | 2025 | V% | 2026 | 2025 | V% | 2026 | 2025 | V bps
> Power (GAAP) | $5,477 | $4,785 | 14% | $1,031 | $785 | 31% | 18.8% | 16.4% | 240bps
> Less: Acquisitions | — | — | — | —
> Less: Business dispositions | — | — | — | —
> Less: Foreign currency effect | 33 | 4 | (9) | 27
> Power organic (Non-GAAP) | $5,444 | $4,781 | 14% | $1,040 | $758 | 37% | 19.1% | 15.9% | 320bps
> Electrification (GAAP) | $3,637 | $2,162 | 68% | $671 | $314 | F | 18.4% | 14.5% | 390bps
> [… 1,958 characters omitted …]
> 2026 GUIDANCE: POWER ORGANIC REVENUE* We cannot provide a reconciliation of the differences between the non-GAAP financial measures expectations and the corresponding GAAP financial measure of Power organic revenue* in the 2026 guidance without unreasonable effort due to the uncertainty of foreign exchange rates. *Non-GAAP Financial Measure
> [… 2,170 characters omitted …]
> However, Adjusted EBITDA*, Adjusted organic EBITDA*, Adjusted EBITDA margin* and Adjusted organic EBITDA margin* should not be construed as inferring that our future results will be unaffected by the items for which the measures adjust. 2026 GUIDANCE: ADJUSTED EBITDA MARGIN* We cannot provide a reconciliation of the differences between the non-GAAP financial measures expectations and the corresponding GAAP financial measures for adjusted EBITDA margin* in the 2026 guidance without unreasonable effort due to the uncertainty of the costs and timing associated with potential restructuring actions and the impacts of depreciation and amortization. *Non-GAAP Financial Measure
> [… 4,320 characters omitted …]
> 2026 GUIDANCE: FREE CASH FLOW (NON-GAAP) We cannot provide a reconciliation of the differences between the non-GAAP financial measure expectations and the corresponding GAAP financial measure for free cash flow* in the 2026 guidance without unreasonable effort due to the uncertainty of timing for capital expenditures. *Non-GAAP Financial Measure
> [… 6,299 characters omitted …]
> Conference Call and Webcast Information GE Vernova will discuss its results during its investor conference call today starting at 7:30 AM Eastern Time. The conference call will be broadcast live via webcast, and the webcast and accompanying slide presentation containing financial information can be accessed by visiting the investor section of the website https://www.gevernova.com/investors. An archived version of the webcast will be available on the website after the call. About GE Vernova GE Vernova Inc. (NYSE: GEV) is a purpose-built global energy company that includes Power, Electrification, and Wind segments and is supported by its accelerator businesses.
> [… 1,040 characters omitted …]

[P2] 10-Q segment table (R32.htm, "SEGMENT INFORMATION"), filed 2026-07-22, accession 0001996810-26-000148, period Q2 2026, https://www.sec.gov/Archives/edgar/data/1996810/000199681026000148/R32.htm
> SEGMENT INFORMATION | 6 Months Ended
> Jun. 30, 2026
> Segment Reporting [Abstract]
> SEGMENT INFORMATION | SEGMENT INFORMATION. Operating segments include components of an enterprise about which separate financial information is available that is evaluated regularly by the Company’s Chief Operating Decision Maker (CODM) for the purpose of assessing performance and allocating resources. The Company’s CODM is its Chief Executive Officer (CEO). Our operating activities are managed through three segments: Power, Electrification, and Wind. These segments have been identified based on the nature of the products and services sold and how the Company manages its operations. The performance of these segments is principally measured based on revenues and segment EBITDA. Segment EBITDA is determined based on the performance measures used by our CEO to assess the performance of each business in a given period. In connection with that assessment, the CEO may exclude matters, such as charges for impairments, significant higher-cost restructuring programs, manufacturing footprint rationalization and other similar expenses, acquisition costs and other related charges, certain gains and losses from acquisitions or dispositions, and certain other non-operational items. Consistent accounting policies have been applied by all segments for all reporting periods. See Note 1 for a description of our reportable segments.
> Three months ended June 30 | Six months ended June 30
> TOTAL SEGMENT REVENUES BY BUSINESS UNIT | 2026 | 2025 | 2026 | 2025
> Gas Power | $4,427 | $3,911 | $8,493 | $7,516
> Nuclear Power | 817 | 649 | 1,575 | 1,310
> Hydro Power | 233 | 225 | 382 | 407
> Power | $5,477 | $4,785 | $10,449 | $9,234
> Power Transmission | $1,877 | $759 | $3,256 | $1,451
> Grid Systems Integration | 806 | 579 | 1,497 | 968
> Power Conversion & Storage | 539 | 411 | 1,016 | 792
> Grid Automation & Software | 416 | 412 | 827 | 790
> Electrification | $3,637 | $2,162 | $6,597 | $4,001
> Onshore Wind | $1,721 | $2,020 | $2,908 | $3,665
> Offshore Wind | 305 | 225 | 551 | 430
> Wind | $2,026 | $2,245 | $3,459 | $4,095
> Total segment revenues | $11,141 | $9,191 | $20,504 | $17,330
> SEGMENT EBITDA
> Three months ended June 30, 2026 | Power | Electrification | Wind | Total
> Equipment revenues | $1,957 | $3,109 | $1,394 | $6,460
> Services revenues | 3,509 | 497 | 631 | 4,637
> Intersegment revenues | 12 | 32 | 1 | 44
> Segment revenues | 5,477 | 3,637 | 2,026 | 11,141
> Other revenues and elimination of intersegment revenues | (37)
> Total revenues | 11,104
> Less:(a)
> Cost of revenues(b) | 3,866 | 2,512 | 2,123
> Selling, general, and administrative expenses(b) | 472 | 341 | 137
> Research and development expenses(b) | 154 | 112 | 34
> Other segment items(c) | (45) | 1 | 7
> Segment EBITDA | $1,031 | $671 | $(275) | $1,427
> Six months ended June 30, 2026 | Power | Electrification | Wind | Total
> Equipment revenues | $3,834 | $5,597 | $2,283 | $11,714
> Services revenues | 6,593 | 948 | 1,174 | 8,715
> Intersegment revenues | 22 | 52 | 1 | 76
> Segment revenues | 10,449 | 6,597 | 3,459 | 20,504
> Other revenues and elimination of intersegment revenues | (62)
> Total revenues | 20,442
> Less:(a)
> Cost of revenues(b) | 7,504 | 4,539 | 3,772
> Selling, general, and administrative expenses(b) | 918 | 694 | 265
> Research and development expenses(b) | 286 | 219 | 70
> Other segment items(c) | (100) | (56) | 9
> Segment EBITDA | $1,842 | $1,200 | $(657) | $2,384
> Three months ended June 30, 2025 | Power | Electrification | Wind | Total
> Equipment revenues | $1,459 | $1,649 | $1,786 | $4,894
> Services revenues | 3,281 | 476 | 447 | 4,205
> Intersegment revenues | 45 | 36 | 11 | 92
> Segment revenues | 4,785 | 2,162 | 2,245 | 9,191
> Other revenues and elimination of intersegment revenues | (80)
> Total revenues | 9,111
> Less:(a)
> Cost of revenues(b) | 3,450 | 1,505 | 2,226
> Selling, general, and administrative expenses(b) | 462 | 306 | 141
> Research and development expenses(b) | 133 | 100 | 40
> Other segment items(c) | (46) | (64) | 3
> Segment EBITDA | $785 | $314 | $(165) | $934
> Six months ended June 30, 2025 | Power | Electrification | Wind | Total
> Equipment revenues | $2,881 | $3,018 | $3,192 | $9,091
> Services revenues | 6,232 | 916 | 885 | 8,033
> Intersegment revenues | 121 | 67 | 18 | 206
> Segment revenues | 9,234 | 4,001 | 4,095 | 17,330
> Other revenues and elimination of intersegment revenues | (187)
> Total revenues | 17,143
> Less:(a)
> Cost of revenues(b) | 6,818 | 2,777 | 4,066
> Selling, general, and administrative expenses(b) | 930 | 636 | 276
> Research and development expenses(b) | 242 | 182 | 73
> Other segment items(c) | (59) | (113) | (8)
> Segment EBITDA | $1,303 | $519 | $(312) | $1,510
> (a) The significant expense categories and amounts align with the segment-level information that is regularly provided to the CODM. Intersegment expenses are included within the amounts shown. (b) Excludes depreciation and amortization expenses. (c) Primarily includes equity method investment income and other interest and investment income.
> RECONCILIATION OF SEGMENT EBITDA TO NET INCOME (LOSS) | Three months ended June 30 | Six months ended June 30
> 2026 | 2025 | 2026 | 2025
> Segment EBITDA | $1,427 | $934 | $2,384 | $1,510
> Corporate and other(a) | (177) | (164) | (239) | (283)
> Restructuring and other charges | (9) | (42) | (102) | (108)
> Gains (losses) on purchases and sales of business interests(b) | (48) | — | 4,445 | 19
> Separation costs(c) | (38) | (34) | (61) | (80)
> Non-operating benefit income | 119 | 110 | 253 | 225
> Depreciation and amortization(d) | (418) | (202) | (760) | (406)
> Interest and other financial income (charges) – net(e) | 73 | 41 | 100 | 97
> (Provision) benefit for income taxes | (279) | (151) | (623) | (218)
> Net income (loss) | $649 | $492 | $5,398 | $756
> (a) Includes interest (income) expense of zero and zero and (provision) benefit for income taxes of $(3) million and $2 million for the three months ended June 30, 2026 and 2025, respectively, as well as interest (income) expense of zero
> [… 2,655 characters omitted …]

[P3] 8-K Item 5.02 (8-K body), filed 2026-08-27, accession 0001996810-26-000153, period not stated, https://www.sec.gov/Archives/edgar/data/1996810/000199681026000153/gev-20260825.htm
> Item 5.02 Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers.
> On August 25, 2026, Kenneth Parks, Chief Financial Officer of GE Vernova Inc. (the "Company"), has decided to retire on April 2, 2027 (the "Retirement Date"). From the six months preceding the Company's spin-off through the present day, Mr. Parks' insight and guidance have been invaluable at critical moments in GE Vernova's success, and he has been a trusted partner to Chief Executive Officer Scott Strazik and a vital resource to the Board of Directors and the Company's businesses. From January 1 to the Retirement Date, he will serve as strategic advisor to Mr. Strazik, and the Company wishes him the best in retirement.
> Effective January 1, 2027, Claire McDonough will become Chief Financial Officer of GE Vernova, succeeding Mr. Parks. She will join the Company as strategic advisor to Mr. Strazik on November 1, 2026, ahead of that appointment.
> Ms. McDonough, age 45, has served as Chief Financial Officer of Rivian Automotive, Inc., an electric vehicle manufacturer, since January 2021. Prior to Rivian, Ms. McDonough served in various roles at J.P. Morgan and Fairway Market. She has served on the board of directors of AutoZone, Inc. since April 2025. Ms. McDonough was not selected as an officer pursuant to any arrangement or understanding, has no family relationship with any Company director or executive officer, and is not party to any transaction requiring disclosure under Item 404(a) of Regulation S-K.
> In connection with her appointment, the Company entered into an offer letter, dated August 25, 2026 (the "Offer Letter"), providing for base salary of $1,000,000, a target Annual Incentive Plan opportunity of 100% of base salary (prorated for 2026), and a 2024 Long-Term Incentive Plan (the "LTIP") equity award with a target grant value of $5,225,000, expected in 2027. The Offer Letter also provides make-whole awards for compensation forfeited on leaving her current employer: a one-time LTIP award valued at $14,500,000 (50% RSUs, 50% PSUs), with RSUs vesting over three years (33%, 33% and 34%) and PSUs vesting after three years, both accelerating on a termination without Cause (as defined in the Offer Letter); and a $5,000,000 cash sign-on payment, repayable in full if she resigns within 12 months or engages in conduct constituting Cause.
> In connection with Mr. Parks’
> [… 991 characters omitted …]

- gev2q2026form8-k.pdf (a PDF exhibit of the same 8-K, such as an investor presentation, accession 0001996810-26-000147) is a PDF and is not included.

## DATA 12 - WHAT WE DO NOT HOLD   [declared so you can source it or carry the uncertainty]
- Segment revenue and margin in raw SEC XBRL: NOT MAPPED; of the 3,767 fact rows in raw SEC companyfacts, zero carry a dimension. See DATA 11 for extracted segment economics and backlog.
- Marketable securities and short-term investments: NOT MAPPED for this company; the cash column and DATA 2's vendor cash can understate liquid assets badly
- Stock-based compensation per year: HELD, 2 year(s) (2024-2025), in DATA 5's SBC column
- Effective tax rate: WITHHELD; net income + tax does not equal pre-tax income, by more than 5%, in FY2023 (our pre-tax field admits a US-domestic-only tag), so do not reconstruct a tax rate from those years.
- Debt components beyond long-term debt: HELD, 3 year(s) (2023-2025), in DATA 6C; whether they overlap is not known, so no total debt is computed
- Which XBRL tag produced each number: NOT RECORDED (see DATA 0).
- Earnings-call text: NOT AVAILABLE — transcript status not recorded.

## DEFAULTS   [each desk input takes this value unless you pass another; a departure needs the named reason, and the desk asks for it]
- shares_outstanding: 266,333,600 | DATA 2, the vendor's basic count
- shares_dilution_factor: 1.0081 | the company's own diluted EPS (basic / diluted EPS); applied when it is at least 1.05
- shares_dilution_period: quarter ended 2026-06-30 | the filed period the factor comes from
- shares_default: 266,333,600 | the desk's shares_diluted unless you pass another count with shares_reason
- shares_warning: not available | when present, the desk asks for shares_reason on every call
- filed_shares_diluted: 276,000,000 | DATA 6B's latest filed diluted average; with after-interest flows it counts a convertible's interest twice
- filed_shares_fy: 2025 | the fiscal year of that average
- owner_earnings_default_b: 8.681 | the Base base_cf; more than 2% away needs base_cf_reason
- owner_earnings_source: ttm_filed | where that default comes from
- excess_cash: not available | $B: the base fiscal year's cash and short-term investments at face (0 for a financial company; not available when the cash term could not be computed, see long_run stamps), which the desk adds per share to every scenario's value; the owner-earnings default and the reference base exclude the after-tax interest on it; a different amount needs excess_cash_reason; the desk refuses an amount above base_year_cash_and_investments_b
- base_year_cash_and_investments_b: 8.848000 | the base fiscal year's cash and short-term investments as filed; the desk refuses an excess_cash above it (cash after the valuation date is already in the cash flows)
- cash_basis_b: 12.181 | the alternative base (includes working-capital swings)
- reference_base_b: not available | the fiscal-year owner-earnings base the CONSENSUS-IMPLIED VALUE grows from
- base_window: not available | information only: the desk's arithmetic does not depend on the window
- coe_anchor: 8.98% | the Base discount rate; more than 1.5 points away needs coe_adjustment_reason
- coe_premium_source: closure | where the premium behind coe_anchor comes from: the live reference uses rs2's closure premium; point-in-time packs use Damodaran's premium, because the live reference's closure premium cannot be rebuilt for a past date
- terminal_g_default: 3.75% | the next-FY consensus revenue growth rule (your record holds fewer than 5 years of revenue or breakeven inflation is missing); more than 0.5 points away needs terminal_reason
- terminal_g_anchor: 3.75% | the long-run nominal growth anchor
- terminal_ronic: 10.1899% | the Base terminal return on new investment: the cost of equity plus p times the excess over it of r_tc, your record's median return on tangible invested capital (both in long_run; p is the share of your last eight years above the cost of equity); a Base terminal_ronic more than 2 points away needs terminal_reason
- long_run: cycle=no, cycle_year=none, cycle_years=none, e5=none, oe5=none, m5=none, m_tc=none, m_years=none, r_tc=13.8198%, r_years=2022-2025:4, p=0.250, g_rev=none, g_rev_years=none, terminal_g_basis=consensus_fallback, ni_over_oe=1.097685, x_over_oe=none, nwc_intensity=none, nwc_years=none, stub_months=8.8706, om_tc=none, om_trend=none, om_L=none, om_years=none, om_shape=none, om_basis=none, om_5=none, m_long=none, margin_ratio=none, stamps=amortization_gap:2022-2025;tangible_equity_partial:2022-2025;margin_record_not_available;cash_term_not_available_no_bill_rate | The desk values years 6 on from X_5 (earnings before acquired-intangible amortization), pays for growth at a return that fades from r_tc (your record's 8-year median return on tangible invested capital) to terminal_ronic, and moves the margin from m5 to m_long by year 10 (margin_ratio = m_long / m5; none means the margin is held): om_5, the operating margin the consensus implies at year 5, moves all the way to om_trend, the trend level of your record's 8-year operating margin (to zero for a loss record). The members are the record behind it.
- net_debt_b: -7.676 | the firm frame's net debt; another figure needs net_debt_reason (the pack's flows are after interest: value them in the equity frame)
- interest_expense_latest_b: not available | the firm frame's interest_addback is at most this
- consensus_data_status: enrich_missing | ok, or why DATA 8 prints no consensus estimates
- consensus_implied_value: not available | a Base value outside 0.75-1.33 of it needs guidance_deviation_reason
- reference_status: not_available | whether the reference is shown, fenced, not available, or not meaningful (a value of zero or less)
- levels: not available | the desk holds the Base's years 1-2 at year1 and year2 unless you pass guidance_deviation_reason (a Base year 2 more than 5% away); a Bull or Bear more than 15% from bull2 or bear2 needs scenario_deviation_reason
- price_implied: not available — the pack has no consensus reference (reference_status not_available) | at the DEFAULTS, the value of each judgment input at which the Base equals today's price, the other inputs held; the desk returns the same for your own inputs on every run; a verdict of undervalued or overvalued needs a crux on one of them (TASK item 6)
- working_capital: not available | no working-capital deduction: the reference has no revenue path or your record holds fewer than 5 years with a classified balance sheet
- next_fy_revenue_growth: not available | Base years 3-5 above it need guidance_deviation_reason, or the desk holds them at it
- years35_p90: not available | growth above the base-rate p90 needs dated, company-specific evidence (a flag, not a veto)
- base_rate_5y: not available | the desk ranks the market-implied growth against it
- revenue_cagr_5y_pct: not available | the desk compares the market-implied growth with it
- cash_flow_life: required on every desk call ("perpetual" or years), with cash_flow_life_reason
- price: a Bull value below today's price needs bull_below_price_reason; a Bear value above it needs bear_above_price_reason
