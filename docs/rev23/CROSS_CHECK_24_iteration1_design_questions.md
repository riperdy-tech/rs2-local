# Cross-check request 24: two design questions from the first benchmark iteration of the staged analyst

Written 2026-10-21 by the coordinator. **This document is self-contained.** You advise, the coordinator rules on each point, and the
operator decides. Records: `github.com/riperdy-tech/rs2-local`, branch `docs/rev23-records`, folder `docs/rev23/`
(`SPEC_rev26_staged_analyst.md`, `PLAN_terminal_reinvestment.md` end sections, cross-checks 22 and 23). Code: branch
`review-2026-10/r26-int`.

## 1. Background you need

**The system.**
- A screener nominates about 160 US-listed stocks.
- A local AI analyst (Qwen 3.8 27B on one GPU) values each one.
- Code does all arithmetic through a "desk" (a DCF engine).
- Real money will depend on the verdicts (undervalued, hold, overvalued). Trading is halted; everything here is a paper test.

**The staged design (revision 26), built after two briefing-form designs failed.** Each stage is a separate model session.
1. **Research:** the analyst registers facts, each with a verbatim quote that code verifies.
2. **Blind forecast,** three samples: with no price and no analyst consensus shown, the analyst gives:
   - years 1–2 revenue growth and operating margin;
   - a "normal" state by year 3–5, as a historical percentile plus a stated delta;
   - the transition shape;
   - the long-run margin.

   Code builds the path, converts it to the valuation basis, and values it.
3. **Reveal:** the price, what the price implies, and a basis-corrected consensus are shown. The analyst states a **crux** and may revise
   once, citing a fact.
4. **Memo,** written from the frozen numbers.

**The crux.** It is the core of a directional verdict. The analyst names 1–3 of the desk's judgment inputs:
- the cost of equity;
- the fade length;
- terminal growth;
- the terminal return on new investment;
- the long-run margin.

For each it gives its own value, the value the **price implies** for that input, and quotes supporting its own. Code computes the
price-implied value with a solver: it holds every other input at the analyst's forecast and finds the value of that one input at which the
desk's value equals the price, within the input's bounds (for example terminal growth 0–4.47%, cost of equity up to 25%, long-run margin
0–100%). If no value within bounds reaches the price, the entry is **"not reachable"**.

**The current rule:** one failing entry makes the whole crux invalid; an invalid crux after one correction turn means **no call**. This
rule exists because, earlier, analysts made directional calls resting on cruxes that did not hold up; a verified, reachable crux was the
guard.

**Why the stage design uses a positive base cash flow.** The desk's arithmetic on this path scales owner earnings from a base-year owner
cash flow ("base_cf" = net income + D&A − capex, attributed), via κ = base_cf / (revenue × after-tax margin). The desk refuses base_cf ≤ 0.

**A parallel design, D2, exists but is not enabled.** It values years 1–5 on earnings less reinvestment at filed levels, with positivity
on earnings (E_0 > 0), not cash flow. It is parked behind an open ruling: how the long-run fade charges reinvestment when margins move.
Revenue growth and earnings growth give answers about ±20% apart.

**The benchmark.** 12 names were drawn by a pre-registered hash order. Each name's research is frozen, then stages 2–4 are re-run per
design iteration, with at most 3 iterations and a pre-registered pass bar:
- 0 loops;
- 0 incoherent;
- ≥ 83% of *callable* names coherent;
- median spread across the three blind samples ≤ 20%;
- ≥ 83% with all three samples agreeing on direction;
- a low pull toward revealed numbers;
- 0 memo verdict mismatches.

Data no-calls (names the desk cannot value) are reported as coverage, outside the denominator. A pass authorizes a book-wide *paper* run
only.

## 2. What iteration 1 showed

**Code defects** (fixed; iteration 1 is being re-run and does not count):
- the memo verifier could not read any verdict;
- a valuation error was recorded as a no_call instead of stopping the run;
- stale input names in an error message;
- per-entry crux detail was not recorded.

**Per name:**

| Name | Outcome |
|---|---|
| MSGE | overvalued (Base about $39 against price $80; the three samples within 11%) |
| BUD | undervalued (18% spread) |
| GOLD | undervalued, but the samples ranged from $66 to $128 (85% spread) |
| ITGR | valued (33% spread) |
| TASK | no call: crux not reachable, even after the correction turn |
| DAC | no call: crux not reachable, even after the correction turn |
| MCY | no call: a malformed corrected crux |
| PACS, LPG | data no-calls (no D&A filed, so no base cash flow; no tax provision filed, so no tax rate) |
| OGE, HNRG, PTCT | **base_cf negative** (−$0.054B, −$0.039B and −$0.086B), so the desk refuses. Now recorded as data no-calls, before any model time |

