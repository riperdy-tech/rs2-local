# Problem report: revenue series stitched from different XBRL tags give false growth

**Date:** 2026-10-13 23:07 KST. **Author:** the coordinator, fork 2. **Records:** SPEC_rebuild Addenda AL.6 and AL.7; fork 1's AK.26.

**Status:**
- open; nothing has been changed;
- **a decision for the operator** (section 8).

## 1. Summary

The SEC extractor shared by the screener and the analyst picks one winning XBRL tag per company for revenue: the tag whose latest year
is most recent. It then fills the years that tag lacks from other revenue tags. The result is a series whose years can come from different
tags, and those tags do not always measure the same thing. Growth computed across the join between two tags (the "seam") can be badly
wrong. Examples:
- **+1,544%** where the filing shows +8.2%;
- **+137%** where the filing shows +3.8%;
- **−54%** where the filing shows +27%.

In a sample of 300 companies of the $300M+ study universe:
- 7.3% of consecutive-year pairs cross a tag change;
- the growth across the change is off by more than 5 points in 0.55% of all pairs;
- it is off by more than 20 points in 0.47%.

It is not a look-ahead leak: each cut reads only filings made before it. It is a data-correctness defect in a shared component, and the
same mechanism very probably affects the other fields resolved the same way, which have not been measured (section 6).

## 2. Why it matters for real money

Revenue growth is an input at three points, and a false figure distorts each one:
- **The priors:** the analyst's population priors (the features `g_latest`/`g3` and the growth cells).
- **The near-term tables:** engine v2's near-term residual tables, which set the width and tails of its forecasts.
- **The outcomes:** gate 2's q1 outcomes, which carry the hard bars, and its annual outcome (section 6, corrected).

The errors are rare but very large, so they sit in exactly the tails that set risk. A company whose own history contains a false collapse
or a false doubling is valued on a wrong trend.

## 3. Evidence: five cases

The cut is 2026-01-01, `first_filed` mode, read from the shared store (`pit_data`). The last column shows what year t's own annual report
files for both years, from the same accession.

| CIK | Year t | Extracted: year t−1 → year t | Extracted growth | Year t's own filing (accession), both years |
|---|---|---|---|---|
| 1042893 | FY2018 | 455.5M `Revenues` → 337.5M `RevenueFromContractWithCustomerExcludingAssessedTax` | −25.9% | `Revenues` 455.5M → 384.6M, **−15.6%** (0001042893-19-000003). The contract tag is filed for 2018 only. |
| 835011 | FY2018 | 22.9M `Revenues` → 376.1M contract-revenue tag | **+1,544%** | contract revenue 347.4M → 376.1M, **+8.2%**. `Revenues` here is a 20-million side line (22.9M → 19.8M) (0001628280-19-002041). |
| 46080 | FY2017 | 2,194.7M `Revenues` → 5,209.8M `SalesRevenueNet` | **+137%** | `SalesRevenueNet` 5,019.8M → 5,209.8M, **+3.8%** (0001193125-18-058659). |
| 76267 | FY2019 (ends 2019-03-03) | 111.2M `Revenues` → 51.1M `RevenueFromContractWithCustomerIncludingAssessedTax` | **−54%** | the same tag 40.2M → 51.1M, **+27%** (0001437749-19-010516). |
| 1720446 | FY2018 | 314.9M `SalesRevenueNet` → 530.2M contract-revenue tag | +68% | `Revenues` 2,048.9M → 3,645.3M, **+78%**. The contract tag is the full figure in 2016–2017 but a 530M slice in 2018 (0001564590-19-011452). |

**Two failure modes appear:**
- **(a) Seam:** two tags of different scope are joined, as in 1042893 and 1720446.
- **(b) Partial line:** the tag that won for some years is a partial line, not the total. Examples: 835011 (`Revenues` = 22.9M against
  a 347M business) and 46080 (a FY2016 `Revenues` of 2,194.7M against `SalesRevenueNet` of 5,019.8M).

Both show up as a tag change between consecutive years.

