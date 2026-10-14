# Gate 2b registration — DRAFT v2, 2026-10-11 11:17: does the assembled system forecast better on dates nobody has touched?

**Drafting history.** Draft v1 was written on 2026-10-10 18:22. Draft v2 (this text) applies the coordinator's rulings
on cross-check 8, recorded in Addendum AH of `SPEC_rebuild.md`. Both drafts were written during gate-2 run 2, **before
any gate-2 outcome was extracted or read**, and before S3 picked a branch.

Recovery plan S5 (`RECOVERY_PLAN_2026-10-10.md`); definition of done D2, D3, D7 and D8 (Addendum AD).

**Status:** a draft for the operator's approval. The bars may change only before any gate-2 outcome is read. From the
first read of a gate-2 outcome on, this file is fixed.

**What a pass means.** Gate 2b is a **screening gate on three dates.**
- A pass is preliminary evidence, conditional on those dates. It is enough to promote a core into S7–S10 and its
  shadow operation.
- It is not proof of forecasting skill across market regimes. D2 and D3 are established only by the shadow record
  (S10).

## v3 — the governing version (approved by the operator 2026-10-14 21:12 KST, SPEC_rebuild AK.53; written before any gate-2b data was drawn)

Sections 1–7 below are the v2 text. Where v3 says otherwise, v3 governs.

**Why v3.** S5 gave w = 0 (AK.52), so **SYSTEM is engine v2 alone.** Engine v2 is a code engine with no knowledge cutoff, so a past date can
be untouched. The operator's deadline is the end of October 2026.

1. **The primary date is 2026-07-31.**
   - The v2 reason for skipping it was the S5 fit's view of June-quarter outcomes through gate-2 date 2026-06-30. No fit exists now.
   - **Every company in gate 2's 2026-06-30 sample is excluded,** because the coordinator has seen their June-quarter outcomes in
     aggregate.
   - Nothing for this date has been valued, scored or examined by engine v2's development (E1–E8 use other dates).
2. **The universe, a census.** The v2 universe rule (market cap at least $300M at T, a built family, an annual report and a 10-Q in the 12
   months before T, engine v2 can value it at T), every eligible company. There is no quota draw: engine v2 runs on the CPU.
   - **The inputs** are pinned to the engine freeze: base priors `priors_v3_fy`, near-term tables `priors_v4_fy` (vintage 2025), engine
     v2.0.3 (AK.51), or as the freeze records.
   - **The context** (`data/gate2b_0731/ctx`) is built with the registered gate-2 configuration and `priors_v3_fy`.
3. **The target is q1:** the next quarterly result not yet public at T, measured under the amendment above (AK.37 v2):
   - same-filing measures;
   - total-revenue verification;
   - exclusion of a result public before the T cutoff (SEC Item 2.02 or the pack);
   - the 120-day guard;
   - the register.

   Every arm forecasts the annual quantity and is scored on q1, with the shared mismatch, as in gate 2's G1.
4. **The arms:** SYSTEM = V2 (engine v2.0.3 at its P50), CODE (engine v1 at its prior P50), PERSIST and POPMED (the run-rate statistics,
   AH).
5. **The bars, in G1's form** (median of the paired d = |arm − y| − |other − y| < 0, with the one-sided 90% company-clustered bootstrap upper
   end < 0; 2,000 draws, seed 20261013):
   - **B2:** SYSTEM beats PERSIST and POPMED on revenue growth and on the margin change; on the ROTE change, it beats PERSIST.
   - **B3:** SYSTEM beats CODE on every measure.
   - **B1** is dropped (SYSTEM = V2).
   - **The verdict:** PASS when B2 and B3 hold; otherwise FAIL. No other bar may be added after any outcome is read.
6. **B4 (calibration of the year-1 annual band)** is read on the fiscal-year-1 outcomes in spring 2027. It is a **condition for real money,
   not for paper (shadow) operation.**
7. **Confirmation dates: 2026-08-31, 09-30 and 10-30.**
   - Each is valued under the same freeze, with its own universe (excluding no one but the gate-2 overlaps).
   - Each is scored when its q1 outcomes are filed, under these same rules, then pooled with 07-31 for a confirmation read.
   - A confirmation failure triggers a review, and suspends promotion toward real money. A confirmation pass never rescues a 07-31
     failure.
8. **Muse** runs, recorded and unused, on a 450-company random subset of 07-31 (seed 20261010), at about 3 GPU-days, off the critical path.
9. **Audit before any report:**
   - the independent recomputation;
   - Audit 1 (look-ahead, coverage, the register);
   - a 20-outcome hand check against the filed documents;
   - E8's measures on the 07-31 census, reported beside the verdict (not a bar).