## 3. Question A: negative base cash flow removes 3 of 12 names

**The three names:**
- **OGE** is a regulated utility: positive earnings, but capex above net income plus D&A.
- **HNRG** is a coal and power producer.
- **PTCT** is a loss-making biotech.

With PACS and LPG, **5 of 12 are uncallable**, which leaves 7 for the pass bar. A pass on 7 is weak evidence.

**One detail:** the pre-registered draw rule already skips names whose base-year owner earnings ("oe_base") are not positive. These three
passed it, because it tested a related but different field (`long_run.oe_base`) from the desk's base cash flow (`owner_earnings_default_b`).

**The coordinator's options:**
- **A1.** Keep the panel; score the 7 callable; report the 5 as coverage.
- **A2 (recommended).** Treat the draw rule's intent ("a positive cash base") as applying to the desk's actual base field. The three are
  skipped as ineligible, recorded as such, and the next names in the pre-registered order are drawn. The 4-name holdout shifts along the
  same order. This is the existing rule applied to the field it was meant to test, not a new filter chosen after seeing results. The
  replacements are drawn mechanically.
- **A3.** Enable D2 for these names now. This is rejected for this benchmark: it changes the valuation engine mid-test, and D2 has an open
  ruling.

**Also on record:** a utility with capex above cash flow is a normal company, not a data error. The book-wide system will need D2 (or
equivalent) to value it. This question is only about the benchmark's sample.

## 4. Question B: when no crux input can reach the price, the rule forces a no call

**Measured** on each name's median forecast: which of the 5 offered inputs the solver could reach.

| Name | Price | Median Base | Reachable inputs |
|---|---|---|---|
| TASK | 8.22 | 20.54 | **none.** The nearest bounds give 8.78 (cost of equity at 25%), 8.34 (terminal return at its floor) and 8.36 (long-run margin 0%) |
| DAC | 158.17 | 491.0 | **none.** The nearest bound gives 187 |
| MSGE | 79.60 | 39.37 | cost of equity (5.9%), long-run margin (21.9%) |
| BUD | 82.59 | 93.93 | cost of equity, terminal growth, terminal return, long-run margin |
| GOLD | 39.35 | 73.24 | cost of equity, terminal return, long-run margin |
| ITGR | 126.70 | 93.86 | cost of equity, fade (41.9 years), long-run margin |

When the analyst's value is very far from the price (2.4× for TASK, 3× for DAC), no single input within bounds can bridge the gap. The
analyst cannot form a valid crux however good its reasoning, so the rule makes no call inevitable.

**The coordinator's options:**
- **B1.** Keep it: no call. Conservative; a 2–3× gap is often a symptom of a wrong forecast, not a bargain.
- **B2 (recommended).**
  - Allow a crux entry marked **"beyond reach"**: the input, the analyst's value with verified quotes, the bound, and the value at the bound
    (which still sits beyond the price).
  - A crux made only of beyond-reach entries is valid but the verdict carries `price_beyond_every_input_reach` and is **non-actionable
    until reviewed**.
  - Rationale: "even the most favourable value of each judgment input cannot justify the price" is logically a strong statement, but only
    if the forecast path itself (margins and growth in years 1–5) is right. The review checks exactly that.
  - The benchmark scores such names on coherence like any other, and reports them separately.
- **B3.** Widen the solver's bounds, or let the crux cite the forecast path itself (years 1–5 margins and growth) as an input. Not chosen
  yet: the path has 10+ numbers, so "the price implies X" is not one number. That needs a design.

## 5. Secondary observation (no ruling asked yet)
GOLD's three blind samples spread 85% ($66, $73, $128), and ITGR's 33%. This is what the three-sample gate exists to catch; GOLD would fail
the spread bar. We will inspect which forecast inputs differ between its samples after the re-run.

## 6. Questions
1. **Question A:** is A2 sound, or is it post-hoc sample shaping? If A1, is 7 callable names enough for the registered pass bar to mean
   anything?
2. **Question B:** B1, B2 or B3? If B2, what review should a "beyond reach" call require before it may be acted on, and should a stage-2
   spread or path check be part of it?
3. Is there a better way to define the crux for large mispricings, one that still guards against calls resting on an unverified forecast?
4. Anything in the iteration-1 outcome that should change the plan before the re-run?

At the end, give your ruling recommendation for A and B in one line each, and the one risk you would watch most in the re-run.
