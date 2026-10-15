# DATA PACK - HRTG   (pack revision 22)

## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator, fetch date NOT RECORDED - age unknown, treat as potentially stale]
- Trailing P/E: not available   |   P/B: not available   |   PEG: not available   [trailing; the vendor does not state the period]
- Return on equity: not available   |   gross margin: not available   |   operating margin: not available   |   dividend yield: not available   [vendor-computed, expressed as fractions not percents]
- CONSENSUS ESTIMATES   [yfinance, fetched 2026-10-05; sell-side estimates, not company guidance]
| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | EPS analysts | growth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current FY | $0.862B | $0.861B | $0.862B | 2 | +1.7% | $5.17 | $5.00 | $5.35 | 2 | -17.2% |
| next FY | $0.899B | $0.878B | $0.920B | 2 | +4.3% | $5.18 | $4.90 | $5.45 | 3 | +0.2% |
- [Arithmetic] BASE-YEAR CHECK: consensus measures current-FY EPS growth from a year-ago EPS of $6.25; our filed FY2025 EPS is $6.32 (net income / diluted shares), -1% apart. A large gap means the consensus growth rate starts from a different base than the filings (adjusted rather than GAAP figures, or one-off items).
- Next-FY EPS estimate trend: now $5.18 | 30 days ago $5.18 | 60 days ago $4.73 | 90 days ago $4.73  (+9.5% in 90 days)
- Estimate revisions, last 30 days (next FY): 1 up / 0 down  (last 7 days: 1 up / 0 down)
- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $69.63 per share, the analysts' own earnings path at our discount rate — context, never the reason for a call: the same generic rules for every company; it values the average stock close to its price but carries little information about any one stock (on 2019–2023 point-in-time data, a stock it valued at twice its price went on to earn only about 3% more over three years than one it valued at its price). | base: owner earnings 0.200 (FY2025, the last full fiscal year, ended 2025-12-31) | cash-flow growth years 1-5: -17.2% / +0.2% / +4.3% / +4.3% / +4.3% (years 1-2 consensus EPS growth; from year 3, next-FY revenue growth fading toward the base-rate median, never above next-FY revenue growth) | then a 5-year fade to the terminal-growth anchor 3.75% | from year 6 growth needs no new investment: your record's tangible capital is zero or negative, so the return on new investment is unlimited and cash flow = earnings; earnings margin moving from 18.5% to 8.6% by year 10: the operating margin moves to the trend level of your 8-year record (12.3%) by year 10 (the consensus implies 25.4% at year 5) | working capital: not deducted (your record holds no classified balance sheet for it) | no excess-cash term (financial company) | discounted at the COE ANCHOR 8.98%, built from the market-consistent premium (rs2 closure, as of 2026-10-04) | valued at the fiscal year end, rolled forward 9 months | levels: year 1 0.166, year 2 0.166; Bull year 2 0.174, Bear year 2 0.157 (next-FY EPS high and low, 3 analysts)
- [Arithmetic] BASE WINDOW CHECK: base_window_gap +21% | TTM owner earnings (through 2026-06-30) 0.221 | the fiscal-year base grown by the consensus current-FY EPS growth for 2 quarter(s) between them is 0.182 (one of the two windows holds items the other does not: a one-off gain or charge, a capex swing) | on the TTM window the consensus path lands above the street fence [$16.36, $76.36], not shown | on the fiscal-year window $69.63 (the CONSENSUS-IMPLIED VALUE above) | the BASE-YEAR CHECK shows the analysts' own year-ago EPS against the filed year
- Analyst price targets: low 36.0 / mean 39.0 / median 39.0 / high 42.0   [Aggregator - 12-month sell-side targets, fetched 2026-10-05, 0 day(s) ago]
- 52-week range: 20.48 - 36.5