10. **The schedule:**
    - the engine freeze by about 10-19;
    - the universe and the freeze of the 07-31 run;
    - the CPU valuation;
    - scoring and audit by about 10-25.

11. **Limits and reported diagnostics** (cross-check 14, ChatGPT; adopted in AK.57, 2026-10-14 21:55; fixed before the 07-31 freeze; none is a bar, and no
    bar or threshold changes):
    - **What the test is, stated in the freeze record and in the verdict.** "A company-disjoint, registered q1 proxy screen on a period
      partly observed in aggregate (gate 2's results of the same reporting season were seen). It is **not** a pristine temporal holdout,
      and **not** a validation of annual forecast accuracy." A pass supports controlled shadow operation only.
    - **The q1-against-annual mismatch** is an explicit limitation: the engines forecast fiscal year 1, and q1 is one quarter, with
      seasonality, one-offs and reporting timing. The shared mismatch does not guarantee an unbiased ranking; the persistence arm's
      trailing-four-quarter rate behaves differently in a shocked quarter.
    - **Reported beside the bars:**
      - the target quarter's end date, its distance from T, and whether it is a late-reported or a later quarter;
      - paired errors by reporting delay, size decile and family;
      - the concentration of any advantage: the share of the median-d gain from the top 10 companies by contribution, and the result
        with each industry left out in turn.
    - **Selection reconciliation:** the full eligible universe against the scored q1 sample, on market cap, family, industry (SIC
      2-digit), filing delay, leverage and distress (C0 P(fail)), and prior growth volatility, with exclusion counts by reason. No weight
      is chosen and no case is removed after performance is seen.
    - **Real money:** B4 (annual calibration and sharpness) and every applicable D1–D10 condition, including D9's money bar, stay
      unchanged and mandatory. No gate-2b pass is ever presented as meeting them.

12. **Amendments from Gemini's cross-check 14** (AK.58, 2026-10-14 21:57; fixed before the 07-31 freeze; each tightens or adds a report, and none relaxes a
    bar):
    - **(a) The inference unit for 07-31 is the industry.** At one date each company appears once, so a company-clustered bootstrap is an
      unclustered one: it ignores shocks shared within an industry. **The B2/B3 interval for 07-31 is a cluster bootstrap by SIC 2-digit
      industry** (2,000 draws, seed 20261013; an industry with fewer than 5 companies is pooled within its family). The company-clustered
      interval is reported beside it.
    - **(b) Public availability widens.** A result also counts as public when an 8-K with **Item 7.01** (Reg FD) is accepted after the
      period end and before the T cutoff, as well as Item 2.02 or the pack. The rule over-excludes on purpose, and the count of extra
      exclusions is reported.
    - **(c) Strata and reweighting, reported:**
      - B2/B3 within strata: fiscal-quarter-end month (late-reported June quarters against later quarter-ends), market-cap tercile and
        family;
      - an inverse-probability-of-selection score, reweighted to the full eligible universe on (SIC 2-digit × size tercile × quarter-end
        month);
      - the attrition table: universe, then gate-2 overlap, then public at T, then the 120-day guard, then the scored sample.
    - **(d) The confirmation pool counts each outcome once.** Monthly dates can target the same quarterly filing, so the pooled read keeps
      each (company, target-quarter period end) once, using its earliest snapshot. It is clustered two ways, by company and by
      (industry × quarter).
      - **For real money,** the confirmation read must pass pooled **and** on 2026-09-30 alone, the first quarter-end census after
        07-31 (it includes the early large reporters that 07-31 lacks).
    - **(e) A sensitivity:** the 07-31 bars recomputed with **every** company of any gate-2 date excluded, not only 2026-06-30's,
      reported. The registered primary keeps the 06-30 exclusion, because only the same quarter's outcomes were seen.
    - **(f) B4's limit, stated.** At 07-31 fiscal year 1 is partly elapsed (its reported quarters are in the information set, as AH
      registered), so B4 tests a partly known year. B4 stays as defined. For real money a **fiscal-year-2 calibration** (a year wholly
      after T) is added, read when available.
    - **(g) A diagnostic:** the share of each name's value from years 1, 2–3 and 4 onward (the `mean_iv` horizon decomposition).
