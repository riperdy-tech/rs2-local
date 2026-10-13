# Problem report: revenue series stitched from different XBRL tags give false growth

**Date:** 2026-10-13 23:07 KST. **Author:** the coordinator, fork 2. **Records:** SPEC_rebuild Addenda AL.6 and AL.7; fork 1's AK.26.

**Status:**
- open; no value has been changed;
- the operator's decisions are recorded in AL.8 (section 8);
- **revised 2026-10-13 after a hand check** (section 9).

**The three questions** (AL.8):

| Question | Answer so far |
|---|---|
| Is the cause real? | Yes. The mechanism is in the code (section 5). Four cases were checked against the filed income statements, and each extracted growth figure is wrong (section 3). |
| How prevalent is it? | Provisional: about 0.4–0.5% of year-to-year pairs off by more than 5 points, from two 300-company samples (section 4). The other fields are suspected and not yet quantified. |
| Does it change a decision? | Not yet measured. The gate-2 share of affected company-dates and the sensitivity of its outcomes are fork 1's (AK.27–AK.28). The effect on engine v2's tables is still to measure. |

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
- the growth across the change is off by more than 5 points in 0.47% of all pairs;
- it is off by more than 20 points in 0.38%.

It is not a look-ahead leak: each cut reads only filings made before it. It is a data-correctness defect in a shared component, and the
same mechanism very probably affects the other fields resolved the same way, which have not been measured (section 6).

## 2. Why it matters for real money

Revenue growth is an input at three points, and a false figure distorts each one:
- **The priors:** the analyst's population priors (the features `g_latest`/`g3` and the growth cells).
- **The near-term tables:** engine v2's near-term residual tables, which set the width and tails of its forecasts.
- **The outcomes:** gate 2's q1 outcomes, which carry the hard bars, and its annual outcome (section 6, corrected).

The errors are rare but very large, so they sit in exactly the tails that set risk. A company whose own history contains a false collapse
or a false doubling is valued on a wrong trend.

## 3. Evidence: four cases, checked by hand against the filed income statements

