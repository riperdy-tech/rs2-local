# Cross-check request 18: our AI analyst copies a formula. How should it choose its valuation inputs?

Written 2026-10-16 by the coordinator. **This document is self-contained.** Where an answer would rest on code you cannot see, say so rather than
assume. Critique freely: the coordinator rules on each point, and the operator decides.

## 1. The system
- **A stock screener** nominates about 160 US stocks.
- **For each one, a local AI analyst** (an open-weights model on one GPU, currently "Muse Glimmer", a 30B model) receives a long briefing and
  values the company. The briefing holds:
  - filed financials (10 years), recent quarters and the full latest earnings release;
  - Wall Street's consensus forecasts;
  - a research brief;
  - price action and macro context.
- **The analyst chooses the valuation inputs** (base earnings, growth path, long-run margin, terminal growth, scenarios). **Code does all the
  arithmetic** through a "desk" tool, a discounted-cash-flow engine that values years 1–5 explicitly, then a fade, then a terminal value.
- **A buy or sell call needs a "crux":** the input the price gets wrong, quoted evidence from the company's own filings, checked by code.
  Without a valid crux the verdict is HOLD.
- **Two independent runs** must agree on direction and sit within 30% of each other.
- **Real money will depend on the verdicts.** It is halted now.

## 2. What went wrong
A baseline run of the frozen analyst produced valuations an outside review called unusable. **Growth stocks came out at 0.2–0.45× their
price, and cyclicals and insurers near peak earnings at 2–3.7×.**

A defect census found two causes:
1. **The analyst copied a code-computed "reference value"** (the CONSENSUS-IMPLIED VALUE: Wall Street's forecasts run through a fixed
   formula). It was printed in the briefing as context. In 11 of 19 stocks the analyst's value was within 10% of it; in 5 it was exactly
   equal.
2. **The formula itself has defects that push different company types in opposite directions:**
   - it forces the long-run margin back to the company's historical trend even when the business has structurally improved (AMD: 26% today
     to 15% long-run);
   - it breaks the translation between operating and earnings margin;
   - it takes terminal growth from the company's record;
   - normalization switches off when data are thin, so spot earnings grow forever (shipping at a supercycle peak, worth 2× its price);
   - a shrinking retailer grows at +2.4% forever;
   - peak insurer earnings are held for five years.

## 3. What we just found
We planned to hide the reference number until the analyst commits to its own value, then reveal it with code-enforced limits on any
revision ("option a").

**But hiding the number does not remove the anchor.** The briefing also gives the analyst **default inputs** to start from: base earnings,
growth for years 1–5, the long-run margin, the terminal growth, the fade. **These defaults are the reference formula's own inputs.** Run
through the desk unchanged, they return the reference value **to the cent in 16 of 16 saved briefings**, and within 1% in 9 of 9 accepted
analyst runs. The instructions tell the analyst to start from the defaults and deviate only with evidence.

So "copying the reference" was really "starting from the defaults and changing little", and the formula's defects sit inside the defaults.

**What we have to fix them with:** population tables, measured point-in-time from 2012–2025 SEC filings:
- how much of a margin change persists after k years, by band;
- how abnormal margins revert, by cyclicality;
- growth fade curves to 10 years;
- long-run growth for shrinking companies.

## 4. The choices
| | What the analyst gets | What it decides | Pros | Cons |
|---|---|---|---|---|
| **(i) Fix the defaults** | Defaults from a corrected formula, using the population tables | Deviations from the defaults, with evidence | Smallest change; stable runs | The analyst is still anchored to one formula; the formula alone showed no stock-picking power (a stock it valued at 2× price earned only about 3% more over 3 years) |
| **(ii) No defaults** | Facts only: filings, consensus, research | Every input, from scratch; then the reference is revealed | Truly independent; matches "the AI chooses every input" | More run-to-run variation (an earlier test with this model failed on exactly that); more room to go wrong |
| **(iii) Facts and population ranges** | Filed facts, consensus years 1–2, and **population ranges** for each long-run input ("firms like this keep about X% of a margin gain after 5 years; P25–P75 is …") | The long-run inputs, within the ranges, with cited reasons to go outside them; the reference revealed afterwards | Judgment stays with the analyst; formula defects cannot slip in silently; the ranges keep it grounded; code checks each choice | New behaviour to test; more for the analyst to do; ranges could become a new anchor |

**The coordinator's recommendation is (iii).**

## 5. Questions
1. **Is the diagnosis right?** Is "defaults equal the formula" the real anchoring mechanism, and is anchoring to a corrected formula (i) still
   a problem?
2. **Which option,** or a different design? If (iii): should the ranges be shown as a median plus P25–P75, or the full distribution? Should
   the analyst's choice be anchored at the median or free inside the range? What should require a citation?
3. **How do we stop the analyst "going crazy"** in (ii) or (iii) without re-creating an anchor?
4. **How should we test it** on a few stocks before a full run? What would show the anchoring is gone and the values are sensible, not just
   different?
5. **Anything else** a careful reviewer would challenge.

At the end, give: your choice, the one guardrail you consider essential, and the one test you would run first.
