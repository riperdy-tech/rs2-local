# Cross-check request: fixing a local-AI stock valuation system that splits by company type

You are asked to review a diagnosis and a proposed fix, critically. Everything you need is in this document. You
cannot see the code or the data, so the document describes them. Please answer the questions in section 9; disagree
wherever the reasoning is weak. A list of what is wrong is more useful than agreement.

---

## 1. What the system is and what it is for

A private investor runs a pipeline whose output is meant to drive real-money stock purchases. Real-money execution
has been switched off since 2026-09-22 and stays off until the system is shown to work. Today's date is 2026-10-06.

The pipeline:

1. **Screener (code).** Every day it scores ~6,900 US-listed companies on fundamentals from SEC filings and
   nominates roughly 150–300 for deep analysis.
2. **The "analyst": a local large language model** on one RTX 3090 (24 GB). Two models are candidates:
   - Qwen 3.8, served through Ollama;
   - Muse Glimmer 30B, served through llama.cpp. The operator has chosen **Muse only** for the experiments
     proposed here: it runs about 7–10 minutes per stock against 27–60 for Qwen.

   For each stock the model receives a long **briefing pack** (text, roughly 50,000 characters):
   - about 12 years of filed financials;
   - the latest earnings release and segment table, verbatim from SEC filings;
   - analyst consensus estimates (EPS, revenue, price targets);
   - news and catalysts;
   - population base rates (how often companies of that size sustain a given growth rate);
   - a cost-of-equity anchor;
   - a code-computed **reference value** (described in section 2).

   It may also search the web.
3. **The "desk" (code).** The model never does valuation arithmetic itself. It chooses inputs and calls a tool:
   - the cash-flow base;
   - growth for years 1–5 in three scenarios (Bull, Base, Bear);
   - a fade period;
   - terminal growth;
   - the terminal return on new investment;
   - the discount rate;
   - share count;
   - scenario probabilities.

   The tool computes the per-share values. It also computes, for each input, the **price-implied value**: the value
   of that input at which the Base would equal today's price, all else held.
4. **Verdict rules (code).**
   - A directional verdict (undervalued or overvalued) needs:
     - a Base at least 10% away from the price;
     - a valid **crux**: an input, a reason, and at least one citation with an exact quote from the company's own
       evidence.
   - Otherwise the verdict is HOLD.
   - Verdicts are published to a website and would feed position sizing.

Design rule throughout: "the AI chooses inputs, Python computes, code checks."

## 2. The code's reference value (the "consensus-implied value")

The reference is a discounted cash flow computed identically for every company:

- **Base:** the last full fiscal year's "owner earnings": net income + depreciation and amortization − capital
  expenditure.
- **Years 1–2:** grow at consensus EPS growth. When that is unusable (a trough, a loss), years 1–2 are consensus
  EPS × shares + D&A − capex.
- **Years 3–5:** growth fades from next-year consensus revenue growth toward a population base-rate median.
- **Years 6–10:** growth fades linearly to a terminal growth rate. The terminal rate is the company's own 8-year
  revenue trend, held between breakeven inflation (2.36%) and a long-run nominal growth anchor (3.75%).
- **Paying for growth from year 6:** cash flow = earnings × (1 − g / RONIC). RONIC is taken from the company's record
  of return on tangible capital; it is effectively unlimited when tangible capital is zero or negative.
- **Margin rule from year 6:** the earnings margin moves linearly, by year 10, all the way to the "trend level" of
  the company's 8-year operating-margin record (a Theil–Sen line evaluated at the base year).
  - The translation between operating margin and earnings margin is additive:
    - `OM_5 = om_L + (m5 − x_L) / (1 − tax)`;
    - `m_long = max(0, m5 + (1 − tax)(target − OM_5))`.
  - Here `m5` is the consensus earnings margin at year 5, `om_L` and `x_L` are the base year's operating and
    earnings margins, and `target = max(0, om_trend)`.
  - The rule applies only when a usable revenue path and margin record exist. Otherwise the margin is held.