**The same filing read at two cuts gives different values (AL.6):**
- 1042893 FY2018 is 384.6M at the 2025-01-01 cut and 337.5M at the 2026-01-01 cut.
- CIK 78003 FY2023 is 50.9B at the first cut and 58.5B at the second.

A later filing changes which tag "wins" for the whole series, so the join moves.

## 4. Measurement

The scripts are `scratch/rev23/engine_v2_audit/tag_breaks_sample.py` and `tag_breaks_effect.py`; the outputs are the `.json` files beside
them. Both are read-only, run at low priority, from a seeded draw (seed 20261013) at the 2026-01-01 cut.

| Sample (300 drawn each) | Companies with a tag change | Consecutive-year pairs | Pairs crossing a tag change | Checkable against the filing | Off by > 1 pt | > 5 pt | > 20 pt |
|---|---|---|---|---|---|---|---|
| All filers (`sic_by_cik`); 292 with data | 96 | 1,641 | 123 (7.5%) | 118 | 17 (1.0%) | 9 (0.55%) | 6 (0.37%) |
| The $300M+ study panel's companies | 131 | 2,343 | 170 (7.3%) | 165 | 19 (0.81%) | 13 (0.55%) | 11 (0.47%) |

The percentages in the last three columns are of all pairs; the counts are of the checkable pairs.

**How "off" was measured:** against the growth that year t's own annual report gives for its two years.
- **Main rule:** year t's tag, with year t−1 taken from that report's comparative column.
- **Fallback, when that filing has no comparative under year t's tag:** year t−1's tag for both years (2 pairs in the first
  sample, 4 in the second).

Large errors cluster in 2018–2019, the ASC 606 transition, but occur in every period from 2015 to 2023.

**Limits of the measurement:**
- **The reference is not ground truth.** It is the growth of one consistently tagged figure. Where that tag is itself a slice, the reference
  is the slice's growth. Case 1720446 shows this: the contract-tag reference says −74%, but the true total, `Revenues`, grew +78%. The
  counts above are therefore an estimate of the order of size, not an audit.
- **No hand check yet.** No case has been checked against the filed income statement itself. Section 7 adds one.
- **Revenue only.** Section 6 covers the other fields.
- **300 companies per sample.** The full-universe count is still to do.

## 5. Root cause

The extractor is `valuation/vendored/build_fundamentals_history.py`. It is a byte-identical copy of the screener's production extractor
(`screener-publish`), checked by a sha256 test; `pit_data` runs it unchanged on a cut document. The relevant function is
`resolve_field_series`:
1. **The primary tag wins on recency.** `annual_duration_series` picks one winning tag by "most RECENT latest-year wins, then most
   coverage". When a company starts filing a new tag, that tag becomes the winner for every year it covers, once a filing that carries it
   exists before the cut.
2. **The other tags backfill.** Every other tag in the `COMBINED` revenue list fills only the years the winner lacks. This stitching was
   added deliberately ("FIELD SPECS (2026-08-20)"): the single-winner rule left gaps that were measured as about 85% of the revenue,
   pretax and operating-cash-flow nulls.

   That stitching is what creates the seam. The single-winner function "never mixes tags", in the code's own words. The backfill layered
   on top of it does mix them, year by year, and nothing checks that the joined tags have the same scope.

The extractor already knows this hazard for banks. Its bank rule refuses a listed tag "in every year and every output, never mixed (an ASC
606 slice in one year beside net revenue in the next would manufacture growth)". Operating companies have no such guard.

## 6. Reach