13. **Readings and one tightening, fixed before the 07-31 freeze** (AK.68, 2026-10-15 00:28; no 07-31 value or outcome had been read; nothing is relaxed):
    - **(a) Few-cluster guard.** A cluster bootstrap over few clusters tends to understate uncertainty. A bar therefore passes only when
      **both** the industry-clustered and the company-clustered upper ends are < 0. Each bar reports its number of industry clusters, and one
      with fewer than 10 is flagged `few_clusters`. One pooled cluster is flagged `single_cluster`.
    - **(b) POPMED's population** is the universe file (gate 2's convention, "over the gate universe"). The census-sample median is
      reported beside it.
    - **(c) The precedence:** FAIL if any decided bar fails; else NOT DECIDED if any bar lacks its minimum sample; else PASS.
    - **(d) Public through the pack** is empty for the census, because no pack exists at T. Muse's 450-subset packs, built later, are not
      used to exclude, so the scored sample does not depend on which names Muse ran.
    - **(e) The 10-Q and annual conditions:** the 10-Q condition is an original 10-Q accepted in the 12 months to T at 16:00 ET. The annual
      condition is gate 2's universe rule (an annual report in the layer at T).

    - **(f) The q1 scoring date for 2026-07-31 is 2026-10-13** (AK.73, 2026-10-15 02:47; before any 07-31 outcome is read): the companyfacts
      snapshot `companyfacts_2026-10-13`, as gate 2 scored on its 10-13 store. A q1 first filed after it is excluded and counted.
      Submissions come from `data/sec_bulk/submissions.zip` of 2026-10-07, which holds every filing before T. Each confirmation date takes
      the first snapshot at least 75 days after its own quarter-ends, registered before its outcomes are read.

    - **Not adopted:**
      - **a binding q1 interval check ("B4-q1").** The engine's band is for the annual quantity, so its coverage of a single quarter is
        not a calibration test. It is reported only, with that caveat;
      - **a Muse shadow arm with an unregistered weight.** S5 is refitted under its own registration when the annual pairs reach 150,
        excluding every (company, fiscal year) gate 2b scores;
      - **q1 already compares a quarter with the same quarter a year earlier** (year-over-year, so seasonally matched), so no further
        seasonal adjustment is added.

## 1. What is tested

**The system under test (SYSTEM)** is whatever S5 assembles, frozen before any gate-2b pack is built:
- **after branch C1:** engine v2 with Muse's transported deviations (`x = v2_P50 + w·(Muse − c7d7a4f prior P50)`, w per
  input and family), the calibration, the red team only if R3b kept it, and multi-sampling only if R8 required it;
- **after branch C2 or C3:** engine v2 plus the structural candidate S5 pre-registered, or engine v2 alone.

**Fitted only on earlier data.** Every fitted part (w, the calibration tables, any structural parameter) is fitted only
on data from before the first gate-2b date, and only on gate-2 outcomes.

**Its frozen form** is a freeze file in the gate-2 manner. It records:
- the code commit and the engine version;
- model, drafter and llama.cpp hashes, where a model is used;
- the template hashes, every w, and the calibration tables with their hashes;
- the seeds, the sample hash and the store snapshot hashes.

`verify` must report no drift before the run, and the run comes from a detached worktree at the frozen commit.

**The arms,** each on the same company-dates, each forecasting **the same quantity** (section 3):
- **SYSTEM**;
- **V2:** engine v2 alone, every input at its v2 P50 (when SYSTEM is V2 alone, the two are one arm);
- **CODE:** the frozen `c7d7a4f` engine;
- **PERSIST:** the run-rate known at T: growth of the latest four reported quarters over the four before them; the
  operating margin and ROTE of the latest four quarters;
- **POPMED:** the cross-sectional median of PERSIST per date and family over the gate universe.

PERSIST and POPMED are computed from the quarters each company had reported by 16:00 ET on T, through the pack's own
source and eligibility rule. That is the AE.3 machinery, extended to the four-quarter run-rate (Addendum AH).

## 2. Dates, sample and cost

**Dates:** month-ends **2026-08-31, 2026-09-30 and 2026-10-30.**
- All three lie after Muse's knowledge ends.
- None has been used by any development, fit, study or test.
- 2026-07-31 is not used. At that date most companies had not yet reported the June quarter, and the June quarter is
  an outcome the S5 fit sees through gate-2 date 2026-06-30. The target would overlap a fitted outcome (Addendum AH).
- The coordinator builds no pack and reads no filing output or outcome for these dates before the freeze.
- Refreshing the point-in-time store with SEC data is permitted (standing approval) and is recorded with hashes.

**Universe:** the gate-2 rule, plus one condition fixed in advance:
- market cap at least $300M, a built family, and an annual report before T;
- **added:** a quarterly report (10-Q) filed in the 12 months before T. A company without one (foreign private issuers
  filing 20-F/6-K) has no quarterly run-rate and no comparable outcome. It is valued in production, not in this test.
  Its count is reported.
