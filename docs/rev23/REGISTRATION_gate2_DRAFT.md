# Gate 2 registration — APPROVED by the operator 2026-10-07: does Muse add information to the code engine?

Written by the coordinator on 2026-10-07, before any Muse run on any replay date. It applies only if gate 1 passes.
Design: `SPEC_muse_passes.md` and `SPEC_rebuild.md` (Addenda A–K).

## 1. What is tested
**Two arms on the same companies and dates:**
- **CODE:** the frozen gate-1 engine, every input at the prior's P50.
- **MUSE:** the same frozen engine, with inputs placed by Muse pass 1 (price-blind) and revised by pass 2 (red team),
  under the code checks: quotes verbatim, hard evidence outside P10..P90, the revision rule.

**Muse settings, frozen in the gate-2 freeze file:**
- Muse Glimmer 30B: the GGUF and drafter hashes, llama.cpp build b11272;
- context 32k, reasoning strength xhigh;
- the server's pinned sampling;
- the prompt template hashes and seeds.

**Information set:** filings only, as known at 16:00 ET on the date. No consensus, no web research (Addendum C).

## 2. Dates, sample and cost
- **Dates:** month-ends 2025-10-31, 2025-12-31, 2026-02-27, 2026-04-30 and 2026-06-30. All after Muse's knowledge ends
  (about late August 2025, probed).
- **Sample:** per date, 120 companies drawn at random from the gate universe (≥ $300M, built family, annual report
  before T). Stratified by family in proportion, seed 20261007. Drawn once, before any run.
- **Cost:**
  - **Volume:** about 600 company-dates, about 8 Muse calls each.
  - **Pilot first:** the time per company is measured on a pilot of 10 company-dates from 2025-10-31. The pilot counts
    toward the sample and its outputs are not looked at before the end.
  - **Estimate:** 5–7 GPU-days.
  - **Running:** the run goes through a scheduled task, not this session, so an app update cannot kill it.

## 3. Outcomes (only those that have elapsed by the scoring date)
- **Forecast:** the next one and two fiscal quarters' revenue growth and operating margin (ROTE for financials), first
  reported after T.
- **Returns:** excess return over SPY from the next session's open, at 3 and 6 months (12 months where elapsed). Every
  return bar is computed under the three delisting bounds.

## 4. Bars (MUSE against CODE, paired by company and date)

| Bar | Kind | Rule |
|---|---|---|
| G1, forecast accuracy | **hard** | The paired median of (MUSE absolute error − CODE absolute error) for next-quarter revenue growth and operating margin is < 0, with the upper end of its one-sided 90% bootstrap interval (clustered by company) < 0. MUSE must forecast better than CODE. |
| G2, return information | **hard (direction)**, plus reported | The rank IC of MUSE IV ÷ price with 3-month excess return minus CODE's is > 0, pooled over dates. The 90% interval is reported; at about 600 observations it is low-power, so direction only is hard. |
| G3, calibration | reported | P10..P90 coverage of MUSE's stated distributions against realized quarterly outcomes. This trains the calibration layer. |
| G4, anchoring | **hard** | Among pass-2 revisions, the share that move toward the price without new evidence is ≤ 10%. (The code refuses those revisions; this checks the refusal works and the model is not trying it constantly.) |
| G5, integrity | **hard** | The leakage audit is clean on every pack; the quote check passes on 100% of accepted citations; no run fails the transport or JSON rules more than once without the fallback being recorded. |
| G6, name bias | reported | A control of 30 company-dates rerun with the name and ticker masked. The mean absolute shift in placed percentiles is reported. |

## 5. Outcome
- **PASS:** G1, G2 (direction), G4 and G5 all hold under all three bounds where they apply. Muse becomes the live
  analyst and live forward scoring starts. Real money remains the operator's decision.
- **FAIL:** a hard bar fails. The code engine stands alone, and Muse's next structural cause is found.
- **NOT DECIDED:** a bar straddles the bounds.

## 6. Choices for the operator to approve
1. Five replay dates and 120 companies per date (about 5–7 GPU-days).
2. G1: Muse must beat the code engine's quarterly forecasts with one-sided 90% confidence.
3. G2: direction only on returns (too few months have elapsed for power).
4. G4: at most 10% of pass-2 revisions trying to move toward the price without new evidence.
5. G5: integrity at 100%.
6. The name-masking control size (30).

## 7. Approval record
On 2026-10-07 the operator approved, in their own words: "approve the six as long as it's your recommended setting".
All six choices in section 6 are the coordinator's recommended settings as drafted, so all six are approved as
written. The bars are fixed from this point and may not change after any gate-2 result exists.