| Consumer | How it is affected | Measured? |
|---|---|---|
| Priors v3 observation tables, all vintages 2016–2025 | Growth features and growth cells include false growth | Indirectly: the panel sample above draws on the same obs |
| The frozen gate-2 engine and priors (`c7d7a4f`) | The same priors, so the inputs of gate 2's 600 company-dates | No: the count of gate-2 company-dates with a seam in their input history is still to do |
| Engine v2 near-term tables, 2016–2025 (`data/priors_v4`) | False growth outcomes land mostly in the P1/P99 residual tails | No |
| Gate 2's annual outcome | r0/m0 at cut T against r1/m1 at a later cut; a seam or a moved join corrupts it | Not measured. Registered before any outcome is read (AK.27): the year-1 10-K's own comparative column, reported beside the current version |
| Gate 2's q1 outcomes (the hard bars) | **Exposed.** `pit_data.quarters` picks a tag per period, so the q1 quarter and its year-earlier comparative can sit on different tags. AK.26 said "not affected"; fork 1 corrected that in AK.27 | Not measured. Registered before any outcome is read (AK.27): growth and margin change from the q1 filing's own comparative columns (one accession, one tag); Audit 1 reports both versions; the operator decides which governs before any score is read |
| The screener's shipped fundamentals history (live site) | The same code in "as known" mode; the recency winner and backfill apply the same way | No: very probably affected, not yet measured |
| Other `COMBINED` fields (pretax income, operating cash flow, capex, operating income, D&A, shares, SBC) | The same backfill mechanism | No |

## 7. Proposed fix (for the ruling; nothing is built)

Non-negotiable 2 applies: the fix belongs in the extractor, never in a consumer and never per ticker. In order of size:

**F1. Annotate the seam (small; recommended now).**
- **What:** the extractor already returns the winning tag per year. Every year whose tag differs from the year before is stamped
  `tag_seam` in `pit_data`'s output.
- **Consumers:** growth across a seam is reported with the flag. Each consumer's registration states how flagged values are treated;
  under non-negotiable 3 they are annotated, never silently deleted.
- **Effect:** this changes no value, so it can land without moving any frozen number.

**F2. Same-filing growth (medium).**
- **What:** growth for year t is taken from year t's own annual report: both years under one tag, the report's own comparative column.
  Where that report has no comparative, the growth is stamped and left to the consumer.
- **Effect:** this removes failure mode (a). It does not fix (b) when the slice is consistent across years, as in 1720446's contract tag.

**F3. Total-revenue check (larger).**
- **What:** the winning tag must be the total, not a line within it. A closure test against other filed facts of the same filing decides,
  for example revenue ≥ any revenue component, and gross profit plus cost of revenue = revenue where both are filed.
- **Effect:** this removes failure mode (b).

**Validation, before any adoption:**
1. **Hand check:** 20 seams against the filed income statements (SEC download, standing approval).
2. **Full-universe count:** every company, every vintage.
3. **Effect on the priors:** the per-vintage change in the priors tables (cell medians and quantiles).
4. **Engine v2 checks:** E3/E4 re-run for engine v2.
5. **The screener:** a diff of its shipped history.
6. **The other fields:** the same seam count for each `COMBINED` field.

## 8. Decisions needed from the operator

1. **The approach:**
   - **My recommendation:** F1 now; F2 and F3 designed and measured before adoption.
2. **Gate 2 and the frozen `c7d7a4f`:**
   - **Recommendation:** gate 2 stays on its frozen inputs. Changing the extractor mid-gate would break the registration.
   - **Instead,** the share of gate-2 company-dates with a seam in their input history is measured and reported beside the result, as a
     stated limitation.
3. **Engine v2:**
   - **Recommendation:** vintage 2025 is built on the current extractor, consistent with 2016–2024. If F2 or F3 is adopted, all ten
     tables are rebuilt together as a new version (V → V+1), never one alone.
4. **The screener:** the extractor is the screener's production code. Any fix lands in `screener-publish`'s script first and is
   re-vendored. That changes what the live site shows, so it needs the operator's approval and a named deploy.

**Correction (2026-10-13, after AK.27).** The first version of this report said gate 2's q1 outcomes were not affected. That was wrong
(section 6). The q1 rule and its operator decision are fork 1's, registered in AK.27, and separate from the `pit_data` repair here.

**Holds in force:** nothing that gate-2 scoring imports (`pit_data`, the extractor, `rebuild_harness/gate2/*`) changes until fork 1's
scoring chain writes `chain/DONE`.
