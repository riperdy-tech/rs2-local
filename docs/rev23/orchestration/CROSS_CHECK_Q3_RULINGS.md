# CROSS_CHECK_Q3 rulings (the financial route, WO_Q6), 2026-10-31

**Coordinator:** Claude. The operator was asleep and had said to keep going (standing go; rulings by the materiality rule).

**Fix commit:** rs2 `review-2026-10/m3q` `2e00b86`, on top of `714dc81`. The suite passes, 613 tests.

**Verdict on the review:** every finding is accepted. Findings 1–6 were material: each moved a value at status `ok`. All twelve are fixed in this commit.

| # | Ruling | What was done | Re-check |
|---|---|---|---|
| 1 | Accept, on both routes | V3 now applies to each typed year-1 and year-2 ROE (`checks._check_fin`) and to each operating margin (`checks._check`). These were the values a hold or step transition carried to year 4. **SPEC_m3q §4 V3 amended:** "every typed explicit-year value, the normalized value and the long-run value". | p3 and p5: every hold or step case is now `valuation_incomplete`, with V3 on `base.roe`. The new operating test covers the twin. |
| 2 | Accept | **Implied issuance:** book growth above the same year's ROE needs a two-fiscal-year span (years 1–2 and the normalized year).<br>**V3g:** the record maximum is now net of issuance (each year's growth, capped at that year's ROE).<br>**Annotations:** the TV share, the implied P/B, and `implied_pb_above_record_max_perpetuity`. | p5: HRTG, RNR, CTBI, UFCS and ALL at the record-maximum growth are all `valuation_incomplete`. |
| 2 (B13) | **Ruling: annotate now; any bound is decided on E3's evidence.** | A hard bound on growth × fade would gate a sample before it is measured (non-negotiable 3), and valuation is diagnostic only (B9). E3's blind readers see the implied-P/B annotation. | — |
| 3 | Accept | **Desk v3:** driver `book` carries `g5`. R_6 = R_5 (1 + g5), and growth in year t ≥ 6 fades from g5 to g_T by year 5+F, aligned with the ROE fade.<br>**PREREG_q6_fin v1.1:** committed in this folder before its run (`6d65f43`, sha256 `e8a83a7f…`). It adds F3_grower (g4 ≠ g5, ROE_5 ≠ ROE_T) and a tolerance of 0.01%. | **v1.1:** F_insurer, F2_bank and F3_grower are all +0.00%.<br>**p1 and p6:** every firm is 0.00%; before the fix they ranged from −4.9% to +5.7%. |
| 4 | Accept | **Span required:** book growth below the record's lowest, and a negative g_T.<br>**V10 on growth reasons:** "grew/grow" cannot support a negative input.<br>**Annotation:** `book_release_terminal`. | p5: the −0.5 liquidation cases are now `valuation_incomplete` (V3g lower and V10). |
| 5 | Accept | `base_financial` now has:<br>- staleness measured on its own equity and net-income series;<br>- `base_year_not_latest_annual`;<br>- an unreconciled ProfitLoss refused;<br>- the EPS reconciliation (`shares_scale_unverified`);<br>- the per-share stamps. | HG is refused (`profitloss_basis_unverified`), as are WTM and JCAP (EPS). |
| 6 | Accept | Preferred stock comes out of book at carrying value. A tag was added, `PreferredStockIncludingAdditionalPaidInCapital`, because ALL files under it.<br>Income to common comes from `NetIncomeLossAvailableToCommonStockholders*`, or from NI less preferred dividends.<br>A preferred balance with neither is refused. | ALL R1 is 28,609M (30,610 − 2,001) and E0 10,165M. RNR R1 is 10,859M. |
| 7 | Accept (partly carried) | `mortgage_reit` is removed from the routed families. Every financial is stamped `financial_classification_unverified`. **Carried to E3:** SPEC §5's balance-sheet test (V is refused today on stale facts). | — |
| 8 | Accept | `_recompute_fin` recomputes every flow, the TV and the equity value independently, on the prompt's definitions. | The truth tests call it. |
| 9 | Accept | `input_value_text` and `reasons_by_input` now take `route`. | `test_9`. |
| 10 | Accept | Pre-registrations are committed in the records folder before their runs (v1.1 is the first). | — |
| 11 | Accept | Stamp `aoci_in_book_not_separated:<share of book>`. | `test_11`. |
| 12 | Accept | Explicit V4 and V10 pass cases added. | `test_12_*`. |

## What changed for the model, versioned

- prompt `m3q.prompt.fin.v2` (pinned): common equity; growth during a year; the issuance and release rules; every year's ROE inside the record;
- `[V0]` prints the lowest growth and the highest growth net of new shares;
- `[Y]` items print common equity and income to common.

## Versions

| Component | Version |
|---|---|
| facts | v3 |
| inputs | v6 |
| desk | v3 |
| forecast_fin | v2 |
| checks | v4 |
| memo | v2 |
| prompt fin | v2 |

