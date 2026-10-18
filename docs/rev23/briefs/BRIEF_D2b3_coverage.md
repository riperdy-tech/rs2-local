# Brief D2b3: the D2 coverage round (operator approved fixes 1–5, 2026-10-18)

The census (`scratch/rev23/d2_coverage/`, see `measure.json` and `tags_recent.json`) found that `d2` is complete for 57 of 160 names.
The gaps:
- kd is missing for 54 names, because interest is filed under unread tags;
- delta is missing for 38;
- pooled capex/D&A is missing for 34.

**Rule for every part: no existing field changes value, tag or provenance.** The new D2-only fields sit beside the old ones. Today's
legacy numbers must not move.

There are two parts, run by two builders in parallel. The field names below are fixed, so neither waits for the other.

## Part S: screener (branch `review-2026-10/d2-fields`, worktree `scratch/rev23/wt-d2-fields`, new commits on top of `5b30e90761`)
Read `briefs/BRIEF_D2b1_screener_fields.md` first. Its limits all apply: no push, merge, deploy or publish; never `public/data`; never the
dev checkout; commit by pathspec.

1. **`interest_on_borrowings`, extended.** The rungs, in order:
   1. ifrs InterestExpenseOnBorrowings;
   2. ifrs InterestExpenseOnBonds + InterestExpenseOnBankLoansAndOverdrafts (the filed ones, summed; state `component_sum`);
   3. us-gaap InterestExpenseNonoperating.

   FinanceCosts stays refused. The winning tag is in provenance, and the rs2 side reads it.
2. **`capex_d2` (new, duration).** Per year:
   - if `capex` (the existing field) resolves, `capex_d2` equals it, with state `from_capex`;
   - else the first rung that is filed, from:
     PaymentsForProceedsFromProductiveAssets (`net_of_proceeds`),
     PaymentsToAcquireOilAndGasPropertyAndEquipment,
     PaymentsToExploreAndDevelopOilAndGasProperties,
     ifrs PurchaseOfMiningAssets,
     PaymentsForConstructionInProcess (`construction_in_process`),
     PaymentsToAcquireMachineryAndEquipment,
     ifrs PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets
     (`includes_intangibles`),
     PaymentsToAcquireOtherPropertyPlantAndEquipment (`other_ppe_partial_risk`; it is ungated here, but only as the last single tag);
   - else the real-estate component sum of the filed ones among PaymentsToAcquireRealEstate, PaymentsToDevelopRealEstateAssets,
     PaymentsForCapitalImprovements and PaymentsToAcquireLand (state `component_sum`, `real_estate_components`).

   PropertyPlantAndEquipmentAdditions is refused (it is not a cash flow). Each class marker named above rides in provenance.
   **Double-count check:** for CBL, LXP, RHP, DEA, MRP, INSW, MSGE, GSL, GSAT and APA, compare the base year's `capex_d2` with the vendor's
   `Capital_Expenditure` (`stock-screener` vendor financials files, read only) and report the ratio. Flag any ratio above 1.3 or below 0.7.
3. **`debt_d2_total` (new, instant): non-lease debt.** Per year:
   - if the existing ladder resolves, use (`debt_lt_noncurrent` or `lt_debt`) + `debt_current` + `short_term_borrowings_separate`, the
     way `rs2-local/tools/throughcycle_record.invested_capital` and `short_term_debt` read them. Mirror its arithmetic exactly and say
     where it lives; state `from_ladder`;
   - else the first total filed: DebtLongtermAndShorttermCombinedAmount, ifrs Borrowings, DebtInstrumentCarryingAmount;
   - else a component sum of the filed ones among LongTermNotesPayable, NotesPayable, ConvertibleDebtNoncurrent, ConvertibleDebtCurrent
     and OtherLongTermDebtNoncurrent. SeniorNotes is used only when LongTermNotesPayable is not filed, because it is usually a subset.
     State `component_sum`.

   Lease liabilities are never included. Check BUD, VEON, BIP and 5 of the US names against vendor `Total_Debt` less filed lease
   liabilities, and report the ratios.
4. **Tests:**
   - fixtures per rung and per state;
   - the 12-ticker identical-output proof for every pre-existing field (and for the 11 earlier D2 fields, except `interest_on_borrowings`,
     whose changed years you list);
   - the full screener suite.
5. **Report (≤40 lines):**
   - commits;
   - coverage of the three fields on the 160 census names, using the census's runner in `d2_coverage` (`data` into a new temp folder);
   - the two check tables;
   - ambiguities, each marked for a ruling.

## Part R: rs2 (branch `review-2026-10/d2-facts`, worktree `scratch/rev23/wt-d2-facts`, new commits on top of `286409a`)
Read `briefs/BRIEF_D2b2_pack_facts.md` first. Its limits all apply: no push, merge or deploy; no GPU or model calls; nothing the model
reads changes; commit by pathspec.

1. **kd.** The interest is chosen in this order:
   1. `interest_on_borrowings` when filed;
   2. else `interest_expense`.

   Lease interest is subtracted when the source is `interest_expense` or the Nonoperating rung of `interest_on_borrowings` (read the winning
   tag from provenance). It is never subtracted from an IFRS borrowings rung. Stamp the source.
2. **Capex.** Pooled and `year0` capex come from `capex_d2` when `capex` is null, with its class markers carried into `d2_provenance` and the
   stamps.
3. **Debt.** δ, kd and `year0.invested_capital` use `debt_d2_total` when the existing ladder is absent, stamped `debt_from_d2_total`.
   - `invested_capital` in `throughcycle_record` and `r_tc` stay unchanged.
   - `year0.invested_capital` under D2 uses the same debt as δ. Say so in a comment.
4. **Fix 4, the debt-free rule.** No debt tag in any window year means `debt_d2_total` is null in every year. Then non-lease debt is set to
   0, stamped `debt_zero_inferred_leases_only`, but only when the vendor `Total_Debt` is 0, or is at most 1.10 × the filed lease liabilities
   (`finance_lease_liability` + `operating_lease_liability`, base year). Otherwise it stays `delta_debt_not_filed`. Never 0 without that
   test.
5. **Tests:** unit tests per rule. Add the two new keys `capex_d2` and `debt_d2_total` to `REVIEWED_HISTORY_KEYS` (the same comment as
   before), with the byte-identical pack-text test. The full suite must show the same 42 failures by name.
6. **Report (≤30 lines):**
   - commits;
   - files;
   - test counts;
   - ambiguities.

## Part M: re-measure (coordinator, after S and R)
Item 5: run `d2_facts` inside the real pack build (real price, shares, π and vendor FX) for the 160 names, using S's rows. Report:
- the complete count;
- the remaining gaps by name and reason;
- the stamp counts by class.
