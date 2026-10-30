# CROSS_CHECK_Q3b: blind re-check of the CROSS_CHECK_Q3 fixes (rs2 `review-2026-10/m3q`, `714dc81..2e00b86`), 2026-10-31

## Verdict: REJECT (narrow)

No GPU run of `valuation_inputs_financial` until N1 and N2 below are fixed. N3 must also be fixed before any values are kept as E2 or E3 evidence. Each fix is a few lines.

- **What holds:**
  - Findings 1, 3, 5, 7–12 are fixed.
  - The desk v3 alignment is exact: my own engine agrees to 1.2e-12 on 3,950 random scenarios.
  - The operating-route change only adds V3 flags. Values are unchanged (to 1e-9) on 1,502 replies.
  - The re-registered truth test is now a real test. The pre-fix path fails it on all three firms.
- **Why REJECT:**
  - Finding 4 is only partly fixed. On ALL, a book release *inside* the filed record gives **+263% at status `ok` with no annotation**. That is the same name and the same size as the original blocking scenario, and the fix-list item that would flag it (a cumulative-release annotation) was not built (N2).
  - The B13 ruling's mitigation does not reach the residual lever. A long-run ROE at the record's peak year gives **+139% to +3,058% at status `ok` with no annotation** on 7 of the 9 ready names (N3). For 5 of the 9, "last" *is* that peak.
  - The finding-8 recompute raises a false `engine_defect` on 17 of 96 full-retention replies on real names (N1). This was already present at `714dc81`.
- **The coordinator's statements that need correcting:**
  - "All twelve are fixed": finding 4 is partly fixed, and finding 6 misses BFH.
  - "p3 and p5 were re-run": both re-run scripts crashed partway through (N10).
  - WTM's refusal is attributed to EPS. It actually comes from an unused year's ProfitLoss stamp (N4).

**Scope.** `git diff 714dc81 2e00b86` (12 files), read against:
- CROSS_CHECK_Q3 and its rulings;
- PREREG_q6_fin v1.1;
- `q6_fin_truth.py`, `synthetic.py` and `gen_fin_fixture.py`;
- SPEC_m3q §4–§6.

Nothing in the commit message, the rulings or the docstrings was taken as given.

**Suite (foreground, once).** `qwen_c/tests -q -p no:cacheprovider`, with bytecode writing off: **613 passed in 213.20 s**.