- **added:** engine v2 can value the company at T. Before the draw, the code-only engine runs on CPU, with information
  as of T only. In gate-2 run 2, 30% of drawn company-dates were refused by the engine (mostly no three-year ROIC),
  and a refused company yields no paired observation. Refused companies are abstentions in production as well. Their
  count and reasons are reported.

**Sample: quota-stratified,** seed **20261010**:
- per date, **100 operating and 50 financial** companies, drawn at random within each family;
- 450 company-dates in all;
- financials are oversampled against their share of about 22%, so the ROTE bars can reach their minimum sample. Every
  bar is computed within one family's measure, so the oversampling biases no statistic;
- drawn once, after the store refresh and before the freeze, and hashed into the freeze;
- commodity is out of scope unless S6 has built and validated it by then.

**Repeat control:** 30 of those company-dates rerun with a second seed (R8 method), into a separate state folder. Only
the sampling seed of the model call differs; packs, templates and engine inputs are identical, and this is verified by
the request hashes.

**Cost:** for a Muse system, about 3.1 GPU-days at k = 1 (450 × the run-2 per-company time). It runs by scheduled task
behind the AD.4 behaviour gate.

## 3. The target and the scoring date

**The target is the quantity the engine actually forecasts and values:** fiscal year 1, the fiscal year after the
base year known at T.
- **Growth:** year-1 revenue ÷ base-year revenue − 1 (operating family).
- **Margin change:** the year-1 operating margin minus the base-year operating margin (operating family).
- **ROTE change:** year-1 ROTE minus base-year ROTE (financial family).

Each outcome is computed by **the engines' own state builder** (`build_state`, which defines `base_year`), applied as of
the first filing of the year-1 annual report. The figures are first-filed, never restated.

**What each arm's forecast is:**
- SYSTEM, V2 and CODE: their year-1 P50s;
- PERSIST and POPMED: the run-rate statistic, minus the base-year level for the two changes.

**Quarters already reported inside year 1 at T** are part of the information set. Every arm may use them, and
PERSIST does.

**The scoring date is 2027-04-15.**
- It lies after the 10-K deadline for fiscal years ending 2026-12-31 (non-accelerated filers 2027-03-31) and the
  15-day late-filing extension.
- A company whose year 1 ends later (a non-calendar fiscal year whose year 1 ends after 2026-12-31) has no outcome by
  then. It is missing by fiscal calendar, not by performance. Its count is reported by family and date.
- Every missing outcome is reported. The included and missing companies are compared on market cap, family, base-year
  margin, leverage and the late-filing (NT) flag.
- There is one scoring and no re-scoring.

**An early read, which carries no weight.** On 2026-12-18 the next-quarter statistic (q1, Addendum O 2) is scored
for every arm, using the same annual-convention forecasts. Every arm is then scored on the same horizon mismatch.
It is labelled as a diagnostic and decides nothing.

**Returns are not part of gate 2b.** The return question belongs to the selection registration, and these dates are
outside its confirmatory count.


**Amendment AK.37 v2 (approved by the operator 2026-10-14 14:39 KST: "approve AK.37 v2 and AL.22"; written before any gate-2b data exists and before
S5 is fitted; the rules and their measured basis are in SPEC_rebuild AK.37, AK.39 and AK.41):**
1. **Measurement.** Revenue growth and the operating-margin change come from **one filing's own comparative columns**
   (`rebuild_harness/gate2/same_filing.py`):
   - one accession, one tag, one unit;
   - among several revenue tags, the largest current value, and on a near-tie (within 0.5%) the largest prior;
   - a derived Q4 only with one tag across the 10-K and the Q3 10-Q, and no recast in between.

   The ROTE change keeps the `build_state` definition, with a net-income tag-consistency check reported beside it.
2. **Total revenue.** The chosen revenue figure must be verified as total revenue: either the largest of two or more tags, or a closure in
   the same filing (gross profit plus cost of revenue equals revenue, or revenue minus total costs and expenses equals operating income,
   within 1%).
   - A closure failure abstains, and is listed.
   - A figure with no test available is scored and flagged, and every bar is also reported on the verified rows only.
3. **Eligibility, both arms alike.** A target is not a forecast, and leaves the scored sample (listed), when its result was **public before
   the T cutoff**:
   - through an 8-K with Item 2.02 in SEC's filing index, accepted after the period's end; or
   - through an earnings release or the annual report in the pack; or
   - for the annual target, through the annual report filed on or before T.

   A quarter that ended more than 120 days before T is also excluded: a guard against a known XBRL artefact, not part of the benchmark.
   The quarterly benchmark is **the next quarterly result not yet public at T**.