The cut is 2026-01-01, `first_filed` mode, read from the shared store (`pit_data`). The last column is the income statement as filed (the
SEC's rendered statement page of that accession, downloaded 2026-10-13 under standing approval O5). Every reference figure is the
statement's total revenue line.

The scripts are `scratch/rev23/engine_v2_audit/handcheck_fetch.py` and `handcheck_read.py`.

| CIK | Year t | Extracted: year t−1 → year t | Extracted growth | Year t's own filing (accession), both years |
|---|---|---|---|---|
| 1042893 | FY2018 | 455.5M `Revenues` → 337.5M `RevenueFromContractWithCustomerExcludingAssessedTax` | −25.9% | "Total revenues" 455,469K → 384,626K, **−15.6%** (0001042893-19-000003). The contract tag, 337,466K, is the line "Revenues from products and services", which excludes leasing (47,160K). |
| 835011 | FY2018 | 22.9M `Revenues` → 376.1M contract-revenue tag | **+1,544%** | "Net sales" 347,448K → 376,089K, **+8.2%** (0001628280-19-002041). `Revenues` (22.9M) is not the statement's revenue line. |
| 46080 | FY2017 | 2,194.7M `Revenues` → 5,209.8M `SalesRevenueNet` | **+137%** | "Net revenues" 5,019,822K → 5,209,782K, **+3.8%** (0001193125-18-058659). |
| 76267 | FY2019 (ends 2019-03-03) | 111.2M `Revenues` → 51.1M `RevenueFromContractWithCustomerIncludingAssessedTax` | **−54%** | "Net sales" 40,230,000 → 51,116,000, **+27.1%** (0001437749-19-010516). |

**Two failure modes appear:**
- **(a) Seam:** two tags of different scope are joined, as in 1042893.
- **(b) Partial line:** the tag that won for some years is a partial line, not the total. Examples: 835011 (`Revenues` = 22.9M against
  a 347M business) and 46080 (a FY2016 `Revenues` of 2,194.7M against `SalesRevenueNet` of 5,019.8M).

Both show up as a tag change between consecutive years. 76267 is one of the two; its 111.2M is not the filed total, and the case shows only
that the extracted year t−1 figure is wrong.

**A fifth case is withdrawn** (it was in the first version). CIK 1720446 reports in RMB. The extracted figures are the USD convenience
translations that each annual report gives for its own year: 314.9M for FY2017, and 530.2M = RMB 3,645.3M for FY2018. Both are totals,
so it is not a tag seam. Its +68% is USD growth at two year-ends' rates, against +77.9% in RMB. The first version called 530.2M a "slice";
that was wrong. The error came from the measurement script, which compared a USD value with RMB values (section 4). Mixed-rate
convenience translation of foreign filers is a separate question, not part of this report.

**The same filing read at two cuts gives different values (AL.6):**
- 1042893 FY2018 is 384.6M at the 2025-01-01 cut and 337.5M at the 2026-01-01 cut.
- CIK 78003 FY2023 is 50.9B at the first cut and 58.5B at the second.

A later filing changes which tag "wins" for the whole series, so the join moves.

## 4. Measurement

The scripts are `scratch/rev23/engine_v2_audit/tag_breaks_sample.py` and `tag_breaks_effect.py`; the outputs are the `.json` files beside
them. Both are read-only, run at low priority, from a seeded draw (seed 20261013) at the 2026-01-01 cut.

| Sample (300 drawn each) | Companies with a tag change | Consecutive-year pairs | Pairs crossing a tag change | Checkable against the filing | Off by > 1 pt | > 5 pt | > 20 pt |
|---|---|---|---|---|---|---|---|
| All filers (`sic_by_cik`); 292 with data | 96 | 1,641 | 123 (7.5%) | 116 | 16 (0.98%) | 8 (0.49%) | 5 (0.30%) |
| The $300M+ study panel's companies | 131 | 2,343 | 170 (7.3%) | 163 | 17 (0.73%) | 11 (0.47%) | 9 (0.38%) |

These are the corrected counts. The first version compared values across units: a foreign filer's USD convenience figure against its own
RMB figures. The script now compares within the cell's unit only, and the first outputs are kept as `*_v1_unit_mix.json`. Earlier figures
were 17/9/6 and 19/13/11.

The percentages in the last three columns are of all pairs; the counts are of the checkable pairs.

**How "off" was measured:** against the growth that year t's own annual report gives for its two years.
- **Main rule:** year t's tag, with year t−1 taken from that report's comparative column.
- **Fallback, when that filing has no comparative under year t's tag:** year t−1's tag for both years (2 pairs in the first
  sample, 4 in the second).

Large errors cluster in 2018–2019, the ASC 606 transition, but occur in every period from 2015 to 2023.

**Limits of the measurement:**
- **The reference is not ground truth.** It is the growth of one consistently tagged figure from one filing. Where that tag is a partial
  line in both years, the reference is the line's growth. The counts above are an estimate of the order of size, not an audit.
- **Hand check:** four cases so far, all confirmed. Twenty are planned before any value fix (section 7).
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
- **Effect:** this removes failure mode (a). It does not fix (b) when a partial line is used consistently in both years of one filing.

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

## 8. Decisions (the operator forwarded an outside review; ruled in AL.8)

1. **Approach: diagnostics only (F1).**
   - **The provenance recorded per year:** the selected tag, any backfill tag, the accession and period, and `tag_seam`.
   - **Before F2 or F3:** the hand check and a broader before-and-after validation.
   - **Status of the numbers:** prevalence is provisional; the other fields are suspected, unquantified.
2. **Gate 2: the frozen inputs and the running chain are preserved as the original result, with the limitation stated.**
   - The affected company-dates are reported with numerator and denominator.
   - A sensitivity analysis comes before any affected outcome counts as clean evidence.
   - q1 is qualified too, because AK.27 disproved its independence.
   - Owner: fork 1.
3. **Engine v2: vintage 2025 is built on the current extractor and labelled the legacy-extractor vintage.**
   - So are all ten tables, through `data/priors_v4/LINEAGE.json`.
   - A value fix would rebuild all ten as a new version, keeping the legacy one with its hashes.
4. **Screener: no live value fix.**
   - Development happens on an isolated branch.
   - Any deploy, warning-only included, needs a named release, the commit, regression tests, a before-and-after comparison, a rollback
     plan, and a list of who sees changed numbers.

**Correction (2026-10-13, after AK.27).** The first version of this report said gate 2's q1 outcomes were not affected. That was wrong
(section 6). The q1 rule and its operator decision are fork 1's, registered in AK.27, and separate from the `pit_data` repair here.

## 9. Revisions

- **2026-10-13, after the hand check (AL.9):**
  - four cases confirmed against the filed statements;
  - case 1720446 withdrawn (currency translation, not a seam);
  - the measurement script's unit mixing fixed, and the counts corrected downward;
  - the three-questions table added;
  - section 8 replaced by the AL.8 rulings.

**Holds in force:** nothing that gate-2 scoring imports (`pit_data`, the extractor, `rebuild_harness/gate2/*`) changes until fork 1's
scoring chain writes `chain/DONE`.
