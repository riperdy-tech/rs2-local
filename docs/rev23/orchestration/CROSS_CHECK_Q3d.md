# CROSS_CHECK_Q3d: narrow blind check of the CROSS_CHECK_Q3c fixes (rs2 `review-2026-10/m3q`, `84ad2df..134c213`), 2026-10-31

## Verdict: APPROVE, with conditions (APPROVED WITH CONDITIONS)

- **Approved:** values on both routes may count as E2/E3 evidence for Q3c-1 to Q3c-4 (B13) on every name whose record-neutral reference is positive. Today that is the 9 ready financials, DAR, and 26 of the 28 measured operating bases.
- **Condition (Q3d-1):** a name whose reference is not positive (QUAD and RNG today), or unavailable, does not count as B13 evidence until Q3d-1 is fixed or ruled. On those names the new annotation fires identically on every reply, including the neutral one.
- **What holds:**
  - Both reference builders are what the ruling says. The financial one agrees with an independent closed form to 1.8e-15 on all 9 names.
  - Beyond the two annotation changes, nothing else moved. On 223 cases, values are bitwise equal and statuses, unsupported inputs and failures are identical.
  - `value_far_from_record_neutral` fires exactly outside [0.5, 2] on every one of the 223 cases.
  - Q3c-5 and Q3c-6 are fixed. Q3c-8 is fixed, with a latent conservative side effect.
  - Nothing the model is told changed for any ready name: `[Y]` and `[V0]` are byte-identical on all 9, and both prompt pins pass.
- **The coordinator's statements that need correcting:**
  - "Terminal growth near r with unlimited RONIC: +151% and +135%", listed as annotated. This holds at the probe's r of 0.09. At the 2026-10-29 anchors (r 0.0744), the suite company's case is 1.88x the reference and unannotated. DAR's is 2.54x and annotated.
  - The examples of unflagged cases ("+56% to +72%", "+64%", "+40%") understate the reach. Inside the band, levers reach 1.98x the reference unannotated: RNR with g_T at r − 2 points. At real anchors, that g_T lever (P3) is unannotated on all 8 names where it is status `ok`.

**Scope.** `git diff 84ad2df 134c213` (8 files), read against:
- CROSS_CHECK_Q3c;
- the last section of CROSS_CHECK_Q3_RULINGS;
- `checks.py`, `forecast.py`, `forecast_fin.py`, `desk.py`, `inputs.py`, `run.py` and `memo.py` as they stand.

The commit message and the rulings were not taken as given.

**Suite (foreground, once, bytecode writing off).** `qwen_c/tests -q -p no:cacheprovider`: **633 passed in 215.36 s**.

