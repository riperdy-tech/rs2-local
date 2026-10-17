# Step 1a addendum: routing, δ on one basis, raw amounts, concessions

*2026-10-18. Answers `RULINGS_step1a_outside_review.md` accepted points 1–5, 8 and 10. Script: `scratch/rev23/terminal_d2/census_1a_addendum.py`;
table: `census_1a_routing.json` (all 160 rows, each with its evidence and raw five-year amounts). Concession screen: §5.*

## 1. The desk routing table

The rule is the one stated in the script header:
- **Financial** when a balance-sheet test confirms it: insurance reserves ≥ 10% of assets, a lending book ≥ 50% of assets on the widened
  loan tags, or deposits ≥ 50% of liabilities.
- **Also financial:** a broker-dealer SIC; a credit SIC whose borrowings fund ≥ 50% of liabilities; an insurer SIC with investments ≥ 50% of
  assets where reserves are not tagged; a real-estate SIC with a lending book or repurchase-agreement funding ≥ 20% of assets.
- **Operating with real-estate treatment:** other real-estate SICs.
- **Operating:** everything else.

**Counts by route:** operating 125, financial 21, real estate 14.

- **Financial (21):** ACIC AII ALL ARX BFH CIM CTBI ECPG HG HRTG JCAP MCY OPY RNR SEZL SLDE STT TOP UFCS UVE WTM
- **Real estate (14):** ALX AMT CBL CLDT DEA DRH HST LAMR LXP MRP NREF OUT RHP STRW

| Acceptance case | Expected | Routed | Evidence |
|---|---|---|---|
| V | operating | operating ✓ | SIC 6099 not confirmed: no lending, deposit or insurance book; borrowings 41% of liabilities |
| MA | operating | operating ✓ | SIC 7389 |
| STT | financial | financial ✓ | deposits 81% of liabilities (SIC 6282 says investment advice) |
| SEZL | financial | financial ✓ | lending book 71% of assets (widened tags; SIC 7389) |
| ECPG | financial | financial ✓ | NotesReceivableNet 82% of assets |
| JCAP | financial | financial ✓ | credit SIC 6153, borrowings 109% of liabilities (its receivable portfolios are tagged by company extension) |
| CIM | financial | financial ✓ | repurchase agreements 38% of assets |
| WTM | financial | financial ✓ | insurer SIC, investments 68% of assets; reserves not tagged in companyfacts |
| **NREF** | financial | **real estate ✗, unresolved** | its consolidated CMBS trusts are tagged by company extension; no standard tag reaches 15% of assets |
| **PGY** | financial | **operating ✗, unresolved** | 61% of assets are available-for-sale debt securities (its own securitizations), borrowings only 20% of liabilities. No general test separates this from a cash-rich company holding securities |
| RHLD | — | operating | SIC 3572 from SEC (the 2026-10-06 census had 6199 from the harness file). It consolidates an operating company; operating is right |
| PRCH | — | operating | insurer SIC, reserves 6% of assets, investments small: the reciprocal insurer is no longer the main book |

**Two acceptance cases fail by general rule, NREF and PGY.** Adding their own tags would be a per-company rule, which the design rules
forbid. Ruling: both are routed as shown and stamped `route_unresolved_credit_assets_extension_tagged`. The analyst receives a reason
request, and step 4's hand check reads their balance sheets. A general fix belongs in the pack, which reads the filing's own balance
sheet rather than companyfacts' standard tags.

## 2. δ on one currency basis, without leases

- **Leases are excluded from net debt and from k_d.** The lease interest tags (`FinanceLeaseInterestExpense`,
  `InterestExpenseOnLeaseLiabilities`) are subtracted from interest.
- **The financial route takes no δ:** ECPG, JCAP, CIM, STT and the insurers leave the δ list.
- **The six non-USD reporters** (CHA KOF LPL RNW TLK UMC) all get δ = 0, stamped `delta_fx_unproven`. None is in `fx_normalize.py`'s
  proven-currency table.
- **The hand check shows why** an unproven conversion must not be used. At the period-end rate (yfinance, as fx_normalize uses):
  - TLK's filed net debt converts to $29 thousand, a units or scale defect in the store's IFRS facts;
  - UMC's screener market cap is $61.7B, which looks like a quote-side scale or perimeter defect;
  - KOF's and LPL's latest annual facts in the store are FY2020 and FY2009, so the store is stale for them.

  Neither source is fit for these names until fx_normalize's proof procedure covers them. Seven names have a base year before 2025 (CX,
  HAFN, KOF, LPL, TLK, UMC, VLRS); their census rows size the cases but are not inputs.

## 3. Raw amounts and unstable ratios

- **Raw amounts:** every row now carries the pooled five-year raw amounts behind its ratios (net income, D&A, capex, owner earnings,
  acquisitions, lease principal, ROU depreciation, REIT capital improvements, development and acquisitions).
- **Unstable ratios, 36 names:** 35 have non-positive five-year net income, so acquisitions over net income is not computed for them
  (they are not counted as acquirers); 2 have a non-lease k_d outside 0–25% (KOF, RNW).
- The census case counts stand, with that qualification on the acquirer count.

## 4. Changes from the 1a report

- **The financial route is 21 names, not 20:**
  - out: V and PRCH;
  - in: STT, SEZL and CIM;
  - JCAP and WTM stay, confirmed by the funding and investment tests rather than by SIC alone.
- **Real estate is 14 names:** CIM moves to financial.

## 5. Concession screen

*Filled in when the full-text screen completes. It is in progress, run by a fresh agent under `briefs/BRIEF_1a_concession_screen.md`.*
