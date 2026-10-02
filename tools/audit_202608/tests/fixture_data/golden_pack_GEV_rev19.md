# DATA PACK - GEV   (pack revision 19)

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
- working_capital: not available | no working-capital deduction: the reference has no revenue path or your record holds fewer than 5 years with a classified balance sheet
- next_fy_revenue_growth: not available | Base years 3-5 above it need guidance_deviation_reason, or the desk holds them at it
- years35_p90: not available | growth above the base-rate p90 needs dated, company-specific evidence (a flag, not a veto)
- base_rate_5y: not available | the desk ranks the market-implied growth against it
- revenue_cagr_5y_pct: not available | the desk compares the market-implied growth with it
- cash_flow_life: required on every desk call ("perpetual" or years), with cash_flow_life_reason
- price: a Bull value below today's price needs bull_below_price_reason; a Bear value above it needs bear_above_price_reason
