# CROSS_CHECK_Q3: blind review of the financial route (rs2 `review-2026-10/m3q`, `136aefd..714dc81`), 2026-10-30

## Verdict: REJECT

No GPU run of `valuation_inputs_financial` (smoke included) until the blocking items below are fixed and their probes re-run.

- **Two critical findings.**
  - V3 is bypassed by years 1-2 ROE held to year 4 (finding 1).
  - Book growth at the record maximum, faded over 30 years, gives values thousands of times the neutral one (finding 2). The record
    maximum is one peak-earnings or share-issuance year.
  - Both end at status `ok`.
- **Major findings:**
  - an identity error in the book path's timing (finding 3);
  - an unchecked liquidation lever (finding 4);
  - two silent data defects on callable names, HG +42% (finding 5) and ALL +35% (finding 6).

**Scope.** Commit `714dc81` against `136aefd`, read against:
- WO_Q6;
- CROSS_CHECK_Q, Q2 and their rulings;
- SPEC_m3q §4-§5;
- PREREG_q6_fin v1.0, `q6_fin_truth.py`, `gen_fin_fixture.py` and `synthetic.py`.

Nothing in the commit message or the docstrings was taken as given.

**Suite (foreground, once).** `qwen_c/tests -q -p no:cacheprovider` with bytecode writing off: **589 passed in 205.26 s**.

