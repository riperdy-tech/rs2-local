# DATA PACK - KSS   (pack revision 22)

## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator, fetch date NOT RECORDED - age unknown, treat as potentially stale]
- Trailing P/E: not available   |   P/B: not available   |   PEG: not available   [trailing; the vendor does not state the period]
- Return on equity: not available   |   gross margin: not available   |   operating margin: not available   |   dividend yield: not available   [vendor-computed, expressed as fractions not percents]
- CONSENSUS ESTIMATES   [yfinance, fetched 2026-10-05; sell-side estimates, not company guidance]
| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | EPS analysts | growth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current FY | $14.928B | $14.606B | $15.435B | 11 | +1.0% | $2.08 | $1.60 | $2.25 | 14 | +28.4% |
| next FY | $14.934B | $14.460B | $15.560B | 11 | +0.0% | $1.56 | $1.23 | $1.91 | 14 | -24.9% |
- BASE-YEAR CHECK: not available — the vendor's year-ago revenue does not match FY2026's filed revenue within 2%, so the vendor's year-ago EPS and ours cannot be shown to be on one basis.
- Next-FY EPS estimate trend: now $1.56 | 30 days ago $1.57 | 60 days ago $1.48 | 90 days ago $1.50  (+3.9% in 90 days)
- Estimate revisions, last 30 days (next FY): 10 up / 2 down  (last 7 days: 8 up / 3 down)
- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $41.43 per share, the analysts' own earnings path at our discount rate — context, never the reason for a call: the same generic rules for every company; it values the average stock close to its price but carries little information about any one stock (on 2019–2023 point-in-time data, a stock it valued at twice its price went on to earn only about 3% more over three years than one it valued at its price). | base: owner earnings 0.578 (FY2026, the last full fiscal year, ended 2026-01-31) | cash-flow growth years 1-5: +28.4% / -24.9% / +0.0% / +0.0% / +0.0% (years 1-2 consensus EPS growth; from year 3, next-FY revenue growth fading toward the base-rate median, never above next-FY revenue growth) | then a 5-year fade to the terminal-growth default 2.36% | from year 6 growth is paid for at the cost of equity, 10.08%: the median return on tangible capital in your 8-year record, 5.6%, is not above it, so new investment earns only its cost; cash flow = earnings x (1 - growth / return); no revenue path (the vendor's revenue is missing or not on the filed basis), so earnings follow owner earnings at the year-5 ratio of earnings to owner earnings | plus excess cash $0.674B at face (after-tax interest on it removed from earnings); the excess cash is the unrestricted cash line: excludes customer liabilities $0.275B (customer_money_excluded); customer liabilities exceed the separate customer assets and restricted cash by $0.275B: the unrestricted line may be funding customer obligations (customer_liabilities_exceed_separate_assets) | discounted at the COE ANCHOR 10.08%, built from the market-consistent premium (rs2 closure, as of 2026-10-04) | valued at the fiscal year end, rolled forward 8 months | levels: year 1 0.742, year 2 0.558; Bull year 2 0.683, Bear year 2 0.439 (next-FY EPS high and low, 14 analysts)
- Analyst price targets: low 9.0 / mean 18.73 / median 18.0 / high 41.5   [Aggregator - 12-month sell-side targets, fetched 2026-10-05, 0 day(s) ago]
- 52-week range: 11.38 - 25.22

