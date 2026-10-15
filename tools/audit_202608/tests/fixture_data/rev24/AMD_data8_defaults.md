# DATA PACK - AMD   (pack revision 21)

## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator, fetched 2026-08-19, 46 day(s) ago - STALE, discount accordingly - STALE (46 days)]
- Trailing P/E: not available (stale)   |   P/B: not available (stale)   |   PEG: not available (stale)   [trailing; the vendor does not state the period]
- Return on equity: not available (stale)   |   gross margin: not available (stale)   |   operating margin: not available (stale)   |   dividend yield: not available (stale)   [vendor-computed, expressed as fractions not percents]
- CONSENSUS ESTIMATES   [yfinance, fetched 2026-10-04; sell-side estimates, not company guidance]
| period | revenue avg | low | high | analysts | growth | EPS avg | low | high | EPS analysts | growth |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| current FY | $50.941B | $48.339B | $52.660B | 47 | +47.1% | $7.58 | $7.00 | $8.20 | 49 | +81.7% |
| next FY | $88.235B | $61.257B | $118.112B | 52 | +73.2% | $15.58 | $9.60 | $20.25 | 50 | +105.7% |
- [Arithmetic] BASE-YEAR CHECK: consensus measures current-FY EPS growth from a year-ago EPS of $4.17; our filed FY2025 EPS is $2.65 (net income / diluted shares), +57% apart. A large gap means the consensus growth rate starts from a different base than the filings (adjusted rather than GAAP figures, or one-off items).
- Next-FY EPS estimate trend: now $15.58 | 30 days ago $15.33 | 60 days ago $13.92 | 90 days ago $13.18  (+18.3% in 90 days)
- Estimate revisions, last 30 days (next FY): 3 up / 1 down  (last 7 days: 1 up / 0 down)
- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $285.18 per share, the analysts' own earnings path at our discount rate — context, never the reason for a call: the same generic rules for every company; it values the average stock close to its price but carries little information about any one stock (on 2019–2023 point-in-time data, a stock it valued at twice its price went on to earn only about 3% more over three years than one it valued at its price). | base: owner earnings 5.752 (FY2025, the last full fiscal year, ended 2025-12-27) | cash-flow growth years 1-5: +81.7% / +105.7% / +52.9% / +32.5% / +12.2% (years 1-2 consensus EPS growth; from year 3, next-FY revenue growth fading toward the base-rate median, never above next-FY revenue growth) | then a 5-year fade to the terminal-growth anchor 3.75% | from year 6 growth is paid for at the return on new investment your record supports: 55.4% in year 5, the median return on tangible capital in your 8-year record, moving to 55.4% from year 10, the cost of equity plus that median's excess over it weighted by the share of record years above the cost of equity; cash flow = earnings x (1 - growth / return); earnings margin moving from 26.3% to 15.0% by year 10: the operating margin moves to the trend level of your 8-year record (7.8%) by year 10 (the consensus implies 19.0% at year 5) | working capital deducted in years 1-5: 2.164 / 4.951 / 6.193 / 5.826 / 2.896 (13.3% of each year's revenue change) | plus excess cash $10.552B at face (after-tax interest on it removed from earnings); the excess cash is the unrestricted cash line: excludes restricted cash $0.017B (customer_money_excluded) | discounted at the COE ANCHOR 10.46%, built from the market-consistent premium (rs2 closure, as of 2026-10-04) | valued at the fiscal year end, rolled forward 9 months | levels: year 1 10.452, year 2 21.496; Bull year 2 27.934, Bear year 2 13.243 (next-FY EPS high and low, 50 analysts)
- Analyst price targets: low 365.0 / mean 619.51 / median 616.0 / high 1250.0   [Aggregator - 12-month sell-side targets, fetched 2026-10-04, 0 day(s) ago]
- 52-week range: 188.22 - 645.46

## DEFAULTS   [each desk input takes this value unless you pass another; a departure needs the named reason, and the desk asks for it]
- shares_outstanding: 1,632,475,042 | DATA 2, the vendor's basic count
- shares_dilution_factor: 1.0145 | the company's own diluted EPS (basic / diluted EPS); applied when it is at least 1.05
- shares_dilution_period: quarter ended 2026-06-30 | the filed period the factor comes from
- shares_default: 1,632,475,042 | the desk's shares_diluted unless you pass another count with shares_reason
- shares_warning: not available | when present, the desk asks for shares_reason on every call
- filed_shares_diluted: 1,636,000,000 | DATA 6B's latest filed diluted average; with after-interest flows it counts a convertible's interest twice
- filed_shares_fy: 2025 | the fiscal year of that average
- owner_earnings_default_b: 7.148 | the Base base_cf; more than 2% away needs base_cf_reason
- owner_earnings_source: ttm_filed | where that default comes from
- excess_cash: 10.552000 | $B: the base fiscal year's cash and short-term investments at face (0 for a financial company; not available when the cash term could not be computed, see long_run stamps), which the desk adds per share to every scenario's value; the owner-earnings default and the reference base exclude the after-tax interest on it; a different amount needs excess_cash_reason; the desk refuses an amount above base_year_cash_and_investments_b
- base_year_cash_and_investments_b: 10.552000 | the base fiscal year's cash and short-term investments as filed; the desk refuses an excess_cash above it (cash after the valuation date is already in the cash flows)
- cash_basis_b: 6.765 | the alternative base (includes working-capital swings)
- reference_base_b: 5.752244 | the fiscal-year owner-earnings base the CONSENSUS-IMPLIED VALUE grows from
- base_window: not available | information only: the desk's arithmetic does not depend on the window
- coe_anchor: 10.46% | the Base discount rate; more than 1.5 points away needs coe_adjustment_reason
- coe_premium_source: closure | where the premium behind coe_anchor comes from: the live reference uses rs2's closure premium; point-in-time packs use Damodaran's premium, because the live reference's closure premium cannot be rebuilt for a past date
- terminal_g_default: 3.75% | from your own revenue trend FY2018-FY2025: 25.20%/yr, held between breakeven inflation and the anchor; more than 0.5 points away needs terminal_reason
- terminal_g_anchor: 3.75% | the long-run nominal growth anchor
- terminal_ronic: 55.4197% | the Base terminal return on new investment: the cost of equity plus p times the excess over it of r_tc, your record's median return on tangible invested capital (both in long_run; p is the share of your last eight years above the cost of equity); a Base terminal_ronic more than 2 points away needs terminal_reason
- long_run: cycle=no, cycle_year=none, cycle_years=none, e5=52.716357, oe5=48.867917, m5=26.2812%, m_tc=15.0000%, m_years=2018-2025:8, r_tc=55.4197%, r_years=2018-2025:8, p=1.000, g_rev=25.1992%, g_rev_years=2018-2025:8, terminal_g_basis=revenue_trend, ni_over_oe=0.839961, x_over_oe=1.161718, nwc_intensity=13.2757%, nwc_years=2018-2025:8, stub_months=9.2649, om_tc=8.3716%, om_trend=7.7872%, om_L=10.6643%, om_years=2018-2025:8, om_shape=swing, om_basis=without_amortization, om_5=19.0314%, m_long=15.0369%, margin_ratio=0.572156, stamps=amortization_gap:2018-2022;tangible_equity_partial:2018-2020;operating_margin_without_amortization | The desk values years 6 on from X_5 (earnings before acquired-intangible amortization), pays for growth at a return that fades from r_tc (your record's 8-year median return on tangible invested capital) to terminal_ronic, and moves the margin from m5 to m_long by year 10 (margin_ratio = m_long / m5; none means the margin is held): om_5, the operating margin the consensus implies at year 5, moves all the way to om_trend, the trend level of your record's 8-year operating margin (to zero for a loss record). The members are the record behind it.
- net_debt_b: -8.204 | the firm frame's net debt; another figure needs net_debt_reason (the pack's flows are after interest: value them in the equity frame)
- interest_expense_latest_b: 0.131 | the firm frame's interest_addback is at most this
- consensus_data_status: ok | ok, or why DATA 8 prints no consensus estimates
- consensus_implied_value: 285.18 | a Base value outside 0.75-1.33 of it (213.88-379.29) needs guidance_deviation_reason
- reference_status: used | whether the reference is shown, fenced, not available, or not meaningful (a value of zero or less)
- levels: year1=10.452, year2=21.496, bull2=27.934, bear2=13.243 | the desk holds the Base's years 1-2 at year1 and year2 unless you pass guidance_deviation_reason (a Base year 2 more than 5% away); a Bull or Bear more than 15% from bull2 or bear2 needs scenario_deviation_reason
- price_implied: coe=6.68%; growth_years_3_5=+58.4% a year; fade_years=41.7 years; terminal_g=not reachable (0.00% to 4.47%); terminal_ronic=not reachable (10.5% to unlimited); year2_level=not reachable ($13.243B to $27.934B) | at the DEFAULTS, the value of each judgment input at which the Base equals today's price, the other inputs held; the desk returns the same for your own inputs on every run; a verdict of undervalued or overvalued needs a crux on one of them (TASK item 6)
- working_capital: 2.164239, 4.950961, 6.193452, 5.826408, 2.895501 | the working capital the reference's revenue growth ties up in years 1-5, $B (13.28% of each year's revenue change, median of FY2018-FY2025, 8 years), which the desk deducts from every scenario's owner earnings unless base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or reference_base_b (a base that matches an owner-earnings figure is owner earnings)
- next_fy_revenue_growth: +73.2% | Base years 3-5 above it need guidance_deviation_reason, or the desk holds them at it
- years35_p90: 30.1% | growth above the base-rate p90 needs dated, company-specific evidence (a flag, not a veto)
- base_rate_5y: share_ge_10=17.2%, share_ge_20=4.0%, share_ge_30=1.5%, p50=4.3%, p90=14.0% | the desk ranks the market-implied growth against it
- revenue_cagr_5y_pct: +28.8% | the desk compares the market-implied growth with it
- cash_flow_life: required on every desk call ("perpetual" or years), with cash_flow_life_reason
- price: a Bull value below today's price needs bull_below_price_reason; a Bear value above it needs bear_above_price_reason
