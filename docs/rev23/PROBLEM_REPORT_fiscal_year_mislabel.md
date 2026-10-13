# Problem report: annual reports assigned to the wrong fiscal year by a forward-looking fact

**Date:** 2026-10-13 23:29. **Author:** the coordinator, fork 2. **Record:** SPEC_rebuild AL.11.

**Status:** open. Nothing has been changed. `pit_data` is under fork 1's scoring hold until `chain/DONE` exists, and any repair is an
operator decision.

## 1. Summary

`pit_data` decides which fiscal year an annual report covers by taking the latest end date among the report's fiscal-year-length
duration facts, in any unit. Some 10-Ks also file a forward-looking annual fact. Boeing's FY2017 10-K, filed 2018-02-12, files the 2018
federal statutory tax rate (21%, unit "pure") for 2018-01-01 to 2018-12-31. That one fact relabels the whole report as FY2018.

**Two consequences:**
1. **A missing year.** At any date in 2018, Boeing's latest fiscal year is FY2016. Its FY2017 does not exist for the system, so its
   inputs are a year stale.
2. **A false early filing date.** In later extractions, the FY2018 row is stamped with the FY2017 report's filing date (2018-02-12),
   although FY2018's revenue was filed in 2019. Any consumer that filters a later vintage's observation table by that stamp takes in
   values from after its cut. That is real look-ahead.

## 2. Evidence

- **Boeing (CIK 12927), vintage-2025 observation table:** the rows are FY2015 (filed 2016-02-10), FY2016 (filed 2017-02-08), and then
  **"FY2018, filed 2018-02-12", revenue 101.127B**. That revenue is FY2018's; FY2017's actual 93.4B is absent.
- **The fact:** `EffectiveIncomeTaxRateReconciliationAtFederalStatutoryIncomeTaxRate`, 0.21, 2018-01-01 to 2018-12-31, accession
  0000012927-18-000007.
- **At T = 2018-06-30** (`pit_data` in as-known mode), Boeing's fiscal years end at 2016-12-31.

## 3. Measurement

Rows whose own report was filed on or before the fiscal year it is said to cover, which is impossible for a true annual report:

| Vintage | Observations | Mislabelled rows |
|---|---|---|
| 2016 | 37,434 | 261 (0.70%) |
| 2018 | 50,131 | 304 (0.61%) |
| 2020 | 62,860 | 373 (0.59%) |
| 2022 | 76,561 | 410 (0.54%) |
| 2024 | 87,183 | 419 (0.48%) |
| 2025 | 91,170 | 402 (0.44%) |

**In the vintage-2025 table, by filing year:**
- 2013 is the peak, with 93 rows.
- 2018 has 44, the year of the tax-reform rate disclosure.
- Recent years have fewer: 2023 has 12, 2024 has 5, and 2025 has none so far.

**By form:** 357 10-K, 39 20-F, 6 40-F.

**In the forecast-study panel** (vintage-2024 observations), outcomes stamped as filed before the end of their own period, estimated from
base fiscal year + k:

| Year | Outcomes so stamped | Of those, with a code forecast |
|---|---|---|
| k = 1 | 16 of 11,602 | 10 |
| k = 2 | 62 of 9,968 | 49 |
| k = 3 | 48 of 8,319 | 27 |

## 4. Root cause

The functions are `valuation/pit_data.py`, `CompanyPit.accessions()` (the own period of an accession) and `fiscal_year_index()`:
- **What sets the period:** any fact with a duration of 350–380 days moves the accession's period to that fact's end, whatever its unit
  or meaning.
- **What is skipped:** the cover-page `dei` facts, including `DocumentPeriodEndDate`, which states the period of report.
- **What is missing:** a check that the period ends before the report was filed.

## 5. Reach

| Consumer | Effect | Measured? |
|---|---|---|
| Every `pit_data` snapshot at a valuation date: engines, gate 1, gate 2, the study's pass | A missing fiscal year means stale inputs for the affected companies around those dates | No; the gate-2 count is for fork 1 |
| Priors v3 observation tables, including those under the frozen `c7d7a4f` | About 0.5% of rows mislabelled or missing a year. Within one vintage there is no look-ahead: values are cut by the store | Counted (section 3) |
| Engine v2 tables `data/priors_v4` (AL.3) | Outcomes and medians come from a later vintage, filtered by the false stamps, so **look-ahead** | Estimated (section 3). Removed by AL.10's per-vintage rebuild |
| The forecast study | Its outcomes are filtered by the same stamps; a small share | Estimated (section 3) |
| The screener | Uses its own history builder, not `fiscal_year_index` | Not checked |

## 6. Proposed fix (for the ruling; nothing is built)

- **The rule:** an accession's period of report is its `dei:DocumentPeriodEndDate` when the store holds it. Otherwise it is the latest
  end of its fiscal-year-length **USD** durations that end **on or before the filing date**. A period that cannot be set is stated.
- **Validation:**
  - every mislabelled row in section 3 is re-checked;
  - Boeing and 20 other rows are checked against the filed cover page;
  - the per-vintage before-and-after diff of the observation tables and priors tables;
  - a test that a forward-dated fact cannot set a period.
- **Holds:**
  - not before fork 1's `chain/DONE`;
  - gate 2's frozen inputs are kept, and the affected company-dates are reported (as AL.8 item 2 for the tag seams);
  - a repair rebuilds the priors as a new version.

## 7. Decisions needed from the operator

1. Approve the fix rule and its validation, to be built after `chain/DONE`.
2. Gate 2 stays on its frozen inputs, with the affected share reported. This is the AL.8 pattern.
3. Engine v2: the AL.10 per-vintage rebuild already removes the look-ahead. The missing years inside each vintage remain until `pit_data`
   is repaired.
