# Revision 23: defect census of the baseline's first 33 verdicts

Written by the coordinator (Opus 5.5, main session) on 2026-10-06. Source: the run folders
`rs2-local/ab_reports/consensus/*_2026100[4-6]_*` (pack revisions 21 and 22, Qwen v33, one sample each). The baseline
was paused at 21:48 and NUTX was terminated at 22:01 on the operator's order, after an outside review found the
verdicts unusable as valuations.

## The finding

The verdicts split by company type. Growth stocks come out at 0.2–0.45× their price, and cyclicals and insurers near
peak earnings at 2–3.7×. Two mechanisms produce the split:

1. **The analyst copies the code's reference.** In 11 of the 19 stocks with a reference, the analyst's value is
   within 10% of it. AMD, DDI, ECPG, IHS and LIND are at exactly 1.00×.
2. **The reference formula carries specific defects,** listed below, that push each company type in one
   direction. Where there is no reference, the analyst's own discounted-cash-flow model on spot earnings gives the
   same split, without any normalization at all.

| Stock | Reference ÷ price | Analyst ÷ price | Verdict |
|---|---|---|---|
| FORM | 0.21 | 0.19 | overvalued |
| LITE | 0.25 | 0.22 | overvalued |
| LIND | 0.27 | 0.27 | overvalued |
| AMD | 0.45 | 0.45 | overvalued |
| DDI | 2.82 | 2.82 | undervalued |
| BCRX | 2.38 | 1.22 | undervalued |
| KSS | 2.12 | 2.25 | undervalued |
| HRTG | 2.03 | 2.19 | undervalued |
| CMRE | 2.01 | 3.71 | undervalued |
| ESEA | none | 3.69 | undervalued |
| GASS | none | 2.35 | undervalued |
| APA | none | 2.00 | undervalued |

The 10-01 backtest had already scored the reference's fitness as a fail: buy-call lift +2.1 points against a +5
bar, and a rank correlation of 0.063. It also recorded that "the 8-year median margin target is wrong for trending
companies". That finding was carried and never fixed.

## Defects that push growth stocks down

**O1. The long-run margin moves all the way back to the company's past trend level.** This is `margin_rule`,
revision 18: `target = max(0, om_trend)`, reached by year 10, whatever the consensus says for year 5. A company
whose margin has structurally risen is valued as if it returns to its past.

| Stock | Earnings margin at year 5 | Long-run margin | Record trend of the operating margin |
|---|---|---|---|
| AMD | 26.3% | 15.0% | 7.8% |
| FORM | 23.9% | 6.3% | 7.9% |

**O2. The translation between operating margin and earnings margin breaks.** `OM_5 = om_L + (m5 − x_L)/(1 − tax_L)`
and `m_long = max(0, m5 + (1 − tax_L)(target − OM_5))` are additive in margin points.
- LITE: the consensus "implies" an operating margin of **352.1%** at year 5. The long-run earnings margin goes from
  31.6% to **0.0%**, so nothing after year 10 has any value.
- LIND: from 2.8% to **0.0%**. The gap between operating and earnings margin (interest, amortization) is larger than
  the earnings margin itself.
- An additive gap can wipe out earnings that a proportional rule would keep.

**O3. Terminal growth comes from the company's own record and the horizon is short.** Five years explicit, then a
five-year fade into a terminal value. LITE's terminal growth is 2.36%, the floor, because its record's revenue trend
is 2.35%. The record's revenue trend does not describe a company whose revenue is growing at 40%.

## Defects that push cyclicals, insurers and decliners up

**U1. Normalization switches off when there is no usable revenue path or record.** When the vendor's revenue is
missing or not on the filed basis ("no revenue path"), or the margin record is too short, `margin_rule` is never
applied. The long run then capitalizes the latest earnings, growing forever, mostly at the 3.75% anchor:
- CMRE: 2.01×. Shipping profits from the 2021–2025 supercycle (net income 0.32–0.56 against 0.01–0.10 in
  2018–2020), grown at 3.75% forever.
- KSS: 2.12×.
- CHA: 1.33×.
- AII and JCAP: 1.93× and 1.40×; their margin records are too short.

This is the biggest single defect: 5 of the 19 reference names, nearly all on the undervalued side.

**U2. A shrinking company gets positive growth forever.** `terminal_growth_default` holds the company's revenue
trend between breakeven inflation (2.36%) and the anchor. KSS's revenue fell from 20.2 to 15.5 ($B) over 2019–2026,
about −3.7% a year, and it is valued growing at +2.36% forever.

**U3. Owner earnings overstated for under-investing decliners.** KSS: owner earnings 0.578 against net income 0.27.
D&A is 0.70 and capex 0.37, so a shrinking retailer's under-investment is counted as cash. This affects years 1–5
(the long run follows earnings at the year-5 ratio).

**U4. Peak earnings are held for five years before any normalization.** Years 1–5 follow the consensus. HRTG, a
Florida property insurer, earned 0.196 in 2025 against 0.027–0.062 in its other positive years (2018–2024, with
losses in 2021–2022). The long-run margin is cut to 8.6% only from year 6, so the peak sits in the most heavily
weighted years.

**U5. No reference at all, so the analyst values spot earnings.**
- **The stocks:** ESEA (3.69×), GASS (2.35×), APA (2.00×), MRP (2.23×), HG (2.10×), CBL, ECO, GTE, NGVT, NREF and
  FLXS.
- **Why there is no reference:**
  - the owner-earnings base is missing (ESEA, FLXS, GASS);
  - the growth base-rate median is missing (APA);
  - the vendor's revenue does not verify (CBL, ECO).
- **What the analyst does instead:** builds its own model on the latest year, with no cycle check. ESEA's memo used
  container-ship day rates at a multi-year high.

**Unresolved: DDI (2.82×).** No formula defect was found. It has a small tangible capital base (return 235%), large
cash, a controlling shareholder and a nonbinding take-private proposal (WGames, $11.25 per ADS, 2026-04-29). The
discount for a controlled company is not modelled. That is a judgment the analyst should make from evidence, not a
formula fix.

## The analyst

**A1. The analyst anchors on the reference.** The crux rule checks the form of a disagreement with the price (an
input, a reason, a quoted citation). It does not check where the analyst's number came from. A Base copied from the
reference passes as long as one input has a citation. Phase 4's acceptance test measured agreement between two runs
and the form of citations, and both are easiest to satisfy by sitting on the reference.

## What follows

`brief_valuation_core.md` (revision 23) fixes O1–O3 and U1–U4 as general rules, measured from the population and
never fitted to these names. It rebuilds the analyst to start from the price (A1, U5).
`registration_timetravel.md` registers the outcome tests before any result is seen.