## DEFAULTS   [each desk input takes this value unless you pass another; a departure needs the named reason, and the desk asks for it]
- shares_outstanding: 113,376,445 | DATA 2, the vendor's basic count
- shares_dilution_factor: 1.0469 | the company's own diluted EPS (basic / diluted EPS); applied when it is at least 1.05
- shares_dilution_period: quarter ended 2026-07-31 | the filed period the factor comes from
- shares_default: 113,376,445 | the desk's shares_diluted unless you pass another count with shares_reason
- shares_warning: not available | when present, the desk asks for shares_reason on every call
- filed_shares_diluted: 114,000,000 | DATA 6B's latest filed diluted average; with after-interest flows it counts a convertible's interest twice
- filed_shares_fy: 2026 | the fiscal year of that average
- owner_earnings_default_b: 0.630 | the Base base_cf; more than 2% away needs base_cf_reason
- owner_earnings_source: ttm_filed | where that default comes from
- excess_cash: 0.674000 | $B: the base fiscal year's cash and short-term investments at face (0 for a financial company; not available when the cash term could not be computed, see long_run stamps), which the desk adds per share to every scenario's value; the owner-earnings default and the reference base exclude the after-tax interest on it; a different amount needs excess_cash_reason; the desk refuses an amount above base_year_cash_and_investments_b
- base_year_cash_and_investments_b: 0.674000 | the base fiscal year's cash and short-term investments as filed; the desk refuses an excess_cash above it (cash after the valuation date is already in the cash flows)
- cash_basis_b: 1.000 | the alternative base (includes working-capital swings)
- reference_base_b: 0.578105 | the fiscal-year owner-earnings base the CONSENSUS-IMPLIED VALUE grows from
- base_window: not available | information only: the desk's arithmetic does not depend on the window
- coe_anchor: 10.08% | the Base discount rate; more than 1.5 points away needs coe_adjustment_reason
- coe_premium_source: closure | where the premium behind coe_anchor comes from: the live reference uses rs2's closure premium; point-in-time packs use Damodaran's premium, because the live reference's closure premium cannot be rebuilt for a past date
- terminal_g_default: 2.36% | from your own revenue trend FY2019-FY2026: -3.73%/yr, held between breakeven inflation and the anchor; more than 0.5 points away needs terminal_reason
- terminal_g_anchor: 3.75% | the long-run nominal growth anchor
- terminal_ronic: 10.0800% | the Base terminal return on new investment: the cost of equity plus p times the excess over it of r_tc, your record's median return on tangible invested capital (both in long_run; p is the share of your last eight years above the cost of equity); a Base terminal_ronic more than 2 points away needs terminal_reason
- long_run: cycle=yes, cycle_year=2025, cycle_years=2021;2023;2025, e5=0.241591, oe5=0.558424, m5=none, m_tc=1.7829%, m_years=2019-2026:8, r_tc=5.6349%, r_years=2019-2026:8, p=0.375, g_rev=-3.7296%, g_rev_years=2019-2026:8, terminal_g_basis=revenue_trend, ni_over_oe=0.393752, x_over_oe=0.393752, nwc_intensity=3.4581%, nwc_years=2019-2026:8, stub_months=8.1478, om_tc=4.0608%, om_trend=3.3287%, om_L=4.0188%, om_years=2019-2026:8, om_shape=swing, om_basis=with_amortization, om_5=none, m_long=none, margin_ratio=none, stamps=none | The desk values years 6 on from X_5 (earnings before acquired-intangible amortization), pays for growth at a return that starts at the cost of equity, coe_anchor (r_tc, your record's 8-year median return on tangible invested capital, is not above it or is not available), then fades to terminal_ronic, and moves the margin from m5 to m_long by year 10 (margin_ratio = m_long / m5; none means the margin is held): om_5, the operating margin the consensus implies at year 5, moves all the way to om_trend, the trend level of your record's 8-year operating margin (to zero for a loss record). The members are the record behind it.
- net_debt_b: 0.762 | the firm frame's net debt; another figure needs net_debt_reason (the pack's flows are after interest: value them in the equity frame)
- interest_expense_latest_b: not available | the firm frame's interest_addback is at most this
- consensus_data_status: ok | ok, or why DATA 8 prints no consensus estimates
- consensus_implied_value: 41.43 | a Base value outside 0.75-1.33 of it (31.07-55.10) needs guidance_deviation_reason
- reference_status: used | whether the reference is shown, fenced, not available, or not meaningful (a value of zero or less)
- levels: year1=0.742, year2=0.558, bull2=0.683, bear2=0.439 | the desk holds the Base's years 1-2 at year1 and year2 unless you pass guidance_deviation_reason (a Base year 2 more than 5% away); a Bull or Bear more than 15% from bull2 or bear2 needs scenario_deviation_reason
- price_implied: coe=not reachable (5.28% to 25.00%); growth_years_3_5=-53.8% a year; fade_years=not reachable (0 years to 60 years); terminal_g=not reachable (0.00% to 4.47%); terminal_ronic=not reachable (10.1% to unlimited); year2_level=not reachable ($0.439B to $0.683B) | at the DEFAULTS, the value of each judgment input at which the Base equals today's price, the other inputs held; the desk returns the same for your own inputs on every run; a verdict of undervalued or overvalued needs a crux on one of them (TASK item 6)
- working_capital: not available | no working-capital deduction: the reference has no revenue path or your record holds fewer than 5 years with a classified balance sheet
- next_fy_revenue_growth: +0.0% | Base years 3-5 above it need guidance_deviation_reason, or the desk holds them at it
- years35_p90: 14.0% | growth above the base-rate p90 needs dated, company-specific evidence (a flag, not a veto)
- base_rate_5y: share_ge_10=17.2%, share_ge_20=4.0%, share_ge_30=1.5%, p50=4.3%, p90=14.0% | the desk ranks the market-implied growth against it
- revenue_cagr_5y_pct: -0.5% | the desk compares the market-implied growth with it
- cash_flow_life: required on every desk call ("perpetual" or years), with cash_flow_life_reason
- price: a Bull value below today's price needs bull_below_price_reason; a Bear value above it needs bear_above_price_reason
