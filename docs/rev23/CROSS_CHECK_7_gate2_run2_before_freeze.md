# Cross-check request 7: gate 2 is about to be frozen and run again. What is wrong with this setup?

You reviewed cross-check 6, which reported that Muse's first run broke on formatting. This document reports the repair
and everything else the repair turned up. It sets out the run as it will be frozen, and asks you to find what is wrong
with it **before** a four-day run starts and before any outcome is read.

Everything you need is here. Critique freely; the coordinator decides. A list of problems is more useful than
agreement.

## 1. Reminder

- **The goal:** a local AI analyst (Muse Glimmer 30B on one 24 GB GPU) whose company analysis is right enough for real
  money. Python computes the values. The AI places each company's inputs inside population distributions and quotes its
  filings for each placement.
- **What is established:**
  - the data are clean point in time;
  - the value engine is correct when it is fed true fundamentals;
  - the code has forecasting skill only for ROTE (banks and insurers).
- **What is not established:** company-specific revenue or margin skill, and stock selection beyond value and size.
- **So the case for the project rests on whether Muse's reading of filings beats the base rates.** Gate 2 tests that
  on 600 company-dates, from 2025-10 to 2026-06. Every date is after Muse's knowledge ends (about August 2025).

## 2. What was repaired

**The run-1 failure, counted from the raw files.**
- **First-attempt valid answers:**

  | Prompt | Valid first time |
  |---|---|
  | P1 | 1 of 39 |
  | P2 | 15 of 39 |
  | P5 | 8 of 34 |
- **Most failures were one missing brace.** 150 of 171 failed answers were complete JSON missing one closing brace:
  the model put extra fields inside the inputs object and lost count.
- **The prompts contradicted the checker in three places:**
  - the example offered a section the checker forbids (R, the population table);
  - P5's text allowed quotes from R;
  - the document pack labels its parts "D1".."D4", but the checker accepted only "D".