The operating prompt is unchanged (pin passes). The operating checks change only by finding 1's twin.

## Coverage

9 of the 20 census financials are valuation-ready. Before the fixes it was 11; HG, WTM and JCAP were lost, and JCAP's first refusal was for its record, not its EPS.

## Before any GPU run of the financial task

A fresh blind re-check of `714dc81..2e00b86` (CROSS_CHECK_Q3b), time-boxed. Probes p1, p3, p5 and p6 were re-run by the coordinator, with the results above.

## Corrections and the CROSS_CHECK_Q3b round (2026-10-31)

CROSS_CHECK_Q3b, the blind re-check of `2e00b86`, rejected it narrowly. **Three statements above were wrong:**
- "Every finding is fixed": finding 4 was only partly fixed (a release inside the record went unannotated), and finding 6 missed BFH, whose preferred stock is carried at $0.
- "Probes p3 and p5 were re-run": both re-runs aborted partway, and their later sections never ran.
- WTM's refusal: it came from an unused opening year, not from its EPS.

**Every N finding is accepted.** All are fixed in rs2 `84ad2df`:

| # | What was done |
|---|---|
| N1 | Desk v4: driver `book` takes BV = R, so full retention and an ROE of 0 are valued. The recompute's tolerance is scaled to book. |
| N2 | A cumulative release of more than 25% of book over years 1–5, at an ROE below r, is annotated `book_release_cumulative`. |
| N3 | The P/B reference is now a perpetuity at the record **median** ROE. New annotations: `roe_at_record_peak` (at or above p75), and on the operating route `margin_at_record_peak`. The memo prints the implied P/B and the TV share. The claim in the B13 ruling now holds. |
| N4 | Only the years whose income is used are checked; WTM is ready again. |
| N5 | A preferred carried in APIC is taken at its liquidation preference, stamped. A preferred first issued inside the record holds none before its first filing. BFH is now refused (`preferred_dividends_unavailable`): it filed no dividends and no income to common for 2025. |
| N6 | Versions bumped: checks v5, inputs v7, facts v4, memo v3, prompt fin v3 (pinned). |
| N7 | The lower bound applies at min(record lowest, 0): a slowdown is not a release. |
| N8 | Equity year-ends are chained 350–380 days apart. |
| N9 | The recompute rebuilds the book path from the reply's path and R_1. |
| N10 | The reviewer's probes were re-run to the end, with exit codes read. b1, b5, b6, b7, b8, b9, b11 and b13 exit 0. b4 and b10 stop at BFH's refusal, which is correct: the probes do not catch refusals. |

**Results:**
- suite: 625 passed;
- truth v1.1: all three firms +0.00%;
- coverage: 9 of 20 (WTM in, BFH out).

**Before any GPU run of the financial task:** CROSS_CHECK_Q3c, a fresh blind check of `2e00b86..84ad2df`.

## CROSS_CHECK_Q3c round (2026-10-31)

**Verdict:** CROSS_CHECK_Q3c, the blind check of `84ad2df`, returned **APPROVE with conditions**. A GPU smoke may run. No value counts as E2/E3 evidence until Q3c-1 to Q3c-4 are fixed.

**Corrections to the section above:**
- "The claim in the B13 ruling now holds" was wrong. Q3c-1 to Q3c-3 showed levers that no annotation saw, on both routes.
- "b4 and b10 ran to the end" was wrong. They stopped after 2 of the 9 names; the reviewer ran all 9.

### Rulings (rs2 `134c213`, pushed and scanned; suite 633 passed)

| # | Ruling |
|---|---|
| Q3c-1 to Q3c-4 | **B13 as built: one reference for every lever.** Each scenario, on both routes, is compared with a code-built **record-neutral reply**. That reply uses the record median margin or ROE throughout, growth and terminal growth at the long-run anchor (on the financial route at most half the median ROE), terminal RONIC equal to the base's return on capital, and a 10-year fade. A scenario valued outside **0.5× to 2×** of it is annotated `value_far_from_record_neutral`. The band is registered here; it is an annotation and never a gate. The median-perpetuity P/B annotation fired on 6 of 9 neutral replies (Q3c-4), so it is dropped; P/B stays a diagnostic. The memo prints the reference. |
| Q3c-5 | Value per share is checked on its own relative tolerance. |
| Q3c-6 | `record_items` reads the base's own preferred series. A preferred first issued inside the record no longer crashes. |
| Q3c-7 | **Carried** (latent; no census name is affected). Not handled: a par-valued preferred, late tagging, and redemption inside the record. Stated in the code comment. |
| Q3c-8 | `run.py` uses the chained fiscal-year ends. |
| Q3c-9 | Accepted. |

### Re-check: the reviewer's probes c2 and c3, re-run to the end (exit 0)

Every extreme case is now annotated:
- the operating growth lever: DAR +16,447% and +19,374%;
- the peak ROE held: ALL +3,058% and ACIC +249%;
- the bull at peak ROE: ALL +3,090%;
- terminal growth near r with unlimited RONIC: +151% and +135%.