**Probes.** Scripts and outputs are in
`C:\Users\riper\AppData\Local\Temp\claude\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91\scratchpad\q3x\`:

| Probe | What it checks |
|---|---|
| `p1_alignment` | Independent clean-surplus engine against the simulator and the production path |
| `p2_census_fin`, `p2b_hg` | The 20 census financials, offline, from the stored companyfacts |
| `p3_checks_fin` | `checks.check(route="financial")` on the suite's own canned bank |
| `p4_operating_twin` | The same lever on the operating route; the shared-helper change |
| `p5_real_names` | Levers and data defects on HG, ALL, RNR, HRTG, CTBI and UFCS |
| `p6_alignment_real` | Finding 3 on realistic parameters |
| `p7_issuance` | What made each name's record maximum book growth |

**Assumptions in the real-name probes.** `p5` uses r 0.10 and g_anchor 0.035; the MRI chain was not called. The census T is the builder's own
coverage T, 2026-10-30T14:19Z.

**Read-only throughout:**
- worktree HEAD `714dc81`, and `git status --ignored` was the same before and after;
- 329 cache files, none newer than the commit;
- no `__pycache__` was written;
- no network call, no model call, no GPU.

**What holds:**
- The simulator's truth values recompute independently to 4 decimals: F_insurer 112.2664, F2_bank 1494.1452.
- Every explicit-year flow satisfies flow = E − ΔBV.
- The ROE fade is aligned correctly. With book growth flat, the production path is exact (p1).
- The financial prompt is price-masked, and nothing in [Y] or [V0] postdates T.
- On the operating route:
  - the `shape`, `_prob_reasons`, `reasons_by_input` and `memo` refactors are line-identical in behaviour;
  - `test_value_task.py` is untouched and its pin passes.

Severity is critical, major or minor. Each finding was verified by running code unless it says otherwise.

---

## Critical

### 1. Critical. V3 is bypassed on the financial route. Years 1-2 ROE outside the record, held to year 4 by the transition, ends at status `ok`.

**Where:**
- `checks.py:397-399`: V3 builds `vals["roe"]` and then skips it (`if k != "roe"`).
- `forecast.py:53-61` (`_blend`): `hold_then_linear` or `step_at_year` with `transition_year` = normalized year = 5 holds the year-2 value through
  year 4.
- `task.py:110-112`: the prompt states the rule for any ROE ("A return on equity outside the filed record's minimum and maximum ... needs
  a reason that quotes ... two different fiscal years"). The checks enforce it only on the normalized and long-run ROE, so the prompt and
  the checks disagree.

**Scenario on the suite's canned bank** (record max 0.1049; p3):
- Inputs: `base.roe` [0.60, 0.60], `hold_then_linear` or `step_at_year`, transition_year 5, normalized year 5.
- The years 1-5 ROE used are 0.60, 0.60, 0.60, 0.60 and 0.1034.
- The only `base.roe` reason is the suite's own: "The filed return on opening equity was 10.5% in the last year."
- Result: **status ok, base +160.1%**.

**Real names** (ROE years 1-2 = 2 × the record max, held to year 4, no transition reason; p5). Every case is **status ok**:

| Name | Base value against the neutral reply |
|---|---|
| CTBI | +35.3% |
| HRTG | +62.0% |
| UFCS | +98.9% |
| RNR | +100.8% |
| ALL | **+1,232.8%** |

**Operating twin (pre-existing, not in this diff).**
- Where: `checks.py:540` (`k != "op_margin"`); SPEC §4 V3 names only the normalized and long-run margins.
- Inputs: `op_margin` [0.60, 0.60] (record max 0.16) with hold or step at 5.
- Result: **status ok, +77.5%** on `test_value_checks.py`'s company (p4).

**Fix:**
- Apply V3 to every explicit-year ROE that `build_path` produces (years 1-5). At minimum, apply it to years 3-4 whenever a transition holds the year-2 value there.
- Apply the same rule on the operating route; the coordinator amends the SPEC §4 V3 wording.
- Add fail and pass tests for hold and for step.

### 2. Critical. Book growth at the record maximum, faded over up to 30 years, gives an unbounded value at status `ok`. Nothing ties forecast book growth to the forecast ROE.

**Where:**
- `inputs.py:291-292`: `book_growth_max` is one year's total book growth.
- `checks.py:453-467`: V3g checks only the years 1-2 and normalized growth against it.
- `checks.py:85`: `fade_years` up to 30, with no check on growth × fade.

**Data** (p2, p2b, p7). The maximum is one peak-earnings year or one issuance year:

| Name | book_growth_max | What made it |
|---|---|---|
| AII | 1.0754 | 2025: a $93.0M IPO on $162.4M of opening equity |
| RNR | 0.7755 | 2023 (5,325 → 9,455M): $1,351.6M of common issued, NI $2,561M |
| HRTG | 0.7375 | 2025: retained earnings at a 67% ROE, no issuance |
| UVE | 0.4763 | 2025: NI $183M on $373M of opening equity, no issuance tag |
| ALL | 0.4276 | 2025: NI $10,282M on $21,442M of opening equity, no issuance tag |
| ACIC | 0.3964 | not decomposed |
| BFH | 0.3706 | not decomposed |

**Scenario:** growth just under the record max in years 1-5, normalized year 3, ROE and long_run_roe at the record median, F 30, g_T 3%,
with the [Y]-quoted reasons (p5). Results, all status ok:

| Name | Base value against the neutral reply |
|---|---|
| HRTG | **258,615 against 63.49 (+407,205%)** |
| RNR | **3,352,270 against 643.17 (+521,110%)** |
| CTBI | +43.8% |
| Synthetic high-ROE bank (ROE 20%, r 10%, record max growth 20%; p3) | +93.0% at F 10, +314.6% at F 30 |

- The only flag is a V2 seam annotation.
- For the low-ROE names, the same reply gives negative values (ALL −10,115) at status ok, with only `value_not_positive`.
- Context: V3's ROE band is wide for cat-exposed insurers (HRTG [−0.45, 0.6726], ALL [−0.0517, 0.4795]). A long-run ROE of 67% needs no span.

**Relation to earlier rulings:** this is CROSS_CHECK_Q2 N7's lever (B13). Here V3g, the ruled fix, does not bind:
- the record maximum is a single peak or issuance year;
- a growth of 73.7% at HRTG's median ROE of 27.9% implies issuing about 46% of book every year, and no check sees it.

**Fix:**
- Builder, blocking:
  - A forecast book growth above the same year's forecast ROE (implied issuance) needs V3-type support. This catches both the HRTG and the
    RNR scenario.
  - Measure V3g's record net of filed issuance.
  - Annotate the terminal value's share of the value and the implied P/B.
- Coordinator, before E3: rule on a bound for growth × fade on both routes (B13).

## Major

### 3. Major (identity error). The book-growth path is one year early. The analyst's year-5 growth never enters, and the growth fade ends at year 4+F while the ROE fade ends at year 5+F.

**Where:**
- `forecast_fin.py:66-68`: the path builds R_1..R_5 from g_1..g_4 only.
- `desk.py:238`: `g5 = R5/R4 − 1`, which is g_4.
- `desk.py:252-253`: R_6 = R_5(1 + g_at(6)), so year 5's ΔBV uses the fade's first step.
- `desk.py:254`: the ROE fade is aligned correctly.
- The prompt contradicts the code:
  - `task.py:101`: "fade_years is how many years after year 5 book growth takes to reach terminal_g";
  - `task.py:99`: normalized.book_growth "is that year's growth of book equity".

**Measured** (p1, p6). An independent engine on the simulator's convention reproduces truth to 0.0000% for both registered firms. The
registered errors (F_insurer −1.19%, F2_bank −0.44%) are therefore entirely this offset, not method noise. On firms built to the prompt's
own definitions (ideal analyst, r 10%):

| Firm | Production error |
|---|---|
| Flat 15% growth, F 20 | **−4.93%** |
| Rising growth 2→10% | **−4.49%** |
| HRTG-like (ROE 28%, growth 15→6%) | **+5.65%** |
| RNR-like | +2.70% |
| Declining growth 12→4% | +2.14% |
| HRTG-like, normalized year 3 (the early fade alone) | −2.77% |

**Why the truth test passes:**
- Both registered firms hold growth flat in years 1-5.
- Neither has an ROE fade: F_insurer's ROE is constant, and F2_bank's ROE_5 equals ROE_T.
- The ±3% tolerance absorbs a structural offset that an exact engine would not have.
- `book_growth_year5_unused` (`checks.py:308`) does not describe the shifted fade.

**Fix:**
- Carry g_5: R_6 = R_5(1 + g_5), and the fade runs from g_5 in year 6. Alternatively, pass closing book R_0..R_5 with E_t = ROE_t R_{t−1}.
- The desk change is versioned.
- V1 recomputes year 5 and the fade (finding 8).
- Re-register the PREREG (v1.1) with a firm whose g_4 ≠ g_5 and one whose ROE_5 ≠ ROE_T, and an ideal-analyst tolerance of 0.01%.

### 4. Major. A liquidation lever: book shrinkage below the record minimum, and negative terminal growth, are unchecked. They raise the value of a low-ROE financial at status `ok`.

**Where:**
- `checks.py:464-467`: V3g checks the upper side only.
- `checks.py:419-422`: V7 applies only when g_T > 0.
- `checks.py:397`: V10 never reads the book_growth or terminal_g reasons.

**Scenario:** book growth −0.5 in years 1-5, g_T 0, F 1 (p5, p3). Every case is status ok:

| Case | Base value against the neutral reply |
|---|---|
| ALL (ROE median 5.34%) | **+263.1%** |
| UFCS | +29.3% |
| Synthetic bank (ROE 6%, r 10%, record min growth +4.76%), growth −0.5 | +158.4% |
| Same, growth −0.9 | +169.9% |
| Same, perpetual g_T −0.5 | +162.4% |

- The supporting reasons say "Book equity grew from $122.0 million to $128.0 million" and "expects deposits and loans to grow". Both pass the
  keyword rule.
- The WO stamps capital constraints as not modelled (`capital_constraint_not_modeled`), which is exactly why a regulated balance sheet
  releasing book at will must not pass unchecked.

**Fix:**
- Mirror V3g: book growth below the record minimum, and g_T < 0, need a two-fiscal-year span.
- Annotate a cumulative book release above a registered share, and g_T < 0 with long_run_roe < r.
- V10 reads growth reasons: a "grew"/"grow" claim cannot support a negative input.

### 5. Major. `base_financial` lacks the operating base's data rules (rulings 5, 8 and 18). HG, a callable name, is overvalued 42% at status `ok`.

**Where:**
- `inputs.py:267-293`:
  - no NI against diluted-EPS reconciliation (the operating base has it at `inputs.py:221-227`);
  - no `base_year_not_latest_annual` (`inputs.py:100-101`);
  - no split or ADS stamps.
- `inputs.py:275`: `_stale` is measured against the latest revenue year (`facts.py:210`), so it is inert for a bank that files no revenue concept
  (CTBI; p2).
- `facts.py:196-209`: an unreconciled ProfitLoss is "left as filed".

**Data** (p2b):
- HG files only `ProfitLoss`, which is consolidated and includes the noncontrolling interest. It is divided by parent-only `StockholdersEquity`,
  stamped `profitloss_basis_unverified`.
- NI per diluted share is 8.089 against a filed diluted EPS of 5.55 (**+45.8%**). The operating base would refuse `shares_scale_unverified`.
- The whole ROE record is inflated:

  | Year | As built | On EPS × shares |
  |---|---|---|
  | 2025 | 0.3607 | 0.2475 |
  | 2024 | 0.2994 | 0.1955 |
  | Median | 0.2339 | 0.1756 |

- [V0] and [Y] show the inflated record to the model.
- A neutral reply (ROE at the record median) gives 85.79 against 60.27 on EPS × diluted shares (**+42.3%**), status ok (p5).

**Ruling 8 is latent.** At T 2026-10-30 every ready name's FY0 equals its latest annual period. It will bind at formations where
companyfacts lags a new 10-K (the CX pattern).

**Fix:**
- Port the share reconciliation (refuse `shares_scale_unverified`), `base_year_not_latest_annual` and the per-share stamps.
- Measure staleness against the equity and NI series.
- Refuse a ProfitLoss that does not reconcile.
- Add an HG-pattern test.

### 6. Major. Preferred stock is valued as common equity (stamped `preferred_not_separated` only).

**Where:** `inputs.py:281-293`. `equity` is `StockholdersEquity`, which includes the preferred. `net_income` is `NetIncomeLoss`, before preferred
dividends.

**Data** (p2, p5):

| Name | Preferred | Effect on a neutral reply |
|---|---|---|
| ALL | $2,001M (6.5% of book); $117M of preferred dividends | 28.59 per share, against 21.10 with the preferred subtracted at carrying value (**+35.5%**), and 20.01 on a common-only base (+42.9%) |
| RNR | $750M | +2.6% |
| BFH | $75M liquidation preference | not measured |

- The effect is large where the ROE is low relative to r, because the preferred is then a large share of the common's value.

**Fix:**
- Subtract the filed preferred (carrying or liquidation value) from book.
- Subtract its dividends from NI, or use `NetIncomeLossAvailableToCommonStockholders*`.
- Refuse when a preferred balance is filed without its dividend.

## Minor

### 7. Minor. SPEC §5's balance-sheet test is not built, and `mortgage_reit` is routed with no name and no coverage.

**Where:** `run.py:31` and `run.py:41-42` route on the CLI or census family alone.

**What is affected:**
- The census marks V (Visa) financial, though SPEC §5 records "V operating". V is refused today only by `facts_stale`.
- The JCAP and WTM rows carry SIC codes only. OPY's lending share is 1.6%.
- No census row is a mortgage REIT, the coverage run covered none, and their preferred stock and fair-value earnings are not handled.

**Fix:**
- Run the reserve, loan or deposit share test before routing, and make a failure a `no_call`.
- Keep `mortgage_reit` out of `FINANCIAL` until a name is covered.

### 8. Minor. V1 on the financial route recomputes years 1-4 only.

**Where:** `checks.py:492-503`. Year 5, the fade, the terminal value and the equity sum are not recomputed; the operating V1 checks the sum at
`checks.py:682-683`.

**Why it matters:** finding 3 sits in exactly the part that is not recomputed. SPEC §4 V1 names "financial-route clean surplus".

**Fix:** recompute all n flows from the analyst's paths, then the PV, the TV and the equity value.

### 9. Minor. A shared helper changes operating behaviour.

**Where:** `checks.py:241`. `input_value_text` prefers `normalized.book_growth` whenever that key is present.

**Scenario** (p4): an operating reply with an extra `book_growth` 0.37 in `normalized`:
- the citable own-value text becomes "37.0% 37%";
- the real rev_growth 0.04 drops out;
- the status is still ok.

**Also:** `INPUTS_VERSION` moved to v6 (`inputs.py:23`), but the operating base did not change. Operating results now carry a new version
label with identical values.

**Fix:** choose the key by route, not by its presence.

### 10. Minor. The truth test and the pre-registration process.

- **The truth test does not exercise `facts.py`.** `q6_fin_truth.facts_of` builds the facts dict directly, so no tag ladder, NCI, preferred or AOCI
  is tested; findings 5 and 6 are invisible to it.
- **The run order cannot be audited.** PREREG_q6_fin.json and its outputs sit under the gitignored `scratch/` (stocks-workspace `.gitignore:72`).
  "Registered before the run" rests on file times (23:06 against 23:07).
- **Fix:** commit each pre-registration before its run.

### 11. Minor (reading plus data). AOCI is inside book equity.

- CTBI's AOCI is −7.6% of book at FY0 (ACIC −2.3%, HRTG −2.1%).
- The flows E − ΔBV carry no OCI, so a pull-to-par recovery is not valued.
- **Fix:** stamp `aoci_in_book_not_separated` with its size.

### 12. Minor. WO items.

- [V0] prints no tax line. This is deliberate: O3 values net income.
- V4 and V10 have no explicit pass fixture; they pass only implicitly through `clean()`.
- Everything else the WO lists is present:
  - the route parameter;
  - the keyword classes;
  - V3, V3g, V4, V7, V9 and V10 on ROE and book growth;
  - `ronic_not_above_growth`;
  - `capital_constraint_not_modeled`;
  - the pinned prompt;
  - the coverage run (11 of 20 ready, reproduced).

**Brief question 3 (leaks).** No price or post-T figure reaches `INSTRUCTION_FIN` or `render_base_fin`: [S0] goes through `mask_price`, and [Y] and
[V0] come from T-filtered facts. The prompt contradicts the checks in two places, findings 1 and 3.

---

## Verdict: REJECTED for any GPU run of the financial task

| # | Fix | Blocking | Owner |
|---|---|---|---|
| 1 | V3 on every explicit-year ROE, or at least on years 3-4 under hold or step; tests | **blocking** | builder |
| 1 (twin) | The same on the operating route; SPEC §4 V3 wording | **blocking before E3** (not in this commit) | coordinator, builder |
| 2 | Support required for book growth above the forecast ROE (implied issuance); V3g record net of filed issuance; annotate TV share and implied P/B | **blocking** | builder |
| 2 | A bound on growth × fade (B13) on both routes | ruling before E3 | coordinator |
| 3 | Carry g_5 and align the book fade; versioned desk change; PREREG v1.1 with a g_4 ≠ g_5 firm and an ROE_5 ≠ ROE_T firm; tolerance 0.01% | **blocking** | coordinator (WO, PREREG), builder |
| 4 | Lower-side V3g and g_T < 0 span; book-release and g_T < 0 annotations; V10 on growth reasons | **blocking** | builder |
| 5 | Port the share/EPS reconciliation, `base_year_not_latest_annual` and the per-share stamps; staleness on equity and NI; refuse an unreconciled ProfitLoss; HG test | **blocking** | builder |
| 6 | Preferred out of book and NI, or refuse | **blocking** (ALL +35.5%) | builder |
| 7 | SPEC §5 balance-sheet test; `mortgage_reit` unrouted until covered | carriable (stamp before E3) | builder, coordinator |
| 8 | V1 over all n flows and the equity sum | carriable (lands with 3) | builder |
| 9 | `input_value_text` by route | carriable | builder |
| 10 | Commit pre-registrations before runs | carriable (process) | coordinator |
| 11 | AOCI stamp with its size | carriable | builder |
| 12 | Explicit V4 and V10 pass fixtures | carriable | builder |

After the blocking items, re-run `p1`, `p3`, `p5` and `p6`. Each one turns its `ok` into a refusal or annotation, or its error into 0.00%,
once its item is fixed.
