# Step 2 report: the lease audit

*2026-10-18. Step 2 of `PLAN_terminal_reinvestment.md`, under `RULINGS_step1a_outside_review.md` points 5–7. No GPU, no code change yet.
Harness: `scratch/rev23/terminal_d2/synthetic.py` (firm I); traces from the companyfacts store and the screener's
`fundamentals_history.json`, which the pack reads.*

## 1. Where the pack's figures come from

`stock-screener/scripts/build_fundamentals_history.py` owns the fields the pack's base_cf and r_tc read:
- `da`: DepreciationDepletionAndAmortization or DepreciationAndAmortization (US GAAP), DepreciationAndAmortisationExpense or
  AdjustmentsForDepreciationAndAmortisationExpense (IFRS);
- `capex`: PaymentsToAcquirePropertyPlantAndEquipment, PurchaseOfPropertyPlantAndEquipment…;
- `interest_expense`: InterestExpense or InterestExpenseDebt, **US GAAP tags only**.

It holds lease liabilities, but **no lease principal and no lease interest field.**

`rs2-local/tools/throughcycle_record.py` builds r_tc as (X + interest × (1 − t)) / tangible invested capital. Invested capital is tangible
equity + debt − cash − investments, with **leases excluded from debt**.

## 2. Traces (base fiscal year, $B)

| Name | Lease regime | D&A | Lease depreciation inside it | Lease principal paid | Lease interest | Owner earnings today | Owner earnings less lease principal |
|---|---|---|---|---|---|---|---|
| BUD | IFRS 16 | 5.652 | 0.742 (`DepreciationRightofuseAssets`) | 0.733 | 0.144 | 8.83 | 8.10 (−8%) |
| EQNR | IFRS 16 | 9.838 | included (IFRS 16; not tagged separately) | 1.459 | 0.120 | ≈ 0.9 | **≈ −0.6: refused by `base_cf must be positive`** |
| MU | US finance leases | 8.352 | 0.335 (`FinanceLeaseRightOfUseAssetAmortization`) | 0.323 | 0.127 | ≈ 1.03 | ≈ 0.71 (−31%) |
| MSGE | US operating leases only | 0.058 | none | none (operating payments 0.038 are rent, inside net income) | — | unchanged | unchanged |
| PACS | US operating leases (0.33 of payments); finance tiny | — | 0.005 | 0.002 | 0.011 | unchanged in effect | −0.002 |
| EAT | US finance leases small | not filed under the D&A tags | 0.026 | 0.026 | 0.006 | the census's 0.76 ratio was a D&A gap, not leases | — |

**What it shows:**
- **IFRS 16 filers:** lease depreciation is inside D&A and the principal never leaves the flow. Owner earnings are overstated by about the
  principal. Same for US finance leases.
- **US operating leases:** rent is already in net income and lease amortization is not in D&A. Deducting their payments would charge rent
  twice (Gemini's warning). They get **no** adjustment. MSGE's and PACS's D&A-above-capex seam is not a lease effect.
- **EQNR is refused once the fix applies.** Its true owner earnings are negative in FY2025: capex above D&A plus the lease principal.
  That makes O7 relevant to a live name, not only to synthetic firm G.

## 3. Firm I: what a correct fix must contain

Firm I is firm A with its capacity leased under IFRS 16 (5% lease rate, 15-year leases). Its true value is 1.681.

| Desk input | Value | Error | PV years 1–5 | PV fade | PV terminal |
|---|---|---|---|---|---|
| Today | 1.731 | +3.0% | 0.750 (true 0.382) | 0.395 | 0.590 |
| (a) base_cf less lease principal, nothing else | 1.363 | **−18.9%** | 0.382 ✓ | 0.395 | 0.590 |
| (b) (a) + return on capital measured after lease interest, on capital excluding lease-funded assets | **1.681** | **+0.0%** | 0.382 | 0.523 | 0.780 |

Today's +3.0% is two large errors that offset. Years 1–5 are double the truth, and the fade and terminal are a third too low. Fixing
base_cf alone, as the plan first proposed, makes the value 19% too low. ChatGPT's point is proved: **the fix must hold in all three
periods.** The terminal is right only when RONIC is measured on the same basis as the flows. That means leases are treated as 100%
lease-funded capital: the ROU asset nets against the lease liability, and the return is after lease interest. Then the growth reinvestment
charged is only what equity and debt fund.

The pack's invested capital already excludes the lease liability (§1), so the capital side is right. The numerator is not, in two ways:
- **IFRS filers:** `interest_expense` holds no IFRS tag, so their r_tc adds back no interest at all. Levered IFRS filers' returns are
  understated.
- **US filers:** `InterestExpense` can include finance-lease interest, which then inflates the numerator against a capital that excludes
  the lease. ZIM: interest 0.475 on large leases.

## 4. The fix (specified; implemented in step 3's desk revision)

| # | Owner | Change |
|---|---|---|
| L1 | `stock-screener/scripts/build_fundamentals_history.py` (the field owner; non-negotiable 5) | New fields `lease_principal` (FinanceLeasePrincipalPayments, RepaymentsOfLongTermCapitalLeaseObligations; IFRS PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities) and `lease_interest` (FinanceLeaseInterestExpense; IFRS InterestExpenseOnLeaseLiabilities). `interest_expense` gains IFRS tags for interest on borrowings (InterestExpenseOnBorrowings, then FinanceCosts less lease interest), each stamped with its source tag |
| L2 | the pack's base_cf (rs2-local) | base_cf = NI + D&A − capex − lease_principal, stamped `lease_principal_deducted`. US operating leases are untouched |
| L3 | `throughcycle_record.return_numerator` | interest added back = interest_expense − lease_interest (the return after lease interest, on capital that already excludes leases) |
| L4 | invested capital | unchanged: it already excludes lease liabilities, which firm I shows is the right basis |

**Why the code waits for step 3.** L1 changes a shared artifact in the screener, which the nightly chain rebuilds. L2 and L3 change the
desk's inputs. All three are one desk revision with D2 and must be registered together (step 7). Landing them separately would make two
revisions of the same numbers. Step 3's acceptance therefore includes:
- firm I at ±3%, with today's +3.0% recorded as a cancellation, not a pass;
- BUD, EQNR, MU and MSGE re-traced against these figures.

## 5. Consequences

- Names whose owner earnings fall with L2 (from the census and these traces): BUD, EQNR, MU, VLRS, VEON, UMC, ZIM, HAFN, IHS, JBS, DXC,
  KSS and other IFRS 16 or finance-lease filers. Step 6 reports the refusal count after L2 and O5 by name. EQNR is the first known new
  refusal.
- The plan's step 2 line ("deduct lease principal in base_cf") was incomplete. This report replaces it with L1–L4.