**The fix.**
- **Every model call now carries a JSON schema** (llama.cpp's `response_format`), generated from the checker's own
  constants. The extra fields sit at the top level, and R is not offered as a section.
- **The checker accepts "D2" and verifies the quote inside that part.**
- **The prompts state only what the checker accepts.**

**The A/B test** (thresholds written down before it ran). The same 48 saved requests from 10 companies, in three
arms:

| Arm | What it is |
|---|---|
| U1 | run 1's saved answer |
| U2 | a new unconstrained answer |
| C | the same request with the schema |

| Measure | Result |
|---|---|
| C valid | 48/48 |
| Reasoning length, C ÷ U2 (median by prompt) | 0.92–1.16 |
| Mean placement shift, C vs U2 | 4.5 percentile points |
| Mean placement shift, U1 vs U2 (sampling noise alone) | 5.1 percentile points |
| Quotes verified | C 98%, U2 96% |

The schema was therefore adopted, and the two-call design (reason freely, then extract) was not needed.

**The rehearsal** (20 company-dates: 14 with model calls, 6 refused by the engine).

| Measure | Result |
|---|---|
| Valid on the first attempt | 100% |
| Inputs falling back to the prior | 0 of 68 |
| Synthesis (P5) succeeded | 14 of 14 |
| Quotes verified | 260 of 260 |
| Reasoning length against run 1 | 0.90–1.01 |

**But the leakage audit stopped the rehearsal, and that led to three findings:**
1. **The ticker shown to the model could leak the future.** Today's ticker is shown. For Ambac (now OSG) and
   OPENLANE (now OPLN), that ticker comes from a corporate change after the analysis date.
   - **Fix:** a ticker is shown only when it appears in a document filed before the analysis date; otherwise the
     company name alone is shown.
   - **Measured:** the ticker appears in pre-T documents for 12 of 14 rehearsal companies.
2. **The leakage audit treated the model's own words as code-built text.** Examples: "calendar 2026 revenue" guidance
   quoted from a filing, "pricing power", and fiscal-quarter labels like "Q2 2026" on filings dated before T.
   - **Fix (the operator's ruling):** these become review items, not violations. The model's knowledge ends before
     every analysis date, and the filings pass an acceptance-time check.
   - Code-built text stays strict.
   - This is a change to the instrument behind the hard bar G5, made before any outcome is read.
3. **The ticker map sometimes named the wrong security.** For a company with several listed securities, the code
   picked the "largest market cap". But it computed every ticker's cap as that ticker's price times the common share
   count, so a high-priced preferred share won.
   - **Example:** Bruker was priced at its $316 preferred, a $48B "cap" against about $5.9B real.
   - **Exposure:** 8 of the 600 gate-2 company-dates (preferreds and notes of banks, B. Riley, Gray TV and others).
     The same map was used in gates 1 and 1b.
   - **Fix:** the common stock is the first ticker in SEC's own list (`company_tickers_exchange.json`), which put the
     common first in every case checked. A company whose corrected cap is below $300M is recorded and never scored.

**A scoring defect, fixed before any outcome exists.** The registered G1 rule compares next-quarter **year-on-year
changes** in the margin. The scoring code compared margin **levels**: an annual forecast against a single quarter. It
now compares changes, as registered.

## 3. How gate 2 will be read (fixed before the run)

**The registered bars are unchanged.**

| Bar | Kind | Rule |
|---|---|---|
| G1 | hard | Muse beats the code on next-quarter growth and margin change: the paired median absolute-error difference < 0, with a one-sided 90% company-clustered bootstrap |
| G2 | hard (direction) | IV ÷ price rank IC, Muse minus code, > 0 |
| G3 | reported | calibration |
| G4 | hard | revisions toward the price without new evidence ≤ 10% |
| G5 | hard | integrity |
| G6 | reported | name-masking control |

**Added as reported diagnostics, with reading rules fixed now (the coordinator's ruling):**
- **(a) Filing skill.** G1's statistic, computed on Muse's **price-blind** pass-1 placements. It is compared against
  the code, the population median and persistence. "Muse adds skill" is concluded only if pass 1 beats all three.
  - **Why:** registered G1 scores the placements **after** the red-team pass, which has seen the market price. The
    market contains information about future fundamentals, so a G1 pass could come from the price rather than from
    reading filings.
- **(b) The red team's value.** Final against pass 1. The red team stays in the live system only if it improves the
  forecasts.
- **(c) Strict anchoring.** In run 1 and in the rehearsal, nearly every red-team revision moved toward the price,
  justified by "a named error in my earlier reasoning" rather than a new quote. G4 as registered counts a named error
  as evidence, so this behaviour passes G4.
  - We also report G4 counting only a new quote as evidence. Above 10% means the red team anchors on the price.
  - We also report the forecast accuracy if those revisions had been refused.
- **(d) Repeatability.** 30 company-dates are rerun with a different random seed. If the median placement moves more
  than 10 percentile points, the live system must combine several runs per company.

**The baselines proposed for (a)** (please critique; they are fixed before the freeze):
- **Persistence:** the same year-on-year statistic, observed on the latest quarter known at T. For growth, that is the
  last reported quarter's year-on-year growth; for the margin change, the last reported quarter's year-on-year margin
  change.
- **Population median:** the cross-sectional median of that statistic over the gate universe's latest known quarters
  at T. It is unconditional, from the same date.

## 4. Questions

1. **The schema.** Is constrained decoding with these A/B numbers sufficient evidence that answer quality is intact?
   Is anything missing from the A/B — for example, a test on a different prompt version, or a check of how often the
   schema forces a truncated quote?
2. **The G5 change.** Is reclassifying the model's echoed words and fiscal-period labels as "review" legitimate before
   the run? Is there a leak path this opens? For example, could the model's own words carry information that the
   filings shown to it do not?
3. **Ticker withholding.** Is hiding an unverifiable ticker the right fix? Could showing the name only, without a
   ticker, change the model's behaviour enough to matter, relative to the G6 masked control?
4. **The wrong-security defect.** Gates 1 and 1b (both failed, both spent) used the same flawed ticker choice. Should
   their price-based results be re-measured, and could the correction change any conclusion? The coordinator plans to
   report the size of the effect, by date.
5. **The red team.** Given the near-universal named-error revisions toward the price, is keeping the registered rule
   and adding diagnostics (a)–(c) the right call? Or should the revision rule be tightened before the freeze, even
   though that changes the system under test?
6. **The baselines for (a).** Are the persistence and population-median definitions above the strongest fair
   baselines for a next-quarter year-on-year comparison? Would you use the trailing four-quarter average instead?
7. **Unanchored inputs.** When a check fails twice, an input falls back to the prior's median with a "wide" spread.
   Under the expected-value valuation, a wider spread changes the value through convexity alone. Should the fallback
   use the prior's own spread instead, so that it equals the code arm exactly?
8. **What else.** What would you check before spending four GPU-days, that this list misses?