**Probes.** Scripts and outputs are in `C:\Users\riper\AppData\Local\Temp\claude\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91\scratchpad\q3d\`. `old84\` is `git archive 84ad2df qwen_c`.

| Probe | What it measures |
|---|---|
| `d1_neutral` | The reference on the 9 financials, DAR and the suite company, in two settings. Financial: against a closed form. Operating: the terminal RONIC it chose and the alternatives. |
| `d2_census_op`, `d2b_negative` | The operating reference on every operating and commodity census name with a measured base; QUAD and RNG in detail |
| `d3_levers` + `d4_compare` | Q3c's c2/c3 lever set, plus a code-neutral reply, P3b, O5 and the real DAR smoke reply, at both roots; old against new |
| `d5_pershare` | Q3c-5: V1's per-share detection threshold; the roll-forward variants |
| `d6_items_ends` | Q3c-6 and Q3c-8: `[Y]`/`[V0]` text old against new; the crash case; `fy_ends` and the fiscal-year mapping |
| `d7_ronic_edge` | The operating reference near its terminal-RONIC edge (synthetic) |
| `d8_memo` | `memo.render` v4 on every diagnostics path |

**Settings:**
- **probe:** Q3c's own settings: r 0.10 (financial) and 0.09 (operating), g_anchor 0.035, stub 0.
- **real:** the 2026-10-29 MRI legs the DAR smoke recorded: rf 0.0505, g_anchor 0.0375, ERP 0.04173. The loading comes from `rs2_data.coe_loading`, a read-only JSON read: r 0.0878 for Financial Services and 0.0744 for Consumer Defensive. Stub days run to T 2026-10-30T14:19:07Z.

**Read-only throughout:**
- HEAD stayed `134c213`, and `git status --short --ignored` was identical before and after;
- no `__pycache__` was written, and no worktree file is newer than the start marker;
- no network, model or GPU call (the GPU was at 94% from another job).

---

## The questions

### Q1. Is the record-neutral reply built correctly on both routes? Can it be degenerate?

**`_neutral_fin` (`checks.py:542-554`) is correct and not degenerate on any ready name.**
- It is ROE at the record median throughout, g = min(g_anchor, median/2) for book and terminal growth, and F 10. With constant ROE and growth this is R1 (med − g)/(r − g), rolled forward, per share.
- `d1` agrees with that closed form to at most 1.78e-15 on all 9 names, in both settings.

| | ACIC | ALL | CTBI | HRTG | OPY | RNR | UFCS | UVE | WTM |
|---|---|---|---|---|---|---|---|---|---|
| Reference, real (per share) | 15.45 | 49.78 | 87.67 | 84.15 | 97.95 | 862.80 | 35.73 | 54.82 | 4,489.53 |
| Implied P/B, real | 2.42 | 0.47 | 1.85 | 5.16 | 1.13 | 3.69 | 1.00 | 2.88 | 2.10 |
| Reference / market cap per share | 1.77 | **0.21** | 1.15 | **2.55** | 0.90 | **2.95** | 0.67 | 1.29 | **2.31** |

- None is near zero, negative or refused.
- The last row matters for how E3 reads the annotation. A reply at the market price would be marked "far" on ALL, HRTG, RNR and WTM.
  - ALL's 5-year median ROE of 5.3% carries its 2022–23 catastrophe-loss years.
  - The annotation says "far from the record median". It is not an implausibility flag (observation O-2).
- A median ROE at or below 0 makes the reference unavailable, so no `value_far` can fire. A median just above 0 makes it near zero, so every reply is "far". No ready name is either; both belong to Q3d-1's class.

**`_neutral_op` (`checks.py:557-571`) is as ruled, but degenerate on real names.**
- It is median margins, g_anchor growth, F 10, pooled capex, and terminal RONIC = `ronic0` (or r when `ronic0` ≤ g_anchor).
- The suite company: 17.16 at the probe settings.
- DAR: 51.14 at the probe settings and 66.67 at real.
- The census (`d2`): 28 of the 110 operating and commodity names have a measured base at T. The other 82 are refused upstream (tax 18, stale facts 13, short history 8, and others). Of the 28:
  - **2 references are not positive:** QUAD −8.03 and RNG −61.72 at r 0.0744 (Q3d-1).
  - none is refused;
  - every one used `ronic0`. The lowest terminal factor 1 − g/RONIC_eq is 0.495 (DAR), p10 0.648, median 0.951;
  - reference over price: p10 0.146, median 0.816, p90 2.60. 14 of 26 lie outside [0.5, 2] (AMD 0.069).
- The RONIC rule has a latent edge, and its basis is mixed (Q3d-2). DAR's FY0 is its record-minimum margin year. Its reference would be 12.8%, 38.1% and 56.3% higher at RONIC = r, 0.15 or unlimited.

### Q2. Does any Q3c lever still reach more than 2x the reference at status `ok` with no annotation?

**No, wherever the reference is positive.**
- On all 223 cases (`d4`), `value_far_from_record_neutral` fires exactly when a scenario lies outside [0.5, 2], for bear, base and bull alike.
- The reference depends only on `b`, `bar` and r, so no reply input can move it.
- In production g_anchor is never missing: `coe.cost_of_equity` refuses without it.
- **Exception:** on QUAD and RNG every scenario is annotated identically (Q3d-1). The annotation exists but says nothing about the lever.

Q3c's acceptance list, re-run (base value over the reference; bull for P4):

| Lever | Probe settings | Real anchors |
|---|---|---|
| E0 (Q3c's neutral) | 0/9 annotated (ALL 0.65) | 0/9 annotated |
| Code-neutral inputs | 1.00 on all 9 | 1.00 on all 9 |
| E1 (peak ROE) | 9/9 annotated (CTBI only by `roe_at_record_peak`, 1.11x: a tight record) | 9/9 annotated |
| P2 (peak years 1–4, under p75, F 30) | 3/9 annotated. Unannotated: WTM 1.90, UVE 1.83, RNR 1.67, HRTG 1.55, UFCS 1.50, CTBI 1.07 | 3/9 annotated |
| P3 (g_T = r − 0.0201, generic two-year span) | annotated 1 of the 8 ok names (HRTG 2.14). Unannotated: RNR **1.98**, UVE 1.82, ACIC 1.68, WTM 1.55, CTBI 1.42 | **0 of the 8 ok names.** HRTG 1.93, RNR 1.83, UVE 1.73, ACIC 1.65, WTM 1.57, CTBI 1.49 |
| P4 (bull at max ROE, F 30) | 8/9 annotated (CTBI 1.15 not) | 8/9 annotated |
| DAR O1–O4b (growth lever; g_T lever) | 5/5 annotated (O2 210x, O3 248x) | 5/5 annotated (O4 2.05x) |
| Suite O2–O4 | 0/3 annotated (1.52, 1.55, 1.67) | 0/3 annotated |
| Suite O4b (g_T near r, unlimited RONIC) | annotated, 2.45x | **unannotated, 1.88x** |
| Real DAR smoke reply (model) | — | 1.44x base: inside the band, `margin_at_record_peak`, `valuation_incomplete` |

The within-band rows are the ruling's design ("left unflagged by the band's design"). They are listed here because the ruling's examples understate the reach. On the g_T lever, see observation O-1.

### Q3. Are the Q3c-5, Q3c-6 and Q3c-8 fixes correct?

| # | Status | Evidence |
|---|---|---|
| Q3c-5 | **Fixed; one residual (Q3d-3)** | <ul><li>`checks.py:621-623`. On 18 cases (9 names × the neutral reply and a growth 0.3 reply, real settings), the smallest per-share error detected is now 1e-8 (14 cases) or 1e-9 (4). At `84ad2df` it was 1% to 200%.</li><li>A per-share value computed without the factor is now caught 18 of 18 times, against 13 of 18 before.</li><li>Residual: the factor itself is never recomputed (Q3d-3).</li></ul> |
| Q3c-6 | **Fixed** | <ul><li>`forecast_fin.py:28`, `inputs.py:366`. The suite's first-issued-in-the-record base raises `KeyError '2021-12-31'` at `84ad2df` and renders at `134c213`: the preferred prints as $0.0 before its first filing.</li><li>`[Y]` and `[V0]` are byte-identical on the 9 ready names.</li><li>One unversioned side change: Q3d-4a.</li></ul> |
| Q3c-8 | **Fixed; latent side effect (Q3d-4b)** | <ul><li>`run.py:72` now passes the chained year-ends, so strays are gone.</li><li>But the list is the 6-year record chain (2020–2025 on all 9), not the full chain. The old list was 2018–2025.</li><li>An item dated 2018-12-31 or 2019-06-30 now maps to FY2020. That can only remove a span, never add one.</li><li>The only packet on disk, DAR's, holds the latest 10-K (2026-01-03) and 10-Q (2026-07-04), which map the same under both.</li></ul> |

### Q4. Did the change move anything else?

**No, beyond the intended annotation changes.**
- `d3`/`d4`, 223 cases across both settings, the 9 financials, DAR, the suite and the real DAR model reply, checked at both roots:
  - values are bitwise equal;
  - status, the unsupported keys and the failures are identical;
  - the only annotation changes are 117 `implied_pb_above_record_median_perpetuity` lines removed and `value_far_from_record_neutral` lines added. Every other annotation (`roe_at_record_peak`, `margin_at_record_peak`, `book_release_*`, V2 seam, V6) is unchanged.
- `record_neutral_unavailable` never appeared.
- The operating prompt is untouched: 0 diff lines in `task.py`, `tasks.py` and `prompts`. Both pins (`test_value_task.py:9`, `test_value_fin.py:225`) pass in the suite.
- No consumer reads the removed `pb_record_median_perpetuity` key.
- `memo.render` v4 renders on every path (`d8`): financial, operating, g_anchor missing, and negative reference.

---

## Findings

### Q3d-1. Major for E2/E3 on the affected names (not for the commit or the smoke). A non-positive reference makes B13 uninformative: every reply is "far".

**Where:**
- `checks.py:582-586`: `ratio = None` when the reference is ≤ 0, and every scenario is then annotated;
- `checks.py:546-547`, `checks.py:578-580`: an unavailable reference writes one line, and no `value_far` can fire.

**Measured (`d2`, `d2b`).**
- QUAD:
  - its median operating margin of 1.66% does not cover the non-operating items held by the bridge (`inputs.py:255-264`); the X margin is −0.78% in years 1–5;
  - its reference is −8.03 per share.
- RNG:
  - its median margin is −9.03%;
  - its reference is −61.72.
- On both, three replies get the same three `value_far_from_record_neutral … (neutral not positive)` lines:
  - one equal to the reference;
  - one at the market price;
  - one at 100 times the reference.
- This is Q3c-4's failure mode, the annotation firing on the neutral reply, in another form.
- It affects 2 of the 28 measured operating bases. The financial analogue (a median ROE ≤ 0, or just above 0) is latent: no ready name has it.

**Fix (the coordinator rules; annotation only, never a gate):**
- When the reference is not positive, write one `record_neutral_not_positive` annotation, naming the reference, instead of three per-scenario "far" lines. Treat an unavailable reference the same way.
- Either exclude such names from B13 evidence at E3, or register a fallback reference.
- Add a test on a negative-reference base.

### Q3d-2. Minor (latent; no measured name affected). The operating reference's terminal-RONIC rule has an edge, and its basis is mixed.

**Where:**
- `checks.py:564` tests the asset return, `ronic0 > g_anchor`;
- the desk tests the O5 equity return against g_T (`desk.py:151-153`);
- the terminal factor 1 − g/RONIC_eq goes to 0 as the equity return approaches g.

**Measured (`d7`, the suite base with `ronic0` overridden, r 0.09, g_anchor 0.0375):**

| `ronic0` | Reference | The suite's own clean reply |
|---|---|---|
| 0.0374 | 15.47 (falls back to r) | 1.13x |
| 0.0376 | refused, `ronic_not_above_growth`: no annotation can fire | — |
| 0.0400 | 8.06 | **flagged far, 2.16x** |

- Levered (delta 0.75, kd 0.08): the reference is refused up to `ronic0` 0.05, while the replies are valued.
- **Mixed basis:** margins sit at the record median, but RONIC comes from FY0. DAR's FY0 is its record-minimum margin year. Its reference would be 12.8%, 38.1% and 56.3% higher at RONIC = r, 0.15 or unlimited (`d1`). The band therefore moves with FY0's cycle.
- The fallback to r is not in the ruling and is not recorded in `inputs`.

**Fix:**
- Set the reference's terminal RONIC to r (growth at zero NPV). That removes the edge and the refusal, and the FY0 dependence.
- Or test the equity return, as the desk does.
- Either way, print the RONIC in `how`.

### Q3d-3. Minor (V1 coverage; pre-existing, both routes; the variant Q3c-5's own example named). V1 trusts the engine's roll-forward factor.

**Where:**
- `checks.py:621` uses `v["rollforward_factor"]`;
- `checks.py:810` uses `v.get("rollforward_factor", 1.0)`;
- neither recomputes (1 + r)^(stub/365) (`forecast_fin.py:84`, `desk.py:173`).

**Measured (`d5`).** On all 18 cases, at both commits, two injections pass V1:
- a factor dropped to 1.0: −7.24% at 303 stub days;
- a factor computed at stub/360.

**Fix:** recompute the factor from `inp["r"]` and `inp["stub_days"]` in `_recompute_fin` and in `_recompute`. That is one line each.

### Q3d-4. Cosmetic or latent (one line each)

- **(a) Unversioned change.**
  - `[Y]` on a liquidation-preference base now prints the preferred and common equity (`forecast_fin.py:34`, the `startswith` test). That partly closes Q3c-7(d).
  - It is a change in what the model is told, with no `FORECAST_FIN_VERSION` or `INPUTS_VERSION` bump.
  - No ready name is affected. Bump forecast_fin to v3.
- **(b) `fy_ends`.** Take the full chain, `inputs._year_chain(sorted(eq_all))`, so an item older than the record is not mapped into its first year (`run.py:72`).
- **(c) Code comment.** The comment at `inputs.py:292-293` lists par value, late tagging and redemption as not handled, but omits Q3c-7(e): UVE's 10,000 preferred shares with no value (immaterial).
- **(d) `how` strings.** They omit r, F and the RONIC (`checks.py:552`, `checks.py:569`).

### Observations (rulings stand; no finding)

- **O-1, the g_T lever.**
  - Q3c-2's per-lever annotation `terminal_g_above_anchor` was not built.
  - At real anchors, g_T at r − 2 points (6.77%, against an anchor of 3.75%), with two generic filed sentences as its span, carries no annotation on any of the 8 names where it is `ok`. Its values run 0.92x to 1.93x the reference.
  - The memo prints g_T, so a reader can see it.
  - Recommended (carriable, the coordinator rules): annotate any g_T above g_anchor, as V3g already computes.
- **O-2, how E3 should read the band.**
  - The band 0.5–2x is registered, not measured.
  - The annotation fires on market-consistent values for 4 of the 9 financials and 14 of the 26 operating bases with a positive reference.
  - Only one real reply exists so far: DAR, at 1.44x.
  - E3 should report the distribution of real replies' ratios before any recalibration, and should read the annotation as "far from the record median", not "implausible".

---

## Fix list

| # | Fix | Blocking | Owner |
|---|---|---|---|
| Q3d-1 | A non-positive or unavailable reference gets one stated annotation, not a per-scenario "far"; such names are excluded from B13 evidence, or a fallback is ruled; add a test | **Blocking for counting those names (QUAD and RNG today) as B13 E2/E3 evidence.** Not blocking for the commit, the smoke, or any other name. | coordinator (ruling), builder |
| Q3d-2 | The reference's terminal RONIC = r, or an equity-return test; record the RONIC in `how` | carriable (before the census widens or E3 calibrates the band) | coordinator, builder |
| Q3d-3 | V1 recomputes the roll-forward factor, on both routes | carriable (next commit) | builder |
| Q3d-4 | Bump forecast_fin (liquidation-basis `[Y]`); full year chain in `run.py`; the comment's list; the `how` strings | carriable | builder |
| O-1 | `terminal_g_above_anchor` annotation | recommendation (the coordinator rules) | coordinator |
| O-2 | E3 reports real replies' ratio distribution; reads the annotation as distance from the record | ruling at E3 | coordinator |
| — | Correct the two ruling statements (the suite's O4b at real r; the unflagged reach of up to 1.98x) | carriable (process) | coordinator |
