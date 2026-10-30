# CROSS_CHECK_Q3e: blind check of `134c213..52bb15a` (checks v7–v8, prompt v6 / fin.v4) and the CTBI smokes, 2026-10-31

## Verdict: APPROVE with conditions (APPROVED WITH CONDITIONS)

- **The arithmetic is right, and nothing else moved.**
  - On all six real replies on disk (CTBI smokes 1–2, DAR), `134c213` and `52bb15a` agree exactly on status, unsupported keys, values, labels and refused reasons (e5).
  - Smoke 2's three values and its reference match an independent clean-surplus recomputation to 0.0 relative error (e2a).
- **Q3d-1, Q3d-3 and O-1 do what the rulings say.** S1 is in both prompts, and both pins pass.
- **Condition 1 (Q3e-2, before E3).** A reason may state its input's own value, but code does not print `normalized` the way the prompt defines it (the year; `delta_pts` in percentage points). That was the only failure of `base.normalized` in 2 of the 6 real attempts, and one of its failures in 3 more.
- **Condition 2 (Q3e-1).** Q3d-2's "terminal RONIC = r" is growth-neutral only when δ = 0.
  - On levered names the desk's O5 makes it an equity return other than r. The reference then sits −4.4% to +28.8% from a zero-NPV one, and QUAD's reference is now refused.
  - Fix it (one line) before E3, or count no B13 evidence on levered operating names until it is recomputed.
- **S2 is partial (Q3e-3).** Scenario inputs still get a repair line that says nothing.
- **Q2's example is two things.**
  - Refusing 0.115 and 0.025 in the `fade_years` reason is correct: they are other inputs' values, and the prompt allows only printed figures and the input's own value.
  - "Year 4" is the input's own value, so refusing it is a code defect (Q3e-2).