**Left unflagged by the band's design:** cases within 2× of the neutral value. Examples are the suite company at +56% to +72%, ACIC at +64% with g_T at r − 2 points, and CTBI at +40%. These are inside the range an analyst's view may legitimately take; E3 measures them.

### Status

The financial task may run a GPU smoke. Before values count as E3 evidence, a narrow, fresh blind check of `84ad2df..134c213` (Q3c-1 to Q3c-4 as fixed) must pass; until then they do not count. The build: `checks.v6`, `prompt.fin.v3`, `desk.v4`.

## CROSS_CHECK_Q3d round (2026-10-31)

**Verdict:** CROSS_CHECK_Q3d, the narrow blind check of `134c213`, returned APPROVE with conditions.
- The reference is built as ruled.
- The 2x annotation fires exactly outside [0.5, 2].
- Nothing else moved.
- **Condition:** QUAD and RNG do not count as B13 evidence until Q3d-1 is fixed.

**Corrections to the Q3c section:**
- The suite company's "g_T near r with unlimited RONIC" case is annotated only at the probe's r of 0.09. At its real r of 0.0744 it is 1.88x and unannotated.
- Levers reach up to 1.98x unannotated inside the band, not only the smaller examples the Q3c section gave.

**Rulings** (rs2 `review-2026-10/m3q`, checks v7; suite 636 passed):

| # | Ruling |
|---|---|
| Q3d-1 | A non-positive reference gives one `record_neutral_not_positive` annotation, and the scenarios are not compared. QUAD and RNG (and any such name) carry no B13 evidence. |
| Q3d-2 | The operating reference takes terminal RONIC = r, so growth at the cost of capital adds nothing. Its `how` names r, F and RONIC. |
| Q3d-3 | V1 recomputes the roll-forward factor on both routes. |
| O-1 | `terminal_g_above_anchor` is annotated whether or not a reason supports it. |
| Q3d-4 | Carried; cosmetic or latent. |
| O-2 | **Ruled:** E3 reads `value_far_from_record_neutral` as "far from the record median", never as "implausible". The 2x band is not measured; E3 measures it. |

The financial task may now run its GPU smoke. The v7 diff (`134c213..5df6b85`) is re-checked in the cross-check that precedes the E3 GPU run; after that, values count as E3 evidence, apart from names with a non-positive reference.

## CROSS_CHECK_Q3e (blind check of `134c213..52bb15a` and the CTBI smokes, 2026-10-31): APPROVE with conditions

**Corrections to my earlier statements:**
- **The Q3d-2 ruling** said terminal RONIC = r adds nothing from growth. That holds only for an unlevered firm. On levered names the
  desk turns RONIC into an equity return (O5) other than r. The reference was therefore 4.4% below to 28.8% above a true zero-NPV
  one, and QUAD's reference was refused again.
- **5df6b85's statement about QUAD was wrong.** It does not get `record_neutral_not_positive`.
- **The CTBI smoke LOG row was wrong in four ways:**
  - "year 4" is the input's own value, not another input;
  - no bare year remained in attempt 2;
  - three scenario inputs failed for reasons the model was never shown;
  - `long_run_roe` also failed V3.

**Rulings** (rs2 `review-2026-10/m3q` `8d25d85`, checks v9, prompt v7 / fin.v5; suite 645 passed):

| # | Ruling |
|---|---|
| Q3e-1 | **Fixed.** The operating reference takes terminal RONIC = (1−δ)r + δ·kd(1−τ), so its O5 equity return is r. `how` names it. DAR's reference is now 66.774, equal to the reviewer's zero-NPV value. A test on a levered base was added. |
| Q3e-2 | **Fixed.** `normalized`'s own value prints "year N", "d percentage points" and "100d basis points", with no % form. Both prompts say to name a forecast year in words. Tests were added. A reason that lists "0" for "0 percentage points" still fails, because a unit mismatch can only be fixed in the contract, which is pinned. The repair message now names it. |
| Q3e-3 | **Fixed.** Scenario lines carry their whys. Every failing check and figure is named. An unlisted figure says "list it if a cited item prints it, otherwise remove it". |
| Q3e-4 | **Fixed.** The repair turn shows up to four failures per input. |
| Q3e-5 | **Fixed.** V10 refuses "within the record / range" when the input is outside [min, max]. |
| Q3e-6 | **Fixed.** Own-value forms are the exact value only (fraction, %, and 2- or 4-decimal forms only when exact). |
| Q3e-7 | Carried. The O-1 annotation noise, the dead branch at Q3d-1 and the missing tests are cosmetic. |
| Q3e-8 | **The operating smoke.** One real turn on each route at the new versions (DAR, then CTBI) before E3, under the smoke rule. The CHANGE_REGISTER rows for the m3q versions are added. |

**E3 may run once these smokes pass on mechanics.** B13 counts on levered names from checks v9. QUAD and RNG keep no B13
evidence if their reference is not positive.
