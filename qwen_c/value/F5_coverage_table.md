# F5: the E3 no-call names re-prepared under the §6 stamps (F_SPEC_valuation_menu v1.1)

Re-prepared OFFLINE on 2026-11-03: every name that was a no-call in E3 (seed 1000; seed 3000's no-calls are the same names, the preparation does not depend on the seed), with this branch's code, the facts in wt-m3q's sec_store, the E3 panel's pinned anchors and the E3 packets (T 2026-11-01T16:47:30Z). `main before F5` is main's inputs.py at d3b236d on the same facts, so a change made by main's facts v5 is told apart from one made by F5. A name that prepares is then checked with the record-neutral reply (checks v11) to show it values.

| Ticker | Family | E3 code | main before F5 | After F5 | Stamps added | Why |
|---|---|---|---|---|---|---|
| AAUC | commodity | history_short | history_short | no_call history_short | - | two fiscal years of revenue (a 2025 listing): legitimate |
| AII | financial | history_short | history_short | no_call history_short | - | two filed returns on opening equity (a 2025 listing): legitimate |
| AMT | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| APA | commodity | history_short | history_short | no_call history_short | - | no filed revenue under any listed tag: F6 (revenue tag coverage) |
| ARX | financial | history_short | history_short | no_call history_short | - | two fiscal-year equity balances: legitimate |
| BCRX | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| BFH | financial | preferred_dividends_unavailable | preferred_dividends_unavailable | no_call preferred_dividends_unavailable | - | inspected: preferred stock first issued in 2025 (liquidation preference $75.0 million, PreferredStockValue 0); no DividendsPreferredStock or income-to-common fact for 2025 in companyfacts. The data are absent, not mis-read: stays a no-call (CROSS_CHECK_Q3 6). A zero-dividend reading for a preferred issued in the base year would be an operator ruling |
| CBL | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| CIM | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| CMRE | commodity | tax_unavailable | tax_unavailable | no_call tax_unavailable | - | §6(a) cannot be checked: no pretax income and no provision filed under any listed tag (20-F, IFRS). Stays; F6 (IFRS pretax tag) |
| CPA | operating | input_missing | kd_out_of_band | no_call kd_out_of_band | - | main's facts v5 now reads net income (ifrs-full:ProfitLoss); the second refusal is kd 0.99%, just under the band's 1% floor: interest is ifrs-full:FinanceCosts ($18.1 million) against average borrowings of $1.83 billion. F6 (interest concept) |
| DAC | commodity | facts_stale | facts_stale | no_call facts_stale | - | F6 (facts tag coverage): capex ends 2012 |
| DDI | operating | shares_unavailable | shares_unavailable | no_call shares_unavailable | - | inspected: ifrs-full:WeightedAverageShares 2,477,672 and DilutiveEffectOfAllInstruments 0 are filed for 2025. Found: F6 (IFRS share tags) |
| DEA | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| DXC | operating | tax_unavailable | tax_unavailable | valued (39.63) | tax_rate_median_outside_band | §6(b): the unclamped median of 6 measured years (19.0%, 122.3%, 35.5%, 21.1%, 37.1%, 91.2%) is 36.3%: valued, stamped |
| ECO | commodity | facts_stale | tax_unavailable | no_call tax_unavailable | - | main's facts v5 now reads net income (no longer stale); the second refusal is tax: no pretax income or provision filed (20-F, IFRS), so §6(a) cannot be checked. F6 |
| ECPG | financial | facts_stale | facts_stale | no_call facts_stale | - | F6 (facts tag coverage): equity ends 2021 |
| EFXT | operating | tax_unavailable | tax_unavailable | no_call tax_unavailable | - | §6(b) needs 3 measured years with positive pretax income; EFXT has 2 (60.5%, 60.7%): stays |
| ESEA | commodity | facts_stale | facts_stale | no_call facts_stale | - | F6 (facts tag coverage): capex ends 2020 |
| FLXS | operating | debt_unavailable | debt_unavailable | valued (35.77) | debt_unresolved_bounded_by_interest, kd_unused_delta_zero | no debt tag; interest $22 thousand: at most $2.2 million of debt at the band's 1% floor, against $16.7 million of cash, so net debt is 0, delta is 0 and kd is unused: valued, stamped |
| FRO | commodity | facts_stale | prepares | valued (22.38) | - | main's facts v5 (IFRS ProfitLoss) now reads net income: valued, not by F5 (per_share_basis_unverified is the existing 20-F stamp) |
| GASS | commodity | tax_unavailable | tax_unavailable | no_call tax_unavailable | - | §6(a) cannot be checked: no pretax income and no provision filed under any listed tag (20-F, IFRS). Stays; F6 |
| GCT | operating | debt_unavailable | debt_unavailable | valued (55.15) | debt_unresolved_bounded_by_interest, kd_unused_delta_zero | debt tags stale since 2023 (last 0); interest $0.2 million: at most $20 million of debt at 1%, against $416 million of cash and short-term investments: delta 0, valued, stamped |
| GSAT | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| GSL | commodity | shares_unavailable | shares_unavailable | no_call shares_unavailable | - | inspected: only dei:EntityCommonStockSharesOutstanding (35,913,628); no weighted-average share fact in companyfacts. Absent |
| GTE | commodity | tax_unavailable | tax_unavailable | no_call e0_not_positive | - | §6(b) gives tau = the unclamped median; the second refusal follows: X_0 not positive (no earnings base) |
| HAFN | operating | base_year_not_latest_annual | base_year_not_latest_annual | no_call base_year_not_latest_annual | - | inspected: the stored companyfacts snapshot has no FY2025 revenue or profit fact under any tag, while the 2025 annual report is filed. F6 (re-fetch online; not done here, offline preferred) |
| HG | financial | profitloss_basis_unverified | profitloss_basis_unverified | no_call profitloss_basis_unverified | - | inspected: 2022 ProfitLoss -$29.9 million, net income including non-redeemable NCI -$98.0 million, redeemable NCI $68.1 million, diluted EPS -$0.95: no basis reconciles. Stays a no-call (Q3b N4) |
| HOG | operating | kd_out_of_band | kd_out_of_band | no_call kd_out_of_band | - | kd 0.67%: interest is InterestExpenseNonoperating ($33.4 million) against average debt of about $5.0 billion that includes the finance arm's, whose FinancingInterestExpense ($388.6 million) is not read. F6 (interest and debt on different bases) |
| HRMY | operating | facts_stale | facts_stale | no_call facts_stale | - | F6 (facts tag coverage): D&A ends 2024 |
| HST | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| IHS | operating | facts_stale | shares_unavailable | no_call shares_unavailable | - | main's facts v5 reads D&A now; the second refusal is shares: ifrs-full:WeightedAverageShares 335,046,000 and DilutiveEffectOfShareOptions 6,591,000 are filed. Found: F6 |
| INSW | commodity | tax_unavailable | tax_unavailable | no_call tax_unavailable | - | §6(b): the unclamped median of the 4 measured years (2022-2025: +0.02%, +0.69%, -0.26%, -0.13%) is -0.06%, below 0: stays a no-call as written. A shipper paying ~0% tax; an operator ruling could treat |median| < 1 point as §6(a)'s zero |
| JCAP | financial | shares_scale_unverified | shares_scale_unverified | no_call shares_scale_unverified | - | a 10-K filer with an 11% EPS gap: stays a no-call (§6: only 20-F/40-F filers take the ADS stamp) |
| LAMR | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| LIND | operating | tax_unavailable | tax_unavailable | no_call tax_unavailable | - | §6(b): two measured years with positive pretax income (2018, 2019); the base year is a loss: stays |
| LPG | commodity | facts_stale | facts_stale | no_call facts_stale | - | F6 (facts tag coverage): capex ends 2023 |
| MRP | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| NGVT | commodity | e0_not_positive | e0_not_positive | no_call e0_not_positive | - | X_0 not positive: legitimate (another route) |
| NREF | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| NUTX | operating | nci_dominant | nci_dominant | no_call nci_dominant | - | inspected: NetIncomeLossAttributableToNoncontrollingInterest $109.6 million on pretax $244.8 million (45%; an Up-C structure). The data are right; the K_0 dollar hold is not valid at that share (N9): stays a no-call |
| PACS | operating | input_missing | input_missing | no_call input_missing | - | inspected: no total D&A tag for 2025; CostOfGoodsAndServicesSoldDepreciationAndAmortization ($55.7 million) and ROU amortization are filed. F6 decides whether the cost-of-sales line is the total |
| PRCH | operating | tax_unavailable | tax_unavailable | no_call tax_unavailable | - | §6(b): one measured year with positive pretax income (2025, 42.7%): stays |
| R | operating | bridge_unavailable | bridge_unavailable | valued (165.31) | oi_from_pretax_plus_interest | OperatingIncomeLoss not filed in any year: oi = pretax income + interest expense, every pooled year: valued, stamped |
| SLDE | financial | history_short | history_short | no_call history_short | - | two fiscal-year equity balances: legitimate |
| STT | financial | shares_scale_unverified | shares_scale_unverified | no_call shares_scale_unverified | - | a 10-K filer with an 8% EPS gap: stays a no-call |
| TRN | operating | input_missing | input_missing | no_call input_missing | - | inspected: no AssetsCurrent / LiabilitiesCurrent: an unclassified balance sheet (only *CurrentAndNoncurrent tags). Absent by presentation: stays; working capital from components would be a new method (not built) |
| UNIT | family_not_built | family_not_routed | family_not_routed | no_call family_not_routed | - | stays a no-call before 11-30 (no REIT / pre-profit route) |
| VLRS | operating | history_short | history_short | no_call history_short | - | no filed revenue under any listed tag: F6 (revenue tag coverage) |
| VSNT | operating | shares_unavailable | shares_unavailable | no_call shares_unavailable | - | inspected: no share or EPS fact for 2025 in companyfacts. Absent |
| ZIM | commodity | kd_out_of_band | kd_out_of_band | no_call kd_out_of_band | - | kd 496%: interest $475.1 million includes lease interest $465.5 million, debt is borrowings only ($90.1 million; lease liabilities $5.65 billion). F6 |

## Summary by E3 code

| E3 code | names | callable now | of which by F5 |
|---|---|---|---|
| family_not_routed | 11 | 0 | 0 |
| facts_stale | 8 | 1 | 0 |
| tax_unavailable | 8 | 1 | 1 |
| history_short | 6 | 0 | 0 |
| input_missing | 3 | 0 | 0 |
| shares_unavailable | 3 | 0 | 0 |
| debt_unavailable | 2 | 2 | 2 |
| kd_out_of_band | 2 | 0 | 0 |
| shares_scale_unverified | 2 | 0 | 0 |
| base_year_not_latest_annual | 1 | 0 | 0 |
| bridge_unavailable | 1 | 1 | 1 |
| e0_not_positive | 1 | 0 | 0 |
| nci_dominant | 1 | 0 | 0 |
| preferred_dividends_unavailable | 1 | 0 | 0 |
| profitloss_basis_unverified | 1 | 0 | 0 |

Total: 51 E3 no-calls; 5 callable now, 4 of them by F5's stamps (DXC, FLXS, GCT, R) and 1 by main's facts v5 (FRO). GTE, ECO, CPA and IHS now stop at a second refusal and take its row. Every stamped value carries its stamp in result.json and memo.md, so it is never pooled silently with unstamped ones.

Into F6 from this table: CMRE, GASS, ECO (IFRS pretax and tax tags), CPA, HOG, ZIM (interest and debt on different bases), PACS (total D&A), DDI, IHS (IFRS weighted-average shares), HAFN (FY2025 facts missing from the snapshot), APA, VLRS (revenue), DAC, ESEA, LPG, HRMY, ECPG (stale concepts). Recorded as absent: TRN (unclassified balance sheet), GSL, VSNT (no share facts), BFH (no preferred dividend fact). Operator questions: INSW (a ~0% median just below 0) and BFH (zero dividends on a preferred issued in the base year).