**Method:**
- **Suite** (foreground, bytecode off, no cache): **639 passed in 193.66 s**.
- **Probes e1–e8** are in `C:\Users\riper\AppData\Local\Temp\claude\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91\scratchpad\q3e_probes\`. All ran to the end (exit 0).
- **Facts.**
  - The smoke replays (e1, e2, e4a, e5–e8) use the exact bytes each smoke used: `sec_store.get_pinned` on the sha256 in result.json.
  - The census probes (e3, e4b) read the store's latest receipts offline, at CROSS_CHECK_Q3d's T and settings.
- **Read-only throughout:**
  - HEAD stayed `52bb15a`, and `git status --ignored` was identical before and after;
  - no worktree file is newer than the start marker;
  - no model, GPU or network call.

## Findings

### Q3e-1. Blocking for B13 evidence on levered operating names. The Q3d-2 reference is not growth-neutral when δ > 0, and it now refuses QUAD.

**Where:** `checks.py:568` (`ronic = r`); `desk.py:45-49` (O5), `desk.py:151-153` and `desk.py:212-213`.

**Why.**
- `terminal_ronic` is a return on capital in an equity-frame desk. The desk applies ROE = RONIC + δ/(1−δ)·(RONIC − kd(1−τ)) and TV = X(1 − g/ROE)/(r − g).
- Growth is worth nothing only when ROE = r, that is at RONIC* = (1−δ)r + δ·kd(1−τ), not at r.

**Measured.**
- **Census (e3, the 28 measured operating bases, g 0.0375; 20 are levered).** The reference as built, against the zero-NPV one:

  | r | Median | Highest | Lowest |
  |---|---|---|---|
  | 0.0744 | +6.1% | MTCH +28.8% (also DVA +28.6%, DELL +24.3%, MA +20.0%) | EAT −4.4%, PARR −3.5% (where kd(1−τ) > r) |
  | 0.09 | +5.9% | +19.2% | — |

  Both rows cover the 18 levered names with positive references. The 8 unlevered names are at 0.0%.
- **DAR at the smoke's settings (e6).** Built 75.20, zero-NPV 66.77 (+12.6%); `134c213` gave 66.67. The DAR reply's base ratio fell from 1.44x to 1.27x (e5).
- **QUAD (δ 0.75, kd 13.5%).** The O5 return of r is −3.9% at r 0.0744 and 2.3% at 0.09, so the reference is refused: `record_neutral_unavailable: equity_ronic_not_positive` / `ronic_not_above_growth` (e4).
  - At `134c213` it was −8.03, and at RONIC* it is −4.41.
  - So the refusal Q3d-2 was meant to remove is back, and 5df6b85's message (QUAD gets `record_neutral_not_positive`) is wrong for QUAD.
- **The FY0 dependence is gone.** Replacing `ronic0` moves the reference by at most 2.2%.

**Fix:**
- Set `terminal_ronic = (1 - δ)·r + δ·kd·(1 - τ)`. In e3 this gives an equity return equal to r to six decimals on all 28 names, with no refusal.
- Name that RONIC in `how`.
- Add a test on a levered base.
- The reference depends only on b, bar and r, so stored runs can be re-annotated offline.

### Q3e-2. Blocking for E3. The own-value exemption does not print `normalized` the way the prompt defines it (both routes).

**Where:** `checks.py:243` and `checks.py:247`. A dict input prints only `[delta_pts, growth]`, as fractions and %. The prompts (`task.py:63`, `task.py:112`) allow "the input's own value"; `normalized` is {year 3–5, baseline, `delta_pts` in percentage points, growth}.

**Measured** (e1, e2b, e7, e8):
- CTBI smoke 2, attempt 2: "normalizing to the median by year 4 with delta of 0 and book growth of 0.04" fails only on `number_not_found (4)`.
- DAR, attempt 2: "…a delta of 0 percentage points" fails only on `number_not_listed (0pp)`. Listing the figure cannot pass either: `_OWN` prints a bare 0.
- "Year 4" appears in the normalized reason in 4 of the 6 real attempts.
- e7, with `delta_pts` 0.5: "0.5 percentage points", "0.5 pp" and "50 basis points" are refused, while "50%", a wrong figure, passes.
- **Prompt trap.** The prompts name inputs "years 1 and 2" and "the year (3, 4 or 5)". "Year-1 and Year-2" made 1, 2 and 4 unlisted figures in smoke 2's first attempt. S1 covers only four-digit years.

**Fix:**
- Print `year` as an integer, and `delta_pts` as "d percentage points" and "100d basis points", with no % forms.
- Make the prompt say "write forecast years in words".
- Add tests on both routes, and bump checks to v9 and the prompts.

### Q3e-3. Should-fix before E3. S2 covers only base inputs, only the first failing check, and at most four figures.

**Where:** `checks.py:396` and `checks.py:657` (the scenario line is fixed text); `checks.py:215-216` (only `chk["support"]`'s class, `bad[:4]`).

**Measured** (raw `attempt_2.json`, e1, e4c):
- **Scenario inputs.** The repair turn got four bare lines, "no supported reason for the scenario's own input". It never saw `bear.roe` `number_not_found (0.1172)`, `bull.roe` `(0.1343)` (V0's minimum and maximum; neither reason cites V0), or `bull.book_growth` `number_not_listed ($5302868k)`. These are 3 of the 6 inputs still unsupported after the repair.
- **The cap and the first check.** `base.roe`'s why named 4 of its 5 unlisted figures (2026 was dropped). `bear.roe` hides `number_not_listed ($6552k, 9171k)` behind its `number_not_found`.
- **The wording invites the wrong fix.** "number_not_listed (X)" reads as "list X". For a figure no cited item prints, listing turns it into `number_not_found`: `base.normalized` (4) and `fade_years` (0.025; 0.115) did exactly that.

**Fix:**
- Give scenario lines their whys.
- Name every failing figure and check, or add "and N more".
- For an unlisted figure that is neither printed nor the input's own value, say "printed by no cited item: remove it or cite an item that prints it".
- Add a test.

### Q3e-4. Should-fix before E3 (pre-existing; revealed by the smoke). The repair turn sees only an input's first failure.

**Where:** `task.py:173` (`v[0]`). The contract failure is written at `checks.py:386-396`, before V3, V3g, issuance, V9 and V10 (`checks.py:405-475`).

**Measured** (e4c):
- `base.long_run_roe` held two failures. The repair turn saw only "number_not_listed (0.115; 2025)", never "V3 unsupported_premium: ROE 0.1150 outside the filed record [0.1172, 0.1343]".
- The model fixed the figures and kept 0.115, and the input stayed unsupported.

**Fix:** one line per failure class per input, each truncated, or the V-check failures first.

### Q3e-5. Should-fix (pre-existing). A false "within the filed range" reason counts as supported, and the memo prints it.

**Where:** `checks.py:49-56` and `checks.py:255-285` (V10 reads only above and below); `memo.py:29`.

**Measured** (e4a):
- Smoke 2 attempt 2, reason 5: "A long-run ROE of 0.115 is within the filed range from 0.1172 to 0.1343". It is `ok`.
- The memo prints it as passing, directly above the V3 line saying 0.1150 is outside that range. E3's coherence bar is 0 incoherent.

**Fix:** V10 refuses "within/inside the range/record" when the input is outside [min, max]; or the memo marks the reasons of an input that fails V3.

### Q3e-6. Should-fix, carriable (pre-existing, 7ae1d92). The own-value forms include roundings, so a misstated filed figure passes.

**Where:** `checks.py:247` (the `:.2f`, `:.0f%`, `:.1f` and `:.0f` forms).

**Measured** (e2c):
- With `base.roe` at 0.125, "The filed return on opening equity was 12% in fiscal 2025" is supported, although Y2025-12-31 prints 12.9%. "0.1" passes the same way.
- A `terminal_g` of 0.025 carries "0.03".

**Fix:** keep only forms equal to the value, plus Q3e-2's forms in points.

### Q3e-7. Note. Annotation noise, dead code and missing tests.

- **O-1 annotates every merged scenario.** One base `terminal_g` of 0.045 gives three `terminal_g_above_anchor` lines; bear and bull do not replace it (e2d).
- **Dead code.** `checks.py:590` and `checks.py:594` are unreachable after Q3d-1.
- **No tests** cover the operating factor check (it works: e2e catches a factor of 1.0 at −6.64% and stub/360 at +0.096%), operating O-1, Q3d-2, or S2 on a scenario.

### Q3e-8. Note. Corrections to the record, and the operating smoke.

- **The LOG row for the CTBI smoke** ("own other inputs (0.115, 0.025, year 4) or a bare year") is wrong on four counts:
  - "year 4" is the input's own value;
  - no bare year remained in attempt 2 (0 of 11 reasons);
  - three scenario inputs failed on V0 figures they did not cite and on a unit the item does not print, and were never named to the model;
  - `long_run_roe` failed V3.
- **The rulings' Q3d-2 reason** ("growth at the cost of capital adds nothing") and the Q3d fix text hold only for δ = 0.
- **S1 alone did not stop bare years.** Counting reasons with an unlisted four-digit year:

  | Attempt | Before the fix | After the fix |
  |---|---|---|
  | First, prompt only (S1: fin.v3 to fin.v4) | 7 of 9 | 5 of 11, including the forbidden example "the 2025 return" |
  | Repair, named figures (S2: v7 to v8) | 5 of 10 | 0 of 11 |

  This is one run each, so it measures neither fix.
- **The operating route at prompt v6 / checks v8 has had no real turn.** The offline replay of DAR's replies shows no engine defect (e5). The coordinator rules whether that meets the smoke rule.
- **There are no CHANGE_REGISTER rows for any m3q prompt or checks version**, although SPEC_m3q §2 says one is added. This predates the diff.

## Fix list

| # | Fix | Blocking | Owner |
|---|---|---|---|
| Q3e-1 | RONIC* = (1−δ)r + δ·kd(1−τ); `how` names it; levered test; correct the ruling and the 5df6b85 statement | **Blocking for B13 evidence on levered operating names** (fix before E3, or re-annotate offline) | coordinator, builder |
| Q3e-2 | `normalized`'s own value prints its year and `delta_pts` in points; forecast years in words; tests on both routes; checks v9 and prompt bumps | **Blocking for E3** | builder |
| Q3e-3 | Scenario repair lines carry the whys; every failing figure and check named; "printed by no cited item" wording | carriable (should-fix before E3) | builder |
| Q3e-4 | The repair message shows each failure class per input | carriable (should-fix before E3) | builder |
| Q3e-5 | V10 covers "within the range"; the memo marks the reasons of an input that fails V3 | carriable; E3 readers told | builder, coordinator |
| Q3e-6 | Own-value forms only at the exact value | carriable | builder |
| Q3e-7 | O-1 only on replaced inputs; remove the dead branch; the missing tests | carriable | builder |
| Q3e-8 | The record corrections; a ruling on the operating smoke; CHANGE_REGISTER rows | carriable (process) | coordinator |

**Verdict: APPROVED WITH CONDITIONS.**
- E3 may run once Q3e-2 is fixed and pinned.
- B13 on levered operating names counts only after Q3e-1.
- Q3e-3 and Q3e-4 are cheap and should go in first. They change the repair turn, not any value.