**Probes.** Scripts and outputs are in
`C:\Users\riper\AppData\Local\Temp\claude\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91\scratchpad\q3b\`.
`old714\` there is `git archive 714dc81 qwen_c`, used for before/after comparisons.

| Probe | What it measures |
|---|---|
| `b1_v1_zero_flow` | The V1 recompute on full-retention replies (canned bank) |
| `b2_alignment` | Desk v3 against my own engine (random scenarios); driver `revenue`, v2 against v3; the truth firms |
| `b3_compare` + `b3_diff` | 714dc81 against 2e00b86 on the same replies: the DAR smoke replies (the only real ones on disk), 1,500 operating and 1,500 financial seeded replies |
| `b4_levers` | Bypass variants and residual levers on the 9 ready names |
| `b5_census`, `b6_wtm_aii`, `b7_ends`, `b8_bfh` | The 20 census financials through `facts.annual_facts` and `base_financial`; preferred-stock tags; equity instants |
| `b9_operating_b13` | B13 on the operating route |
| `b10_v1_real`, `b10_old` | The V1 false engine defect on real names, at 2e00b86 and at 714dc81 |
| `b11_truth_discriminates` | The v1.1 fixtures through the pre-fix path |
| `b12_span_limit`, `b13_zero_roe` | V3's stated span limit; a typed ROE of 0 |
| `p1`, `p6` (re-run as is); `p3_fixed` (p3_rerun with its `record_items` calls fixed); `p5_rerun` (re-run) | The earlier reviewer's probes |

**Assumptions.** The real-name probes use r 0.10 and g_anchor 0.035, as p5 did; the MRI chain was not called. T is 2026-10-30T14:19:07Z, the builder's coverage T.

**Read-only throughout:**
- worktree HEAD stayed `2e00b86`;
- `git status --short --ignored` was identical before and after;
- no `__pycache__` was written;
- no cache file is newer than the commit;
- no network call, no model call, no GPU.

---

## Per-finding status

| # | Status | Evidence |
|---|---|---|
| 1 | **Fixed, on both routes** | <ul><li>Every hold or step case is now `valuation_incomplete` with V3 on `base.roe`: p3 §1 (+160% case) and p5 (all five names).</li><li>Variants are flagged: a bull `roe` replaced and held; a normalized baseline pushed outside the record.</li><li>Operating route: see Q2 (b3).</li><li>Stated limit, already present: V3 counts a two-fiscal-year span but does not check that the evidence reaches the premium. ROE 60% supported by quotes of 14.0% and 14.2% is `ok` at +160%, annotated (b12).</li></ul> |
| 2 | **Fixed as specified for the builder; residual in N3** | <ul><li>Implied issuance catches all five record-maximum-growth scenarios from p5.</li><li>The V3g maximum is now net of issuance: HRTG 0.7375 → 0.6726, RNR 0.7755 → 0.5520.</li><li>The implied-issuance check is complete. The years 3–5 and fade-year (g − ROE) are convex combinations of the checked endpoints, with the same weights.</li><li>**Variant E2** (book growth = ROE = the record-maximum ROE, F 30) is still status `ok`, annotated only: HRTG +994,900%, ALL +879,454%, ACIC +33,718%, OPY +1,799%, UFCS +442%, CTBI +82% (b4). The B13 ruling accepts this.</li><li>The TV share and implied P/B go to `res["diagnostics"]` but are not printed in the memo.</li></ul> |
| 3 | **Fixed** | <ul><li>b2: my own engine, written from the prompt's definitions, agrees with the production path to ≤ 1.22e-12 on 3,950 random scenarios. They cover linear, step and hold transitions, normalized years 3–5, F 1–30 and negative growth.</li><li>Driver `revenue` is bitwise identical between v2 and v3 on 3,000 random inputs.</li><li>p1 and p6 now show 0.00%.</li><li>The v1.1 firms match truth to within 1.3e-15.</li><li>The old path fails v1.1: −1.19%, −0.44%, −2.25% (b11).</li></ul> |
| 4 | **Partly fixed: N2** | <ul><li>Fixed: the −0.5 cases and every g_T < 0 case are refused (p5, b4 E4).</li><li>Not fixed: a release *inside* the record (growth at the record minimum + 0.001 in years 1–5, F 1, g_T 0, reasons worded without "grow") is status `ok` with no release annotation: **ALL +263%**, UFCS +23%, OPY +8% (b4 E3).</li><li>The fix list's "annotate a cumulative book release above a registered share" was not built.</li><li>V10 is lexical: HRTG at −0.5 (inside its record, minimum −0.618) was caught only by the word "grew".</li></ul> |
| 5 | **Fixed; one over-refusal: N4** | <ul><li>HG is refused with `profitloss_basis_unverified`; JCAP with `shares_scale_unverified` (6.262 against 5.64).</li><li>Staleness, latest annual and the per-share stamps are tested.</li><li>WTM is refused only because of the opening year's ProfitLoss, which is not used (b6).</li></ul> |
| 6 | **Fixed for ALL and RNR; BFH missed: N5** | <ul><li>ALL R1 28,609M, E0 10,165M; RNR R1 10,859M (b5), as the rulings claim.</li><li>BFH's preferred stock (filed `PreferredStockValue` 0, liquidation preference $75M) is treated as common equity with no stamp: +2.31%.</li></ul> |
| 7 | Fixed as ruled | <ul><li>`mortgage_reit` is no longer routed (`run.py:31`).</li><li>`financial_classification_unverified` is stamped.</li><li>SPEC §5's balance-sheet test is carried.</li></ul> |
| 8 | **Fixed, with a tolerance defect: N1, N9** | <ul><li>`_recompute_fin` reproduces every flow, the TV and the equity value from separate code. It raised no false assertion on 3,950 random inputs.</li><li>It does raise on exactly-retained flows (b1, b10).</li></ul> |
| 9 | Fixed | `checks.py:242` chooses the key by `route`; `test_9`. |
| 10 | Fixed (process) | <ul><li>PREREG v1.1 was committed as `6d65f43` at 23:56:28 KST; its sha256 `e8a83a7f…` matches the file.</li><li>`q6_fin_truth.json` was written at 23:56:42.</li><li>The truth test still bypasses `facts.py` (see Q4).</li></ul> |
| 11 | Fixed | `inputs.py:327-329`; CTBI is stamped `aoci_in_book_not_separated:-0.076` (b5). |
| 12 | Fixed | `test_12_v4_*` and `test_12_v10_*`. |

---

## New findings

### N1. Major. The V1 recompute raises a false `engine_defect` on full-retention replies, and a typed ROE of 0 makes the whole reply `invalid`.

**Where:**
- `checks.py:535-536`: `same()` uses a tolerance relative to the flow, `1e-9 × max(1, |a|, |c|)`.
- `checks.py:549-551`: each flow compared there is a difference of book-sized numbers.
- `desk.py:261`: `bv = E / roe` is not exactly R in floating point, and it divides by zero when an ROE is 0.
- `run.py:129-132`: the AssertionError becomes `engine_defect`, with no value and no repair turn.

**Scenario.** A reply with book growth equal to ROE in years 1–2: a no-dividend insurer, a natural reply for HRTG, which pays none.
- At 2e00b86: **17 of 96** such replies raise, on ACIC, ALL, BFH, HRTG, OPY, RNR and UFCS (b10). Example: ALL at 0.05 gives "year-2 flow −3.8e-06 != 0.0".
- The defect is not new to this commit: 16 of 97 raise at 714dc81, where the recompute covered years 1–4.
- A typed ROE of exactly 0.0, in base or in a scenario, returns `invalid` with "ZeroDivisionError: float division by zero" (b13).

**Fix:**
- For driver `book`, set `bv = R` (no division).
- Compare flows with a tolerance scaled to book, for example `1e-9 × max(1, |a|, |c|, book_t, book_{t+1})`.
- Add a test with g = ROE, and one with ROE = 0.

### N2. Major (finding 4 residual). A book release inside the record raises a low-ROE financial's value at status `ok` with no annotation.

**Where:**
- `checks.py:426-431`: the lower V3g binds only below the record's lowest growth.
- `inputs.py:338`: that lowest growth is "as filed", so it includes OCI and buyback years. The maximum, by contrast, is netted to ROE.
- `checks.py:435-436`: `book_release_terminal` fires only for g_T < 0.

**Scenario (b4 E3).** ALL's record minimum is −0.3245, its 2022 AOCI year.
- Inputs: growth −0.3235 in years 1–5, ROE at the median 0.0531, F 1, g_T 0, reasons without growth words.
- Result: **status `ok`, +263%** (P/B 0.86 against 0.24), and no annotation except a V2 seam annotation.
- The same reply on UFCS gives +23%, and on OPY +8%.

**Fix:**
- Build the fix list's cumulative-release annotation: book released over years 1–5 above a registered share, with ROE < r.
- The coordinator rules whether the lower bound should be measured net of OCI and buybacks, symmetric with the maximum.

### N3. Major (B13). The implied-P/B annotation is referenced to a perpetuity at the record's *maximum* ROE, so it cannot see a peak-year ROE held for the long run. The operating route has no B13 annotation at all.

**Where:**
- `checks.py:513-517`: the threshold is `pb_ref = (ROE_max − g_T)/(r − g_T)`.
- For any reply with every ROE ≤ ROE_max and growth ≤ g_T, the implied P/B is ≤ pb_ref (from the residual-income identity), so the annotation never fires.
- `checks.py:693-705`: the operating route has no implied-multiple annotation.
- `memo.py`: does not print `diagnostics` (the TV share and implied P/B).

**Scenario (b4 E1).** Every ROE, normalized and long-run, at the record maximum, which is inside the record and needs no span; growth 3.4%; F 10; g_T 3.5%. Every name ends at **status `ok` with no annotation**:

| Name | Base value against the neutral reply |
|---|---|
| ALL | **+3,058%** (799 against 25) |
| OPY | +255% |
| ACIC | +249% |
| UVE | +219% |
| RNR | +182% |
| HRTG | +149% |
| UFCS | +139% |
| CTBI | +9% |

- The only signal is the V6 label `cycle_position peak`, which is not an annotation.
- For ALL, HRTG, ACIC, UFCS and UVE, the record's `last` equals its `max`. The natural reply "normalizes at last" is this lever.
- Operating route (b9), on the suite company: growth at the record maximum, margins at the maximum, F 30 gives `ok` with no annotation: **+51.8%** with terminal RONIC "unlimited", +37.6% with RONIC 0.15.

**Fix:**
- Reference the annotation to a perpetuity at the record **median** (or p75) ROE.
- Annotate a normalized or long-run ROE at or above p75 (`roe_at_record_peak`).
- Print the implied P/B and TV share in the memo.
- Add the operating analogue: implied terminal multiple against a record-median perpetuity.
- The coordinator amends the B13 ruling's claim that "E3's blind readers see the implied-P/B annotation".

### N4. Minor. WTM is refused for a year whose net income is not used.

**Where:** `inputs.py:284-286` loops over `ends`, which includes `ends[0]`, the opening balance. Net income is used only for `ends[1:]` (`inputs.py:301`).

**Data (b6).** WTM's 2020 ProfitLoss is stamped unverified. With only that stamp cleared, WTM is ready: ROE record −0.0705 to 0.2468, net income tagged `NetIncomeLoss` from 2021. One callable name is lost; coverage is 9 instead of 10.

**Fix:** check `ends[1:]` only.

### N5. Minor (silent default). Preferred stock carried in APIC with a filed `PreferredStockValue` of 0 is treated as common equity, and the universal stamp that used to disclose this was removed.

**Where:** `facts.py:81-83` (the ladder) and `inputs.py:293` (`has_pref` requires a value > 0).

**Data (b8, b10):**
- BFH issued 75,000 preferred shares in 2025: liquidation preference $75M, proceeds $71M, `PreferredStockValue` 0. It gets no stamp, and the neutral value is overstated by **+2.31%**.
- UVE has the same pattern at $0.1M, which is immaterial.
- The prompt tells the model "Book equity here is common equity", which is false for BFH.

**Fix:**
- When `PreferredStockSharesOutstanding` > 0 or `PreferredStockLiquidationPreferenceValue` > 0 and no carrying value is found, subtract the liquidation preference with a stamp, or refuse.
- Also check the ladder's order. Its first tag, `PreferredStockValue`, is the par value for some filers.

### N6. Minor (audit). `CHECKS_VERSION` and `INPUTS_VERSION` were not bumped.

**Where:** `checks.py:21` is still `m3q.checks.v4`; `inputs.py:23` is still `m3q.inputs.v6`. Both labels are unchanged from 714dc81, while behaviour changed on both routes:
- operating: 597 of 704 previously `ok` seeded replies change status (b3);
- financial: `base_financial` changed.

The rulings' version table presents them as versioned.

**Fix:** bump to `checks.v5` and `inputs.v7` in the fix commit.

### N7. Minor. The lower V3g fires on ordinary slowdowns when the record's lowest growth is positive, and the prompt calls a slowdown "releasing book".

**Where:** `checks.py:427-431` and `task.py:103-105`.

**Data:**
- BFH (record minimum +4.56%): growth 3.4% is `valuation_incomplete` (b4 E1).
- Synthetic 20%-ROE bank: growth 5% or 10% is flagged "below the filed record's lowest 0.1996" (p3_fixed §3).

**Fix (coordinator rules):** bind at min(record minimum, 0), or only when ROE < r, the only case in which a release adds value.

### N8. Minor (already present, latent). `base_financial` takes the last six equity instants without checking that they are fiscal-year ends a year apart.

**Where:** `inputs.py:275`.

**Data (b7):**
- HG has instants at 2021-11-30 and 2021-12-31, a 31-day "year" in the growth record.
- PRCH has quarterly instants.
- Both names are refused today for other reasons.

**Fix:** keep only the ends of 350–380-day net-income flows.

### N9. Minor. V1 does not rebuild the book path from the reply.

**Where:** `checks.py:539-541` reads R_1..R_5 and `g5` from `forecast_fin.assemble`'s output. A wrong R or g5 at the interface between assemble and the desk, finding 3's class, passes V1. Only the truth test covers it, and only for linear transitions with N 5.

**Fix:** recompute R_2..R_5 and g5 from `inp["_path"]` and R_1.

### N10. Minor (process). The coordinator's re-run probes aborted partway.

**Where:**
- `p3_rerun.py:65` raises TypeError (`record_items(low)` without `b`), so §2 and §3 never ran.
- `p5_rerun.py:97` stops at HG's refusal, so the preferred-stock section never ran.

The rulings say p3 and p5 were re-run "with the results above". `p3_fixed` here runs §2 and §3: the base's growth lever passes every base check, and it is incomplete only on the probe's own bear and bull values.

**Fix:** re-run probes to the end and read the exit code.

**Cosmetic (one line each):**
- `book_release_terminal` and the V3 messages repeat once per scenario or year.
- `run.py:163`'s help text still lists `mortgage_reit`.
- `task.py:93` still names mortgage REITs.
- The [V0] ROE label still says "net income over opening book equity".

---

## The questions

**Q2. New defects.**
- **Desk alignment:** exact. R_6 = R_5(1 + g5), and growth in year t is g5 + (g_T − g5)(t − 5)/F, reaching g_T in year 5+F together with the ROE. The TV is B_N(ROE_T − g_T)/(r − g_T). Driver `revenue` is unchanged (b2).
- **Operating V3 twin:**
  - It changes nothing else. Values are identical (to 1e-9) on 1,502 replies, no flag is removed, and annotations are unchanged (b3).
  - It flags every typed year-1 or year-2 margin outside the record, including under a linear transition. That is broader than the hold or step bypass, but it is what the unchanged operating prompt already told the model, and SPEC §4 is amended.
  - On DAR's real smoke replies it adds V3 on `base.op_margin` (0.20 against a maximum of 0.1865) and on `bull.op_margin`. The status was already `valuation_incomplete`.
  - Consequence: a bear case below the record minimum now needs a two-year span.
- **Preferred handling and facts tags:** correct for ALL and RNR; BFH is missed (N5); the new concepts do not reach the operating base.
- **New `_check_fin` checks:**
  - implied issuance: correct and complete;
  - lower V3g: N2 and N7;
  - V10 on growth: lexical only;
  - annotations: N3.
- **`_recompute_fin`:** separate code and correct on the prompt's definitions; N1 and N9.

**Q3. B13.**
- **Annotate rather than bound: defensible.** Valuation is diagnostic only (B9), and a bound would gate before E3 measures (non-negotiable 3).
- **But "annotate" is not delivered.** A reply still reaches an extreme value at status `ok` with **no annotation**: ALL +3,058% from a peak ROE inside the record (N3), and +263% from a release inside the record (N2).
- **At the extreme, the annotation is only an annotation.** Status `ok` with values of 10³–10⁴ times neutral (E2).
- **The operating route has nothing at all** (+51.8%).

**Q4. The truth test is now a real test.**
- **It discriminates:** the pre-fix path fails all three firms at 0.01% (−1.19%, −0.44%, −2.25%, b11).
- **Truth is independent:** a 300-year simulator; the scenario is taken from the simulator's specification, not from production output.
- **It tests the identity and the alignment only:**
  - an ideal analyst;
  - a linear transition, N 5, F 10;
  - firms whose fade the desk can represent exactly;
  - facts built as a dict, so `facts.py` is bypassed. N5's BFH defect sits exactly in that gap.

---

## Fix list

| # | Fix | Blocking | Owner |
|---|---|---|---|
| N1 | `bv = R` for driver `book`; V1 tolerance scaled to book; tests for g = ROE and ROE = 0 | **blocking** (any GPU run) | builder |
| N2 | Cumulative-release annotation (finding 4's unbuilt item) | **blocking** (any GPU run) | builder |
| N2 | Lower bound net of OCI and buybacks, or not | ruling before E3 | coordinator |
| N3 | Annotation referenced to the median or p75 perpetuity; `roe_at_record_peak`; P/B and TV share in the memo; operating analogue; amend the B13 text | **blocking before any value is kept as E2/E3 evidence** (a plumbing smoke may run without it) | builder, coordinator |
| N4 | Check ProfitLoss stamps on `ends[1:]` only | carriable (land with N1) | builder |
| N5 | Detect preferred carried at zero par (shares outstanding or liquidation preference), subtract with a stamp or refuse; check the ladder's order | carriable (before E3) | builder |
| N6 | Bump checks and inputs versions | carriable (in the fix commit) | builder |
| N7 | Lower V3g at min(record minimum, 0) or only when ROE < r; prompt wording | carriable | coordinator, builder |
| N8 | Equity instants restricted to fiscal-year ends | carriable | builder |
| N9 | V1 rebuilds the book path from the reply | carriable | builder |
| N10 | Re-run probes to completion before citing them | carriable (process) | coordinator |
| — | Cosmetic items | carriable | builder |

After N1–N3, re-run these probes and expect:

| Probe | Expected result |
|---|---|
| `b10_v1_real` | 0 assertions |
| `b4_levers` | E1 and E3 annotated |
| `b9_operating_b13` | annotated |
| `p3_fixed`, `p5_rerun` | run to the end |