- **Excess cash** is added at face value.
- **Discount rate:**
  - **Formula:** cost of equity = max(risk-free rate, growth anchor) + adjusted sector loading × market premium.
  - **Inputs today:** risk-free 5.24%, premium 4.17%. The premium is solved so that the reference values the market
    at its capitalization (the "closure" premium).
  - **Sector loading:** a sector beta-like coefficient, shrunk toward 1 with the Blume adjustment (0.67 × raw + 0.33).
  - **Results:** typical costs of equity are 8–10.5%.

**A point-in-time backtest on 2019–2023 data (code only, no AI) scored this reference as unfit:**
- Rank correlation between value ÷ price and 3-year returns was 0.063.
- Stocks it called cheap beat the market by only +2.1 percentage points, against a pre-registered bar of +5.
- Stocks it valued at 2× their price earned only about 3% more over three years than those it valued at their
  price.
- Its "expensive" calls (0.7× price or less) did underperform the S&P more often than average.
- The simple earnings yield ranked stocks better (0.087).

## 3. What happened over the last two weeks ("Phase 4")

1. The project spent about a week of design revisions reducing the **spread between repeated runs of the same stock**
   and making the crux citation format reliable. The acceptance test passed on 2026-10-04, based on agreement between
   two runs per stock, citation validity and integrity checks.
2. A "baseline" run of one sample per stock over ~170 nominated stocks began. After 33 stocks, an independent review
   by another AI, acting as an outside analyst, judged the verdicts unusable as valuations.
   - **They split by company type:**
     - growth stocks come out at 0.2–0.45× their price;
     - cyclicals and insurers at 2–3.7×;
     - even Bull cases for the growth stocks cannot reach the price, and Bear cases for the cyclicals sit far above
       it.
   - **The analyst mostly copies the code's reference:** within ±10% in 11 of the 19 stocks that have one, some
     identical to the cent.
   - **The same stocks gave very different answers two weeks apart** under earlier design revisions.
3. The operator's assessment: the project has come full circle. Months ago the screener never nominated AI and tech
   companies, and only certain company types ever looked cheap. Now the nominations include them, but the valuation
   step reproduces the same bias. **The lesson accepted:** the acceptance tests measured agreement and form, not
   whether valuations are right. Agreement was achieved largely by the AI sitting on a biased code reference.
4. The baseline is now stopped.

## 4. The evidence: the first 33 verdicts

Price, the code reference, and the AI analyst's Base value, as multiples of the price:

| Stock | Type | Reference ÷ price | Analyst ÷ price | Verdict |
|---|---|---|---|---|
| FORM (FormFactor, semiconductor test) | growth | 0.21 | 0.19 | overvalued |
| LITE (Lumentum, optical, AI networking) | growth | 0.25 | 0.22 | overvalued |
| LIND (Lindblad, expedition travel) | growth or recovery | 0.27 | 0.27 | overvalued |
| AMD | growth | 0.45 | 0.45 | overvalued |
| DELL | growth | 0.76 | 0.69 | overvalued |
| MA (Mastercard) | quality | 1.02 | 1.12 | undervalued |
| GOLD (Barrick) | commodity | 1.05 | 1.32 | undervalued |
| CHA | consumer | 1.33 | 1.75 | undervalued |
| ECPG (Encore Capital, debt buyer) | financial | 1.67 | 1.68 | undervalued |
| AII (American Integrity Insurance) | insurer | 1.93 | 2.54 | hold |
| CMRE (Costamare, container shipping) | cyclical | 2.01 | 3.71 | undervalued |
| HRTG (Heritage Insurance, Florida) | insurer | 2.03 | 2.19 | undervalued |
| KSS (Kohl's, department stores) | decliner | 2.12 | 2.25 | undervalued |
| BCRX (BioCryst, biotech) | growth | 2.38 | 1.22 | undervalued |
| DDI (DoubleDown Interactive) | controlled company | 2.82 | 2.82 | undervalued |
| ESEA (Euroseas, container shipping) | cyclical | none | 3.69 | undervalued |
| GASS (StealthGas, LPG shipping) | cyclical | none | 2.35 | undervalued |
| APA (oil producer, during an oil spike) | cyclical | none | 2.00 | undervalued |
| MRP | — | none | 2.23 | undervalued |
| HG (Hamilton Insurance) | insurer | none | 2.10 | undervalued |

The other 13 (analyst ÷ price):
- **Overvalued:** ARX 0.78, FLXS 0.82.
- **Hold:** IHS 0.89, LAMR 0.95, HAFN 0.99, HOG 1.49, JCAP 3.17 (reference 1.40).
- **Undervalued:** NREF 1.22, ECO 1.28, NGVT 1.30, CBL 1.36, GTE 1.47.
- **No usable sample:** GSL.

Detailed outside reviews of two memos (ESEA and APA) found:
- **ESEA:**
  - the pack itself printed net debt as "Net Debt −$0.021B"; the model read the double negative as net cash. This
    was fixed on 2026-10-05;
  - cash already committed to a $560M newbuild programme was counted as excess cash;
  - the remaining newbuild capex was not deducted while the fleet growth it buys was counted;
  - Base and Bear values contradicted the memo's own worst-case scenario.
- **APA:** the 8.22% cost of equity (energy sector loading 0.573 raw, 0.714 after Blume) drives most of the gap. The
  memo used gross production including tax barrels in its oil sensitivity, although the adjusted figure was in its
  briefing.
- **Sizing:** the Kelly sizing output saturated at its cap (full Kelly 99%) in both cases, because no scenario was
  below the price.

## 5. Diagnosis: specific defects, traced in the data

### Defects that push growth stocks down

- **O1. Full reversion of margins to the company's past.** The long-run margin moves all the way to the 8-year record's
  trend level, whatever the consensus says for year 5.
  - AMD: earnings margin 26.3% at year 5, moved to 15.0%, against a record trend operating margin of 7.8%.
  - FORM: 23.9% moved to 6.3%.
  - A company whose margin has structurally risen (a new product cycle, scale) is valued as if it returns to its
    past.
- **O2. The additive margin translation breaks.**
  - LITE: the formula "implies" an operating margin of 352% at year 5, because the base year's earnings margin was
    near zero. The long-run earnings margin is then set to **0%**, so nothing after year 10 has value.
  - LIND: 2.8% goes to 0%, because the gap between operating and earnings margin (interest, amortization) exceeds the
    earnings margin.
- **O3. Short horizon, and terminal growth from the record.**
  - The horizon is 5 explicit years plus a 5-year fade.
  - Terminal growth comes from the company's 8-year revenue trend. LITE's record trend is 2.35%, so its terminal
    growth is the 2.36% floor, although revenue is currently growing ~40%.
  - Long-duration growth cannot be represented.

### Defects that push cyclicals, insurers and decliners up

- **U1. Normalization switches off when the vendor's revenue does not match the filed basis, or the margin record is
  too short.**
  - Affected: CMRE, KSS, CHA, AII, JCAP (5 of 19), nearly all on the undervalued side.
  - The long run then capitalizes the latest earnings, growing at the 3.75% anchor forever.
  - CMRE's net income was 0.32–0.56 ($B) in 2021–2025 against 0.01–0.10 in 2018–2020. A container-shipping supercycle
    is treated as permanent.
- **U2. Shrinking companies get positive perpetual growth.** KSS revenue fell from 20.2 to 15.5 ($B) over 2019–2026,
  about −3.7% a year. Its terminal growth is the 2.36% floor.
- **U3. Owner earnings overstated for under-investing decliners.** KSS: D&A 0.70 against capex 0.37 gives owner
  earnings 0.58 against net income 0.27.
- **U4. Peak earnings held for five years.** Years 1–5 follow consensus, and normalization starts in year 6. HRTG
  earned 0.196 in 2025 against 0.027–0.062 in its other positive years.
- **U5. No reference at all.**
  - Affected: 11 of 33. The owner-earnings base is missing, the base-rate median is missing, or the vendor data does
    not verify.
  - The AI then builds its own model on the latest year's earnings, with no cycle check. Shipping at peak day rates,
    oil during a spike, insurers after a good year: all 2–3.7×.

### The analyst

- **A1. Anchoring.** The crux rule checks the *form* of a disagreement with the price, not where the analyst's number
  comes from. A Base copied from the reference passes if one input has a citation.

### Unresolved

- **DDI (2.8×):** no formula defect found. It has a controlling shareholder and a take-private proposal. The discount
  for a controlled company is not modelled.

## 6. The proposed fix

Constraints the operator has set:
- **Fix the engine, never the ticker:** no rule may name or target a specific company.
- **No curve-fitting:** every number is measured from the population or set by principle, never tuned until these 33
  look right.
- **Annotate, never silently gate:** never delete a sample to make a statistic look better.
- **Outcomes must be the acceptance test.**

### Part A: the valuation engine (code; it serves both the reference and the desk's long-run arithmetic)

- **A1. One normalization path for every company with a filed record.**
  - Use filed revenue and earnings, so normalization no longer depends on the vendor's revenue matching (fixes U1).
  - Classify the record's margin series as **cyclical** (it crosses its own median at least twice in 8–10 years) or
    **secular** (it does not). The record already measures this.
  - **Cyclical:** normalize toward the record's through-cycle *median* margin, not a fitted trend line. A trend
    fitted over an upswing extrapolates the peak, as on CMRE. Normalization starts from year 3, so years 1–2 still
    follow consensus, at a speed taken from A2. Not from year 6 (fixes U4).
  - **Secular:** the long-run margin keeps a population-measured share of the consensus year-5 margin's distance
    from the record median, instead of reverting fully (fixes O1).
- **A2. Measure the reversion speeds from the population, before any test.**
  - **Data:** ~6,900 companies' filed history, 2014–2025.
  - **Measure:** for each company-year, the deviation of the margin from its trailing 8-year median, and the fraction
    of that deviation remaining 1, 2, … 7 years later.
  - **Split:** by cyclical or secular, and by sign of the deviation.
  - **Point in time:** each test date uses only years before it.
  - **Use:** the measured table becomes the rule. No parameter is chosen by looking at valuations or returns.
- **A3. Proportional margin translation** (fixes O2).
  - The long-run earnings margin = consensus year-5 earnings margin × (normalized operating margin ÷ implied operating
    margin at year 5).
  - The implied operating margin is computed proportionally (base-year operating margin × m5 ÷ base-year earnings
    margin). When the base-year earnings margin is not positive, or the implied operating margin exceeds 100%, the
    rule works on the earnings-margin record directly.
  - Long-run earnings are never floored to zero unless the record's own median is a loss.
- **A4. Terminal growth for shrinking companies** (fixes U2).
  - When the filed 8-year revenue trend is negative, terminal growth is that trend times the population-measured
    persistence of revenue decline (same method as A2), bounded below at −3%.
  - Positive terminal growth stays within [breakeven inflation, the 3.75% anchor].
- **A5. Fade length from the growth base rate, not fixed at 5 years** (fixes O3).
  - Year by year after year 5, growth follows the population's conditional decay for companies growing at that rate.
    The project already has these growth-persistence base rates.
  - It stops when growth reaches the terminal rate, capped at year 25.
  - A company growing 40% fades over many years; a mature one reaches the terminal rate quickly.
- **A6. The owner-earnings base for decliners** (fixes U3). When filed revenue is shrinking and capex is below D&A, the
  base uses net income plus amortization of acquired intangibles, not D&A − capex. The capex shortfall of a shrinking
  business is not treated as permanent cash.

### Part B: the analyst works from the price

- **B1. The pack no longer gives the analyst a value to start from.** The reference value number is removed. Instead,
  the pack shows **what today's price implies**, computed with the corrected engine:
  - the growth path, margin, fade length and return on new investment the price requires;
  - each placed against the company's own record and the population base rates. For example: "the price requires
    revenue growth of 33% a year for 10 years; 3% of companies of this size have ever done that."
- **B2. The analyst's task becomes:** for each price-implied expectation, judge whether the evidence (filings,
  guidance, contracts, industry data, research) says it is too high, too low or plausible.
  - For any input it disagrees with, it states its own value, the price-implied value, and quoted evidence.
  - The desk recomputes with only those inputs changed. **Intrinsic value = the price, moved only by evidence-backed
    input changes.**
  - No disagreement means IV = price and HOLD.