## DEFAULTS   [each desk input takes this value unless you pass another; a departure needs the named reason, and the desk asks for it]
- shares_outstanding: 29,732,416 | DATA 2, the vendor's basic count
- shares_dilution_factor: 1.0049 | the company's own diluted EPS (basic / diluted EPS); applied when it is at least 1.05
- shares_dilution_period: quarter ended 2026-06-30 | the filed period the factor comes from
- shares_default: 29,732,416 | the desk's shares_diluted unless you pass another count with shares_reason
- shares_warning: not available | when present, the desk asks for shares_reason on every call
- filed_shares_diluted: 30,949,899 | DATA 6B's latest filed diluted average; with after-interest flows it counts a convertible's interest twice
- filed_shares_fy: 2025 | the fiscal year of that average
- owner_earnings_default_b: 0.221 | the Base base_cf; more than 2% away needs base_cf_reason
- owner_earnings_source: ttm_filed | where that default comes from
- excess_cash: 0.000000 | $B: the base fiscal year's cash and short-term investments at face (0 for a financial company; not available when the cash term could not be computed, see long_run stamps), which the desk adds per share to every scenario's value; the owner-earnings default and the reference base exclude the after-tax interest on it; a different amount needs excess_cash_reason; the desk refuses an amount above base_year_cash_and_investments_b
- base_year_cash_and_investments_b: 0.559274 | the base fiscal year's cash and short-term investments as filed; the desk refuses an excess_cash above it (cash after the valuation date is already in the cash flows)
- cash_basis_b: 0.292 | the alternative base (includes working-capital swings)
- reference_base_b: 0.200219 | the fiscal-year owner-earnings base the CONSENSUS-IMPLIED VALUE grows from
- base_window: gap=+21% | information only: the desk's arithmetic does not depend on the window
- coe_anchor: 8.98% | the Base discount rate; more than 1.5 points away needs coe_adjustment_reason
- coe_premium_source: closure | where the premium behind coe_anchor comes from: the live reference uses rs2's closure premium; point-in-time packs use Damodaran's premium, because the live reference's closure premium cannot be rebuilt for a past date
- terminal_g_default: 3.75% | from your own revenue trend FY2018-FY2025: 8.31%/yr, held between breakeven inflation and the anchor; more than 0.5 points away needs terminal_reason
- terminal_g_anchor: 3.75% | the long-run nominal growth anchor
- terminal_ronic: unlimited | the Base terminal return on new investment: the cost of equity plus p times the excess over it of r_tc, your record's median return on tangible invested capital (both in long_run; p is the share of your last eight years above the cost of equity); a Base terminal_ronic more than 2 points away needs terminal_reason
- long_run: cycle=yes, cycle_year=2017, cycle_years=2017, e5=0.188336, oe5=0.188287, m5=18.4692%, m_tc=6.8195%, m_years=2018-2025:8, r_tc=+inf, r_years=2018-2025:8, p=0.750, g_rev=8.3115%, g_rev_years=2018-2025:8, terminal_g_basis=revenue_trend, ni_over_oe=0.973841, x_over_oe=0.994999, nwc_intensity=none, nwc_years=none, stub_months=9.1663, om_tc=10.3815%, om_trend=12.3303%, om_L=32.2603%, om_years=2018-2025:8, om_shape=swing, om_basis=with_amortization, om_5=25.4121%, m_long=8.6000%, margin_ratio=0.465639, stamps=tangible_equity_partial:2023-2025 | The desk values years 6 on from X_5 (earnings before acquired-intangible amortization), pays for growth at a return that fades from r_tc (your record's 8-year median return on tangible invested capital) to terminal_ronic, and moves the margin from m5 to m_long by year 10 (margin_ratio = m_long / m5; none means the margin is held): om_5, the operating margin the consensus implies at year 5, moves all the way to om_trend, the trend level of your record's 8-year operating margin (to zero for a loss record). The members are the record behind it.
- net_debt_b: -0.481 | the firm frame's net debt; another figure needs net_debt_reason (the pack's flows are after interest: value them in the equity frame)
- interest_expense_latest_b: 0.011 | the firm frame's interest_addback is at most this
- consensus_data_status: ok | ok, or why DATA 8 prints no consensus estimates
- consensus_implied_value: 69.63 | a Base value outside 0.75-1.33 of it (52.22-92.61) needs guidance_deviation_reason
- reference_status: used | whether the reference is shown, fenced, not available, or not meaningful (a value of zero or less)
- levels: year1=0.166, year2=0.166, bull2=0.174, bear2=0.157 | the desk holds the Base's years 1-2 at year1 and year2 unless you pass guidance_deviation_reason (a Base year 2 more than 5% away); a Bull or Bear more than 15% from bull2 or bear2 needs scenario_deviation_reason
- price_implied: coe=17.87%; growth_years_3_5=-17.5% a year; fade_years=not reachable (0 years to 60 years); terminal_g=not reachable (0.00% to 4.47%); terminal_ronic=not reachable (9.0% to unlimited); year2_level=not reachable ($0.157B to $0.174B) | at the DEFAULTS, the value of each judgment input at which the Base equals today's price, the other inputs held; the desk returns the same for your own inputs on every run; a verdict of undervalued or overvalued needs a crux on one of them (TASK item 6)
- working_capital: not available | no working-capital deduction: the reference has no revenue path or your record holds fewer than 5 years with a classified balance sheet
- next_fy_revenue_growth: +4.3% | Base years 3-5 above it need guidance_deviation_reason, or the desk holds them at it
- years35_p90: 46.7% | growth above the base-rate p90 needs dated, company-specific evidence (a flag, not a veto)
- base_rate_5y: share_ge_10=46.9%, share_ge_20=28.1%, share_ge_30=17.4%, p50=8.9%, p90=46.7% | the desk ranks the market-implied growth against it
- revenue_cagr_5y_pct: +7.4% | the desk compares the market-implied growth with it
- cash_flow_life: required on every desk call ("perpetual" or years), with cash_flow_life_reason
- price: a Bull value below today's price needs bull_below_price_reason; a Bear value above it needs bear_above_price_reason
