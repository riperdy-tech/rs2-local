# Brief R24 step 1: the desk arithmetic audit (Phase 4 revision 24 v2)

## Where and how
- **Repository:** rs2-local. **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-rev24`, branch `review-2026-10/rev24-muse`.
  Work only there.
- **Never:** GPU, model or server; push, merge or deploy; delete files; edit `.env*`; change `config.json`.
- **Commits:** by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q`. There are 42 known failures, plus one timing
  flake (`test_missing_timings_fall_back_to_wall_clock`); no new failure is allowed. Wait for more than 2.5 GB of free memory before the full
  suite.

## Read first
- `stocks-workspace/docs/review_2026-09-22/PHASE_4_REV24_MUSE.md` (v2) and `PHASE_4_AMENDMENTS.md` "Revision 24".
- `rev23/defect_census.md`, especially O2: the operating-to-earnings margin translation, LITE (implied OM_5 352%) and LIND (a long-run margin of
  0).
- The code:
  - `tools/consensus_reference.py` (`margin_rule`, `long_run_value`, `build`, `defaults_desk_args`);
  - `tools/throughcycle_record.py` (`om_L`, `x_L`, `tax_L`, `om_trend`, `om_tc`);
  - `tools/audit_202608/financial_model_tool.py` (the desk: `execute_financial_model` and everything it calls for the long run);
  - `tools/audit_202608/pack_facts.py` (the DEFAULTS).

## The question
Is the long-run arithmetic right **in the desk itself**, independent of what the defaults feed it? The census found O2 in the formula. If the
same translation sits in the desk's own path, no change to the briefing can fix it.

## What to deliver
1. **A trace** (markdown, in your reply) of how each long-run input enters cash flow, in both the **default generator** and the **desk DCF**:
   - the base earnings, years 1–2, the years 3–5 growth;
   - the long-run margin (and the operating-to-earnings translation: where `om_L`, `x_L`, `tax_L` enter and in which code path);
   - the fade years, terminal growth, the return on new investment (RONIC), working capital, excess cash, the discount rate.

   For each: the function and line; the formula as implemented; whether the desk and the default generator share the code (and where they do
   not).
2. **Unit tests** (a new file, `tools/audit_202608/tests/test_rev24_desk_arithmetic.py`), one per input, proving its **intended effect** on cash
   flow and per-share value on a synthetic company, with hand-computed expected values in comments:
   - a higher long-run margin raises value;
   - terminal growth below the discount rate raises value;
   - a higher RONIC lowers the reinvestment charge;
   - more working capital lowers the year-1–5 flows;
   - and so on, for every input.

   Also a test for **monotonicity and no sign flips** across the input's realistic range.
3. **O2 reproduced or cleared:**
   - Build the LITE-like and LIND-like synthetic cases (a small earnings margin against a large operating margin; a gap between the operating
     and earnings margin larger than the earnings margin), plus their saved real facts if they are in the 33 saved baseline packs
     (`rs2-local/ab_reports/consensus/*_2026100[4-6]_*`).
   - Report what the default generator gives and what the desk gives for the same inputs, and whether the desk itself can produce an
     impossible operating margin or a zeroed long-run margin.
4. **Any other arithmetic defect found on the way:** report it with a failing test, and **do not fix it.** The coordinator rules on every fix.

## Deliverable
The commits (tests only, plus any test fixtures), the suite counts before and after, the trace, the O2 finding, and every other defect found,
each with its failing test. Reply as text, with no report file.
