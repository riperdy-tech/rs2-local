# Brief D2b1: desk port part (b), screener side: the filed fields D2 needs (L1 and the vintage and amortization inputs)

## Read first
1. `docs/review_2026-09-22/rev23/PLAN_terminal_reinvestment.md`: §3a (with its amendment) and the "Port part (a) audited" block at the end.
2. `docs/review_2026-09-22/rev23/REPORT_step2_lease_audit.md`: §1 and §4 (L1).
3. `stock-screener/AGENTS.md`.
4. In `scripts/build_fundamentals_history.py` **on `origin/main`**, read by grep and section:
   - `DURATION_TAGS`, `INSTANT_TAGS`, `FIELD_SPECS`, `INSTANT_FIELD_SPECS`, `DURATION_LADDER_SPECS`, `VOTE_EXCLUDED_FIELDS`;
   - the refusal comments near the `*NextTwelveMonths` and `DepreciationRightofuseAssets` lines;
   - `prov_bundle` and `encode_provenance`.

The dev checkout (`stock-screener`, another session's branch) is stale. Do not use it or touch it.

## Workspace and limits
- **Worktree:**
  ```
  git -C C:/Users/riper/stocks/stock-screener fetch origin
  git -C C:/Users/riper/stocks/stock-screener worktree add -b review-2026-10/d2-fields ../stocks-workspace/scratch/rev23/wt-d2-fields origin/main
  ```
- **Commit by pathspec.**
- **Never:**
  - push, merge or deploy (Vercel deploys from this repository);
  - publish, or touch `screener-publish`;
  - write to `public/data/` (any test output goes under a temp directory);
  - edit `.env*`, CI or deploy config;
  - use a bare `git stash`.
- **Your report is at most 50 lines.**

## Build
Add **new fields only**. No existing field's value, tag order or provenance may change for any ticker.

| Field | Kind | Tags, in priority order |
|---|---|---|
| `lease_principal` | duration | us-gaap FinanceLeasePrincipalPayments, RepaymentsOfLongTermCapitalLeaseObligations; ifrs PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities |
| `lease_interest` | duration | us-gaap FinanceLeaseInterestExpense; ifrs InterestExpenseOnLeaseLiabilities |
| `rou_depreciation` | duration | ifrs DepreciationRightofuseAssets; us-gaap FinanceLeaseRightOfUseAssetAmortization |
| `interest_on_borrowings` | duration | ifrs InterestExpenseOnBorrowings, else ifrs FinanceCosts less `lease_interest` of the same year (stamped `component_sum`, i.e. derived) |
| `ppe_gross` | instant | us-gaap PropertyPlantAndEquipmentGross; ifrs PropertyPlantAndEquipmentGrossCarryingAmount if it exists in the store (check, do not assume) |
| `amortization_schedule` | instant, per filing year | FiniteLivedIntangibleAssetsAmortizationExpenseNextTwelveMonths, …YearTwo, …YearThree, …YearFour, …YearFive, …AfterYearFive, stored as `{y1..y5, thereafter}` for the year whose filing carries it; partial sets kept with the missing keys absent |

- **Positive amounts.** Sign conventions follow the neighbouring fields: flows that are reported negative are stored positive, as the existing amortization IFRS rung does.
- **Two recorded refusals stay in force for the old fields.** `DepreciationRightofuseAssets` still never enters `da`, and `*NextTwelveMonths` still never fills a history value. Each new field is a separate key. Amend the two refusal comments to say so and to name the new field, citing PLAN_terminal_reinvestment.md §3a.
- **`interest_expense` is unchanged.** The IFRS borrowing interest goes in its own field, and the pack decides how to use it.
- **Every new field:**
  - goes in `VOTE_EXCLUDED_FIELDS` (it must never steer the accession vote);
  - carries provenance (source tag and state) like the others;
  - is listed in whatever schema or field list the builder owns (non-negotiable 5: single owner per field).

## Tests (system Python; run the screener suite per its AGENTS.md)
1. **New-field tests:**
   - fixtures for one US GAAP filer and one IFRS filer per field;
   - `FinanceCosts` less lease interest is stamped as derived;
   - a partial amortization schedule.
2. **No change to existing output.** Run the builder on a fixed subset of at least 12 real tickers (AZN, NVS, BUD, EQNR, MU, AAPL, XOM, MSGE, PACS, DAC, VLRS, AMT) from `companyfacts.zip`, read-only via `--zip`, writing to a temp directory, once at `origin/main` and once on your branch.
   - Every pre-existing field and its provenance must be identical.
   - Report the diff restricted to new keys, plus per new field the coverage: how many of the 12 have it in their latest year.
3. **The full screener suite:** the same failures by name as `origin/main`.

## Report
- commits;
- files, one line each;
- test counts;
- the coverage table;
- the identical-output proof (which command, which comparison);
- ambiguities, each marked for a ruling.