- **B3. Extraordinary claims need extraordinary evidence.** An input moved outside the population's 10th–90th
  percentile for that company's size and history must cite company-specific hard evidence: signed contracts, filed
  guidance, a backlog. A general outlook is not enough. Otherwise the desk refuses the change. This targets both the
  "2–3.7× undervalued at peak" pattern and the "growth can't be worth this" pattern.
- **B4. Scenarios.** Bull and Bear are built the same way (price-implied inputs moved by evidence). Bear must be
  consistent with the memo's own worst-case narrative, and the desk checks that Bear is not above the price unless an
  input-level reason is given. Kelly sizing uses the Bear scenario as a loss state, so it cannot saturate.

### Part C: validation by outcomes, registered before any result

- **C1. Engine backtest (code only, no AI), 2017–2023, point in time.**
  - Confirmation uses 167 stocks whose outcomes were never looked at.
  - **Bars:**
    1. the share of stocks valued below 0.4× or above 2.5× their price falls substantially;
    2. the extremes no longer sort by company type;
    3. the rank correlation of value ÷ price with 3-year returns is not worse than before.

  The engine is a component, so this is a check, not the main test.
- **C2. Time-travel trial with the AI (Muse).**
  - **Why this date:** a probe dated Muse's knowledge as ending around late August 2025. It is accurate on events up
    to 27 Aug 2025 and wrong or blank from September 2025.
  - **Setup:**
    - briefing packs built as of **2026-01-02**, with filings by filing date and that day's prices;
    - **no web research**, which would leak the future;
    - about 250–290 stocks (today's nomination universe, excluding those listed after the date).
  - **Graded on** the actual total return from 2026-01-02 to ~2026-10-01 (9 months), against the S&P 500.
  - **Compared against two code-only yardsticks:** earnings-yield ranking, and the old reference.
  - **Pre-registered bars (proposed):**
    1. the mean excess return of the AI's undervalued calls minus that of its overvalued calls is positive, with a
       90% bootstrap interval excluding zero;
    2. the rank correlation of AI value ÷ price with excess return is at least the earnings-yield ranking's;
    3. no more than 10% of stocks at below 0.4× or above 2.5× price.
  - **Known limits:**
    - no history of consensus estimates exists, so the trial's packs lack consensus. The price-first design needs it
      less; the old design cannot be run faithfully;
    - 9 months is short and one date is one market regime;
    - survivorship among today's names is small but non-zero.
- **C3. Forward scoring.** From now on, every live verdict is scored at 3, 6 and 12 months against the price and the
  Street target. Real money stays off until the AI beats both.

## 7. What the operator expects

- **The goal stands:** an AI analyst whose valuations are right enough for real money. Turning the system into "a
  research assistant" or "a screener with AI commentary" is not an acceptable outcome.
- **If a test fails,** the next structural cause is found and fixed, with evidence. The goal is not redefined.

## 8. Things the author is unsure of

1. **Whether B1 removes anchoring or moves it to the price.** An analyst that always says HOLD would pass any
   consistency check and make no money.
2. **Whether A1–A5 are enough to remove the type split,** or whether the discount-rate structure also needs changing.
   The sector loading ignores firm leverage and single-commodity exposure (APA at 8.22%).
3. **Whether 9 months of returns from one date can distinguish anything.** With ~250 stocks, the standard error of a
   rank correlation is about 0.06.
4. **Whether a 30B local model can do evidence-based input judgment well,** without months of fine-tuning.

## 9. Questions for you

Please answer each, briefly and concretely:

1. Is the diagnosis right? Do defects O1–O3 and U1–U5 plausibly explain the split, or is something more basic wrong
   with valuing every company by one owner-earnings DCF?
2. Are fixes A1–A6 sound and free of curve-fitting? Which would you change, and how? Is "measure the reversion speeds
   from the population" the right principle?
3. **Price-first (B1–B3):** is "IV = price moved only by evidence-backed input changes" a sound way to get justifiable
   intrinsic values from an LLM? What failure modes do you foresee, and how would you guard against them?
4. Should insurers, banks and other financials, and commodity producers, be valued with different methods? For
   example price-to-book with return on equity, or mid-cycle commodity prices. Or can the normalization in Part A
   carry them?
5. **The discount rate:** keep the market-consistent premium with Blume-adjusted sector loadings, or add firm leverage
   and concentration? How would you do it without fitting?
6. **Validation:** are C1–C3 and the proposed bars the right tests? What would you add or change, given that the AI
   model's training data contains outcomes before about September 2025?
7. Is there a materially better overall approach to "an LLM that produces intrinsic values good enough for real
   money", within one 24 GB GPU and a local 30B model? If so, describe it concretely.
8. What is the single biggest risk in this plan?
