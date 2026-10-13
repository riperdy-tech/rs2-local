# Cross-check request 9: the forecasting core after gate 2. Engine v2, Muse integration (S5), the distress layer. What is wrong?

You reviewed cross-check 8 (the gate-2b and selection registrations). This request covers the three designs that decide what the
system forecasts once gate 2 is scored. Two are approved by the operator and fixed; one awaits approval. All three were written
**before any gate-2 outcome was read**, and nothing in them may change in response to an outcome.

Everything you need is here; the full texts are attached. Critique freely; the coordinator decides. A list of problems is more
useful than agreement. Rank your points by how much they could hurt a real-money decision.

## 1. Reminder

- **The goal:** a local AI analyst (Muse Glimmer 30B) whose company analysis is right enough for real money. Python computes values.
  Muse places a company's inputs inside population distributions, quoting its filings.
- **Established on development data:**
  - point-in-time data are clean;
  - the value engine is correct on true fundamentals;
  - the code has forecasting skill only for ROTE;
  - the code's revenue forecast is no better than the population median;
  - its margin edge is small and unstable;
  - its P10–P90 bands cover 71%, 33% and 9% of outcomes at years 1, 2 and 3.
- **Gate 2** (600 company-dates, 2025-10 to 2026-06, all after Muse's knowledge cutoff) is about to finish. Its scoring will decide
  whether Muse has filing skill.
- **Gate 2b** (approved): the assembled system on the untouched dates 2026-08-31, 09-30 and 10-30, scored against fiscal-year-1 annual
  outcomes on 2027-04-15.

## 2. Engine v2 (approved; code written and tested, tables not yet built)

**Purpose:** the best forecaster without AI. It is the prior Muse's deviations are added to, and the bar any later system must beat.

**Years 1–3, point forecasts**, each from a walk-forward study of 2018–2024 on forecast loss only:

| Measure | Rule | Why |
|---|---|---|
| Revenue growth, year 1 | population median + 0.5 × (code − median) | fitted w 0.53; a small gain over either |
| Revenue growth, years 2–3 | population median | the code is worse than the median by year 3 (t +3.7) |
| Operating margin | the code's retention path | beats persistence by 6–12% (but was worse in the 2025 holdout) |
| ROTE (financials) | population median + 0.75 × (code − median) | an empirical-Bayes weight; about 3% better |
| Tangible-book growth | the code | every option within 1% |

The weights are fixed constants from the study, not refitted per vintage.

**Years 1–3 dispersion:** each forecast's distribution is the point forecast plus the empirical quantiles of v2's own walk-forward
misses for similar companies (size × growth band, or the current-level band).
- The median miss is kept, not re-centred: a measured bias correction, reported.
- Years and variables are joined by a Gaussian copula of measured rank correlations.

**From year 4:** the old engine's measured shapes continue from the year-3 draw. The terminal value, the ROIC path and reinvestment
are unchanged.

**Proof of the code:** with its years 1–3 set to the old engine's own path, v2 reproduces the old engine exactly. This is
mutation-checked: a 1e-4 change breaks it.

**Its validation before freezing (E1–E7):**
- an independent recomputation;
- the study reproduced;
- walk-forward coverage within 75–85%, with neither tail above 15%;
- sharpness against v1;
- the oracle ranking;
- a no-look-ahead cut proof;
- the old engine untouched.

## 3. S5: Muse integrated with engine v2 (approved, v2 after a first review)

**What Muse can move:** only forecasts gate 2 can check one year out. That is year-1 operating growth and margin, and financial ROTE,
**year 1 only**. Return on new capital, terminal growth and banks' book growth stay at v2's values (w = 0), since there is no outcome
to fit them on.

**The transport:** `x = v2 + w × (Muse's v1-chain value − the code's v1-chain value)`, in outcome units. v2's own company-specific
term is the v1 chain, so this is the native unit; the fitted w measures how much transfers.

**Fitting w** (gate-2 data only; forecast error only; leave one date out over 5 dates):
- **Primary target:** the annual year-1 outcome (the quantity the valuation uses).
- **Breadth check:** the next quarter.
- **Adoption** needs all of:
  - an out-of-fold paired gain, with the bootstrap upper bound below 0;
  - at least 150 pairs from at least 2 dates;
  - not worse on at least 3 of 5 dates on the quarterly check.

  Every adoption statistic uses fold weights only. Otherwise w = 0.

**Calibration (year 1, annual target):** isotonic against a smoothed monotone map, chosen out of fold. It needs at least 150 points
on at least 3 dates; otherwise identity (v2's bands).

**The red team** (the price-aware pass) is kept only if it improves on Muse's price-blind pass. Its current behaviour: 21% of its
proposed revisions move toward the price without new evidence; the code refuses all of them.

**Multi-sampling:** if reruns disagree, k samples are taken (at most 5) and the median is used.

**A stated consequence:** annual outcomes exist mostly for two of the five dates, so many cells may end at w = 0. That is by design.

## 4. Distress layer v2 (draft, awaiting approval)

**Today:**
- **The model:** value = mean IV × P(survive 12 months), from a logistic model on six solvency variables.
- **Its accuracy:** AUC 0.65; its scores barely change the ranking (correlation 0.9999).
- **The tell-tale:** the least-solvent tercile of the value ranking inverts (−9.4 at 12 months).

**Candidates, fixed now:**
- C1: richer solvency (Altman and Ohlson components, the coverage trend, a debt-maturity wall where data allow);
- C2: the Merton distance to default;
- C3: both;
- C4: Muse's distress flags, later, under its own registration.

**Selection:**
- one logistic class with a fixed penalty, no tuning;
- chosen on walk-forward AUC, Brier and calibration only. **No return is read in selection.**

**The decisive bars, on fresh dates** (from 2026-07; read when about 30 events have accrued, around mid-2028): AUC ≥ 0.70, Brier ≤
today's, and the least-solvent tercile no longer inverts.

## 5. Questions

1. **Engine v2.** Is keeping the residuals' median miss (a bias correction) right, or should the distributions be re-centred on the
   rule? Is a Gaussian copula on rank correlations adequate for the joint years 1–3, or does it understate joint tails?
2. **Engine v2.** Fixed weights from one study, validated in-sample, then tested on gate 2b: acceptable, or should they be refitted
   walk-forward per vintage?
3. **S5.** Is restricting Muse to year 1 too conservative, given that value depends mostly on later years? What evidence would justify
   a year-2 weight, and when?
4. **S5.** Is a single w per family × measure right, or should w depend on the strength of Muse's evidence (hard evidence against
   none)? We avoided that to limit fitted parameters on five dates.
5. **S5.** With annual outcomes on two dates only, is the adoption rule (annual gain required) so strict that it will almost surely
   give w = 0? If so, is that the right answer or a design flaw?
6. **Distress.** Is the logistic class with a fixed penalty too weak? Would you add a non-linear candidate, given the overfitting risk on
   rare events?
7. **Distress.** About 30 fresh events by mid-2028 makes an AUC of 0.70 noisy. Is the bar well posed, and what minimum event count
   would you require?
8. **Overall.** What is the single most likely way this core produces confident, wrong valuations in live use?

## 6. Attached

- `SPEC_engine_v2.md` and `REGISTRATION_engine_v2.md`
- `SPEC_S5_muse_integration.md` (v2)
- `REGISTRATION_distress_v2.md`
