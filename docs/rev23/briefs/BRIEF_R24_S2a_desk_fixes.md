# Brief R24 step 2a: the desk arithmetic fixes, the remaining reference leaks, and the reveal off (Phase 4 revision 24 v2)

## Where and how
- **Repository:** rs2-local. **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-rev24`, branch `review-2026-10/rev24-muse`
  (head `f737115` or later). Work only there.
- **Never:** GPU, model or server; push, merge or deploy; delete files; edit `.env*`; change `config.json`.
- **Commits:** small commits by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q`. Baseline: the 42 known failures plus the
  timing flake; no new failure. Wait for more than 2.5 GB of free memory before the full suite.

## Read first
- `PHASE_4_REV24_MUSE.md` (v2).
- `PHASE_4_AMENDMENTS.md`, "Revision 24" and "Revision 24 step 1" (the audit findings and **the coordinator's rulings 1–6, which you
  implement**).
- The audit tests, `tools/audit_202608/tests/test_rev24_desk_arithmetic.py`: their 8 strict xfails are what you turn into passes.
- The R24.2 build notes in the commits `600be12` and `a8c10b2`, and their tests `test_rev24_stage_a_pack.py` and `test_rev24_stage_b.py`.

## What to build
**1. The analyst-chosen long-run margin (ruling 1).**
- Add the desk input `long_run_margin`: a decimal, the **earnings** margin at the end of the fade, required for a complete run.
- The desk applies it proportionally per scenario: `margin_ratio = long_run_margin / (scenario year-5 earnings ÷ year-5 revenue)`.
- The generator's `margin_ratio` must **no longer reach the desk**. Remove it from `_long_run_inputs` and from `defaults_desk_args`.
- The tool schema (`analyst_tools.TOOLS`) documents the input. It is an analyst judgment with **no default value in the DEFAULTS**; step 2b
  adds the population ranges.
- `margin_rule` stays, for the logged reference benchmark only.
- Tests:
  - the margin path reaches `long_run_margin` at the end of the fade, in Base, Bull and Bear;
  - LITE's and LIND's saved facts with an analyst-style `long_run_margin` (for example 15% and 4%) give a positive long run;
  - a missing `long_run_margin` is refused by name.

**2. D2.** The long-run margin applies whatever the fade length. With fade 0 it is reached in the terminal year. Two explicit rates with
`fade_years` 3 are not dropped. The strict xfails turn into passes.

**3. D3.** Year-5 earnings are always proportional, `E5 = e5 × OE5/oe5`, with or without a reference. A Bear scenario at 35% stays positive.

**4. D4.** With an unlimited terminal RONIC, the reinvestment charge `g/RONIC` fades linearly to 0 over the fade. Value is monotone in the
terminal RONIC up to unlimited, and the price-implied `terminal_ronic` block has no self-made discontinuity.

**5. Annotate, never silent (ruling 5):**
- a `terminal_ronic` below r is valued as r, with the stamp `terminal_ronic_floored_at_r`, in the desk output and the sample record;
- the reference generator stamps `implied_operating_margin_out_of_range` (outside [−0.5, 1.0]) and `long_run_margin_clamped_to_zero`,
  benchmark only.

**6. The remaining reference leaks** (from the R24.2 report):
- the BASE WINDOW CHECK's TTM value ("on the TTM window the consensus path is worth $Y");
- the DEFAULTS `base_window` line's `ttm_value`: omit both;
- lines that **name** the CIV with no number:
  - the `reference_base_b` explanation: reword it as "the fiscal-year owner-earnings base";
  - TASK item 3's "as the CONSENSUS-IMPLIED VALUE does": remove it;
  - the desk's unit note, "x the reference": it now says "x the price".
- **Test:** no `consensus`-path or CIV value, and no CIV name, can be derived from the rebuilt pack text of the 3 saved packs. A grep test for
  the names, plus the parity of the computed facts.

**7. Stage B (the reveal) off.** A config flag `reference_reveal`, default **false**. With it false, `REFERENCE_REVEAL` is never sent, and
`reference_revision` is refused by the desk at all times. Keep the code and its tests, run with the flag true in those tests, and add a test
that the default pipeline never fires it.

**8. `PACK_REVISION` and the history line.** It stays 24 (not yet run anywhere). Append to the revision-24 history line: "desk long_run_margin
(analyst), D2–D4 fixed, reveal off".

## Deliverable
The commits, the suite counts before and after, the 8 former xfails now passing, LITE's and LIND's desk runs with the analyst-style margin
(values and a terminal value above 0), and every judgement call or gap. Reply as text; decide nothing left open.