4. **The register.** Every exclusion records the company, T, the target period, the metric(s), the public source with its acceptance
   timestamp, and the reason. The original and the eligible sample sizes are both reported.

   This replaces "first-filed, never restated" above for growth and margin.

## 4. Bars

**The statistic** is G1's: per measure, the paired median of `|A − y| − |B − y|` over company-dates. A is better when
both of these hold:
- the median is < 0;
- the upper end of the one-sided 90% bootstrap interval is < 0, from 2,000 resamples of whole companies, seed
  20261010.

**Reporting.** Every bar is reported pooled and by date, with its paired n. Every interval is conditional on the three
dates. The coordinator's independent script (Addendum AG.4, extended for the annual target) must reproduce every
number before it is reported.

**Departures.** A measure is a departure of SYSTEM from V2 when an input feeding it is moved by SYSTEM:
- growth ← g1;
- margin change ← margin target and path;
- ROTE change ← ROTE target;
- with any w > 0, or a structural candidate in use.

| Bar | Kind | Rule |
|---|---|---|
| B1, skill against the engine | **hard** | SYSTEM beats V2 on every departure measure. On every other measure, its median d against V2 is ≤ 0. (Dropped when SYSTEM is V2 alone.) |
| B2, skill against the base rates | **hard** | SYSTEM beats PERSIST and POPMED on growth and on the margin change. On the ROTE change, it beats PERSIST. |
| B3, against the old engine | **hard** | SYSTEM beats CODE on every measure. |
| B4a, coverage | **hard** | SYSTEM's calibrated year-1 P10–P90 covers 80% ± 7 of outcomes for each measure. Neither tail holds more than 15% (target 10% each). |
| B4b, sharpness | **hard** | The paired median of the interval score at α = 0.2 (SYSTEM − V2; CODE when SYSTEM is V2 alone) is ≤ 0. A band cannot pass B4a merely by widening. |
| B5, repeatability | **hard** where a model is used | On the repeat control, the median absolute shift of final placed percentiles is ≤ 10 points, after the multi-sampling S5 adopted. The relative IV shift and the share of verdict directions that change are reported. |
| B6, integrity | **hard** | G5 as registered: a clean leakage audit (the AE classes), 100% of accepted quotes verified on re-check, and no unrecorded fallback. |
| B7, anchoring | **hard** if the red team is kept | G4-strict (AE.1): at most 10% of proposed revisions move toward the price without a new quote from a filing section, and none of those is accepted. Registered G4 (a named error counts) is reported beside it. |
| B8, behaviour | **hard** | The AD.4 behaviour gate holds on the full run. |

**Minimum sample:** at least 200 paired observations per operating measure, and 100 for the ROTE change. Below that,
the bar reads NOT DECIDED.

## 5. Outcome

- **PASS:** B1–B8 all hold. SYSTEM is promoted as the analyst core for S7–S10. Real money remains the operator's
  decision (S11).
- **SYSTEM fails, V2 qualifies.** If SYSTEM fails while **V2's own scorecard** passes, V2 is promoted and the operator
  is told.
  - V2's scorecard is B2, B3, B4a and B6, computed for V2 itself on these company-dates, with B4b against CODE.
  - Nothing about V2 is inferred from SYSTEM's results.
- **FAIL:** neither qualifies.
  - The structural search continues (S5-C2/C3).
  - The next attempt needs a new registration on the next untouched month-ends after the latest outcome period any
    fit has seen.
  - These three dates are never reused.
- **NOT DECIDED:** a minimum sample is not met. The bar is reported with its n, nothing is promoted, and the next
  attempt uses new dates.

## 6. What this registration deliberately does not do

- **No tuning on these dates.** No w, calibration table or template changes after the freeze. A defect found during
  the run stops the run, and the fix goes to new dates.
- **No pooled-only claims.** Every bar is shown by date as well.
- **No returns.**
- **No prescribed calibration method.** S5 chooses between isotonic mapping and a smoothed monotone mapping by
  cross-fitted loss on gate-2 data, and freezes the choice. This file tests the result.

## 7. Approval record

**SYSTEM is V2 alone (AK.52, 2026-10-14 20:18).** S5's rule gave w = 0 on every measure, so SYSTEM and V2 are one arm and B1 is dropped, as section 4
already provides. B2, B3 and the other bars are unchanged. Muse runs on these dates and its positions are recorded, not used.

Approved by the operator on 2026-10-11 12:33 KST ("approve 1-4, keep D9 as written, adopt O3"). The bars are fixed from this point.
