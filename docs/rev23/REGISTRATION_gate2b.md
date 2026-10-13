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

Approved by the operator on 2026-10-11 12:33 KST ("approve 1-4, keep D9 as written, adopt O3"). The bars are fixed from this point.
