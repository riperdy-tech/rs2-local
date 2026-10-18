# Brief D2b4: D2-only `da_d2` and `revenue_d2` (operator approved, 2026-10-18)

Evidence: `PLAN_terminal_reinvestment.md`, the item "D&A gap measured", and `scratch/rev23/d2_da/da_tags.json`.

**Rule: no existing field changes value, tag or provenance.** Today's numbers do not move. Two parts, built in parallel; the field names
below are fixed.

**Memory and GPU.** A Qwen GPU run is live and RAM is tight.
- Never touch Ollama or the GPU.
- Read the companyfacts store one CIK at a time.
- Run targeted tests only. The coordinator runs the full suites after the GPU run ends.

## Part S: screener (`review-2026-10/d2-fields`, worktree `scratch/rev23/wt-d2-fields`, new commits on top of `65328f973e`)
All limits of `BRIEF_D2b1_screener_fields.md` apply. The store for proofs is `scratch/rev23/sec_data/companyfacts_2026-10-18.zip`.

1. **`da_d2` (duration).** Per year:
   - `da` when it resolves (state `from_da`);
   - else `CostOfGoodsAndServicesSoldDepreciationAndAmortization` (marker `cogs_da`);
   - else `ResultsOfOperationsDepreciationDepletionAmortizationAndAccretion` (marker `includes_accretion`);
   - else a lone `Depreciation` / `DepreciationExpense` (ifrs) / `DepreciationNonproduction`, **only when the filer files no
     amortization series** (none of the amortization tags the `da` component slots read) in **any** year of the five-year window ending
     that year (marker `da_lone_depreciation`).

   Never a component sum. Never `SECScheduleIII…`.
2. **`revenue_d2` (duration).** `revenue` when it resolves (state `from_revenue`), else `RevenueFromRenderingOfTransportServices` (ifrs)
   (marker `transport_services_revenue`).
3. **Both fields:** vote-excluded, in `D2_FIELDS`, with schema text; `capex_test`-style loops skip them as `capex_d2`'s do.
4. **Tests:**
   - fixtures per rung and marker, including a lone-depreciation case refused because amortization is filed in one window year;
   - the 12-ticker identical-output proof for every pre-existing and earlier D2 field (use the fresh store at both commits);
   - a 14-name build (FLXS GASS ESEA FRO DRH PACS SM STT PTEN MRP TLK VLRS OPTX RNW) reporting `da_d2` / `revenue_d2` per name and year.
   - Screener test files touching fundamentals only.
5. **Report (≤25 lines):** commits, test counts, the 14-name table, ambiguities.

## Part R: rs2 (`review-2026-10/d2-facts`, worktree `scratch/rev23/wt-d2-facts`, new commits on top of `84ae50c`)
All limits of `BRIEF_D2b2_pack_facts.md` apply.

1. **Fallbacks.** Pooled and `year0` D&A use `da_d2` when `da` is null. Pooled revenue uses `revenue_d2` when `revenue` is null. The
   D&A_org arithmetic (`da − rou_depreciation − amortization_intangibles`) is unchanged.
   - For `da_lone_depreciation` there is no amortization to subtract. State that in a comment.
2. **Vendor checks** (the same rule and band as `capex_d2`, including the absent-vendor stamp):
   - **Rung-sourced `da_d2`:** check against the vendor's `Calculated_Metrics.Depreciation_Amortization` (TTM, base year). Stamp
     `da_d2_rung_vendor_agrees`, `da_d2_vendor_disagrees` or `da_d2_rung_unverified`.
   - **Rung-sourced `revenue_d2`:** check against the vendor's annual revenue for the same fiscal year, when the vendor holds it.
3. **Markers** ride into `d2_provenance` and the stamps.
4. **Add both keys** to `REVIEWED_HISTORY_KEYS`, extending the byte-identical pack-text test.
5. **Tests:**
   - unit tests per rule;
   - `test_d2_facts.py` and the pack-text test only;
   - do not run the full suite.
6. **Report (≤20 lines):** commits, files, test counts, ambiguities.
